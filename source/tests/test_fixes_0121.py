"""Regression tests for the 0.12.1 review fixes."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Document,ModelError,edge_reference,build_state
from geometry import base_frame,new_sketch,entity,regions,face_reference,frame_on_face,identifier


def extrusion(sketch,ids=None,depth=5,operation='add'):
    return dict(kind='extrude',id=identifier(),name='Extrude',enabled=True,depth=depth,operation=operation,
                source={'type':'sketch','sketch':sketch['id'],'entities':ids or regions(sketch)[0]})


def base_part(width=40,center=(0,0)):
    s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=list(center),width=width,height=30)]
    return [s,extrusion(s,depth=10)]


class FilletErrorTests(unittest.TestCase):
    def test_failed_fillet_reports_a_model_error_not_a_python_error(self):
        features=base_part();d=Document(features)
        edges=[e for e in d.solid.val().Edges() if e.geomType()=='LINE'][:3]
        fillet=dict(kind='fillet',id=identifier(),name='Fillet',enabled=True,radius=500.,edge_refs=[edge_reference(e,d.solid) for e in edges])
        with self.assertRaises(ModelError) as caught:d.commit(features+[fillet])
        self.assertNotIn('local variable',str(caught.exception))
        self.assertIn('Fillet',str(caught.exception))


class SlotTests(unittest.TestCase):
    def test_slot_extrusion_has_true_arcs(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('slot',a=[-10,0],b=[10,0],width=6)]
        d=Document([s,extrusion(s,depth=4)])
        kinds={e.geomType() for e in d.solid.val().Edges()}
        self.assertIn('CIRCLE',kinds)
        self.assertLess(len(d.solid.val().Faces()),10)
        self.assertAlmostEqual(d.solid.val().Volume(),(20*6+math.pi*9)*4,places=4)


class FaceSketchOriginTests(unittest.TestCase):
    def test_projected_face_sketch_stays_in_place_when_face_grows(self):
        features=base_part();d=Document(features)
        top=next(f for f in d.solid.val().Faces() if f.normalAt().z>.9)
        s=new_sketch(frame_on_face(top,projected=True),support=face_reference(top));s['frame_origin']='projected'
        s['entities']=[entity('circle',center=[10,0],radius=2)]
        features+=[s,extrusion(s,depth=3)];d=Document(features)
        def boss_x(doc):
            return [e.Center().x for e in doc.solid.val().Edges() if e.geomType()=='CIRCLE' and e.Center().z>12.5][0]
        self.assertAlmostEqual(boss_x(d),10,places=6)
        changed=copy.deepcopy(features);changed[0]['entities'][0].update(center=[5,0],width=50);d.commit(changed)
        self.assertAlmostEqual(boss_x(d),10,places=6)

    def test_legacy_face_sketch_keeps_face_centre_origin(self):
        features=base_part();d=Document(features)
        top=next(f for f in d.solid.val().Faces() if f.normalAt().z>.9)
        s=new_sketch(frame_on_face(top),support=face_reference(top));s['entities']=[entity('circle',center=[0,0],radius=2)]
        features+=[s];changed=copy.deepcopy(features);changed[0]['entities'][0].update(center=[5,0])
        _,_,frames=build_state(changed);self.assertAlmostEqual(frames[s['id']]['origin'][0],5)


class TolerantLoadTests(unittest.TestCase):
    def test_project_with_failing_feature_still_opens(self):
        features=base_part();broken=dict(kind='extrude',id=identifier(),name='Broken',enabled=True,depth=5,operation='add',
                                          source={'type':'sketch','sketch':'missing','entities':['x']})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'broken.fcad'
            path.write_text(json.dumps(dict(format='slothcad',version=9,units='mm',features=features+[broken],display={})),encoding='utf-8')
            d=Document.load(path)
        self.assertIsNotNone(d.build_error);self.assertEqual(d.build_error.feature_index,2)
        self.assertEqual(len(d.features),3);self.assertAlmostEqual(d.solid.val().Volume(),12000)
        repaired=copy.deepcopy(d.features);repaired[2]['enabled']=False
        d.commit(repaired);self.assertIsNone(d.build_error)

    @unittest.skipIf(__import__('sys').platform=='win32','Windows has no Unix permission bits')
    def test_save_uses_normal_permissions_and_keeps_existing_ones(self):
        import os
        mask=os.umask(0);os.umask(mask)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'part.fcad';d=Document(base_part());d.save(path)
            self.assertEqual(path.stat().st_mode & 0o777,0o666 & ~mask)
            os.chmod(path,0o640);d.save(path);self.assertEqual(path.stat().st_mode & 0o777,0o640)


class HistoryAndSolverTests(unittest.TestCase):
    def test_joint_depends_on_fixed_component(self):
        from feature_history import graph
        features=[dict(id='c1',kind='component',features=[]),dict(id='c2',kind='component',features=[]),dict(id='j',kind='joint',moving='c2',fixed='c1')]
        self.assertEqual(graph(features)['j'],{'c1','c2'})

    def test_arc_with_fixed_ends_has_one_degree_of_freedom(self):
        import constraints as C
        arc=entity('arc',a=[0,0],mid=[5,3],b=[10,0]);s=dict(entities=[arc],constraints=[])
        for key in ('a','b'):s['constraints'].append(C.new_constraint(s,'fix',[C.point_ref(arc['id'],key)]))
        self.assertEqual(C.constraint_status(s)['degrees_of_freedom'],1)

    def test_cached_trim_preview_matches_trim(self):
        from trim import trim_entities,_CUT_CACHE
        entities=[entity('rectangle',center=[0,0],width=20,height=10),entity('line',a=[0,-8],b=[0,8])]
        first=trim_entities(entities,1,[0,7],preview=True);_CUT_CACHE.clear()
        second=trim_entities(entities,1,[0,7],preview=True)
        np.testing.assert_allclose([first['a'],first['b']],[second['a'],second['b']])


if __name__=='__main__':unittest.main()
