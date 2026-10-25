"""Live preview for tools without a drag arrow."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication

from app import Window
from model import Document
from geometry import new_sketch, base_frame, entity, profile_regions, identifier


def box_document():
    s = new_sketch(base_frame('XY')); s['entities'] = [entity('rectangle', center=[0, 0], width=20, height=12)]
    region = profile_regions(s)[0]
    f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=10., operation='add',
             source=dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes']))
    return Document([s, f])


class LivePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.errors = []; self.w.error = self.errors.append
        self.w.resize(1200, 800); self.w.show(); self.app.processEvents()
        self.w.doc = box_document(); self.w.refresh(); self.app.processEvents()
        self.w.live_preview = True

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()
        self.assertEqual(self.errors, [])

    def test_checkbox_is_offered_for_tools_without_arrows_only(self):
        self.w.start_solid_tool('draft'); self.app.processEvents()
        self.assertIn('live_preview', self.w.widgets)
        self.w.cancel(); self.app.processEvents()
        self.w.start_extrude(); self.app.processEvents()
        self.w.extrusion_picked(dict(type='sketch', sketch=list(self.w.doc.sketches)[0], entities=[], holes=[]))
        self.assertNotIn('live_preview', self.w.widgets)

    def test_a_parameter_change_refreshes_the_preview_by_itself(self):
        self.w.start_solid_tool('draft'); self.app.processEvents()
        calls = []
        original = self.w.preview_feature
        self.w.preview_feature = lambda quiet=False: calls.append(quiet) or original(quiet=quiet)
        self.w.widgets['angle'].setValue(5.); self.app.processEvents()
        self.assertTrue(self.w.live_timer.isActive())
        self.w.run_live_preview()                         # what the timer does after its delay
        self.assertEqual(calls, [True])

    def test_switching_it_off_stops_automatic_previews(self):
        self.w.start_solid_tool('draft'); self.app.processEvents()
        self.w.widgets['live_preview'].setChecked(False)
        self.assertFalse(self.w.live_preview)
        self.w.widgets['angle'].setValue(4.); self.app.processEvents()
        timer = getattr(self.w, 'live_timer', None)
        self.assertFalse(timer is not None and timer.isActive())

    def test_an_unbuildable_value_is_reported_quietly(self):
        self.w.start_solid_tool('shell'); self.app.processEvents()
        face = next(i for i, fc in enumerate(self.w.workspace.faces) if fc.geomType() == 'PLANE')
        self.w.pick_solid_face(face); self.app.processEvents()
        self.w.preview_feature(quiet=True); self.app.processEvents()
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
