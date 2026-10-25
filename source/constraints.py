"""Persistent sketch relations and a transactional, component-local solver.

References use stable entity IDs, never display indices. Solver output is a
new sketch: failed additions, numeric edits, and drags leave input untouched.
"""
import copy
import json
import math
import numpy as np
from scipy.optimize import least_squares
from geometry import identifier, validate_entity, EPS
from legacy_model import ModelError

LABELS={'coincident':'Coincidence','horizontal':'Horizontal','vertical':'Vertical',
        'parallel':'Parallel','perpendicular':'Perpendicular','dimension':'Dimension',
        'equal':'Equality','symmetry':'Symmetry','tangent':'Tangency',
        'fix':'Fix','unfix':'Unfix','midpoint':'Midpoint','concentric':'Concentric',
        'collinear':'Collinear','point_on_object':'Point on object'}


class ConstraintConflict(ModelError):
    def __init__(self, constraints, message=None):
        self.constraint_ids=[c['id'] for c in constraints]
        names=[LABELS.get(c['kind'],c['kind'])+(f" ({c['value']:g})" if 'value' in c else '') for c in constraints]
        super().__init__(message or 'Conflicting constraints: '+', '.join(names)+'. The last valid sketch was kept.')


def point_ref(entity_id, point):return dict(entity=entity_id,kind='point',point=point)
def line_ref(entity_id, edge=None):
    result=dict(entity=entity_id,kind='line')
    if edge is not None:result['edge']=int(edge)
    return result
def circle_ref(entity_id):return dict(entity=entity_id,kind='circle')


def handles(e):
    """Editable point references, including rectangle corners and spline controls."""
    result=[]
    for field in ('a','b','mid','center','major','control','p'):
        if field in e:result.append(point_ref(e['id'],field))
    if e['kind']=='rectangle':result.extend(point_ref(e['id'],f'corner:{i}') for i in range(4))
    elif e['kind'] in ('polygon','spline'):result.extend(point_ref(e['id'],f'points:{i}') for i in range(len(e['points'])))
    return result


def edges(e):
    if e['kind']=='line':return [line_ref(e['id'])]
    if e['kind']=='rectangle':return [line_ref(e['id'],i) for i in range(4)]
    if e['kind']=='polygon':return [line_ref(e['id'],i) for i in range(len(e['points']))]
    if e['kind'] in ('circle','arc'):return [circle_ref(e['id'])]
    return []


class Layout:
    def __init__(self,entities):
        self.entities={e['id']:e for e in entities};self.fields={};values=[];lower=[]
        for e in entities:
            fields={};start=len(values)
            for key in ('a','b','mid','center','major','control','p'):
                if key in e:
                    fields[key]=slice(len(values),len(values)+2);values.extend(e[key]);lower.extend([-np.inf]*2)
            if 'points' in e:
                fields['points']=[]
                for point in e['points']:
                    fields['points'].append(slice(len(values),len(values)+2));values.extend(point);lower.extend([-np.inf]*2)
            for key in ('radius','width','height','minor_radius'):
                if key in e:
                    fields[key]=len(values);values.append(e[key]);lower.append(EPS*2)
            fields['_slice']=slice(start,len(values));self.fields[e['id']]=fields
        self.x=np.asarray(values,dtype=float);self.lower=np.asarray(lower,dtype=float)
        if not np.isfinite(self.x).all():raise ModelError('Sketch parameters must be finite.')

    def point(self,ref,x):
        if ref.get('entity') is None and ref.get('point')=='origin':return np.zeros(2)
        id_=ref.get('entity');key=ref.get('point','')
        if id_ not in self.fields:raise ModelError('A constraint references geometry that was removed.')
        fields=self.fields[id_]
        if key.startswith('corner:') and self.entities[id_]['kind']=='rectangle':
            i=int(key.split(':')[1]);signs=((-1,-1),(1,-1),(1,1),(-1,1))
            if not 0<=i<4:raise ModelError('Invalid rectangle corner reference.')
            return x[fields['center']]+np.asarray(signs[i])*np.array([x[fields['width']],x[fields['height']]])/2
        if key.startswith('points:'):
            try:return x[fields['points'][int(key.split(':')[1])]]
            except (KeyError,IndexError,ValueError):raise ModelError('Invalid sketch point reference.')
        if key not in fields or not isinstance(fields[key],slice):raise ModelError('Choose a sketch endpoint or center.')
        return x[fields[key]]

    def line(self,ref,x):
        id_=ref.get('entity');e=self.entities.get(id_)
        if e is None:raise ModelError('A constraint references geometry that was removed.')
        if e['kind']=='line':return self.point(point_ref(id_,'a'),x),self.point(point_ref(id_,'b'),x)
        if e['kind'] in ('rectangle','polygon'):
            n=4 if e['kind']=='rectangle' else len(e['points']);i=ref.get('edge')
            if not isinstance(i,int) or not 0<=i<n:raise ModelError('Choose a straight sketch edge.')
            prefix='corner:' if e['kind']=='rectangle' else 'points:'
            return self.point(point_ref(id_,prefix+str(i)),x),self.point(point_ref(id_,prefix+str((i+1)%n)),x)
        raise ModelError('This constraint requires straight lines or polygon edges.')

    def circle(self,ref,x):
        """Centre and radius of a circle, or of the full circle an arc lies on."""
        id_=ref.get('entity');e=self.entities.get(id_)
        if e is None or e['kind'] not in ('circle','arc'):raise ModelError('This constraint requires a circle or an arc.')
        fields=self.fields[id_]
        if e['kind']=='arc':return circumcircle(x[fields['a']],x[fields['mid']],x[fields['b']])
        return x[fields['center']],float(x[fields['radius']])

    def unpack(self,x):
        result=copy.deepcopy(list(self.entities.values()))
        for e in result:
            for key,index in self.fields[e['id']].items():
                if key=='_slice':continue
                if key=='points':e[key]=[x[i].tolist() for i in index]
                elif isinstance(index,slice):e[key]=x[index].tolist()
                else:e[key]=float(x[index])
            validate_entity(e)
        return result


def circumcircle(a,m,b):
    """Centre and radius of the circle through three points (differentiable, safe when collinear)."""
    d1=m-a;d2=b-a;cross=d1[0]*d2[1]-d1[1]*d2[0];s1=float(d1@d1);s2=float(d2@d2)
    if abs(cross)<1e-12:
        centre=(a+b)/2;return centre,float(np.linalg.norm(b-a))/2
    centre=a+np.array([(d2[1]*s1-d1[1]*s2)/(2*cross),(d1[0]*s2-d2[0]*s1)/(2*cross)])
    return centre,float(np.linalg.norm(a-centre))


def arc_orientation(layout,e_id,x):
    """Signed area of an arc's start/through/end triangle: it only changes sign when the arc would flip."""
    a,m,b=(layout.point(point_ref(e_id,k),x) for k in ('a','mid','b'))
    return float((m[0]-a[0])*(b[1]-a[1])-(m[1]-a[1])*(b[0]-a[0]))


def reference_value(entities,ref):
    layout=Layout(entities)
    if ref['kind']=='point':return layout.point(ref,layout.x)
    if ref['kind']=='line':return layout.line(ref,layout.x)
    if ref['kind']=='circle':return layout.circle(ref,layout.x)
    raise ModelError('Unsupported sketch reference.')


def _direction(layout,ref,x):
    a,b=layout.line(ref,x);d=b-a;length=float(np.linalg.norm(d))
    return a,d/max(length,EPS),length


def _cross(u,v):return float(u[0]*v[1]-u[1]*v[0])
def _signed_distance(point,a,u):return _cross(u,point-a)


def fixed_values(layout,ref,x):
    if ref['kind']=='entity':return x[layout.fields[ref['entity']]['_slice']]
    if ref['kind']=='point':return layout.point(ref,x)
    if ref['kind']=='circle':
        center,r=layout.circle(ref,x);return np.r_[center,r]
    return np.asarray(layout.line(ref,x)).ravel()


def dimension_measure(layout,c,x):
    measured=dict(c,value=0.)
    result=residual(layout,measured,x)[0]
    if c.get('mode')=='angle':
        _,u,_=_direction(layout,c['refs'][0],x)
        if len(c['refs'])==1:return math.degrees(math.atan2(u[1],u[0]))
        _,v,_=_direction(layout,c['refs'][1],x);return math.degrees(math.atan2(_cross(u,v),float(u@v)))
    return float(result)


def resolve_dimensions(sketch):
    from expressions import resolve,active_parameters
    # Document parameters come first; sketch parameters and dimension names of this sketch shadow them.
    result=copy.deepcopy(sketch);definitions=dict(active_parameters());definitions.update(result.get('parameters') or {});layout=Layout(result['entities'])
    named=set()
    for c in result.get('constraints',[]):
        if c['kind']!='dimension':continue
        if c.get('reference'):c['value']=dimension_measure(layout,c,layout.x)
        if c.get('name'):
            if c['name'] in (result.get('parameters') or {}) or c['name'] in named:raise ModelError('Duplicate dimension or parameter name: '+c['name'])
            named.add(c['name']);definitions[c['name']]=c.get('expression') if c.get('expression') else c['value']
    values=resolve(definitions)
    for c in result.get('constraints',[]):
        if c.get('expression'):
            if c.get('reference'):raise ModelError('Reference dimensions are measured and cannot drive expressions.')
            from expressions import evaluate
            c['value']=values[c['name']] if c.get('name') else evaluate(c['expression'],lambda name:_parameter(values,name))
    return result


def _parameter(values,name):
    if name not in values:raise ModelError('Unknown expression parameter: '+name)
    return values[name]


def constraint_status(sketch):
    """Jacobian rank per connected component, without a large dense global solve."""
    sketch=resolve_dimensions(sketch);validate_definitions(sketch)
    items={e['id']:e for e in sketch['entities']};parent={id_:id_ for id_ in items}
    def find(key):
        while parent[key]!=key:key=parent[key]
        return key
    active=[c for c in sketch.get('constraints',[]) if not c.get('reference')]
    for c in active:
        ids=[r['entity'] for r in c['refs'] if r.get('entity') in items]
        for id_ in ids[1:]:parent[find(id_)]=find(ids[0])
    groups={}
    for id_ in items:groups.setdefault(find(id_),[]).append(items[id_])
    dof=0;rank=0;redundant=0;solved=[]
    for entities in groups.values():
        layout=Layout(entities);ids=set(layout.entities);relations=[c for c in active if any(r.get('entity') in ids for r in c['refs'])]
        # An arc stores start/through/end points, but sliding the through point along
        # the arc does not change its shape. Remove that gauge freedom so a fully
        # dimensioned arc can report "fully constrained".
        arcs=[e['id'] for e in entities if e['kind']=='arc']
        if not relations:dof+=len(layout.x)-len(arcs);continue
        def gauge(x):
            values=[]
            for id_ in arcs:
                a,m,b=(layout.point(point_ref(id_,k),x) for k in ('a','mid','b'))
                values.append(float(np.linalg.norm(m-a)-np.linalg.norm(m-b)))
            return np.asarray(values,dtype=float)
        def evaluate(x):return np.concatenate([np.atleast_1d(residual(layout,c,x)) for c in relations]+[gauge(x)])
        baseline=evaluate(layout.x);jac=np.empty((len(baseline),len(layout.x)))
        for j in range(len(layout.x)):
            h=1e-6*max(1.,abs(layout.x[j]));x=layout.x.copy();x[j]+=h;jac[:,j]=(evaluate(x)-baseline)/h
        r=int(np.linalg.matrix_rank(jac,tol=max(1e-7,float(np.linalg.norm(jac,ord=2))*1e-7)))
        rank+=r;dof+=len(layout.x)-r;redundant+=max(0,len(baseline)-r)
        if len(layout.x)-r==0:solved.extend(e['id'] for e in entities)
    return dict(degrees_of_freedom=dof,rank=rank,redundant_equations=redundant,fully_constrained=dof==0,constrained_entities=solved)


def unfix(sketch,refs):
    result=copy.deepcopy(sketch);ids={r.get('entity') for r in refs}
    result['constraints']=[c for c in result.get('constraints',[]) if not(c['kind']=='fix' and any(r.get('entity') in ids for r in c['refs']))]
    return result

def residual(layout,c,x):
    kind=c['kind'];refs=c['refs'];types=[r['kind'] for r in refs]
    if kind=='fix':return fixed_values(layout,refs[0],x)-np.asarray(c['fixed'],float)
    if kind=='midpoint':
        a,b=layout.line(refs[1],x);return layout.point(refs[0],x)-(a+b)/2
    if kind=='concentric':return layout.circle(refs[0],x)[0]-layout.circle(refs[1],x)[0]
    if kind=='collinear':
        a,u,l1=_direction(layout,refs[0],x);b,v,l2=_direction(layout,refs[1],x)
        return [_cross(u,v)*min(l1,l2),_signed_distance(b,a,u)]
    if kind in ('coincident','point_on_object'):
        p=layout.point(refs[0],x)
        if types[1]=='point':return p-layout.point(refs[1],x)
        if types[1]=='line':
            a,u,length=_direction(layout,refs[1],x)
            if kind=='point_on_object':
                distance=float((p-a)@u);return [_signed_distance(p,a,u),min(0.,distance)+max(0.,distance-length)]
            return [_signed_distance(p,a,u)]
        center,r=layout.circle(refs[1],x);return [np.linalg.norm(p-center)-r]
    if kind in ('horizontal','vertical'):
        a,b=layout.line(refs[0],x);return [b[1]-a[1] if kind=='horizontal' else b[0]-a[0]]
    if kind in ('parallel','perpendicular'):
        _,u,l1=_direction(layout,refs[0],x);_,v,l2=_direction(layout,refs[1],x)
        scale=max(EPS,min(l1,l2))
        return [float(_cross(u,v) if kind=='parallel' else u@v)*scale]
    if kind=='equal':
        if types[0]=='line':return [_direction(layout,refs[0],x)[2]-_direction(layout,refs[1],x)[2]]
        return [layout.circle(refs[0],x)[1]-layout.circle(refs[1],x)[1]]
    if kind=='symmetry':
        p,q=[layout.point(r,x) for r in refs[:2]];a,u,_=_direction(layout,refs[2],x)
        return [_signed_distance((p+q)/2,a,u),float((q-p)@u)]
    if kind=='tangent':
        if types==['circle','circle']:
            (c1,r1),(c2,r2)=layout.circle(refs[0],x),layout.circle(refs[1],x);gap=float(np.linalg.norm(c1-c2))
            return [gap-(r1+r2) if c['side']==1 else gap-abs(r1-r2)]
        line,circle=refs;a,u,_=_direction(layout,line,x);center,r=layout.circle(circle,x)
        return [_signed_distance(center,a,u)-c['side']*r]
    if kind=='dimension':
        mode=c.get('mode','length');value=c['value']
        if mode in ('radius','diameter'):return [layout.circle(refs[0],x)[1]*(2 if mode=='diameter' else 1)-value]
        if mode=='length':return [_direction(layout,refs[0],x)[2]-value]
        if mode in ('distance','dx','dy'):
            p,q=[layout.point(r,x) for r in refs];d=q-p
            return [float(np.linalg.norm(d) if mode=='distance' else d[0 if mode=='dx' else 1])-value]
        if mode=='angle':
            _,u,l1=_direction(layout,refs[0],x)
            if len(refs)==1:angle=math.atan2(u[1],u[0]);scale=l1
            else:
                _,v,l2=_direction(layout,refs[1],x);angle=math.atan2(_cross(u,v),float(u@v));scale=min(l1,l2)
            delta=(angle-math.radians(value)+math.pi)%(2*math.pi)-math.pi
            return [delta*max(scale,EPS)]
    raise ModelError('Unknown sketch constraint.')


def validate_definitions(sketch):
    constraints=sketch.get('constraints',[])
    if not isinstance(constraints,list):raise ModelError('Sketch constraints must be a list.')
    if len({c.get('id') for c in constraints if isinstance(c,dict)})!=len(constraints):raise ModelError('Invalid or duplicate constraint ID.')
    layout=Layout(sketch['entities'])
    for c in constraints:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'] or c.get('kind') not in LABELS or not isinstance(c.get('refs'),list):raise ModelError('Invalid sketch constraint.')
        refs=c['refs']
        if any(not isinstance(r,dict) or r.get('kind') not in ('point','line','circle','entity') for r in refs):raise ModelError('Invalid constraint reference.')
        types=[r['kind'] for r in refs];kind=c['kind'];valid=False
        if kind=='fix':valid=len(types)==1 and types[0] in ('entity','point','line','circle') and isinstance(c.get('fixed'),list) and np.asarray(c['fixed']).shape==fixed_values(layout,refs[0],layout.x).shape and np.isfinite(np.asarray(c['fixed'],float)).all()
        elif kind=='midpoint':valid=types==['point','line']
        elif kind=='concentric':valid=types==['circle','circle']
        elif kind=='collinear':valid=types==['line','line']
        elif kind=='point_on_object':valid=len(types)==2 and types[0]=='point' and types[1] in ('line','circle')
        elif kind=='coincident':valid=len(types)==2 and types[0]=='point' and types[1] in ('point','line','circle')
        elif kind in ('horizontal','vertical'):valid=types==['line']
        elif kind in ('parallel','perpendicular'):valid=types==['line','line']
        elif kind=='equal':valid=types in (['line','line'],['circle','circle'])
        elif kind=='symmetry':valid=types==['point','point','line']
        elif kind=='tangent':valid=types in (['line','circle'],['circle','circle']) and c.get('side') in (-1,1)
        elif kind=='dimension':
            mode=c.get('mode');expected={'length':[['line']],'radius':[['circle']],'diameter':[['circle']],
                'distance':[['point','point']],'dx':[['point','point']],'dy':[['point','point']], 'angle':[['line'],['line','line']]}
            valid=types in expected.get(mode,[]) and isinstance(c.get('value'),(int,float)) and not isinstance(c.get('value'),bool) and math.isfinite(c['value'])
            if valid and not c.get('reference') and mode in ('length','radius','diameter','distance') and c['value']<=EPS:valid=False
        if not valid:raise ModelError('Choose geometry compatible with this constraint.')
        for ref in refs:
            if ref['kind']=='entity':fixed_values(layout,ref,layout.x)
            else:getattr(layout,ref['kind'])(ref,layout.x)
    return layout


def validate_constraints(sketch):
    if not sketch.get('constraints'):return
    layout=validate_definitions(sketch)
    failed=[c for c in sketch['constraints'] if not c.get('reference') and np.max(np.abs(residual(layout,c,layout.x)))>1e-6]
    if failed:raise ConstraintConflict(failed)


def new_constraint(sketch,kind,refs,value=None,mode=None,reference=False,expression=None,name=None):
    refs=copy.deepcopy(refs)
    if kind=='fix':refs=[dict(kind='entity',entity=r['entity']) if r['kind'] in ('line','circle') else r for r in refs]
    required=1 if kind in ('horizontal','vertical','fix','unfix') else 3 if kind=='symmetry' else 2
    if kind=='dimension':
        if len(refs) not in (1,2):raise ModelError('Pick one edge/circle or two points/edges for a dimension.')
    elif len(refs)!=required:raise ModelError(f'{LABELS.get(kind,kind)} requires {required} selected references.')
    if kind=='tangent' and refs[0]['kind']=='circle' and refs[1]['kind']=='line':refs.reverse()
    if kind=='coincident' and refs[0]['kind']!='point':refs.reverse()
    c=dict(id=identifier(),kind=kind,refs=refs)
    if kind=='fix':c['fixed']=fixed_values(Layout(sketch['entities']),refs[0],Layout(sketch['entities']).x).tolist()
    if kind=='dimension':
        c.update(value=float(value),mode=mode)
        if reference:c['reference']=True
        if expression:c['expression']=expression
        # Every new dimension has an editable, stable expression name.
        occupied={item.get('name') for item in sketch.get('constraints',[])}|set(sketch.get('parameters') or {});n=1
        while f'd{n}' in occupied:n+=1
        c['name']=name or f'd{n}'
    if kind=='tangent':
        layout=Layout(sketch['entities'])
        if refs[0]['kind']=='circle':
            (c1,r1),(c2,r2)=layout.circle(refs[0],layout.x),layout.circle(refs[1],layout.x);gap=float(np.linalg.norm(c1-c2))
            c['side']=1 if abs(gap-(r1+r2))<=abs(gap-abs(r1-r2)) else -1
        else:
            a,u,_=_direction(layout,refs[0],layout.x);center,_=layout.circle(refs[1],layout.x)
            c['side']=1 if _signed_distance(center,a,u)>=0 else -1
    candidate=copy.deepcopy(sketch);candidate.setdefault('constraints',[]).append(c);candidate=resolve_dimensions(candidate);c=candidate['constraints'][-1];validate_definitions(candidate)
    return c


SPARSE_FROM=150      # variables; below this a dense Jacobian is faster and exactly as before


def solve(sketch,targets=None,seeds=None,strict_targets=False,max_nfev=100):
    """Preserve hard relations while moving free geometry toward soft drag targets."""
    sketch=resolve_dimensions(sketch);validate_definitions(sketch);targets=targets or [];all_constraints=[c for c in sketch.get('constraints',[]) if not c.get('reference')]
    active=set(seeds or [r.get('entity') for c in all_constraints for r in c['refs']])
    active.update(t['ref'].get('entity') for t in targets);active.discard(None)
    while True:
        expanded=active|{r.get('entity') for c in all_constraints if any(r.get('entity') in active for r in c['refs']) for r in c['refs']}
        expanded.discard(None)
        if expanded==active:break
        active=expanded
    selected=[e for e in sketch['entities'] if e['id'] in active];layout=Layout(selected);x0=layout.x
    constraints=[c for c in all_constraints if any(r.get('entity') in active for r in c['refs'])]
    if not len(x0):return copy.deepcopy(sketch)
    if not constraints:
        # Unconstrained moves must land exactly on the snapped target.
        x=x0.copy()
        for target in targets:
            ref=target['ref'];fields=layout.fields[ref['entity']];value=target['value']
            if ref['kind']=='parameters':x[fields['_slice']]=value
            elif ref['kind']=='circle':x[fields['radius']]=float(value)
            elif ref['kind']=='point':
                # A rectangle corner changes its center and size together.
                if ref.get('point','').startswith('corner:'):
                    index=int(ref['point'].split(':')[1]);opposite=layout.point(point_ref(ref['entity'],'corner:'+str((index+2)%4)),x)
                    target=np.asarray(value,dtype=float);x[fields['center']]=(target+opposite)/2
                    x[fields['width']]=abs(float(target[0]-opposite[0]));x[fields['height']]=abs(float(target[1]-opposite[1]))
                else:
                    point=ref['point']
                    index=fields['points'][int(point.split(':')[1])] if point.startswith('points:') else fields[point]
                    x[index]=value
        replacement={e['id']:e for e in layout.unpack(x)};result=copy.deepcopy(sketch)
        result['entities']=[replacement.get(e['id'],copy.deepcopy(e)) for e in sketch['entities']]
        return resolve_dimensions(result)
    line_refs={json.dumps(r,sort_keys=True):r for c in constraints for r in c['refs'] if r['kind']=='line'}
    # An arc is stored by three points; letting the through point slide past an end point would
    # silently turn the arc into its complement, so each arc keeps the orientation it started with.
    arc_signs={e['id']:(1. if arc_orientation(layout,e['id'],x0)>=0 else -1.) for e in selected if e['kind']=='arc'}
    def hard(x):
        pieces=[np.asarray(residual(layout,c,x)).ravel() for c in constraints]
        pieces.extend(np.array([max(0.,EPS*10-sign*arc_orientation(layout,id_,x))]) for id_,sign in arc_signs.items())
        # Collapsing a line is not a valid way to satisfy incompatible direction
        # relations. Keep referenced segments nonzero during the solve itself.
        pieces.extend(np.array([max(0.,EPS*10-_direction(layout,r,x)[2])]) for r in line_refs.values())
        if strict_targets:pieces.extend(target_residual(t,x) for t in targets)
        return np.concatenate(pieces) if pieces else np.empty(0)
    def target_residual(t,x):
        ref=t['ref'];kind=ref['kind'];value=np.asarray(t['value'])
        if kind=='point':return layout.point(ref,x)-value
        if kind=='circle':return np.atleast_1d(layout.circle(ref,x)[1]-float(value))
        if kind=='parameters':return x[layout.fields[ref['entity']]['_slice']]-value
        raise ModelError('Unsupported sketch drag target.')
    def objective(x):
        pieces=[hard(x)*1000.,(x-x0)*(.01 if targets else .001)]
        if not strict_targets:pieces.extend(target_residual(t,x) for t in targets)
        return np.concatenate(pieces)
    # Big sketches: every residual depends on only a few entities, so the finite-difference
    # Jacobian is computed in column groups (a handful of evaluations instead of one per variable).
    options={}
    hard_options={}
    if len(x0)>=SPARSE_FROM:
        spans={id_:(f['_slice'].start,f['_slice'].stop) for id_,f in layout.fields.items()}
        def columns(entity_ids):
            return sorted({k for id_ in entity_ids if id_ in spans for k in range(*spans[id_])})
        rows=[]
        for c in constraints:
            rows.extend([columns({r.get('entity') for r in c['refs']})]*int(np.asarray(residual(layout,c,x0)).size))
        rows.extend(columns([id_]) for id_ in arc_signs)
        rows.extend(columns([r.get('entity')]) for r in line_refs.values())
        if strict_targets:
            for t in targets:rows.extend([columns([t['ref'].get('entity')])]*int(np.asarray(target_residual(t,x0)).size))
        def sparsity(entries):
            from scipy.sparse import lil_matrix
            matrix=lil_matrix((len(entries),len(x0)),dtype=int)
            for row,cols in enumerate(entries):
                if cols:matrix[row,cols]=1
            return matrix
        hard_options['jac_sparsity']=sparsity(rows)
        full=list(rows)+[[k] for k in range(len(x0))]
        if not strict_targets:
            for t in targets:full.extend([columns([t['ref'].get('entity')])]*int(np.asarray(target_residual(t,x0)).size))
        options['jac_sparsity']=sparsity(full)
    answer=least_squares(objective,x0,bounds=(layout.lower,np.inf),method='trf',
                         ftol=1e-10,xtol=1e-10,gtol=1e-10,max_nfev=max_nfev,**options)
    x=answer.x
    # Project the small remaining weighted residual back onto the exact relation
    # manifold. Cursor goals are deliberately soft; dimensions are never relaxed.
    if len(hard(x)) and np.max(np.abs(hard(x)))>1e-9:
        x=least_squares(hard,x,bounds=(layout.lower,np.inf),method='trf',ftol=1e-12,
                        xtol=1e-12,gtol=1e-12,max_nfev=max_nfev,**hard_options).x
    if len(hard(x)) and np.max(np.abs(hard(x)))>1e-7:
        failed=[c for c in constraints if np.max(np.abs(residual(layout,c,x)))>1e-7]
        # Name the constraints whose removal makes the rest solvable: those are the real conflict.
        def feasible(subset):
            def partial(y):
                pieces=[np.asarray(residual(layout,c,y)).ravel() for c in subset]
                pieces.extend(np.array([max(0.,EPS*10-_direction(layout,r,y)[2])]) for r in line_refs.values())
                pieces.extend(np.array([max(0.,EPS*10-sign*arc_orientation(layout,id_,y))]) for id_,sign in arc_signs.items())
                return np.concatenate(pieces) if pieces else np.empty(0)
            if not len(partial(x0)):return True
            try:
                answer=least_squares(partial,x0,bounds=(layout.lower,np.inf),method='trf',ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=60)
            except Exception:return False
            return float(np.max(np.abs(answer.fun)))<=1e-7
        culprits=[c for c in (failed or constraints)[:12] if feasible([k for k in constraints if k is not c])]
        raise ConstraintConflict(culprits or failed or constraints,'This edit conflicts with driving constraints. The last valid sketch was kept.' if strict_targets else None)
    replacement={e['id']:e for e in layout.unpack(x)};result=copy.deepcopy(sketch)
    result['entities']=[replacement.get(e['id'],copy.deepcopy(e)) for e in sketch['entities']]
    return resolve_dimensions(result)


def add_constraint(sketch,constraint):
    signature=lambda c:json.dumps({k:v for k,v in c.items() if k not in ('id','name')},sort_keys=True)
    if any(signature(c)==signature(constraint) for c in sketch.get('constraints',[])):raise ModelError('This constraint already exists.')
    candidate=copy.deepcopy(sketch);candidate.setdefault('constraints',[]).append(copy.deepcopy(constraint))
    return solve(candidate,seeds=[r.get('entity') for r in constraint['refs']])


def drag(sketch,ref,position,start=None):
    layout=Layout(sketch['entities']);kind=ref['kind']
    if kind=='entity':
        id_=ref['entity'];sl=layout.fields[id_]['_slice'];values=layout.x[sl].copy()
        offset=np.asarray(position)-np.asarray(start)
        for key,index in layout.fields[id_].items():
            indices=index if key=='points' else [index]
            if key=='_slice':continue
            for item in indices:
                if isinstance(item,slice):values[item.start-sl.start:item.stop-sl.start]+=offset
        target=dict(ref=dict(entity=id_,kind='parameters'),value=values)
    elif kind=='circle':
        center,_=layout.circle(ref,layout.x);target=dict(ref=ref,value=max(EPS*2,float(np.linalg.norm(np.asarray(position)-center))))
    else:target=dict(ref=ref,value=position)
    return solve(sketch,[target],seeds=[ref['entity']],max_nfev=70)


def edit_entity(sketch,entity):
    candidate=copy.deepcopy(sketch);candidate['entities']=[copy.deepcopy(entity) if e['id']==entity['id'] else e for e in candidate['entities']]
    layout=Layout(candidate['entities']);id_=entity['id']
    target=dict(ref=dict(entity=id_,kind='parameters'),value=layout.x[layout.fields[id_]['_slice']].tolist())
    return solve(candidate,[target],seeds=[id_],strict_targets=True)


def retain_constraints(sketch,entities):
    """Drop only references to deleted/replaced handles after trim or deletion."""
    candidate=copy.deepcopy(sketch);candidate['entities']=copy.deepcopy(entities);kept=[]
    for c in candidate.get('constraints',[]):
        test=dict(candidate,constraints=[c])
        try:validate_definitions(test)
        except ModelError:continue
        kept.append(c)
    candidate['constraints']=kept
    return solve(candidate)

