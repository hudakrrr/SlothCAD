"""Constraints a new sketch curve implies, as Fusion and FreeCAD apply them while drawing.

FreeCAD's sketcher (``DrawSketchHandler::seekAutoConstraint``) and Fusion's inference add:
an end point that lands on an existing point is made *coincident* with it (or with the origin);
an end point that lands on a curve is made *point on object*; a line drawn within about two degrees
of the horizontal or vertical becomes *horizontal* / *vertical*.
``infer`` returns those as ``(kind, refs)`` pairs; the caller adds them one by one so a conflicting
one can simply be skipped.
"""
import math
import numpy as np
from constraints import Layout, handles, edges, point_ref, line_ref, circle_ref
from geometry import EPS

ANGLE_TOLERANCE = math.radians(2.)
DISTANCE_TOLERANCE = 1e-6
KINDS = ('line', 'arc', 'circle', 'point')


def _new_points(entity):
    kind = entity['kind']
    if kind in ('line', 'arc'):
        return [point_ref(entity['id'], 'a'), point_ref(entity['id'], 'b')]
    if kind == 'circle':
        return [point_ref(entity['id'], 'center')]
    if kind == 'point':
        return [point_ref(entity['id'], 'p')]
    return []


def _segment_distance(point, a, b):
    d = b - a
    length = float(d @ d)
    if length < 1e-18:
        return float(np.linalg.norm(point - a))
    t = min(1., max(0., float((point - a) @ d) / length))
    return float(np.linalg.norm(point - (a + t * d)))


def infer(existing, entity):
    """Constraints implied by ``entity`` (just drawn) against the ``existing`` entities."""
    if entity.get('kind') not in KINDS:
        return []
    layout = Layout(list(existing) + [entity])
    x = layout.x
    found = []
    for ref in _new_points(entity):
        point = layout.point(ref, x)
        if float(np.linalg.norm(point)) < DISTANCE_TOLERANCE:
            found.append(('coincident', [ref, point_ref(None, 'origin')]))
            continue
        target = None
        for other in existing:
            if other.get('projection'):
                continue                     # linked geometry is read-only
            for handle in handles(other):
                if handle.get('point') == 'mid':
                    continue                 # the through point of an arc is not a place to join to
                try:
                    q = layout.point(handle, x)
                except Exception:
                    continue
                if float(np.linalg.norm(point - q)) < DISTANCE_TOLERANCE:
                    target = ('coincident', [ref, handle])
                    break
            if target:
                break
        if target is None:
            for other in existing:
                if other.get('projection') or other['kind'] in ('point',):
                    continue
                for edge in edges(other):
                    try:
                        if edge['kind'] == 'line':
                            a, b = layout.line(edge, x)
                            hit = _segment_distance(point, a, b) < DISTANCE_TOLERANCE
                        else:
                            center, radius = layout.circle(edge, x)
                            hit = abs(float(np.linalg.norm(point - center)) - radius) < DISTANCE_TOLERANCE
                            if hit and other['kind'] == 'arc':
                                from geometry import nearest_on_entity
                                hit = float(np.linalg.norm(nearest_on_entity(other, point) - point)) < DISTANCE_TOLERANCE
                    except Exception:
                        continue
                    if hit:
                        target = ('point_on_object', [ref, edge])
                        break
                if target:
                    break
        if target:
            found.append(target)
    if entity['kind'] == 'line':
        a, b = layout.point(point_ref(entity['id'], 'a'), x), layout.point(point_ref(entity['id'], 'b'), x)
        d = b - a
        if float(np.linalg.norm(d)) > EPS:
            angle = abs(math.atan2(d[1], d[0]))
            if angle < ANGLE_TOLERANCE or math.pi - angle < ANGLE_TOLERANCE:
                found.append(('horizontal', [line_ref(entity['id'])]))
            elif abs(angle - math.pi / 2) < ANGLE_TOLERANCE:
                found.append(('vertical', [line_ref(entity['id'])]))
    return found


def apply(sketch, entity):
    """``sketch`` with the implied constraints added (and the solver run). Conflicts are skipped."""
    from constraints import new_constraint, add_constraint
    import copy
    result = copy.deepcopy(sketch)
    added = 0
    for kind, refs in infer(sketch['entities'][:-1] if sketch['entities'] and sketch['entities'][-1]['id'] == entity['id'] else sketch['entities'], entity):
        try:
            constraint = new_constraint(result, kind, refs)
            result = add_constraint(result, constraint)
            added += 1
        except Exception:
            continue
    return result, added
