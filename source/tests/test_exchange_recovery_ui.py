import copy,os,tempfile,time,unittest,json
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity,base_frame,new_sketch,identifier
from model import Document
from exchange import import_step
from recovery import atomic_json,recovery_files
import cadquery as cq

class ExchangeRecoveryUITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=str(self.root/'recovery'));self.env.start();self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents()
 def tearDown(self):
  self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup();self.assertEqual(self.errors,[])
 def sketch(self):
  self.w.support_picked({'type':'plane','plane':'XY'});self.w.add_entity(entity('rectangle',center=[0,0],width=10,height=8))
 def test_file_actions_and_dxf_batch_sketch_undo_redo(self):
  from exchange import export_dxf
  expected={'Import…','Export…','Recover autosave…'};self.assertTrue(expected.issubset({a.property('_i18n_text') or a.text() for a in self.w.file_menu.actions()}))
  self.sketch();p=self.root/'batch.dxf';export_dxf(p,[entity('circle',center=[0,0],radius=2),entity('line',a=[-10,0],b=[10,0])])
  with patch('exchange_ui.QFileDialog.getOpenFileName',return_value=(str(p),'')):self.w.import_dxf_file()
  self.assertEqual(len(self.w.draft['entities']),3);self.w.undo();self.assertEqual(len(self.w.draft['entities']),1);self.w.redo();self.assertEqual(len(self.w.draft['entities']),3)
  out=self.root/'export.dxf'
  with patch('exchange_ui.QFileDialog.getSaveFileName',return_value=(str(out),'')):self.w.export_dxf_file()
  self.assertTrue(out.exists())
 def test_import_editor_scale_replacement_and_apply(self):
  p=self.root/'solid.step';cq.exporters.export(cq.Workplane('XY').box(5,6,7),str(p))
  with patch('exchange_ui.QFileDialog.getOpenFileName',return_value=(str(p),'')):self.w.import_step_file()
  self.w.select(0);self.assertEqual(self.w.draft['kind'],'import_solid');self.assertIn('scale',self.w.widgets);self.w.widgets['scale'].setValue(2);self.w.widgets['dx'].setValue(10);self.w.apply_feature();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),1680,places=5)
  self.w.undo();self.assertAlmostEqual(self.w.doc.solid.val().Volume(),210,places=5);self.w.redo();self.assertAlmostEqual(self.w.doc.solid.val().Center().x,10,places=6)
 def test_unfinished_sketch_precision_constraints_and_history_recover(self):
  self.sketch();self.w.select_entity(0);self.w.precise_draft['width']=14;self.w.apply_entity();self.w.undo();self.w.select_entity(0);self.w.precise_draft['height']=12
  self.w.workspace.points=[[1,2],[3,4]];self.w.workspace.tool='spline';data=self.w.autosave.snapshot();atomic_json(self.root/'recovery'/'interrupted.json',data);self.assertEqual(len(recovery_files(self.root/'recovery')),1)
  self.w.restore_autosave(data);self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.precise_draft['height'],12);self.assertEqual(self.w.workspace.points,[[1,2],[3,4]]);self.assertTrue(self.w.sketch_redo)
  self.w.workspace.points=[];self.w.undo();self.assertEqual(self.w.precise_draft['height'],8);self.w.redo();self.assertEqual(self.w.precise_draft['height'],12);self.w.undo();self.w.precise_draft=None;self.w.redo();self.assertEqual(self.w.draft['entities'][0]['width'],14)
 def test_atomic_autosave_background_and_clean_shutdown(self):
  self.sketch();self.w.autosave.tick();deadline=time.monotonic()+3
  while self.w.autosave.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
  self.assertFalse(self.w.autosave.busy);self.assertTrue(self.w.autosave.path.exists());data=json.loads(self.w.autosave.path.read_text());self.assertEqual(data['draft']['entities'][0]['kind'],'rectangle');self.assertEqual(list(self.w.autosave.root.glob('.writing-*')),[])
  self.w.autosave.cleanup();self.assertFalse(self.w.autosave.path.exists())
 def test_pending_edit_recovered_without_changing_committed_geometry(self):
  p=self.root/'solid.step';cq.exporters.export(cq.Workplane('XY').box(5,6,7),str(p));self.w.doc=Document([import_step(p)]);pending=copy.deepcopy(self.w.doc.features);pending[0]['scale']=-2;self.w.doc.pending_features=pending;data=self.w.autosave.snapshot();self.w.restore_autosave(data);self.assertEqual(self.w.doc.pending_features[0]['scale'],-2);self.assertAlmostEqual(self.w.doc.solid.val().Volume(),210,places=5)
 def test_point_undo_redo_and_plane_edit_history(self):
  self.sketch();self.w.workspace.points=[[0,0],[1,2],[3,4]];self.w.undo();self.assertEqual(len(self.w.workspace.points),2);self.w.redo();self.assertEqual(len(self.w.workspace.points),3);self.w.workspace.cancel_tool()
  self.w.change_sketch_plane({'type':'origin','plane':'XZ'});self.assertEqual(self.w.workspace.active_frame['normal'],[0.,-1.,0.]);self.w.undo();self.assertEqual(self.w.workspace.active_frame['normal'],[0.,0.,1.]);self.w.redo();self.assertEqual(self.w.workspace.active_frame['normal'],[0.,-1.,0.])
 def test_corrupt_autosave_ignored_and_invalid_restore_transactional(self):
  root=self.root/'recovery';root.mkdir(exist_ok=True);(root/'bad.json').write_text('broken');self.assertEqual(recovery_files(root),[]);before=self.w.doc
  with self.assertRaises(Exception):self.w.restore_autosave({'features':[{'kind':'bad','id':'bad'}]})
  self.assertIs(self.w.doc,before)
  with self.assertRaises(Exception):self.w.restore_autosave({'features':[],'source_path':42})
  self.assertIs(self.w.doc,before)

 def test_abrupt_process_exit_leaves_a_recoverable_session(self):
  import subprocess,sys
  code="""import os,time
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity
app=QApplication([]);w=Window();w.support_picked({'type':'plane','plane':'XY'});w.add_entity(entity('circle',center=[0,0],radius=7));w.autosave.tick()
deadline=time.monotonic()+5
while w.autosave.busy and time.monotonic()<deadline:time.sleep(.01)
assert w.autosave.path.exists()
os._exit(23)
"""
  result=subprocess.run([sys.executable,'-c',code],env=os.environ.copy(),capture_output=True,timeout=20);self.assertEqual(result.returncode,23,result.stderr.decode())
  files=recovery_files(self.root/'recovery',include_live=False);self.assertEqual(len(files),1);self.w.restore_autosave(files[0][1]);self.assertEqual(self.w.draft['entities'][0]['radius'],7);self.assertEqual(self.w.workspace.mode,'sketch')
