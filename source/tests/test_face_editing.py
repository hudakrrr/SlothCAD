import copy,unittest
from model import Document,ModelError
from geometry import new_sketch,entity,base_frame,profile_regions,identifier
from references import body_reference,shape_reference

class FaceEditingTests(unittest.TestCase):
    def base(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
        e=dict(id=identifier(),kind='extrude',name='Block',source=dict(type='sketch',sketch=s['id'],entities=profile_regions(s)[0]['entities']),depth=5,operation='add')
        return Document([s,e])
    def feature(self,d,kind,**kw):
        b=d.solid.val().Solids()[0];face=max(b.Faces(),key=lambda f:f.Center().z)
        return dict(id=identifier(),kind=kind,name=kind,targets=[body_reference(b,0,1,d.solid)],faces=[shape_reference(face,'face',d.solid)],**kw)
    def test_offset_and_press_pull_signed_and_upstream_edit(self):
        for kind in ('press_pull','offset_face'):
            for distance in (-2,2):
                d=self.base();d.commit(d.features+[self.feature(d,kind,distance=distance)])
                self.assertAlmostEqual(d.solid.val().Volume(),200*(5+distance),places=4)
                candidate=copy.deepcopy(d.features);candidate[0]['entities'][0]['width']=25;d.commit(candidate)
                self.assertAlmostEqual(d.solid.val().Volume(),250*(5+distance),places=4)
    def test_scale_pivot_volume_and_undo(self):
        d=self.base();d.commit(d.features+[self.feature(d,'scale',factor=2,pivot=[10,0,0])]);self.assertAlmostEqual(d.solid.val().Volume(),8000)
        self.assertAlmostEqual(d.solid.val().BoundingBox().xmin,-30);d.undo();self.assertAlmostEqual(d.solid.val().Volume(),1000)
    def test_press_pull_profile_creates_first_body_and_split_open_path(self):
        d=self.base();source=d.features[1]['source'];f=dict(id=identifier(),kind='press_pull',name='Profile pull',press_type='profile',source=source,distance=3,operation='new')
        first=Document([d.features[0],f]);self.assertAlmostEqual(first.solid.val().Volume(),600)
        s=new_sketch(base_frame('XY'));s['frame']['origin'][2]=5;s['entities']=[entity('line',a=[0,-5],b=[0,5])]
        f=self.feature(d,'split_face',source=dict(type='path',sketch=s['id'],entities=[s['entities'][0]['id']]));d.commit(d.features+[s,f]);self.assertEqual(len(d.solid.val().Faces()),7);self.assertAlmostEqual(d.solid.val().Volume(),1000)
    def test_multi_body_scale_keeps_each_explicit_identity(self):
        from references import resolve_body
        d=self.base();d.commit(d.features+[dict(id=identifier(),kind='primitive',name='Second',shape='box',width=3,length=3,height=3,origin=[50,0,0],operation='new')]);refs=[body_reference(b,i,2,d.solid) for i,b in enumerate(d.solid.val().Solids())]
        d.commit(d.features+[dict(id=identifier(),kind='scale',name='Scale both',targets=refs,factor=2,pivot=[0,0,0])]);self.assertAlmostEqual(resolve_body(d.solid,refs[0])[1].Volume(),8000);self.assertAlmostEqual(resolve_body(d.solid,refs[1])[1].Volume(),216)
    def test_split_face_keeps_volume_and_adds_faces(self):
        d=self.base();s=new_sketch(base_frame('XY'));s['frame']['origin'][2]=5;s['entities']=[entity('circle',center=[0,0],radius=2)]
        f=self.feature(d,'split_face',source=dict(type='sketch',sketch=s['id'],entities=profile_regions(s)[0]['entities']));d.commit(d.features+[s,f]);self.assertEqual(len(d.solid.val().Faces()),7);self.assertAlmostEqual(d.solid.val().Volume(),1000)
    def test_replace_face_and_invalid_edit_are_atomic(self):
        d=self.base();f=self.feature(d,'replace_face',replacement=dict(type='frame',frame=dict(origin=[0,0,7],u=[1,0,0],normal=[0,0,1])));d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),1400)
        before=copy.deepcopy(d.features);bad=self.feature(d,'offset_face',distance=-100)
        with self.assertRaises(ModelError):d.commit(d.features+[bad])
        self.assertEqual(d.features,before);self.assertAlmostEqual(d.solid.val().Volume(),1400)

if __name__=='__main__':unittest.main()
