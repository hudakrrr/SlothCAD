import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from render_backend import Rasterizer,numpy_render
from workspace import Workspace
from geometry import base_frame,new_sketch,entity,world
from model import Document,new_feature

class RasterTests(unittest.TestCase):
    def setUp(self):
        self.renderer=Rasterizer()
        self.screen=np.array([[2.2,2.7],[23.1,4.3],[4.4,20.6],[3.3,3.9],[21.8,7.6],[13.7,19.4]])
        self.z=np.array([0.,0.,0.,1.,2.,1.])
        self.triangles=np.array([[0,1,2],[3,4,5]],np.int32);self.faces=np.array([7,9],np.int32);self.colors=np.array([[20,150,200],[230,140,50]],np.uint8)
    def test_native_matches_independent_reference_with_depth_and_coverage(self):
        if not self.renderer.native:self.skipTest('C compiler is not installed; native path unavailable')
        for factor in (1,2):
            actual=self.renderer.render(self.screen,self.z,self.triangles,self.faces,self.colors,28,24,factor==2)
            expected=numpy_render(self.screen,self.z,self.triangles,self.faces,self.colors,28,24,factor)
            np.testing.assert_array_equal(actual[0],expected[0]);np.testing.assert_array_equal(actual[2],expected[2])
            np.testing.assert_allclose(actual[1],expected[1],atol=1e-6)
    def test_antialias_produces_partial_edge_coverage_and_preserves_interior(self):
        pixels,depth,ids=self.renderer.render(self.screen,self.z,self.triangles,self.faces,self.colors,28,24,True)
        self.assertTrue(np.any((pixels[:,:,3]>0)&(pixels[:,:,3]<255)))
        self.assertEqual(pixels[8,10,3],255);self.assertEqual(ids[8,10],9);self.assertGreater(depth[8,10],0)
        self.assertEqual(ids[23,27],-1);self.assertEqual(pixels[23,27,3],0)
    def test_offscreen_and_degenerate_triangles_are_safe(self):
        screen=np.array([[-100.,-100.],[-20.,-20.],[-10.,-10.]])
        p,z,ids=self.renderer.render(screen,np.zeros(3),np.array([[0,1,2]]),np.array([1]),np.array([[10,20,30]]),20,20)
        self.assertTrue(np.all(ids==-1));self.assertTrue(np.all(p[:,:,3]==0))
    def test_invalid_indices_rejected_before_native_call(self):
        with self.assertRaises(ValueError):self.renderer.render(self.screen,self.z,np.array([[0,1,99]]),np.array([0]),np.array([[1,2,3]]),20,20)
    def test_native_reuses_work_buffers(self):
        if not self.renderer.native:self.skipTest('Native path unavailable')
        self.renderer.render(self.screen,self.z,self.triangles,self.faces,self.colors,28,24)
        before=(id(self.renderer.high_z),id(self.renderer.pixels))
        self.renderer.render(self.screen+1,self.z,self.triangles,self.faces,self.colors,28,24)
        self.assertEqual(before,(id(self.renderer.high_z),id(self.renderer.pixels)))

class ViewportCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Workspace();self.w.resize(600,400);self.w.set_mode('model')
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_empty_scene_camera_motion_keeps_empty_buffers_and_skips_renderer(self):
        self.w.rasterize();depth=self.w.depth;ids=self.w.face_buffer
        for i in range(10):self.w.yaw+=1;self.w.pan+=1;self.w.rasterize()
        self.assertIs(depth,self.w.depth);self.assertIs(ids,self.w.face_buffer);self.assertIsNone(self.w.pixels)
        self.assertEqual(self.w.rasterizer.calls,0)
    def test_background_reused_for_hover_and_invalidated_by_camera_or_grid(self):
        first=self.w.cached_background();self.w.hover={'type':'plane','plane':'XY'}
        self.assertIs(first,self.w.cached_background());self.assertEqual(self.w.background_builds,1)
        self.w.yaw+=10;self.assertIsNot(first,self.w.cached_background())
        self.w.show_grid=False;self.w.cached_background();self.assertEqual(self.w.background_builds,3)
    def test_finite_grid_has_complete_cells_and_no_overhanging_segments(self):
        low,high,minor,major=self.w.grid_segments(np.array([-13.2,-8.7]),np.array([15.8,11.9]),2,finite=True)
        np.testing.assert_array_equal(low,[-20,-10]);np.testing.assert_array_equal(high,[20,10])      # whole blocks of five cells
        segments=np.concatenate([np.asarray(minor).reshape((-1,2,2)),np.asarray(major).reshape((-1,2,2))])
        self.assertTrue(np.all(segments>=low));self.assertTrue(np.all(segments<=high))
        for a,b in segments:
            if a[0]==b[0]:self.assertEqual((a[1],b[1]),(low[1],high[1]));self.assertTrue(low[0]<a[0]<high[0])
            else:self.assertEqual((a[0],b[0]),(low[0],high[0]));self.assertTrue(low[1]<a[1]<high[1])

    def test_clicking_solid_vertex_selects_all_incident_edges(self):
        feature=new_feature();feature.update(width=20,height=16,depth=12)
        solid=Document([feature]).solid
        self.w.set_scene(solid,[],True);self.w.set_mode('edge')
        self.assertTrue(self.w.solid_vertices)
        point,group=next((point,group) for point,group in self.w.solid_vertices
                         if self.w.vertex_edges_at(QPointF(*self.w.project([point])[0][0]))==group)
        self.assertEqual(len(group),3)
        x,y=self.w.project([point])[0][0]
        QTest.mouseClick(self.w,Qt.LeftButton,pos=QPoint(round(x),round(y)))
        self.assertEqual(self.w.selected_edges,set(group))
        QTest.mouseClick(self.w,Qt.LeftButton,pos=QPoint(round(x),round(y)))
        self.assertFalse(self.w.selected_edges)

    def test_batched_projection_matches_world_coordinates(self):
        frame=base_frame('YZ');frame['origin']=[10,20,30];points=[[2,3],[-5,1],[0,0]]
        np.testing.assert_allclose(self.w.project_local(points,frame),self.w.project([world(frame,p) for p in points])[0])
    def test_sketch_profile_cache_refreshes_after_geometry_edit(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=10,height=10)]
        first=self.w.cached_sketch(s);self.assertIs(first[0],self.w.cached_sketch(s)[0])
        s['entities'][0]['width']=20;changed=self.w.cached_sketch(s)
        self.assertIsNot(first[0],changed[0]);self.assertEqual(changed[0][0][1][:,0].max(),10)
    def test_same_solid_scene_updates_do_not_retessellate(self):
        solid=Document.load(Path(__file__).resolve().parents[1]/'examples'/'face_sketch_demo.fcad').solid
        self.w.set_scene(solid,[],True);vertices=self.w.vertices;count=self.w.mesh_builds
        self.w.set_scene(solid,[]);self.assertIs(vertices,self.w.vertices);self.assertEqual(self.w.mesh_builds,count)
    def test_document_caches_frames_and_unchanged_commit_skips_kernel(self):
        from unittest.mock import patch
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=10,height=10)]
        doc=Document([s]);self.assertIn(s['id'],doc.frames)
        with patch('model.build_state',side_effect=AssertionError('unchanged commit rebuilt geometry')):
            self.assertFalse(doc.commit(doc.features))
        changed=[s,dict(kind='extrude',name='Extrude',depth=5,operation='add',source={'type':'sketch','sketch':s['id'],'entities':[s['entities'][0]['id']]})]
        doc.commit(changed);self.assertAlmostEqual(doc.solid.val().Volume(),500)
        doc.undo();self.assertIsNone(doc.solid);self.assertIn(s['id'],doc.frames)
        doc.redo();self.assertAlmostEqual(doc.solid.val().Volume(),500)
    def test_antialias_toggle_invalidates_body_image_and_face_pick_stays_available(self):
        self.w.set_scene(Document.load(Path(__file__).resolve().parents[1]/'examples'/'face_sketch_demo.fcad').solid,[],True)
        self.w.rasterize();first=self.w.rasterizer.calls
        self.assertTrue(np.any((self.w.pixels[:,:,3]>0)&(self.w.pixels[:,:,3]<255)))
        self.w.show_aa=False;self.w.rasterize();self.assertEqual(self.w.rasterizer.calls,first+1)
        self.assertTrue(np.all(np.isin(self.w.pixels[:,:,3],[0,255])))
        y,x=np.argwhere(self.w.face_buffer>=0)[len(np.argwhere(self.w.face_buffer>=0))//2]
        self.w.mode='extrude';self.assertIn(self.w.pick(QPoint(int(x),int(y)))['type'],('face','curved'))

if __name__=='__main__':unittest.main()
