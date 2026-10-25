import copy
import math
import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from unittest.mock import patch
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from app import Window
from model import Document, new_feature
from geometry import new_sketch, base_frame, entity, profile_regions
from i18n import set_language
from pick_slots import slots_for


def plate(**fields):
    f=new_feature();f.update(width=40,height=30,depth=10,id='plate001',name='Plate');f.update(fields);return f


class ClickToChooseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.resize(1200,850);self.w.show();self.app.processEvents()

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def load(self,features):
        self.w.doc=Document(features);self.w.refresh(True);self.app.processEvents()
        self.w.workspace.set_mode('model')

    def click_face(self,predicate):
        """Click the middle of the first face for which ``predicate(face)`` holds."""
        ws=self.w.workspace
        for index,face in enumerate(ws.faces):
            if predicate(face):
                screen=ws.project([list(face.Center().toTuple())])[0][0]
                hit=ws.slot_hit(QPointF(*screen))
                self.assertIsNotNone(hit,'nothing under the pointer')
                self.w.slot_clicked(hit);self.app.processEvents();return hit
        self.fail('no such face')

    def click_world(self,point):
        ws=self.w.workspace;screen=ws.project([point])[0][0]
        hit=ws.slot_hit(QPointF(*screen));self.assertIsNotNone(hit);self.w.slot_clicked(hit);self.app.processEvents();return hit

    def top(self,face):return face.geomType()=='PLANE' and abs(face.normalAt().z-1)<1e-6 and face.Center().z>1
    def side(self,face):return face.geomType()=='PLANE' and abs(face.normalAt().x-1)<1e-6

    # ---- inputs are taken from clicks -----------------------------------------------------------
    def test_mirror_body_then_plane_by_chip_and_apply(self):
        self.load([plate()]);self.w.start_body_tool('body_mirror');self.app.processEvents()
        self.assertEqual(self.w.active_slot,'targets')
        self.assertTrue(self.w.workspace.slot_accept)
        self.click_face(self.top)                    # one click on the body
        self.assertEqual(len(self.w.draft['targets']),1);self.assertEqual(self.w.active_slot,'plane')
        chips=self.w.widgets['slot_panel'].findChildren(type(self.w.undo_button))
        xy=next(c for c in chips if c.text()=='YZ');xy.click();self.app.processEvents()
        self.assertEqual(self.w.draft['plane'],dict(type='origin',plane='YZ'))
        self.w.apply_feature();self.app.processEvents()
        self.assertEqual(len(self.w.doc.solids()),2)

    def test_draft_faces_then_neutral_plane_from_a_face(self):
        self.load([plate()]);self.w.start_solid_tool('draft');self.app.processEvents()
        self.assertEqual(self.w.active_slot,'faces')
        self.click_face(self.side);self.assertEqual(len(self.w.draft['faces']),1)
        self.click_face(self.side);self.assertEqual(len(self.w.draft['faces']),0)        # a second click removes it
        self.click_face(self.side)
        self.w.activate_slot('neutral');self.click_face(lambda f:f.geomType()=='PLANE' and abs(f.normalAt().z+1)<1e-6)
        self.assertEqual(self.w.draft['neutral']['type'],'face')
        self.assertEqual(missing:=__import__('requirements').missing_inputs(self.w.draft),[])
        self.w.draft['angle']=5.;self.w.apply_feature();self.assertEqual(len(self.w.doc.features),2)

    def test_hole_site_is_the_clicked_point_on_the_face(self):
        self.load([plate()]);self.w.start_solid_tool('hole');self.app.processEvents()
        self.assertEqual(self.w.active_slot,'plane')
        ws=self.w.workspace;screen=ws.project([[8.,5.,10.]])[0][0]
        hit=ws.slot_hit(QPointF(*screen));self.assertEqual(hit['type'],'face')
        self.w.slot_clicked(hit);self.app.processEvents()
        self.assertAlmostEqual(self.w.draft['x'],8.,places=1);self.assertAlmostEqual(self.w.draft['y'],5.,places=1)
        self.assertEqual(self.w.draft['plane']['type'],'face')
        self.w.draft['diameter']=4.;self.w.draft['depth']=3.;self.w.apply_feature()
        self.assertEqual(len(self.w.doc.features),2);self.assertAlmostEqual(12000-self.w.doc.solid.val().Volume(),math.pi*4*3,places=2)

    def test_revolve_profile_and_axis_by_clicking(self):
        profile=new_sketch(base_frame('XZ'),'Half');profile['entities']=[entity('rectangle',center=[15,10],width=10,height=20),entity('line',a=[0,-5],b=[0,30])]
        # the second entity is an open line: it can be clicked as a curve but is not a profile
        self.load([profile]);self.w.start_solid_tool('revolve');self.app.processEvents()
        ws=self.w.workspace
        source=self.w.draft.get('source')
        self.assertTrue(source is None or source['type']=='sketch')
        self.w.activate_slot('source')
        self.click_world([15.,0.,10.])                     # inside the rectangle
        self.assertEqual(self.w.draft['source']['type'],'sketch')
        self.w.activate_slot('axis')
        self.click_world([0.,0.,12.])                       # on the sketch line
        self.assertEqual(self.w.draft['axis']['type'],'sketch_line')
        self.w.draft['angle']=360.;self.w.apply_feature();self.app.processEvents()
        self.assertEqual(len(self.w.doc.features),2)
        self.assertAlmostEqual(self.w.doc.solid.val().Volume(),math.pi*(20**2-10**2)*20,places=1)

    def test_path_of_a_sweep_is_a_clicked_curve(self):
        profile=new_sketch(base_frame('XY'),'Profile');profile['entities']=[entity('circle',center=[0,0],radius=2)]
        path=new_sketch(base_frame('XZ'),'Path');path['entities']=[entity('line',a=[0,0],b=[0,30])]
        self.load([profile,path]);self.w.start_solid_tool('sweep');self.app.processEvents()
        self.w.activate_slot('path');self.click_world([0.,0.,15.])
        self.assertEqual(self.w.draft['path']['entities'],[path['entities'][0]['id']])

    def test_a_pattern_finds_the_feature_from_a_clicked_face(self):
        hole=new_feature();hole.update(profile='circle',radius=3,depth=12,z=-1,operation='cut',id='hole0001',name='Hole',x=10.)
        self.load([plate(),hole])
        self.w.start_advanced_tool('feature_rectangular');self.app.processEvents()
        self.w.draft['features']=[]        # forget the automatic choice: the user clicks the hole
        self.w.activate_slot('features')
        self.click_face(lambda f:f.geomType()=='CYLINDER')
        self.assertEqual(self.w.draft['features'],['hole0001'])
        self.click_face(lambda f:f.geomType()=='CYLINDER');self.assertEqual(self.w.draft['features'],[])       # toggles

    def test_joint_parts_and_mate_faces(self):
        a=dict(kind='component',id='c1',name='Base',enabled=True,features=[dict(kind='primitive',id='b1',name='b',enabled=True,shape='box',width=10.,length=10.,height=10.,origin=[0,0,0],operation='new')],pose=dict(origin=[0,0,0],axis=[0,0,1],angle=0.),grounded=False)
        b=copy.deepcopy(a);b.update(id='c2',name='Part');b['pose']['origin']=[40,0,0]
        self.load([a,b]);self.w.start_assembly('joint');self.app.processEvents()
        self.assertEqual(self.w.active_slot,'moving')
        ws=self.w.workspace
        screen=ws.project([[45.,5.,10.]])[0][0];self.w.slot_clicked(ws.slot_hit(QPointF(*screen)));self.app.processEvents()
        self.assertEqual(self.w.draft['moving'],'c2')
        self.w.change_joint_type('mate');self.app.processEvents()
        self.assertEqual([s.key for s in self.w.current_slots],['mate_moving','mate_target'])
        self.click_face(lambda f:f.geomType()=='PLANE' and abs(f.normalAt().z+1)<1e-6 and f.Center().x>30)
        self.assertEqual(self.w.draft['mate_moving']['type'],'face')
        self.click_face(lambda f:f.geomType()=='PLANE' and abs(f.normalAt().z-1)<1e-6 and f.Center().x<20)
        self.assertEqual(self.w.draft['mate_target']['type'],'face')
        self.w.apply_feature();self.assertEqual(len(self.w.doc.features),3)

    # ---- friendliness --------------------------------------------------------------------------
    def test_old_lists_are_hidden_until_asked_for(self):
        self.load([plate()]);self.w.start_body_tool('body_mirror');self.app.processEvents()
        self.assertTrue(self.w.widgets['targets'].isHidden())
        checkbox=next(c for c in self.w.widgets['slot_panel'].findChildren(__import__('PySide6.QtWidgets',fromlist=['QCheckBox']).QCheckBox))
        checkbox.setChecked(True);self.app.processEvents()
        self.assertFalse(self.w.widgets['targets'].isHidden())

    def test_clicking_nothing_explains_what_to_click(self):
        self.load([plate()]);self.w.start_body_tool('body_split');self.app.processEvents()
        self.w.slot_clicked(dict(type='none'))
        self.assertIn('Nothing there',self.w.statusBar().currentMessage())

    def test_wrong_kind_of_click_gets_a_clear_message(self):
        cylinder=dict(kind='primitive',id='cy',name='Cyl',enabled=True,shape='cylinder',radius=5.,height=20.,origin=[60,0,0],operation='new')
        self.load([plate(),cylinder]);self.w.start_solid_tool('draft');self.w.activate_slot('neutral');self.app.processEvents()
        self.click_face(lambda f:f.geomType()=='CYLINDER')
        self.assertIn('curved',self.w.statusBar().currentMessage());self.assertEqual(self.w.draft['neutral'],dict(type='origin',plane='XY'))      # unchanged

    def test_every_picked_tool_lists_its_inputs(self):
        for kind in ('revolve','sweep','loft','draft','hole','body_move','body_combine','feature_circular','joint','surface_trim'):
            self.assertTrue(slots_for(dict(kind=kind)),kind)


if __name__=='__main__':
    unittest.main()
