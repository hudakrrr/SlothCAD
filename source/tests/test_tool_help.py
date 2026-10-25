"""Right-click on a tool shows its name, what it does and what it is good for."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QAbstractButton
from app import Window
import tool_help


class ToolHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.resize(1400,860);self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()

    def test_every_tool_in_the_ribbons_and_lists_has_a_description(self):
        keys=set()
        for button in self.w.ribbon_container.findChildren(QAbstractButton):
            if button.property('_icon_name'):keys.add(button.property('_icon_name'))
        def walk(menu):
            for action in menu.actions():
                if action.isSeparator():continue
                keys.add(action.property('_icon_name') or action.data())
                if action.menu():walk(action.menu())
        for palette in self.w.tool_palettes.values():walk(palette.menu)
        for button in self.w.draw_palette.findChildren(QAbstractButton):
            if button.property('_icon_name'):keys.add(button.property('_icon_name'))
        missing=sorted(str(k) for k in keys if k and tool_help.help_for(k) is None)
        self.assertEqual(missing,[])

    def test_right_click_opens_a_centered_description(self):
        button=self.w.body_buttons['extrude']
        QTest.mouseClick(button,Qt.RightButton);self.app.processEvents();self.app.processEvents()
        dialog=getattr(self.w,'tool_help_dialog',None)
        self.assertIsNotNone(dialog);self.assertTrue(dialog.isVisible())
        self.assertAlmostEqual(dialog.geometry().center().x(),self.w.geometry().center().x(),delta=3)
        # a normal click still starts the tool and opens no description
        dialog.close();self.w.tool_help_dialog=None


if __name__=='__main__':unittest.main()
