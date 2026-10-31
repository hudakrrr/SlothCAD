"""Kernel validity checks that stay fast on faces with hundreds of holes.

``BRepCheck_Analyzer`` compares every pair of wires on a face, so one face with n hole
outlines costs O(n²): 1.4 s for a plate face with 361 holes, paid on every fillet trial
and every rebuild. Wires whose bounding boxes do not overlap can neither cross nor nest,
so such a face is checked as several stand-in faces (same surface, its outer wire and a
batch of non-overlapping hole groups), analysed in one pass.
"""
import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_NoError, BRepCheck_Shell, BRepCheck_Solid
from OCP.Bnd import Bnd_Box
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRepTools import BRepTools

HEAVY_WIRES = 24   # faces with more wires than this are split into stand-in faces
BATCH = 8          # hole outlines per stand-in face


def _children(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def _wires(face):
    return [TopoDS.Wire_s(w) for w in _children(face, TopAbs_WIRE)]


def _box(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    x0, y0, z0, x1, y1, z1 = box.Get()
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def _stand_ins(face):
    """The face itself, or stand-in faces covering every wire pair that could interact."""
    wires = _wires(face)
    if len(wires) <= HEAVY_WIRES:
        return [face]
    outer = BRepTools.OuterWire_s(face)
    inner = [w for w in wires if not w.IsSame(outer)]
    boxes = [_box(w) for w in inner]
    # Group holes whose boxes overlap (sweep along x, union-find); groups never interact.
    parent = list(range(len(inner)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = sorted(range(len(inner)), key=lambda i: boxes[i][0][0])
    active = []
    for i in order:
        low, high = boxes[i]
        active = [j for j in active if boxes[j][1][0] >= low[0]]
        for j in active:
            if np.all(boxes[j][0] <= high) and np.all(low <= boxes[j][1]):
                parent[find(i)] = find(j)
        active.append(i)
    groups = {}
    for i in order:
        groups.setdefault(find(i), []).append(i)
    builder = BRep_Builder()
    result = []
    batch = []
    for members in list(groups.values()) + [None]:
        if members is not None:
            batch.extend(members)
        if batch and (members is None or len(batch) >= BATCH):
            proxy = TopoDS.Face_s(face.EmptyCopied())
            builder.Add(proxy, outer)
            for i in batch:
                builder.Add(proxy, inner[i])
            result.append(proxy)
            batch = []
    return result


def _heavy(faces):
    return any(sum(1 for _ in _children(face, TopAbs_WIRE)) > HEAVY_WIRES for face in faces)


def faces_valid(faces):
    """Validity of a set of faces (TopoDS or CadQuery), analysed in one parallel pass."""
    faces = [getattr(face, 'wrapped', face) for face in faces]
    if not faces:
        return True
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    shared = False
    for face in faces:
        items = _stand_ins(TopoDS.Face_s(face))
        shared = shared or len(items) > 1
        for item in items:
            builder.Add(compound, item)
    # Stand-ins share their face's outer edges; the parallel analyzer races on edges used by
    # many faces at once (a valid body was reported invalid about one time in thirty).
    return BRepCheck_Analyzer(compound, True, not shared).IsValid()


def _ok(result):
    return all(status == BRepCheck_NoError for status in result.Status())


def shape_valid(shape):
    """Same answer as ``BRepCheck_Analyzer(shape).IsValid()``, without the O(n²) wire cost."""
    shape = getattr(shape, 'wrapped', shape)
    faces = list(_children(shape, TopAbs_FACE))
    if not _heavy(faces):
        return BRepCheck_Analyzer(shape, True, True).IsValid()
    if not faces_valid(faces):
        return False
    # What the analyzer adds above the faces: closed, consistently oriented shells and solids
    # whose shells are properly arranged.
    for item in _children(shape, TopAbs_SHELL):
        check = BRepCheck_Shell(TopoDS.Shell_s(item))
        check.Closed(False)
        check.Orientation(False)
        if not _ok(check):
            return False
    for item in _children(shape, TopAbs_SOLID):
        if not _ok(BRepCheck_Solid(TopoDS.Solid_s(item))):
            return False
    return True


def near_part(face, low, high):
    """``face`` (CadQuery), or for a face with many holes a stand-in keeping only the holes
    whose boxes meet the box ``low``..``high``: overlap checks near that box are unchanged."""
    wires = _wires(face.wrapped)
    if len(wires) <= HEAVY_WIRES:
        return face
    import cadquery as cq
    outer = BRepTools.OuterWire_s(face.wrapped)
    builder = BRep_Builder()
    proxy = TopoDS.Face_s(face.wrapped.EmptyCopied())
    builder.Add(proxy, outer)
    for wire in wires:
        if wire.IsSame(outer):
            continue
        a, b = _box(wire)
        if np.all(a <= high) and np.all(b >= low):
            builder.Add(proxy, wire)
    return cq.Face(proxy)
