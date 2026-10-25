"""Live drag outlines must match what Apply builds, survive refreshes, and cover sketch tools."""
import copy
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app import Window
from model import Document, edge_reference
from geometry import new_sketch, base_frame, entity, identifier, profile_regions
import handle_previews as H


def rectangle_sketch():
    s = new_sketch(base_frame('XY')); s['entities'] = [entity('rectangle', center=[0, 0], width=20, height=12)]; return s


def extrude_feature(sketch, depth=10):
    region = profile_regions(sketch)[0]
    return dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=depth, operation='add',
                source=dict(type='sketch', sketch=sketch['id'], entities=region['entities'], holes=region['holes']))


def cloud(lines):
    return sorted({tuple(np.round(p, 5)) for line in lines for p in np.asarray(line)})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.errors = []; self.w.error = self.errors.append
        self.w.show(); self.app.processEvents(); self.w.workspace.snap_enabled = False

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()
        self.assertEqual(self.errors, [])

    def box_document(self):
        s = rectangle_sketch(); doc = Document([s, extrude_feature(s)])
        self.w.doc = doc; self.w.refresh(); return doc

    def start_fillet(self, radius=3., auto_fit=True):
        doc = self.box_document()
        self.w.new_edge('fillet')
        edge = [e for e in doc.solid.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        self.w.draft.update(edge_refs=[edge_reference(edge, doc.solid)], radius=radius, auto_fit=auto_fit)
        self.w.show_editor(); self.app.processEvents()
        return doc


class SolidToolOutlineTests(Base):
    def test_live_outline_equals_what_apply_builds(self):
        doc = self.start_fillet(3.)
        outcome = self.w.exact_feature_outlines(); lines, error = outcome[0], outcome[1]
        self.assertIsNone(error)
        built = Document(copy.deepcopy(doc.features) + [copy.deepcopy(self.w.draft)])
        polyline = lambda e: np.array([e.positionAt(float(t)).toTuple() for t in np.linspace(0, 1, 2 if e.geomType() == 'LINE' else 40)])
        expected = H.changed_outlines(doc.solid.val(), built.solid.val(), polyline)
        self.assertEqual(cloud(lines), cloud(expected))
        self.assertEqual(len(lines), 4)   # two rails and two end arcs

    def test_exact_outline_survives_unrelated_refreshes(self):
        self.start_fillet(3.)
        g = self.w.workspace.gizmo
        g.compute_exact()
        self.assertIsNotNone(g.exact_result)
        for _ in range(3):
            self.w.sync_gizmo()
        self.assertIsNotNone(g.exact_result)
        self.assertFalse(g.exact_timer.isActive())

    def test_changing_the_size_invalidates_and_recomputes(self):
        self.start_fillet(3.)
        g = self.w.workspace.gizmo
        g.compute_exact(); first = cloud(g.exact_result[1])
        self.w.widgets['radius'].setValue(1.5); self.app.processEvents()
        self.assertTrue(g.exact_timer.isActive() or g.exact_result is None)
        g.compute_exact()
        self.assertNotEqual(first, cloud(g.exact_result[1]))
        self.assertAlmostEqual(g.exact_result[0], 1.5)

    def test_unbuildable_size_reports_an_error_instead_of_a_stale_outline(self):
        self.start_fillet(500., auto_fit=False)
        g = self.w.workspace.gizmo
        g.compute_exact()
        self.assertIsNotNone(g.exact_result[2])
        self.assertIsNone(g.exact_result[1])

    def test_fillet_arrow_cannot_exceed_the_largest_size_that_builds(self):
        doc = self.start_fillet(34.)               # far more than a 12 mm wide, 10 mm tall box allows
        g = self.w.workspace.gizmo
        lo, hi = g.state['limits']
        self.assertIsNotNone(hi)
        self.assertLess(hi, 12.0)
        self.assertLessEqual(g.state['values'][0], hi + 1e-9)       # shown at the size it can really make
        g.set_value(500.); self.app.processEvents()
        self.assertLessEqual(self.w.draft['radius'], hi + 1e-9)
        # And that capped size really builds without needing auto-fit to shrink it.
        from model import apply_edge_operation
        edge = [e for e in doc.solid.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        apply_edge_operation(doc.solid, [edge], 'fillet', self.w.draft['radius'])

    def test_enter_applies_the_active_solid_tool(self):
        doc = self.start_fillet(2.)
        count = len(self.w.doc.features)
        QTest.keyClick(self.w.workspace, Qt.Key_Return); self.app.processEvents()
        self.assertEqual(len(self.w.doc.features), count + 1)
        self.assertEqual(self.w.doc.features[-1]['kind'], 'fillet')
        self.assertIsNone(self.w.draft)

    def test_enter_in_the_arrow_value_box_commits_the_typed_size_and_applies(self):
        self.start_fillet(2.)
        g = self.w.workspace.gizmo
        g.editor.setValue(1.5)                  # typing a value into the on-canvas box
        g.editor.setFocus(); self.app.processEvents()
        QTest.keyClick(g.editor, Qt.Key_Return); self.app.processEvents()
        self.assertEqual(self.w.doc.features[-1]['kind'], 'fillet')
        self.assertAlmostEqual(self.w.doc.features[-1]['radius'], 1.5)

    def test_value_box_is_docked_at_the_bottom_left_and_never_over_the_arrow(self):
        self.start_fillet(3.)
        g = self.w.workspace.gizmo; ws = self.w.workspace
        self.w.workspace.repaint(); self.app.processEvents()
        box = g.editor.geometry()
        self.assertGreater(box.top(), ws.height() * 0.6)          # in the lower part of the view
        self.assertLess(box.left(), ws.width() * 0.6)             # and to the left
        for base, tip, unit in g.handles():
            for point in (base, tip):
                self.assertFalse(box.adjusted(-4, -4, 4, 4).contains(int(point[0]), int(point[1])))

    def test_real_outline_stays_visible_while_the_arrow_is_dragged(self):
        self.start_fillet(3.)
        g = self.w.workspace.gizmo
        g.compute_exact(); self.assertIsNotNone(g.exact_result)
        g.dragging = True
        g.schedule_exact()                      # a drag step must not throw the real outline away
        self.assertIsNotNone(g.exact_result)
        # The live preview of a fillet comes from cached geometry: no kernel rebuild starts mid-drag.
        self.assertFalse(g.exact_timer.isActive())
        g.exact_result = None
        g.release = g.release                   # the real outline is requested again when the arrow is let go
        g.consume_release = True; g.release()
        self.assertTrue(g.exact_timer.isActive())
        g.exact_timer.stop()

    def test_fillet_arrow_starts_where_the_edge_was_picked(self):
        doc = self.start_fillet(2.)
        edge = [e for e in doc.solid.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        pick = np.asarray(edge.positionAt(.8).toTuple())
        self.w.edge_pick_point = pick; self.w.gizmo_geometry_key = None
        self.w.sync_gizmo(); self.app.processEvents()
        origin = self.w.workspace.gizmo.state['origin']
        spacing = edge.Length() / 40.0                       # the pick is matched to a 41-sample polyline
        self.assertLess(float(np.linalg.norm(origin - pick)), spacing + 1e-6)
        # not the old default at the middle of the edge
        self.assertGreater(float(np.linalg.norm(origin - np.asarray(edge.positionAt(.5).toTuple()))), edge.Length() * .2)

    def test_chamfer_arrow_also_starts_at_the_picked_point(self):
        doc = self.box_document()
        self.w.new_edge('chamfer')
        edge = [e for e in doc.solid.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        self.w.draft.update(edge_refs=[edge_reference(edge, doc.solid)], radius=1.5)
        pick = np.asarray(edge.positionAt(.2).toTuple()); self.w.edge_pick_point = pick
        self.w.show_editor(); self.app.processEvents()
        origin = self.w.workspace.gizmo.state['origin']
        self.assertLess(float(np.linalg.norm(origin - pick)), edge.Length() / 40. + 1e-6)

    def test_face_tool_arrow_starts_at_the_clicked_point_on_the_face(self):
        s = rectangle_sketch(); doc = Document([s, extrude_feature(s)]); self.w.doc = doc; self.w.refresh()
        self.w.start_solid_tool('shell')
        top = next(i for i, f in enumerate(self.w.workspace.faces) if f.normalAt().z > .9)
        clicked = np.array([6.0, 2.5, 10.0])                  # on the top face, away from its centre
        self.w.workspace.last_face_pick = clicked
        self.w.enable_face_pick(); self.w.pick_solid_face(top); self.app.processEvents()
        origin = self.w.workspace.gizmo.state['origin']
        np.testing.assert_allclose(origin, clicked, atol=1e-6)

    def test_extrusion_outline_turns_red_when_it_runs_into_a_body(self):
        s1 = rectangle_sketch(); s2 = new_sketch(base_frame('XY'))
        s2['entities'] = [entity('rectangle', center=[0, 0], width=6, height=4)]
        self.w.doc = Document([s1, extrude_feature(s1, 10), s2]); self.w.refresh(); self.w.start_extrude()
        region = profile_regions(s2)[0]
        self.w.extrusion_picked(dict(type='sketch', sketch=s2['id'], entities=region['entities'], holes=region['holes']))
        self.w.draft['operation'] = 'add'; self.app.processEvents()
        g = self.w.workspace.gizmo
        self.w.widgets['depth'].setValue(5.); self.app.processEvents(); g.compute_exact()
        hit = g.exact_result[4]
        self.assertTrue(hit)                                  # goes up into the 10 mm body: intersects
        self.assertEqual(hit['hit'], [0])                     # which body it runs into
        self.assertEqual(self.w.workspace.faded_bodies, {0})  # that body is shown at half opacity
        outline = np.vstack([np.asarray(l) for l in g.exact_result[1]])
        segments = sum(len(np.asarray(l)) - 1 for l in g.exact_result[1])
        self.assertEqual(segments, 12)                        # the whole prism (4 + 4 + 4 edges) is outlined, even inside the body
        self.assertAlmostEqual(float(outline[:, 2].max()), 5.0, places=4)
        self.w.widgets['depth'].setValue(-5.); self.app.processEvents(); g.compute_exact()
        self.assertFalse(g.exact_result[4])                   # goes down into free space
        self.assertEqual(self.w.workspace.faded_bodies, set())
        # A cut is meant to enter the body, so it is not flagged.
        self.w.draft['operation'] = 'cut'; self.w.widgets['depth'].setValue(5.); self.app.processEvents(); g.compute_exact()
        self.assertFalse(g.exact_result[4])

    def test_extrude_arrow_also_gets_an_exact_outline(self):
        s = rectangle_sketch(); self.w.doc = Document([s]); self.w.refresh(); self.w.start_extrude()
        region = profile_regions(s)[0]
        self.w.extrusion_picked(dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes']))
        self.w.widgets['depth'].setValue(10.)       # a new extrusion starts at 0
        self.app.processEvents()
        g = self.w.workspace.gizmo; g.compute_exact()
        self.assertIsNone(g.exact_result[2]); self.assertTrue(sum(len(np.asarray(l)) - 1 for l in g.exact_result[1]) >= 8)


class SketchToolGizmoTests(Base):
    def start_sketch(self):
        self.w.doc = Document([]); self.w.refresh(); self.w.start_sketch()
        self.w.support_picked({'type': 'plane', 'plane': 'XY'}); self.app.processEvents()

    def add_corner(self):
        self.w.draft['entities'] = [entity('line', a=[0, 0], b=[20, 0]), entity('line', a=[0, 0], b=[0, 20])]
        self.w.workspace.active = self.w.draft; self.w.show_editor()

    def test_corner_tools_pick_first_then_arrow_preview_then_apply(self):
        self.start_sketch(); self.add_corner()
        self.w.set_tool('fillet'); self.w.sketch_corner_size = 4.
        g = self.w.workspace.gizmo
        # Nothing is applied or previewed by merely hovering; picking a corner selects it.
        self.w.workspace.cursor = [0.2, 0.2]; self.w.sync_gizmo()
        self.assertIsNone(g.state)
        before = len(self.w.draft['entities'])
        self.w.toggle_sketch_corner([0.2, 0.2]); self.app.processEvents()
        self.assertEqual(len(self.w.draft['entities']), before)
        self.assertIsNotNone(g.state); self.assertEqual(g.state['kind'], 'value')
        self.assertTrue(len(g.state['ghost'](4.)) >= 2)
        self.w.apply_sketch_corners()
        self.assertEqual(len(self.w.draft['entities']), before + 1)
        self.assertEqual(self.w.draft['entities'][-1]['kind'], 'arc')
        self.assertEqual(self.w.sketch_corners, [])

    def test_clicking_a_selected_corner_again_deselects_it(self):
        self.start_sketch(); self.add_corner(); self.w.set_tool('chamfer')
        self.w.toggle_sketch_corner([0.1, 0.1]); self.assertEqual(len(self.w.sketch_corners), 1)
        self.w.toggle_sketch_corner([0.2, 0.0]); self.assertEqual(self.w.sketch_corners, [])

    def test_corner_arrow_is_capped_at_the_largest_size_the_corner_accepts(self):
        self.start_sketch(); self.add_corner(); self.w.set_tool('fillet'); self.w.sketch_corner_size = 1.
        self.w.toggle_sketch_corner([0.2, 0.2]); self.app.processEvents()
        g = self.w.workspace.gizmo
        top = g.state['limits'][1]
        self.assertIsNotNone(top)
        self.assertLess(top, 20.0 + 1e-6)             # the lines are 20 mm long
        g.axis = 0; g.set_value(1000.); self.app.processEvents()
        self.assertLessEqual(self.w.sketch_corner_size, top + 1e-9)
        self.assertGreater(self.w.sketch_corner_size, 1.0)
        self.w.apply_sketch_corners()                 # the capped size is one that really builds
        self.assertEqual(self.w.draft['entities'][-1]['kind'], 'arc')

    def test_dragging_the_corner_arrow_changes_the_size_field(self):
        self.start_sketch(); self.add_corner()
        self.w.set_tool('chamfer'); self.w.sketch_corner_size = 2.
        self.w.toggle_sketch_corner([0.2, 0.2]); self.app.processEvents()
        g = self.w.workspace.gizmo
        g.axis = 0; g.set_value(5.); self.app.processEvents()
        self.assertAlmostEqual(self.w.sketch_corner_size, 5.)

    def test_corner_preview_shows_the_new_arc_and_what_it_removes(self):
        self.start_sketch()
        self.w.draft['entities'] = [entity('circle', center=[0, 0], radius=20), entity('rectangle', center=[0, -20], width=18, height=16)]
        self.w.workspace.active = self.w.draft; self.w.show_editor()
        self.w.set_tool('fillet'); self.w.sketch_corner_size = 3.
        self.w.toggle_sketch_corner([9.0, -17.86]); self.app.processEvents()
        g = self.w.workspace.gizmo
        out = g.state['ghost'](3.)
        self.assertIsInstance(out, dict)
        self.assertEqual(len(out['lines']), 1)                      # only the new corner arc, not whole shapes
        self.assertTrue(len(out['removed']) >= 1)                   # and the parts of the sketch it cuts away
        arc = np.vstack(out['lines'])
        self.assertLess(np.ptp(arc[:, 0]) + np.ptp(arc[:, 1]), 20)   # small, local to the corner

    def test_enter_applies_picked_sketch_corners(self):
        self.start_sketch(); self.add_corner(); self.w.set_tool('fillet'); self.w.sketch_corner_size = 3.
        self.w.toggle_sketch_corner([0.2, 0.2]); self.app.processEvents()
        before = len(self.w.draft['entities'])
        QTest.keyClick(self.w.workspace, Qt.Key_Return); self.app.processEvents()
        self.assertEqual(len(self.w.draft['entities']), before + 1)
        self.assertEqual(self.w.draft['entities'][-1]['kind'], 'arc')

    def test_corner_arrow_starts_at_the_picked_corner(self):
        self.start_sketch(); self.add_corner(); self.w.set_tool('fillet'); self.w.sketch_corner_size = 4.
        self.w.toggle_sketch_corner([0.3, 0.2]); self.app.processEvents()
        g = self.w.workspace.gizmo
        np.testing.assert_allclose(g.state['origin'], [0., 0., 0.], atol=1e-6)       # the corner of the two lines
        # and it points into the corner (toward the centre of the rounding), along the bisector
        d = np.asarray(g.state['directions'][0]); d = d / np.linalg.norm(d)
        np.testing.assert_allclose(d, np.array([1., 1., 0.]) / np.sqrt(2), atol=1e-6)

    def test_union_corner_fillet_goes_on_the_outside_like_the_solid_fillet(self):
        """Clicking right on the crossing of a circle and a rectangle must round the outline's
        concave corner (as the extruded body's edge fillet does), not an inner crossing."""
        from sketch_corners import modify_corner
        from geometry import sample
        circle = entity('circle', center=[0, 0], radius=20); box = entity('rectangle', center=[0, -20], width=18, height=16)
        info = {}
        result = modify_corner([circle, box], [9.0, -17.8606], 'fillet', 3.0, 1.0, info)
        np.testing.assert_allclose(info['vertex'], [9.0, -17.8606], atol=1e-3)
        arc = np.asarray(sample(result[-1], 40), float)
        mid = arc[len(arc) // 2]
        outside_circle = np.hypot(*mid) > 20 - 1e-6
        outside_box = not (abs(mid[0]) < 9 and -28 < mid[1] < -12)
        self.assertTrue(outside_circle and outside_box)

    def test_rectangular_pattern_has_two_spacing_arrows_and_copy_preview(self):
        self.start_sketch()
        self.w.draft['entities'] = [entity('rectangle', center=[0, 0], width=6, height=4)]
        self.w.workspace.active = self.w.draft
        self.w.set_tool('rectangular')
        self.w.workspace.pattern_selection = {0}
        self.w.pattern_columns, self.w.pattern_rows = 3, 2
        self.w.sync_gizmo(); self.app.processEvents()
        g = self.w.workspace.gizmo
        self.assertEqual(g.state['kind'], 'spacing'); self.assertEqual(len(g.state['values']), 2)
        near = g.state['ghost']((10., 8.)); far = g.state['ghost']((20., 8.))
        self.assertTrue(near and far)
        self.assertGreater(np.vstack(far)[:, 0].max(), np.vstack(near)[:, 0].max())
        g.axis = 0; g.set_value(15.); self.app.processEvents()
        self.assertAlmostEqual(self.w.pattern_spacing_x, 15.)

    def test_circular_pattern_shows_a_preview_without_arrows(self):
        self.start_sketch()
        self.w.draft['entities'] = [entity('circle', center=[10, 0], radius=2)]
        self.w.workspace.active = self.w.draft
        self.w.set_tool('circular'); self.w.workspace.pattern_selection = {0}
        self.w.pattern_center = [0.0, 0.0]; self.w.pattern_copies = 3
        self.w.sync_gizmo(); self.app.processEvents()
        g = self.w.workspace.gizmo
        self.assertEqual(g.state['kind'], 'preview'); self.assertEqual(g.handles(), [])
        self.assertEqual(len(g.state['ghost'](0.)), 3)


if __name__ == '__main__':
    unittest.main()
