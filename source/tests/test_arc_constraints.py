import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from geometry import entity, new_sketch, base_frame, arc_data
from legacy_model import ModelError
from constraints import (new_constraint, add_constraint, circle_ref, line_ref, point_ref, constraint_status,
                         validate_constraints, edges, drag)


def sketch_with(*entities):
    sketch=new_sketch(base_frame('XY'));sketch['entities']=list(entities);return sketch


def arc_geometry(sketch,index):
    e=sketch['entities'][index]
    center,radius,start,sweep=arc_data(e)
    return np.asarray(center),float(radius),float(sweep)


class ArcConstraintTests(unittest.TestCase):
    def arc(self):return entity('arc',a=[10,0],mid=[0,10],b=[-10,0])

    def test_arcs_are_pickable_as_circles(self):
        a=self.arc();self.assertEqual(edges(a),[circle_ref(a['id'])])

    def test_radius_and_diameter_dimension_on_arc(self):
        a=self.arc();s=sketch_with(a)
        s=add_constraint(s,new_constraint(s,'dimension',[circle_ref(a['id'])],7.,'radius'))
        center,radius,sweep=arc_geometry(s,0);self.assertAlmostEqual(radius,7.,places=5)
        b=entity('arc',a=[40,0],mid=[30,10],b=[20,0]);t=sketch_with(b)
        t=add_constraint(t,new_constraint(t,'dimension',[circle_ref(b['id'])],20.,'diameter'))
        self.assertAlmostEqual(arc_geometry(t,0)[1],10.,places=5)
        with self.assertRaises(ModelError):                   # radius 7 and diameter 20 contradict each other
            add_constraint(s,new_constraint(s,'dimension',[circle_ref(a['id'])],20.,'diameter'))

    def test_arc_orientation_is_preserved_by_the_solver(self):
        a=self.arc();s=sketch_with(a);before=arc_geometry(s,0)[2]
        s=add_constraint(s,new_constraint(s,'dimension',[circle_ref(a['id'])],30.,'radius'))
        after=arc_geometry(s,0)[2]
        self.assertGreater(after*before,0)               # same turning direction
        self.assertLess(abs(after),2*np.pi)

    def test_line_tangent_to_arc(self):
        a=self.arc();l=entity('line',a=[-20,0],b=[-20,15]);s=sketch_with(a,l)
        s=add_constraint(s,new_constraint(s,'tangent',[line_ref(l['id']),circle_ref(a['id'])]))
        center,radius,_=arc_geometry(s,0);line=s['entities'][1]
        p,q=np.asarray(line['a']),np.asarray(line['b']);d=(q-p)/np.linalg.norm(q-p)
        w=center-p;distance=abs(float(d[0]*w[1]-d[1]*w[0]))
        self.assertAlmostEqual(distance,radius,places=5)

    def test_arc_tangent_to_circle_both_ways(self):
        a=self.arc();c=entity('circle',center=[30,0],radius=5);s=sketch_with(a,c)
        s=add_constraint(s,new_constraint(s,'tangent',[circle_ref(a['id']),circle_ref(c['id'])]))
        center,radius,_=arc_geometry(s,0);circle=s['entities'][1]
        gap=float(np.linalg.norm(center-np.asarray(circle['center'])))
        self.assertAlmostEqual(gap,radius+circle['radius'],places=5)
        # internal tangency is chosen when the circle is inside
        inner=entity('circle',center=[0,1],radius=3);s2=sketch_with(self.arc(),inner)
        s2=add_constraint(s2,new_constraint(s2,'tangent',[circle_ref(s2['entities'][0]['id']),circle_ref(inner['id'])]))
        center,radius,_=arc_geometry(s2,0);circle=s2['entities'][1]
        self.assertAlmostEqual(float(np.linalg.norm(center-np.asarray(circle['center']))),abs(radius-circle['radius']),places=5)

    def test_equal_and_concentric_with_circles(self):
        a=self.arc();c=entity('circle',center=[40,40],radius=3);s=sketch_with(a,c)
        s=add_constraint(s,new_constraint(s,'equal',[circle_ref(a['id']),circle_ref(c['id'])]))
        self.assertAlmostEqual(arc_geometry(s,0)[1],s['entities'][1]['radius'],places=5)
        s=add_constraint(s,new_constraint(s,'concentric',[circle_ref(a['id']),circle_ref(c['id'])]))
        np.testing.assert_allclose(arc_geometry(s,0)[0],s['entities'][1]['center'],atol=1e-5)
        validate_constraints(s)

    def test_endpoint_stays_on_the_line_when_dragging_a_tangent_arc(self):
        a=self.arc();l=entity('line',a=[10,0],b=[10,-15]);s=sketch_with(a,l)
        s=add_constraint(s,new_constraint(s,'coincident',[point_ref(a['id'],'a'),point_ref(l['id'],'a')]))
        s=add_constraint(s,new_constraint(s,'tangent',[line_ref(l['id']),circle_ref(a['id'])]))
        moved=drag(s,point_ref(l['id'],'b'),[14,-20])
        validate_constraints(moved)

    def test_constraint_status_counts_arc_freedom(self):
        a=self.arc();s=sketch_with(a)
        s=add_constraint(s,new_constraint(s,'dimension',[circle_ref(a['id'])],10.,'radius'))
        self.assertEqual(constraint_status(s)['degrees_of_freedom'],constraint_status(sketch_with(a))['degrees_of_freedom']-1)

    def test_status_lists_fully_constrained_entities(self):
        a=entity('line',a=[0,0],b=[10,0]);b=entity('line',a=[0,5],b=[10,6]);s=sketch_with(a,b)
        s=add_constraint(s,new_constraint(s,'fix',[dict(kind='entity',entity=a['id'])]))
        status=constraint_status(s)
        self.assertIn(a['id'],status['constrained_entities']);self.assertNotIn(b['id'],status['constrained_entities'])

    def test_conflict_names_only_the_contradicting_constraints(self):
        a=entity('line',a=[0,0],b=[10,0]);b=entity('line',a=[0,5],b=[10,6]);s=sketch_with(a,b)
        s=add_constraint(s,new_constraint(s,'dimension',[line_ref(b['id'])],12.,'length'))
        s=add_constraint(s,new_constraint(s,'dimension',[line_ref(a['id'])],10.,'length'))
        s=add_constraint(s,new_constraint(s,'horizontal',[line_ref(a['id'])]))
        extra=new_constraint(s,'dimension',[line_ref(a['id'])],25.,'length')
        from constraints import ConstraintConflict
        with self.assertRaises(ConstraintConflict) as raised:add_constraint(s,extra)
        names=raised.exception.constraint_ids
        self.assertIn(extra['id'],names)
        self.assertLessEqual(len(names),2)                  # the 25 mm and the 10 mm length, not the unrelated line


if __name__=='__main__':
    unittest.main()
