"""Panels for the sketch tools Extend, Offset and Transform (move / copy / rotate / scale)."""
import copy
import math
import numpy as np
from PySide6.QtWidgets import QComboBox,QCheckBox,QLabel
from legacy_model import ModelError
from constraints import retain_constraints
from geometry import validate_entity,sample
from i18n import tr

MODIFY_TOOLS = ('offset', 'transform')
HINTS = {
    'extend': 'Click a line or arc near the end you want to lengthen: it runs on to the next curve it meets.',
    'offset': 'Click the curves to offset (a connected chain is taken as it is), then set the distance. Positive grows a closed outline.',
    'transform': 'Click the geometry to change, choose Move, Rotate or Scale, and type the values. Copy keeps the original.',
}


class SketchModifyUI:
    TRANSFORM_MODES = (('Move', 'move'), ('Rotate', 'rotate'), ('Scale', 'scale'))

    def modify_editor(self):
        kind = self.workspace.tool
        w = self.workspace
        self.note(HINTS[kind])
        count = len(w.pattern_selection)
        self.note(f'<b>{count}</b> '+tr('item selected' if count == 1 else 'items selected')+' · '+tr('click geometry to add or remove it; Shift+drag draws a selection box.'))
        if kind == 'offset':
            form = self.form('Offset')
            self.spin(form, 'offset_distance', 'Distance', getattr(self, 'offset_distance', 5.), lambda v: setattr(self, 'offset_distance', v))
            flip = QCheckBox(tr('Other side'));flip.setChecked(getattr(self, 'offset_flip', False))
            flip.toggled.connect(lambda on: setattr(self, 'offset_flip', bool(on)));form.addRow(flip)
            self.button('Create offset', self.apply_offset, True).setEnabled(count > 0)
        else:
            form = self.form('Transform')
            mode = QComboBox()
            for label, value in self.TRANSFORM_MODES:mode.addItem(tr(label), value)
            current = getattr(self, 'transform_mode', 'move');mode.setCurrentIndex(max(0, mode.findData(current)))
            mode.currentIndexChanged.connect(lambda i: (setattr(self, 'transform_mode', mode.itemData(i)), self.show_editor()))
            form.addRow(tr('Operation'), mode)
            if current == 'move':
                self.spin(form, 'transform_dx', 'Distance X', getattr(self, 'transform_dx', 10.), lambda v: setattr(self, 'transform_dx', v))
                self.spin(form, 'transform_dy', 'Distance Y', getattr(self, 'transform_dy', 0.), lambda v: setattr(self, 'transform_dy', v))
            else:
                self.spin(form, 'transform_cx', 'Center X', getattr(self, 'transform_cx', 0.), lambda v: setattr(self, 'transform_cx', v))
                self.spin(form, 'transform_cy', 'Center Y', getattr(self, 'transform_cy', 0.), lambda v: setattr(self, 'transform_cy', v))
                if current == 'rotate':
                    self.spin(form, 'transform_angle', 'Angle', getattr(self, 'transform_angle', 90.), lambda v: setattr(self, 'transform_angle', v))
                else:
                    self.spin(form, 'transform_factor', 'Scale factor', getattr(self, 'transform_factor', 2.), lambda v: setattr(self, 'transform_factor', v), True)
                self.button('Use the center of the selection', self.center_on_selection).setEnabled(count > 0)
            keep = QCheckBox(tr('Copy (keep the original)'));keep.setChecked(getattr(self, 'transform_copy', False))
            keep.toggled.connect(lambda on: setattr(self, 'transform_copy', bool(on)));form.addRow(keep)
            self.button('Apply transform', self.apply_transform, True).setEnabled(count > 0)
        self.button('Done', lambda: self.set_tool('select'))

    def selection_center(self):
        points = []
        for i in self.workspace.pattern_selection:
            if 0 <= i < len(self.draft['entities']):
                points.append(np.asarray(sample(self.draft['entities'][i], 16), float))
        if not points:
            return None
        stack = np.vstack(points)
        return (stack.min(axis=0) + stack.max(axis=0)) / 2

    def center_on_selection(self):
        center = self.selection_center()
        if center is not None:
            self.transform_cx, self.transform_cy = float(center[0]), float(center[1]);self.show_editor()

    def apply_offset(self):
        from sketch_tools import offset_entities
        try:
            chosen = sorted(self.workspace.pattern_selection)
            created = self.run_busy('Offsetting curves…', lambda report: offset_entities(copy.deepcopy(self.draft['entities']), chosen, getattr(self, 'offset_distance', 5.), getattr(self, 'offset_flip', False)))
            self.sketch_change();self.draft['entities'].extend(created)
            self.workspace.pattern_selection.clear();self.workspace.update();self.show_editor()
            self.show_status(f"{len(created)} "+tr('curves created. Undo reverses the offset.'))
        except Exception as error:self.error(error)

    def apply_transform(self):
        from sketch_tools import transform_selection
        try:
            chosen = sorted(i for i in self.workspace.pattern_selection if 0 <= i < len(self.draft['entities']))
            if any(self.draft['entities'][i].get('projection') for i in chosen) and not getattr(self, 'transform_copy', False):
                raise ModelError('Break the projection link before editing this geometry.')
            mode = getattr(self, 'transform_mode', 'move')
            entities, moved = transform_selection(copy.deepcopy(self.draft['entities']), chosen, mode, getattr(self, 'transform_copy', False),
                                                  dx=getattr(self, 'transform_dx', 10.), dy=getattr(self, 'transform_dy', 0.), angle=getattr(self, 'transform_angle', 90.),
                                                  factor=getattr(self, 'transform_factor', 2.), center=(getattr(self, 'transform_cx', 0.), getattr(self, 'transform_cy', 0.)))
            self.sketch_change()
            removed = 0
            if not getattr(self, 'transform_copy', False):
                # Constraints that pin moved geometry would fight the move: they are dropped, as in Fusion's Move.
                ids = set(moved)
                kept = [c for c in self.draft.get('constraints', []) if not any(r.get('entity') in ids for r in c['refs'])]
                removed = len(self.draft.get('constraints', [])) - len(kept)
                candidate = copy.deepcopy(self.draft);candidate['constraints'] = kept
                self.draft.update(entities=entities, constraints=kept)
            else:
                self.draft['entities'] = entities
            self.workspace.pattern_selection.clear();self.workspace.update();self.show_editor()
            message = tr('Transformed.')
            if removed:message += ' ' + f'{removed} ' + tr('constraints on the moved geometry were removed.')
            self.show_status(message)
        except Exception as error:self.error(error)
