"""Fast, cached tessellation of OpenCASCADE shapes for the viewport.

Three things make the viewport rebuild cheap:

* The whole shape is meshed once, in parallel, through ``BRepMesh_IncrementalMesh``
  (CadQuery's ``Shape.mesh`` is single threaded; on big models parallel meshing is 2-6x faster).
* Per-face triangles and per-edge outlines are cached by TShape identity. A boolean keeps
  the untouched faces/edges of a body, so a small edit only converts what really changed.
* Edge outlines are sampled by curve parameter instead of arc length, which avoids one
  length integration per point.

Everything here only touches OCC objects and numpy, so it is safe to run in a worker thread.
"""
import math
import threading
from collections import OrderedDict
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Line
from OCP.TopAbs import TopAbs_EDGE, TopAbs_Orientation
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Vertex

FACE_LIMIT = 6000
EDGE_LIMIT = 12000
CURVE_POINTS = 41
_LOCK = threading.RLock()
# Held by every background job that builds or meshes solids (the busy-dialog worker and the
# live-preview worker), so two threads never modify the same OCC shapes at once.
KERNEL_LOCK = threading.RLock()
_FACES = OrderedDict()   # (hashCode, orientation) -> [(face, quality, vertices, triangles)]
_EDGES = OrderedDict()   # hashCode -> [(edge, polyline, ((x,y,z), ...))]
_MESHED = OrderedDict()  # hashCode -> [(shape, linear, angular)] the settings a shape was meshed with


def quality(shape, draft=False):
    """(linear deflection, angular deflection) for the display mesh.

    ``draft`` is used for previews that are replaced by the real result on Apply: about
    2.5x coarser in deflection, so a preview costs a fraction of the final mesh.
    """
    try:
        box = shape.BoundingBox()
        diagonal = math.sqrt(box.xlen * box.xlen + box.ylen * box.ylen + box.zlen * box.zlen)
    except Exception:
        diagonal = 100.
    linear = max(.05, min(.25, diagonal / 2000.))
    angular = .10
    if draft:
        return min(1., linear * 2.5), .20
    return linear, angular


def _meshed_with(shape):
    for entry in _MESHED.get(shape.hashCode(), ()):
        if entry[0].isSame(shape):
            return entry
    return None


def _remember(shape, linear, angular):
    ident = shape.hashCode()
    bucket = [e for e in _MESHED.get(ident, []) if not e[0].isSame(shape)]
    bucket.append((shape, linear, angular))
    _MESHED[ident] = bucket
    _MESHED.move_to_end(ident)
    _trim(_MESHED, 400)


def mesh(shape, linear, angular):
    """Triangulate every face of ``shape`` (no-op where a fine enough mesh already exists).

    OpenCASCADE treats a shape as meshed when its actual deflection is below ``linear``,
    which a coarse *angular* draft mesh often satisfies; the settings used here are
    therefore remembered per shape, so a draft mesh is refined when the real one is asked for
    and a draft request never throws away a finer mesh.
    """
    with _LOCK:
        prior = _meshed_with(shape)
    if prior is not None:
        if prior[1] <= linear * 1.001 and prior[2] <= angular * 1.001:
            return
        BRepTools.Clean_s(shape.wrapped)           # coarser than asked for: refine from scratch
    elif BRepTools.Triangulation_s(shape.wrapped, linear):
        with _LOCK:
            _remember(shape, linear, angular)      # meshed elsewhere (e.g. an earlier view); trust it
        return
    # isRelative=False (absolute deflection in mm), isInParallel=True.
    BRepMesh_IncrementalMesh(shape.wrapped, linear, False, angular, True)
    with _LOCK:
        _remember(shape, linear, angular)


def _trim(cache, limit):
    while len(cache) > limit:
        cache.popitem(last=False)


def _extract_face(face):
    location = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(face.wrapped, location)
    if poly is None:
        return np.empty((0, 3)), np.empty((0, 3), dtype=int)
    transform = location.Transformation()
    count = poly.NbNodes()
    points = np.empty((count, 3))
    for index in range(1, count + 1):
        node = poly.Node(index).Transformed(transform)
        points[index - 1] = (node.X(), node.Y(), node.Z())
    reverse = face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
    triangles = np.empty((poly.NbTriangles(), 3), dtype=int)
    # Triangle(i) per item: poly.Triangles() copies the whole array through a slow path
    # (about 1 ms per face).
    for index in range(poly.NbTriangles()):
        triangle = poly.Triangle(index + 1)
        a, b, c = triangle.Value(1) - 1, triangle.Value(2) - 1, triangle.Value(3) - 1
        triangles[index] = (a, c, b) if reverse else (a, b, c)
    return points, triangles


def face_mesh(face, key):
    """Cached ``(vertices, triangles)`` of a meshed face; ``key`` is the quality it was meshed at."""
    ident = (face.hashCode(), face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED)
    with _LOCK:
        for entry in _FACES.get(ident, ()):
            if entry[0].isSame(face) and entry[1] == key:
                _FACES.move_to_end(ident)
                return entry[2], entry[3]
    points, triangles = _extract_face(face)
    with _LOCK:
        bucket = [e for e in _FACES.get(ident, []) if not e[0].isSame(face)]
        bucket.append((face, key, points, triangles))
        _FACES[ident] = bucket
        _FACES.move_to_end(ident)
        _trim(_FACES, FACE_LIMIT)
    return points, triangles


def _edge_record(topo_edge):
    """(polyline, vertex points) of one OCC edge, read through OCP directly.

    The cadquery wrappers (``positionAt`` / ``Vertices`` / ``Center``) cost about a millisecond
    per edge; a text or lattice body has thousands of edges.
    """
    try:
        curve = BRepAdaptor_Curve(topo_edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        count = 2 if curve.GetType() == GeomAbs_Line else CURVE_POINTS
        points = np.empty((count, 3))
        for index in range(count):
            point = curve.Value(first + (last - first) * index / (count - 1))
            points[index] = (point.X(), point.Y(), point.Z())
    except Exception:
        points = None
    first_vertex, last_vertex = TopoDS_Vertex(), TopoDS_Vertex()
    TopExp.Vertices_s(topo_edge, first_vertex, last_vertex)
    ends = [first_vertex] if first_vertex.IsSame(last_vertex) else [first_vertex, last_vertex]
    vertices = []
    for vertex in ends:
        if not vertex.IsNull():
            point = BRep_Tool.Pnt_s(vertex)
            vertices.append((point.X(), point.Y(), point.Z()))
    if points is None:   # degenerate edge without a 3D curve: its vertices stand in
        points = np.array(vertices or [(0., 0., 0.)], dtype=float)
    return points, tuple(vertices)


def _edge_lookup(topo_edge):
    ident = hash(topo_edge)
    with _LOCK:
        for entry in _EDGES.get(ident, ()):
            if entry[0].IsSame(topo_edge):
                _EDGES.move_to_end(ident)
                return entry[1], entry[2]
    polyline, vertices = _edge_record(topo_edge)
    with _LOCK:
        bucket = [e for e in _EDGES.get(ident, []) if not e[0].IsSame(topo_edge)]
        bucket.append((topo_edge, polyline, vertices))
        _EDGES[ident] = bucket
        _EDGES.move_to_end(ident)
        _trim(_EDGES, EDGE_LIMIT)
    return polyline, vertices


def edge_data(edge):
    """Cached ``(polyline, vertex_points)`` of a CadQuery edge."""
    return _edge_lookup(edge.wrapped)


def face_outlines(face):
    """Cached polylines of every edge of a face."""
    edges = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face.wrapped, TopAbs_EDGE, edges)
    return [_edge_lookup(TopoDS.Edge_s(edges.FindKey(index)))[0] for index in range(1, edges.Extent() + 1)]


def clear():
    with _LOCK:
        _FACES.clear()
        _EDGES.clear()
        _MESHED.clear()
