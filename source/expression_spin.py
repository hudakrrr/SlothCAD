"""A number box that also accepts expressions such as ``plate_width / 2 + 3 mm``.

The box behaves exactly like a ``QDoubleSpinBox`` for plain numbers. When the text is an
expression it is evaluated with the document's parameters; the box then shows the expression
(not the number) until it is replaced by a number again, and ``expression`` holds the text so the
owner can store it next to the value.
"""
import re
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox

_NUMBER = re.compile(r'^\s*[+-]?(\d+[.,]?\d*|[.,]\d+)([eE][+-]?\d+)?\s*$')
_EXPRESSION_CHARS = re.compile(r'^[\w\s.,+\-*/^()°]+$', re.UNICODE)


class ExpressionSpinBox(QDoubleSpinBox):
    def __init__(self, resolver=None, parent=None):
        super().__init__(parent)
        self.expression = None
        self.resolver = resolver          # callable(text) -> float, raising on any problem
        self.setToolTip('')

    # -- text <-> value ---------------------------------------------------------------------
    def evaluate(self, text):
        """The value of an expression text, or None when it is not (yet) a valid expression."""
        if self.resolver is None or not text.strip() or not _EXPRESSION_CHARS.match(text):
            return None
        try:
            value = float(self.resolver(text.strip().replace('^', '**')))
        except Exception:
            return None
        return value

    def validate(self, text, pos):
        state = super().validate(text, pos)
        if isinstance(state, tuple):
            state, text, pos = state
        if state == QValidator.State.Invalid and text.strip() and _EXPRESSION_CHARS.match(text):
            # Typing an expression: "L", "L/" and "L/2" all have to be accepted on the way.
            state = QValidator.State.Acceptable if self.evaluate(text) is not None else QValidator.State.Intermediate
        return state, text, pos

    def valueFromText(self, text):
        if _NUMBER.match(text) or self.resolver is None:
            self.expression = None
            return super().valueFromText(text)
        value = self.evaluate(text)
        if value is None:
            return self.value()
        self.expression = text.strip().replace('^', '**')
        return value

    def textFromValue(self, value):
        if self.expression:
            return self.expression
        return super().textFromValue(value)

    def fixup(self, text):
        return text

    # -- programmatic use ----------------------------------------------------------------------
    def setValue(self, value):
        # A different number set from code (an arrow dragged in the viewport) replaces the expression.
        if self.expression and abs(float(value) - self.value()) > 1e-9:
            self.expression = None
        super().setValue(value)

    def set_expression(self, text, value):
        """Show ``text`` as the content of the box without emitting a change."""
        self.blockSignals(True)
        try:
            self.expression = text
            super().setValue(value)
            self.lineEdit().setText(text)
        finally:
            self.blockSignals(False)
        self.setToolTip(f'= {value:g}')


class SidedSpinBox(QDoubleSpinBox):
    """A size shown as a positive number whose stored value carries a side (a shell's -inward/+outward).

    The value the program stores is signed; the box shows and accepts the magnitude, and ``sign``
    (set from a Side choice next to it) decides which way the stored value points.
    """
    def __init__(self, sign=-1, parent=None):
        super().__init__(parent)
        self.sign = -1 if sign < 0 else 1

    def textFromValue(self, value):
        return super().textFromValue(abs(value))

    def valueFromText(self, text):
        return self.sign * abs(super().valueFromText(text.lstrip('-+ ')))

    def validate(self, text, pos):
        state = super().validate(text.lstrip('-+'), pos)
        return (state[0], text, pos) if isinstance(state, tuple) else (state, text, pos)

    def stepBy(self, steps):
        self.setValue(self.value() + self.sign * steps * self.singleStep())
