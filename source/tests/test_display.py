import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import cadquery as cq
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import base_frame,new_sketch,entity
from model import Document
from test_sketch_model import base_part,extrusion

class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.show();self.app.processEvents();self.errors=[];self.w.error=self.errors.append
        self.w.doc=Document(base_part());self.w.workspace.set_mode('model');self.w.refresh(True);self.app.processEvents()
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def body_item(self,index=0):return self.w.objects.topLevelItem(0).child(index)
    def sketch_item(self,index=0):return self.w.objects.topLevelItem(1).child(index)
    def test_body_visibility_hides_geometry_and_picking_keeps_export(self):
        before=copy.deepcopy(self.w.doc.features);volume=self.w.doc.solid.val().Volume()
        self.body_item().setCheckState(0,Qt.Unchecked);self.app.processEvents()
        self.assertEqual(len(self.w.workspace.faces),0);self.w.workspace.rasterize();self.assertTrue(np.all(self.w.workspace.face_buffer==-1))
        self.assertEqual(self.w.doc.features,before);self.assertAlmostEqual(self.w.doc.solid.val().Volume(),volume)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'hidden.step';self.w.doc.export(path)
            self.assertAlmostEqual(cq.importers.importStep(str(path)).val().Volume(),volume,places=5)
        self.body_item().setCheckState(0,Qt.Checked);self.assertEqual(len(self.w.workspace.faces),6)
    def test_each_disconnected_body_has_own_visibility(self):
        features=base_part();s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[100,0],width=10,height=10)]
        self.w.doc=Document(features+[s,extrusion(s,depth=5)]);self.w.refresh(True)
        self.assertEqual(self.w.objects.topLevelItem(0).childCount(),2);self.assertEqual(len(self.w.workspace.faces),12)
        self.body_item(1).setCheckState(0,Qt.Unchecked);self.assertEqual(len(self.w.workspace.faces),6)
        self.assertEqual(len(self.w.doc.solid.val().Solids()),2)
    def test_consumed_sketch_visibility_is_independent(self):
        self.assertEqual(self.sketch_item().checkState(0),Qt.Unchecked);self.assertEqual(len(self.w.workspace.sketches),0)
        self.sketch_item().setCheckState(0,Qt.Checked);self.assertEqual(len(self.w.workspace.sketches),1)
        self.body_item().setCheckState(0,Qt.Unchecked);self.assertEqual(len(self.w.workspace.sketches),1)
        self.sketch_item().setCheckState(0,Qt.Unchecked);self.assertEqual(len(self.w.workspace.sketches),0)
    def test_visibility_and_grid_preferences_roundtrip(self):
        self.body_item().setCheckState(0,Qt.Unchecked);self.sketch_item().setCheckState(0,Qt.Checked)
        self.w.grid_button.setChecked(False);self.w.axes_button.setChecked(False)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'display.fcad';self.w.doc.save(path);self.w.load(path)
            self.assertFalse(self.w.dirty());self.assertFalse(self.w.workspace.show_grid);self.assertFalse(self.w.workspace.show_axes)
            self.assertEqual(len(self.w.workspace.faces),0);self.assertEqual(len(self.w.workspace.sketches),1)
    def test_ribbon_switches_and_restores(self):
        self.assertIs(self.w.ribbon.currentWidget(),self.w.body_bar)
        QTest.mouseClick(self.w.body_buttons['sketch'],Qt.LeftButton);self.w.support_picked({'type':'plane','plane':'XY'})
        self.assertIs(self.w.ribbon.currentWidget(),self.w.sketch_bar)
        QTest.mouseClick(self.w.tool_buttons['circle'],Qt.LeftButton);self.assertEqual(self.w.workspace.tool,'circle')
        self.w.add_entity(entity('circle',center=[100,0],radius=5));self.w.finish_sketch()
        self.assertIs(self.w.ribbon.currentWidget(),self.w.body_bar)
    def test_grid_toggle_controls_body_and_sketch_without_changing_snap(self):
        self.assertTrue(self.w.workspace.show_grid);self.w.grid_button.setChecked(False);self.assertFalse(self.w.workspace.show_grid)
        self.w.start_sketch();self.w.support_picked({'type':'plane','plane':'XY'})
        self.assertFalse(self.w.workspace.show_grid);self.assertTrue(self.w.workspace.snap_enabled)
        self.w.grid_button.setChecked(True);self.assertTrue(self.w.workspace.show_grid)
        self.w.workspace.points=[];self.w.cancel()
    def test_timeline_selects_feature_for_editing(self):
        QTest.mouseClick(self.w.timeline_buttons[1],Qt.LeftButton)
        self.assertEqual(self.w.selected,1);self.assertTrue(self.w.timeline_buttons[1].isChecked());self.assertIn('depth',self.w.widgets)
        self.w.widgets['depth'].setValue(12);self.w.apply_feature()
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),40*30*12)

    def test_left_sidebar_is_only_compact_object_browser(self):
        self.assertFalse(hasattr(self.w,'history'));self.assertEqual(self.w.objects.objectName(),'objectBrowser')
        self.assertEqual(self.w.objects.indentation(),16);self.assertTrue(self.w.objects.uniformRowHeights())
    def test_timeline_hover_details_include_parameters_and_source(self):
        tip=self.w.timeline_buttons[1].toolTip();self.assertIn('mm',tip);self.assertIn('Source:',tip);self.assertIn('Active',tip)
        sketch=self.w.timeline_buttons[0].toolTip();self.assertIn('closed profiles',sketch);self.assertIn('Double-click',sketch)
    def test_double_click_timeline_sketch_opens_edit_mode(self):
        QTest.mouseDClick(self.w.timeline_buttons[0],Qt.LeftButton);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.draft_index,0)

    def checkbox_point(self,item):
        from PySide6.QtCore import QPoint
        rect=self.w.objects.visualItemRect(item)
        for x in range(rect.left(),min(rect.right(),rect.left()+100)):
            point=QPoint(x,rect.center().y())
            if self.w.objects.checkbox_at(point):return point
        self.fail('Checkbox indicator was not found')
    def test_double_click_checkbox_never_enters_sketch_editing(self):
        item=self.sketch_item();point=self.checkbox_point(item)
        QTest.mouseClick(self.w.objects.viewport(),Qt.LeftButton,pos=point)
        QTest.mouseDClick(self.w.objects.viewport(),Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'model');self.assertIsNone(self.w.draft)
        self.assertEqual(len(self.w.workspace.sketches),1)
    def test_double_click_sketch_name_opens_editing(self):
        from PySide6.QtCore import QPoint
        item=self.sketch_item();rect=self.w.objects.visualItemRect(item)
        point=QPoint(rect.left()+110,rect.center().y())
        QTest.mouseClick(self.w.objects.viewport(),Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'model')
        QTest.mouseDClick(self.w.objects.viewport(),Qt.LeftButton,pos=point);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.draft['id'],self.w.doc.features[0]['id'])
    def test_visibility_does_not_interrupt_extrusion_selection(self):
        self.w.start_extrude();item=self.sketch_item();item.setCheckState(0,Qt.Checked);self.app.processEvents()
        self.assertEqual(self.w.workspace.mode,'extrude');self.assertIsNone(self.w.draft)

if __name__=='__main__':unittest.main()
