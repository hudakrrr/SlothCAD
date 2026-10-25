import os,copy,math,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
import numpy as np
import cadquery as cq
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QImage,QPainter
from PySide6.QtTest import QTest
from measure import calculate_measurement
from geometry import entity,new_sketch,base_frame,profile_regions,identifier
from model import Document
from app import Window


def point(p):return dict(kind='point',point=list(p),label='Point',anchor=list(p),key=('point',tuple(p)),contours=[])
def shape(kind,s):return dict(kind=kind,shape=s,label=kind.title(),anchor=list(s.Center().toTuple()),key=(kind,id(s)),contours=[])
def face():return cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(0,0,0),cq.Vector(10,0,0),cq.Vector(10,10,0),cq.Vector(0,10,0),cq.Vector(0,0,0)]))

class MeasureGeometryTests(unittest.TestCase):
    def test_point_to_point_and_order_reversal(self):
        a,b=point([1,2,3]),point([4,6,3]);result=calculate_measurement([a,b]);self.assertAlmostEqual(result['distance'],5)
        np.testing.assert_allclose(result['points'],[[1,2,3],[4,6,3]])
        reverse=calculate_measurement([b,a]);self.assertAlmostEqual(reverse['distance'],5);np.testing.assert_allclose(reverse['points'],result['points'][::-1])
    def test_point_face_uses_bounded_face_and_exact_witness_points(self):
        f=shape('face',face())
        result=calculate_measurement([point([5,4,7]),f]);self.assertAlmostEqual(result['distance'],7);np.testing.assert_allclose(result['points'][1],[5,4,0])
        result=calculate_measurement([f,point([-2,-3,5])]);self.assertAlmostEqual(result['distance'],math.sqrt(38));np.testing.assert_allclose(result['points'][0],[0,0,0])
    def test_edge_face_and_edge_edge_distances_and_angles(self):
        edge=cq.Edge.makeLine((2,2,4),(8,2,4));result=calculate_measurement([shape('edge',edge),shape('face',face())]);self.assertAlmostEqual(result['distance'],4);self.assertAlmostEqual(result['angle'],0)
        other=cq.Edge.makeLine((2,5,4),(8,5,4));result=calculate_measurement([shape('edge',edge),shape('edge',other)]);self.assertAlmostEqual(result['distance'],3)
        crossing=cq.Edge.makeLine((5,-1,4),(5,6,4));result=calculate_measurement([shape('edge',edge),shape('edge',crossing)]);self.assertAlmostEqual(result['distance'],0);self.assertAlmostEqual(result['angle'],90)
    def test_face_face_distance_and_face_area(self):
        a=face();b=a.translate((0,0,8));result=calculate_measurement([shape('face',a),shape('face',b)]);self.assertAlmostEqual(result['distance'],8);self.assertAlmostEqual(result['angle'],0);self.assertAlmostEqual(result['properties'][0]['area'],100)
    def test_circle_radius_diameter_and_distance_to_center(self):
        circle=cq.Edge.makeCircle(3,(0,0,0));result=calculate_measurement([shape('edge',circle),point([0,0,0])]);self.assertAlmostEqual(result['distance'],3);self.assertAlmostEqual(result['properties'][0]['radius'],3);self.assertAlmostEqual(result['properties'][0]['length'],6*math.pi)
    def test_sketch_region_hole_is_respected_and_cross_plane_distance(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=20),entity('circle',center=[0,0],radius=2)]
        profile=profile_regions(s)[0];selection=dict(kind='face',label='Sketch face',sketch=s,profile=profile,frame=s['frame'])
        result=calculate_measurement([point([0,0,3]),selection]);self.assertAlmostEqual(result['distance'],math.sqrt(13),places=6)
        edge=dict(kind='edge',label='Sketch edge',entity=entity('line',a=[0,0],b=[10,0]),frame=base_frame('XZ'))
        result=calculate_measurement([edge,point([5,7,0])]);self.assertAlmostEqual(result['distance'],7)

class MeasureUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        with patch('app.load_language',return_value='en'):self.w=Window()
        self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents()
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def click(self,p):
        screen=self.w.workspace.project_local([p],self.w.workspace.active_frame)[0]
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=QPointF(*screen).toPoint());self.app.processEvents()
    def test_one_top_button_remains_visible_in_both_modes_and_preserves_sketch(self):
        button=self.w.measure_button;self.assertTrue(button.isVisible());self.w.support_picked({'type':'plane','plane':'XY'})
        self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=10));draft=self.w.draft;before=copy.deepcopy(draft)
        QTest.mouseClick(button,Qt.LeftButton);self.assertTrue(self.w.workspace.measure_active);self.assertIs(self.w.draft,draft)
        self.click([-10,-5]);self.click([10,5]);result=self.w.workspace.measure_result;self.assertAlmostEqual(result['distance'],math.sqrt(500),places=6)
        self.assertEqual(draft,before);QTest.mouseClick(button,Qt.LeftButton);self.assertFalse(self.w.workspace.measure_active);self.assertEqual(self.w.workspace.mode,'sketch');self.assertIs(button,self.w.measure_button)
        self.w.cancel();self.app.processEvents();self.assertTrue(button.isVisible())
    def test_rectangle_side_and_face_auto_detection_without_mode_picker(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.add_entity(entity('rectangle',center=[0,0],width=30,height=20));self.w.toggle_measure();w=self.w.workspace
        def pick(p):return w.measure_pick(QPointF(*w.project_local([p],w.active_frame)[0]))
        self.assertEqual(pick([-15,-10])['kind'],'point');self.assertEqual(pick([0,-10])['kind'],'edge');self.assertEqual(pick([3,3])['kind'],'face')
        self.w.measure_picked(pick([0,-10]));self.assertAlmostEqual(w.measure_result['properties'][0]['length'],30)
        self.w.measure_picked(pick([0,10]));self.assertAlmostEqual(w.measure_result['distance'],20)
    def test_solid_face_pick_and_mixed_sketch_to_body_measurement(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
        f=dict(kind='extrude',id=identifier(),name='Box',depth=10,operation='add',source=dict(type='sketch',sketch=s['id'],entities=[s['entities'][0]['id']]))
        self.w.doc=Document([s,f]);self.w.workspace.set_mode('model');self.w.refresh(fit=True);self.w.workspace.aligned=np.eye(3);self.w.toggle_measure();w=self.w.workspace
        target=w.measure_pick(QPointF(*w.project([[3,2,10]])[0][0]));self.assertEqual(target['kind'],'face')
        self.w.measure_picked(point([3,2,15]));self.w.measure_picked(target);self.assertAlmostEqual(w.measure_result['distance'],5)
        self.assertEqual(len(self.w.doc.features),2)
    def test_third_click_restarts_escape_exits_without_canceling_sketch(self):
        self.w.support_picked({'type':'plane','plane':'XY'});draft=self.w.draft;self.w.toggle_measure()
        for p in ([0,0,0],[3,4,0],[8,1,0]):self.w.measure_picked(point(p))
        self.assertEqual(len(self.w.workspace.measure_selection),1);self.assertNotIn('distance',self.w.workspace.measure_result)
        QTest.keyClick(self.w.workspace,Qt.Key_Escape);self.assertFalse(self.w.workspace.measure_active);self.assertIs(self.w.draft,draft);self.assertEqual(self.w.workspace.mode,'sketch')
        QTest.keyClick(self.w.workspace,Qt.Key_M);self.assertTrue(self.w.workspace.measure_active)
        QTest.keyClick(self.w.workspace,Qt.Key_M);self.assertFalse(self.w.workspace.measure_active)
    def test_dimension_overlay_is_visible_and_tracks_camera(self):
        self.w.toggle_measure();w=self.w.workspace;self.w.measure_picked(point([0,0,0]));self.w.measure_picked(point([20,0,0]))
        def render():
            image=QImage(w.width(),w.height(),QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent);p=QPainter(image);w.paint_measure(p);p.end();return image
        image=render();self.assertGreater(np.count_nonzero(np.frombuffer(image.bits(),np.uint8)),100)
        w.pan+=np.array([20.,0.]);second=render();self.assertNotEqual(image,second);self.assertAlmostEqual(w.measure_result['distance'],20)
        self.app.processEvents();with_overlay=w.grab().toImage()
        w.measure_active=False;w.update();self.app.processEvents();without_overlay=w.grab().toImage()
        self.assertNotEqual(with_overlay,without_overlay)
        midpoint=np.mean(w.project(w.measure_result['points'])[0],axis=0)
        x,y=np.round(midpoint).astype(int)
        self.assertNotEqual(with_overlay.pixelColor(x,y),without_overlay.pixelColor(x,y))
