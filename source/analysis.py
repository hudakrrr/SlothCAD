"""Read-only model analysis: mass properties, interference between bodies and a bill of materials."""
import itertools
import math
import numpy as np
from legacy_model import ModelError

# Density presets in g/cm³ (the unit most material tables use). Model units are millimetres,
# so 1 g/cm³ equals 0.001 g/mm³.
MATERIALS = (
    ('Aluminium 6061', 2.70),
    ('Steel (mild)', 7.85),
    ('Stainless steel 304', 8.00),
    ('Brass', 8.50),
    ('Copper', 8.96),
    ('Titanium', 4.51),
    ('ABS plastic', 1.04),
    ('PLA plastic', 1.24),
    ('Nylon', 1.15),
    ('Oak wood', 0.75),
    ('Water', 1.00),
)


def _properties(shape, surface=False):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    if surface:
        BRepGProp.SurfaceProperties_s(shape.wrapped, props)
    else:
        BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props


def body_properties(shape, density=1.0):
    """Volume, surface area, mass, centre of mass and inertia tensor of one solid.

    ``density`` is in g/cm³. The inertia tensor is in g·mm² about the centre of mass, in the world
    axes; ``principal`` holds its eigenvalues (the principal moments, ascending).
    """
    if density <= 0 or not math.isfinite(density):
        raise ModelError('Density must be a positive number.')
    volume_props = _properties(shape)
    volume = float(volume_props.Mass())
    area = float(_properties(shape, True).Mass())
    centre = volume_props.CentreOfMass()
    matrix = volume_props.MatrixOfInertia()
    tensor = np.array([[matrix.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)], dtype=float)
    scale = density / 1000.0          # g/mm³
    tensor = tensor * scale
    principal = np.linalg.eigvalsh((tensor + tensor.T) / 2)
    return dict(volume=volume, area=area, mass=volume * scale,
                center=[centre.X(), centre.Y(), centre.Z()],
                inertia=tensor.tolist(), principal=principal.tolist())


def mass_properties(shapes, density=1.0):
    """Combined properties of several solids that share one density.

    The result also holds ``bodies`` with the per-body values. The combined inertia tensor is taken
    about the combined centre of mass (parallel-axis theorem).
    """
    shapes = list(shapes)
    if not shapes:
        raise ModelError('There is no solid to measure.')
    bodies = [body_properties(shape, density) for shape in shapes]
    mass = sum(b['mass'] for b in bodies)
    volume = sum(b['volume'] for b in bodies)
    area = sum(b['area'] for b in bodies)
    centre = np.average([b['center'] for b in bodies], axis=0, weights=[b['mass'] for b in bodies]) if mass > 0 else np.zeros(3)
    tensor = np.zeros((3, 3))
    for b in bodies:
        offset = np.asarray(b['center']) - centre
        shift = b['mass'] * (float(offset @ offset) * np.eye(3) - np.outer(offset, offset))
        tensor += np.asarray(b['inertia']) + shift
    return dict(volume=volume, area=area, mass=mass, center=centre.tolist(), inertia=tensor.tolist(),
                principal=np.linalg.eigvalsh((tensor + tensor.T) / 2).tolist(), bodies=bodies, density=float(density))


def interferences(named_shapes, tolerance=1e-6):
    """Pairs of bodies whose volumes overlap: ``[(name_a, name_b, overlap_volume), ...]``.

    ``named_shapes`` is a list of ``(name, solid)``. Bounding boxes reject most pairs cheaply; the
    rest are intersected with the kernel. Touching faces are not interference.
    """
    boxes = []
    for name, shape in named_shapes:
        box = shape.BoundingBox()
        boxes.append((box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax))
    found = []
    for (i, (name_a, a)), (j, (name_b, b)) in itertools.combinations(list(enumerate(named_shapes)), 2):
        p, q = boxes[i], boxes[j]
        if p[0] > q[3] or q[0] > p[3] or p[1] > q[4] or q[1] > p[4] or p[2] > q[5] or q[2] > p[5]:
            continue
        try:
            common = a.intersect(b)
            volume = float(common.Volume()) if common is not None else 0.0
        except Exception:
            continue
        if volume > tolerance:
            found.append((name_a, name_b, volume))
    return found


def bill_of_materials(solid_entries, components):
    """Rows ``dict(name, quantity, volume)`` grouped by name and (rounded) volume.

    ``solid_entries`` is ``[(body_name, solid)]``. Components of an assembly give their bodies the
    component's name, so identical parts are counted together.
    """
    groups = {}
    for name, shape in solid_entries:
        volume = float(shape.Volume())
        key = (name, round(volume, 3))
        row = groups.setdefault(key, dict(name=name, quantity=0, volume=volume))
        row['quantity'] += 1
    return sorted(groups.values(), key=lambda row: row['name'])
