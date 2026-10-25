"""Startup view, sketch-mode camera transitions, orbit while using tools, and drag previews."""
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import cadquery as cq
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import handle_previews as H
import workspace as W
from workspace import Workspace, blend_rotation, plane_selector_center, plane_selector_size


def mouse(kind, point, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(kind, QPointF(*point), QPointF(*point), button, buttons, Qt.NoModifier)


class ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Workspace(); self.w.resize(600, 400); self.w.set_mode('model')

    def tearDown(self):
        self.w.motion_timer.stop(); self.w.deleteLater(); self.app.processEvents()

    def test_orbit_view_is_a_proper_rotation_for_every_preset(self):
        for name in ('Iso', 'Top', 'Front', 'Right'):
            self.w.preset(name)
            self.assertAlmostEqual(np.linalg.det(self.w.rotation()), 1.0, places=9, msg=name)

    def test_top_preset_matches_xy_sketch_view(self):
        self.w.preset('Top')
        np.testing.assert_allclose(self.w.rotation(), np.eye(3), atol=1e-9)

    def test_start_view_centres_on_the_middle_of_the_three_plane_squares(self):
        size = plane_selector_size(self.w.span)
        np.testing.assert_allclose(self.w.center, np.full(3, size / 3), atol=1e-9)
        np.testing.assert_allclose(plane_selector_center(60.), np.full(3, 7.0), atol=1e-9)

    def test_blend_rotation_endpoints_and_orthonormal_path(self):
        a = self.w.rotation().copy(); b = np.eye(3)
        np.testing.assert_allclose(blend_rotation(a, b, 0), a, atol=1e-9)
        np.testing.assert_allclose(blend_rotation(a, b, 1), b, atol=1e-9)
        for t in np.linspace(0, 1, 9):
            m = blend_rotation(a, b, t)
            np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-9)
            self.assertAlmostEqual(np.linalg.det(m), 1.0, places=9)

    def test_orbit_allowed_in_tool_modes_but_not_while_sketching(self):
        for mode in ('model', 'support', 'extrude', 'edge'):
            self.w.set_mode(mode); self.assertTrue(self.w.orbit_allowed(), mode)
        self.assertFalse(Workspace.orbit_allowed(type('Fake', (), {'mode': 'sketch'})()))

    def test_left_drag_orbits_in_edge_picking_mode_without_toggling_an_edge(self):
        self.w.set_mode('edge')
        yaw = self.w.yaw
        self.w.mousePressEvent(mouse(QEvent.MouseButtonPress, (100, 100)))
        self.w.queue_motion(QPointF(160, 100), Qt.LeftButton)
        self.w.flush_motion()
        self.w.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (160, 100), buttons=Qt.NoButton))
        self.assertNotAlmostEqual(self.w.yaw, yaw)
        self.assertFalse(self.w.selected_edges)

    def test_animation_is_skipped_when_not_visible(self):
        start = self.w.camera_state()
        self.w.align({'origin': [0, 0, 0], 'u': [1, 0, 0], 'normal': [0, 0, 1]})
        self.assertIsNone(self.w.camera_animation)
        np.testing.assert_allclose(self.w.rotation(), np.eye(3), atol=1e-9)
        self.assertFalse(np.allclose(start['R'], np.eye(3)))

    def test_transition_runs_and_ends_exactly_at_the_target(self):
        old = W.ANIMATIONS
        W.ANIMATIONS = True
        try:
            self.w.show(); self.app.processEvents()
            target_start = self.w.camera_state()
            self.w.align({'origin': [0, 0, 0], 'u': [1, 0, 0], 'normal': [0, 0, 1]})
            self.assertIsNotNone(self.w.camera_animation)
            # Mid-transition the view is a valid rotation between the two.
            self.w._camera_step(.5)
            self.assertAlmostEqual(np.linalg.det(self.w.rotation()), 1.0, places=6)
            self.w.finish_camera_animation()
            np.testing.assert_allclose(self.w.rotation(), np.eye(3), atol=1e-9)
            self.assertFalse(np.allclose(target_start['R'], self.w.rotation()))
        finally:
            W.ANIMATIONS = old

    def test_grid_is_lighter_while_the_camera_moves_and_full_when_still(self):
        from unittest.mock import patch
        self.w.show(); self.app.processEvents()
        self.w.camera_busy = False; self.w.background_key = None
        with patch.object(self.w, 'draw_grid_labels') as labels, patch.object(self.w, 'draw_segments', wraps=self.w.draw_segments) as segments:
            self.w.cached_background()
            full = sum(len(call.args[1]) for call in segments.call_args_list)
            self.assertTrue(labels.called)
        self.w.camera_busy = True
        with patch.object(self.w, 'draw_grid_labels') as labels, patch.object(self.w, 'draw_segments', wraps=self.w.draw_segments) as segments:
            self.w.cached_background()
            light = sum(len(call.args[1]) for call in segments.call_args_list)
            self.assertFalse(labels.called)
        self.assertLess(light, full * .5)

    def test_camera_motion_marks_busy_and_settles_back(self):
        from PySide6.QtTest import QTest
        self.w.show(); self.app.processEvents()
        self.w.queue_motion(QPointF(100, 100), Qt.NoButton)
        self.w.pending_zoom = 1.; self.w.flush_motion()
        self.assertTrue(self.w.camera_busy)
        QTest.qWait(260)
        self.assertFalse(self.w.camera_busy)

    def test_grid_segments_cover_the_view_and_split_major_lines(self):
        low, high, minor, major = self.w.grid_segments(np.array([-12., -7.]), np.array([12., 7.]), 1.0)
        self.assertEqual(len(minor) + len(major), 25 + 15)
        self.assertEqual(len(major), 5 + 3)                      # indices -10,-5,0,5,10 and -5,0,5
        self.assertEqual(minor.shape[1:], (2, 2))


class PreviewTests(unittest.TestCase):
    def station_entry(self, solid, edge):
        faces = [f for f in solid.Faces() if any(edge.isSame(e) for e in f.Edges())]
        key = lambda face: tuple(round(float(c), 4) for c in face.Center().toTuple())
        stations = []
        for t in (0., 1.):
            point = np.asarray(edge.positionAt(t).toTuple()); tangent = np.asarray(edge.tangentAt(t).toTuple())
            n1 = np.asarray(faces[0].normalAt(cq.Vector(*point)).toTuple()); n2 = np.asarray(faces[1].normalAt(cq.Vector(*point)).toTuple())
            stations.append(H.edge_station(point, tangent, n1, n2, True))
        vertex = lambda t: tuple(round(float(c), 5) for c in edge.positionAt(t).toTuple())
        return dict(stations=stations, faces=(key(faces[0]), key(faces[1])), vertices=(vertex(0.), vertex(1.)), straight=True)

    def distance_to_new_faces(self, base, result, points):
        base_faces = base.Faces()
        new = [f for f in result.Faces() if not any(f.isSame(b) for b in base_faces)]
        return max(min(f.distance(cq.Vertex.makeVertex(*p)) for f in new) for p in points)

    def test_cheap_fillet_preview_lies_on_the_real_fillet_surface(self):
        box = cq.Workplane('XY').box(40, 30, 10)
        edge = box.edges('>Z and |X').vals()[0]
        real = box.newObject([edge]).fillet(3)
        lines = H.edge_ghost([self.station_entry(box.val(), edge)])(3)
        points = np.vstack([np.asarray(l) for l in lines])
        top = self.distance_to_new_faces(box.val(), real.val(), points)
        # arcs are chords of 9 samples, so allow a small sag
        self.assertLess(top, 0.05)

    def test_adjacent_edge_rails_are_cut_where_they_meet_on_a_face(self):
        box = cq.Workplane('XY').box(40, 30, 10)
        edges = [e for e in box.edges('>Z').vals() if e.geomType() == 'LINE']
        entries = [self.station_entry(box.val(), e) for e in edges]
        lines = H.edge_ghost(entries)(3)
        # Rails run along the top face's inner rectangle: no rail point may stray beyond it.
        rails = [np.asarray(l) for l in lines if len(l) == 2]
        for rail in rails:
            on_top = np.allclose(rail[:, 2], 5.0, atol=1e-6)
            if on_top:
                self.assertLessEqual(float(np.max(np.abs(rail[:, 0]))), 20 - 3 + 1e-6)
                self.assertLessEqual(float(np.max(np.abs(rail[:, 1]))), 15 - 3 + 1e-6)

    def test_exact_outline_is_only_the_new_fillet_face(self):
        box = cq.Workplane('XY').box(40, 30, 10)
        edge = box.edges('>Z and |X').vals()[0]
        real = box.newObject([edge]).fillet(3)
        polyline = lambda e: np.array([e.positionAt(float(t)).toTuple() for t in np.linspace(0, 1, 2 if e.geomType() == 'LINE' else 20)])
        outlines = H.changed_outlines(box.val(), real.val(), polyline)
        self.assertEqual(len(outlines), 4)   # two rails and two end arcs

    def test_exact_outline_of_a_concave_fillet_ignores_enlarged_neighbours(self):
        bracket = cq.Workplane('XY').box(40, 20, 5).union(cq.Workplane('XY').box(40, 5, 25).translate((0, -7.5, 10)))
        edge = bracket.edges(cq.selectors.BoxSelector((-30, -6, 2), (30, -4, 3))).vals()[0]
        real = bracket.newObject([edge]).fillet(2)
        polyline = lambda e: np.array([e.positionAt(float(t)).toTuple() for t in np.linspace(0, 1, 2 if e.geomType() == 'LINE' else 20)])
        self.assertEqual(len(H.changed_outlines(bracket.val(), real.val(), polyline)), 4)


if __name__ == '__main__':
    unittest.main()
