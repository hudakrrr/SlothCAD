"""Selectable sketch cells, including boundaries borrowed from other entities."""
import os,copy,math,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from geometry import new_sketch,base_frame,entity,profile_regions,regions,wire_for
from model import Document
from workspace import Workspace
from app import Window

def example():
    s=new_sketch(base_frame('XY'))
    s['entities']=[entity('rectangle',center=[0,0],width=40,height=30),entity('rectangle',center=[0,0],width=10,height=6)]
    for a,b in [([-15,-15],[-15,-9]),([-15,-9],[-8,-7]),([-8,-7],[-2,-15])]:
        s['entities'].append(entity('line',a=a,b=b))
    return s

def extrusion(s,p,depth=5):
    return dict(kind='extrude',id='extrusion',name='Extrusion',depth=depth,operation='add',signed_depth=False,
                source=dict(type='sketch',sketch=s['id'],entities=p['entities'],holes=p['holes'],profile_mode='nested'))

class SharedBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_three_cells_without_mutating_the_sketch(self):
        s=example();original=copy.deepcopy(s);profiles=profile_regions(s)
        self.assertEqual(len(profiles),3)
        volumes=sorted(Document([s,extrusion(s,p)]).solid.val().Volume() for p in profiles)
        np.testing.assert_allclose(volumes,np.array([60,73,1067])*5,atol=1e-7)
        self.assertEqual(s,original)
    def test_cursor_selects_each_area_and_extrudes_only_that_area(self):
        s=example();w=Workspace();w.resize(600,400);w.set_scene(None,[(s,s['frame'])]);w.set_mode('extrude');w.aligned=np.eye(3);w.span=50
        try:
            hits=[]
            for point,area in [([10,8],1067),([0,0],60),([-10,-11],73)]:
                hit=w.pick(QPointF(*w.project_local([point],s['frame'])[0]));self.assertIsNotNone(hit)
                self.assertEqual(hit['profile_mode'],'nested');hits.append(hit)
                self.assertAlmostEqual(Document([s,extrusion(s,hit)]).solid.val().Volume(),area*5,places=6)
            self.assertEqual(len({w.extrusion_source_key(h) for h in hits}),3)
        finally:w.deleteLater();self.app.processEvents()
    def test_shared_region_save_reload_and_different_height(self):
        s=example();profiles=profile_regions(s)
        shared=next(p for p in profiles if abs(Document([s,extrusion(s,p)]).solid.val().Volume()-365)<1e-6)
        d=Document([s,extrusion(s,shared,8)])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'shared.fcad';d.save(path);loaded=Document.load(path)
            self.assertAlmostEqual(loaded.solid.val().Volume(),73*8,places=6)
            self.assertEqual(loaded.features[0]['entities'],s['entities'])
    def test_crossing_lines_partition_rectangle_into_four_regions(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=20),entity('line',a=[-10,0],b=[10,0]),entity('line',a=[0,-10],b=[0,10])]
        profiles=profile_regions(s);self.assertEqual(len(profiles),4)
        for p in profiles:self.assertAlmostEqual(Document([s,extrusion(s,p)]).solid.val().Volume(),500,places=6)
    def test_circle_chord_preserves_exact_curved_solids(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('circle',center=[0,0],radius=10),entity('line',a=[-10,0],b=[10,0])]
        profiles=profile_regions(s);self.assertEqual(len(profiles),2)
        for p in profiles:
            solid=Document([s,extrusion(s,p)]).solid.val()
            self.assertAlmostEqual(solid.Volume(),250*math.pi,places=6)
            self.assertTrue(any(f.geomType()=='CYLINDER' for f in solid.Faces()))
    def test_dangling_stroke_does_not_break_the_closed_face(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=20),entity('line',a=[-10,0],b=[0,0])]
        profiles=profile_regions(s);self.assertEqual(len(profiles),1)
        self.assertAlmostEqual(Document([s,extrusion(s,profiles[0])]).solid.val().Volume(),2000,places=6)
    def test_real_gap_does_not_create_a_closed_shared_shape(self):
        s=example();s['entities'][-1]['b'][1]=-14.9
        self.assertEqual(len(profile_regions(s)),2)
    def test_construction_line_does_not_partition_rectangle(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=20),entity('line',a=[-10,0],b=[10,0],construction=True)]
        self.assertEqual(regions(s),[[s['entities'][0]['id']]])
    def test_coincident_rectangle_sides_do_not_duplicate_a_boundary(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[-5,0],width=10,height=10),entity('rectangle',center=[5,0],width=10,height=10)]
        profiles=profile_regions(s);self.assertEqual(len(profiles),2)
        for p in profiles:self.assertAlmostEqual(Document([s,extrusion(s,p)]).solid.val().Volume(),500,places=6)
    def test_shared_shape_can_extrude_taller_after_the_outer_body(self):
        s=example();outer=next(p for p in profile_regions(s) if p['holes'])
        w=Window();errors=[];w.error=errors.append;w.doc=Document([s,extrusion(s,outer)]);w.workspace.set_mode('model');w.refresh()
        try:
            w.start_extrude();w.workspace.align(s['frame'])
            hit=w.workspace.pick(QPointF(*w.workspace.project_local([[-10,-11]],s['frame'])[0]))
            self.assertIsNotNone(hit);w.extrusion_picked(hit);w.draft['depth']=8
            w.apply_feature();self.assertEqual(errors,[]);self.assertIsNone(w.draft)
            self.assertAlmostEqual(w.doc.solid.val().Volume(),1067*5+73*8,places=6)
            self.assertEqual(len(w.doc.solid.val().Solids()),1)
        finally:w.hide();w.deleteLater();self.app.processEvents()
