import os,tempfile,unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QSize
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtGui import QIcon,QImage
from PySide6.QtTest import QTest
from app import Window
from ui_icons import icon,icon_colors
from icon_art import ICON_KEYS,svg_source
from themes import apply_theme
from solid_tools import SOLID_TOOLS,CONSTRUCTIONS
from body_tools import BODY_TOOLS
from constraints import LABELS


def alpha_sum(image):
    return sum(image.pixelColor(x,y).alpha() for y in range(image.height()) for x in range(image.width()))


class VectorIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def tearDown(self):apply_theme(self.app,'light')
    def test_every_glyph_renders_without_clipping_in_both_themes(self):
        for theme in ('light','dark'):
            apply_theme(self.app,theme)
            for name in ICON_KEYS:
                with self.subTest(theme=theme,name=name):
                    glyph=icon(name);self.assertFalse(glyph.isNull())
                    image=glyph.pixmap(QSize(32,32),2).toImage();self.assertGreater(alpha_sum(image),1000)
                    self.assertTrue(all(image.pixelColor(x,0).alpha()==image.pixelColor(x,63).alpha()==0 for x in range(64)))
                    self.assertTrue(all(image.pixelColor(0,y).alpha()==image.pixelColor(63,y).alpha()==0 for y in range(64)))
    def test_hidpi_and_fractional_scale_are_rendered_at_the_requested_resolution(self):
        for scale in (1.,1.25,1.5,2.,3.):
            pix=icon('spline').pixmap(QSize(24,24),scale)
            self.assertEqual(pix.width(),round(24*scale));self.assertAlmostEqual(pix.devicePixelRatio(),scale)
    def test_disabled_glyph_is_visible_but_dimmed(self):
        enabled=icon('line').pixmap(QSize(24,24),1,QIcon.Normal).toImage()
        disabled=icon('line').pixmap(QSize(24,24),1,QIcon.Disabled).toImage()
        self.assertGreater(alpha_sum(disabled),0);self.assertLess(alpha_sum(disabled),alpha_sum(enabled)*.7)
    def test_operations_have_specific_geometry_instead_of_unknown_placeholders(self):
        kinds=(*SOLID_TOOLS,*CONSTRUCTIONS,*BODY_TOOLS,*LABELS,'sketch_fillet','sketch_chamfer','offset_plane','angled_plane','midplane','three_point_plane')
        self.assertTrue(set(kinds)<=ICON_KEYS)
        sources=[svg_source(k,icon_colors()) for k in kinds]
        self.assertEqual(len(set(sources)),len(sources))


class ToolbarIconInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.temp.name);self.env.start()
        self.w=Window();self.w.change_theme('light');self.w.change_language('en');self.w.show();self.app.processEvents();self.errors=[];self.w.error=self.errors.append
    def tearDown(self):
        self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.temp.cleanup();self.assertEqual(self.errors,[])
    def click(self,b):
        if self.w.ribbon_scroll.isAncestorOf(b):self.w.ribbon_scroll.ensureWidgetVisible(b)
        self.app.processEvents();QTest.mouseClick(b,Qt.LeftButton);self.app.processEvents()
    def test_all_toolbar_and_submenu_icons_are_registered(self):
        buttons=[b for b in self.w.centralWidget().findChildren(QToolButton) if b.property('_icon_name')]
        self.assertGreater(len(buttons),40)
        for b in buttons:self.assertIn(b.property('_icon_name'),ICON_KEYS)
        for menu in (self.w.solid_menu,self.w.solid_modify_menu,self.w.body_menu,self.w.construction_menu,self.w.constraint_menu):
            for action in menu.actions():self.assertIn(action.property('_icon_name'),ICON_KEYS);self.assertFalse(action.icon().isNull())
    def test_measure_takes_one_click_while_a_solid_submenu_is_open(self):
        self.click(self.w.body_buttons['construct']);self.assertTrue(self.w.tool_palettes['construct'].isVisible())
        self.click(self.w.measure_button);self.assertTrue(self.w.workspace.measure_active);self.assertFalse(self.w.tool_palettes['construct'].isVisible())
    def test_repair_takes_one_click_while_a_submenu_is_open(self):
        self.assertFalse(self.w.inspect_buttons['repair'].isCheckable())
        self.click(self.w.body_buttons['construct'])
        with patch('body_ui.RecoveryDialog.exec',return_value=0) as execute:
            self.click(self.w.inspect_buttons['repair']);execute.assert_called_once()
        self.assertFalse(self.w.tool_palettes['construct'].isVisible())
    def test_measure_takes_one_click_while_draw_submenu_is_open(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.click(self.w.draw_menu_button);self.assertTrue(self.w.draw_palette.isVisible())
        self.click(self.w.measure_button);self.assertTrue(self.w.workspace.measure_active);self.assertFalse(self.w.draw_palette.isVisible())
    def test_submenus_close_when_their_toolbar_mode_is_hidden(self):
        self.click(self.w.body_buttons['construct']);self.w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        self.assertFalse(self.w.tool_palettes['construct'].isVisible())
        self.click(self.w.tool_buttons['constraint']);self.assertTrue(self.w.tool_palettes['constraint'].isVisible())
        self.w.cancel();self.app.processEvents();self.assertFalse(self.w.tool_palettes['constraint'].isVisible())
    def test_theme_switch_refreshes_inspect_and_sketch_icons_without_changing_tools(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.set_tool('line')
        repair=next(b for b in self.w.inspect_buttons.values() if b.property('_icon_name')=='repair')
        before=repair.icon().pixmap(24,24).toImage();self.w.change_theme('dark')
        self.assertNotEqual(before,repair.icon().pixmap(24,24).toImage());self.assertEqual(self.w.workspace.tool,'line')
        self.assertEqual(self.w.tool_buttons['fillet'].property('_icon_name'),'sketch_fillet')
        self.w.change_theme('light')
    def test_hungarian_camera_toolbar_resizes_to_show_the_complete_label(self):
        self.w.change_language('hu');self.app.processEvents()
        box=self.w.view_selector
        self.assertGreaterEqual(box.width(),box.sizeHint().width());self.assertEqual(box.currentData(),'Iso')
        self.assertGreaterEqual(self.w.viewport_tools.width(),self.w.viewport_tools.sizeHint().width())
        self.w.change_language('en')
    def test_narrow_ribbon_scrolls_instead_of_clipping_labels_or_hiding_tools(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.resize(1100,800);self.app.processEvents()
        self.assertEqual(self.w.width(),1100)
        self.assertGreater(self.w.ribbon_scroll.horizontalScrollBar().maximum(),0)
        self.assertTrue(self.w.measure_button.isVisible())
        for b in self.w.tool_buttons.values():self.assertGreaterEqual(b.width(),b.sizeHint().width())
        # Inspect tools scroll with the ribbon; the mode badge and Finish/Cancel stay fixed on the right.
        repair=self.w.inspect_buttons['repair']
        self.w.ribbon_scroll.ensureWidgetVisible(repair);self.app.processEvents();self.assertGreater(self.w.ribbon_scroll.horizontalScrollBar().value(),0)
        finish=self.w.sketch_actions['finish'];self.assertTrue(finish.isVisible());self.assertFalse(self.w.ribbon_scroll.isAncestorOf(finish))
        self.assertLessEqual(finish.mapTo(self.w,finish.rect().topRight()).x(),self.w.width())
        self.w.cancel();self.app.processEvents();self.assertFalse(finish.isVisible());self.assertTrue(self.w.body_mode_badge.isVisible())
