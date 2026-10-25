"""Interaction tests of one scene, plane/face picking, drawing and extrusion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint,QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from workspace import Workspace
from geometry import entity,regions,face_reference

class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        import app as _a;_old=_a.DEFAULT_EXTRUDE_DEPTH;_a.DEFAULT_EXTRUDE_DEPTH=10.;self.addCleanup(setattr,_a,'DEFAULT_EXTRUDE_DEPTH',_old);self.w=Window();self.w.show();self.app.processEvents();self.errors=[];self.w.error=self.errors.append
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()
        self.assertEqual(self.errors,[])
    def plane(self,name='XY'):self.w.support_picked({'type':'plane','plane':name});self.app.processEvents()
    def click_local(self,p):
        v=self.w.workspace;xy=v.project_local([p],v.active_frame)[0]
        QTest.mouseClick(v,Qt.LeftButton,pos=QPoint(round(xy[0]),round(xy[1])));self.app.processEvents()
    def solid(self):
        self.plane();self.w.add_entity(entity('rectangle',center=[0,0],width=40,height=30));self.w.finish_sketch();self.w.start_extrude()
        s=self.w.doc.features[0]
        self.w.extrusion_picked({'type':'sketch','sketch':s['id'],'entities':regions(s)[0]});self.w.apply_feature();self.app.processEvents()
    def visible_face_pixel(self,normal):
        v=self.w.workspace;v.rasterize()
        for i,face in enumerate(v.faces):
            if face.geomType()=='PLANE' and np.dot(face.normalAt().toTuple(),normal)>.9:
                ys,xs=np.where(v.face_buffer==i)
                if len(xs):
                    j=len(xs)//2;return QPoint(int(xs[j]),int(ys[j])),i
        self.fail('Expected planar face is not visible')
    def test_sketch_corner_toolbar_click_and_undo_redo(self):
        import copy
        self.plane();self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=10))
        before=copy.deepcopy(self.w.draft['entities'])
        self.w.tool_buttons['fillet'].click();self.app.processEvents()
        self.assertEqual(self.w.workspace.tool,'fillet')
        self.w.widgets['sketch_corner_size'].setValue(2);self.click_local([10,5])
        # Clicking only picks the corner; the arrow/preview follow, and Apply commits it.
        self.assertEqual(self.w.draft['entities'],before);self.assertEqual(len(self.w.sketch_corners),1)
        self.w.apply_sketch_corners()
        after=copy.deepcopy(self.w.draft['entities']);self.assertEqual(after[-1]['kind'],'arc')
        self.assertEqual(len(regions(self.w.draft)),1)
        self.w.undo();self.assertEqual(self.w.draft['entities'],before)
        self.w.redo();self.assertEqual(self.w.draft['entities'],after)
        self.w.tool_buttons['chamfer'].click();self.app.processEvents();self.click_local([-10,5]);self.w.apply_sketch_corners()
        self.assertEqual(self.w.draft['entities'][-1]['kind'],'line');self.assertEqual(len(regions(self.w.draft)),1)

    def test_editor_focus_does_not_change_history_or_prompt(self):
        self.solid();self.w.select(0);self.w.edit_selected_sketch();self.w.add_entity(entity('circle',center=[10,0],radius=2))
        self.w.select_entity(1);self.w.objects.setFocus();self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.draft_index,0)
    def test_only_one_workspace(self):
        self.assertEqual(len(self.w.findChildren(Workspace)),1);self.assertFalse(hasattr(self.w,'sketch'))
    def test_visual_plane_pick(self):
        self.assertEqual(self.w.workspace.mode,'support');self.app.processEvents()
        poly=self.w.workspace.plane_polygons['XY'];center=sum((p for p in poly),QPointF())/len(poly)
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=center.toPoint());self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.draft['frame']['normal'],[0,0,1])
    def test_rectangle_clicks_then_universal_profile_pick(self):
        self.plane();self.click_local([-10,-5]);self.click_local([10,5]);self.assertEqual(len(self.w.draft['entities']),1)
        self.w.finish_sketch();self.assertIsNone(self.w.doc.solid);self.w.start_extrude();self.app.processEvents()
        s=self.w.doc.features[0];frame=s['frame'];xy=self.w.workspace.project_local([[0,0]],frame)[0]
        QTest.mouseMove(self.w.workspace,QPoint(round(xy[0]),round(xy[1])))
        for _ in range(40):                       # the pointer batch is applied by a ~16 ms timer
            QTest.qWait(10);self.app.processEvents()
            if self.w.workspace.hover:break
        self.assertEqual(self.w.workspace.hover['type'],'sketch')
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=QPoint(round(xy[0]),round(xy[1])));self.app.processEvents()
        self.w.widgets['depth'].setValue(5);self.w.apply_feature();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),1000)
    def test_circle_center_and_radius_grid_snap(self):
        self.plane();self.w.set_tool('circle');self.click_local([2.2,3.2]);self.click_local([7.2,3.2])
        e=self.w.draft['entities'][0];np.testing.assert_allclose(e['center'],[2,3]);self.assertAlmostEqual(e['radius'],5)
    def test_line_chain_closes_profile_and_arc_tool(self):
        self.plane();self.w.set_tool('line')
        for p in [[0,0],[10,0],[10,10],[0,10],[0,0]]:self.click_local(p)
        self.assertEqual(len(regions(self.w.draft)),1)
        self.w.set_tool('arc')
        for p in [[-20,0],[-15,5],[-10,0]]:self.click_local(p)
        self.assertEqual(self.w.draft['entities'][-1]['kind'],'arc')
    def test_manual_rectangle_and_edge_snap(self):
        self.plane();self.w.widgets['width'].setValue(20.5);self.w.widgets['height'].setValue(10.5);self.w.apply_entity()
        self.w.set_tool('line');self.click_local([10.25,1.8]);self.click_local([20,1.8])
        e=self.w.draft['entities'][-1];self.assertAlmostEqual(e['a'][0],10.25)
        self.assertNotEqual(e['a'][0],round(e['a'][0]))
    def test_finish_commits_changed_numeric_geometry(self):
        self.plane();self.w.widgets['width'].setValue(20.5);self.w.widgets['height'].setValue(10.5)
        self.assertTrue(self.w.precise_changed());self.assertTrue(self.w.finish_sketch())
        self.assertEqual(self.w.doc.features[0]['entities'][0]['width'],20.5)
    def test_sketch_undo_redo(self):
        self.plane();self.w.add_entity(entity('circle',center=[0,0],radius=5));self.w.undo();self.assertEqual(self.w.draft['entities'],[])
        self.w.redo();self.assertEqual(len(self.w.draft['entities']),1)
    def test_planar_side_face_pick_to_sketch(self):
        self.solid();self.w.start_sketch();self.app.processEvents()
        # The default camera sees the positive Y face.
        point,i=self.visible_face_pixel([0,1,0]);QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertIsNotNone(self.w.draft['support'])
        np.testing.assert_allclose(self.w.draft['frame']['normal'],[0,1,0])
        self.w.set_tool('circle');self.click_local([0,0]);self.click_local([3,0]);self.w.finish_sketch()
        self.assertEqual(len(self.w.doc.features),3)
    def test_direct_face_extrusion_cursor_selection(self):
        self.solid();before=self.w.doc.solid.val().Volume();self.w.start_extrude();self.app.processEvents()
        point,i=self.visible_face_pixel([0,0,1]);QTest.mouseMove(self.w.workspace,point);QTest.qWait(20);self.app.processEvents()
        self.assertEqual(self.w.workspace.hover['type'],'face')
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.w.draft['source']['type'],'face');self.w.widgets['depth'].setValue(2);self.w.apply_feature()
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),before+40*30*2)
    def test_edit_sketch_rebuilds_later_extrusion(self):
        self.solid();self.w.select(0);self.w.edit_selected_sketch();self.w.select_entity(0)
        self.app.processEvents();self.w.widgets['width'].setValue(50);self.w.apply_entity();self.w.finish_sketch()
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),15000)
        self.w.undo();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),12000)
        self.w.redo();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),15000)

if __name__=='__main__':unittest.main()
