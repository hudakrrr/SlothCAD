import os,unittest,math,threading
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,Qt,QPointF
from PySide6.QtTest import QTest
from geometry import entity,new_sketch,base_frame,regular_polygon,profile_regions,sample,transform_entity
from model import Document
from app import Window

class PolygonSplineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        with patch('app.load_language',return_value='en'):self.w=Window()
        self.w.support_picked({'type':'plane','plane':'XY'})
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_polygon_modes_use_vertex_radius_edge_radius_or_edge_length(self):
        center=np.array([3.,4.])
        for sides in (3,5,8):
            vertices=np.array(regular_polygon(center,center+[10,0],sides,'inscribed'))
            np.testing.assert_allclose(np.linalg.norm(vertices-center,axis=1),10)
            vertices=np.array(regular_polygon(center,center+[10,0],sides,'circumscribed'))
            for a,b in zip(vertices,np.roll(vertices,-1,axis=0)):
                direction=b-a;offset=center-a
                self.assertAlmostEqual(abs(direction[0]*offset[1]-direction[1]*offset[0])/np.linalg.norm(direction),10)
            vertices=np.array(regular_polygon(center,center+[10,0],sides,'edge'))
            np.testing.assert_allclose(vertices[:2],[center,center+[10,0]],atol=1e-8)
            np.testing.assert_allclose(np.linalg.norm(vertices-np.roll(vertices,-1,axis=0),axis=1),10)
    def test_polygon_is_one_tool_with_live_side_mode_and_size_settings(self):
        self.w.start_polygon_tool();self.w.widgets['polygon_sides'].setValue(7)
        self.w.widgets['polygon_mode'].setCurrentIndex(2);self.w.widgets['polygon_size'].setValue(12)
        workspace=self.w.workspace;workspace.draw_point(np.array([2.,3.]))
        workspace.draw_point(workspace.constrained_cursor(workspace.points,np.array([40.,3.]),{}))
        vertices=np.array(self.w.draft['entities'][-1]['points']);self.assertEqual(len(vertices),7)
        np.testing.assert_allclose(np.linalg.norm(vertices-np.roll(vertices,-1,axis=0),axis=1),12)
    def test_typing_polygon_size_uses_current_mode(self):
        self.w.start_polygon_tool();self.w.set_polygon_mode('circumscribed');workspace=self.w.workspace
        workspace.draw_point(np.array([0.,0.]));workspace.cursor=np.array([10.,0.])
        QTest.keyClicks(workspace,'15');QTest.keyClick(workspace,Qt.Key_Return)
        vertices=np.array(self.w.draft['entities'][-1]['points'])
        np.testing.assert_allclose(np.linalg.norm(vertices,axis=1),15/math.cos(math.pi/6))
    def test_spline_clicking_first_point_closes_an_extrudable_smooth_loop(self):
        workspace=self.w.workspace;self.w.set_tool('spline')
        for point in [[0,0],[10,0],[10,10],[0,10],[0,0]]:workspace.draw_point(np.array(point,dtype=float))
        e=self.w.draft['entities'][-1];self.assertTrue(e['closed']);self.assertEqual(workspace.points,[])
        points=sample(e,100);np.testing.assert_allclose(points[0],points[-1]);self.assertGreater(np.dot(points[1]-points[0],points[-1]-points[-2]),0)
        s=self.w.draft;p=profile_regions(s)[0]
        f=dict(kind='extrude',name='Closed spline',depth=3,operation='add',source=dict(type='sketch',sketch=s['id'],entities=p['entities'],profile_mode='nested'))
        self.assertTrue(Document([s,f]).solid.val().isValid())
        mirrored=transform_entity(e,np.array([[-1.,0],[0,1]]),np.zeros(2));self.assertTrue(mirrored['closed'])
        self.w.show();self.app.processEvents();self.w.set_tool('spline')
        for point in [[20.3,20.4],[30,20],[30,30]]:workspace.draw_point(np.array(point,dtype=float))
        screen=workspace.project_local([[20.3,20.4]],workspace.active_frame)[0]
        QTest.mouseClick(workspace,Qt.LeftButton,pos=QPointF(screen[0]+3,screen[1]).toPoint())
        self.assertTrue(self.w.draft['entities'][-1]['closed']);self.assertEqual(workspace.points,[])
    def test_legacy_spline_with_repeated_endpoint_is_also_closed(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('spline',points=[[0,0],[10,0],[10,10],[0,10],[0,0]])]
        self.assertEqual(len(profile_regions(s)),1)
    def test_progress_operation_runs_in_worker_and_services_gui_timer(self):
        self.w.show();self.app.processEvents()
        ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(self.w.busy_progress.isVisible()));timer.start()
        main=threading.get_ident()
        def work(report):report(1,2,'Working');threading.Event().wait(.45);return threading.get_ident()
        worker=self.w.run_busy('Test operation',work);timer.stop()
        # A long job is shown as busy (the indicator appears after a short grace period and the
        # GUI timer keeps running meanwhile); it is gone and the window usable again afterwards.
        self.assertNotEqual(main,worker);self.assertGreater(len(ticks),8);self.assertTrue(any(ticks));self.assertTrue(ticks[-1]);self.assertFalse(self.w.loading)
        self.assertFalse(self.w.busy_progress.isVisible());self.assertTrue(self.w.centralWidget().isEnabled())
    def test_quick_operations_do_not_flash_the_busy_state(self):
        self.w.show();self.app.processEvents()
        seen=[];timer=QTimer();timer.setInterval(1);timer.timeout.connect(lambda:seen.append((self.w.busy_progress.isVisible(),self.w.centralWidget().isEnabled())));timer.start()
        for _ in range(5):self.w.run_busy('Quick',lambda report:threading.Event().wait(.02))
        timer.stop()
        self.assertTrue(all(visible is False and enabled for visible,enabled in seen),seen)
    def test_region_preparation_uses_worker_and_paint_cache_is_warm(self):
        self.w.workspace.sketch_cache.clear();threads=[]
        import app as app_module
        original=app_module.regions
        def traced(s):threads.append(threading.get_ident());return original(s)
        with patch('app.regions',side_effect=traced):self.w.prepare_active_sketch()
        self.assertTrue(threads);self.assertTrue(all(t!=threading.get_ident() for t in threads))
        with patch('workspace.regions',side_effect=AssertionError('UI recomputed topology')):self.w.workspace.cached_sketch(self.w.draft)
