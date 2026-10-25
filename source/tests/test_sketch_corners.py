import copy
import math
import unittest
import numpy as np
from geometry import entity,arc_data,new_sketch,base_frame,regions,sample
from model import Document
from sketch_corners import modify_corner
from legacy_model import ModelError

class SketchCornerTests(unittest.TestCase):
    def setUp(self):self.rectangle=[entity('rectangle',center=[0,0],width=20,height=10)]
    def test_fillet_is_exact_tangent_arc_and_keeps_closed_profile(self):
        result=modify_corner(self.rectangle,[10,5],'fillet',2,.5)
        c,r,_,_=arc_data(result[-1]);np.testing.assert_allclose(c,[8,3]);self.assertAlmostEqual(r,2)
        for key in ('a','b'):
            point=np.array(result[-1][key]);line=next(e for e in result[:-1] if np.linalg.norm(np.array(e['a'])-point)<1e-6 or np.linalg.norm(np.array(e['b'])-point)<1e-6)
            self.assertAlmostEqual(float((point-c)@(np.array(line['b'])-line['a'])),0,places=7)
        sketch=new_sketch(base_frame('XY'));sketch['entities']=result;self.assertEqual(len(regions(sketch)),1)
        from model import Document
        extrusion=dict(kind='extrude',name='Rounded plate',depth=2,operation='add',sources=[dict(type='sketch',sketch=sketch['id'],entities=regions(sketch)[0])])
        volume=Document([sketch,extrusion]).solid.val().Volume()
        self.assertAlmostEqual(volume,(200-4+math.pi)*2,places=5)
    def test_fillet_uses_the_inside_wedge_at_all_four_rectangle_corners(self):
        # A corner solver must not choose an external offset solution just
        # because that candidate has shorter tangent travel. That used to
        # trim away the wrong side at some orientations.
        for corner in ([10,5],[-10,5],[-10,-5],[10,-5]):
            with self.subTest(corner=corner):
                result=modify_corner(self.rectangle,corner,'fillet',2,.5)
                arc=next(e for e in result if e['kind']=='arc')
                center,radius,_,_=arc_data(arc)
                expected=np.asarray(corner)-np.sign(corner)*2
                np.testing.assert_allclose(center,expected,atol=1e-7)
                self.assertAlmostEqual(radius,2)
                sketch=new_sketch(base_frame('XY'));sketch['entities']=result
                self.assertEqual(len(regions(sketch)),1)
                extrusion=dict(kind='extrude',name='Rounded plate',depth=2,operation='add',sources=[dict(type='sketch',sketch=sketch['id'],entities=regions(sketch)[0])])
                volume=Document([sketch,extrusion]).solid.val().Volume()
                self.assertAlmostEqual(volume,(200-4+math.pi)*2,places=5)
    def test_chamfer_keeps_profile_and_can_modify_another_corner(self):
        first=modify_corner(self.rectangle,[10,5],'chamfer',2,.5)
        self.assertEqual(first[-1]['kind'],'line');self.assertAlmostEqual(math.dist(first[-1]['a'],first[-1]['b']),math.sqrt(8))
        second=modify_corner(first,[-10,5],'fillet',1,.5)
        sketch=new_sketch(base_frame('XY'));sketch['entities']=second;self.assertEqual(len(regions(sketch)),1)
    def test_joined_lines_preserve_ids_and_unrelated_geometry(self):
        edges=[entity('line',a=[0,0],b=[10,0]),entity('line',a=[0,10],b=[0,0]),entity('circle',center=[20,20],radius=2)]
        before=copy.deepcopy(edges);result=modify_corner(edges,[0,0],'chamfer',1,.5)
        self.assertEqual(edges,before);self.assertEqual([e['id'] for e in result[:3]],[e['id'] for e in edges])
        self.assertEqual(result[2],edges[2]);np.testing.assert_allclose(result[0]['a'],[1,0]);np.testing.assert_allclose(result[1]['b'],[0,1])
    def test_invalid_and_oversized_corners_leave_input_unchanged(self):
        before=copy.deepcopy(self.rectangle)
        for point,size in [([0,0],1),([10,5],0),([10,5],10),([10,5],float('nan'))]:
            with self.assertRaises(ModelError):modify_corner(self.rectangle,point,'fillet',size,.5)
        self.assertEqual(self.rectangle,before)
    def test_branching_junction_is_rejected(self):
        edges=[entity('line',a=[0,0],b=q) for q in ([10,0],[0,10],[-10,0])]
        with self.assertRaises(ModelError):modify_corner(edges,[0,0],'chamfer',1,.5)

    def test_arc_to_line_corner_accepts_fillet_and_chamfer(self):
        arc=entity('arc',a=[10,0],mid=[10.878679656,-2.121320344],b=[13,-3])
        line=entity('line',a=[0,0],b=[10,0])
        for kind in ('fillet','chamfer'):
            result=modify_corner([line,arc],[10,0],kind,.5,.25)
            self.assertIn(kind=='fillet' and 'arc' or 'line',[e['kind'] for e in result])
            original=[e for e in result if e['id'] in (line['id'],arc['id'])]
            self.assertEqual({e['kind'] for e in original},{'line','arc'})
            shared=next(e for e in result if e['id'] not in (line['id'],arc['id']))
            self.assertEqual(shared['kind'],'arc' if kind=='fillet' else 'line')
            sketch=new_sketch(base_frame('XY'));sketch['entities']=result+[entity('line',a=[13,-3],b=[0,-3]),entity('line',a=[0,-3],b=[0,0])]
            self.assertEqual(len(regions(sketch)),1)
            feature=dict(kind='extrude',name='Curve corner',depth=2,operation='add',sources=[dict(type='sketch',sketch=sketch['id'],entities=regions(sketch)[0])])
            self.assertTrue(Document([sketch,feature]).solid.val().isValid())

    def test_line_meets_conic_and_spline_endpoints(self):
        line=entity('line',a=[0,0],b=[10,0])
        for curve in (entity('conic',a=[10,0],control=[12,3],b=[14,4]),
                      entity('spline',points=[[10,0],[12,3],[14,4]])):
            for kind,connector in (('chamfer','line'),('fillet','arc')):
                result=modify_corner([line,curve],[10,0],kind,.4,.2)
                self.assertGreater(len(result),80)
                self.assertEqual(result[-1]['kind'],connector)

    def test_circle_line_crossing_selects_and_modifies_a_sketch_corner(self):
        entities=[entity('circle',center=[0,0],radius=5),entity('line',a=[-8,0],b=[8,0])]
        tangent_x=math.sqrt((5-.3)**2-.3**2)
        for cursor,center in (((4.9,.1),(tangent_x,.3)),((4.9,-.1),(tangent_x,-.3)),
                              ((-4.9,.1),(-tangent_x,.3)),((-4.9,-.1),(-tangent_x,-.3))):
            with self.subTest(cursor=cursor):
                result=modify_corner(entities,cursor,'fillet',.3,.3)
                center_actual,_,_,_=arc_data(result[-1])
                np.testing.assert_allclose(center_actual,center,atol=1e-6)
                sketch=new_sketch(base_frame('XY'));sketch['entities']=result
                self.assertEqual(len(regions(sketch)),1)
                feature=dict(kind='extrude',name='Crossing corner',depth=1,operation='add',sources=[dict(type='sketch',sketch=sketch['id'],entities=regions(sketch)[0])])
                self.assertTrue(Document([sketch,feature]).solid.val().isValid())
