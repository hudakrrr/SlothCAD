import copy
import math
import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window
from model import Document, new_feature, edge_reference
from geometry import new_sketch, base_frame, entity, profile_regions
from expression_spin import ExpressionSpinBox
from i18n import set_language


def sketch_and_extrude():
    sketch=new_sketch(base_frame('XY'),'Outline')
    sketch['entities']=[entity('rectangle',center=[0,0],width=40,height=30),entity('circle',center=[0,0],radius=5)]
    region=max(profile_regions(sketch),key=lambda r:len(r['holes']))
    extrude=dict(kind='extrude',id='e0000001',name='Extrude',enabled=True,depth=10.,operation='add',signed_depth=False,
                 sources=[dict(type='sketch',sketch=sketch['id'],entities=region['entities'],holes=region['holes'],profile_mode='nested')])
    return sketch,extrude


class FeatureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.resize(1000,800);self.w.show();self.app.processEvents()

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def load(self,features,**kwargs):
        self.w.doc=Document(features,**kwargs);self.w.refresh(True);self.app.processEvents()

    def test_extrude_two_sides_and_thin_wall_through_the_editor(self):
        sketch,extrude=sketch_and_extrude();self.load([sketch,extrude])
        self.w.select(1);self.app.processEvents()
        self.assertNotIn('depth2',self.w.widgets)
        self.w.change_extrusion_direction('two sides');self.app.processEvents()
        box=self.w.widgets['depth2'];self.assertIsInstance(box,ExpressionSpinBox)
        box.setValue(4.);self.app.processEvents()
        self.assertEqual(self.w.draft['depth2'],4.)
        self.w.apply_feature();self.app.processEvents()
        area=40*30-math.pi*25
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),area*14,places=2)
        # thin wall
        self.w.select(1);self.app.processEvents()
        self.w.widgets['thin_toggle'].setChecked(True);self.app.processEvents()
        self.assertEqual(self.w.draft['thin'],2.0);self.assertIn('thin',self.w.widgets);self.assertIn('thin_side',self.w.widgets)
        side=self.w.widgets['thin_side'];side.setCurrentIndex(side.findData('outside'));self.app.processEvents()
        self.assertEqual(self.w.draft['thin_side'],'outside')
        self.w.apply_feature();self.app.processEvents()
        outside=((44*34-40*30)+math.pi*(25-9))*14
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),outside,places=2)
        # switching it off again restores the full profile
        self.w.select(1);self.app.processEvents();self.w.widgets['thin_toggle'].setChecked(False);self.app.processEvents()
        self.assertNotIn('thin',self.w.draft);self.w.apply_feature()
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),area*14,places=2)

    def test_chamfer_modes_show_the_matching_fields(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        base=Document([plate])
        edge=next(e for e in base.solid.val().Edges() if abs(e.Center().z-10)<1e-6)
        chamfer=dict(kind='chamfer',id='c0000001',name='Chamfer',enabled=True,radius=2.,edges='vertical',edge_refs=[edge_reference(edge,base.solid)],auto_fit=True)
        self.load([plate,chamfer]);self.w.select(1);self.app.processEvents()
        self.assertNotIn('distance2',self.w.widgets)
        self.w.change_edge_mode('two_distance');self.app.processEvents()
        self.assertIn('distance2',self.w.widgets);self.assertIn('flip',self.w.widgets)
        self.w.widgets['distance2'].setValue(4.);self.app.processEvents()
        self.w.apply_feature();self.app.processEvents()
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),12000-.5*2*4*40,places=3)
        self.w.select(1);self.w.change_edge_mode('distance_angle');self.app.processEvents()
        self.assertIn('angle',self.w.widgets);self.assertNotIn('distance2',self.w.widgets)

    def test_fillet_variable_radius_field(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        base=Document([plate])
        edge=next(e for e in base.solid.val().Edges() if abs(e.Center().z-10)<1e-6)
        fillet=dict(kind='fillet',id='f0000001',name='Fillet',enabled=True,radius=2.,edges='vertical',edge_refs=[edge_reference(edge,base.solid)],auto_fit=True)
        self.load([plate,fillet]);self.w.select(1);self.app.processEvents()
        self.w.change_edge_mode('variable');self.app.processEvents()
        self.assertIn('radius_end',self.w.widgets)
        self.w.widgets['radius_end'].setValue(5.);self.w.apply_feature();self.app.processEvents()
        self.assertEqual(self.w.doc.features[1]['mode'],'variable');self.assertEqual(self.w.doc.features[1]['radius_end'],5.)

    def test_hole_standard_sizes_set_diameter_and_head(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        self.load([plate]);self.w.start_solid_tool('hole');self.app.processEvents()
        self.w.apply_hole_standard('M5','clearance');self.assertEqual(self.w.draft['diameter'],5.5)
        self.w.apply_hole_standard('M5','tap');self.assertEqual(self.w.draft['diameter'],4.2)
        self.w.change_hole_type('counterbore');self.assertEqual(self.w.draft['head_diameter'],10.0);self.assertEqual(self.w.draft['head_depth'],5.4)
        self.w.apply_hole_standard('','clearance');self.assertNotIn('standard',self.w.draft)

    def test_hole_editor_offers_sketches_with_points(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        points=new_sketch(base_frame('XY'),'Drill points');points['frame']=dict(origin=[0,0,10],u=[1,0,0],normal=[0,0,1])
        points['entities']=[entity('point',p=[-10,0]),entity('point',p=[10,0])]
        self.load([plate,points]);self.w.start_solid_tool('hole');self.app.processEvents()
        box=self.w.widgets['points_sketch'];self.assertGreaterEqual(box.count(),2)
        self.assertIn('x',self.w.widgets)                              # single hole: coordinates are shown
        box.setCurrentIndex(box.findData(points['id']));self.app.processEvents()
        self.assertEqual(self.w.draft['points_sketch'],points['id']);self.assertNotIn('x',self.w.widgets)
        self.w.draft['direction']='inward';self.w.draft['depth']=4.;self.w.draft['diameter']=4.
        self.w.apply_feature();self.app.processEvents()
        self.assertAlmostEqual(12000-self.w.doc.solid.val().Volume(),2*math.pi*4*4,places=3)

    def test_sweep_editor_has_a_guide_curve_choice(self):
        profile=new_sketch(base_frame('XY'),'Profile');profile['entities']=[entity('circle',center=[0,0],radius=2)]
        path=new_sketch(base_frame('XZ'),'Path');path['entities']=[entity('line',a=[0,0],b=[0,30])]
        self.load([profile,path])
        self.w.start_solid_tool('sweep');self.app.processEvents()
        self.assertIn('guide',self.w.widgets)

    def test_mate_joint_editor(self):
        base=dict(kind='component',id='c1',name='Base',enabled=True,features=[dict(kind='primitive',id='b1',name='b',enabled=True,shape='box',width=10.,length=10.,height=10.,origin=[0,0,0],operation='new')],pose=dict(origin=[0,0,0],axis=[0,0,1],angle=0.),grounded=False)
        part=copy.deepcopy(base);part.update(id='c2',name='Part')
        self.load([base,part]);self.w.start_assembly('joint');self.app.processEvents()
        self.w.change_joint_type('mate');self.app.processEvents()
        self.assertIn('mate_offset',self.w.widgets)
        self.assertNotIn('anchorX',self.w.widgets)

    def test_clicking_a_face_in_edge_mode_takes_all_its_edges_and_select_all(self):
        from PySide6.QtCore import QPointF
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        self.load([plate]);self.w.new_edge('fillet');self.app.processEvents()
        w=self.w.workspace;w.set_mode('edge')
        top=max(range(len(w.faces)),key=lambda i:w.faces[i].Center().z)
        centre=w.project([list(w.faces[top].Center().toTuple())])[0][0]
        w.toggle_edge_at(QPointF(*centre));self.app.processEvents()
        self.assertEqual(len(w.selected_edges),4)
        w.toggle_edge_at(QPointF(*centre));self.assertEqual(len(w.selected_edges),0)       # a second click deselects
        self.w.widgets  # editor is built
        w.select_all_edges();self.assertEqual(len(w.selected_edges),len(w.solid_edges))
        w.clear_edge_selection();self.assertEqual(len(w.selected_edges),0)

    def test_shell_side_is_a_choice_not_a_negative_number(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        self.load([plate]);self.w.start_solid_tool('shell');self.app.processEvents()
        box=self.w.widgets['thickness'];side=self.w.widgets['shell_side']
        self.assertEqual(side.currentData(),'inside');self.assertEqual(box.text(),'1.0000')        # shown as a positive number
        self.assertLess(self.w.draft['thickness'],0)
        box.lineEdit().setText('2.5');box.interpretText();self.assertEqual(self.w.draft['thickness'],-2.5)
        side.setCurrentIndex(side.findData('outside'));self.app.processEvents()
        self.assertEqual(self.w.draft['thickness'],2.5)
        box.stepBy(1);self.assertEqual(self.w.draft['thickness'],3.5)       # up arrow always makes the wall thicker

    def test_revolve_symmetric_and_axis_through_profile(self):
        sketch,extrude=sketch_and_extrude()
        profile=new_sketch(base_frame('XZ'),'Half');profile['entities']=[entity('rectangle',center=[12,10],width=4,height=20)]
        source=dict(type='sketch',sketch=profile['id'],entities=profile_regions(profile)[0]['entities'],holes=[],profile_mode='nested')
        spin=dict(kind='revolve',id='r1',name='Revolve',enabled=True,source=source,axis=dict(type='origin',axis='Z'),angle=90.,operation='add',symmetric=True)
        document=Document([profile,spin]);box=document.solid.val().BoundingBox()
        # a quarter turn centred on the XZ plane reaches both +Y and -Y by the same amount
        self.assertAlmostEqual(box.ymin,-box.ymax,places=4)
        crossing=new_sketch(base_frame('XZ'),'Across');crossing['entities']=[entity('rectangle',center=[0,10],width=6,height=20)]
        bad=dict(spin,id='r2',source=dict(type='sketch',sketch=crossing['id'],entities=profile_regions(crossing)[0]['entities'],holes=[],profile_mode='nested'),symmetric=False)
        from model import ModelError
        with self.assertRaises(ModelError) as raised:Document([crossing,bad])
        self.assertIn('passes through the profile',str(raised.exception))

    def test_hole_drill_point_and_pattern_overall_length(self):
        plate=new_feature();plate.update(width=40,height=30,depth=10,id='plate001',name='Plate')
        hole=dict(kind='hole',id='h1',name='Hole',enabled=True,operation='cut',plane=dict(type='origin',plane='XY'),x=0.,y=0.,depth=4.,diameter=6.,
                  hole_type='simple',head_diameter=10.,head_depth=3.,head_angle=90.,through_all=False,direction='outward',tip_angle=0.)
        # the plate sits on the XY plane, so drill upward from the plane
        flat=Document([plate,hole]).solid.val().Volume()
        pointed=Document([plate,dict(hole,id='h2',tip_angle=118.)]).solid.val().Volume()
        cone=(1/3)*math.pi*9*(3/math.tan(math.radians(59)))
        self.assertAlmostEqual(flat-pointed,cone,places=3)
        base=Document([plate]);ref=dict(kind='body_rectangular',id='p1',name='Pattern',enabled=True,targets=[],plane=dict(type='origin',plane='XY'),columns=3,rows=1,spacing_x=60.,spacing_y=20.)
        from references import body_reference
        ref['targets']=[body_reference(base.solid.val().Solids()[0],0,1,base.solid)]
        bodies=Document([plate,dict(ref,spacing_mode='extent')]).solids()
        xs=sorted(round(b.Center().x,3) for b in bodies)
        self.assertEqual(xs,[0.0,30.0,60.0])                                # 60 mm overall, three copies: 30 mm apart

    def test_construction_axis_from_a_round_face(self):
        cylinder=dict(kind='primitive',id='cy1',name='Cylinder',enabled=True,shape='cylinder',radius=5.,height=20.,origin=[10,0,0],operation='new')
        self.load([cylinder]);self.w.start_solid_tool('construction_axis');self.app.processEvents()
        face=next(i for i,f in enumerate(self.w.workspace.faces) if f.geomType()=='CYLINDER')
        self.w.workspace.solid_pick_key='cylinder_axis:reference'
        self.w.pick_solid_face(face);self.app.processEvents()
        ref=self.w.draft['reference'];self.assertEqual(ref['type'],'points')
        import numpy as np
        direction=np.asarray(ref['end'])-np.asarray(ref['start']);self.assertAlmostEqual(abs(direction[2])/np.linalg.norm(direction),1.,places=6)
        self.assertAlmostEqual(ref['start'][0],10.,places=6)


if __name__=='__main__':
    unittest.main()
