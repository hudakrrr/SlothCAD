import os,copy,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import numpy as np
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt,QSettings,QPointF
from PySide6.QtWidgets import QApplication,QGroupBox,QLabel
from PySide6.QtTest import QTest
from geometry import entity,new_sketch,base_frame,profile_regions,regions,snap,mirror_entities,frame_on_face
from trim import trim_entities
from model import Document,ModelError
from app import Window,CollapsibleSection

def sketch():
    s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=12)];return s

def extrude(s,**kwargs):
    f=dict(kind='extrude',id='e',name='Extrusion',enabled=True,depth=10,operation='add',signed_depth=True,source=dict(type='sketch',sketch=s['id'],entities=[s['entities'][0]['id']],profile_mode='nested'));f.update(kwargs);return f

class ReviewGeometryTests(unittest.TestCase):
    def test_construction_loop_is_snap_reference_but_not_a_hole(self):
        s=sketch();g=entity('circle',center=[0,0],radius=3,construction=True);s['entities'].append(g)
        self.assertEqual(len(regions(s)),1);self.assertEqual(profile_regions(s)[0]['holes'],[])
        self.assertAlmostEqual(Document([s,extrude(s)]).solid.val().Volume(),2400)
        point,label=snap([3.1,0],[g],1,.3);np.testing.assert_allclose(point,[3,0]);self.assertEqual(label,'vertex / center')
    def test_construction_only_sketch_is_valid_but_not_extrudable(self):
        s=sketch();s['entities'][0]['construction']=True;self.assertIsNone(Document([s]).solid)
        with self.assertRaisesRegex(ModelError,'Construction'):Document([s,extrude(s)])
    def test_mirror_and_trim_keep_guide_status(self):
        g=entity('line',a=[-5,0],b=[5,0],construction=True);axis=entity('line',a=[0,-5],b=[0,5])
        self.assertTrue(mirror_entities([g],axis)[0]['construction']);self.assertTrue(trim_entities([g,axis],0,[3,0])[0]['construction'])
    def test_symmetric_total_depth_and_offset(self):
        s=sketch();d=Document([s,extrude(s,direction='symmetric',offset=3)]);box=d.solid.val().BoundingBox()
        self.assertAlmostEqual(box.zmin,-2);self.assertAlmostEqual(box.zmax,8);self.assertAlmostEqual(d.solid.val().Volume(),2400)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            p=Path(td)/'part.fcad';d.save(p);self.assertAlmostEqual(Document.load(p).solid.val().Volume(),2400)
    def test_symmetric_cut_and_side_face_offset(self):
        s=sketch();base=extrude(s);d=Document([s,base]);top=max(d.solid.val().Faces(),key=lambda f:f.Center().z)
        cut=new_sketch(frame_on_face(top));cut['entities']=[entity('circle',center=[0,0],radius=2)]
        result=Document([s,base,cut,extrude(cut,depth=-4,direction='symmetric')]);self.assertAlmostEqual(result.solid.val().Volume(),2400-8*np.pi,places=6)
    def test_invalid_direction_is_atomic(self):
        s=sketch();d=Document([s]);before=copy.deepcopy(d.features)
        with self.assertRaises(ModelError):d.commit([s,extrude(s,direction='bad')])
        self.assertEqual(d.features,before)

class ReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path.cwd());QSettings.setPath(QSettings.NativeFormat,QSettings.UserScope,cls.temp.name);cls.app=QApplication.instance() or QApplication([])
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):import app as _a;_old=_a.DEFAULT_EXTRUDE_DEPTH;_a.DEFAULT_EXTRUDE_DEPTH=10.;self.addCleanup(setattr,_a,'DEFAULT_EXTRUDE_DEPTH',_old);self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents()
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def start(self):self.w.support_picked(dict(type='plane',plane='XY'))
    def test_keyboard_tools_and_guides_and_pending_numeric_edit(self):
        self.start();self.w.widgets['width'].setValue(31);QTest.keyClick(self.w.workspace,Qt.Key_L)
        self.assertEqual(self.w.draft['entities'][0]['width'],31);self.assertEqual(self.w.workspace.tool,'line')
        QTest.keyClick(self.w.workspace,Qt.Key_X);self.w.add_entity(entity('line',a=[0,0],b=[8,0]));self.assertTrue(self.w.draft['entities'][-1]['construction'])
    def test_preview_never_commits_and_parameter_change_restores(self):
        s=sketch();self.w.doc=Document([s]);self.w.workspace.set_mode('model');self.w.refresh()
        self.w.start_extrude();self.w.extrusion_picked(extrude(s)['source']);self.assertEqual(self.w.workspace.mode,'model')
        self.w.preview_feature();self.assertTrue(self.w.preview_active);self.assertIsNone(self.w.doc.solid);self.assertGreater(len(self.w.workspace.triangles),0)
        self.w.widgets['depth'].setValue(12);self.assertFalse(self.w.preview_active);self.assertEqual(len(self.w.workspace.triangles),0)
        self.w.preview_feature();self.w.cancel();self.assertEqual(len(self.w.doc.features),1);self.assertEqual(len(self.w.workspace.triangles),0)
    def test_preview_apply_has_one_undo_step(self):
        s=sketch();self.w.doc=Document([s]);self.w.workspace.set_mode('model');self.w.refresh();self.w.extrusion_picked(extrude(s)['source']);self.w.widgets['direction'].setCurrentIndex(self.w.widgets['direction'].findData('symmetric'));self.w.widgets['offset'].setValue(3)
        self.w.preview_feature();self.assertEqual(len(self.w.doc.undo_stack),0);self.w.apply_feature();self.assertEqual(len(self.w.doc.undo_stack),1);self.assertAlmostEqual(self.w.doc.solid.val().BoundingBox().zmin,-2,places=6)
    def test_enter_uses_latest_queued_cursor(self):
        self.start();w=self.w.workspace;w.draw_point(np.array([0.,0.]));w.cursor=np.array([5.,5.]);pos=QPointF(*w.project_local([[12,8]],w.active_frame)[0]);w.queue_motion(pos,Qt.NoButton)
        QTest.keyClick(w,Qt.Key_Return);e=self.w.draft['entities'][0];self.assertEqual(e['width'],12);self.assertEqual(e['height'],8)

    def test_workspace_help_tooltip_is_disabled(self):
        self.assertEqual(self.w.workspace.toolTip(),'')

    def test_pattern_stage_feedback_is_visible_in_editor(self):
        self.start();self.w.add_entity(entity('line',a=[0,-10],b=[0,10]));self.w.add_entity(entity('circle',center=[6,0],radius=2))
        self.w.start_pattern('mirror');self.w.choose_pattern_stage('axis');texts=[label.text() for label in self.w.editor.findChildren(QLabel)]
        self.assertTrue(any('Current step:' in text and 'guide line' in text.lower() for text in texts))

    def test_timeline_click_previews_history_and_revert_is_undoable(self):
        s=sketch();self.w.doc=Document([s,extrude(s)]);self.w.workspace.set_mode('model');self.w.refresh();self.assertGreater(len(self.w.workspace.triangles),0)
        self.w.timeline_select(0);self.assertEqual(self.w.history_preview_index,0);self.assertEqual(len(self.w.workspace.triangles),0)
        self.w.return_to_latest();self.assertIsNone(self.w.history_preview_index);self.assertGreater(len(self.w.workspace.triangles),0)
        with patch('app.QMessageBox.question',return_value=QMessageBox.Yes):self.w.revert_to_timeline(0)
        self.assertEqual(len(self.w.doc.features),1);self.assertIsNone(self.w.doc.solid);self.assertTrue(self.w.doc.undo());self.assertEqual(len(self.w.doc.features),2);self.assertIsNotNone(self.w.doc.solid)

    def test_disclosure_state_survives_geometry_changes(self):
        self.start();section=next(g for g in self.w.editor.findChildren(CollapsibleSection) if g.title()=='Geometry list');section.header.setChecked(True)
        self.w.add_entity(entity('circle',center=[0,0],radius=3));section=next(g for g in self.w.editor.findChildren(CollapsibleSection) if g.title()=='Geometry list');self.assertTrue(section.isChecked())

    def test_canceling_browser_edit_does_not_prompt_again_or_discard(self):
        s=sketch();self.w.doc=Document([s]);self.w.workspace.set_mode('model');self.w.refresh();self.w.select(0);self.w.edit_selected_sketch();self.w.add_entity(entity('circle',center=[0,0],radius=2))
        draft=copy.deepcopy(self.w.draft);item=self.w.objects.topLevelItem(1).child(0)
        with patch('app.QMessageBox.question',return_value=QMessageBox.Cancel) as question:self.w.object_edit(item,0)
        self.assertEqual(question.call_count,1);self.assertEqual(self.w.draft,draft)
