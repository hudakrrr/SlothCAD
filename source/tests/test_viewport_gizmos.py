"""Move/extrude controls tested against model state, typed values and real mouse events."""
import copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
import numpy as np
from app import Window
from model import Document,ModelError
from geometry import new_sketch,base_frame,entity,identifier,profile_regions
from references import body_reference

def sketch():
    s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)];return s

def feature(kind,**kw):return dict(kind=kind,id=identifier(),name=kind,enabled=True,**kw)
def source(s):
    r=profile_regions(s)[0];return dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'])

class SketchMoveModelTests(unittest.TestCase):
    def test_constraints_geometry_and_downstream_extrude_follow_placement(self):
        s=sketch()
        from constraints import add_constraint,new_constraint,line_ref
        s=add_constraint(s,new_constraint(s,'dimension',[line_ref(s['entities'][0]['id'],0)],20,'length'))
        original=copy.deepcopy(s)
        m=feature('sketch_move',sketch=s['id'],dx=3,dy=-4,dz=7)
        e=feature('extrude',source=source(s),depth=5,operation='add')
        d=Document([s,m,e]);np.testing.assert_allclose(d.frames[s['id']]['origin'],[3,-4,7]);self.assertEqual(d.sketches[s['id']],original)
        self.assertAlmostEqual(d.solid.val().Volume(),1000);self.assertAlmostEqual(d.solid.val().Center().z,9.5)
        changed=copy.deepcopy(d.features);changed[1]['dx']=9;d.commit(changed);self.assertAlmostEqual(d.solid.val().Center().x,9)
        d.undo();self.assertAlmostEqual(d.solid.val().Center().x,3);d.redo();self.assertAlmostEqual(d.solid.val().Center().x,9)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'placement.fcad';d.save(path);loaded=Document.load(path);self.assertAlmostEqual(loaded.solid.val().Center().x,9)
    def test_offsets_accumulate_and_suppression_works(self):
        s=sketch();a=feature('sketch_move',sketch=s['id'],dx=3);b=feature('sketch_move',sketch=s['id'],dz=-2)
        d=Document([s,a,b]);np.testing.assert_allclose(d.frames[s['id']]['origin'],[3,0,-2]);a['enabled']=False
        d=Document([s,a,b]);np.testing.assert_allclose(d.frames[s['id']]['origin'],[0,0,-2])
    def test_missing_sketch_and_invalid_offsets_give_feedback(self):
        with self.assertRaisesRegex(ModelError,'missing'):Document([feature('sketch_move',sketch='missing',dx=2)])
        s=sketch()
        with self.assertRaises(ModelError):Document([s,feature('sketch_move',sketch=s['id'],dx=float('nan'))])

class GizmoUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        import app as _a;_old=_a.DEFAULT_EXTRUDE_DEPTH;_a.DEFAULT_EXTRUDE_DEPTH=10.;self.addCleanup(setattr,_a,'DEFAULT_EXTRUDE_DEPTH',_old);self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents();self.w.workspace.snap_enabled=False
    def tearDown(self):
        self.w.draft=None;self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def extrude(self):
        s=sketch();self.w.doc=Document([s]);self.w.refresh();self.w.start_extrude()
        self.w.extrusion_picked(dict(source(s),type='sketch'));self.app.processEvents();return s
    def move(self):
        s=sketch();self.w.doc=Document([s,feature('extrude',source=source(s),depth=5,operation='add')]);self.w.refresh();self.w.start_body_tool('body_move')
        body=self.w.doc.solid.val().Solids()[0];self.w.draft['targets']=[body_reference(body,0,1)];self.w.show_editor();self.app.processEvents()
    def drag(self,axis,mm):
        g=self.w.workspace.gizmo;base,tip,unit=g.handles()[axis];start=tip-(tip-base)/np.linalg.norm(tip-base)*6
        self.assertTrue(g.press(QPointF(*start)));g.move(QPointF(*(start+unit*mm)));g.release();self.app.processEvents()
    def test_extrude_arrow_changes_distance_without_kernel_and_typing_matches_form(self):
        self.extrude();g=self.w.workspace.gizmo;self.assertIsNotNone(g.state);self.assertTrue(g.editor.isVisible())
        with patch.object(self.w.doc,'preview',side_effect=AssertionError('Kernel rebuild during drag')):
            self.drag(0,3);self.assertAlmostEqual(self.w.draft['depth'],13,places=4)
            g.editor.setFocus();g.editor.selectAll();QTest.keyClicks(g.editor,'-7.5');g.editor.interpretText()
            self.assertAlmostEqual(self.w.draft['depth'],-7.5);self.assertAlmostEqual(self.w.widgets['depth'].value(),-7.5)
        self.w.widgets['depth'].setValue(4);self.w.draft['operation']='add';self.w.apply_feature();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),800);self.assertIsNone(g.state)
    def test_move_xyz_ghost_drag_cancel_apply_undo(self):
        self.move();g=self.w.workspace.gizmo;before=self.w.doc.solid.val().Center().toTuple()
        with patch.object(self.w.doc,'preview',side_effect=AssertionError('Kernel rebuild during drag')):
            for axis,mm in enumerate((3,-2,4)):self.drag(axis,mm)
        self.assertEqual([self.w.draft[k] for k in ('dx','dy','dz')],[3,-2,4]);self.assertEqual(self.w.doc.solid.val().Center().toTuple(),before)
        base,tip,unit=g.handles()[0];self.assertTrue(g.press(QPointF(*tip)));g.move(QPointF(*(tip+unit*8)))
        QTest.keyClick(self.w.workspace,Qt.Key_Escape);self.assertFalse(g.dragging);self.assertAlmostEqual(self.w.draft['dx'],3)
        self.w.apply_feature();np.testing.assert_allclose(self.w.doc.solid.val().Center().toTuple(),np.asarray(before)+[3,-2,4],atol=1e-7)
        self.w.undo();np.testing.assert_allclose(self.w.doc.solid.val().Center().toTuple(),before,atol=1e-7)
    def test_real_mouse_drag_does_not_orbit_or_toggle_profile(self):
        self.extrude();w=self.w.workspace;g=w.gizmo;base,tip,unit=g.handles()[0];start=QPoint(int(tip[0]),int(tip[1]));end=start+QPoint(int(unit[0]*4),int(unit[1]*4));yaw=w.yaw
        QTest.mousePress(w,Qt.LeftButton,pos=start);QTest.mouseMove(w,end);QTest.mouseRelease(w,Qt.LeftButton,pos=end);self.app.processEvents()
        self.assertEqual(w.yaw,yaw);self.assertGreater(self.w.draft['depth'],12);self.assertEqual(len(self.w.extrude_hits),1);self.assertFalse(g.dragging)
    def test_edge_on_axis_and_tab_and_symmetric_distance(self):
        self.move();self.w.view_preset('Top');g=self.w.workspace.gizmo;self.drag(2,3);self.assertAlmostEqual(self.w.draft['dz'],3,places=4)
        g.editor.setFocus();QTest.keyClick(g.editor,Qt.Key_Tab);self.assertEqual(g.axis,0)
        self.w.cancel();self.w.start_extrude();s=self.w.doc.sketches[next(iter(self.w.doc.sketches))];self.w.extrusion_picked(source(s));self.w.draft['direction']='symmetric';self.w.show_editor();self.drag(0,2)
        self.assertAlmostEqual(self.w.draft['depth'],14,places=4)
    def test_whole_sketch_move_preview_cancel_and_apply(self):
        s=sketch();self.w.doc=Document([s]);self.w.refresh();self.w.selected=0;self.w.start_sketch_move();g=self.w.workspace.gizmo
        self.drag(0,3);self.drag(2,5);self.w.preview_feature();self.assertIsNone(self.w.doc.solid);np.testing.assert_allclose(self.w.doc.frames[s['id']]['origin'],[0,0,0])
        np.testing.assert_allclose(self.w.workspace.sketches[0][1]['origin'],[3,0,5]);self.w.apply_feature();np.testing.assert_allclose(self.w.doc.frames[s['id']]['origin'],[3,0,5]);self.assertIsNone(g.state)
    def test_move_sketch_is_inserted_before_existing_extrusion_and_edits_rebuild_it(self):
        s=sketch();self.w.doc=Document([s,feature('extrude',source=source(s),depth=5,operation='add')]);self.w.refresh();self.w.selected=0
        self.w.start_sketch_move();self.drag(0,3);self.w.apply_feature()
        self.assertEqual([f['kind'] for f in self.w.doc.features],['sketch','sketch_move','extrude'])
        self.assertAlmostEqual(self.w.doc.solid.val().Center().x,3)
        self.w.select(1);self.assertAlmostEqual(self.w.workspace.gizmo.state['origin'][0],0)
        self.w.widgets['dx'].setValue(8);self.w.apply_feature();self.assertAlmostEqual(self.w.doc.solid.val().Center().x,8)

    def test_escape_consumes_mouse_release_and_preserves_profile_selection(self):
        self.extrude();w=self.w.workspace;g=w.gizmo;tip=g.handles()[0][1];unit=g.handles()[0][2]
        start=QPoint(round(tip[0]),round(tip[1]));end=QPoint(round(tip[0]+unit[0]*4),round(tip[1]+unit[1]*4));yaw=w.yaw
        QTest.mousePress(w,Qt.LeftButton,pos=start);QTest.mouseMove(w,end);w.flush_motion();self.assertGreater(self.w.draft['depth'],12)
        QTest.keyClick(w,Qt.Key_Escape);QTest.mouseRelease(w,Qt.LeftButton,pos=end)
        self.assertEqual(self.w.draft['depth'],10);self.assertEqual(len(self.w.extrude_hits),1);self.assertEqual(w.yaw,yaw);self.assertFalse(g.consume_release)
    def test_typing_from_workspace_and_exact_submillimeter_translation(self):
        self.move();w=self.w.workspace;g=w.gizmo;w.setFocus();QTest.keyClick(w,Qt.Key_3);self.assertIs(self.app.focusWidget(),g.editor);QTest.keyClicks(self.app.focusWidget(),'.125');g.editor.interpretText()
        self.assertAlmostEqual(self.w.draft['dx'],3.125,places=4);QTest.keyClick(g.editor,Qt.Key_Tab)
        g.editor.selectAll();QTest.keyClicks(g.editor,'-0.0001');g.editor.interpretText()
        self.assertAlmostEqual(self.w.draft['dy'],-.0001,places=4);self.assertAlmostEqual(g.state['values'][0],3.125,places=4)

    def test_nondistance_extents_and_measure_hide_drag_controls(self):
        self.extrude();self.w.draft['extent']='through all';self.w.show_editor();self.assertIsNone(self.w.workspace.gizmo.state)
        self.w.draft['extent']='distance';self.w.show_editor();self.w.toggle_measure();self.assertIsNone(self.w.workspace.gizmo.state)

if __name__=='__main__':unittest.main()
