import copy
import math
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Document,ModelError,build_state
from geometry import (base_frame,new_sketch,entity,regions,face_reference,frame_on_face,
                      snap,arc_data,identifier)

def extrusion(sketch,ids=None,depth=5,operation='add'):
    return dict(kind='extrude',id=identifier(),name='Extrude',enabled=True,depth=depth,operation=operation,
                source={'type':'sketch','sketch':sketch['id'],'entities':ids or regions(sketch)[0]})
def base_part():
    s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=40,height=30)]
    return [s,extrusion(s,depth=10)]

class SketchModelTests(unittest.TestCase):
    def test_standalone_sketch_no_body_and_roundtrip(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('line',a=[0,0],b=[10,0])]
        d=Document([s]);self.assertIsNone(d.solid);self.assertEqual(regions(s),[])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sketch.fcad';d.save(p);self.assertEqual(Document.load(p).features,d.features)
    def test_connected_lines_make_extrudable_profile(self):
        s=new_sketch(base_frame('XY'));p=[[0,0],[20,0],[20,10],[0,10]]
        s['entities']=[entity('line',a=p[i],b=p[(i+1)%4]) for i in [2,0,3,1]]
        self.assertEqual(len(regions(s)),1)
        self.assertAlmostEqual(Document([s,extrusion(s)]).solid.val().Volume(),1000)
    def test_adjacent_closed_profiles_can_share_a_trimmed_edge(self):
        s=new_sketch(base_frame('XY'))
        segments=[([-10,-5],[0,-5]),([0,-5],[10,-5]),([10,-5],[10,5]),([10,5],[0,5]),([0,5],[-10,5]),([-10,5],[-10,-5]),([0,-5],[0,5])]
        s['entities']=[entity('line',a=a,b=b) for a,b in segments]
        faces=regions(s);self.assertEqual(len(faces),2)
        shared=s['entities'][-1]['id'];self.assertTrue(all(shared in face for face in faces))
        self.assertAlmostEqual(Document([s,extrusion(s,ids=faces[0])]).solid.val().Volume(),500)
        self.assertAlmostEqual(Document([s,extrusion(s,ids=faces[1])]).solid.val().Volume(),500)
    def test_arc_and_line_closed_profile(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('arc',a=[-10,0],mid=[0,10],b=[10,0]),entity('line',a=[10,0],b=[-10,0])]
        d=Document([s,extrusion(s,depth=2)])
        self.assertAlmostEqual(d.solid.val().Volume(),100*math.pi,places=5)
    def test_open_lines_rejected_as_extrusion(self):
        s=new_sketch(base_frame('XY'));e=entity('line',a=[0,0],b=[10,0]);s['entities']=[e]
        with self.assertRaises(ModelError):Document([s,extrusion(s,[e['id']])])
    def test_invalid_arc_transactional(self):
        d=Document(base_part());original=copy.deepcopy(d.features)
        s=new_sketch(base_frame('XY'));s['entities']=[entity('arc',a=[0,0],mid=[5,0],b=[10,0])]
        with self.assertRaises(ModelError):d.commit(original+[s])
        self.assertEqual(d.features,original)
    def test_profile_selection_extrudes_only_chosen_region(self):
        s=new_sketch(base_frame('XY'));a=entity('circle',center=[0,0],radius=2);b=entity('rectangle',center=[20,0],width=10,height=10);s['entities']=[a,b]
        d=Document([s,extrusion(s,[a['id']],depth=3)])
        self.assertAlmostEqual(d.solid.val().Volume(),12*math.pi,places=5)
    def test_multi_profile_extrude_uses_one_depth_for_all_sources(self):
        s=new_sketch(base_frame('XY'));a=entity('circle',center=[-10,0],radius=2);b=entity('circle',center=[10,0],radius=3);s['entities']=[a,b]
        sources=[{'type':'sketch','sketch':s['id'],'entities':[a['id']]},{'type':'sketch','sketch':s['id'],'entities':[b['id']]}]
        f=dict(kind='extrude',id=identifier(),name='Multi extrusion',enabled=True,depth=5,operation='add',signed_depth=False,source=sources[0],sources=sources)
        d=Document([s,f]);self.assertAlmostEqual(d.solid.val().Volume(),5*math.pi*(2**2+3**2),places=5);self.assertEqual(len(d.solid.val().Solids()),2)
    def test_multi_face_extrude_extends_all_selected_faces(self):
        features=base_part();base=Document(features)
        top=next(face for face in base.solid.val().Faces() if face.normalAt().z>.9)
        bottom=next(face for face in base.solid.val().Faces() if face.normalAt().z<-.9)
        sources=[{'type':'face','face':face_reference(top)},{'type':'face','face':face_reference(bottom)}]
        f=dict(kind='extrude',id=identifier(),name='Two faces',enabled=True,depth=2,operation='add',signed_depth=False,source=sources[0],sources=sources)
        d=Document(features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),40*30*(10+4),places=5)
    def test_snap_offgrid_vertices_edges_and_circle_center(self):
        rectangle=entity('rectangle',center=[0,0],width=20.5,height=10.5)
        q,label=snap([10.21,1.83],[rectangle],1,.15)
        np.testing.assert_allclose(q,[10.25,1.83]);self.assertEqual(label,'edge')
        q,label=snap([10.22,5.22],[rectangle],1,.15)
        np.testing.assert_allclose(q,[10.25,5.25]);self.assertEqual(label,'vertex / center')
        circle=entity('circle',center=[2.25,3.75],radius=5)
        q,label=snap([2.2,3.7],[circle],1,.15);np.testing.assert_allclose(q,[2.25,3.75])
        q,label=snap([50.4,60.8],[rectangle],.5,.1);np.testing.assert_allclose(q,[50.5,61]);self.assertEqual(label,'grid')
    def test_arc_snapping_uses_curve_not_tessellation(self):
        arc=entity('arc',a=[-10,0],mid=[0,10],b=[10,0])
        q,_=snap([7.1,7.1],[arc],1,.5)
        self.assertAlmostEqual(float(np.linalg.norm(q)),10,places=8)
    def test_side_face_sketch_and_support_follows_resize(self):
        features=base_part();d=Document(features)
        face=next(f for f in d.solid.val().Faces() if f.normalAt().x>.9)
        s=new_sketch(frame_on_face(face),support=face_reference(face));s['entities']=[entity('circle',center=[0,0],radius=3)]
        features += [s,extrusion(s,depth=5)];d=Document(features)
        self.assertAlmostEqual(d.solid.val().Volume(),12000+45*math.pi,places=5)
        changed=copy.deepcopy(features);changed[0]['entities'][0]['width']=50;d.commit(changed)
        self.assertAlmostEqual(d.solid.val().Volume(),15000+45*math.pi,places=5)
        _,_,frames=build_state(changed);self.assertAlmostEqual(frames[s['id']]['origin'][0],25)
    def test_universal_face_extrusion_add_cut(self):
        features=base_part();d=Document(features)
        face=next(f for f in d.solid.val().Faces() if f.normalAt().x>.9)
        f=dict(kind='extrude',name='Side face',depth=5,operation='add',source={'type':'face','face':face_reference(face)})
        d=Document(features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),13500)
        f.update(depth=-5,operation='cut');d=Document(features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),10500)
    def test_face_extrusion_retains_holes(self):
        features=base_part();d=Document(features)
        top=next(f for f in d.solid.val().Faces() if f.normalAt().z>.9)
        s=new_sketch(frame_on_face(top),support=face_reference(top));s['entities']=[entity('circle',center=[0,0],radius=3)]
        features += [s,extrusion(s,depth=-10,operation='cut')];d=Document(features)
        top=next(f for f in d.solid.val().Faces() if f.geomType()=='PLANE' and f.normalAt().z>.9)
        f=dict(kind='extrude',name='Top face',depth=5,operation='add',source={'type':'face','face':face_reference(top)})
        d=Document(features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),18000-135*math.pi,places=5)
    def test_earlier_sketch_edit_rebuilds_and_missing_profile_rejected(self):
        features=base_part();d=Document(features);changed=copy.deepcopy(features);changed[0]['entities'][0]['width']=50
        d.commit(changed);self.assertAlmostEqual(d.solid.val().Volume(),15000)
        changed[0]['entities']=[]
        with self.assertRaises(ModelError):d.commit(changed)
        self.assertAlmostEqual(d.solid.val().Volume(),15000)

if __name__=='__main__':unittest.main()
