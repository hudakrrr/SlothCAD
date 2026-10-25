import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry import (base_frame,new_sketch,entity,regions,identifier,text_polygons,
                      rectangular_entities,mirror_entities,sample)
from model import Document


def extrusion(sketch,ids=None,depth=2):
    return dict(kind='extrude',id=identifier(),name='Extrude',enabled=True,depth=depth,operation='add',
                source={'type':'sketch','sketch':sketch['id'],'entities':ids or regions(sketch)[0]})

class DrawMenuGeometryTests(unittest.TestCase):
    def extrudable(self,e):
        s=new_sketch(base_frame('XY'));s['entities']=[e];self.assertEqual(len(regions(s)),1)
        d=Document([s,extrusion(s)]);self.assertGreater(d.solid.val().Volume(),0)
    def test_ellipse_and_slot_are_closed_extrudable_profiles(self):
        self.extrudable(entity('ellipse',center=[0,0],major=[5,0],minor_radius=2))
        self.extrudable(entity('slot',a=[-5,0],b=[5,0],width=4))
    def test_spline_and_conic_can_close_profiles_with_lines(self):
        for curve in [entity('spline',points=[[-5,0],[0,5],[5,0]]),entity('conic',a=[-5,0],control=[0,5],b=[5,0])]:
            s=new_sketch(base_frame('XY'));s['entities']=[curve,entity('line',a=[5,0],b=[-5,0])]
            self.assertEqual(len(regions(s)),1);self.assertGreater(Document([s,extrusion(s)]).solid.val().Volume(),0)
    def test_text_becomes_real_polygon_profiles(self):
        loops=text_polygons('A',[0,0],10);self.assertGreaterEqual(len(loops),2);self.assertTrue(all(e['kind']=='polygon' for e in loops))
        s=new_sketch(base_frame('XY'));s['entities']=loops;self.assertGreaterEqual(len(regions(s)),2)
        self.assertGreater(Document([s,extrusion(s,regions(s)[0],1)]).solid.val().Volume(),0)
    def test_rectangular_pattern_preserves_geometry(self):
        source=entity('circle',center=[0,0],radius=2);copies=rectangular_entities([source],3,2,10,20)
        self.assertEqual(len(copies),5);self.assertEqual([e['center'] for e in copies],[[10.,0.],[20.,0.],[0.,20.],[10.,20.],[20.,20.]])
        self.assertTrue(all(e['radius']==2 for e in copies))
    def test_new_entities_support_rigid_transforms(self):
        guide=entity('line',a=[0,-10],b=[0,10]);ellipse=entity('ellipse',center=[5,0],major=[8,0],minor_radius=2)
        mirrored=mirror_entities([ellipse],guide)[0];self.assertEqual(mirrored['kind'],'ellipse');self.assertAlmostEqual(mirrored['center'][0],-5)
        self.assertAlmostEqual(len(sample(mirrored)),65)

if __name__=='__main__':unittest.main()
