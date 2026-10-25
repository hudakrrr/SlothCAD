"""Rubber-band (box) selection: profiles and faces for extrusion, edges, sketch entities."""
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


def circles_sketch(count=6, spacing=14.):
    s = new_sketch(base_frame('XY'))
    s['entities'] = [entity('circle', center=[i * spacing, 0], radius=4) for i in range(count)]
    return s


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

    def screen(self, point):
        return self.ws.project_local([point], base_frame('XY'))[0]

    def drag(self, a, b, modifiers=Qt.ShiftModifier):
        """Left-button drag from a to b (screen coordinates) with modifiers held."""
        QTest.mousePress(self.ws, Qt.LeftButton, modifiers, QPoint(int(a[0]), int(a[1])))
        steps = 6
        for i in range(1, steps + 1):
            x = a[0] + (b[0] - a[0]) * i / steps
            y = a[1] + (b[1] - a[1]) * i / steps
            QTest.mouseMove(self.ws, QPoint(int(x), int(y)))
            self.app.processEvents()
            self.ws.flush_motion()
        QTest.mouseRelease(self.ws, Qt.LeftButton, modifiers, QPoint(int(b[0]), int(b[1])))
        self.app.processEvents()


class ExtrudeBoxTests(Base):
    def setUp(self):
        super().setUp()
        self.sketch = circles_sketch()
        self.doc = Document([self.sketch]); self.w.doc = self.doc; self.w.refresh(); self.app.processEvents()
        self.w.start_extrude(); self.app.processEvents()
        self.ws.align(base_frame('XY'), animate=False); self.ws.fit(); self.app.processEvents()

    def test_window_box_selects_the_profiles_fully_inside(self):
        self.drag(self.screen([-8, 10]), self.screen([38, -10]))       # circles 0, 1, 2 (x = 0, 14, 28)
        self.assertEqual(len(self.w.extrude_hits), 3)
        self.assertEqual(len(self.w.draft['sources']), 3)

    def test_crossing_box_selects_what_it_touches(self):
        self.drag(self.screen([66, 10]), self.screen([41, -10]))       # right to left
        self.assertGreaterEqual(len(self.w.extrude_hits), 2)

    def test_window_box_ignores_partially_covered_profiles(self):
        self.drag(self.screen([-8, 10]), self.screen([2, -10]))        # cuts through circle 0
        self.assertEqual(len(self.w.extrude_hits), 0)

    def test_second_box_adds_and_ctrl_shift_removes(self):
        self.drag(self.screen([-8, 10]), self.screen([10, -10]))
        self.assertEqual(len(self.w.extrude_hits), 1)
        self.drag(self.screen([20, 10]), self.screen([50, -10]))       # circles at x = 28, 42
        self.assertEqual(len(self.w.extrude_hits), 3)
        self.drag(self.screen([20, 10]), self.screen([50, -10]), modifiers=Qt.ShiftModifier | Qt.ControlModifier)
        self.assertEqual(len(self.w.extrude_hits), 1)

    def test_plain_drag_still_orbits_and_does_not_select(self):
        self.drag(self.screen([-8, 10]), self.screen([38, -10]), modifiers=Qt.NoModifier)
        self.assertEqual(len(self.w.extrude_hits), 0)
        self.assertIsNone(self.ws.box)

    def test_drag_selects_option_makes_plain_drag_a_box(self):
        self.ws.drag_selects = True
        self.drag(self.screen([-8, 10]), self.screen([38, -10]), modifiers=Qt.NoModifier)
        self.assertEqual(len(self.w.extrude_hits), 3)

    def test_select_all_profiles_and_extrude_them_together(self):
        self.w.select_all_profiles(); self.app.processEvents()
        self.assertEqual(len(self.w.extrude_hits), 6)
        self.w.widgets['depth'].setValue(5.); self.w.apply_feature(); self.app.processEvents()
        self.assertEqual(len(self.w.doc.solid.val().Solids()), 6)
        expected = 6 * np.pi * 16 * 5
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(), expected, delta=expected * .01)

    def test_box_selection_extrudes_only_the_boxed_profiles(self):
        self.drag(self.screen([-8, 10]), self.screen([38, -10]))
        self.w.widgets['depth'].setValue(4.); self.w.apply_feature(); self.app.processEvents()
        self.assertEqual(len(self.w.doc.solid.val().Solids()), 3)


class SketchBoxTests(Base):
    def setUp(self):
        super().setUp()
        self.w.doc = Document([]); self.w.refresh(); self.w.start_sketch()
        self.w.support_picked({'type': 'plane', 'plane': 'XY'}); self.app.processEvents()
        self.w.draft['entities'] = [entity('line', a=[i * 10, 0], b=[i * 10, 8]) for i in range(6)]
        self.ws.active = self.w.draft; self.w.show_editor(); self.w.set_tool('select'); self.app.processEvents()
        self.ws.fit(); self.app.processEvents()

    def sc(self, p):
        return self.ws.project_local([p], self.ws.active_frame)[0]

    def test_box_selects_sketch_entities_and_delete_removes_them(self):
        self.drag(self.sc([-3, 12]), self.sc([23, -3]))                # lines 0, 1, 2
        self.assertEqual(self.ws.pattern_selection, {0, 1, 2})
        self.w.delete_entity(); self.app.processEvents()
        self.assertEqual(len(self.w.draft['entities']), 3)
        self.assertEqual(self.ws.pattern_selection, set())

    def test_toggle_construction_on_the_selection(self):
        self.drag(self.sc([-3, 12]), self.sc([13, -3]))
        self.w.toggle_selected_construction()
        self.assertTrue(self.w.draft['entities'][0].get('construction'))
        self.assertTrue(self.w.draft['entities'][1].get('construction'))
        self.assertFalse(self.w.draft['entities'][2].get('construction'))
        self.assertGreater(len(self.w.sketch_undo), 0)

    def test_box_in_the_pattern_tool_feeds_its_source_selection(self):
        self.w.set_tool('circular')
        self.drag(self.sc([-3, 12]), self.sc([33, -3]))
        self.assertEqual(self.ws.pattern_selection, {0, 1, 2, 3})


class EdgeBoxTests(Base):
    def test_box_selects_many_edges_at_once(self):
        s = new_sketch(base_frame('XY')); s['entities'] = [entity('rectangle', center=[0, 0], width=20, height=12)]
        region = profile_regions(s)[0]
        f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=8., operation='add',
                 source=dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes']))
        self.w.doc = Document([s, f]); self.w.refresh(); self.app.processEvents()
        self.w.new_edge('fillet'); self.app.processEvents()
        self.ws.fit(); self.app.processEvents()
        w, h = self.ws.width(), self.ws.height()
        self.drag((5, 5), (w - 5, h - 5))                               # a window around the whole body
        self.assertGreaterEqual(len(self.ws.selected_edges), 12)
        self.assertEqual(len(self.w.draft.get('edge_refs', [])), len(self.ws.selected_edge_objects()))


if __name__ == '__main__':
    unittest.main()
