"""Text boxes for sketches: document-style layout converted to ordinary polygon outlines.

A text box is a rectangle in the sketch plane. The text inside it is laid out like in a
word processor (font, size in points, bold/italic/underline, horizontal and vertical
alignment, line spacing, word wrap) and turned into closed polygon loops, so the result
can be extruded, mirrored and patterned like any other sketch geometry.

The outlines come from Qt's font engine (``QPainterPath.addText``): that is the same font
the panel shows, it needs no extra font library and is fast enough for a live preview.
"""
import math
import os
from dataclasses import dataclass, field, replace
import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath

PT_MM = 25.4 / 72.0          # one typographic point in millimetres
OUTLINE_PX = 160.0           # em size in which outlines are generated (precision, not scale)
HALIGN = ('left', 'center', 'right', 'justify')
VALIGN = ('top', 'middle', 'bottom')
SIMPLIFY_MM = 0.003          # collinear points closer than this to the outline are dropped
MAX_CHARACTERS = 4000


@dataclass
class TextStyle:
    text: str = 'Text'
    font: str = 'Liberation Sans'
    size_pt: float = 24.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    halign: str = 'left'
    valign: str = 'top'
    spacing: float = 1.0      # line spacing factor
    wrap: bool = True

    def validated(self):
        if self.halign not in HALIGN:
            raise ValueError('Unknown horizontal alignment.')
        if self.valign not in VALIGN:
            raise ValueError('Unknown vertical alignment.')
        if not (self.size_pt > 0 and math.isfinite(self.size_pt)):
            raise ValueError('Text size must be positive.')
        if not (self.spacing > 0 and math.isfinite(self.spacing)):
            raise ValueError('Line spacing must be positive.')
        if len(self.text) > MAX_CHARACTERS:
            raise ValueError('Text is too long (limit: 4000 characters).')
        return self

    @classmethod
    def from_dict(cls, data):
        fields = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in dict(data).items() if key in fields})

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def size_mm(self):
        return self.size_pt * PT_MM


@dataclass
class TextLayout:
    loops: list = field(default_factory=list)   # closed polygons, (n, 2) arrays in sketch units
    width: float = 0.0                           # widest line, mm
    height: float = 0.0                          # block height, mm
    lines: int = 0
    overflow_x: bool = False                     # a line is wider than the box
    overflow_y: bool = False                     # the block is taller than the box


def make_font(style):
    ensure_fonts()
    font = QFont(style.font)
    font.setPixelSize(int(OUTLINE_PX))
    font.setBold(bool(style.bold))
    font.setItalic(bool(style.italic))
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferOutline)
    return font


def _wrap(paragraph, metrics, limit, wrap):
    """Greedy word wrap. Returns lists of words; a single over-long word stays on its line."""
    words = paragraph.split(' ')
    if not wrap or limit <= 0:
        return [words]
    lines, current = [], []
    for word in words:
        trial = ' '.join(current + [word])
        if current and metrics.horizontalAdvance(trial) > limit:
            lines.append(current)
            current = [word]
        else:
            current.append(word)
    lines.append(current)
    return lines


def _simplify(points, tolerance):
    """Douglas-Peucker for a closed ring (returned without the repeated first point)."""
    pts = np.asarray(points, float)
    if len(pts) <= 3:
        return pts
    # Split the ring at its two farthest-apart anchors so both halves are open polylines.
    first = 0
    second = int(np.argmax(np.linalg.norm(pts - pts[first], axis=1)))
    if second == first:
        return pts

    def reduce(chain):
        if len(chain) < 3:
            return chain
        a, b = chain[0], chain[-1]
        d = b - a
        length = float(np.hypot(*d))
        if length < 1e-12:
            distances = np.linalg.norm(chain - a, axis=1)
        else:
            distances = np.abs(d[0] * (chain[:, 1] - a[1]) - d[1] * (chain[:, 0] - a[0])) / length
        index = int(np.argmax(distances))
        if distances[index] <= tolerance:
            return np.vstack((a, b))
        left = reduce(chain[:index + 1])
        right = reduce(chain[index:])
        return np.vstack((left[:-1], right))

    one = reduce(pts[first:second + 1])
    two = reduce(np.vstack((pts[second:], pts[:1])))
    ring = np.vstack((one[:-1], two[:-1]))
    return ring if len(ring) >= 3 else pts


def layout_text(style, rect):
    """Lay ``style.text`` out inside ``rect = (x0, y0, x1, y1)`` (sketch coordinates)."""
    style = style.validated()
    x0, y0, x1, y1 = (float(v) for v in rect)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    result = TextLayout()
    text = style.text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.strip():
        return result
    font = make_font(style)
    metrics = QFontMetricsF(font)
    scale = style.size_mm / OUTLINE_PX                    # mm per outline unit
    box_w = (x1 - x0) / scale
    box_h = (y1 - y0) / scale
    ascent, descent = metrics.ascent(), metrics.descent()
    pitch = (ascent + descent + metrics.leading()) * style.spacing

    lines = []                                            # (words, ends_paragraph)
    for paragraph in text.split('\n'):
        wrapped = _wrap(paragraph, metrics, box_w, style.wrap)
        for index, words in enumerate(wrapped):
            lines.append((words, index == len(wrapped) - 1))
    count = len(lines)
    block_h = (count - 1) * pitch + ascent + descent
    if style.valign == 'top':
        top = 0.0
    elif style.valign == 'middle':
        top = (box_h - block_h) / 2
    else:
        top = box_h - block_h

    path = QPainterPath()
    widest = 0.0
    for index, (words, ends_paragraph) in enumerate(lines):
        baseline = top + ascent + index * pitch
        sentence = ' '.join(words)
        width = metrics.horizontalAdvance(sentence)
        widest = max(widest, width)
        justify = style.halign == 'justify' and not ends_paragraph and len(words) > 1 and width < box_w
        if style.halign == 'right':
            start = box_w - width
        elif style.halign == 'center':
            start = (box_w - width) / 2
        else:
            start = 0.0
        if justify:
            natural = sum(metrics.horizontalAdvance(w) for w in words)
            gap = (box_w - natural) / (len(words) - 1)
            cursor = 0.0
            for word in words:
                if word:
                    path.addText(QPointF(cursor, baseline), font, word)
                cursor += metrics.horizontalAdvance(word) + gap
            line_x, line_w = 0.0, box_w
        else:
            if sentence:
                path.addText(QPointF(start, baseline), font, sentence)
            line_x, line_w = start, width
        if style.underline and sentence.strip() and line_w > 0:
            thickness = max(metrics.lineWidth(), OUTLINE_PX / 18.0)
            y = baseline + max(metrics.underlinePos(), thickness * 0.8)
            bar = QPainterPath()
            bar.addRect(QRectF(line_x, y, line_w, thickness))
            path = path.united(bar)
    result.lines = count
    result.width = widest * scale
    result.height = block_h * scale
    result.overflow_x = widest > box_w + 1e-6
    result.overflow_y = block_h > box_h + 1e-6

    tolerance = SIMPLIFY_MM / scale
    loops = []
    for polygon in path.toSubpathPolygons():
        pts = np.array([[p.x(), p.y()] for p in polygon], float)
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        pts = _simplify(pts, tolerance)
        if len(pts) < 3:
            continue
        # Outline space is y-down with the first baseline below the box top; sketch space is y-up.
        sketch = np.column_stack((x0 + pts[:, 0] * scale, y1 - pts[:, 1] * scale))
        area = 0.5 * float(np.sum(sketch[:, 0] * np.roll(sketch[:, 1], -1) - np.roll(sketch[:, 0], -1) * sketch[:, 1]))
        if abs(area) < 1e-8:
            continue
        loops.append(sketch)
    result.loops = loops
    return result


def polygon_entities(layout, construction=False):
    """Sketch entities (closed polygons) for a laid-out text."""
    from geometry import entity
    items = []
    for loop in layout.loops:
        item = entity('polygon', points=[[float(x), float(y)] for x, y in loop])
        if construction:
            item['construction'] = True
        items.append(item)
    return items


_FONT_DIRS = (
    os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'),
    '/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.local/share/fonts'),
    '/System/Library/Fonts',
)
_PREFERRED_FILES = ('LiberationSans-Regular.ttf', 'DejaVuSans.ttf', 'arial.ttf', 'segoeui.ttf', 'NotoSans-Regular.ttf')
_fonts_checked = False


def ensure_fonts():
    """Load a few font files when Qt's font database is empty (offscreen/minimal platforms)."""
    global _fonts_checked
    if _fonts_checked:
        return
    _fonts_checked = True
    from PySide6.QtGui import QFontDatabase
    if QFontDatabase.families():
        return
    found = []
    for directory in _FONT_DIRS:
        if not os.path.isdir(directory):
            continue
        for root, _, files in os.walk(directory):
            for name in files:
                if name in _PREFERRED_FILES:
                    found.append(os.path.join(root, name))
            if len(found) >= 8:
                break
    if not found:
        for directory in _FONT_DIRS:
            for root, _, files in os.walk(directory) if os.path.isdir(directory) else ():
                found += [os.path.join(root, n) for n in files if n.lower().endswith(('.ttf', '.otf'))][:3]
                if found:
                    break
            if found:
                break
    for path in found[:8]:
        QFontDatabase.addApplicationFont(path)


def system_fonts():
    from PySide6.QtGui import QFontDatabase
    ensure_fonts()
    return sorted(QFontDatabase.families())


def default_font():
    """A sans-serif family that exists on this machine (the preferred one first)."""
    families = set(system_fonts())
    for name in ('Liberation Sans', 'DejaVu Sans', 'Arial', 'Segoe UI', 'Noto Sans', 'Helvetica'):
        if name in families:
            return name
    return next(iter(sorted(families)), 'Sans Serif')


def with_defaults(style):
    """``style`` with the font replaced by an installed one when needed."""
    families = set(system_fonts())
    return replace(style, font=style.font if style.font in families else default_font())
