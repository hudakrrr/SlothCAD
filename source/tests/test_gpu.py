"""GPU data and picking regressions; desktop GL context smoke test is separate."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from unittest.mock import patch
from workspace import Workspace
from gpu_renderer import mesh_data,surface_format
from geometry import base_frame,new_sketch,entity

class GpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Workspace();self.w.resize(600,400);self.w.gpu_enabled=True
    def tearDown(self):self.w.gpu_enabled=False;self.w.deleteLater();self.app.processEvents()
    def test_empty_gpu_pick_allocates_no_framebuffer(self):
        with patch.object(self.w,'rasterize',side_effect=AssertionError('CPU full-frame rasterization')):
            self.assertEqual(self.w.body_hit(QPointF(10,20)),(-1,-np.inf))
        self.assertIsNone(self.w.depth);self.assertIsNone(self.w.pixels)
    def test_gpu_pick_uses_nearest_triangle_and_cached_camera_projection(self):
        self.w.aligned=np.eye(3);self.w.center=np.zeros(3);self.w.vertices=np.array([[-10,-10,0],[10,-10,0],[0,10,0],[-10,-10,4],[10,-10,4],[0,10,4]])
        self.w.triangles=np.array([[0,1,2],[3,4,5]]);self.w.face_ids=np.array([2,5])
        with patch.object(self.w,'rasterize',side_effect=AssertionError('CPU full-frame rasterization')):
            self.assertEqual(self.w.body_hit(QPointF(300,200)),(5,4.))
            cached=self.w.pick_cache;self.w.body_hit(QPointF(301,201));self.assertIs(cached,self.w.pick_cache)
            self.w.pan[0]+=1;self.w.body_hit(QPointF(300,200));self.assertIsNot(cached,self.w.pick_cache)
            self.assertEqual(self.w.body_hit(QPointF(0,0)),(-1,-np.inf))
    def test_gpu_buffer_normals_and_face_ids(self):
        vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,1]])
        data=mesh_data(vertices,np.array([[0,1,2],[3,4,5]]),np.array([4,9]))
        self.assertEqual(data.shape,(6,7));self.assertEqual(data.dtype,np.float32)
        np.testing.assert_allclose(data[:3,3:6],[[0,0,1]]*3)
        np.testing.assert_allclose(data[3:,3:6],[[1,0,0]]*3)
        np.testing.assert_array_equal(data[:,6],[4,4,4,9,9,9])
    def test_requested_surface_has_depth_and_msaa(self):
        fmt=surface_format();self.assertEqual(fmt.samples(),8);self.assertEqual(fmt.depthBufferSize(),24)
        self.assertEqual((fmt.majorVersion(),fmt.minorVersion()),(3,3))
    def test_select_existing_sketch_entity(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.w.gpu_enabled=False
        sketch=new_sketch(base_frame('XY'));sketch['entities']=[entity('line',a=[-5,0],b=[5,0])]
        self.w.set_mode('sketch',sketch,base_frame('XY'));self.w.set_tool('select')
        QTest.mouseClick(self.w,Qt.LeftButton,pos=QPointF(300,200).toPoint())
        self.assertEqual(self.w.selected_entity,0)

    def test_plane_selector_reuses_images_and_projection_for_hover_changes(self):
        self.w.mode='support';self.w.prepare_planes();images=self.w.plane_images.copy()
        for name in ['XY','XZ','YZ',None]*100:
            self.w.hover={'type':'plane','plane':name} if name else None
            self.w.prepare_planes()
        self.assertEqual(self.w.plane_cache_builds,1)
        for name,image in images.items():self.assertIs(image,self.w.plane_images[name])
        self.w.pan[0]+=10;self.w.prepare_planes();self.assertEqual(self.w.plane_cache_builds,2)
    def test_empty_selector_picks_without_body_renderer_or_a_paint(self):
        self.w.mode='support';self.w.prepare_planes()
        poly=self.w.plane_polygons['XY'];point=sum((p for p in poly),QPointF())/len(poly)
        with patch.object(self.w,'body_hit',side_effect=AssertionError('empty scene body picking')):
            hit=self.w.pick(point)
        self.assertEqual(hit['type'],'plane');self.assertIn(hit['plane'],('XY','XZ','YZ'))
    def test_cached_plane_states_include_a_visible_hover_change(self):
        self.w.prepare_planes()
        self.assertNotEqual(self.w.plane_images[None],self.w.plane_images['XY'])
        self.assertEqual(self.w.plane_images['XY'].devicePixelRatio(),self.w.devicePixelRatioF())
