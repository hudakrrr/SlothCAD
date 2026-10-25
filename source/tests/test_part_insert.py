import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QFileDialog
from app import Window
from model import Document, new_feature
from i18n import set_language


class PartInsertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        f=new_feature();f.update(width=20,height=10,depth=5,id='pp0001',name='Block',expressions={'depth':'thick'})
        part=Document([f],parameters={'thick':5})
        self.part_path=Path(self.folder.name)/'bracket.fcad';part.save(self.part_path)
        self.w=Window();self.w.show();self.app.processEvents()
        self.w.doc=Document([]);self.w.refresh(True)

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def insert(self):
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(self.part_path),'')):
            self.w.insert_part_file()

    def test_inserting_the_same_file_twice_gives_two_independent_components(self):
        self.insert();self.insert()
        components=[f for f in self.w.doc.features if f['kind']=='component']
        self.assertEqual(len(components),2);self.assertNotEqual(components[0]['id'],components[1]['id'])
        self.assertEqual(len(self.w.doc.solids()),2)
        self.assertEqual(components[0]['name'],'bracket');self.assertEqual(components[0]['source_file'],str(self.part_path))

    def test_parameter_expressions_are_baked_so_the_part_stands_alone(self):
        self.insert()
        inner=self.w.doc.features[0]['features'][0]
        self.assertNotIn('expressions',inner);self.assertEqual(inner['depth'],5)

    def test_reloading_picks_up_a_changed_source(self):
        self.insert()
        changed=Document.load(self.part_path);edited=copy.deepcopy(changed.features);edited[0]['width']=44
        changed.commit(edited);changed.save(self.part_path)
        self.w.select(0);self.app.processEvents()
        self.w.reload_part_source();self.w.apply_feature();self.app.processEvents()
        box=self.w.doc.solids()[0].BoundingBox()
        self.assertAlmostEqual(box.xmax-box.xmin,44,places=5)


if __name__=='__main__':
    unittest.main()
