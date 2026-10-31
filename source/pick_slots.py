"""Click-to-choose inputs for tools.

A tool lists the things it needs as *slots*: "Profile", "Axis", "Faces to remove", "Body to move"...
The panel shows one row per slot; the active row waits for a click in the 3D view and takes whatever
is under the pointer (a face, a sketch profile, a curve, a plane...), then moves on to the next one.
Fusion and FreeCAD work the same way; no lists or drop-downs have to be used (they stay available
behind "Show all options").
"""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QToolButton,QCheckBox,QLabel,QFormLayout,QSizePolicy
from legacy_model import ModelError
from i18n import tr


class Slot:
    """One input of a tool.

    ``accept`` lists what the viewport may offer (``curve``, ``profile``, ``plane``, ``face``, ``edge``);
    ``kind`` says how a hit becomes the stored value; ``multi`` slots toggle items in a list.
    """
    def __init__(self, key, label, kind, accept, multi=False, optional=False, quick=None, help=None):
        self.key = key
        self.label = label
        self.kind = kind
        self.accept = list(accept)
        self.multi = multi
        self.optional = optional
        self.quick = quick or []          # [(label, value)] one-click answers (origin planes / axes)
        self.help = help


PLANE_QUICK = [('XY', dict(type='origin', plane='XY')), ('XZ', dict(type='origin', plane='XZ')), ('YZ', dict(type='origin', plane='YZ'))]
AXIS_QUICK = [('X', dict(type='origin', axis='X')), ('Y', dict(type='origin', axis='Y')), ('Z', dict(type='origin', axis='Z'))]


def plane_slot(key='plane', label='Plane', optional=False):
    return Slot(key, label, 'plane', ['plane', 'face'], quick=PLANE_QUICK, optional=optional)


def axis_slot(key='axis', label='Axis', optional=False):
    return Slot(key, label, 'axis', ['curve', 'edge', 'face'], quick=AXIS_QUICK, optional=optional)


BODY = lambda key='targets', label='Body': Slot(key, label, 'bodies', ['face'], multi=True)


def slots_for(f):
    """The ordered inputs of the feature ``f`` (empty for tools that are not picked with clicks)."""
    kind = f.get('kind')
    s = []
    if kind == 'revolve':
        s = [Slot('source', 'Profile to revolve', 'profile', ['profile', 'face']), axis_slot('axis', 'Axis it turns around')]
    elif kind == 'sweep':
        s = [Slot('source', 'Profile', 'profile', ['profile', 'face']), Slot('path', 'Path', 'path', ['curve']),
             Slot('guide', 'Guide curve (optional)', 'path', ['curve'], optional=True)]
    elif kind == 'loft':
        s = [Slot('sections', 'Profiles, in order', 'profiles', ['profile', 'face'], multi=True)]
    elif kind == 'shell':
        s = [Slot('faces', 'Faces to leave open (none = closed hollow)', 'faces', ['face'], multi=True, optional=True)]
    elif kind == 'draft':
        s = [Slot('faces', 'Faces to draft', 'faces', ['face'], multi=True), plane_slot('neutral', 'Neutral plane (stays put)')]
    elif kind == 'hole':
        s = [Slot('plane', 'Click where the hole goes', 'hole_site', ['face'])]
    elif kind == 'construction_plane':
        mode = f.get('mode', 'offset')
        if mode in ('offset', 'angled'):
            s = [plane_slot('reference', 'Plane or face to start from')]
            if mode == 'angled':
                s.append(axis_slot('axis', 'Axis to tilt about'))
        elif mode == 'midplane':
            s = [plane_slot('reference', 'First plane or face'), plane_slot('second', 'Second plane or face')]
    elif kind == 'construction_axis':
        s = [Slot('reference', 'Edge, round face or sketch line', 'axis', ['curve', 'edge', 'face'], quick=AXIS_QUICK)]
    elif kind == 'body_combine':
        s = [Slot('targets', 'Body to keep (target)', 'bodies', ['face'], multi=False), Slot('tools', 'Bodies to combine with it', 'bodies', ['face'], multi=True)]
    elif kind in ('body_move', 'body_mirror', 'body_rectangular', 'body_circular', 'body_split'):
        s = [BODY('targets', 'Body')]
        if kind in ('body_mirror',):
            s.append(plane_slot('plane', 'Mirror plane'))
        elif kind == 'body_rectangular':
            s.append(plane_slot('plane', 'Plane the copies lie in'))
        elif kind == 'body_split':
            s.append(plane_slot('plane', 'Plane that cuts the body'))
        elif kind == 'body_circular':
            s.append(axis_slot('axis', 'Axis to turn about'))
        elif kind == 'body_move':
            s.append(axis_slot('axis', 'Axis for the rotation (optional)', optional=True))
    elif kind == 'press_pull':
        if f.get('press_type') == 'profile':
            s = [Slot('source', 'Profile', 'profile', ['profile', 'face'])]
            if f.get('operation', 'new') != 'new':
                s.append(BODY('targets', 'Body to change'))
        else:
            s = [Slot('faces', 'Faces to push or pull', 'faces', ['face'], multi=True)]
    elif kind == 'offset_face':
        s = [Slot('faces', 'Faces to move', 'faces', ['face'], multi=True)]
    elif kind == 'scale':
        s = [BODY('targets', 'Body to scale')]
    elif kind == 'split_face':
        s = [Slot('faces', 'Face to divide', 'faces', ['face'], multi=True), Slot('source', 'Profile or curve that divides it', 'profile_or_curve', ['curve', 'profile'])]
    elif kind == 'replace_face':
        s = [Slot('faces', 'Faces to replace', 'faces', ['face'], multi=True), plane_slot('replacement', 'Plane they move to')]
    elif kind in ('feature_rectangular', 'feature_circular', 'feature_mirror', 'path_pattern'):
        s = [BODY('targets', 'Body')]
        if f.get('object_type', 'features') == 'features':
            s.append(Slot('features', 'Click a face made by the feature to repeat', 'features', ['face'], multi=True))
        elif f.get('object_type') == 'faces':
            s.append(Slot('faces', 'Faces to repeat', 'faces', ['face'], multi=True))
        if kind in ('feature_rectangular', 'feature_mirror'):
            s.append(plane_slot('plane', 'Plane of the pattern' if kind == 'feature_rectangular' else 'Mirror plane'))
        elif kind == 'feature_circular':
            s.append(axis_slot('axis', 'Axis to turn about'))
        else:
            s.append(Slot('path', 'Path', 'path', ['curve']))
    elif kind in ('pipe', 'rib', 'web'):
        s = [Slot('path', 'Path' if kind == 'pipe' else 'Sketch line', 'path', ['curve'])]
        if f.get('operation', 'new') in ('join', 'cut', 'intersect'):
            s.append(BODY('targets', 'Body to change'))
    elif kind == 'primitive':
        if f.get('operation', 'new') in ('join', 'cut', 'intersect'):
            s = [BODY('targets', 'Body to change')]
    elif kind in ('thread', 'coil'):
        s = [Slot('axis', 'Round face (shaft or hole wall)', 'round_face', ['face'])]
        if kind == 'thread' or f.get('operation', 'new') in ('join', 'cut', 'intersect'):
            pass
    elif kind in ('surface_extrude', 'surface_patch'):
        s = [Slot('source', 'Boundary curve or profile', 'profile_or_curve', ['curve', 'profile'])]
    elif kind == 'surface_revolve':
        s = [Slot('source', 'Curve or profile', 'profile_or_curve', ['curve', 'profile']), axis_slot('axis', 'Axis it turns around')]
    elif kind == 'surface_sweep':
        s = [Slot('source', 'Curve or profile', 'profile_or_curve', ['curve', 'profile']), Slot('path', 'Path', 'path', ['curve'])]
    elif kind == 'surface_loft':
        s = [Slot('sections', 'Curves, in order', 'curve_sections', ['curve', 'profile'], multi=True)]
    elif kind in ('surface_trim', 'surface_extend', 'surface_thicken', 'surface_stitch'):
        s = [Slot('surfaces', 'Surfaces', 'surfaces', ['face'], multi=True)]
        if kind == 'surface_trim':
            s.append(plane_slot('plane', 'Plane that trims'))
    elif kind == 'joint':
        if f.get('joint_type') == 'mate':
            s = [Slot('mate_moving', 'Face of the part that moves', 'mate_face', ['face']), Slot('mate_target', 'Face it should touch', 'mate_face', ['face'])]
            s[0].component = True
        else:
            s = [Slot('moving', 'Part that moves', 'component', ['face']), Slot('fixed', 'Part it is attached to (none = the origin)', 'component', ['face'], optional=True)]
    return s


class SlotUI:
    """Panel rows, routing of viewport clicks and the conversion of a click into a stored value."""
    def init_slots(self):
        self.active_slot = None
        self.show_all_selectors = False
        self.selector_widgets = []        # old list / combo widgets that the slots replace
        self.workspace.slot_picked.connect(self.slot_clicked)

    # ---- what is currently chosen --------------------------------------------------------------
    def slot_value(self, slot, f=None):
        f = f or self.draft
        return f.get(slot.key)

    def slot_filled(self, slot, f=None):
        f = f or self.draft
        value = self.slot_value(slot, f)
        if slot.kind == 'hole_site':
            # an existing hole is placed; a new one waits for the first click on a face
            return self.draft_index is not None or getattr(self, 'site_confirmed', None) == f.get('id')
        if isinstance(value, (list, tuple, dict, str)):
            return len(value) > 0
        return value is not None

    def describe_slot(self, slot):
        f = self.draft
        value = f.get(slot.key)
        if not self.slot_filled(slot):
            return ''
        if slot.multi or isinstance(value, list):
            return f'{len(value)} ' + tr('chosen')
        if isinstance(value, dict):
            t = value.get('type')
            if t == 'origin':
                return (value.get('plane') + ' ' + tr('plane')) if 'plane' in value else (value.get('axis') + ' ' + tr('axis'))
            if t == 'construction':
                return next((g.get('name', '') for g in self.doc.features if g.get('id') == value.get('id')), tr('Construction plane'))
            if t == 'face':
                return tr('Face')
            if t == 'sketch_line':
                return next((g.get('name', '') for g in self.doc.features if g.get('id') == value.get('sketch')), tr('Sketch')) + ' · ' + tr('line')
            if t == 'points':
                return tr('Axis through two points')
            if t == 'sketch':
                return next((g.get('name', '') for g in self.doc.features if g.get('id') == value.get('sketch')), tr('Sketch')) + ' · ' + tr('profile')
            if 'sketch' in value:
                return next((g.get('name', '') for g in self.doc.features if g.get('id') == value.get('sketch')), tr('Sketch')) + ' · ' + tr('curve')
            if 'center' in value:
                return tr('Face')
            return tr('chosen')
        if slot.kind == 'component':
            comp = self.tool_context()[2].get('_components', {}).get(value)
            return comp['name'] if comp else str(value)
        return str(value)

    # ---- panel -----------------------------------------------------------------------------------
    def render_slots(self, f):
        """Add the slot rows to the editor (called from the tool's action row)."""
        slots = slots_for(f)
        self.current_slots = slots
        if not slots:
            self.workspace.slot_accept = None
            return
        if getattr(self, 'slots_draft_id', None) != f.get('id'):
            self.slots_draft_id = f.get('id');self.active_slot = None;self.confirmed_slots = set()
        if self.active_slot is None or self.active_slot not in {s.key for s in slots}:
            self.active_slot = self.first_open_slot(slots)
        box = QWidget();layout = QVBoxLayout(box);layout.setContentsMargins(0, 2, 0, 2);layout.setSpacing(3)
        for number, slot in enumerate(slots, 1):
            row = QWidget();stack = QVBoxLayout(row);stack.setContentsMargins(0, 0, 0, 0);stack.setSpacing(2)
            line = QHBoxLayout();line.setContentsMargins(0, 0, 0, 0);line.setSpacing(4)
            filled = self.slot_filled(slot)
            default = filled and not self.slot_confirmed(slot)
            text = f'{number}. {tr(slot.label)}'
            if filled:
                text += ' — ' + self.describe_slot(slot) + ((' (' + tr('default, click to change') + ')') if default else '')
            elif slot.key == self.active_slot:
                text += ' — ' + tr('click it in the 3D view')
            button = QPushButton();button.setCheckable(True);button.setChecked(slot.key == self.active_slot)
            # Long names are cut with an ellipsis (the whole text is in the tooltip) so a row never widens the panel.
            button.setText(button.fontMetrics().elidedText(text, Qt.ElideRight, 330));button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setObjectName('slotRow');button.setStyleSheet(self.slot_style(slot.key == self.active_slot, filled and not default))
            button.setToolTip(text + '\n' + (tr(slot.help) if slot.help else tr('Click here, then click the object in the 3D view.')))
            button.clicked.connect(lambda checked=False, key=slot.key: self.activate_slot(key))
            stack.addWidget(button)
            line.addStretch(1)
            for label, value in slot.quick:
                chip = QToolButton();chip.setText(label);chip.setToolTip(tr('Use the') + ' ' + label)
                chip.clicked.connect(lambda checked=False, s=slot, v=copy.deepcopy(value): self.set_slot_value(s, v))
                line.addWidget(chip)
            if slot.multi and filled and slot.key == self.active_slot and self.first_open_slot(slots) not in (None, slot.key):
                nxt = QToolButton();nxt.setText(tr('Next') + ' ▸');nxt.setToolTip(tr('Done choosing here: go to the next input.'))
                nxt.clicked.connect(lambda checked=False: self.activate_slot(self.first_open_slot(self.current_slots)))
                line.addWidget(nxt)
            if filled or slot.multi:
                clear = QToolButton();clear.setText('✕');clear.setToolTip(tr('Clear'))
                clear.clicked.connect(lambda checked=False, s=slot: self.clear_slot(s))
                line.addWidget(clear)
            if line.count() > 1:                       # chips only when there are any
                stack.addLayout(line)
            layout.addWidget(row)
        show = QCheckBox(tr('Show all selection options'));show.setChecked(self.show_all_selectors)
        show.setToolTip(tr('The lists and drop-down menus behind the clicks: for choosing something you cannot click.'))
        show.toggled.connect(self.toggle_selectors);layout.addWidget(show)
        self.editor_layout.addWidget(box);self.widgets['slot_panel'] = box

    @staticmethod
    def slot_style(active, filled):
        if active:
            return 'QPushButton{text-align:left;padding:6px;border:2px solid #f0ad45;border-radius:6px;font-weight:bold;}'
        if filled:
            return 'QPushButton{text-align:left;padding:5px;border:1px solid #3f9f6a;border-radius:6px;}'
        return 'QPushButton{text-align:left;padding:5px;border:1px dashed #9aa5ae;border-radius:6px;}'

    # inputs the program fills in by itself and that count as chosen (the only body, the last feature)
    AUTO_CHOSEN = ('targets', 'features')

    def slot_confirmed(self, slot):
        """True once the input was chosen by the user, belongs to an existing feature, or is automatic."""
        return (self.draft_index is not None or slot.key in getattr(self, 'confirmed_slots', set())
                or slot.key in self.AUTO_CHOSEN or slot.kind == 'hole_site')

    def first_open_slot(self, slots):
        # A value that is only a default (a mirror plane of XY) still asks to be confirmed with a click.
        for slot in slots:
            if not slot.optional and (not self.slot_filled(slot) or not self.slot_confirmed(slot)):
                return slot.key
        return None

    def activate_slot(self, key):
        self.active_slot = key
        self.show_editor()

    def clear_slot(self, slot):
        f = self.draft
        if slot.multi:
            f[slot.key] = []
        elif slot.kind == 'hole_site':
            pass
        else:
            f[slot.key] = None
        self.active_slot = slot.key
        self.invalidate_preview();self.show_editor()

    def toggle_selectors(self, on):
        self.show_all_selectors = bool(on)
        for widget in self.selector_widgets:
            try:widget.setVisible(self.show_all_selectors)
            except RuntimeError:pass

    # ---- keeping the viewport in step with the active slot ---------------------------------------
    def sync_slots(self):
        """Tell the viewport what a click may choose now; hide the old selection widgets."""
        w = self.workspace
        f = self.draft
        slots = getattr(self, 'current_slots', []) if f is not None and f.get('kind') not in ('sketch', None) else []
        if f is None or not slots or w.mode != 'model' or self.history_preview_index is not None or w.measure_active:
            w.slot_accept = None
            return
        slot = next((s for s in slots if s.key == self.active_slot), None)
        if slot is None:
            w.slot_accept = None
            return
        w.solid_face_picking = False;w.path_picking = False
        if 'profile' in slot.accept and not w.extrude_selecting:
            w.set_extrusion_selection([], True)
        w.slot_accept = list(slot.accept)
        self.hide_selectors(slots)

    def hide_selectors(self, slots):
        keys = {s.key for s in slots}
        keys |= {'solid_faces', 'loft_profile', 'body', 'section'} if any(s.key in ('faces', 'sections') for s in slots) else set()
        found = []
        for key in keys:
            widget = self.widgets.get(key)
            if widget is None or widget is self.widgets.get('slot_panel'):
                continue
            found.append(widget)
            parent = widget.parentWidget()
            layout = parent.layout() if parent is not None else None
            if isinstance(layout, QFormLayout):
                label = layout.labelForField(widget)
                if label is not None:found.append(label)
        found.extend(b for b in getattr(self, 'picker_buttons', []) if b is not None)
        self.selector_widgets = []
        for widget in found:
            try:
                widget.setVisible(self.show_all_selectors);self.selector_widgets.append(widget)
            except RuntimeError:pass

    # ---- a click in the viewport ---------------------------------------------------------------------
    def slot_clicked(self, hit):
        f = self.draft
        if f is None or self.active_slot is None:return
        slot = next((s for s in getattr(self, 'current_slots', []) if s.key == self.active_slot), None)
        if slot is None:return
        if hit.get('type') == 'none':
            self.show_status(tr('Nothing there. Click') + ' ' + tr(slot.label).lower() + ' ' + tr('in the 3D view.'));return
        try:
            value = self.resolve_hit(slot, hit)
        except ModelError as error:
            self.show_status(tr(str(error)));return
        if value is None:return
        self.set_slot_value(slot, value, hit)

    def set_slot_value(self, slot, value, hit=None):
        f = self.draft
        self.confirmed_slots = getattr(self, 'confirmed_slots', set()) | {slot.key}
        if slot.kind == 'bodies' and f.get('kind') == 'body_combine' and slot.key in ('targets', 'tools'):
            # A body is either the target or a tool: picking it for one takes it out of the other.
            other = 'tools' if slot.key == 'targets' else 'targets'
            key = self.slot_item_key(slot, value)
            f[other] = [item for item in f.get(other, []) if self.slot_item_key(slot, item) != key]
        if slot.kind == 'hole_site':
            f['plane'] = value['plane'];f['x'], f['y'] = value['x'], value['y'];f.pop('points_sketch', None)
            self.site_confirmed = f.get('id')
        elif slot.multi:
            items = f.setdefault(slot.key, [])
            key = self.slot_item_key(slot, value)
            found = next((i for i, item in enumerate(items) if self.slot_item_key(slot, item) == key), None)
            if slot.key == 'targets' and slot.kind == 'bodies' and f.get('kind') == 'body_combine' and not slot.multi:
                items[:] = [value]
            elif found is None:items.append(value)
            else:items.pop(found)
        elif slot.kind in ('bodies',):
            f[slot.key] = [value]                 # a single-body slot holds a list of one reference
        else:
            f[slot.key] = value
        if slot.kind == 'round_face':
            pass
        self.invalidate_preview()
        # carry on with the next open input (a multi-selection stays active so more can be added)
        slots = self.current_slots
        # A single choice moves on by itself; so does picking the body of a tool (one body is the usual case).
        if (not slot.multi or slot.kind == 'bodies') and slot.kind != 'hole_site':
            nxt = self.first_open_slot(slots)
            self.active_slot = nxt if nxt is not None else slot.key
        self.show_editor()

    @staticmethod
    def slot_item_key(slot, value):
        if isinstance(value, dict):
            if 'body_id' in value:return ('body', value['body_id'])
            if 'center' in value and ('area' in value or 'volume' in value):
                return tuple(round(float(v), 5) for v in value['center']) + (round(float(value.get('area', value.get('volume', 0))), 5),)
            return repr(sorted(value.items(), key=lambda kv: kv[0]))
        return value

    # ---- hit -> value ------------------------------------------------------------------------------
    def resolve_hit(self, slot, hit):
        w = self.workspace
        result, sketches, frames = self.tool_context()
        kind = slot.kind
        t = hit['type']
        from geometry import face_reference
        from solid_tools import face_ref
        face = w.faces[hit['index']] if t == 'face' else None
        if kind in ('profile', 'profile_or_curve', 'profiles', 'curve_sections'):
            if t == 'sketch':
                return {k: copy.deepcopy(v) for k, v in hit.items()}
            if t == 'curve' and kind in ('profile_or_curve', 'curve_sections'):
                ref = dict(sketch=hit['sketch'], entities=list(hit['entities']))
                return dict(type='path', **ref) if kind == 'profile_or_curve' else dict(type='path', **ref)
            if face is not None:
                if face.geomType() != 'PLANE':
                    raise ModelError('That face is curved. Click a closed sketch profile or a flat face.')
                return dict(type='face', face=face_reference(face))
            raise ModelError('Click a closed sketch profile or a flat face.')
        if kind == 'path':
            if t != 'curve':raise ModelError('Click one of the sketch curves.')
            return dict(sketch=hit['sketch'], entities=list(hit['entities']))
        if kind == 'plane':
            if t == 'plane':return dict(type='origin', plane=hit['plane'])
            if t == 'construction':return dict(type='construction', id=hit['id'])
            if face is not None:
                if face.geomType() != 'PLANE':raise ModelError('That face is curved. Click a flat face or one of the planes.')
                return dict(type='face', face=face_reference(face), origin='projected')
            raise ModelError('Click a flat face or a plane.')
        if kind == 'axis':
            return self.axis_from_hit(hit, face, result, sketches, frames)
        if kind in ('faces',):
            if face is None:raise ModelError('Click a face of the body.')
            return face_ref(face, result)
        if kind in ('bodies',):
            if face is None:raise ModelError('Click a body.')
            from references import body_reference
            bodies = result.val().Solids() if result else []
            index = next((i for i, b in enumerate(bodies) if any(face.isSame(x) for x in b.Faces())), None)
            if index is None:raise ModelError('That face does not belong to a body of the model.')
            return body_reference(bodies[index], index, len(bodies), result)
        if kind == 'features':
            if face is None:raise ModelError('Click a face that the feature created.')
            found = self.feature_that_made(face, result)
            if found is None:
                raise ModelError('Could not tell which feature made that face. Try another of its faces, or use "Show all selection options".')
            return found
        if kind == 'component':
            if face is None:raise ModelError('Click a body of the part.')
            return self.component_of(face, result, frames)
        if kind == 'mate_face':
            if face is None:raise ModelError('Click a flat face.')
            if face.geomType() != 'PLANE':raise ModelError('Mates align flat faces. Choose a flat face.')
            return dict(type='face', face=face_reference(face), origin='projected')
        if kind == 'surfaces':
            if face is None:raise ModelError('Click a surface.')
            for id_, body in frames.get('_surfaces', {}).items():
                if any(face.isSame(own) for own in body['shape'].Faces()):return id_
            raise ModelError('That is not a surface body.')
        if kind == 'round_face':
            if face is None or face.geomType() != 'CYLINDER':raise ModelError('That face is not round. Click the wall of a shaft or a round hole.')
            self.use_cylinder_face(face)
            return None
        if kind == 'hole_site':
            if face is None or face.geomType() != 'PLANE':raise ModelError('Click a flat face to drill from.')
            from geometry import frame_on_face, axes
            frame = frame_on_face(face)         # the kernel measures hole X/Y from the face centre
            o, u, v, n = axes(frame)
            point = np.asarray(hit.get('point') or face.Center().toTuple(), float)
            return dict(plane=dict(type='face', face=face_reference(face), origin='projected'),
                        x=round(float((point - o) @ u), 4), y=round(float((point - o) @ v), 4))
        raise ModelError('This input cannot be picked with a click.')

    def axis_from_hit(self, hit, face, result, sketches, frames):
        t = hit['type']
        if t == 'curve':
            sketch = sketches.get(hit['sketch'])
            clicked = hit.get('clicked') or hit['entities'][0]
            entity = next((e for e in (sketch or {}).get('entities', []) if e['id'] == clicked), None)
            if entity is None or entity['kind'] != 'line':
                raise ModelError('An axis needs a straight line. Click a straight sketch line, a straight edge or a round face.')
            return dict(type='sketch_line', sketch=hit['sketch'], entity=clicked)
        if t == 'edge':
            edge = self.workspace.solid_edges[hit['index']][0]
            if edge.geomType() == 'LINE':
                return dict(type='points', start=list(edge.startPoint().toTuple()), end=list(edge.endPoint().toTuple()))
            if edge.geomType() == 'CIRCLE':
                center = np.asarray(edge.arcCenter().toTuple());normal = np.asarray(edge.normal().toTuple())
                return dict(type='points', start=center.tolist(), end=(center + normal * max(5., float(edge.radius()))).tolist())
            raise ModelError('That edge is curved. Click a straight edge, a circular edge or a round face.')
        if face is not None:
            if face.geomType() == 'CYLINDER':
                from advanced_ui import cylinder_axis
                start, end = cylinder_axis(face)
                return dict(type='points', start=start, end=end)
            if face.geomType() == 'PLANE':
                point = np.asarray(hit.get('point') or face.Center().toTuple(), float);normal = np.asarray(face.normalAt().toTuple())
                return dict(type='points', start=point.tolist(), end=(point + normal * 10.).tolist())
            raise ModelError('Click a round face, a flat face (its normal), a straight edge or a sketch line.')
        raise ModelError('Click a straight edge, a round face or a sketch line.')

    def component_of(self, face, result, frames):
        from topology import entries
        records = entries(result)
        body = next((r for r in records if any(face.isSame(x) for x in r['shape'].Faces())), None)
        if body is None:raise ModelError('Click a body that belongs to a component.')
        for id_, component in frames.get('_components', {}).items():
            if body['id'] in component.get('members', []):return id_
        raise ModelError('That body is not part of a component. Make a component first.')

    def feature_that_made(self, face, result):
        """The id of the history feature that first produced ``face`` (its geometry), or None."""
        from references import shape_reference
        reference = shape_reference(face, 'face')
        center = np.asarray(reference['center']);normal = np.asarray(reference['normal']);area = reference['area']
        def present(solid):
            if solid is None:return False
            for candidate in solid.val().Faces():
                if candidate.geomType() != face.geomType():continue
                if abs(candidate.Area() - area) > 1e-5 * max(1., area):continue
                if float(np.linalg.norm(np.asarray(candidate.Center().toTuple()) - center)) > 1e-5 * max(1., area ** .5):continue
                try:
                    if abs(float(np.asarray(candidate.normalAt().toTuple()) @ normal)) < .999:continue
                except Exception:pass
                return True
            return False
        features = self.doc.features
        limit = self.draft_index if self.draft_index is not None else len(features)
        states = getattr(self.doc, '_states', [])
        def after(i):
            if i < len(states) and states[i] is not None:return states[i][0]
            return self.doc.preview(copy.deepcopy(features[:i + 1]))[0]
        hidden = ('sketch', 'sketch_move', 'construction_plane', 'construction_axis', 'sketch3d', 'surface_sketch')
        previous = None
        for i in range(limit - 1, -1, -1):
            f = features[i]
            if not f.get('enabled', True) or f['kind'] in hidden or not f.get('id'):continue
            try:current = after(i)
            except Exception:continue
            if not present(current):
                # the face does not exist yet at this point: it was made by the next feature that builds
                continue
            before = None
            for j in range(i - 1, -1, -1):
                g = features[j]
                if g.get('enabled', True) and g['kind'] not in hidden:
                    try:before = after(j)
                    except Exception:before = None
                    break
            if not present(before):return f['id']
        return None
