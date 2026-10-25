"""Preview outlines that do not need the CAD kernel.

The live outline of an extrusion used to build a real solid for every selected profile just
to read its edges back (about a second for a sketch with a few dozen loops, all of it Python
work that also starves the user interface). For the common case, a plain distance extrusion
of sketch profiles, the outline is simply every profile loop at the bottom and at the top
plus vertical edges at the loop's corners, which numpy produces in milliseconds.

Anything else (tapers, through-all / to-object extents, body faces, nested-region profiles)
returns ``None`` and the caller falls back to the exact kernel result.
"""
import math
import numpy as np
from geometry import EPS, axes, profile_geometry, sample

CORNER_DEGREES = 12.      # a vertex turning more than this gets a vertical edge
SMOOTH_VERTICALS = 4      # a loop without corners (a circle) still gets this many


def _source_ids(source, sketch):
    """(outer ids, [hole ids]) of a sketch-profile source, or ``None`` when it cannot be resolved here.

    Sources picked in the workspace are "nested" profiles: their holes are the regions found
    in the sketch now (the same recovery the kernel path performs), not a stored list.
    """
    if source.get('profile_mode') == 'nested':
        from profile_references import recover
        region = recover(dict(source), sketch)    # a copy: recovery would otherwise rewrite the source
        if region is None:
            return None
        return list(region['entities']), [list(hole) for hole in region['holes']]
    return list(source.get('entities', [])), [list(hole) for hole in source.get('holes', [])]


def _lookup(sketch):
    table = {e['id']: e for e in sketch['entities']}
    table.update({e['id']: e for e in profile_geometry(sketch)})
    return table


def _loop(table, ids):
    """Closed polygon (without the repeated end point) of one profile loop, like region_points."""
    if not ids:
        raise ValueError('empty loop')
    first = table[ids[0]]
    kind = first['kind']
    if len(ids) == 1 and (kind in ('rectangle', 'circle', 'polygon', 'ellipse', 'slot')
                          or (kind == 'spline' and (first.get('closed') or math.dist(first['points'][0], first['points'][-1]) < EPS))):
        points = np.asarray(sample(first), float)
    else:
        remaining = [table[i] for i in ids]
        points = sample(remaining.pop(0)).tolist()
        while remaining:
            for index, entity in enumerate(remaining):
                pts = sample(entity).tolist()
                if math.dist(points[-1], pts[0]) < EPS:
                    break
                if math.dist(points[-1], pts[-1]) < EPS:
                    pts = pts[::-1]
                    break
            else:
                raise ValueError('disconnected profile')
            points.extend(pts[1:])
            remaining.pop(index)
        points = np.asarray(points, float)
    if len(points) > 1 and np.allclose(points[0], points[-1], atol=1e-9):
        points = points[:-1]
    if len(points) < 3:
        raise ValueError('degenerate loop')
    return points


def _corner_indices(points):
    previous = points - np.roll(points, 1, axis=0)
    following = np.roll(points, -1, axis=0) - points
    cross = previous[:, 0] * following[:, 1] - previous[:, 1] * following[:, 0]
    dot = (previous * following).sum(axis=1)
    turning = np.degrees(np.abs(np.arctan2(cross, dot)))
    corners = np.nonzero(turning > CORNER_DEGREES)[0]
    if len(corners):
        return corners
    count = min(SMOOTH_VERTICALS, len(points))
    return np.unique(np.linspace(0, len(points) - 1, count, dtype=int))


def prism_lines(feature, sources, sketches, frames):
    """Outline polylines (each an (n, 3) array) of the extrusion, or ``None`` when the kernel is needed."""
    try:
        if feature.get('extent', 'distance') != 'distance':
            return None
        if abs(float(feature.get('taper', 0) or 0)) > 1e-12:
            return None
        direction = feature.get('direction', 'one side')
        if direction not in ('one side', 'symmetric'):
            return None
        depth = float(feature.get('depth', 10))
        offset = float(feature.get('offset', 0) or 0)
        if abs(depth) < 1e-9 or not math.isfinite(depth) or not math.isfinite(offset):
            return None
        low, high = (offset - depth / 2, offset + depth / 2) if direction == 'symmetric' else (offset, offset + depth)
        tables = {}
        lines = []
        for source in sources:
            if not isinstance(source, dict) or source.get('type') != 'sketch':
                return None
            sketch = sketches.get(source.get('sketch'))
            frame = frames.get(source.get('sketch'))
            if sketch is None or frame is None or frame.get('spatial'):
                return None
            table = tables.get(sketch['id'])
            if table is None:
                table = tables[sketch['id']] = (_lookup(sketch), axes(frame))
            lookup, (o, u, v, n) = table
            resolved = _source_ids(source, sketch)
            if resolved is None:
                return None
            ids, holes = resolved
            if not ids or any(i not in lookup or lookup[i].get('construction') for i in ids):
                return None
            loops = [ids] + holes
            for loop_ids in loops:
                if any(i not in lookup or lookup[i].get('construction') for i in loop_ids):
                    return None
                points = _loop(lookup, loop_ids)
                planar = o + points[:, 0, None] * u + points[:, 1, None] * v
                bottom = planar + n * low
                top = planar + n * high
                lines.append(np.vstack((bottom, bottom[:1])))
                lines.append(np.vstack((top, top[:1])))
                for index in _corner_indices(points):
                    lines.append(np.array([bottom[index], top[index]]))
        return lines or None
    except Exception:
        return None


def source_loops(sources, sketches, frames):
    """For each sketch-profile source: ``(normal, [(ring (n,3) closed, ...)], center)`` in world space.

    The first ring of a source is its outer boundary, the following ones its holes. ``center``
    is the length-weighted centre of the outer boundary (what the kernel reports as the
    wire's centre). Returns ``None`` when any source needs the kernel (body faces, spatial
    sketches, nested-region profiles), so the caller can fall back.
    """
    try:
        tables = {}
        result = []
        for source in sources:
            if not isinstance(source, dict) or source.get('type') != 'sketch':
                return None
            sketch = sketches.get(source.get('sketch'))
            frame = frames.get(source.get('sketch'))
            if sketch is None or frame is None or frame.get('spatial'):
                return None
            table = tables.get(sketch['id'])
            if table is None:
                table = tables[sketch['id']] = (_lookup(sketch), axes(frame))
            lookup, (o, u, v, n) = table
            resolved = _source_ids(source, sketch)
            if resolved is None:
                return None
            ids, holes = resolved
            if not ids or any(i not in lookup or lookup[i].get('construction') for i in ids):
                return None
            rings = []
            for loop_ids in [ids] + holes:
                if any(i not in lookup or lookup[i].get('construction') for i in loop_ids):
                    return None
                points = _loop(lookup, loop_ids)
                world = o + points[:, 0, None] * u + points[:, 1, None] * v
                rings.append(np.vstack((world, world[:1])))
            outer = rings[0]
            segments = outer[1:] - outer[:-1]
            lengths = np.linalg.norm(segments, axis=1)
            total = float(lengths.sum())
            midpoints = (outer[1:] + outer[:-1]) / 2
            center = (midpoints * lengths[:, None]).sum(axis=0) / total if total > 1e-12 else outer.mean(axis=0)
            result.append((n, rings, center))
        return result or None
    except Exception:
        return None

