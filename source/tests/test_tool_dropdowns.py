import os,unittest,tempfile
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from app import Window
from geometry import entity

class ToolDropdownTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.temp.name);self.env.start()
  self.w=Window();self.w.show();self.app.processEvents();self.errors=[];self.w.error=self.errors.append
 def tearDown(self):
  self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup();self.assertEqual(self.errors,[])
 def button(self,key):return (self.w.tool_buttons if key=='constraint' else self.w.body_buttons)[key]
 def open(self,key):
  self.w.ribbon_scroll.ensureWidgetVisible(self.button(key));self.app.processEvents();QTest.mouseClick(self.button(key),Qt.LeftButton);self.app.processEvents();p=self.w.tool_palettes[key]
  self.assertTrue(p.isVisible());self.assertFalse(p.isWindow());self.assertIsNone(self.button(key).menu());return p
 def test_all_three_solid_dropdowns_open_with_real_clicks_and_switch(self):
  for key in ('solid_tools','solid_modify','construct','body_patterns','body_tools'):
   p=self.open(key);self.assertTrue(p.buttons)
   self.assertEqual(sum(p.isVisible() for p in self.w.tool_palettes.values()),1)
  QTest.mouseClick(self.button('body_tools'),Qt.LeftButton);self.assertFalse(self.w.tool_palettes['body_tools'].isVisible())
 def test_construct_click_activates_offset_plane(self):
  p=self.open('construct');QTest.mouseClick(p.buttons[0],Qt.LeftButton);self.assertFalse(p.isVisible());self.assertEqual(self.w.draft['kind'],'construction_plane');self.assertEqual(self.w.draft['mode'],'offset')
 def test_task_group_menus_separate_creation_from_modification(self):
  self.assertIn('hole',[a.data() for a in self.w.solid_menu.actions()])
  self.assertIn('shell',[a.data() for a in self.w.solid_modify_menu.actions()])
  self.assertNotIn('shell',[a.data() for a in self.w.solid_menu.actions()])
  p=self.open('body_patterns');self.assertEqual({a.data() for a in self.w.body_pattern_menu.actions()},{'body_mirror','body_rectangular','body_circular','feature_rectangular','feature_circular','feature_mirror','path_pattern'})
  self.assertTrue(p.buttons)
 def test_ribbon_keyboard_opens_dropdown_without_a_native_menu(self):
  b=self.button('solid_tools');b.setFocus();QTest.keyClick(b,Qt.Key_Space);self.app.processEvents();self.assertTrue(self.w.tool_palettes['solid_tools'].isVisible())
  QTest.keyClick(self.w.tool_palettes['solid_tools'].buttons[0],Qt.Key_Escape);self.assertFalse(self.w.tool_palettes['solid_tools'].isVisible())
 def test_dropdown_arrow_area_opens_and_closes(self):
  b=self.button('construct');pos=QPoint(b.width()-10,b.height()-8)
  QTest.mouseClick(b,Qt.LeftButton,pos=pos);self.assertTrue(self.w.tool_palettes['construct'].isVisible())
  QTest.mouseClick(b,Qt.LeftButton,pos=pos);self.assertFalse(self.w.tool_palettes['construct'].isVisible())
 def test_body_menu_click_activates_move_copy(self):
  from model import Document
  from tests.test_workflow_audit import base
  self.w.doc=Document(base());self.w.refresh()
  p=self.open('body_tools');QTest.mouseClick(p.buttons[0],Qt.LeftButton);self.assertFalse(p.isVisible());self.assertEqual(self.w.draft['kind'],'body_move');self.assertIn('targets',self.w.widgets)
 def test_solid_menu_click_dispatches_every_action(self):
  from special_solids import SPECIAL_TOOLS
  for i,action in enumerate(self.w.solid_menu.actions()):
   if action.menu():continue  # Nested pages are exercised by test_roadmap_ui.
   method='start_advanced_tool' if action.data() in SPECIAL_TOOLS else 'start_solid_tool'
   with patch.object(self.w,method) as start:
    p=self.open('solid_tools');p.scroll.ensureWidgetVisible(p.buttons[i]);self.app.processEvents();QTest.mouseClick(p.buttons[i],Qt.LeftButton);start.assert_called_once_with(action.data());self.assertFalse(p.isVisible())
 def test_all_remaining_solid_and_body_rows_dispatch_the_matching_command(self):
  for key,menu,method in [('solid_modify',self.w.solid_modify_menu,'start_solid_tool'),('body_tools',self.w.body_modify_menu,'start_body_tool'),('body_patterns',self.w.body_pattern_menu,'start_body_tool')]:
   from advanced_ui import ADVANCED_TOOLS
   for i,action in enumerate(menu.actions()):
    dispatch='start_advanced_tool' if action.data() in ADVANCED_TOOLS else method
    with self.subTest(key=key,action=action.data()),patch.object(self.w,dispatch) as start:
     p=self.open(key);p.scroll.ensureWidgetVisible(p.buttons[i]);self.app.processEvents();QTest.mouseClick(p.buttons[i],Qt.LeftButton);start.assert_called_once_with(action.data());self.assertFalse(p.isVisible())
 def test_every_construction_row_dispatches_the_plane_or_axis_mode(self):
  expected=[('construction_plane','offset'),('construction_plane','angled'),('construction_plane','midplane'),('construction_plane','three points'),('construction_axis','two points')]
  for i,args in enumerate(expected):
   with self.subTest(args=args),patch.object(self.w,'start_solid_tool') as start:
    p=self.open('construct');QTest.mouseClick(p.buttons[i],Qt.LeftButton);start.assert_called_once_with(*args);self.assertFalse(p.isVisible())
 def test_every_constraint_row_dispatches_the_matching_relation(self):
  self.w.support_picked({'type':'plane','plane':'XY'})
  for i,action in enumerate(self.w.constraint_menu.actions()):
   with self.subTest(kind=action.data()),patch.object(self.w,'start_constraint') as start:
    p=self.open('constraint');p.scroll.ensureWidgetVisible(p.buttons[i]);self.app.processEvents();QTest.mouseClick(p.buttons[i],Qt.LeftButton);start.assert_called_once_with(action.data());self.assertFalse(p.isVisible())
 def test_constraints_click_and_keyboard_activation(self):
  self.w.support_picked({'type':'plane','plane':'XY'});self.w.add_entity(entity('line',a=[0,0],b=[10,0]))
  p=self.open('constraint');index=next(i for i,a in enumerate(self.w.constraint_menu.actions()) if a.data()=='horizontal')
  p.buttons[index].setFocus();QTest.keyClick(p.buttons[index],Qt.Key_Space);self.assertFalse(p.isVisible());self.assertEqual(self.w.constraint_kind,'horizontal');self.assertEqual(self.w.workspace.tool,'constraint')
 def test_escape_and_outside_click_close_without_editing(self):
  p=self.open('construct');QTest.keyClick(p.buttons[0],Qt.Key_Escape);self.assertFalse(p.isVisible());self.assertIsNone(self.w.draft)
  p=self.open('construct');QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=QPoint(30,200));self.assertFalse(p.isVisible());self.assertIsNone(self.w.draft)
 def test_language_switch_preserves_actions_and_translates_rows(self):
  menu=self.w.construction_menu;self.w.change_language('hu');p=self.open('construct');self.assertIs(self.w.construction_menu,menu)
  self.assertEqual(p.buttons[0].text(),'Eltolt sík');QTest.mouseClick(p.buttons[0],Qt.LeftButton);self.assertEqual(self.w.draft['mode'],'offset');self.w.change_language('en')
 def test_switching_between_draw_and_constraints_takes_one_click(self):
  self.w.support_picked({'type':'plane','plane':'XY'});QTest.mouseClick(self.w.draw_menu_button,Qt.LeftButton);self.assertTrue(self.w.draw_palette.isVisible())
  p=self.open('constraint');self.assertFalse(self.w.draw_palette.isVisible())
  # Opening Constraints scrolled the (wide) ribbon; click the part of the Draw tools bar that is on screen.
  self.w.ribbon_scroll.horizontalScrollBar().setValue(0);self.app.processEvents()
  QTest.mouseClick(self.w.draw_menu_button,Qt.LeftButton);self.assertFalse(p.isVisible());self.assertTrue(self.w.draw_palette.isVisible())
