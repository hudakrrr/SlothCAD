import sys,unittest,math,tempfile,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from geometry import entity,mirror_entities,circular_entities,sample,arc_data,regions,new_sketch,base_frame,frame_on_face
from model import Document,ModelError
from test_sketch_model import base_part,extrusion

class TransformTests(unittest.TestCase):
    def test_arbitrary_line_mirror_preserves_exact_arc_and_circle(self):
        guide=entity('line',a=[2,2],b=[7,7]);circle=entity('circle',center=[5,2],radius=3)
        arc=entity('arc',a=[5,2],mid=[6,3],b=[5,4])
        result=mirror_entities([circle,arc],guide)
        np.testing.assert_allclose(result[0]['center'],[2,5]);self.assertEqual(result[0]['radius'],3)
        np.testing.assert_allclose(result[1]['a'],[2,5]);self.assertAlmostEqual(arc_data(result[1])[1],arc_data(arc)[1])
        self.assertLess(arc_data(result[1])[3]*arc_data(arc)[3],0)
        self.assertNotEqual(result[0]['id'],circle['id'])
    def test_mirror_rectangle_and_closed_line_profile_are_extrudable(self):
        guide=entity('line',a=[0,-10],b=[0,10]);rect=entity('rectangle',center=[8,0],width=4,height=6)
        copied=mirror_entities([rect,guide],guide);self.assertEqual(len(copied),1)
        s=new_sketch(base_frame('XY'));s['entities']=[rect]+copied
        self.assertEqual(len(regions(s)),2)
        d=Document([s,extrusion(s,ids=regions(s)[1])]);self.assertAlmostEqual(d.solid.val().Volume(),120)
    def test_invalid_mirror_axis(self):
        with self.assertRaises(ModelError):mirror_entities([],entity('circle',center=[0,0],radius=2))
        with self.assertRaises(ModelError):mirror_entities([],entity('line',a=[0,0],b=[0,0]))
    def test_circular_copies_have_uniform_angles_and_keep_radii(self):
        source=entity('circle',center=[12,5],radius=2);copies=circular_entities([source],[2,5],3)
        np.testing.assert_allclose([e['center'] for e in copies],[[2,15],[-8,5],[2,-5]],atol=1e-12)
        self.assertEqual(len({e['id'] for e in copies}),3);self.assertTrue(all(e['radius']==2 for e in copies))
        self.assertEqual(source['center'],[12,5])
    def test_multi_entity_rotation_preserves_rectangle_and_line_lengths(self):
        rect=entity('rectangle',center=[8,0],width=2,height=4);line=entity('line',a=[7,0],b=[9,0])
        result=circular_entities([rect,line],[0,0],2);self.assertEqual(len(result),4)
        self.assertEqual(result[0]['kind'],'polygon');self.assertAlmostEqual(np.linalg.norm(np.array(result[1]['b'])-result[1]['a']),2)
        s=new_sketch(base_frame('XY'));s['entities']=[result[0]]
        self.assertAlmostEqual(Document([s,extrusion(s)]).solid.val().Volume(),40)
    def test_invalid_pattern_count(self):
        for count in [0,101,1.5,True]:
            with self.assertRaises(ModelError):circular_entities([], [0,0],count)
    def test_negative_signed_depth_cuts_top_face_without_operation_switch(self):
        features=base_part();d=Document(features);top=max(d.solid.val().Faces(),key=lambda f:f.Center().z)
        s=new_sketch(frame_on_face(top));s['entities']=[entity('rectangle',center=[0,0],width=10,height=8)]
        cut=extrusion(s,depth=-4);cut['signed_depth']=True
        result=Document(features+[s,cut]);self.assertAlmostEqual(result.solid.val().Volume(),12000-320)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cut.fcad';result.save(path);self.assertAlmostEqual(Document.load(path).solid.val().Volume(),11680)
    def test_negative_cut_without_body_or_contact_is_rejected(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('circle',center=[100,100],radius=2)]
        cut=extrusion(s,depth=-2);cut['signed_depth']=True
        with self.assertRaisesRegex(ModelError,'existing body'):Document([s,cut])
        with self.assertRaisesRegex(ModelError,'does not intersect'):Document(base_part()+[s,cut])
    def test_legacy_negative_add_is_preserved(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('circle',center=[0,0],radius=2)]
        self.assertAlmostEqual(Document([s,extrusion(s,depth=-5)]).solid.val().Volume(),math.pi*20)
