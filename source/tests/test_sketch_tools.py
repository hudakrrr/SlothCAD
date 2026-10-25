import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from geometry import entity, arc_data, sample
from legacy_model import ModelError
from sketch_tools import extend_entity, offset_entities, transform_selection, scale_entity


def area_of(e):
    points=sample(e);x,y=points[:,0],points[:,1]
    return abs(.5*float(np.sum(x[:-1]*y[1:]-x[1:]*y[:-1])))


class ExtendTests(unittest.TestCase):
    def test_line_extends_to_the_next_curve_from_the_nearest_end(self):
        line=entity('line',a=[0,0],b=[10,0]);wall=entity('line',a=[25,-10],b=[25,10]);far=entity('line',a=[40,-10],b=[40,10])
        result=extend_entity([line,wall,far],0,[9,0])
        self.assertEqual(result[0]['b'],[25.,0.]);self.assertEqual(result[0]['a'],[0,0])
        with self.assertRaises(ModelError):extend_entity([wall,line],1,[1,0])     # nothing behind the other end

    def test_line_with_nothing_ahead_is_reported(self):
        with self.assertRaises(ModelError):extend_entity([entity('line',a=[0,0],b=[10,0])],0,[9,0])

    def test_arc_extends_along_its_circle_to_a_boundary(self):
        arc=entity('arc',a=[10,0],mid=[7.071067811865,7.071067811865],b=[0,10])      # quarter circle, radius 10
        wall=entity('line',a=[-20,5],b=[20,5])       # y = 5 meets the circle again, behind the start point
        result=extend_entity([arc,wall],0,[10,0.2])    # extend the start end (a)
        centre,radius,start,sweep=arc_data(result[0])
        np.testing.assert_allclose(centre,[0,0],atol=1e-9);self.assertAlmostEqual(radius,10,places=6)
        end_points=[np.asarray(result[0]['a']),np.asarray(result[0]['b'])]
        self.assertTrue(any(abs(p[1]-5)<1e-6 for p in end_points))     # reached the wall
        self.assertGreater(abs(sweep),math.pi/2)

    def test_other_kinds_are_refused(self):
        with self.assertRaises(ModelError):extend_entity([entity('circle',center=[0,0],radius=3)],0,[3,0])


class OffsetTests(unittest.TestCase):
    def test_closed_outline_grows_and_shrinks(self):
        square=entity('polygon',points=[[0,0],[10,0],[10,10],[0,10]])
        grown=offset_entities([square],[0],2.)
        self.assertAlmostEqual(sum(1 for e in grown if e['kind']=='line'),4)
        xs=[v for e in grown for v in (e['a'][0],e['b'][0])];self.assertAlmostEqual(min(xs),-2,places=5);self.assertAlmostEqual(max(xs),12,places=5)
        shrunk=offset_entities([square],[0],2.,flip=True)
        xs=[v for e in shrunk for v in (e['a'][0],e['b'][0])];self.assertAlmostEqual(min(xs),2,places=5);self.assertAlmostEqual(max(xs),8,places=5)

    def test_circle_offset_changes_the_radius(self):
        result=offset_entities([entity('circle',center=[3,4],radius=5)],[0],1.5)
        self.assertEqual(result[0]['kind'],'circle');self.assertAlmostEqual(result[0]['radius'],6.5,places=6)
        np.testing.assert_allclose(result[0]['center'],[3,4],atol=1e-9)

    def test_open_chain_is_offset_to_one_side(self):
        a=entity('line',a=[0,0],b=[10,0]);b=entity('line',a=[10,0],b=[10,10])
        left=offset_entities([a,b],[0,1],2.);right=offset_entities([a,b],[0,1],2.,flip=True)
        ys=lambda items:[v for e in items for v in (e['a'][1],e['b'][1])]
        self.assertNotEqual(round(min(ys(left)),6),round(min(ys(right)),6))
        self.assertEqual(len(left),2)

    def test_connected_pieces_become_one_chain(self):
        parts=[entity('line',a=[0,0],b=[10,0]),entity('line',a=[10,0],b=[10,10]),entity('line',a=[10,10],b=[0,10]),entity('line',a=[0,10],b=[0,0])]
        grown=offset_entities(parts,[0,1,2,3],1.)
        self.assertEqual(len(grown),4)

    def test_bad_input(self):
        square=entity('polygon',points=[[0,0],[10,0],[10,10],[0,10]])
        with self.assertRaises(ModelError):offset_entities([square],[0],0)
        with self.assertRaises(ModelError):offset_entities([square],[],1.)
        with self.assertRaises(ModelError):offset_entities([entity('point',p=[0,0])],[0],1.)


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.entities=[entity('line',a=[0,0],b=[10,0]),entity('rectangle',center=[20,0],width=4,height=2),entity('circle',center=[0,10],radius=2)]

    def test_move_keeps_identity_and_rectangles(self):
        result,ids=transform_selection(self.entities,[0,1],'move',dx=5,dy=-3)
        self.assertEqual(result[0]['id'],self.entities[0]['id']);self.assertEqual(result[0]['a'],[5.,-3.])
        self.assertEqual(result[1]['kind'],'rectangle');self.assertEqual(result[1]['center'],[25.,-3.])
        self.assertEqual(result[2],self.entities[2]);self.assertEqual(len(ids),2)

    def test_copy_adds_new_entities_and_leaves_originals(self):
        result,ids=transform_selection(self.entities,[0],'move',copy_it=True,dx=0,dy=7)
        self.assertEqual(len(result),4);self.assertEqual(result[0],self.entities[0])
        self.assertNotIn(result[3]['id'],[e['id'] for e in self.entities]);self.assertEqual(result[3]['a'],[0.,7.])

    def test_rotate_about_a_point(self):
        result,_=transform_selection(self.entities,[0],'rotate',angle=90,center=(0,0))
        np.testing.assert_allclose(result[0]['b'],[0,10],atol=1e-9)
        result,_=transform_selection(self.entities,[0],'rotate',angle=180,center=(5,0))
        np.testing.assert_allclose(result[0]['a'],[10,0],atol=1e-9)

    def test_scale_about_a_point(self):
        result,_=transform_selection(self.entities,[0,1,2],'scale',factor=2,center=(0,0))
        np.testing.assert_allclose(result[0]['b'],[20,0]);self.assertEqual(result[1]['width'],8);np.testing.assert_allclose(result[1]['center'],[40,0])
        self.assertEqual(result[2]['radius'],4);np.testing.assert_allclose(result[2]['center'],[0,20])

    def test_bad_values(self):
        for kwargs in (dict(mode='move'),dict(mode='rotate',angle=0),dict(mode='scale',factor=-1),dict(mode='shear')):
            with self.assertRaises(ModelError):transform_selection(self.entities,[0],**kwargs)
        with self.assertRaises(ModelError):transform_selection(self.entities,[],'move',dx=1)


if __name__=='__main__':
    unittest.main()
