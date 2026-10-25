"""End-to-end constraint controls, picking, dragging and conflict feedback."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import unittest
import numpy as np
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity,regions
from constraints import validate_constraints

class ConstraintInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.show();self.app.processEvents();self.errors=[];self.w.error=self.errors.append
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.workspace.snap_enabled=False
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def pixel(self,xy):
        p=self.w.workspace.project_local([xy],self.w.workspace.active_frame)[0]
        return QPoint(round(p[0]),round(p[1]))
    def click(self,xy):
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=self.pixel(xy));self.app.processEvents()
    def mode(self,kind):
        action=next(a for a in self.w.constraint_menu.actions() if a.data()==kind);action.trigger();self.app.processEvents()
        self.assertEqual(self.w.workspace.tool,'constraint')
    def apply(self):self.w.constraint_apply_button.click();self.app.processEvents()
    def test_menu_picking_dimensions_drag_undo_redo_conflict(self):
        self.w.add_entity(entity('line',a=[-10,0],b=[10,0]));self.mode('horizontal');self.click([0,0]);self.apply()
        self.assertEqual(len(self.w.draft['constraints']),1)
        self.mode('dimension');self.click([0,0]);self.w.constraint_value.setValue(20);self.apply()
        self.assertEqual(len(self.w.draft['constraints']),2)
        self.w.set_tool('select');before=copy.deepcopy(self.w.draft)
        undo_count=len(self.w.sketch_undo);v=self.w.workspace
        QTest.mousePress(v,Qt.LeftButton,pos=self.pixel([10,0]))
        QTest.mouseMove(v,self.pixel([14,6]));QTest.qWait(40)
        QTest.mouseRelease(v,Qt.LeftButton,pos=self.pixel([14,6]));self.app.processEvents()
        validate_constraints(self.w.draft);line=self.w.draft['entities'][0]
        self.assertAlmostEqual(line['a'][1],line['b'][1],places=6)
        self.assertAlmostEqual(np.linalg.norm(np.array(line['b'])-line['a']),20,places=6)
        self.assertGreater(line['b'][1],4);self.assertEqual(len(self.w.sketch_undo),undo_count+1)
        after=copy.deepcopy(self.w.draft);self.w.undo()
        self.assertEqual(self.w.draft['entities'],before['entities']);self.w.redo();self.assertEqual(self.w.draft['entities'],after['entities'])
        mid=(np.array(line['a'])+line['b'])/2;self.mode('dimension');self.click(mid)
        self.w.constraint_value.setValue(25);prior=copy.deepcopy(self.w.draft);self.apply()
        self.assertEqual(self.w.draft,prior);self.assertIn('Conflicting constraints',self.w.constraint_feedback)
        self.assertTrue(self.w.constraint_conflicts);self.assertIn('Dimension',self.w.constraint_feedback)
        self.w.constraint_list.setCurrentRow(0);self.w.remove_sketch_constraint()
        self.assertEqual(len(self.w.draft['constraints']),1);self.w.undo();self.assertEqual(len(self.w.draft['constraints']),2)
    def test_tangency_and_point_origin_picking(self):
        self.w.add_entity(entity('line',a=[-12,0],b=[12,0]));self.w.add_entity(entity('circle',center=[0,3],radius=3))
        self.mode('tangent');self.click([-8,0]);self.click([3,3]);self.apply()
        self.assertIn('tangent',[c['kind'] for c in self.w.draft['constraints']]);validate_constraints(self.w.draft)
        self.w.add_entity(entity('point',p=[-5,4]));self.mode('coincident');self.click([-5,4]);self.click([0,0]);self.apply()
        self.assertEqual(self.w.draft['constraints'][-1]['refs'][1]['entity'],None)
        self.assertTrue(np.allclose(self.w.draft['entities'][-1]['p'],[0,0]))
    def test_numeric_edit_rejected_and_drag_cancel_restores_snapshot(self):
        self.w.add_entity(entity('circle',center=[0,0],radius=5));self.mode('dimension');self.click([5,0]);self.apply()
        self.w.set_tool('select');self.w.select_entity(0);self.w.precise_draft['radius']=8
        before=copy.deepcopy(self.w.draft);self.assertFalse(self.w.apply_entity())
        self.assertEqual(self.w.draft,before);self.assertIn('conflicts',self.w.constraint_feedback)
        self.w.precise_draft=None;self.w.entity_index=None;v=self.w.workspace
        self.w.begin_sketch_drag({'entity':before['entities'][0]['id'],'kind':'point','point':'center'},[0,0])
        self.w.move_sketch_drag([5,8]);QTest.qWait(60);self.app.processEvents();self.w.cancel_sketch_drag()
        self.assertEqual(self.w.draft,before);self.assertFalse(v.sketch_drag_preview)
    def test_constrained_rectangle_stays_closed_and_extrudes(self):
        self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=10))
        self.mode('dimension');self.click([0,-5]);self.w.constraint_value.setValue(20);self.apply()
        self.w.set_tool('select');v=self.w.workspace
        QTest.mousePress(v,Qt.LeftButton,pos=self.pixel([10,5]));QTest.mouseRelease(v,Qt.LeftButton,pos=self.pixel([12,9]))
        validate_constraints(self.w.draft);self.assertEqual(len(regions(self.w.draft)),1)
        self.assertTrue(self.w.finish_sketch());self.w.start_extrude();s=self.w.doc.features[0]
        self.w.extrusion_picked({'type':'sketch','sketch':s['id'],'entities':regions(s)[0]});self.w.widgets['depth'].setValue(10.);self.w.apply_feature()
        self.assertIsNotNone(self.w.doc.solid);self.assertTrue(self.w.doc.solid.val().isValid())
