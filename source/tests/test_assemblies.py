import copy,tempfile,unittest
from pathlib import Path
from geometry import identifier
from model import Document,ModelError
from assemblies import components,validate_tree
from references import body_reference,resolve_body

class AssemblyTests(unittest.TestCase):
    def feature(self,kind,**kw):return dict(id=identifier(),kind=kind,name=kind,enabled=True,**kw)
    def component(self,x=0,children=None):return self.feature('component',features=children if children is not None else [self.feature('primitive',shape='box',width=2,length=2,height=2,operation='new')],pose=dict(origin=[x,0,0],axis=[0,0,1],angle=0))
    def test_nested_components_separate_histories_upstream_edit_and_save(self):
        child=self.component(3);parent=self.component(10,[child]);d=Document([parent]);self.assertAlmostEqual(d.solid.val().BoundingBox().xmin,13);self.assertEqual(len(components(d.frames)),1)
        ref=body_reference(d.solid.val().Solids()[0],0,1,d.solid);changed=copy.deepcopy(d.features);changed[0]['features'][0]['features'][0]['width']=4;d.commit(changed);self.assertAlmostEqual(d.solid.val().Volume(),16);resolve_body(d.solid,ref)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'assembly.fcad';d.save(p);loaded=Document.load(p);self.assertAlmostEqual(loaded.solid.val().Volume(),16);self.assertEqual(loaded.features,d.features)
        d.undo();self.assertAlmostEqual(d.solid.val().Volume(),8)
    def test_joint_motion_limits_grounding_and_identity(self):
        a=self.component();b=self.component(10);b['grounded']=True;d=Document([a,b]);ref=body_reference(d.solid.val().Solids()[0],0,2,d.solid)
        joint=self.feature('joint',moving=a['id'],fixed=b['id'],joint_type='slider',direction=[1,0,0],anchor=[0,0,0],value=3,minimum=0,maximum=5);d.commit(d.features+[joint]);self.assertAlmostEqual(resolve_body(d.solid,ref)[1].BoundingBox().xmin,3)
        changed=copy.deepcopy(d.features);changed[-1]['value']=6
        with self.assertRaisesRegex(ModelError,'limits'):d.commit(changed)
        changed=copy.deepcopy(d.features);changed[-1].update(moving=b['id'],fixed=a['id'])
        with self.assertRaisesRegex(ModelError,'Unground'):d.commit(changed)
        d.undo();joint.update(fixed=None,direction=[0,0,1],joint_type='revolute',value=90,minimum=-180,maximum=180);d.commit(d.features+[joint]);self.assertAlmostEqual(resolve_body(d.solid,ref)[1].BoundingBox().xmin,-2,places=5)
    def test_invalid_nested_identity_and_joint_feedback(self):
        a=self.component();a['features']=[dict(a)]
        with self.assertRaisesRegex(ModelError,'cycle'):validate_tree([a])
        d=Document([self.component()]);j=self.feature('joint',moving='gone',fixed=None)
        with self.assertRaisesRegex(ModelError,'missing'):d.commit(d.features+[j])

if __name__=='__main__':unittest.main()
