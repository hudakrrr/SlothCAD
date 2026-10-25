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
        for expected in ('Import IGES / mesh…','Export drawing…','Export 3MF…','Export glTF (.glb)…'):self.assertIn(expected,file_names)

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
        with patch('analysis_ui._setting',side_effect=lambda key,default:{'export/quality':'fine','export/visible_only':'true'}.get(key,default)):
            tolerance,angular,visible=self.w.export_preferences()
        self.assertEqual((tolerance,angular,visible),(0.01,0.05,True))
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
