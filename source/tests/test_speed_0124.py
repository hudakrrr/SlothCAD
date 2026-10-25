"""Interaction-speed work: cached shape measurements, local fillet checks, cheap preview strokes."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import cadquery as cq
import numpy as np

import model
import references
from model import apply_edge_operation, edge_reference, resolve_edges


class CachedMeasurementTests(unittest.TestCase):
    def test_cached_bounds_match_the_kernel_box(self):
        body = cq.Workplane('XY').box(20, 12, 10).val()
        for edge in body.Edges():
            low, high = references.bounds(edge)
            box = edge.BoundingBox()
            self.assertTrue(np.allclose(low, [box.xmin, box.ymin, box.zmin]))
            self.assertTrue(np.allclose(high, [box.xmax, box.ymax, box.zmax]))
            low[0] = 12345.     # callers get copies; the cache must not change
            self.assertFalse(np.isclose(references.bounds(edge)[0][0], 12345.))

    def test_picks_still_resolve_after_the_caches_are_warm(self):
        body = cq.Workplane('XY').box(20, 12, 10)
        edges = [e for e in body.val().Edges() if e.geomType() == 'LINE'][:3]
        refs = [edge_reference(e, body) for e in edges]
        for _ in range(2):
            picked = resolve_edges(body, refs)
            self.assertEqual(len(picked), 3)
            for want, got in zip(edges, picked):
                self.assertTrue(want.isSame(got))

    def test_edge_owner_lookup_finds_the_body(self):
        body = cq.Workplane('XY').box(20, 12, 10)
        edge = body.val().Edges()[0]
        owner = references._owner(edge, body, 'edge')
        self.assertIsNotNone(owner)
        self.assertEqual(owner[0], 0)


class FilletCheckTests(unittest.TestCase):
    def large_plate(self):
        body = cq.Workplane('XY').box(120, 80, 10, centered=(True, True, False))
        points = [(-50 + i * 100 / 11., -30 + j * 60 / 11.) for i in range(12) for j in range(12)]
        return body.faces('>Z').workplane().pushPoints(points).hole(2.0)

    def test_large_body_fillet_builds_and_stays_valid(self):
        body = self.large_plate()
        self.assertGreaterEqual(len(body.val().Faces()), model.LOCAL_CHECK_FACES)
        edges = [e for e in body.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6
                 and (abs(abs(e.Center().x) - 60) < 1e-6 or abs(abs(e.Center().y) - 40) < 1e-6)]
        result = apply_edge_operation(body, edges, 'fillet', 2.0)
        self.assertTrue(result.val().isValid())
        self.assertLess(result.val().Volume(), body.val().Volume())
        self.assertEqual(len(result.val().Solids()), 1)

    def test_local_check_accepts_a_clean_fillet_and_fast_validity_agrees(self):
        body = self.large_plate()
        edge = [e for e in body.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        raw = body.findSolid().fillet(1.5, [edge])
        wrapped = body.newObject([raw])
        self.assertFalse(model._local_self_intersects(body, raw))
        self.assertTrue(model._edge_trial_is_valid_fast(body, wrapped))

    def test_fast_validity_rejects_an_empty_result(self):
        body = cq.Workplane('XY').box(10, 10, 10)
        self.assertFalse(model._edge_trial_is_valid_fast(body, cq.Workplane('XY')))

    def test_maximum_size_matches_the_box_geometry(self):
        body = cq.Workplane('XY').box(20, 12, 10)
        ref = [edge_reference(list(body.val().Edges())[0])]
        limit, bounded = model.maximum_edge_size(body, 'fillet', ref, hint=1)
        self.assertTrue(bounded)
        self.assertGreater(limit, 11.9)
        self.assertLess(limit, 12.01)


class PreviewStrokeTests(unittest.TestCase):
    def test_fast_stroke_paints_pixels_and_restores_the_painter(self):
        from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor
        import viewport_gizmo
        image = QImage(80, 60, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        path = QPainterPath()
        path.moveTo(5, 5)
        path.lineTo(70, 50)
        painter = QPainter(image)
        before = painter.transform()
        viewport_gizmo.stroke_fast(painter, path, QColor('#f0ad45'), dashed=True, glow=60, core=2)
        self.assertEqual(painter.transform(), before)
        painter.end()
        covered = sum(1 for x in range(80) for y in range(60) if image.pixelColor(x, y).alpha() > 0)
        self.assertGreater(covered, 40)


class HistoryLimitTests(unittest.TestCase):
    """Shell / offset face / press-pull sizes are searched by worker processes."""
    def test_shell_thickness_limit_found_by_workers(self):
        import limit_search
        from geometry import entity, new_sketch, base_frame, identifier, profile_regions
        from model import Document
        from solid_tools import face_ref
        sketch = new_sketch(base_frame('XY'))
        sketch['entities'] = [entity('rectangle', center=[0, 0], width=20, height=20)]
        region = profile_regions(sketch)[0]
        extrude = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=20, operation='add',
                       source=dict(type='sketch', sketch=sketch['id'], entities=region['entities'], holes=region['holes'],
                                   profile_mode='nested'))
        document = Document([sketch, extrude])
        top = max(document.solid.val().Faces(), key=lambda f: f.Center().z)
        shell = dict(kind='shell', id=identifier(), name='Shell', enabled=True, body=0,
                     faces=[face_ref(top, document.solid)], thickness=-1.)
        try:
            outcome = limit_search.history_limits([sketch, extrude], shell, 'thickness', -1, 200., 1.)
        finally:
            limit_search.POOL.shutdown()
        self.assertIsNot(outcome, NotImplemented)
        low, high = outcome
        self.assertIsNotNone(high)
        self.assertGreater(high, 5.)          # a 20 mm box takes walls well below 10 mm
        self.assertLess(high, 10.01)


if __name__ == '__main__':
    unittest.main()
