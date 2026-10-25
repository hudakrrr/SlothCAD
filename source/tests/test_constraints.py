import copy
import math
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
from geometry import entity,new_sketch,base_frame,regions
from constraints import (new_constraint,add_constraint,drag,point_ref,line_ref,circle_ref,
                         validate_constraints,ConstraintConflict,edit_entity,retain_constraints)
from model import Document,ModelError


class ConstraintSolverTests(unittest.TestCase):
    def sketch(self,*entities):
        sketch=new_sketch(base_frame('XY'));sketch['entities']=list(entities);return sketch
    def constrain(self,s,kind,refs,value=None,mode=None):
        return add_constraint(s,new_constraint(s,kind,refs,value,mode))
    def line(self,a=(0,0),b=(10,3)):return entity('line',a=list(a),b=list(b))
    def assertValid(self,s):validate_constraints(s)

    def test_coincidence_drag_propagates_to_connected_endpoint_and_origin(self):
        a=self.line();b=self.line((12,4),(20,9));s=self.sketch(a,b)
        s=self.constrain(s,'coincident',[point_ref(a['id'],'b'),point_ref(b['id'],'a')])
        s=drag(s,point_ref(a['id'],'b'),[15,6]);self.assertValid(s)
        np.testing.assert_allclose(s['entities'][0]['b'],s['entities'][1]['a'],atol=1e-8)
        s=self.constrain(s,'coincident',[point_ref(a['id'],'a'),point_ref(None,'origin')])
        moved=drag(s,point_ref(a['id'],'a'),[7,7]);self.assertValid(moved)
        np.testing.assert_allclose(moved['entities'][0]['a'],[0,0],atol=1e-8)

    def test_horizontal_vertical_and_length_survive_handle_drag(self):
        for kind in ('horizontal','vertical'):
            with self.subTest(kind=kind):
                line=self.line();s=self.sketch(line);ref=line_ref(line['id'])
                s=self.constrain(s,kind,[ref]);s=self.constrain(s,'dimension',[ref],10,'length')
                s=drag(s,point_ref(line['id'],'b'),[16,12]);self.assertValid(s)
                a,b=np.asarray(s['entities'][0]['a']),np.asarray(s['entities'][0]['b'])
                self.assertAlmostEqual(np.linalg.norm(b-a),10,places=7)
                self.assertAlmostEqual((b-a)[1 if kind=='horizontal' else 0],0,places=7)

    def test_parallel_perpendicular_and_equality_while_dragging(self):
        for kind in ('parallel','perpendicular'):
            a=self.line();b=self.line((0,6),(6,8));s=self.sketch(a,b)
            s=self.constrain(s,kind,[line_ref(a['id']),line_ref(b['id'])])
            s=self.constrain(s,'equal',[line_ref(a['id']),line_ref(b['id'])])
            s=drag(s,point_ref(a['id'],'b'),[14,12]);self.assertValid(s)
            da=np.asarray(s['entities'][0]['b'])-s['entities'][0]['a'];db=np.asarray(s['entities'][1]['b'])-s['entities'][1]['a']
            self.assertAlmostEqual(np.linalg.norm(da),np.linalg.norm(db),places=7)
            self.assertAlmostEqual(da[0]*db[1]-da[1]*db[0] if kind=='parallel' else da@db,0,places=6)

    def test_circle_equality_and_radius_reject_conflicting_numeric_edit(self):
        a=entity('circle',center=[0,0],radius=3);b=entity('circle',center=[10,0],radius=4)
        s=self.sketch(a,b);s=self.constrain(s,'equal',[circle_ref(a['id']),circle_ref(b['id'])])
        s=self.constrain(s,'dimension',[circle_ref(a['id'])],5,'radius')
        s=drag(s,circle_ref(b['id']),[20,0]);self.assertValid(s)
        for e in s['entities']:self.assertAlmostEqual(e['radius'],5,places=8)
        before=copy.deepcopy(s);changed=copy.deepcopy(s['entities'][0]);changed['radius']=7
        with self.assertRaises(ConstraintConflict):edit_entity(s,changed)
        self.assertEqual(s,before)

    def test_symmetry_drag_keeps_points_reflected_across_movable_axis(self):
        axis=self.line((0,-10),(0,10));a=entity('point',p=[-5,2]);b=entity('point',p=[6,3])
        s=self.sketch(axis,a,b);s=self.constrain(s,'vertical',[line_ref(axis['id'])])
        s=self.constrain(s,'symmetry',[point_ref(a['id'],'p'),point_ref(b['id'],'p'),line_ref(axis['id'])])
        s=drag(s,point_ref(a['id'],'p'),[-8,7]);self.assertValid(s)
        axis_x=s['entities'][0]['a'][0];p=s['entities'][1]['p'];q=s['entities'][2]['p']
        np.testing.assert_allclose(q,[2*axis_x-p[0],p[1]],atol=1e-8)

    def test_tangent_line_circle_preserves_side_and_radius_when_dragged(self):
        line=self.line((-10,0),(10,0));circle=entity('circle',center=[0,6],radius=4)
        s=self.sketch(line,circle);s=self.constrain(s,'horizontal',[line_ref(line['id'])])
        s=self.constrain(s,'dimension',[circle_ref(circle['id'])],4,'radius')
        s=self.constrain(s,'tangent',[line_ref(line['id']),circle_ref(circle['id'])])
        for point in ([7,10],[-8,-7],[4,3]):
            s=drag(s,point_ref(circle['id'],'center'),point);self.assertValid(s)
            self.assertAlmostEqual(s['entities'][1]['center'][1]-s['entities'][0]['a'][1],4,places=7)

    def test_distance_offsets_angle_and_rectangle_edge_dimensions(self):
        a=entity('point',p=[0,0]);b=entity('point',p=[8,6]);s=self.sketch(a,b)
        s=self.constrain(s,'dimension',[point_ref(a['id'],'p'),point_ref(b['id'],'p')],10,'distance')
        s=drag(s,point_ref(b['id'],'p'),[30,20]);self.assertValid(s)
        self.assertAlmostEqual(math.dist(s['entities'][0]['p'],s['entities'][1]['p']),10,places=7)
        line=self.line();s=self.sketch(line);s=self.constrain(s,'dimension',[line_ref(line['id'])],45,'angle')
        s=drag(s,point_ref(line['id'],'b'),[5,20]);self.assertValid(s)
        rect=entity('rectangle',center=[0,0],width=20,height=10);s=self.sketch(rect)
        s=self.constrain(s,'dimension',[line_ref(rect['id'],0)],20,'length')
        s=drag(s,point_ref(rect['id'],'corner:2'),[17,14]);self.assertValid(s)
        self.assertAlmostEqual(s['entities'][0]['width'],20,places=7)
        self.assertEqual(len(regions(s)),1)

    def test_conflicting_dimensions_and_directions_are_transactional_with_ids(self):
        a=self.line();s=self.sketch(a);ref=line_ref(a['id']);s=self.constrain(s,'dimension',[ref],10,'length')
        before=copy.deepcopy(s);bad=new_constraint(s,'dimension',[ref],12,'length')
        with self.assertRaises(ConstraintConflict) as error:add_constraint(s,bad)
        self.assertIn(bad['id'],error.exception.constraint_ids);self.assertIn(s['constraints'][0]['id'],error.exception.constraint_ids)
        self.assertEqual(s,before)
        s=self.constrain(s,'horizontal',[ref]);before=copy.deepcopy(s)
        with self.assertRaises(ConstraintConflict):self.constrain(s,'vertical',[ref])
        self.assertEqual(s,before)

    def test_saved_constraints_rebuild_and_failed_document_edit_is_atomic(self):
        a=self.line();s=self.sketch(a);s=self.constrain(s,'horizontal',[line_ref(a['id'])]);doc=Document([s])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'constraints.fcad';doc.save(path);loaded=Document.load(path)
            self.assertEqual(loaded.features[0]['constraints'],s['constraints'])
            changed=copy.deepcopy(loaded.features);changed[0]['entities'][0]['b'][1]+=2
            with self.assertRaises(ModelError):loaded.commit(changed)
            self.assertEqual(loaded.features[0],s)

    def test_local_drag_leaves_unrelated_geometry_unchanged_and_fast(self):
        line=self.line();others=[entity('circle',center=[i*4,30],radius=1) for i in range(100)]
        s=self.sketch(line,*others);s=self.constrain(s,'horizontal',[line_ref(line['id'])])
        started=time.perf_counter()
        for i in range(12):s=drag(s,point_ref(line['id'],'b'),[i+10,i])
        self.assertLess(time.perf_counter()-started,2.)
        self.assertEqual(s['entities'][1:],others)

    def test_exact_unconstrained_grid_drag_and_rectangle_corner(self):
        line=self.line();s=self.sketch(line);moved=drag(s,point_ref(line['id'],'b'),[8.1,7.2])
        self.assertEqual(moved['entities'][0]['b'],[8.1,7.2]);self.assertEqual(moved['entities'][0]['a'],line['a'])
        rect=entity('rectangle',center=[0,0],width=20,height=10);s=self.sketch(rect)
        moved=drag(s,point_ref(rect['id'],'corner:2'),[12,9])
        self.assertEqual(moved['entities'][0]['center'],[1.,2.]);self.assertEqual(moved['entities'][0]['width'],22.)
        self.assertEqual(moved['entities'][0]['height'],14.);self.assertEqual(len(regions(moved)),1)

    def test_point_curve_coincidence_signed_offsets_and_diameter(self):
        line=self.line((-10,0),(10,0));p=entity('point',p=[3,4]);circle=entity('circle',center=[20,5],radius=4)
        s=self.sketch(line,p,circle);s=self.constrain(s,'coincident',[point_ref(p['id'],'p'),line_ref(line['id'])])
        s=drag(s,point_ref(p['id'],'p'),[8,9]);self.assertValid(s)
        s=self.constrain(s,'coincident',[point_ref(p['id'],'p'),circle_ref(circle['id'])]);s=drag(s,point_ref(p['id'],'p'),[18,8]);self.assertValid(s)
        s=self.constrain(s,'dimension',[circle_ref(circle['id'])],8,'diameter')
        s=drag(s,circle_ref(circle['id']),[30,30]);self.assertValid(s);self.assertAlmostEqual(s['entities'][2]['radius'],4,places=7)
        a=entity('point',p=[0,0]);b=entity('point',p=[5,8]);s=self.sketch(a,b)
        for mode,value in [('dx',-6),('dy',4)]:s=self.constrain(s,'dimension',[point_ref(a['id'],'p'),point_ref(b['id'],'p')],value,mode)
        s=drag(s,point_ref(b['id'],'p'),[20,15]);self.assertValid(s)
        np.testing.assert_allclose(np.array(s['entities'][1]['p'])-s['entities'][0]['p'],[-6,4],atol=1e-7)

    def test_delete_removes_only_affected_constraints(self):
        a=self.line();b=self.line((0,10),(10,10));s=self.sketch(a,b)
        s=self.constrain(s,'horizontal',[line_ref(a['id'])]);s=self.constrain(s,'horizontal',[line_ref(b['id'])])
        after=retain_constraints(s,[s['entities'][1]])
        self.assertEqual(len(after['constraints']),1);self.assertEqual(after['constraints'][0]['refs'][0]['entity'],b['id'])


if __name__=='__main__':unittest.main()
