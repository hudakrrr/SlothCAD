import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from workspace import Workspace
from geometry import new_sketch,base_frame
from dimensions import values,constrain
class DynamicDimensionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Workspace();s=new_sketch(base_frame('XY'));self.w.set_mode('sketch',s,s['frame']);self.created=[];self.w.entity_created.connect(self.created.append);self.w.show();self.w.setFocus()
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def start(self,tool,cursor):self.w.set_tool(tool);self.w.draw_point(np.array([0.,0.]));self.w.cursor=np.array(cursor,dtype=float)
    def test_rectangle_type_tab_type_enter(self):
        self.start('rectangle',[12,8]);QTest.keyClicks(self.w,'23.5');QTest.keyClick(self.w,Qt.Key_Tab);self.assertEqual(self.w.dimension_index,1);QTest.keyClicks(self.w,'7.25');QTest.keyClick(self.w,Qt.Key_Return)
        self.assertEqual(len(self.created),1);self.assertEqual(self.created[0]['width'],23.5);self.assertEqual(self.created[0]['height'],7.25);self.assertEqual(self.w.dimension_locks,{})
    def test_line_length_and_angle(self):
        self.start('line',[6,8]);QTest.keyClicks(self.w,'20');QTest.keyClick(self.w,Qt.Key_Tab);QTest.keyClicks(self.w,'30');QTest.keyClick(self.w,Qt.Key_Return)
        np.testing.assert_allclose(self.created[0]['b'],[20*np.cos(np.pi/6),10]);self.assertEqual(len(self.w.points),1)
    def test_circle_decimal_comma_and_escape(self):
        self.start('circle',[3,4]);QTest.keyClicks(self.w,'8,5');QTest.keyClick(self.w,Qt.Key_Return);self.assertEqual(self.created[0]['radius'],8.5)
        self.start('rectangle',[4,5]);QTest.keyClicks(self.w,'9');QTest.keyClick(self.w,Qt.Key_Escape);self.assertEqual(self.w.points,[]);self.assertFalse(self.w.dimension_typing)
    def test_invalid_dimension_does_not_finish(self):
        self.start('circle',[3,4]);QTest.keyClicks(self.w,'-2');QTest.keyClick(self.w,Qt.Key_Return);self.assertEqual(self.created,[]);self.assertEqual(len(self.w.points),1)
    def test_arc_exact_chord_and_bend(self):
        self.start('arc',[10,0]);QTest.keyClicks(self.w,'12');QTest.keyClick(self.w,Qt.Key_Return);self.w.cursor=np.array([6,4.]);QTest.keyClicks(self.w,'3');QTest.keyClick(self.w,Qt.Key_Return)
        self.assertEqual(self.created[0]['b'],[12.,0.]);self.assertEqual(self.created[0]['mid'],[6.,3.])
    def test_locked_width_keeps_cursor_quadrant(self):
        np.testing.assert_allclose(constrain('rectangle',[[2,3]],[-8,-4],{0:5,1:6}),[-3,-3]);self.assertEqual(values('circle',[[0,0]],[3,4])[0][1],5)
