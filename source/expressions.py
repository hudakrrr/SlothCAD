"""Restricted CAD expressions in millimeters and degrees; no Python evaluation."""
import ast
import contextlib
import keyword
import math
import operator
import re
import threading
from legacy_model import ModelError

CONSTANTS={'pi':math.pi,'e':math.e,'mm':1.,'cm':10.,'m':1000.,'inch':25.4,'deg':1.,'rad':180/math.pi}
FUNCTIONS={'sqrt':math.sqrt,'abs':abs,'min':min,'max':max,
           'sin':lambda a:math.sin(math.radians(a)), 'cos':lambda a:math.cos(math.radians(a)),
           'tan':lambda a:math.tan(math.radians(a)), 'asin':lambda a:math.degrees(math.asin(a)),
           'acos':lambda a:math.degrees(math.acos(a)), 'atan':lambda a:math.degrees(math.atan(a))}
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow}


def parse(text):
    if not isinstance(text,str) or not text.strip() or len(text)>512:raise ModelError('Enter a dimension expression of at most 512 characters.')
    text=re.sub(r'(?<=[0-9.)])\s*(mm|cm|inch|in|deg|rad|m)\b',lambda m:'*'+('inch' if m[1]=='in' else m[1]),text)
    try:tree=ast.parse(text,mode='eval')
    except SyntaxError as error:raise ModelError('Invalid dimension expression.') from error
    if sum(1 for _ in ast.walk(tree))>96:raise ModelError('Dimension expression is too complex.')
    return tree.body


def evaluate(text,lookup):
    def visit(node,depth=0):
        if depth>24:raise ModelError('Dimension expression is too deeply nested.')
        rec=lambda item:visit(item,depth+1)
        if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)) and not isinstance(node.value,bool):value=float(node.value)
        elif isinstance(node,ast.Name):value=CONSTANTS[node.id] if node.id in CONSTANTS else lookup(node.id)
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):value=rec(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        elif isinstance(node,ast.BinOp) and type(node.op) in OPS:
            a,b=rec(node.left),rec(node.right)
            if isinstance(node.op,ast.Pow) and abs(b)>32:raise ModelError('Expression exponent must be between -32 and 32.')
            value=OPS[type(node.op)](a,b)
        elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS and not node.keywords and 1<=len(node.args)<=8:
            value=FUNCTIONS[node.func.id](*[rec(arg) for arg in node.args])
        else:raise ModelError('Expressions allow numbers, parameter names, arithmetic and supported math functions only.')
        if not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>1e12:raise ModelError('Expression result must be finite and within ±10¹².')
        return float(value)
    try:return visit(parse(text))
    except ModelError:raise
    except (ValueError,TypeError,OverflowError,ZeroDivisionError) as error:raise ModelError('Invalid arithmetic in dimension expression.') from error


def resolve(definitions):
    if not isinstance(definitions,dict) or len(definitions)>500:raise ModelError('Use at most 500 named parameters.')
    for name in definitions:
        if not isinstance(name,str) or not name.isidentifier() or keyword.iskeyword(name) or name in CONSTANTS or name in FUNCTIONS:raise ModelError('Parameter names must be identifiers distinct from units and math functions.')
    values={};stack=[]
    def lookup(name):
        if name in values:return values[name]
        if name not in definitions:raise ModelError('Unknown expression parameter: '+name)
        if name in stack:raise ModelError('Circular parameter dependency: '+' → '.join(stack+[name]))
        if len(stack)>=64:raise ModelError('Parameter dependency chain is too long.')
        stack.append(name);raw=definitions[name]
        value=evaluate(raw,lookup) if isinstance(raw,str) else float(raw) if isinstance(raw,(float,int)) and not isinstance(raw,bool) else None
        if value is None or not math.isfinite(value):raise ModelError('Parameter values must be finite numbers or expressions.')
        values[name]=value;stack.pop();return value
    for name in definitions:lookup(name)
    return values


# ---- document parameters -------------------------------------------------------------------
# A document owns a table of named parameters (name -> number or expression). Whatever is being
# built or solved reads the table through ``active_parameters``: a build installs its document's
# table for its own thread (``using_parameters``); the interface publishes the table of the project
# on screen as the default, so sketch solves started from the UI see the same names.
_LOCAL=threading.local()
_DEFAULT={}


def set_default_parameters(parameters):
    """Table used by threads that are not inside a document build (the interface's own solves)."""
    global _DEFAULT
    _DEFAULT=dict(parameters or {})


def active_parameters():
    value=getattr(_LOCAL,'parameters',None)
    return _DEFAULT if value is None else value


@contextlib.contextmanager
def using_parameters(parameters):
    previous=getattr(_LOCAL,'parameters',None)
    _LOCAL.parameters=dict(parameters or {})
    try:yield
    finally:_LOCAL.parameters=previous


def resolved_parameters(parameters=None):
    """Numeric value of every document parameter (raises ModelError on cycles and bad names)."""
    table=active_parameters() if parameters is None else parameters
    return resolve(dict(table)) if table else {}


def evaluate_with_parameters(text,parameters=None):
    values=resolved_parameters(parameters)
    def lookup(name):
        if name not in values:raise ModelError('Unknown expression parameter: '+name)
        return values[name]
    return evaluate(text,lookup)


def apply_feature_expressions(feature):
    """Set every expression-driven numeric field of a feature from the active parameters.

    ``expressions`` maps a field name to its expression text and ``expression_values`` remembers the
    number that expression last produced. When a field no longer holds that number it was edited by
    hand (a dragged arrow, a typed value), so the expression is dropped and the new value wins.
    """
    expressions=feature.get('expressions')
    if not expressions:return
    if not isinstance(expressions,dict):raise ModelError('Invalid feature expressions.')
    produced=feature.setdefault('expression_values',{})
    values=None
    for field in list(expressions):
        current=feature.get(field)
        if isinstance(current,bool) or not isinstance(current,(int,float)):
            del expressions[field];produced.pop(field,None);continue
        last=produced.get(field)
        if last is not None and abs(float(current)-float(last))>1e-9:
            del expressions[field];produced.pop(field,None);continue
        if values is None:values=resolved_parameters()
        def lookup(name,values=values):
            if name not in values:raise ModelError('Unknown expression parameter: '+name)
            return values[name]
        value=evaluate(expressions[field],lookup)
        feature[field]=value;produced[field]=value
    if not expressions:
        feature.pop('expressions',None);feature.pop('expression_values',None)
