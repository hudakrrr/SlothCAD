import unittest,math,copy
from model import Document,ModelError
from geometry import identifier,new_sketch,base_frame,entity
from references import body_reference

class SpecialTests(unittest.TestCase):
    def feature(self,kind,**kw):return dict(id=identifier(),kind=kind,name=kind,**kw)
    def test_primitives_exact_volume_and_validation(self):
        expected={'box':1000,'cylinder':math.pi*25*10,'sphere':4/3*math.pi*125,'cone':math.pi*25*10/3,'torus':2*math.pi**2*5}
        for shape,volume in expected.items():
            d=Document([self.feature('primitive',shape=shape,operation='new',width=10,length=10,height=10,radius=5,minor_radius=1)]);self.assertAlmostEqual(d.solid.val().Volume(),volume,places=4)
        with self.assertRaises(ModelError):Document([self.feature('primitive',shape='cone',radius=5,top_radius=-1)])
    def test_pipe_hollow_coil_and_turn_guard(self):
        s=new_sketch(base_frame('XZ'));s['entities']=[entity('line',a=[0,0],b=[0,20])];path=dict(sketch=s['id'],entities=[s['entities'][0]['id']])
        d=Document([s,self.feature('pipe',path=path,diameter=4,hollow=True,thickness=1,operation='new')]);self.assertAlmostEqual(d.solid.val().Volume(),math.pi*3*20,places=4)
        d=Document([self.feature('coil',radius=5,pitch=3,height=9,diameter=1,operation='new')]);self.assertTrue(d.solid.val().isValid());self.assertGreater(d.solid.val().Volume(),50)
        with self.assertRaisesRegex(ModelError,'200'):Document([self.feature('coil',radius=5,pitch=.01,height=10,diameter=.005)])
    def test_rib_web_explicit_target_and_thread_groove(self):
        for kind in ('rib','web'):
            base=self.feature('primitive',shape='box',width=10,length=10,height=5,operation='new');d=Document([base]);s=new_sketch(base_frame('XY'));s['frame']['origin'][2]=4;s['entities']=[entity('line',a=[1,5],b=[9,5])];ref=body_reference(d.solid.val().Solids()[0],0,1,d.solid)
            f=self.feature(kind,path=dict(sketch=s['id'],entities=[s['entities'][0]['id']]),thickness=1,height=5,targets=[ref],operation='join');d.commit(d.features+[s,f]);self.assertGreater(d.solid.val().Volume(),500);self.assertEqual(len(d.solid.val().Solids()),1)
        base=self.feature('primitive',shape='cylinder',radius=5,height=10,operation='new');d=Document([base]);volume=d.solid.val().Volume();ref=body_reference(d.solid.val().Solids()[0],0,1,d.solid)
        f=self.feature('thread',radius=5,height=9,pitch=2,thread_depth=.6,thread_width=1.2,targets=[ref],axis=dict(type='origin',axis='Z'));d.commit(d.features+[f]);self.assertLess(d.solid.val().Volume(),volume);self.assertTrue(d.solid.val().isValid())
        changed=copy.deepcopy(d.features);changed[1]['thread_width']=2
        with self.assertRaises(ModelError):d.commit(changed)
    def test_long_external_and_internal_threads_cut(self):
        # One swept groove of 12.5 turns made the boolean return nothing ("misses the target").
        for shape,thread_type in (('cylinder','external'),('box','internal')):
            base=self.feature('primitive',shape=shape,radius=8,height=25,width=30,length=30,origin=[-15,-15,0] if shape=='box' else [0,0,0],operation='new')
            d=Document([base])
            if shape=='box':
                hole=self.feature('primitive',shape='cylinder',radius=8,height=25,operation='cut',targets=[body_reference(d.solid.val().Solids()[0],0,1,d.solid)]);d.commit(d.features+[hole])
            volume=d.solid.val().Volume();ref=body_reference(d.solid.val().Solids()[0],0,1,d.solid)
            f=self.feature('thread',radius=8,height=25,pitch=2,thread_depth=1.2,thread_width=1.2,thread_type=thread_type,targets=[ref],axis=dict(type='origin',axis='Z'))
            d.commit(d.features+[f]);solid=d.solid.val()
            self.assertTrue(solid.isValid());self.assertEqual(len(solid.Solids()),1)
            self.assertGreater(abs(solid.Volume()-volume),300,thread_type)

if __name__=='__main__':unittest.main()
