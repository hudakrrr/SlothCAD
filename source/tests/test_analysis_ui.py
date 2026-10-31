import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTableWidget, QFileDialog
import ezdxf
from app import Window
from model import Document, new_feature
from i18n import set_language


def plate(**fields):
    f=new_feature();f.update(width=40,height=30,depth=10,id='plate001',name='Plate');f.update(fields);return f


class AnalysisUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.settings=tempfile.TemporaryDirectory();self.addCleanup(self.settings.cleanup)
        self.w=Window();self.w.resize(900,700);self.w.show();self.app.processEvents()
        block=dict(kind='primitive',id='block001',name='Block',enabled=True,shape='box',width=20.,length=20.,height=20.,origin=[-10,-10,0],operation='new')
        self.w.doc=Document([plate(),block]);self.w.refresh(True);self.app.processEvents()   # a second body overlapping the plate
        self.captured=[]

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def run_dialog(self,call):
        def fake(dialog):
            self.captured.append(dialog);return QDialog.Accepted
        with patch.object(QDialog,'exec',fake):return call()

    def test_menus_exist(self):
        titles=[a.text() for a in self.w.menuBar().actions()]
        self.assertIn('Tools',titles)
        names=[a.text() for a in next(a.menu() for a in self.w.menuBar().actions() if a.text()=='Tools').actions() if not a.isSeparator()]
        self.assertEqual(names[:3],['Mass properties…','Check interference','Bill of materials…'])
        file_names=[a.text() for a in next(a.menu() for a in self.w.menuBar().actions() if a.text()=='File').actions()]
        for expected in ('Import…','Export…'):self.assertIn(expected,file_names)
        for gone in ('Import STEP…','Import DXF…','Import IGES / mesh…','Export STEP…','Export STL…','Export DXF…','Export drawing…','Export 3MF…','Export glTF (.glb)…'):self.assertNotIn(gone,file_names)

    def test_import_and_export_ask_for_the_file_type_first(self):
        from exchange_ui import IMPORT_FORMATS,EXPORT_FORMATS
        self.assertIn('stl',[f[0] for f in IMPORT_FORMATS])
        with patch.object(type(self.w),'choose_file_format',return_value='stl'),patch.object(type(self.w),'import_model_file') as importer:
            self.w.import_file()
        self.assertIn('*.stl',importer.call_args.args[0])
        with patch.object(type(self.w),'choose_file_format',return_value='dxf'),patch.object(type(self.w),'import_dxf_file') as importer:
            self.w.import_file()
        importer.assert_called_once()
        with patch.object(type(self.w),'choose_file_format',return_value='3mf'),patch.object(type(self.w),'export_format') as exporter:
            self.w.export_file()
        exporter.assert_called_once_with('3mf')
        with patch.object(type(self.w),'choose_file_format',return_value=None),patch.object(type(self.w),'export_format') as exporter:
            self.w.export_file()
        exporter.assert_not_called()

    def test_import_runs_in_a_worker_process_and_keeps_the_ui_responsive(self):
        import cadquery as cq,time
        from PySide6.QtCore import QTimer
        import exchange_ui
        stages=[];gaps=[];last=[time.monotonic()];in_worker=[True]
        original=exchange_ui.ImportProgressDialog.set_stage
        def record(dialog,text,*args,**kwargs):
            stages.append(text)
            if text=='Adding it to the model…':in_worker[0]=False
            return original(dialog,text,*args,**kwargs)
        def tick():
            now=time.monotonic()
            if in_worker[0]:gaps.append(now-last[0])
            last[0]=now
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'ball.stl');cq.exporters.export(cq.Workplane().sphere(10).val(),target,tolerance=.1)
            self.w.doc=Document([]);self.w.refresh(True)
            timer=QTimer();timer.timeout.connect(tick);timer.start(20)
            with patch.object(exchange_ui.ImportProgressDialog,'set_stage',record):
                self.assertTrue(self.w.import_feature_file(target))
            timer.stop()
        self.assertEqual(len(self.w.doc.solids()),1)
        self.assertIn('Sewing {count} triangles into a solid…',stages)
        self.assertLess(max(gaps),.5)     # the kernel work ran in another process

    def test_exports_and_analysis_run_in_the_kernel_process(self):
        import kernel_process
        calls=[];original=kernel_process.KERNEL.call
        def spy(op,args=None,report=None):calls.append(op);return original(op,args,report)
        with tempfile.TemporaryDirectory() as folder,patch.object(kernel_process.KERNEL,'call',side_effect=spy):
            target=Path(folder)/'part.step'
            with patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'')):self.w.export_format('step')
            self.assertTrue(target.exists() and target.stat().st_size>0)
            unit=self.w._unit_mass_properties(False)
            self.assertAlmostEqual(unit['volume'],self.w.doc.mass_properties(1.)['volume'],places=4)
            self.assertEqual(len(self.run_dialog(self.w.check_interference) or []),1)
        self.assertEqual(calls,['export','mass','interference'])

    def test_kernel_process_recovers_after_it_dies(self):
        import kernel_process
        kernel_process.KERNEL.call('ping');kernel_process.KERNEL.process.kill();kernel_process.KERNEL.process.wait()
        self.assertTrue(kernel_process.KERNEL.call('ping'))

    def test_run_busy_keeps_the_viewport_frozen_and_restores_filters(self):
        import threading
        from PySide6.QtCore import QTimer
        seen=[]
        def probe():seen.append((self.w.centralWidget().updatesEnabled(),self.w.busy_progress.isVisible()))
        timer=QTimer();timer.timeout.connect(probe);timer.start(20)
        self.w.run_busy('Long',lambda report:(report(1,4,'Step'),threading.Event().wait(.5)))
        timer.stop()
        self.assertIn((False,True),seen)
        self.assertTrue(self.w.centralWidget().updatesEnabled());self.assertTrue(self.w.centralWidget().isEnabled())
        self.assertEqual(self.w.busy_progress.maximum(),4)

    def test_import_can_be_cancelled(self):
        import cadquery as cq
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        import exchange_ui
        def cancel():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget,exchange_ui.ImportProgressDialog) and widget.isVisible():widget.cancel_button.click();return
            QTimer.singleShot(50,cancel)
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'ball.stl');cq.exporters.export(cq.Workplane().sphere(10).val(),target,tolerance=.02)
            self.w.doc=Document([]);self.w.refresh(True)
            QTimer.singleShot(300,cancel)
            self.assertFalse(self.w.import_feature_file(target))
        self.assertEqual(self.w.doc.features,[])

    def test_import_errors_from_the_worker_are_reported(self):
        from legacy_model import ModelError
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'open.stl'
            target.write_text('solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n')
            with self.assertRaisesRegex(ModelError,'watertight'):self.w.import_feature_file(str(target))

    def test_stl_file_imports_as_a_solid(self):
        import cadquery as cq
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'box.stl');cq.exporters.export(cq.Workplane().box(10,20,5).val(),target)
            self.w.doc=Document([]);self.w.refresh(True)
            with patch.object(type(self.w),'choose_file_format',return_value='stl'),patch.object(QFileDialog,'getOpenFileName',return_value=(target,'')):
                self.w.import_file()
            self.assertEqual(len(self.w.doc.solids()),1)
            self.assertAlmostEqual(self.w.doc.solid.val().Volume(),1000,places=3)

    def test_mass_properties_dialog_reports_values(self):
        self.run_dialog(self.w.show_mass_properties)
        dialog=self.captured[0];text=' '.join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn('Volume',text);self.assertIn('Mass',text);self.assertIn('Principal moments',text)
        self.assertIn('Body 2',text)                                   # per-body list for two bodies

    def test_interference_finds_the_overlap(self):
        pairs=self.run_dialog(self.w.check_interference)
        self.assertEqual(len(pairs),1);self.assertEqual({pairs[0][0],pairs[0][1]},{'Body 1','Body 2'})
        self.assertGreater(pairs[0][2],0)
        self.assertTrue(any(isinstance(d,QDialog) for d in self.captured))

    def test_no_interference_reports_in_the_status_bar(self):
        far=dict(kind='primitive',id='far00001',name='Far',enabled=True,shape='box',width=5.,length=5.,height=5.,origin=[200,0,0],operation='new')
        self.w.doc=Document([plate(),far]);self.w.refresh(True)
        self.assertEqual(self.run_dialog(self.w.check_interference),[])
        self.assertIn('No interference',self.w.statusBar().currentMessage())

    def test_bill_of_materials_and_csv(self):
        rows=self.run_dialog(self.w.show_bill_of_materials)
        self.assertEqual(sorted(r['name'] for r in rows),['Body 1','Body 2'])
        csv_text=self.w.bill_as_csv(rows)
        self.assertTrue(csv_text.startswith('Part,Quantity,Volume (mm3)'))

    def test_export_preferences_and_formats(self):
        with patch('analysis_ui._setting',side_effect=lambda key,default:{'export/quality':'fine'}.get(key,default)):
            tolerance,angular,visible=self.w.export_preferences()
        self.assertEqual((tolerance,angular,visible),(0.01,0.05,True))     # hidden bodies are left out by default
        with patch('analysis_ui._setting',side_effect=lambda key,default:{'export/include_hidden':'true'}.get(key,default)):
            self.assertFalse(self.w.export_preferences()[2])
        with tempfile.TemporaryDirectory() as folder:
            for kind,suffix in (('3mf','.3mf'),('glb','.glb'),('stl','.stl'),('step','.step')):
                target=str(Path(folder)/('out'+suffix))
                with patch.object(QFileDialog,'getSaveFileName',return_value=(target,'')):
                    self.w.export_format(kind)
                self.assertTrue(Path(target).exists() and Path(target).stat().st_size>100,kind)

    def test_export_drawing_writes_a_dxf(self):
        options=dict(views=['front','top'],hidden=True,dimensions=True,scale=1.)
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'sheet.dxf')
            with patch.object(self.w,'drawing_options',return_value=options),patch.object(QFileDialog,'getSaveFileName',return_value=(target,'')):
                self.w.export_drawing_file()
            document=ezdxf.readfile(target)
            self.assertTrue(any(e.dxf.layer=='VISIBLE' for e in document.modelspace()))

    def test_import_model_file_applies_step_colours(self):
        import exchange
        self.w.doc.display['materials']={'0':{'color':'#ff0000','finish':'matte'}}
        with tempfile.TemporaryDirectory() as folder:
            target=str(Path(folder)/'c.step');Document([plate()],parameters={}).export(target,colors=True)
            fresh=Document([plate(id='p0')]);fresh.display['materials']={'0':{'color':'#ff0000','finish':'matte'}}
            fresh.export(target)
            self.w.doc=Document([]);self.w.refresh(True)
            with patch.object(QFileDialog,'getOpenFileName',return_value=(target,'')):
                self.w.import_model_file()
            self.assertEqual(len(self.w.doc.solids()),1)
            self.assertEqual(self.w.doc.display['materials']['0']['color'],'#ff0000')


if __name__=='__main__':
    unittest.main()
