"""Fixed mode area on the right, Inspect in the scrolling ribbon, unclipped dropdown rows."""
import os,tempfile,unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app import Window


class ToolbarLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.temp.name);self.env.start()
        self.w=Window();self.w.change_language('en');self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup()

    def test_mode_and_sketch_actions_are_fixed_and_inspect_scrolls(self):
        self.assertTrue(self.w.ribbon_scroll.isAncestorOf(self.w.measure_button))
        self.assertFalse(self.w.ribbon_scroll.isAncestorOf(self.w.body_mode_badge))
        self.assertTrue(self.w.body_mode_badge.isVisible());self.assertFalse(self.w.sketch_action_group.isVisible())
        self.w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        self.assertTrue(self.w.sketch_action_group.isVisible());self.assertTrue(self.w.sketch_mode_badge.isVisible())
        self.assertFalse(self.w.body_mode_badge.isVisible())
        badge=self.w.sketch_mode_badge.mapTo(self.w,self.w.sketch_mode_badge.rect().topLeft()).x()
        finish=self.w.sketch_actions['finish'].mapTo(self.w,self.w.sketch_actions['finish'].rect().topLeft()).x()
        self.assertLess(badge,finish)
        self.w.cancel();self.app.processEvents();self.assertFalse(self.w.sketch_action_group.isVisible())

    def test_every_dropdown_row_fits_its_text(self):
        for key,palette in self.w.tool_palettes.items():
            if not palette.anchor.isVisible():continue
            with self.subTest(key=key):
                palette.toggle();self.app.processEvents()
                for button in palette.buttons:
                    self.assertGreaterEqual(button.height(),button.sizeHint().height())
                    self.assertGreaterEqual(button.height(),button.fontMetrics().height()+12)
                if palette.height()<self.w.centralWidget().height()-palette.y()-8:
                    self.assertFalse(palette.scroll.verticalScrollBar().isVisible())
                palette.dismiss()


if __name__=='__main__':unittest.main()


class ValueHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from model import Document,new_feature
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.temp.name);self.env.start()
        self.w=Window();self.w.change_language('en');self.w.show();self.app.processEvents()
        box=new_feature();box.update(width=20,height=16,depth=12);self.w.doc=Document([box]);self.w.refresh(True)
    def tearDown(self):
        self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup()

    def test_fillet_and_chamfer_have_a_draggable_size_arrow(self):
        for kind,label in (('fillet','Radius'),('chamfer','Distance')):
            with self.subTest(kind=kind):
                self.w.new_edge(kind);self.app.processEvents();self.assertIsNone(self.w.workspace.gizmo.state)
                self.w.workspace.selected_edges={0};self.w.edge_selection_changed();self.app.processEvents()
                state=self.w.workspace.gizmo.state;self.assertIsNotNone(state)
                self.assertEqual((state['kind'],state['label']),('value',label))
                state['setter'](0,2.5);self.assertAlmostEqual(self.w.draft['radius'],2.5)
                self.w.cancel();self.app.processEvents()


class EscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from model import Document,new_feature
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.temp.name);self.env.start()
        self.w=Window();self.w.change_language('en');self.w.show();self.app.processEvents()
        box=new_feature();box.update(width=20,height=16,depth=12);self.w.doc=Document([box]);self.w.refresh(True)
    def tearDown(self):
        self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup()
    def escape(self,widget=None):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        QTest.keyClick(widget or self.w.workspace,Qt.Key_Escape);self.app.processEvents()

    def test_escape_leaves_a_drawing_tool_but_keeps_the_sketch(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.set_tool('line');self.w.workspace.points=[[0,0]]
        self.escape();self.assertEqual(self.w.workspace.tool,'select');self.assertEqual(self.w.workspace.points,[])
        self.assertEqual(self.w.workspace.mode,'sketch');self.assertIsNotNone(self.w.draft)

    def test_escape_cancels_feature_tools_from_any_focus(self):
        self.w.new_edge('fillet');self.app.processEvents()
        self.escape(self.w.widgets['radius']);self.assertIsNone(self.w.draft);self.assertEqual(self.w.workspace.mode,'model')
        self.w.start_extrude();self.escape();self.assertNotEqual(self.w.workspace.mode,'extrude');self.assertFalse(self.w.workspace.extrude_selecting)
