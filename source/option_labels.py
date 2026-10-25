"""Plain-language names for the options that tools store as short identifiers."""

OPTION_LABELS = {
    # extrusion and general
    'one side': 'One side', 'symmetric': 'Symmetric', 'two sides': 'Two sides',
    'distance': 'Distance', 'through all': 'Through all', 'to object': 'Up to a face or plane',
    'auto': 'Automatic (asks when it crosses a body)', 'add': 'Join', 'cut': 'Cut', 'intersect': 'Intersect',
    'new': 'New body', 'join': 'Join',
    # direction and sides
    'inward': 'Into the body', 'outward': 'Out of the body', 'positive': 'Positive side', 'negative': 'Negative side',
    'both': 'Both sides', 'inside': 'Inside', 'outside': 'Outside', 'centered': 'Centered',
    # what a pattern repeats
    'features': 'Features', 'faces': 'Faces', 'bodies': 'Whole bodies', 'profile': 'Closed profile',
    # surfaces and threads
    'external': 'External (on a shaft)', 'internal': 'Internal (in a hole)',
    'all': 'All directions', 'u': 'Along U', 'v': 'Along V',
    # splines
    'catmull': 'Smooth through the points', 'bspline': 'B-spline (control points)',
    # holes and construction
    'simple': 'Simple', 'counterbore': 'Counterbore', 'countersink': 'Countersink',
    'offset': 'Offset from a plane', 'angled': 'At an angle to a plane', 'midplane': 'Midway between two planes',
    'three points': 'Through three points',
    # joints
    'rigid': 'Rigid', 'revolute': 'Revolute (hinge)', 'slider': 'Slider', 'cylindrical': 'Cylindrical (slide and turn)',
    'mate': 'Mate (face to face)',
    # primitives
    'box': 'Box', 'cylinder': 'Cylinder', 'sphere': 'Sphere', 'cone': 'Cone', 'torus': 'Torus',
    # legacy edge choices
    'vertical': 'Vertical edges', 'top': 'Top edges', 'bottom': 'Bottom edges',
    # pattern distances
    'spacing': 'Spacing between copies', 'extent': 'Overall length',
}


def option_label(value):
    """The label for an option value; unknown values are shown as they are."""
    return OPTION_LABELS.get(value, value) if isinstance(value, str) else value


# Menu and panel titles of tools whose identifier reads badly when title-cased ("Feature Rectangular").
TOOL_LABELS = {
    'feature_rectangular': 'Rectangular pattern of features', 'feature_circular': 'Circular pattern of features',
    'feature_mirror': 'Mirror features', 'path_pattern': 'Pattern along a path',
    'press_pull': 'Press / Pull', 'offset_face': 'Offset face', 'split_face': 'Split face', 'replace_face': 'Replace face',
    'primitive': 'Primitive solid', 'surface_extrude': 'Extrude surface', 'surface_revolve': 'Revolve surface',
    'surface_sweep': 'Sweep surface', 'surface_loft': 'Loft surface', 'surface_patch': 'Patch surface',
    'surface_trim': 'Trim surface', 'surface_extend': 'Extend surface', 'surface_stitch': 'Stitch surfaces',
    'surface_thicken': 'Thicken surface',
}


def tool_label(kind):
    """The title of a tool: its plain-language name when it has one, else the identifier title-cased."""
    return TOOL_LABELS.get(kind) or kind.replace('_', ' ').title()
