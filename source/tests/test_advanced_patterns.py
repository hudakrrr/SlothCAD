import copy,unittest
from model import Document,ModelError
from geometry import new_sketch,entity,base_frame,profile_regions,identifier
from references import body_reference,shape_reference

class PatternTests(unittest.TestCase):
    def source(self,s):return dict(type='sketch',sketch=s['id'],entities=profile_regions(s)[0]['entities'])
    def block_with_boss(self):
        a=new_sketch(base_frame('XY'));a['entities']=[entity('rectangle',center=[0,0],width=50,height=30)]
        b=new_sketch(base_frame('XY'));b['frame']['origin'][2]=5;b['entities']=[entity('circle',center=[-15,0],radius=2)]
        ex=lambda s,z:dict(id=identifier(),kind='extrude',name='Extrude',source=self.source(s),depth=z,operation='add')
        return Document([a,ex(a,5),b,ex(b,3)])
    def pattern(self,d,kind,**kw):
        b=d.solid.val().Solids()[0]
        return dict(id=identifier(),kind=kind,name=kind,targets=[body_reference(b,0,1,d.solid)],features=[d.features[3]['id']],object_type='features',plane=dict(type='origin',plane='XY'),axis=dict(type='origin',axis='Z'),**kw)
    def test_feature_array_updates_upstream_and_undo(self):
        d=self.block_with_boss();f=self.pattern(d,'feature_rectangular',columns=3,rows=1,spacing_x=15,spacing_y=10);d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),7500+3*3.141592653589793*4*3,places=5)
        changed=copy.deepcopy(d.features);changed[3]['depth']=4;d.commit(changed);self.assertAlmostEqual(d.solid.val().Volume(),7500+3*3.141592653589793*4*4,places=5);d.undo();self.assertAlmostEqual(d.solid.val().Volume(),7500+3*3.141592653589793*4*3,places=5)
    def test_feature_mirror_circular_and_cut_patterns(self):
        d=self.block_with_boss();f=self.pattern(d,'feature_mirror');f['plane']=dict(type='origin',plane='YZ');d.commit(d.features+[f]);self.assertEqual(len(d.solid.val().Solids()),1);self.assertAlmostEqual(d.solid.val().Volume(),7500+2*3.141592653589793*4*3,places=4)
        d=self.block_with_boss();f=self.pattern(d,'feature_circular',count=2,angle=360);d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),7500+2*3.141592653589793*4*3,places=4)
        d=self.block_with_boss();changed=copy.deepcopy(d.features);changed[2]['frame']['origin'][2]=0;changed[3].update(depth=5,operation='cut');d.commit(changed);f=self.pattern(d,'feature_rectangular',columns=3,rows=1,spacing_x=15,spacing_y=10);d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),7500-3*3.141592653589793*4*5,places=4)
    def test_faces_pattern_heals_boss(self):
        d=self.block_with_boss();f=self.pattern(d,'feature_rectangular',columns=2,rows=1,spacing_x=15,spacing_y=10);f['object_type']='faces';f['faces']=[shape_reference(face,'face',d.solid) for face in d.solid.val().Faces() if face.Center().z>5+1e-6];d.commit(d.features+[f]);self.assertAlmostEqual(d.solid.val().Volume(),7500+2*3.141592653589793*4*3,places=4)
    def test_path_body_pattern_and_missing_feature_atomic(self):
        d=self.block_with_boss();p=new_sketch(base_frame('XY'));p['entities']=[entity('line',a=[0,0],b=[100,0])]
        f=self.pattern(d,'path_pattern',count=3,path=dict(sketch=p['id'],entities=[p['entities'][0]['id']]));f['object_type']='bodies';d.commit(d.features+[p,f]);self.assertEqual(len(d.solid.val().Solids()),3)
        before=copy.deepcopy(d.features);f=self.pattern(d,'feature_rectangular',columns=2,rows=1,spacing_x=15,spacing_y=10);f['features']=['missing']
        with self.assertRaisesRegex(ModelError,'missing'):d.commit(d.features+[f])
        self.assertEqual(d.features,before)

if __name__=='__main__':unittest.main()
