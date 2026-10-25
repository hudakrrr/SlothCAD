import copy,os,tempfile,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app import Window
from model import Document
from geometry import identifier,entity
from face_tools import FACE_TOOLS
from advanced_ui import ADVANCED_TOOLS
from surface_tools import bodies
from assemblies import assembled_features
from tests.test_workflow_audit import base

class RoadmapUITests(unittest.TestCase):
    def test_spatial_point_has_a_visible_marker(self):
        from PySide6.QtGui import QImage,QPainter
        import numpy as np
        image=QImage(30,30,QImage.Format_ARGB32);image.fill(Qt.transparent);painter=QPainter(image)
        self.w.workspace.draw_polyline(painter,np.asarray([[15,15]]),'#8d68ac',2);painter.end()
        self.assertGreater(sum(image.pixelColor(x,y).alpha() for x in range(10,21) for y in range(10,21)),0)
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,SLOTHCAD_RECOVERY_DIR=self.tmp.name);self.env.start();self.w=Window();self.errors=[];self.w.error=lambda error:self.errors.append(str(error));self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.draft=None;self.w.saved_features=copy.deepcopy(self.w.doc.features);self.w.saved_display=copy.deepcopy(self.w.doc.display);self.w.autosave.cleanup();self.w.hide();self.w.deleteLater();self.app.processEvents();self.env.stop();self.tmp.cleanup();self.assertEqual(self.errors,[])
    def test_every_extended_editor_opens_and_has_parameters(self):
        self.w.doc=Document(base());self.w.refresh();self.w.abandon=lambda:True
        for kind in ADVANCED_TOOLS:
            with self.subTest(kind=kind):
                self.w.start_advanced_tool(kind);self.assertEqual(self.w.draft['kind'],kind);self.assertIn('name',self.w.widgets)
                self.w.draft=None;self.w.workspace.set_mode('model')
        for kind in ('component','joint'):
            self.w.start_assembly(kind);self.assertEqual(self.w.draft['kind'],kind);self.assertIn('name',self.w.widgets);self.w.draft=None
        for kind in ('sketch3d','surface_sketch'):
            self.w.start_spatial(kind);self.assertEqual(self.w.draft['kind'],kind);self.assertIn('spatial_entities',self.w.widgets);self.w.draft=None
    def test_nested_surface_and_assembly_palettes_are_clickable(self):
        self.w.abandon=lambda:True
        for submenu,kind in [(self.w.surface_menu,'surface_patch'),(self.w.assembly_menu,'component')]:
            palette=self.w.tool_palettes['solid_tools'];palette.toggle();self.app.processEvents();button=next(b for b in palette.buttons if b.property('_action').menu() is submenu);QTest.mouseClick(button,Qt.LeftButton);self.assertTrue(palette.isVisible());self.assertTrue(palette.back.isVisible())
            button=next(b for b in palette.buttons if b.property('_action').data()==kind);palette.scroll.ensureWidgetVisible(button);self.app.processEvents();QTest.mouseClick(button,Qt.LeftButton);self.assertFalse(palette.isVisible());self.assertEqual(self.w.draft['kind'],kind);self.w.draft=None;self.w.workspace.set_mode('model')
    def test_component_edit_save_autosave_and_return_preserve_parent(self):
        child=dict(kind='component',id=identifier(),name='Part',features=base(),pose=dict(origin=[10,0,0],axis=[0,0,1],angle=0))
        self.w.doc=Document([child]);self.w.refresh();self.w.open_component(0);self.assertEqual(len(self.w.component_stack),1)
        edited=copy.deepcopy(self.w.doc.features);edited[1]['depth']=8;self.w.doc.commit(edited);self.assertTrue(self.w.dirty())
        data=self.w.autosave.snapshot();self.assertEqual(data['component_path'],[0]);self.assertEqual(data['features'][0]['features'][1]['depth'],8)
        self.w.close_component();self.assertEqual(len(self.w.component_stack),0);self.assertEqual(self.w.doc.features[0]['features'][1]['depth'],8)
        self.w.restore_autosave(data);self.assertEqual(len(self.w.component_stack),1);self.assertEqual(self.w.doc.features[1]['depth'],8)
        self.w.save_assembly(os.path.join(self.tmp.name,'assembly.fcad'));loaded=Document.load(os.path.join(self.tmp.name,'assembly.fcad'));self.assertEqual(loaded.features[0]['features'][1]['depth'],8)
        self.w.close_component();self.assertFalse(self.w.dirty())
    def test_spatial_sketch_coordinates_render_apply_and_path_choices(self):
        self.w.start_spatial('sketch3d');self.w.add_spatial_point([0,0,0]);self.w.add_spatial_point([10,5,3]);self.assertEqual(len(self.w.draft['entities']),1);self.w.apply_feature();self.assertIsNone(self.w.draft);self.assertEqual(len(self.w.workspace.spatial_scenes),1);self.w.tool_context();self.assertTrue(self.w.path_choices)
    def test_spatial_draft_undo_redo_and_autosave_pending_spline(self):
        self.w.start_spatial('sketch3d');self.w.add_spatial_point([0,0,0]);self.w.add_spatial_point([10,5,3]);self.w.undo();self.assertFalse(self.w.draft['entities']);self.w.redo();self.assertEqual(len(self.w.draft['entities']),1)
        self.w.change_spatial_kind('spline');self.w.add_spatial_point([0,0,0]);self.w.add_spatial_point([4,5,2]);self.w.add_spatial_point([8,7,5]);data=self.w.autosave.snapshot();self.w.draft=None;self.w.restore_autosave(data);self.assertEqual(len(self.w.spatial_points),3);self.w.finish_spatial_curve();self.assertEqual(len(self.w.draft['entities']),2);self.w.undo();self.assertEqual(len(self.w.draft['entities']),1);self.assertEqual(len(self.w.spatial_points),3)
    def test_projection_ui_works_and_break_link_keeps_geometry(self):
        self.w.support_picked(dict(type='plane',plane='XY'));self.w.add_entity(entity('rectangle',center=[0,0],width=10,height=5));self.w.finish_sketch()
        self.w.support_picked(dict(type='plane',plane='XY'));self.w.start_projection();self.w.widgets['projection_source'].setCurrentIndex(1);listing=self.w.widgets['projection_entities'];listing.item(0).setSelected(True);self.w.apply_projection();self.assertEqual(len(self.w.draft['entities']),4);self.w.break_projection();self.assertEqual(len(self.w.draft['entities']),4);self.assertFalse(self.w.draft['projections'])

if __name__=='__main__':unittest.main()
