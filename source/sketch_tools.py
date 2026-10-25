"""Sketch editing tools that Fusion and FreeCAD have beside Trim: Extend, Offset and Move / Rotate / Scale.

Each function takes the sketch's entity list and returns a replacement list; none of them touch the
sketch itself, so the interface can validate, preview and undo them like the other sketch edits.
"""
import copy
import math
import numpy as np
from geometry import entity, arc_data, vec, sample, transform_entity, EPS, validate_entity
from legacy_model import ModelError
import trim as T

TAU = 2 * math.pi
FAR = 1e6


# ---- extend ------------------------------------------------------------------------------------
def _other_parts(entities, skip):
    parts = []
    for index, e in enumerate(entities):
        if index == skip:
            continue
        try:
            parts.extend(T.primitives(e))
        except Exception:
            continue
    return parts


def extend_entity(entities, index, point):
    """Lengthen the line or arc at ``index`` from the end nearest ``point`` to the next curve it meets."""
    if not 0 <= index < len(entities):
        raise ModelError('Click a line or arc near the end you want to extend.')
    target = entities[index]
    kind = target['kind']
    point = vec(point)
    others = _other_parts(entities, index)
    if kind == 'line':
        a, b = vec(target['a']), vec(target['b'])
        end_is_b = np.linalg.norm(b - point) <= np.linalg.norm(a - point)
        origin, tip = (a, b) if end_is_b else (b, a)
        direction = tip - origin
        length = float(np.linalg.norm(direction))
        if length < EPS:
            raise ModelError('This line has no length to extend.')
        direction /= length
        ray = dict(kind='line', a=tip, b=tip + direction * FAR)
        best = None
        for part in others:
            for q in T.intersections(ray, part):
                distance = float((q - tip) @ direction)
                if distance > 1e-7 and (best is None or distance < best[0]):
                    best = (distance, q)
        if best is None:
            raise ModelError('Nothing lies in the way: this end does not reach another curve.')
        result = copy.deepcopy(entities)
        result[index]['b' if end_is_b else 'a'] = best[1].tolist()
        validate_entity(result[index])
        return result
    if kind == 'arc':
        center, radius, start, sweep = arc_data(target)
        a, b = vec(target['a']), vec(target['b'])
        end_is_b = np.linalg.norm(b - point) <= np.linalg.norm(a - point)
        direction = 1. if sweep > 0 else -1.
        if not end_is_b:
            direction = -direction
        theta_end = start + sweep if end_is_b else start
        circle = dict(kind='curve', center=center, radius=radius, angle=0., sweep=TAU, closed=True)
        best = None
        for part in others:
            for q in T.intersections(circle, part):
                theta = math.atan2(q[1] - center[1], q[0] - center[0])
                delta = ((theta - theta_end) * direction) % TAU
                if 1e-7 < delta < TAU - 1e-7 and (best is None or delta < best[0]):
                    best = (delta, q)
        if best is None:
            raise ModelError('Nothing lies in the way: this end does not reach another curve.')
        # Grow the sweep by the angle travelled and rebuild the three points of the arc.
        new_sweep = abs(sweep) + best[0]
        if new_sweep >= TAU - 1e-6:
            raise ModelError('The extension would close the arc into a full circle. Use a circle instead.')
        sign = 1. if sweep > 0 else -1.
        first = start if end_is_b else start - sign * best[0]
        last = first + sign * new_sweep
        at = lambda t: (center + radius * np.array([math.cos(t), math.sin(t)])).tolist()
        result = copy.deepcopy(entities)
        result[index].update(a=at(first), mid=at((first + last) / 2), b=at(last))
        validate_entity(result[index])
        return result
    raise ModelError('Extend works on lines and arcs.')


# ---- offset ------------------------------------------------------------------------------------
JOIN_TOLERANCE = 1e-6


def _segments(entities):
    """Directed pieces ``dict(kind, a, b, center, radius, ccw)`` of the lines and arcs of ``entities``."""
    pieces, circles = [], []
    for e in entities:
        kind = e['kind']
        if kind == 'point':
            continue
        if kind == 'circle':
            circles.append((vec(e['center']), float(e['radius']), bool(e.get('construction'))))
        elif kind == 'line':
            pieces.append(dict(kind='line', a=vec(e['a']), b=vec(e['b']), construction=bool(e.get('construction'))))
        elif kind == 'arc':
            c, r, start, sweep = arc_data(e)
            pieces.append(dict(kind='arc', a=vec(e['a']), b=vec(e['b']), center=c, radius=r, ccw=sweep > 0, construction=bool(e.get('construction'))))
        elif kind in ('rectangle', 'polygon'):
            points = sample(e)[:-1]
            for p, q in zip(points, np.roll(points, -1, axis=0)):
                pieces.append(dict(kind='line', a=np.asarray(p, float), b=np.asarray(q, float), construction=bool(e.get('construction'))))
        elif kind == 'slot':
            from geometry import slot_parts
            for part, points in slot_parts(e):
                if part == 'line':
                    pieces.append(dict(kind='line', a=np.asarray(points[0], float), b=np.asarray(points[1], float), construction=False))
                else:
                    c, r, start, sweep = arc_data(dict(a=points[0].tolist(), mid=points[1].tolist(), b=points[2].tolist()))
                    pieces.append(dict(kind='arc', a=np.asarray(points[0], float), b=np.asarray(points[2], float), center=c, radius=r, ccw=sweep > 0, construction=False))
        else:
            raise ModelError('Offset works on lines, arcs, circles, rectangles, polygons and slots.')
    return pieces, circles


def _chains(pieces):
    """Group pieces into end-to-end chains, each oriented along its travel direction."""
    remaining = list(range(len(pieces)))
    chains = []
    def near(p, q):
        return float(np.linalg.norm(p - q)) < 1e-5
    while remaining:
        # start at a free end when there is one, so open chains are walked from their start
        start = None
        for i in remaining:
            ends = (pieces[i]['a'], pieces[i]['b'])
            for end_index, end in enumerate(ends):
                if not any(j != i and (near(pieces[j]['a'], end) or near(pieces[j]['b'], end)) for j in remaining):
                    start = (i, end_index == 1)
                    break
            if start:
                break
        if start is None:
            start = (remaining[0], False)
        index, reverse = start
        chain = [_oriented(pieces[index], reverse)]
        remaining.remove(index)
        while True:
            tail = chain[-1]['b']
            follow = next(((j, near(pieces[j]['b'], tail)) for j in remaining if near(pieces[j]['a'], tail) or near(pieces[j]['b'], tail)), None)
            if follow is None:
                break
            chain.append(_oriented(pieces[follow[0]], follow[1]))
            remaining.remove(follow[0])
        chains.append(chain)
    return chains


def _oriented(piece, reverse):
    if not reverse:
        return dict(piece)
    flipped = dict(piece)
    flipped['a'], flipped['b'] = piece['b'], piece['a']
    if piece['kind'] == 'arc':
        flipped['ccw'] = not piece['ccw']
    return flipped


def _signed_area(chain):
    points = []
    for piece in chain:
        if piece['kind'] == 'line':
            points.append(piece['a'])
        else:
            c = piece['center']
            a0 = math.atan2(*(piece['a'] - c)[::-1])
            a1 = math.atan2(*(piece['b'] - c)[::-1])
            span = (a1 - a0) % TAU if piece['ccw'] else -((a0 - a1) % TAU)
            for t in np.linspace(0, 1, 12, endpoint=False):
                points.append(c + piece['radius'] * np.array([math.cos(a0 + span * t), math.sin(a0 + span * t)]))
    p = np.asarray(points)
    return .5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def _shifted(piece, left):
    """The piece moved ``left`` to its left (negative: to its right)."""
    if piece['kind'] == 'line':
        d = piece['b'] - piece['a']
        n = np.array([-d[1], d[0]]) / float(np.linalg.norm(d))
        return dict(piece, a=piece['a'] + n * left, b=piece['b'] + n * left)
    radius = piece['radius'] - left if piece['ccw'] else piece['radius'] + left
    if radius <= 1e-9:
        raise ModelError('The offset is larger than an arc of the outline. Use a smaller distance.')
    c = piece['center']
    def move(p):
        direction = (p - c) / float(np.linalg.norm(p - c))
        return c + direction * radius
    return dict(piece, a=move(piece['a']), b=move(piece['b']), radius=radius)


def _extended(piece):
    if piece['kind'] == 'line':
        d = piece['b'] - piece['a']
        d = d / float(np.linalg.norm(d))
        return dict(kind='line', a=piece['a'] - d * FAR, b=piece['b'] + d * FAR)
    return dict(kind='curve', center=piece['center'], radius=piece['radius'], angle=0., sweep=TAU, closed=True)


def _join(first, second, corner):
    """Where two offset pieces meet: their curves' intersection nearest the original corner."""
    best = None
    for q in T.intersections(_extended(first), _extended(second)):
        distance = float(np.linalg.norm(q - corner))
        if best is None or distance < best[0]:
            best = (distance, q)
    return None if best is None else best[1]


def _arc_entity(piece, construction):
    c, r = piece['center'], piece['radius']
    a0 = math.atan2(*(piece['a'] - c)[::-1])
    a1 = math.atan2(*(piece['b'] - c)[::-1])
    span = (a1 - a0) % TAU if piece['ccw'] else -((a0 - a1) % TAU)
    if abs(span) < 1e-9:
        span = TAU if piece['ccw'] else -TAU
    mid = c + r * np.array([math.cos(a0 + span / 2), math.sin(a0 + span / 2)])
    flags = {'construction': True} if construction else {}
    return entity('arc', a=piece['a'].tolist(), mid=mid.tolist(), b=piece['b'].tolist(), **flags)


def offset_entities(entities, indices, distance, flip=False):
    """New curves at ``distance`` from the selected ones (the originals are kept).

    A closed outline grows for a positive distance (``flip`` makes it shrink); for an open chain the
    distance is to its left in the direction it was drawn, ``flip`` puts it on the right. Corners
    stay sharp. Lines, arcs, circles, rectangles, polygons and slots can be offset.
    """
    distance = float(distance)
    if not math.isfinite(distance) or abs(distance) < 1e-9:
        raise ModelError('Enter an offset distance other than zero.')
    chosen = [entities[i] for i in indices if 0 <= i < len(entities) and entities[i]['kind'] != 'point']
    if not chosen:
        raise ModelError('Select the curves to offset.')
    pieces, circles = _segments(chosen)
    created = []
    for center, radius, construction in circles:
        new_radius = radius + (-distance if flip else distance)
        if new_radius <= 1e-9:
            raise ModelError('The offset is larger than the circle. Use a smaller distance.')
        flags = {'construction': True} if construction else {}
        created.append(entity('circle', center=center.tolist(), radius=new_radius, **flags))
    for chain in _chains(pieces):
        closed = len(chain) > 1 and float(np.linalg.norm(chain[0]['a'] - chain[-1]['b'])) < 1e-5
        if closed:
            # Positive distance grows the outline: to the right of a counter-clockwise loop.
            counter = _signed_area(chain) > 0
            left = -distance if counter else distance
        else:
            left = distance
        if flip:
            left = -left
        shifted = [_shifted(piece, left) for piece in chain]
        count = len(shifted)
        for i in range(count if closed else count - 1):
            j = (i + 1) % count
            corner = chain[i]['b']
            point = _join(shifted[i], shifted[j], corner)
            if point is None:           # parallel or concentric pieces: keep their own ends and bridge the gap below
                continue
            shifted[i]['b'] = point
            shifted[j]['a'] = point
        previous = None
        for piece in shifted:
            if piece['kind'] == 'line':
                if float(np.linalg.norm(piece['b'] - piece['a'])) < 1e-9:
                    continue
                flags = {'construction': True} if piece['construction'] else {}
                created.append(entity('line', a=piece['a'].tolist(), b=piece['b'].tolist(), **flags))
            else:
                created.append(_arc_entity(piece, piece['construction']))
        # A connecting segment where two neighbouring pieces were parallel and did not meet.
        for i in range(count if closed else count - 1):
            j = (i + 1) % count
            gap = shifted[j]['a'] - shifted[i]['b']
            if float(np.linalg.norm(gap)) > 1e-6:
                created.append(entity('line', a=shifted[i]['b'].tolist(), b=shifted[j]['a'].tolist()))
    if not created:
        raise ModelError('The offset produced no geometry.')
    for e in created:
        validate_entity(e)
    return created


# ---- move / rotate / scale -----------------------------------------------------------------------
def scale_entity(source, factor, center):
    """A copy of ``source`` scaled uniformly about ``center`` (new identity)."""
    factor = float(factor)
    if not math.isfinite(factor) or factor <= 0:
        raise ModelError('The scale factor must be a positive number.')
    c = vec(center)
    point = lambda p: (c + factor * (vec(p) - c)).tolist()
    kind = source['kind']
    flags = {k: copy.deepcopy(source[k]) for k in ('construction', 'range', 'basis', 'degree', 'knots', 'weights', 'weight') if k in source}
    if kind == 'line':
        return entity(kind, a=point(source['a']), b=point(source['b']), **flags)
    if kind == 'arc':
        return entity(kind, a=point(source['a']), mid=point(source['mid']), b=point(source['b']), **flags)
    if kind == 'circle':
        return entity(kind, center=point(source['center']), radius=source['radius'] * factor, **flags)
    if kind == 'rectangle':
        return entity(kind, center=point(source['center']), width=source['width'] * factor, height=source['height'] * factor, **flags)
    if kind == 'polygon':
        return entity(kind, points=[point(p) for p in source['points']], **flags)
    if kind == 'ellipse':
        return entity(kind, center=point(source['center']), major=point(source['major']), minor_radius=source['minor_radius'] * factor, **flags)
    if kind == 'slot':
        return entity(kind, a=point(source['a']), b=point(source['b']), width=source['width'] * factor, **flags)
    if kind == 'spline':
        return entity(kind, points=[point(p) for p in source['points']], closed=source.get('closed', False), **flags)
    if kind == 'conic':
        return entity(kind, a=point(source['a']), control=point(source['control']), b=point(source['b']), **flags)
    if kind == 'point':
        return entity(kind, p=point(source['p']), **flags)
    raise ModelError('Unsupported sketch entity.')


def transform_selection(entities, indices, mode, copy_it=False, dx=0., dy=0., angle=0., factor=1., center=(0., 0.)):
    """Move, rotate (degrees, counter-clockwise) or scale the selected entities.

    Returns ``(entities, moved_ids)``. With ``copy_it`` the originals stay and new entities are
    added; otherwise each selected entity keeps its identity so it can be edited further.
    """
    chosen = [i for i in indices if 0 <= i < len(entities)]
    if not chosen:
        raise ModelError('Select the geometry to transform.')
    if mode == 'move':
        if not (math.isfinite(dx) and math.isfinite(dy)) or (abs(dx) < 1e-12 and abs(dy) < 1e-12):
            raise ModelError('Enter a distance to move.')
        shift = np.array([dx, dy], float)
        def make(e):
            if e['kind'] == 'rectangle':        # a pure move keeps a rectangle a rectangle
                moved = copy.deepcopy(e)
                moved['id'] = entity('point')['id']
                moved['center'] = (vec(e['center']) + shift).tolist()
                return moved
            return transform_entity(e, np.eye(2), shift)
    elif mode == 'rotate':
        if not math.isfinite(angle) or abs(angle) < 1e-12:
            raise ModelError('Enter an angle other than zero.')
        t = math.radians(angle)
        matrix = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        c = vec(center)
        make = lambda e: transform_entity(e, matrix, c - matrix @ c)
    elif mode == 'scale':
        make = lambda e: scale_entity(e, factor, center)
    else:
        raise ModelError('Choose move, rotate or scale.')
    result = copy.deepcopy(entities)
    moved = []
    for i in chosen:
        new = make(entities[i])
        validate_entity(new)
        if copy_it:
            result.append(new)
            moved.append(new['id'])
        else:
            new['id'] = entities[i]['id']
            result[i] = new
            moved.append(new['id'])
    return result, moved
