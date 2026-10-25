"""Tools that need faces, bodies or profiles start in click-to-select mode."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import Window
from model import Document
from geometry import new_sketch, base_frame, entity, profile_regions, identifier


def box_features(width=20., height=12., depth=10., at=(0., 0.)):
    s = new_sketch(base_frame('XY')); s['entities'] = [entity('rectangle', center=list(at), width=width, height=height)]
    region = profile_regions(s)[0]
    f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=depth, operation='add',
             source=dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes']))
    return [s, f]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.errors = []; self.w.error = self.errors.append
        self.w.resize(1200, 800); self.w.show(); self.app.processEvents()
        self.ws = self.w.workspace

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()
        self.assertEqual(self.errors, [])


class FaceToolTests(Base):
    def setUp(self):
        super().setUp()
        self.w.doc = Document(box_features()); self.w.refresh(); self.app.processEvents()

    def test_shell_starts_in_face_picking_mode(self):
        self.w.start_solid_tool('shell'); self.app.processEvents()
        self.assertTrue(self.ws.solid_face_picking)
        self.assertEqual(self.ws.solid_pick_key, 'faces')

    def test_clicking_a_face_selects_it_and_clicking_again_deselects(self):
        self.w.start_solid_tool('shell'); self.app.processEvents()
        self.w.pick_solid_face(0); self.app.processEvents()
        self.assertEqual(len(self.w.draft['faces']), 1)
        self.w.pick_solid_face(0); self.app.processEvents()
        self.assertEqual(len(self.w.draft['faces']), 0)

    def test_box_of_faces_selects_many_at_once(self):
        self.w.start_solid_tool('shell'); self.app.processEvents()
        self.ws.fit(); self.app.processEvents()
        indices = self.ws.faces_in_rect((0, 0, self.ws.width(), self.ws.height()), True, planar_only=False)
        self.assertGreaterEqual(len(indices), 3)               # the faces turned towards the viewer
        self.w.faces_box(indices, 'add'); self.app.processEvents()
        self.assertEqual(len(self.w.draft['faces']), len(indices))
        self.w.faces_box(indices, 'remove'); self.app.processEvents()
        self.assertEqual(len(self.w.draft['faces']), 0)

    def test_hole_starts_by_asking_for_its_face(self):
        self.w.start_solid_tool('hole'); self.app.processEvents()
        self.assertTrue(self.ws.solid_face_picking)
        self.assertEqual(self.ws.solid_pick_key, 'plane')

    def test_press_pull_starts_in_face_picking_mode(self):
        self.w.start_advanced_tool('press_pull'); self.app.processEvents()
        self.assertTrue(self.ws.solid_face_picking)

    def test_scale_does_not_pick_faces(self):
        self.w.start_advanced_tool('scale'); self.app.processEvents()
        self.assertFalse(self.ws.solid_face_picking)

    def test_shell_follows_the_body_of_the_clicked_face(self):
        two = box_features() + []
        s2, f2 = box_features(at=(60., 0.))
        self.w.doc = Document([two[0], two[1], s2, f2]); self.w.refresh(); self.app.processEvents()
        self.w.start_solid_tool('shell'); self.app.processEvents()
        bodies = self.w.doc.solid.val().Solids()
        self.assertEqual(len(bodies), 2)
        # A face of the second body.
        target = next(i for i, face in enumerate(self.ws.faces) if any(face.isSame(x) for x in bodies[1].Faces()) and face.geomType() == 'PLANE')
        owner_before = self.w.draft.get('body', 0)
        self.w.pick_solid_face(target); self.app.processEvents()
        self.assertNotEqual(self.w.draft['body'], owner_before if owner_before is not None else -1)


class ProfileToolTests(Base):
    def setUp(self):
        super().setUp()
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('rectangle', center=[0, 20], width=10, height=6)]
        self.sketch = s
        self.w.doc = Document([s]); self.w.refresh(); self.app.processEvents()
        self.hit = dict(type='sketch', sketch=s['id'], entities=profile_regions(s)[0]['entities'], holes=[], profile_mode='nested', index=None)

    def test_revolve_takes_the_clicked_profile(self):
        self.w.start_solid_tool('revolve'); self.app.processEvents()
        self.assertTrue(self.ws.extrude_selecting)
        self.w.extrusion_picked(self.hit); self.app.processEvents()
        self.assertEqual(self.w.draft['source']['entities'], self.hit['entities'])
        self.assertNotIn('index', self.w.draft['source'])
        self.assertFalse('sources' in self.w.draft and self.w.draft.get('sources'))    # not treated as an extrusion

    def test_loft_collects_sections_in_click_order_and_toggles(self):
        self.w.start_solid_tool('loft'); self.app.processEvents()
        self.w.extrusion_picked(self.hit); self.app.processEvents()
        self.assertEqual(len(self.w.draft['sections']), 1)
        self.w.extrusion_picked(self.hit); self.app.processEvents()
        self.assertEqual(len(self.w.draft['sections']), 0)

    def test_planar_faces_are_accepted_but_curved_ones_are_not(self):
        self.w.start_solid_tool('revolve'); self.app.processEvents()
        before = dict(self.w.draft.get('source') or {})
        self.w.extrusion_picked({'type': 'curved', 'index': 0}); self.app.processEvents()
        self.assertEqual(dict(self.w.draft.get('source') or {}), before)
        self.w.extrusion_picked({'type': 'face', 'index': 0, 'face': {}}); self.app.processEvents()
        self.assertEqual(self.w.draft['source']['type'], 'face')


if __name__ == '__main__':
    unittest.main()
