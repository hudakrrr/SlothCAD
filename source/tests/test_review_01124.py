import os,math,copy,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QPointF,Qt
from PySide6.QtWidgets import QApplication
from geometry import entity,new_sketch,base_frame,snap_intersections,nearest_on_entity
from dimensions import values,constrain
from model import Document,ModelError
from workspace import Workspace
from app import Window


class GeometryReviewTests(unittest.TestCase):
    def test_curved_intersections_are_analytic_including_tangency(self):
        circle=entity('circle',center=[0,0],radius=5)
        line=entity('line',a=[-10,1.37],b=[10,1.37])
        points=snap_intersections([circle,line]);self.assertEqual(len(points),2)
        np.testing.assert_allclose(sorted(p[0] for p in points),[-math.sqrt(25-1.37**2),math.sqrt(25-1.37**2)],atol=1e-10)
        tangent=entity('line',a=[-10,5],b=[10,5]);points=snap_intersections([circle,tangent])
        self.assertEqual(len(points),1);np.testing.assert_allclose(points[0],[0,5])
    def test_sources_only_extrusions_rebuild_and_empty_sources_reject(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=8,height=6)]
        f=dict(kind='extrude',name='Extrude',depth=4,operation='add',sources=[dict(type='sketch',sketch=s['id'],entities=[s['entities'][0]['id']])])
        self.assertAlmostEqual(Document([s,f]).solid.val().Volume(),192)
        with self.assertRaisesRegex(ModelError,'at least one'):Document([s,{**f,'sources':[]}])
    def test_degenerate_arc_dimensions_do_not_generate_nan(self):
        points=[[1.,2.],[1.,2.]]
        self.assertEqual(values('arc',points,[3,4]),[])
        np.testing.assert_array_equal(constrain('arc',points,[3,4],{0:2}),[3,4])
    def test_small_line_nearest_point_preserves_submillimeter_precision(self):
        line=entity('line',a=[0,0],b=[.0001,0])
        np.testing.assert_allclose(nearest_on_entity(line,[.00005,.00002]),[.00005,0],atol=1e-12)


class WorkspaceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Workspace();self.w.resize(600,400)
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_picking_outside_viewport_returns_empty_without_rasterizing(self):
        with patch.object(self.w,'rasterize',side_effect=AssertionError('outside pick rasterized')):
            for p in [(-.1,1),(1,-.1),(600,10),(10,400)]:self.assertEqual(self.w.body_hit(QPointF(*p))[0],-1)
    def test_measure_point_and_edge_skip_profile_work(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
        self.w.set_mode('sketch',s,s['frame']);self.w.set_measure_active(True)
        with patch.object(self.w,'cached_profiles',side_effect=AssertionError('profile work on boundary pick')):
            for p,kind in [([-10,-5],'point'),([2,-5],'edge')]:
                hit=self.w.measure_pick(QPointF(*self.w.project_local([p],s['frame'])[0]));self.assertEqual(hit['kind'],kind)
    def test_material_resolution_runs_once_per_body_and_reuses_camera_independent_data(self):
        self.w.body_ids=np.repeat([0,1],500);self.w.materials={'0':{'color':'#ff0000','finish':'metallic'},'1':{'color':'#00ff00','finish':'matte'}}
        with patch.object(self.w,'body_material',wraps=self.w.body_material) as resolve:
            first=self.w.triangle_materials();self.w.yaw+=10;second=self.w.triangle_materials()
            self.assertEqual(resolve.call_count,2);self.assertIs(first,second)
            np.testing.assert_array_equal(first[0][[0,-1]],[[255,0,0],[0,255,0]])
            np.testing.assert_array_equal(first[1][[0,-1]],[1,0])
        self.w.materials['0']['color']='#0000ff';np.testing.assert_array_equal(self.w.triangle_materials()[0][0],[0,0,255])
    def test_grid_step_respects_nondefault_base_spacing(self):
        self.w.grid=3
        with patch.object(self.w,'scale',return_value=22):
            self.assertAlmostEqual(self.w.adaptive_grid_step(22),1.5)
    def test_edge_hover_picks_once_per_motion_batch(self):
        self.w.set_mode('edge')
        with patch.object(self.w,'edge_at',return_value=2) as pick:
            self.w.queue_motion(QPointF(100,100),Qt.NoButton);self.w.flush_motion();pick.assert_called_once()
    def test_repeated_arc_start_stays_ready_for_a_distinct_endpoint(self):
        s=new_sketch(base_frame('XY'));self.w.set_mode('sketch',s,s['frame']);self.w.set_tool('arc')
        self.w.draw_point(np.array([1.,2.]));self.w.draw_point(np.array([1.,2.]));self.assertEqual(self.w.points,[[1.,2.]])


class SceneReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_unchanged_sketch_scene_reuses_prepared_geometry(self):
        w=Window()
        try:
            s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
            first=w.prepare_sketch_data([s],lambda *_:None,True);w.install_sketch_data(first)
            with patch('app.regions',side_effect=AssertionError('unchanged loops rebuilt')),patch('app.profile_regions',side_effect=AssertionError('unchanged profiles rebuilt')):
                second=w.prepare_sketch_data([copy.deepcopy(s)],lambda *_:None,True)
                self.assertIs(first[0][s['id']],second[0][s['id']]);self.assertIs(first[1][s['id']],second[1][s['id']])
        finally:w.hide();w.deleteLater();self.app.processEvents()
