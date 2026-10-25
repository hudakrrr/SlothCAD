import os,unittest,copy
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QFrame
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt,QPointF,QPoint
from PySide6.QtGui import QImage,QPainter
from app import Window
from geometry import new_sketch,base_frame,entity,profile_regions
from workspace import Workspace

class DrawPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        with patch('app.load_language',return_value='en'):self.w=Window()
        self.w.show();self.w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
    def tearDown(self):self.w.draw_palette.dismiss();self.w.hide();self.w.deleteLater();self.app.processEvents()
    def open(self):QTest.mouseClick(self.w.draw_menu_button,Qt.LeftButton);self.app.processEvents();self.assertTrue(self.w.draw_palette.isVisible())
    def test_dropdown_is_a_child_widget_and_every_drawing_tool_click_works(self):
        palette=self.w.draw_palette;self.assertFalse(palette.isWindow());self.assertIs(palette.parentWidget(),self.w.centralWidget())
        for button in palette.buttons:
            source=button.property('_i18n_text');tool=button.property('_tool')
            if source in ('Regular polygon…','Text…') or tool in ('mirror','circular','rectangular'):continue
            self.open();palette.scroll.ensureWidgetVisible(button);self.app.processEvents();QTest.mouseClick(button,Qt.LeftButton);self.app.processEvents()
            self.assertFalse(palette.isVisible());self.assertEqual(self.w.workspace.tool,tool)
    def test_toggle_escape_and_outside_click_do_not_draw(self):
        palette=self.w.draw_palette;self.open();QTest.mouseClick(self.w.draw_menu_button,Qt.LeftButton);self.assertFalse(palette.isVisible())
        self.open();draft=self.w.draft;QTest.keyClick(palette.buttons[0],Qt.Key_Escape);self.app.processEvents();self.assertFalse(palette.isVisible());self.assertIs(self.w.draft,draft)
        self.w.set_tool('line');self.open();QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=self.w.workspace.rect().bottomRight()-QPoint(10,10))
        self.assertFalse(palette.isVisible());self.assertEqual(self.w.workspace.points,[])
    def test_keyboard_opens_and_activates_tool(self):
        self.w.draw_menu_button.setFocus();QTest.keyClick(self.w.draw_menu_button,Qt.Key_Space);self.app.processEvents();palette=self.w.draw_palette;self.assertTrue(palette.isVisible())
        button=next(b for b in palette.buttons if b.property('_tool')=='circle_3p');palette.scroll.ensureWidgetVisible(button);button.setFocus();QTest.keyClick(button,Qt.Key_Space)
        self.assertEqual(self.w.workspace.tool,'circle_3p');self.assertFalse(palette.isVisible())
    def test_polygon_text_and_pattern_buttons_dispatch_their_settings(self):
        palette=self.w.draw_palette
        def click(label):
            self.open();button=next(b for b in palette.buttons if b.property('_i18n_text')==label)
            palette.scroll.ensureWidgetVisible(button);self.app.processEvents();QTest.mouseClick(button,Qt.LeftButton)
            self.assertFalse(palette.isVisible())
        click('Polygon');self.w.widgets['polygon_sides'].setValue(7);self.assertEqual(self.w.workspace.polygon_sides,7)
        # The text tool no longer asks in dialogs: it waits for a text box, and the text and
        # format are set in the right-hand panel afterwards.
        with patch('app.QInputDialog.getText',side_effect=AssertionError('text tool must not open dialogs')):
            click('Text…');self.assertEqual(self.w.workspace.tool,'text');self.assertIsNone(self.w.text_draft)
        for label,kind in [('Mirror','mirror'),('Circular pattern','circular'),('Rectangular pattern','rectangular')]:
            click(label);self.assertEqual(self.w.workspace.tool,kind)

class ProfileTintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_selected_fill_excludes_holes_and_neighboring_regions(self):
        w=Workspace();w.resize(600,400);w.aligned=np.eye(3);w.span=50
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=40,height=30),entity('rectangle',center=[0,0],width=10,height=6)]
        for a,b in [([-15,-15],[-15,-9]),([-15,-9],[-8,-7]),([-8,-7],[-2,-15])]:s['entities'].append(entity('line',a=a,b=b))
        w.set_scene(None,[(s,s['frame'])]);w.aligned=np.eye(3);w.set_mode('extrude');w.aligned=np.eye(3)
        profiles=profile_regions(s);outer=next(p for p in profiles if p['holes'])
        def render(target=None):
            image=QImage(600,400,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent);p=QPainter(image);w.paint_overlays(p,target);p.end();return image
        baseline=render();w.set_extrusion_selection([dict(type='sketch',sketch=s['id'],entities=outer['entities'])]);selected=render()
        def color(image,point):
            x,y=w.project_local([point],s['frame'])[0];return image.pixelColor(round(x),round(y))
        self.assertNotEqual(color(baseline,[10,8]),color(selected,[10,8]))
        for point in ([0,0],[-10,-11],[22,0]):self.assertEqual(color(baseline,point),color(selected,point))
        w.set_extrusion_selection([]);self.assertEqual(color(baseline,[10,8]),color(render(),[10,8]))
        hovered=render(dict(type='sketch',sketch=s['id'],entities=outer['entities']))
        self.assertNotEqual(color(baseline,[10,8]),color(hovered,[10,8]))
        for point in ([0,0],[-10,-11]):self.assertEqual(color(baseline,point),color(hovered,point))
        w.deleteLater();self.app.processEvents()
