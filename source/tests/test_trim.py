import unittest
import numpy as np
from geometry import entity,arc_data,validate_entity
from trim import trim_entities
class TrimTests(unittest.TestCase):
    def test_only_interval_between_crossings_removed(self):
        es=[entity('line',a=[0,0],b=[10,0])]+[entity('line',a=[x,-2],b=[x,2]) for x in (3,7)]
        result=trim_entities(es,0,[5,.01]);self.assertEqual(len(result),4)
        self.assertEqual(result[0]['a'],[0,0]);self.assertEqual(result[0]['b'],[3,0]);self.assertEqual(result[1]['a'],[7,0]);self.assertEqual(result[1]['b'],[10,0])
        self.assertEqual(result[-2:],es[1:]);self.assertEqual(result[0]['id'],es[0]['id'])
    def test_rectangle_side_retains_other_edges(self):
        es=[entity('rectangle',center=[0,0],width=10,height=10),entity('line',a=[0,-7],b=[0,-3])]
        result=trim_entities(es,0,[3,-5]);self.assertEqual(len(result),5)
        for e in result:validate_entity(e)
        self.assertTrue(any(e['a']==[-5.,-5.] and e['b']==[0.,-5.] for e in result))
    def test_circle_trims_half_and_retains_exact_arc(self):
        es=[entity('circle',center=[0,0],radius=5),entity('line',a=[-6,0],b=[6,0])]
        result=trim_entities(es,0,[0,5]);self.assertEqual(len(result),2);self.assertEqual(result[0]['kind'],'arc')
        c,r,a,sweep=arc_data(result[0]);self.assertAlmostEqual(r,5);self.assertAlmostEqual(abs(sweep),np.pi);self.assertLess(result[0]['mid'][1],0)
    def test_arc_cut_at_line_intersection(self):
        es=[entity('arc',a=[-5,0],mid=[0,5],b=[5,0]),entity('line',a=[0,-1],b=[0,6])]
        result=trim_entities(es,0,[3,4]);self.assertEqual(len(result),2);validate_entity(result[0]);self.assertAlmostEqual(abs(arc_data(result[0])[3]),np.pi/2)
    def test_isolated_edge_deleted(self):
        self.assertEqual(trim_entities([entity('line',a=[0,0],b=[3,0])],0,[1,0]),[])
