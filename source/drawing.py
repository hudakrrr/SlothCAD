"""Technical drawing sheets: orthographic views with hidden-line removal, written as DXF or SVG.

The kernel's hidden-line algorithm projects the model for each view; visible edges go to the
``VISIBLE`` layer, edges behind other geometry to ``HIDDEN`` (dashed). Views are laid out in
third-angle projection (top above the front view, right of the front view to its right).
"""
import math
import numpy as np
from legacy_model import ModelError

# name -> (direction towards the viewer, direction of the view's X axis)
VIEWS = {
    'front': ((0., -1., 0.), (1., 0., 0.)),
    'back': ((0., 1., 0.), (-1., 0., 0.)),
    'top': ((0., 0., 1.), (1., 0., 0.)),
    'bottom': ((0., 0., -1.), (1., 0., 0.)),
    'right': ((1., 0., 0.), (0., 1., 0.)),
    'left': ((-1., 0., 0.), (0., -1., 0.)),
    'iso': ((1., -1., 1.), (1., 1., 0.)),
}
VIEW_NAMES = tuple(VIEWS)
CURVE_TOLERANCE = 0.02          # mm: how closely curved edges are followed by line segments


def _simplify(points, tolerance):
    """Douglas-Peucker: drop points that lie within ``tolerance`` of the line between their neighbours."""
    if len(points) <= 2:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        worst, index = -1., None
        for i in range(first + 1, last):
            px, py = points[i]
            distance = (abs(dx * (ay - py) - (ax - px) * dy) / length) if length > 1e-12 else math.hypot(px - ax, py - ay)
            if distance > worst:
                worst, index = distance, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def _edge_strokes(edge):
    """One drawing stroke of an edge: a polyline, or a full circle."""
    try:
        length = float(edge.Length())
    except Exception:
        return None
    if length < 1e-6:
        return None
    kind = edge.geomType()
    if kind == 'LINE':
        a, b = edge.startPoint(), edge.endPoint()
        return ('poly', [(a.x, a.y), (b.x, b.y)])
    if kind == 'CIRCLE' and edge.IsClosed():
        center = edge.arcCenter()
        return ('circle', (center.x, center.y), float(edge.radius()))
    count = max(8, min(600, int(math.ceil(length / max(CURVE_TOLERANCE * 25, 0.25)))))
    points = [edge.positionAt(i / count) for i in range(count + 1)]
    return ('poly', _simplify([(p.x, p.y) for p in points], CURVE_TOLERANCE))


def _strokes(compound):
    result = []
    if compound is None or compound.IsNull():
        return result
    import cadquery as cq
    for edge in cq.Shape.cast(compound).Edges():
        stroke = _edge_strokes(edge)
        if stroke is not None:
            result.append(stroke)
    return result


def project_view(shape, name, hidden=True):
    """Visible and hidden strokes of ``shape`` seen from the named direction, in view coordinates."""
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    normal, xdir = VIEWS[name]
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal), gp_Dir(*xdir))))
    algo.Update()
    algo.Hide()
    pieces = HLRBRep_HLRToShape(algo)
    visible = []
    for getter in ('VCompound', 'Rg1LineVCompound', 'OutLineVCompound'):
        visible.extend(_strokes(getattr(pieces, getter)()))
    hidden_strokes = []
    if hidden:
        for getter in ('HCompound', 'Rg1LineHCompound', 'OutLineHCompound'):
            hidden_strokes.extend(_strokes(getattr(pieces, getter)()))
    return visible, hidden_strokes


def _bounds(strokes):
    xs, ys = [], []
    for stroke in strokes:
        if stroke[0] == 'circle':
            (x, y), r = stroke[1], stroke[2]
            xs.extend((x - r, x + r)); ys.extend((y - r, y + r))
        else:
            for x, y in stroke[1]:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _shift(stroke, dx, dy):
    if stroke[0] == 'circle':
        (x, y), r = stroke[1], stroke[2]
        return ('circle', (x + dx, y + dy), r)
    return ('poly', [(x + dx, y + dy) for x, y in stroke[1]])


def layout_views(shape, names, hidden=True):
    """Project every view and place them on one sheet. Returns ``[(name, visible, hidden, bounds)]``."""
    names = [n for n in names if n in VIEWS]
    if not names:
        raise ModelError('Choose at least one view for the drawing.')
    raw = {}
    for name in names:
        visible, hidden_strokes = project_view(shape, name, hidden)
        box = _bounds(visible + hidden_strokes)
        if box is None:
            raise ModelError('The model has no edges to draw in the ' + name + ' view.')
        raw[name] = (visible, hidden_strokes, box)
    biggest = max(max(b[2] - b[0], b[3] - b[1]) for _, _, b in raw.values())
    gap = 10. + .15 * biggest

    def size(name):
        b = raw[name][2]
        return b[2] - b[0], b[3] - b[1]

    anchor = 'front' if 'front' in raw else names[0]
    place = {anchor: (0., 0.)}          # lower-left corner of each view on the sheet
    w0, h0 = size(anchor)

    def put(name, x, y):
        if name in raw and name not in place:
            place[name] = (x, y)
    if 'top' in raw:
        put('top', 0., h0 + gap)
    if 'bottom' in raw:
        put('bottom', 0., -gap - size('bottom')[1])
    if 'right' in raw:
        put('right', w0 + gap, 0.)
    if 'left' in raw:
        put('left', -gap - size('left')[0], 0.)
    if 'back' in raw:
        x = place['right'][0] + size('right')[0] + gap if 'right' in place else w0 + gap
        put('back', x, 0.)
    if 'iso' in raw:
        x = place['right'][0] if 'right' in place else w0 + gap
        y = place['top'][1] if 'top' in place else h0 + gap
        put('iso', x, y)
    for name in names:                  # anything still unplaced goes in a row below
        if name not in place:
            put(name, 0., -2 * gap - 2 * biggest)
    sheet = []
    for name in names:
        visible, hidden_strokes, box = raw[name]
        x, y = place[name]
        dx, dy = x - box[0], y - box[1]
        shifted = [_shift(s, dx, dy) for s in visible]
        shifted_hidden = [_shift(s, dx, dy) for s in hidden_strokes]
        sheet.append((name, shifted, shifted_hidden, (x, y, x + box[2] - box[0], y + box[3] - box[1])))
    return sheet


def _scaled(stroke, scale):
    if stroke[0] == 'circle':
        (x, y), r = stroke[1], stroke[2]
        return ('circle', (x * scale, y * scale), r * scale)
    return ('poly', [(x * scale, y * scale) for x, y in stroke[1]])


def export_dxf(path, shape, names=('front', 'top', 'right'), hidden=True, scale=1., dimensions=True, title=''):
    """Write the views to a DXF file (millimetres, layers VISIBLE / HIDDEN / DIMENSIONS / TEXT)."""
    import ezdxf
    if not (math.isfinite(scale) and scale > 0):
        raise ModelError('The drawing scale must be a positive number.')
    sheet = layout_views(shape, names, hidden)
    document = ezdxf.new('R2010')
    document.units = 4
    if 'DASHED' not in document.linetypes:
        document.linetypes.add('DASHED', pattern=[6.0, 4.0, -2.0], description='Dashed')
    document.layers.new('VISIBLE', dxfattribs={'color': 7})
    document.layers.new('HIDDEN', dxfattribs={'color': 8, 'linetype': 'DASHED'})
    document.layers.new('DIMENSIONS', dxfattribs={'color': 3})
    document.layers.new('TEXT', dxfattribs={'color': 7})
    space = document.modelspace()

    def draw(stroke, layer):
        stroke = _scaled(stroke, scale)
        if stroke[0] == 'circle':
            space.add_circle(stroke[1], stroke[2], dxfattribs={'layer': layer})
        else:
            space.add_lwpolyline(stroke[1], dxfattribs={'layer': layer})
    for name, visible, hidden_strokes, box in sheet:
        for stroke in hidden_strokes:
            draw(stroke, 'HIDDEN')
        for stroke in visible:
            draw(stroke, 'VISIBLE')
        x0, y0, x1, y1 = (v * scale for v in box)
        space.add_text(name.upper(), dxfattribs={'layer': 'TEXT', 'height': max(2.5, .04 * max(x1 - x0, y1 - y0))}).set_placement((x0, y0 - max(8., .1 * (y1 - y0))))
        if dimensions:
            offset = max(6., .08 * max(x1 - x0, y1 - y0))
            space.add_linear_dim(base=(x0, y0 - 2 * offset - 2.5), p1=(x0, y0), p2=(x1, y0), dimstyle='EZDXF', dxfattribs={'layer': 'DIMENSIONS'}).render()
            space.add_linear_dim(base=(x1 + offset, y0), p1=(x1, y0), p2=(x1, y1), angle=90, dimstyle='EZDXF', dxfattribs={'layer': 'DIMENSIONS'}).render()
    lowest = min(box[1] for *_, box in sheet) * scale
    left = min(box[0] for *_, box in sheet) * scale
    label = (title + '  ·  ' if title else '') + f'scale {scale:g}:1' if scale >= 1 else (title + '  ·  ' if title else '') + f'scale 1:{1 / scale:g}'
    space.add_text(label + '  ·  mm', dxfattribs={'layer': 'TEXT', 'height': 3.5}).set_placement((left, lowest - 26))
    document.saveas(str(path))
    return [name for name, *_ in sheet]


def export_svg(path, shape, names=('front', 'top', 'right'), hidden=True, scale=1., title=''):
    """The same sheet as a scalable vector graphic (1 drawing unit = 1 mm)."""
    if not (math.isfinite(scale) and scale > 0):
        raise ModelError('The drawing scale must be a positive number.')
    sheet = layout_views(shape, names, hidden)
    strokes = [(layer, _scaled(s, scale)) for _, visible, hid, _ in sheet for layer, group in (('hidden', hid), ('visible', visible)) for s in group]
    box = _bounds([s for _, s in strokes])
    margin = 12.
    x0, y1 = box[0] - margin, box[3] + margin
    width, height = box[2] - box[0] + 2 * margin, box[3] - box[1] + 2 * margin + 8
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" viewBox="0 0 {width:.3f} {height:.3f}">',
             '<rect width="100%" height="100%" fill="white"/>']

    def flip(x, y):
        return x - x0, y1 - y
    for layer, stroke in strokes:
        style = ('stroke="#222" stroke-width="0.35"' if layer == 'visible' else 'stroke="#888" stroke-width="0.2" stroke-dasharray="3 1.5"')
        if stroke[0] == 'circle':
            (cx, cy), r = stroke[1], stroke[2]
            fx, fy = flip(cx, cy)
            parts.append(f'<circle cx="{fx:.3f}" cy="{fy:.3f}" r="{r:.3f}" fill="none" {style}/>')
        else:
            points = ' '.join('{:.3f},{:.3f}'.format(*flip(x, y)) for x, y in stroke[1])
            parts.append(f'<polyline points="{points}" fill="none" {style}/>')
    from xml.sax.saxutils import escape
    caption = (title + '  ·  ' if title else '') + (f'scale {scale:g}:1' if scale >= 1 else f'scale 1:{1 / scale:g}') + '  ·  mm'
    parts.append(f'<text x="{margin:.1f}" y="{height - 4:.1f}" font-size="4" font-family="sans-serif" fill="#222">{escape(caption)}</text></svg>')
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(parts))
    return [name for name, *_ in sheet]
