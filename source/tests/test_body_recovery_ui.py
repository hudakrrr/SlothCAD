import os,copy,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app import Window
from body_ui import RecoveryDialog
import tests.test_body_recovery as helpers
from references import body_reference
from solid_tools import face_ref
from model import ModelError

class BodyRecoveryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.doc=helpers.BodyRecoveryTests().base();self.w.workspace.set_mode('model');self.w.refresh();self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def test_menu_explicit_target_move_copy_and_undo(self):
        action=next(a for a in self.w.body_menu.actions() if a.data()=='body_move');action.trigger()
        self.assertEqual(self.w.draft['targets'],[]);original=self.w.doc.solid.val().Solids()[1].Center().toTuple()
        self.w.widgets['targets'].item(0).setSelected(True);self.w.widgets['dx'].setValue(30);self.w.widgets['copy'].setChecked(True)
        self.w.preview_feature();self.assertEqual(len(self.w.doc.features),4);self.assertEqual(len(self.w.workspace.mesh_shape.Solids()),3)
        self.w.apply_feature();self.assertEqual(len(self.w.doc.solid.val().Solids()),3);self.assertEqual(self.w.doc.solid.val().Solids()[1].Center().toTuple(),original)
        self.w.undo();self.assertEqual(len(self.w.doc.solid.val().Solids()),2);self.w.redo();self.assertEqual(len(self.w.doc.solid.val().Solids()),3)
    def test_pattern_split_and_combine_fields_and_viewport_selection(self):
        for kind in ('body_rectangular','body_circular','body_split','body_combine','body_mirror'):
            self.w.start_body_tool(kind);self.assertIn('targets',self.w.widgets)
            if kind=='body_combine':self.assertIn('tools',self.w.widgets)
            self.w.cancel()
        self.w.start_body_tool('body_rectangular');self.w.enable_face_pick('targets')
        first=self.w.doc.solid.val().Solids()[0];index=next(i for i,face in enumerate(self.w.workspace.faces) if any(face.isSame(f) for f in first.Faces()))
        self.w.pick_solid_face(index);self.assertEqual(len(self.w.draft['targets']),1);self.assertTrue(self.w.workspace.solid_selected_faces)
        self.w.widgets['spacing_x'].setValue(30);self.w.widgets['columns'].setValue(3);self.w.apply_feature();self.assertEqual(len(self.w.doc.solid.val().Solids()),4)
    def test_upstream_editor_dimension_and_recovery_inspection(self):
        helper=helpers.BodyRecoveryTests();top=max(self.w.doc.solid.val().Solids()[0].Faces(),key=lambda face:face.Center().z)
        shell=helper.feature('shell',body=0,faces=[face_ref(top,self.w.doc.solid)],thickness=-1);self.w.doc.commit(self.w.doc.features+[shell]);self.w.refresh()
        self.w.selected=0;self.w.edit_selected_sketch();self.w.select_entity(0);self.w.precise_draft['width']=30;self.assertTrue(self.w.apply_entity());self.assertTrue(self.w.finish_sketch())
        self.assertAlmostEqual(self.w.doc.solid.val().Solids()[0].BoundingBox().xmax,15,places=6)
        dialog=RecoveryDialog(self.w);self.assertTrue(any(r['state']=='recovered' for r in dialog.report));self.assertFalse(any(r['state']=='needs repair' for r in dialog.report));dialog.reject();dialog.deleteLater()
    def test_repair_dialog_keeps_upstream_candidate_and_commits_atomically(self):
        helper=helpers.BodyRecoveryTests();top=max(self.w.doc.solid.val().Solids()[0].Faces(),key=lambda face:face.Center().z)
        shell=helper.feature('shell',body=0,faces=[face_ref(top,self.w.doc.solid)],thickness=-1);self.w.doc.commit(self.w.doc.features+[shell]);self.w.refresh()
        old=copy.deepcopy(self.w.doc.features);changed=copy.deepcopy(old);changed[0]['entities'][0]['width']=30;changed[-1]['faces'][0]['geometry']='SPHERE'
        with self.assertRaises(ModelError):self.w.doc.commit(changed)
        self.assertEqual(self.w.doc.features,old)
        dialog=RecoveryDialog(self.w);self.assertEqual(dialog.history.currentRow(),len(changed)-1)
        index=next(i for i in range(dialog.slots.count()) if dialog.slots.itemData(i)[0]==['faces',0]);dialog.slots.setCurrentIndex(index)
        replacement=next(i for i in range(dialog.replacements.count()) if dialog.replacements.itemData(i).get('normal')==[0.,0.,1.]);dialog.replacements.setCurrentIndex(replacement);dialog.replace_reference()
        self.assertFalse(any(r['state']=='needs repair' for r in dialog.report));dialog.apply_repairs()
        self.assertIsNone(self.w.doc.pending_features);self.assertAlmostEqual(self.w.doc.features[0]['entities'][0]['width'],30);self.assertEqual(self.w.doc.features[-1]['faces'][0]['geometry'],'PLANE')
        self.w.undo();self.assertEqual(self.w.doc.features,old);dialog.deleteLater()

    def test_reference_preview_restores_measurement_and_camera(self):
        first=self.w.doc.solid.val().Solids()[0]
        self.w.doc.commit(self.w.doc.features+[helpers.BodyRecoveryTests().feature('body_move',targets=[body_reference(first,0,2)],dx=0,dy=5,dz=0,angle=0,axis={'type':'origin','axis':'Z'},copy=False)])
        self.w.refresh();workspace=self.w.workspace;workspace.set_measure_active(True)
        workspace.measure_result={'distance':12.,'points':[[0,0,0],[12,0,0]]};workspace.zoom=1.7
        dialog=RecoveryDialog(self.w);dialog.show_reference()
        self.assertTrue(dialog.previewing);self.assertFalse(workspace.measure_active)
        dialog.reject();self.assertTrue(workspace.measure_active);self.assertEqual(workspace.measure_result['distance'],12.);self.assertEqual(workspace.zoom,1.7)
        self.assertEqual(len(workspace.mesh_shape.Solids()),2);dialog.deleteLater()
