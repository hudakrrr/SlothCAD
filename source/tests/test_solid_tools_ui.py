import os,unittest,copy
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from app import Window
from geometry import entity,profile_regions,face_reference,base_frame,new_sketch
from solid_tools import face_ref

class SolidToolsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        import app as _a;_old=_a.DEFAULT_EXTRUDE_DEPTH;_a.DEFAULT_EXTRUDE_DEPTH=10.;self.addCleanup(setattr,_a,'DEFAULT_EXTRUDE_DEPTH',_old);self.w=Window();self.errors=[];self.w.error=self.errors.append;self.w.show();self.app.processEvents()
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.assertEqual(self.errors,[])
    def base(self):
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=20));self.w.finish_sketch();self.w.start_extrude()
        s=self.w.doc.features[0];r=profile_regions(s)[0];self.w.extrusion_picked(dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes']));self.w.widgets['depth'].setValue(20);self.w.draft['operation']='add';self.w.apply_feature();self.app.processEvents()
    def test_construct_menu_preview_apply_visibility_and_sketch_support(self):
        self.w.construction_menu.actions()[0].trigger();self.assertEqual(self.w.draft['kind'],'construction_plane')
        self.w.widgets['offset'].setValue(12);self.w.preview_feature();self.assertEqual(len(self.w.doc.features),0)
        self.assertEqual(self.w.workspace.construction_items[0][2]['origin'][2],12)
        self.w.apply_feature();id_=self.w.doc.features[0]['id'];self.assertEqual(self.w.doc.frames[id_]['origin'][2],12)
        self.w.workspace.fit();self.assertAlmostEqual(self.w.workspace.center[2],12)
        item=self.w.objects.topLevelItem(2).child(0);item.setCheckState(0,Qt.Unchecked);self.assertEqual(self.w.workspace.construction_items,[])
        item.setCheckState(0,Qt.Checked);self.assertEqual(len(self.w.workspace.construction_items),1)
        self.w.object_edit(item,0);self.assertEqual(self.w.workspace.mode,'sketch');self.assertEqual(self.w.draft['plane_ref']['id'],id_)
        self.w.add_entity(entity('circle',center=[0,0],radius=2));self.w.finish_sketch();self.assertEqual(self.w.doc.frames[self.w.doc.features[1]['id']]['origin'][2],12)
    def test_hole_menu_face_pick_preview_and_apply(self):
        self.base();action=next(a for a in self.w.solid_menu.actions() if a.data()=='hole');action.trigger()
        box=self.w.widgets['hole_type'];box.setCurrentIndex(box.findData('counterbore'));self.w.widgets['diameter'].setValue(4)
        self.w.widgets['head_diameter'].setValue(8);self.w.widgets['head_depth'].setValue(3)
        top=next(i for i,f in enumerate(self.w.workspace.faces) if f.geomType()=='PLANE' and f.normalAt().z>.9)
        self.w.enable_face_pick('plane');self.w.pick_solid_face(top);self.assertFalse(self.w.workspace.solid_face_picking)
        count=len(self.w.doc.features);volume=self.w.doc.solid.val().Volume();self.w.preview_feature()
        self.assertEqual(len(self.w.doc.features),count);self.assertEqual(self.w.doc.solid.val().Volume(),volume)
        self.w.apply_feature();self.assertLess(self.w.doc.solid.val().Volume(),volume);self.assertEqual(self.w.doc.features[-1]['hole_type'],'counterbore')
    def test_shell_arrow_is_capped_at_a_wall_thickness_that_can_be_built(self):
        self.base();self.w.start_solid_tool('shell')
        top=next(i for i,f in enumerate(self.w.workspace.faces) if f.normalAt().z>.9)
        self.w.enable_face_pick();self.w.pick_solid_face(top);self.app.processEvents()
        g=self.w.workspace.gizmo;self.assertIsNotNone(g.state)
        lo,hi=g.state['limits']
        self.assertIsNotNone(hi);self.assertLess(hi,10.0)        # a 20 mm box cannot have walls of 10 mm or more
        self.assertGreater(hi,1.0)
        g.axis=0;g.set_value(999.);self.app.processEvents()
        self.assertLessEqual(abs(self.w.draft['thickness']),hi+1e-9)
        self.w.apply_feature();self.assertEqual(self.w.doc.features[-1]['kind'],'shell')   # builds without any error dialog
    def test_shell_face_multi_selection_and_draft_editor(self):
        self.base();self.w.start_solid_tool('shell');self.assertIn('solid_faces',self.w.widgets)
        top=next(i for i,f in enumerate(self.w.workspace.faces) if f.normalAt().z>.9)
        self.w.enable_face_pick();self.w.pick_solid_face(top);self.assertEqual(len(self.w.draft['faces']),1)
        self.w.apply_feature();self.assertEqual(self.w.doc.features[-1]['kind'],'shell');self.w.undo()
        self.w.start_solid_tool('draft');listing=self.w.widgets['solid_faces']
        faces=self.w.doc.solid.val().Solids()[0].Faces()
        for i,face in enumerate(faces):
            if abs(face.normalAt().z)<.1:listing.item(i).setSelected(True)
        self.assertEqual(len(self.w.draft['faces']),4);self.w.apply_feature();self.assertEqual(self.w.doc.features[-1]['kind'],'draft')
    def test_extrude_extent_target_and_taper_controls(self):
        self.w.start_solid_tool('construction_plane','offset');self.w.widgets['offset'].setValue(15);self.w.apply_feature();target=self.w.doc.features[0]
        self.w.support_picked({'type':'plane','plane':'XY'});self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=20));self.w.finish_sketch();s=self.w.doc.features[-1]
        self.w.start_extrude();r=profile_regions(s)[0];self.w.extrusion_picked(dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes']))
        box=self.w.widgets['extent'];box.setCurrentIndex(box.findData('to object'));targetbox=self.w.widgets['target']
        index=next(i for i in range(targetbox.count()) if targetbox.itemData(i)==dict(type='construction',id=target['id']));targetbox.setCurrentIndex(index)
        self.w.widgets['taper'].setValue(2);self.w.draft['operation']='add';self.w.apply_feature()
        self.assertAlmostEqual(self.w.doc.solid.val().BoundingBox().zmax,15,places=6);self.assertEqual(self.w.doc.features[-1]['taper'],2)
    def test_revolve_sweep_loft_editors_and_three_point_picking(self):
        self.base()
        for kind in ('revolve','sweep','loft'):
            self.w.start_solid_tool(kind);self.assertEqual(self.w.draft['kind'],kind)
            self.assertIn('source' if kind!='loft' else 'loft_profile',self.w.widgets);self.w.cancel()
        self.w.start_solid_tool('construction_plane','three points');self.w.enable_point_pick('p1');self.w.pick_construction_point([1,2,3])
        self.assertEqual(self.w.draft['p1'],[1,2,3]);self.assertTrue(self.w.workspace.construction_point_picking)   # carries on with the next point
        self.assertEqual(self.w.construction_pick_key,('p2',None))
        self.w.draft['p2']=[11,2,3];self.w.draft['p3']=[1,12,3];self.w.apply_feature();self.assertEqual(self.w.doc.frames[self.w.doc.features[-1]['id']]['origin'],[1,2,3])
