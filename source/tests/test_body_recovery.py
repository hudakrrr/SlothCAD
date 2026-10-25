import copy,math,tempfile,unittest
from pathlib import Path
import cadquery as cq
import numpy as np
from model import Document,ModelError,new_feature,edge_reference
from geometry import new_sketch,base_frame,entity,identifier,profile_regions,face_reference
from references import body_reference,match_shape,resolve_body,shape_reference,ReferenceError
from solid_tools import face_ref

class BodyRecoveryTests(unittest.TestCase):
    def feature(self,kind,**values):return dict(kind=kind,id=identifier(),name=kind,enabled=True,**values)
    def base(self):
        features=[]
        for x,w,h in [(0,20,20),(50,12,10)]:
            s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[x,0],width=w,height=h)];r=profile_regions(s)[0]
            f=self.feature('extrude',source=dict(type='sketch',sketch=s['id'],entities=r['entities']),depth=20,operation='add');features += [s,f]
        return Document(features)
    def refs(self,d):
        bodies=d.solid.val().Solids();return [body_reference(b,i,len(bodies)) for i,b in enumerate(bodies)]
    def assertBodies(self,d,count):
        bodies=d.solid.val().Solids();self.assertEqual(len(bodies),count);self.assertTrue(all(b.isValid() for b in bodies));return bodies
    def test_move_copy_rotation_mirror_isolate_targets_and_persist(self):
        d=self.base();refs=self.refs(d);before=d.solid.val().Solids()[1]
        move=self.feature('body_move',targets=[refs[0]],dx=5,dy=3,dz=2,angle=0,copy=False)
        d.commit(d.features+[move]);bodies=self.assertBodies(d,2);np.testing.assert_allclose(bodies[0].Center().toTuple(),[5,3,12]);self.assertAlmostEqual(bodies[1].Volume(),before.Volume());self.assertEqual(bodies[1].Center().toTuple(),before.Center().toTuple())
        d.undo();copyf=self.feature('body_move',targets=[self.refs(d)[0]],dx=30,dy=0,dz=0,copy=True,angle=90,axis=dict(type='origin',axis='Z'))
        d.commit(d.features+[copyf]);self.assertBodies(d,3);self.assertAlmostEqual(d.solid.val().Solids()[-1].Center().x,30)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bodies.fcad';d.save(path);loaded=Document.load(path);self.assertBodies(loaded,3)
        d.undo();mirror=self.feature('body_mirror',targets=[self.refs(d)[1]],plane=dict(type='origin',plane='YZ'),keep_original=True);d.commit(d.features+[mirror]);bodies=self.assertBodies(d,3);self.assertAlmostEqual(bodies[-1].Center().x,-50)
    def test_rectangular_circular_patterns_counts_and_positions(self):
        d=self.base();f=self.feature('body_rectangular',targets=[self.refs(d)[0]],columns=3,rows=2,spacing_x=25,spacing_y=30,plane=dict(type='origin',plane='XY'))
        d.commit(d.features+[f]);b=self.assertBodies(d,7);centers={(round(s.Center().x),round(s.Center().y)) for s in b};self.assertIn((50,30),centers);self.assertIn((0,30),centers)
        d.undo();f=self.feature('body_circular',targets=[self.refs(d)[1]],count=4,angle=360,axis=dict(type='origin',axis='Z'));d.commit(d.features+[f]);b=self.assertBodies(d,5)
        for target in [(50,0),(0,50),(-50,0),(0,-50)]:self.assertTrue(any(np.linalg.norm(np.asarray(s.Center().toTuple())[:2]-target)<1e-6 for s in b))
        d.undo();f['angle']=180;f['count']=3;d.commit(d.features+[f]);self.assertBodies(d,4)
    def test_split_sides_and_unselected_body(self):
        d=self.base();f=self.feature('body_split',targets=[self.refs(d)[0]],plane=dict(type='frame',frame=dict(origin=[0,0,10],u=[1,0,0],normal=[0,0,1])),keep='both')
        d.commit(d.features+[f]);b=self.assertBodies(d,3);self.assertAlmostEqual(sum(s.Volume() for s in b),10400);self.assertTrue(any(abs(s.Center().z-5)<1e-6 for s in b))
        d.undo();f['keep']='positive';d.commit(d.features+[f]);b=self.assertBodies(d,2);self.assertAlmostEqual(b[0].BoundingBox().zmin,10)
        d.undo();f['keep']='negative';d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Solids()[0].BoundingBox().zmax,10)
    def test_combine_join_cut_intersect_and_keep_tools(self):
        for operation,expected in [('join',11200),('cut',3200),('intersect',4800)]:
            with self.subTest(operation=operation):
                d=self.base();copyf=self.feature('body_move',targets=[self.refs(d)[0]],dx=8,dy=0,dz=0,copy=True,angle=0);d.commit(d.features+[copyf]);refs=self.refs(d)
                f=self.feature('body_combine',targets=[refs[0]],tools=[refs[2]],operation=operation,keep_tools=False);d.commit(d.features+[f]);b=self.assertBodies(d,2)
                self.assertAlmostEqual(b[0].Volume(),expected,places=5);self.assertAlmostEqual(b[1].Volume(),2400,places=5)
                d.undo();f['keep_tools']=True;d.commit(d.features+[f]);self.assertBodies(d,3)
    def test_explicit_targets_invalid_patterns_and_booleans_transactional(self):
        d=self.base();before=copy.deepcopy(d.features)
        bad=self.feature('body_move',targets=[],dx=5)
        with self.assertRaisesRegex(ModelError,'explicitly'):d.commit(before+[bad])
        self.assertEqual(d.features,before);self.assertIsNotNone(d.pending_features)
        for f in [self.feature('body_rectangular',targets=[self.refs(d)[0]],columns=200,rows=200),self.feature('body_split',targets=[self.refs(d)[0]],plane=dict(type='frame',frame=dict(origin=[0,0,50],u=[1,0,0],normal=[0,0,1])),keep='both'),self.feature('body_combine',targets=[self.refs(d)[0]],tools=[self.refs(d)[1]],operation='join')]:
            with self.assertRaises(ModelError):d.commit(before+[f])
            self.assertEqual(d.features,before)
    def test_upstream_width_depth_recover_face_edge_body_and_downstream_features(self):
        d=self.base();first=d.solid.val().Solids()[0];top=max(first.Faces(),key=lambda face:face.Center().z)
        hole=self.feature('hole',plane=dict(type='face',face=face_reference(top,d.solid)),diameter=4,depth=6,x=0,y=0,hole_type='simple');d.commit(d.features+[hole])
        edge=next(e for e in d.solid.val().Solids()[0].Edges() if e.geomType()=='LINE' and abs(e.Center().z-10)<1e-6 and abs(e.Center().x-10)<1e-6)
        fillet=new_feature('fillet');fillet['edge_refs']=[edge_reference(edge,d.solid)];fillet['radius']=1;d.commit(d.features+[fillet])
        move=self.feature('body_move',targets=[self.refs(d)[0]],dx=0,dy=5,dz=0,angle=0,copy=False);d.commit(d.features+[move]);before=copy.deepcopy(d.features)
        changed=copy.deepcopy(d.features);changed[0]['entities'][0]['width']=30;changed[1]['depth']=25;d.commit(changed)
        b=self.assertBodies(d,2);self.assertAlmostEqual(b[0].BoundingBox().xmax,15,places=5);self.assertAlmostEqual(b[0].BoundingBox().zmax,25,places=5);self.assertAlmostEqual(b[1].Volume(),2400,places=5)
        report=d.inspect_history();self.assertTrue(any(r['state']=='recovered' for r in report));self.assertFalse(any(r['state']=='needs repair' for r in report))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'recovery.fcad';d.save(path);self.assertBodies(Document.load(path),2)
        d.undo();self.assertEqual(d.features,before);d.redo();self.assertAlmostEqual(d.solid.val().Solids()[0].BoundingBox().zmax,25)
    def test_ambiguous_references_fail_instead_of_guessing(self):
        a=cq.Workplane('XY').box(10,10,10).val();b=a.translate((20,0,0));result=cq.Workplane('XY').newObject([cq.Compound.makeCompound([a,b])])
        ref=dict(center=[10,0,5],normal=[0,0,1],area=100,geometry='PLANE')
        with self.assertRaisesRegex(ReferenceError,'ambiguous'):match_shape(result,ref,'face')
        body=body_reference(a);body['center']=[10,0,0]
        with self.assertRaisesRegex(ReferenceError,'ambiguous'):resolve_body(result,body)
    def test_reference_failure_retains_pending_upstream_edit_for_manual_repair(self):
        d=self.base();top=max(d.solid.val().Solids()[0].Faces(),key=lambda face:face.Center().z)
        shell=self.feature('shell',body=0,faces=[face_ref(top,d.solid)],thickness=-1);d.commit(d.features+[shell]);committed=copy.deepcopy(d.features)
        changed=copy.deepcopy(d.features);changed[-1]['faces'][0]['geometry']='SPHERE'
        with self.assertRaises(ModelError):d.commit(changed)
        self.assertEqual(d.features,committed);self.assertEqual(d.pending_features[-1]['faces'][0]['geometry'],'SPHERE')
        report=d.inspect_history(d.pending_features);self.assertEqual(report[-1]['state'],'needs repair')
        repaired=copy.deepcopy(d.pending_features);prefix=Document(repaired[:-1]);top=max(prefix.solid.val().Solids()[0].Faces(),key=lambda face:face.Center().z)
        repaired[-1]['faces'][0]=face_ref(top,prefix.solid);d.commit(repaired);self.assertIsNone(d.pending_features)
