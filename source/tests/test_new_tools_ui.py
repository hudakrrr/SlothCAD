import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QSettings,QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Window
from themes import load_theme
from i18n import load_language
from geometry import base_frame,entity

class NewToolsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings_dir=tempfile.TemporaryDirectory(dir=Path.cwd())
        QSettings.setPath(QSettings.NativeFormat,QSettings.UserScope,cls.settings_dir.name)
        cls.app=QApplication.instance() or QApplication([])
    @classmethod
    def tearDownClass(cls):cls.settings_dir.cleanup()
    def setUp(self):
        import app as _a;_old=_a.DEFAULT_EXTRUDE_DEPTH;_a.DEFAULT_EXTRUDE_DEPTH=10.;self.addCleanup(setattr,_a,'DEFAULT_EXTRUDE_DEPTH',_old);self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.change_theme('light');self.w.change_language('en');self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def sketch(self):self.w.support_picked({'type':'plane','plane':'XY'})
    def click(self,point):
        screen=self.w.workspace.project_local([point],self.w.workspace.active_frame)[0]
        QTest.mouseClick(self.w.workspace,Qt.LeftButton,pos=QPointF(*screen).toPoint());self.app.processEvents()
    def test_dark_theme_persists_for_new_windows_and_invalidates_render_cache(self):
        self.w.workspace.prepare_planes();cached=self.w.workspace.plane_cache_key
        self.w.change_theme('dark');self.assertEqual(load_theme(),'dark');self.assertEqual(self.w.workspace.theme,'dark')
        self.w.workspace.prepare_planes();self.assertNotEqual(self.w.workspace.plane_cache_key,cached)
        other=Window();self.assertEqual(other.theme,'dark');self.assertEqual(other.workspace.theme,'dark');other.deleteLater();self.app.processEvents()
    def test_language_setting_persists_and_retranslates_ui(self):
        self.w.change_language('hu');self.app.processEvents()
        self.assertEqual(load_language(),'hu');self.assertEqual(self.w.file_menu.title(),'Fájl');self.assertEqual(self.w.settings_menu.title(),'Beállítások');self.assertEqual(self.w.language_menu.title(),'Nyelv')
        self.assertEqual(self.w.body_buttons['sketch'].text(),'Vázlat létrehozása')
        other=Window();self.assertEqual(other.language,'hu');self.assertEqual(other.file_menu.title(),'Fájl');other.close();other.deleteLater();self.app.processEvents()
        self.w.change_language('en')
    def test_mirror_select_sources_then_click_axis_apply_and_undo(self):
        self.sketch();self.w.add_entity(entity('line',a=[0,-15],b=[0,15]));self.w.add_entity(entity('circle',center=[8,0],radius=2))
        self.w.start_pattern('mirror');self.click([10,0]);self.assertEqual(self.w.workspace.pattern_selection,{1})
        self.w.choose_pattern_stage('axis');self.click([0,8]);self.assertEqual(self.w.pattern_axis,0)
        self.w.apply_pattern();self.assertEqual(len(self.w.draft['entities']),3);self.assertAlmostEqual(self.w.draft['entities'][-1]['center'][0],-8)
        self.w.undo();self.assertEqual(len(self.w.draft['entities']),2);self.w.redo();self.assertEqual(len(self.w.draft['entities']),3)
    def test_circular_multi_selection_point_and_copy_count(self):
        self.sketch();self.w.add_entity(entity('circle',center=[10,0],radius=1));self.w.add_entity(entity('line',a=[9,-2],b=[11,-2]))
        self.w.start_pattern('circular');self.click([11,0]);self.click([10,-2]);self.assertEqual(self.w.workspace.pattern_selection,{0,1})
        self.w.choose_pattern_stage('center');self.click([0.2,0.2]);self.assertEqual(self.w.pattern_center,[0,0])
        self.w.widgets['copies'].setValue(3);self.w.apply_pattern();self.assertEqual(len(self.w.draft['entities']),8)
        self.w.undo();self.assertEqual(len(self.w.draft['entities']),2)
    def test_fillet_and_chamfer_open_edge_editor(self):
        self.sketch();self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=12));self.w.finish_sketch();self.w.start_extrude()
        source=self.w.doc.features[0];self.w.extrusion_picked({'type':'sketch','sketch':source['id'],'entities':[source['entities'][0]['id']]});self.w.apply_feature()
        for kind in ('fillet','chamfer'):
            self.w.new_edge(kind);self.assertEqual(self.w.workspace.mode,'edge');self.assertEqual(self.w.draft['kind'],kind)
            self.assertIn('radius',self.w.widgets);self.assertEqual(self.w.body_mode_label.text(),'SELECT EDGES');self.w.cancel()

    def test_negative_ui_depth_auto_switches_cut_and_back_to_add(self):
        feature=dict(depth=10.,operation='add');self.w.set_extrusion_depth(feature,-5)
        self.assertEqual(feature['operation'],'cut');self.assertTrue(feature['signed_depth'])
        self.w.set_extrusion_depth(feature,5);self.assertEqual(feature['operation'],'add')
    def test_draw_caption_menu_contains_extended_sketch_tools(self):
        labels=[button.text() for button in self.w.draw_palette.buttons]
        for expected in ['Line','Center rectangle','3-point circle','Center arc','Polygon','Ellipse','Center-to-center slot','Control-point spline','Conic curve','Point','Text…','Mirror','Circular pattern','Rectangular pattern']:
            self.assertIn(expected,labels)
    def test_rectangular_pattern_creates_grid_copies(self):
        self.sketch();self.w.add_entity(entity('circle',center=[0,0],radius=1));self.w.start_pattern('rectangular');self.click([1,0])
        self.w.pattern_columns=3;self.w.pattern_rows=2;self.w.pattern_spacing_x=10;self.w.pattern_spacing_y=20;self.w.apply_pattern()
        self.assertEqual(len(self.w.draft['entities']),6)
