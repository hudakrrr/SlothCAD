import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QToolBar
from app import Window

class TopBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Window();self.w.show();self.app.processEvents()
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_commands_live_in_menus_and_history_has_only_undo_redo_buttons(self):
        self.assertEqual(self.w.findChildren(QToolBar),[])
        self.assertIsNone(self.w.menuBar().cornerWidget(Qt.TopRightCorner))
        file_menu=next(a.menu() for a in self.w.menuBar().actions() if a.text()=='File')
        # The QMenu must remain alive independently of temporary QAction wrappers.
        self.app.processEvents()
        file_names=[a.text() for a in file_menu.actions() if not a.isSeparator()]
        for expected in ('New','Open','Save','Save as','Import…','Export…','Example part'):
            self.assertIn(expected,file_names)
        edit_menu=next(a.menu() for a in self.w.menuBar().actions() if a.text()=='Edit')
        self.assertEqual([a.text() for a in edit_menu.actions() if not a.isSeparator()],['Undo','Redo','Copy feature (with what it needs)','Paste feature into this project','Parameters…'])
        self.assertFalse(self.w.undo_action.shortcut().isEmpty());self.assertFalse(self.w.redo_action.shortcut().isEmpty())
        self.assertEqual(self.w.undo_button.defaultAction(),self.w.undo_action);self.assertEqual(self.w.redo_button.defaultAction(),self.w.redo_action)
        self.assertTrue(self.w.undo_button.isVisible());self.assertTrue(self.w.redo_button.isVisible())
    def test_measure_uses_same_ribbon_button_geometry_as_other_tools(self):
        solid=self.w.body_buttons['sketch'];measure=self.w.measure_button
        self.assertEqual(measure.toolButtonStyle(),solid.toolButtonStyle())
        self.assertEqual(measure.minimumHeight(),solid.minimumHeight())
        self.assertLessEqual(abs(measure.mapTo(self.w,measure.rect().topLeft()).y()-solid.mapTo(self.w,solid.rect().topLeft()).y()),1)
        self.assertEqual(measure.property('_i18n_text'),'Measure')
    def test_tools_are_grouped_by_task_and_inspect_is_at_far_right(self):
        self.assertEqual(set(self.w.body_buttons),{'sketch','extrude','solid_tools','body_patterns','fillet','chamfer','solid_modify','body_tools','construct'})
        x=lambda key:self.w.body_buttons[key].mapTo(self.w.body_bar,self.w.body_buttons[key].rect().center()).x()
        self.assertLess(x('sketch'),x('fillet'))
        self.assertLess(x('fillet'),x('construct'))
        self.assertGreater(self.w.measure_button.mapTo(self.w, self.w.measure_button.rect().topRight()).x(),self.w.body_buttons['construct'].mapTo(self.w,self.w.body_buttons['construct'].rect().topRight()).x())
    def test_step_and_stl_exports_use_separate_filters_and_extensions(self):
        import kernel_process
        with patch('app.QFileDialog.getSaveFileName',side_effect=[('part','STEP solid (*.step *.stp)'),('part','STL mesh (*.stl)')]) as dialog, patch.object(kernel_process.KERNEL,'call') as export, patch.object(self.w.doc,'export_items',return_value=[]):
            self.w.export_step();self.w.export_stl()
        self.assertEqual(dialog.call_count,2)
        # The file is written by the background kernel process, never on the interface thread.
        self.assertEqual([call.args[0] for call in export.call_args_list],['export','export'])
        self.assertEqual([call.args[1]['path'] for call in export.call_args_list],['part.step','part.stl'])
        self.assertIn('STEP solid',dialog.call_args_list[0].args[-1]);self.assertIn('STL mesh',dialog.call_args_list[1].args[-1])
    def test_warning_is_hidden_until_issue_then_opens_details(self):
        self.assertFalse(self.w.graphics_warning.isVisible())
        self.w.workspace.gpu_error='OpenGL float uniform error: 0x0502'
        self.w.workspace.graphics_issue.emit()
        self.assertTrue(self.w.graphics_warning.isVisible())
        self.assertGreater(self.w.graphics_warning.x(),self.w.workspace.width()/2)
        with patch('app.QMessageBox.exec') as execute:
            self.w.graphics_warning.click();execute.assert_called_once()
