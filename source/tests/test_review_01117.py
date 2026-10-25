import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Window
from i18n import tr,set_language

class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.draw_palette.dismiss();self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')
    def test_draw_popup_mouse_click_selects_ellipse(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        QTest.mouseClick(self.w.draw_menu_button,Qt.LeftButton);self.app.processEvents()
        menu=self.w.draw_palette;self.assertTrue(menu.isVisible())
        button=next(b for b in menu.buttons if b.property('_tool')=='ellipse')
        menu.scroll.ensureWidgetVisible(button);self.app.processEvents()
        QTest.mouseClick(button,Qt.LeftButton);self.app.processEvents()
        self.assertEqual(self.w.workspace.tool,'ellipse');self.assertFalse(menu.isVisible())
    def test_language_switch_preserves_menu_and_translates_labels(self):
        menu=self.w.draw_palette
        with patch('app.save_language'):
            for language in ['hu','en','hu']:
                self.w.change_language(language);self.assertIs(menu,self.w.draw_palette)
        self.assertEqual(next(b.text() for b in menu.buttons if b.property('_tool')=='ellipse'),'Ellipszis')
        self.assertIn('Rajzeszközök',self.w.draw_menu_button.text())
    def test_modern_negative_depth_keeps_operation_choice(self):
        for operation in ['auto','add','cut']:
            f=dict(depth=5,operation=operation,source={'type':'sketch'})
            self.w.set_extrusion_depth(f,-3)
            self.assertEqual(f['operation'],operation);self.assertEqual(f['depth'],-3);self.assertFalse(f['signed_depth'])
    def test_edit_overlap_uses_only_earlier_features(self):
        self.w.doc.solid=object();self.w.doc.features=[{'name':'before'},{'name':'edited'},{'name':'after'}]
        self.w.draft_index=1;self.w.draft=dict(kind='extrude',operation='auto')
        captured=[]
        def preview(features,**kwargs):captured.extend(features)
        with patch.object(self.w.doc,'preview',side_effect=preview),patch.object(self.w,'run_busy',side_effect=lambda text,fn:fn(None)):
            self.w.resolved_feature()
        self.assertEqual(len(captured),2);self.assertEqual(captured[0]['name'],'before');self.assertEqual(captured[1]['operation'],'intersect')
    def test_hungarian_terms_and_safe_dynamic_translation(self):
        set_language('hu')
        self.assertEqual(tr('Redo'),'Újraalkalmazás')
        self.assertEqual(tr('Rows'),'Sorok száma')
        self.assertEqual(tr('surface interface'),'surface interface')
        self.assertEqual(tr('Exported /tmp/Sketch profile.step'),'Exportálva: /tmp/Sketch profile.step')
        self.assertIn('title="profile"',tr('<span title="profile">profile selected</span>'))
        self.assertIn('(Sketch profile)',tr('Feature 2 (Sketch profile): Unknown sketch profile.'))
