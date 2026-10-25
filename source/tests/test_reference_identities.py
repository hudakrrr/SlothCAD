import copy,unittest
import numpy as np
from model import Document,ModelError
from geometry import new_sketch,base_frame,entity,identifier,profile_regions
from references import body_reference,resolve_body,shape_reference,match_shape,ReferenceError

class IdentityTests(unittest.TestCase):
    def test_rotation_never_silently_substitutes_a_geometrically_similar_face(self):
        d=self.model();body=d.solid.val();face=max(body.Faces(),key=lambda f:f.Center().x);reference=shape_reference(face,'face',d.solid)
        move=dict(id=identifier(),kind='body_move',name='Rotate',targets=[body_reference(body,0,1,d.solid)],angle=180,dx=0,dy=0,dz=0,copy=False,axis=dict(type='origin',axis='Z'));d.commit(d.features+[move])
        with self.assertRaisesRegex(ReferenceError,'orientation changed'):match_shape(d.solid,reference,'face')
        current=shape_reference(max(d.solid.val().Faces(),key=lambda f:f.Center().x),'face',d.solid);self.assertEqual(match_shape(d.solid,current,'face')[1],'matched')
        from topology import orientation_key
        self.assertEqual(orientation_key('',('rotate',180,[0,0,1])),orientation_key('',('rotate',180.,[0.,0.,1.])))
        from geometry import new_sketch,frame_on_face,sketch_frame,axes
        face=max(d.solid.val().Faces(),key=lambda f:f.Center().x);s=new_sketch(frame_on_face(face));s['support']=current;s['frame']['normal']=[0,0,1];s['frame']['u']=[1,0,0]
        self.assertGreater(abs(axes(sketch_frame(s,d.solid))[3]@np.asarray(face.normalAt().toTuple())),.999999)
    def model(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
        f=dict(kind='extrude',id=identifier(),name='Block',enabled=True,source=dict(type='sketch',sketch=s['id'],entities=profile_regions(s)[0]['entities']),depth=8,operation='add')
        return Document([s,f])
    def test_large_upstream_move_keeps_body_face_and_edge_identity(self):
        d=self.model();body=d.solid.val();ref=body_reference(body,0,1,d.solid)
        face=max(body.Faces(),key=lambda x:x.Center().z);face_ref=shape_reference(face,'face',d.solid)
        edge=max(body.Edges(),key=lambda x:x.Center().z);edge_ref=shape_reference(edge,'edge',d.solid)
        changed=copy.deepcopy(d.features);changed[0]['entities'][0]['center']=[500,800];d.commit(changed)
        self.assertAlmostEqual(resolve_body(d.solid,ref)[1].Center().x,500)
        self.assertAlmostEqual(match_shape(d.solid,face_ref,'face')[0].Center().x,500)
        self.assertGreater(match_shape(d.solid,edge_ref,'edge')[0].Center().y,790)
    def test_missing_identity_never_substitutes_a_nearby_body(self):
        d=self.model();ref=body_reference(d.solid.val(),0,1,d.solid);ref['body_id']='removed:body:0'
        with self.assertRaisesRegex(ReferenceError,'identity is missing'):resolve_body(d.solid,ref)
    def test_invalid_nan_reference_is_rejected(self):
        d=self.model();ref=body_reference(d.solid.val());ref['center']=[float('nan'),0,0]
        with self.assertRaises(ReferenceError):resolve_body(d.solid,ref)
    def test_body_preferences_follow_large_translation(self):
        d=self.model();d.display={'materials':{'0':{'color':'#aa2244','finish':'metallic'}}}
        changed=copy.deepcopy(d.features);changed[0]['entities'][0]['center']=[500,0];d.commit(changed)
        self.assertEqual(d.display['materials']['0']['color'],'#aa2244');d.undo();self.assertEqual(d.display['materials']['0']['color'],'#aa2244')
