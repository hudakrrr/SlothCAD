import os
import sys
import copy
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window
from model import Document, new_feature
from i18n import set_language
from geometry import new_sketch, base_frame, entity
from expression_spin import ExpressionSpinBox


def plate():
    f=new_feature();f.update(width=40,height=30,depth=10,id='base0001',name='Plate')
    return f


class ExpressionBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.show();self.app.processEvents()

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def test_box_accepts_numbers_and_expressions(self):
        from expressions import evaluate_with_parameters
        box=ExpressionSpinBox(lambda text:evaluate_with_parameters(text,{'L':20}))
        box.setRange(-1000,1000);box.setValue(5)
        self.assertEqual(box.valueFromText('7.5'),7.5);self.assertIsNone(box.expression)
        self.assertEqual(box.valueFromText('L/4'),5.);self.assertEqual(box.expression,'L/4')
        self.assertEqual(box.textFromValue(5.),'L/4')
        box.setValue(9.)                                   # a different number from code drops the expression
        self.assertIsNone(box.expression)
        self.assertEqual(box.valueFromText('2*'),9.)       # an unfinished expression keeps the value

    def test_feature_editor_stores_the_expression_and_rebuilds_with_it(self):
        self.w.doc=Document([plate()],parameters={'wall':3});self.w.refresh(True)
        self.w.select(0);self.app.processEvents()
        box=self.w.widgets['depth'];self.assertIsInstance(box,ExpressionSpinBox)
        box.lineEdit().setText('wall * 4');box.interpretText();self.app.processEvents()
        self.assertEqual(self.w.draft['expressions']['depth'],'wall * 4')
        self.assertAlmostEqual(self.w.draft['depth'],12)
        self.w.apply_feature();self.app.processEvents()
        self.assertEqual(self.w.doc.features[0]['expressions'],{'depth':'wall * 4'})
        # the parameter changes: the committed feature follows
        self.w.doc.set_parameters({'wall':5});self.w.refresh();self.app.processEvents()
        self.assertAlmostEqual(self.w.doc.features[0]['depth'],20)
        # reopening the editor shows the expression, not the number
        self.w.select(0);self.app.processEvents()
        self.assertEqual(self.w.widgets['depth'].expression,'wall * 4');self.assertEqual(self.w.widgets['depth'].lineEdit().text(),'wall * 4')

    def test_typing_a_number_removes_the_expression(self):
        feature=plate();feature['expressions']={'depth':'wall'};feature['expression_values']={'depth':3.}
        self.w.doc=Document([feature],parameters={'wall':3});self.w.refresh(True)
        self.w.select(0);self.app.processEvents()
        box=self.w.widgets['depth'];box.lineEdit().setText('8');box.interpretText();self.app.processEvents()
        self.assertNotIn('expressions',self.w.draft);self.assertEqual(self.w.draft['depth'],8)

    def test_parameter_change_marks_the_project_unsaved(self):
        self.w.doc=Document([plate()]);self.w.refresh(True)
        self.w.saved_features=copy.deepcopy(self.w.doc.features);self.w.saved_display=copy.deepcopy(self.w.doc.display)
        self.w.doc._saved_parameters=dict(self.w.doc.parameters)
        self.assertFalse(self.w.dirty())
        self.w.doc.set_parameters({'a':1});self.assertTrue(self.w.dirty())

    def test_autosave_snapshot_carries_parameters(self):
        self.w.doc=Document([plate()],parameters={'a':2});self.w.refresh(True)
        self.assertEqual(self.w.autosave.snapshot()['parameters'],{'a':2})


if __name__=='__main__':
    unittest.main()
