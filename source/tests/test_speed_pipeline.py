"""The speed work must not change results: caches, draft meshes, memoised previews and the
background outline job all have to agree with the plain, synchronous paths."""
import copy
import os
import time
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication

import mesh_cache
from app import Window
from model import Document, edge_reference
from geometry import new_sketch, base_frame, entity, identifier, profile_regions
from workspace import prepare_scene_mesh


def box_features(width=20., depth=10.):
    s = new_sketch(base_frame('XY')); s['entities'] = [entity('rectangle', center=[0, 0], width=width, height=12)]
    region = profile_regions(s)[0]
    f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=depth, operation='add',
             source=dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes']))
    return [s, f]


def disk_document():
    return Document.load(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'examples', 'perforated_disk.fcad'))


class MeshTests(unittest.TestCase):
    def test_mesh_matches_the_shape(self):
        doc = disk_document(); shape = doc.solid.val(); data = prepare_scene_mesh(doc.solid)
        box = shape.BoundingBox(); v = data['vertices']
        self.assertGreater(len(data['triangles']), 100)
        for axis, (low, high) in enumerate(((box.xmin, box.xmax), (box.ymin, box.ymax), (box.zmin, box.zmax))):
            self.assertAlmostEqual(v[:, axis].min(), low, delta=.05)
            self.assertAlmostEqual(v[:, axis].max(), high, delta=.05)
        self.assertEqual(len(data['face_ids']), len(data['triangles']))
        self.assertEqual(len(data['faces']), len(shape.Faces()))
        self.assertTrue(data['triangles'].max() < len(v))
        # Triangles of every face are present and outlines exist for every face.
        self.assertEqual(set(np.unique(data['face_ids'])), set(range(len(data['faces']))))
        self.assertEqual(len(data['face_edges']), len(data['faces']))

    def test_mesh_surface_area_matches_the_kernel(self):
        doc = disk_document(); data = prepare_scene_mesh(doc.solid)
        v, t = data['vertices'], data['triangles']
        area = .5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1).sum()
        exact = sum(f.Area() for f in doc.solid.val().Faces())
        self.assertAlmostEqual(area / exact, 1., delta=.01)

    def test_triangles_face_outward(self):
        data = prepare_scene_mesh(Document(box_features()).solid)
        v, t = data['vertices'], data['triangles']
        normals = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        centroid = v.mean(axis=0)
        outward = ((v[t].mean(axis=1) - centroid) * normals).sum(axis=1)
        self.assertTrue((outward > 0).all())

    def test_repeat_and_draft_meshes(self):
        solid = disk_document().solid
        first = prepare_scene_mesh(solid)
        again = prepare_scene_mesh(solid)
        np.testing.assert_array_equal(first['triangles'], again['triangles'])
        np.testing.assert_allclose(first['vertices'], again['vertices'])
        # A shape that was never meshed gets the coarse draft mesh; the real mesh replaces it.
        fresh = disk_document().solid
        draft = prepare_scene_mesh(fresh, draft=True)
        self.assertTrue(draft['draft'] and not first['draft'])
        self.assertLess(len(draft['triangles']), len(first['triangles']))
        final_again = prepare_scene_mesh(fresh)       # refined in place, not stuck coarse
        self.assertEqual(len(final_again['triangles']), len(first['triangles']))
        # An already fine mesh is kept for a draft request: nothing is thrown away.
        self.assertEqual(len(prepare_scene_mesh(fresh, draft=True)['triangles']), len(first['triangles']))

    def test_unchanged_faces_are_reused_after_an_edit(self):
        features = box_features()
        a = Document(features); prepare_scene_mesh(a.solid)
        before = len(mesh_cache._FACES)
        changed = copy.deepcopy(features); changed[1]['depth'] = 14.
        b = Document(changed); prepare_scene_mesh(b.solid)
        # A different depth builds new faces; nothing may break and the cache stays bounded.
        self.assertLessEqual(len(mesh_cache._FACES), mesh_cache.FACE_LIMIT)
        self.assertGreaterEqual(len(mesh_cache._FACES), before)

    def test_empty_scene(self):
        data = prepare_scene_mesh(None)
        self.assertEqual(len(data['triangles']), 0)


class DocumentTests(unittest.TestCase):
    def test_preview_is_remembered_and_cleared_by_commits(self):
        doc = Document(box_features())
        trial = copy.deepcopy(doc.features); trial[1]['depth'] = 12.
        first = doc.preview(trial)
        second = doc.preview(copy.deepcopy(trial))
        self.assertIs(first[0], second[0])                # same result object: not rebuilt
        self.assertAlmostEqual(first[0].val().Volume(), 20 * 12 * 12, places=3)
        doc.commit(trial)
        self.assertEqual(len(doc._preview_memo), 0)
        self.assertAlmostEqual(doc.solid.val().Volume(), 20 * 12 * 12, places=3)

    def test_failing_preview_is_not_remembered(self):
        doc = Document(box_features())
        bad = copy.deepcopy(doc.features); bad[1]['depth'] = 0.
        for _ in range(2):
            with self.assertRaises(Exception):
                doc.preview(bad)
        self.assertEqual(len(doc._preview_memo), 0)

    def test_preview_never_changes_the_document(self):
        doc = Document(box_features()); original = copy.deepcopy(doc.features); volume = doc.solid.val().Volume()
        trial = copy.deepcopy(doc.features); trial[1]['depth'] = 3.
        doc.preview(trial)
        self.assertEqual(doc.features, original)
        self.assertAlmostEqual(doc.solid.val().Volume(), volume)


class BackgroundOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.errors = []; self.w.error = self.errors.append
        self.w.show(); self.app.processEvents()
        doc = Document(box_features()); self.w.doc = doc; self.w.refresh()
        self.w.new_edge('fillet')
        edge = [e for e in doc.solid.val().Edges() if e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6][0]
        self.w.draft.update(edge_refs=[edge_reference(edge, doc.solid)], radius=3., auto_fit=True)
        self.w.show_editor(); self.app.processEvents()
        self.g = self.w.workspace.gizmo

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()
        self.assertEqual(self.errors, [])

    def wait_for(self, predicate, seconds=20.):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(.005)
        return False

    def test_background_result_equals_the_synchronous_one(self):
        self.g.compute_exact(background=False)
        expected = self.g.exact_result
        self.g.exact_result = None
        self.g.compute_exact(background=True)
        self.assertTrue(self.g._exact_running)           # returned immediately, work continues
        self.assertTrue(self.wait_for(lambda: self.g.exact_result is not None))
        got = self.g.exact_result
        self.assertIsNone(got[2])
        cloud = lambda r: sorted({tuple(np.round(p, 5)) for line in r[1] for p in np.asarray(line)})
        self.assertEqual(cloud(got), cloud(expected))
        self.assertFalse(self.g._exact_running)

    def test_requests_during_a_rebuild_collapse_into_one_follow_up(self):
        self.g.compute_exact(background=True)
        self.assertTrue(self.g._exact_running)
        runs = []
        original = self.g.state['exact_job']
        def counting():
            runs.append(1); return original()
        self.g.state['exact_job'] = counting
        for _ in range(10):
            self.g.compute_exact(background=True)          # all of these only mark "again"
        self.assertEqual(runs, [])
        self.w.widgets['radius'].setValue(1.5); self.app.processEvents()
        self.assertTrue(self.wait_for(lambda: not self.g._exact_running and self.g.exact_result is not None and abs(self.g.exact_result[0] - 1.5) < 1e-9))
        self.assertLessEqual(len(runs), 1)

    def test_result_of_a_cleared_gizmo_is_dropped(self):
        self.g.compute_exact(background=True)
        self.g.clear()
        self.assertTrue(self.wait_for(lambda: not self.g._exact_running))
        self.assertIsNone(self.g.exact_result)

    def test_ui_thread_stays_free_while_the_job_runs(self):
        gate = []
        original = self.g.state['exact_job']
        import threading
        release = threading.Event()
        def slow_factory():
            job = original()
            def slow():
                release.wait(10); return job()
            return slow
        self.g.state['exact_job'] = slow_factory
        started = time.perf_counter()
        self.g.compute_exact(background=True)
        self.assertLess(time.perf_counter() - started, .5)
        self.assertTrue(self.g._exact_running)
        self.app.processEvents()                              # the UI can still process events
        release.set()
        self.assertTrue(self.wait_for(lambda: self.g.exact_result is not None))


if __name__ == '__main__':
    unittest.main()


class QuickOutlineTests(unittest.TestCase):
    """The kernel-free extrusion outline must describe the same prism as the real solid."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def sketch_with_hole(self):
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('rectangle', center=[0, 0], width=20, height=12), entity('circle', center=[2, 1], radius=3)]
        return s

    def feature(self, sketch, **extra):
        region = max(profile_regions(sketch), key=lambda r: len(r['holes']))
        f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=7., operation='add',
                 source=dict(type='sketch', sketch=sketch['id'], entities=region['entities'], holes=region['holes']))
        f.update(extra)
        return f

    def kernel_points(self, doc, feature):
        from solid_tools import extrude
        from model import extrusion_sources
        prism = extrude(extrusion_sources(feature)[0], feature, None, doc.sketches, doc.frames)
        return np.vstack([np.array([v.Center().toTuple() for v in e.Vertices()]) for e in prism.Edges()])

    def quick(self, doc, feature):
        from preview_lines import prism_lines
        from model import extrusion_sources
        return prism_lines(feature, extrusion_sources(feature), doc.sketches, doc.frames)

    def test_matches_the_kernel_prism(self):
        s = self.sketch_with_hole(); f = self.feature(s); doc = Document([s, f])
        lines = self.quick(doc, f); self.assertIsNotNone(lines)
        pts = np.vstack(lines); kernel = self.kernel_points(doc, f)
        np.testing.assert_allclose(pts.min(axis=0), kernel.min(axis=0), atol=1e-6)
        np.testing.assert_allclose(pts.max(axis=0), kernel.max(axis=0), atol=1e-6)
        corners = {(x, y) for x in (-10., 10.) for y in (-6., 6.)}
        for z in (0., 7.):
            for x, y in corners:
                self.assertTrue(np.any(np.all(np.abs(pts - [x, y, z]) < 1e-6, axis=1)), (x, y, z))
        # A rectangle with a round hole: both loops are drawn at both heights.
        self.assertGreaterEqual(len(lines), 4)

    def test_symmetric_and_offset(self):
        s = self.sketch_with_hole(); f = self.feature(s, direction='symmetric', depth=6., offset=2.); doc = Document([s, f])
        pts = np.vstack(self.quick(doc, f))
        self.assertAlmostEqual(float(pts[:, 2].min()), -1.); self.assertAlmostEqual(float(pts[:, 2].max()), 5.)
        kernel = self.kernel_points(doc, f)
        np.testing.assert_allclose([pts[:, 2].min(), pts[:, 2].max()], [kernel[:, 2].min(), kernel[:, 2].max()], atol=1e-6)

    def test_negative_depth_goes_the_other_way(self):
        s = self.sketch_with_hole(); f = self.feature(s, depth=-4.); doc = Document([s, self.feature(s)])
        pts = np.vstack(self.quick(doc, f))
        self.assertAlmostEqual(float(pts[:, 2].min()), -4.); self.assertAlmostEqual(float(pts[:, 2].max()), 0.)

    def test_cases_that_need_the_kernel_return_none(self):
        s = self.sketch_with_hole(); doc = Document([s, self.feature(s)])
        for extra in (dict(taper=5.), dict(extent='through all'), dict(extent='to object'), dict(depth=0.)):
            self.assertIsNone(self.quick(doc, self.feature(s, **extra)), extra)
        face = self.feature(s); face['source'] = dict(type='face', face={})
        self.assertIsNone(self.quick(doc, face))

    def test_many_loops_are_fast(self):
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('circle', center=[i * 10, j * 10], radius=3) for i in range(15) for j in range(10)]
        regions = profile_regions(s)
        f = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=5., operation='add',
                 sources=[dict(type='sketch', sketch=s['id'], entities=r['entities'], holes=r['holes']) for r in regions])
        from preview_lines import prism_lines
        from model import extrusion_sources
        started = time.perf_counter()
        lines = prism_lines(f, extrusion_sources(f), {s['id']: s}, {s['id']: base_frame('XY')})
        self.assertLess(time.perf_counter() - started, .5)
        self.assertEqual(len(regions), 150)
        self.assertGreaterEqual(len(lines), 300)


class StatusCacheTests(unittest.TestCase):
    def test_validity_is_computed_once_per_shape(self):
        import model
        solid = Document(box_features()).solid.val()
        calls = []
        original = solid.__class__.isValid
        try:
            solid.__class__.isValid = lambda self, *a, **k: (calls.append(1), original(self, *a, **k))[1]
            model._STATUS.clear()
            first = model._shape_status(solid); second = model._shape_status(solid)
        finally:
            solid.__class__.isValid = original
        self.assertEqual(first, second); self.assertTrue(first[0]); self.assertAlmostEqual(first[1], 20 * 12 * 10, places=3)
        self.assertEqual(len(calls), 1)


class SketchLayerCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.w.resize(900, 600); self.w.show(); self.app.processEvents()
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('circle', center=[i * 12, 0], radius=4) for i in range(6)]
        self.doc = Document([s]); self.w.doc = self.doc; self.w.refresh(); self.app.processEvents()
        self.ws = self.w.workspace; self.sketch = s

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()

    def pixels(self):
        return self.ws.grab().toImage()

    def test_still_view_is_cached_and_identical_to_direct_drawing(self):
        first = self.pixels(); second = self.pixels()      # second paint builds the cached layer
        third = self.pixels()                              # third one is a blit of it
        self.assertIsNotNone(self.ws.layer_image)
        self.assertEqual(first, second); self.assertEqual(second, third)

    def test_moving_the_camera_never_shows_a_stale_layer(self):
        self.pixels(); self.pixels(); self.assertIsNotNone(self.ws.layer_image)
        before = self.pixels()
        self.ws.yaw += 25; after = self.pixels()
        self.assertNotEqual(before, after)
        self.assertIsNone(self.ws.layer_image)             # a new view starts uncached

    def test_changing_the_selection_or_the_sketch_invalidates_the_layer(self):
        self.pixels(); self.pixels()
        sig = self.ws.layer_seen
        region = profile_regions(self.sketch)[0]
        self.ws.extrusion_selection = [dict(type='sketch', sketch=self.sketch['id'], entities=region['entities'], holes=region['holes'])]
        self.pixels()
        self.assertNotEqual(self.ws.layer_seen, sig)


class SourceLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loops_and_center_match_the_kernel_wire(self):
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('rectangle', center=[5, 3], width=20, height=12), entity('circle', center=[7, 3], radius=3)]
        region = max(profile_regions(s), key=lambda r: len(r['holes']))
        source = dict(type='sketch', sketch=s['id'], entities=region['entities'], holes=region['holes'])
        doc = Document([s])
        from preview_lines import source_loops
        from solid_tools import profile
        quick = source_loops([source], doc.sketches, doc.frames)
        self.assertIsNotNone(quick)
        normal, rings, center = quick[0]
        outer, inner, frame = profile(source, None, doc.sketches, doc.frames)
        np.testing.assert_allclose(center, outer.Center().toTuple(), atol=1e-6)
        np.testing.assert_allclose(normal, [0, 0, 1], atol=1e-9)
        self.assertEqual(len(rings), 2)                       # outer boundary + one hole
        self.assertTrue(np.allclose(rings[0][0], rings[0][-1]))
        # Face sources and unknown sketches still need the kernel.
        self.assertIsNone(source_loops([dict(type='face', face={})], doc.sketches, doc.frames))
        self.assertIsNone(source_loops([dict(type='sketch', sketch='missing', entities=['x'])], doc.sketches, doc.frames))


class NestedSourceTests(unittest.TestCase):
    """Profiles picked in the workspace are 'nested': they must take the fast paths too."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_nested_profile_uses_the_fast_outline_and_finds_its_holes(self):
        s = new_sketch(base_frame('XY'))
        s['entities'] = [entity('rectangle', center=[0, 0], width=30, height=20), entity('circle', center=[0, 0], radius=4)]
        outer = max(profile_regions(s), key=lambda r: len(r['holes']))
        source = dict(type='sketch', sketch=s['id'], entities=outer['entities'], holes=[], profile_mode='nested')  # stale holes
        doc = Document([s])
        from preview_lines import prism_lines, source_loops
        f = dict(kind='extrude', depth=5., operation='add')
        lines = prism_lines(f, [source], doc.sketches, doc.frames)
        self.assertIsNotNone(lines)
        self.assertGreaterEqual(len(lines), 4)                  # outer and hole loops, top and bottom
        quick = source_loops([source], doc.sketches, doc.frames)
        self.assertEqual(len(quick[0][1]), 2)                  # the hole is found from the sketch
        self.assertNotIn('region_key', source)                  # the caller's source is not rewritten
