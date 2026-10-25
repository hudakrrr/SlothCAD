import copy,unittest,math,tempfile
from pathlib import Path
import numpy as np
from constraints import (new_constraint,add_constraint,drag,unfix,constraint_status,validate_constraints,
                         point_ref,line_ref,circle_ref,ConstraintConflict,resolve_dimensions,solve)
from geometry import new_sketch,base_frame,entity
from model import Document,ModelError
from expressions import resolve

class CompletionTests(unittest.TestCase):
    def sketch(self,*entities):
        s=new_sketch(base_frame('XY'));s['entities']=list(entities);return s
    def add(self,s,kind,refs,**kw):return add_constraint(s,new_constraint(s,kind,refs,**kw))
    def test_fix_unfix_and_dof_drag(self):
        e=entity('line',a=[0,0],b=[10,0]);s=self.sketch(e);self.assertEqual(constraint_status(s)['degrees_of_freedom'],4)
        s=self.add(s,'fix',[line_ref(e['id'])]);self.assertTrue(constraint_status(s)['fully_constrained'])
        moved=drag(s,point_ref(e['id'],'b'),[20,30]);np.testing.assert_allclose(moved['entities'][0]['b'],[10,0],atol=1e-7)
        s=unfix(s,[line_ref(e['id'])]);self.assertEqual(constraint_status(s)['degrees_of_freedom'],4)
    def test_midpoint_follows_dragged_segment(self):
        e=entity('line',a=[0,0],b=[10,0]);p=entity('point',p=[5,0]);s=self.sketch(e,p)
        s=self.add(s,'midpoint',[point_ref(p['id'],'p'),line_ref(e['id'])]);s=drag(s,point_ref(e['id'],'b'),[20,8])
        a,b=s['entities'][0]['a'],s['entities'][0]['b'];np.testing.assert_allclose(s['entities'][1]['p'],(np.asarray(a)+b)/2,atol=1e-7)
    def test_concentric_equality_and_fix_fully_constrain_circle(self):
        a=entity('circle',center=[0,0],radius=5);b=entity('circle',center=[2,2],radius=3);s=self.sketch(a,b)
        s=self.add(s,'concentric',[circle_ref(a['id']),circle_ref(b['id'])]);s=self.add(s,'equal',[circle_ref(a['id']),circle_ref(b['id'])]);s=self.add(s,'fix',[circle_ref(a['id'])])
        self.assertTrue(constraint_status(s)['fully_constrained']);s=drag(s,point_ref(b['id'],'center'),[20,30]);validate_constraints(s)
        np.testing.assert_allclose(s['entities'][0]['center'],s['entities'][1]['center'],atol=1e-7)
    def test_collinear_drag_and_conflict_keeps_input(self):
        a=entity('line',a=[0,0],b=[10,0]);b=entity('line',a=[12,0],b=[20,0]);s=self.sketch(a,b)
        s=self.add(s,'collinear',[line_ref(a['id']),line_ref(b['id'])]);s=drag(s,point_ref(b['id'],'b'),[25,8]);validate_constraints(s)
        before=copy.deepcopy(s)
        with self.assertRaises(ConstraintConflict):self.add(s,'perpendicular',[line_ref(a['id']),line_ref(b['id'])])
        self.assertEqual(s,before)
    def test_point_on_object_is_bounded_to_segment(self):
        e=entity('line',a=[0,0],b=[10,0]);p=entity('point',p=[5,0]);s=self.sketch(e,p)
        s=self.add(s,'fix',[line_ref(e['id'])]);s=self.add(s,'point_on_object',[point_ref(p['id'],'p'),line_ref(e['id'])]);s=drag(s,point_ref(p['id'],'p'),[30,8]);validate_constraints(s)
        self.assertLessEqual(s['entities'][1]['p'][0],10.000001);self.assertAlmostEqual(s['entities'][1]['p'][1],0,places=6)
    def test_reference_dimension_updates_without_removing_freedom(self):
        e=entity('line',a=[0,0],b=[10,0]);s=self.sketch(e)
        s=self.add(s,'dimension',[line_ref(e['id'])],value=10,mode='length',reference=True,name='measured')
        self.assertEqual(constraint_status(s)['degrees_of_freedom'],4);s=drag(s,point_ref(e['id'],'b'),[20,5]);self.assertAlmostEqual(s['constraints'][0]['value'],math.hypot(20,5))
    def test_named_expression_updates_geometry_and_project(self):
        e=entity('line',a=[0,0],b=[10,0]);s=self.sketch(e);s['parameters']={'pitch':'5 mm','width':'pitch * 2'}
        s=self.add(s,'dimension',[line_ref(e['id'])],value=10,mode='length',expression='width',name='length')
        s['parameters']['pitch']='7.5 mm';result=solve(s);self.assertAlmostEqual(np.linalg.norm(np.asarray(result['entities'][0]['b'])-result['entities'][0]['a']),15,places=6)
        d=Document([s]);self.assertAlmostEqual(d.features[0]['constraints'][0]['value'],15)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'expression.fcad';d.save(p);loaded=Document.load(p);self.assertEqual(loaded.features[0]['parameters']['pitch'],'7.5 mm')
    def test_expression_units_cycles_and_code_rejected(self):
        values=resolve({'a':'1 inch','b':'a/2','c':'sin(30 deg)'})
        self.assertAlmostEqual(values['b'],12.7);self.assertAlmostEqual(values['c'],.5)
        for definitions in ({'a':'b','b':'a'},{'a':'unknown + 1'},{'a':'__import__("os").system("false")'},{'a':'2 ** 100000'},{'a':'1/0'}):
            with self.assertRaises(ModelError):resolve(definitions)
