"""What a feature still needs before it can be built.

Fusion and FreeCAD keep a tool's OK button disabled until its required selections are made, and
say what is missing. ``missing_inputs`` gives SlothCAD's editors the same: a list of short, plain
phrases ("a profile", "the faces to remove"), empty when the feature can be built.
"""

TARGET_OPERATIONS_NEED_TARGETS = ('join', 'cut', 'intersect')


def _has(feature, key):
    value = feature.get(key)
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) > 0
    return value is not None


def missing_inputs(feature):
    """Phrases for the selections ``feature`` lacks (an empty list means it is ready)."""
    kind = feature.get('kind')
    need = []

    def require(key, phrase):
        if not _has(feature, key):
            need.append(phrase)

    if kind in ('fillet', 'chamfer'):
        if feature.get('edge_refs') is not None and not feature.get('edge_refs'):
            need.append('the edges to round' if kind == 'fillet' else 'the edges to bevel')
    elif kind == 'revolve':
        require('source', 'a profile to revolve'); require('axis', 'an axis')
    elif kind == 'sweep':
        require('source', 'a profile'); require('path', 'a path')
    elif kind == 'loft':
        if len(feature.get('sections') or []) < 2:
            need.append('at least two profiles, in order')
    elif kind == 'draft':
        require('faces', 'the faces to draft'); require('neutral', 'a neutral plane')
    elif kind == 'hole':
        if not feature.get('points_sketch'):
            require('plane', 'a face or plane to drill from')
    elif kind == 'construction_plane':
        mode = feature.get('mode', 'offset')
        if mode in ('offset', 'angled', 'midplane'):
            require('reference', 'a reference plane or face')
        if mode == 'midplane':
            require('second', 'the second plane')
    elif kind == 'construction_axis':
        require('reference', 'an axis, two points or a cylindrical face')
    elif kind in ('body_move', 'body_mirror', 'body_rectangular', 'body_circular', 'body_split', 'body_combine'):
        require('targets', 'the body to change')
        if kind == 'body_combine':
            require('tools', 'the tool bodies')
    elif kind == 'press_pull':
        if feature.get('press_type') == 'profile':
            require('source', 'a profile')
            if feature.get('operation', 'new') != 'new':
                require('targets', 'the target body')
        else:
            require('faces', 'the faces to push or pull'); require('targets', 'the body they belong to')
    elif kind in ('scale',):
        require('targets', 'the body to scale')
    elif kind in ('offset_face', 'split_face', 'replace_face'):
        require('targets', 'the body'); require('faces', 'the face to change')
        if kind == 'split_face':
            require('source', 'a splitting profile or curve')
        if kind == 'replace_face':
            require('replacement', 'the replacement plane')
    elif kind in ('feature_rectangular', 'feature_circular', 'feature_mirror', 'path_pattern'):
        require('targets', 'the body to pattern')
        if feature.get('object_type', 'features') == 'features':
            require('features', 'the features to repeat')
        elif feature.get('object_type') == 'faces':
            require('faces', 'the faces to repeat')
        if kind == 'feature_circular':
            require('axis', 'an axis')
        if kind == 'path_pattern':
            require('path', 'a path')
    elif kind in ('pipe', 'rib', 'web'):
        require('path', 'a path')
        if feature.get('operation', 'new') in TARGET_OPERATIONS_NEED_TARGETS:
            require('targets', 'the target body')
    elif kind == 'thread':
        require('axis', 'a cylindrical face'); require('targets', 'the body to thread')
    elif kind == 'coil':
        require('axis', 'a cylindrical face or an axis')
        if feature.get('operation', 'new') in TARGET_OPERATIONS_NEED_TARGETS:
            require('targets', 'the target body')
    elif kind == 'primitive':
        if feature.get('operation', 'new') in TARGET_OPERATIONS_NEED_TARGETS:
            require('targets', 'the target body')
    elif kind in ('surface_extrude', 'surface_patch'):
        require('source', 'a boundary curve or profile')
    elif kind == 'surface_revolve':
        require('source', 'a boundary curve or profile'); require('axis', 'an axis')
    elif kind == 'surface_sweep':
        require('source', 'a boundary curve or profile'); require('path', 'a path')
    elif kind == 'surface_loft':
        if len(feature.get('sections') or []) < 2:
            need.append('at least two sections, in order')
    elif kind in ('surface_trim', 'surface_extend', 'surface_thicken', 'surface_stitch'):
        require('surfaces', 'the surface bodies')
        if kind == 'surface_trim':
            require('plane', 'a trim plane')
    elif kind == 'joint':
        require('moving', 'the moving component')
        if feature.get('joint_type') == 'mate':
            require('mate_moving', 'a face of the moving component'); require('mate_target', 'the face to mate to')
    return need
