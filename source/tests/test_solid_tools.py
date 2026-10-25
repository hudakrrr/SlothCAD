import copy,math,tempfile,unittest
from pathlib import Path
import cadquery as cq
import numpy as np
from model import Document,ModelError
from geometry import entity,new_sketch,base_frame,identifier,profile_regions,face_reference
from solid_tools import face_ref

class SolidToolTests(unittest.TestCase):
    def sketch(self,plane='XY',origin=None,entities=None):
        f=base_frame(plane)
        if origin:f['origin']=origin
        s=new_sketch(f);s['entities']=entities or [entity('rectangle',center=[0,0],width=20,height=20)];return s
    def feature(self,kind,**values):return dict(kind=kind,id=identifier(),name=kind,enabled=True,**values)
    def source(self,s):
        r=profile_regions(s)[0];return dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested')
    def base(self):
        s=self.sketch();f=self.feature('extrude',source=self.source(s),depth=20,operation='add');return [s,f]
    def assertSolid(self,features):
        d=Document(features);self.assertTrue(d.solid.val().isValid());self.assertGreater(d.solid.val().Volume(),0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'feature.fcad';d.save(path);loaded=Document.load(path)
            self.assertTrue(loaded.solid.val().isValid());self.assertAlmostEqual(loaded.solid.val().Volume(),d.solid.val().Volume(),places=4)
        return d
    def test_construction_offset_angled_midplane_three_point_axis_and_sketch_reference(self):
        off=self.feature('construction_plane',mode='offset',reference=dict(type='origin',plane='XY'),offset=10)
        angle=self.feature('construction_plane',mode='angled',reference=dict(type='origin',plane='XY'),axis=dict(type='origin',axis='X'),angle=45)
        mid=self.feature('construction_plane',mode='midplane',reference=dict(type='origin',plane='XY'),second=dict(type='construction',id=off['id']))
        three=self.feature('construction_plane',mode='three points',p1=[1,2,3],p2=[11,2,3],p3=[1,12,3])
        axis=self.feature('construction_axis',reference=dict(type='points',start=[1,2,3],end=[1,2,13]))
        s=self.sketch();s['plane_ref']=dict(type='construction',id=mid['id']);ex=self.feature('extrude',source=self.source(s),depth=2,operation='add')
        d=self.assertSolid([off,angle,mid,three,axis,s,ex])
        np.testing.assert_allclose(d.frames[mid['id']]['origin'],[0,0,5]);self.assertAlmostEqual(d.solid.val().BoundingBox().zmin,5)
        self.assertTrue(d.frames[axis['id']]['axis']);self.assertAlmostEqual(d.frames[angle['id']]['normal'][1],-math.sqrt(.5))
        changed=copy.deepcopy(d.features);changed[0]['offset']=16;d.commit(changed);self.assertAlmostEqual(d.solid.val().BoundingBox().zmin,8)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'new.fcad';d.save(path);loaded=Document.load(path);self.assertEqual(loaded.features,d.features)
    def test_invalid_construction_inputs_transactional(self):
        d=Document();bad=self.feature('construction_plane',mode='three points',p1=[0,0,0],p2=[1,0,0],p3=[2,0,0])
        with self.assertRaises(ModelError):d.commit([bad])
        self.assertEqual(d.features,[])
        bad=self.feature('construction_plane',mode='midplane',reference=dict(type='origin',plane='XY'),second=dict(type='origin',plane='XZ'))
        with self.assertRaises(ModelError):Document([bad])
    def test_revolve_full_partial_and_axis_reference(self):
        s=self.sketch('XZ',entities=[entity('rectangle',center=[10,0],width=4,height=10)])
        axis=self.feature('construction_axis',reference=dict(type='origin',axis='Z'))
        f=self.feature('revolve',source=self.source(s),axis=dict(type='construction',id=axis['id']),angle=360,operation='add')
        d=self.assertSolid([axis,s,f]);self.assertAlmostEqual(d.solid.val().Volume(),math.pi*(12**2-8**2)*10,places=4)
        f['angle']=180;d=self.assertSolid([axis,s,f]);self.assertAlmostEqual(d.solid.val().Volume(),math.pi*(12**2-8**2)*5,places=4)
    def test_sweep_path_and_loft_with_inner_loops(self):
        s=self.sketch(entities=[entity('circle',center=[0,0],radius=2)])
        path=self.sketch('XZ',entities=[entity('line',a=[0,0],b=[0,20])])
        f=self.feature('sweep',source=self.source(s),path=dict(sketch=path['id'],entities=[path['entities'][0]['id']]),operation='add')
        d=self.assertSolid([s,path,f]);self.assertAlmostEqual(d.solid.val().Volume(),math.pi*4*20,places=4)
        a=self.sketch(entities=[entity('circle',center=[0,0],radius=5),entity('circle',center=[0,0],radius=2)])
        b=self.sketch(origin=[0,0,10],entities=[entity('circle',center=[0,0],radius=8),entity('circle',center=[0,0],radius=3)])
        def ring(s):
            r=max(profile_regions(s),key=lambda r:len(r['holes']));return dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested')
        f=self.feature('loft',sections=[ring(a),ring(b)],operation='add',ruled=False);d=self.assertSolid([a,b,f])
        expected=math.pi*10/3*(25+40+64-4-6-9);self.assertAlmostEqual(d.solid.val().Volume(),expected,places=3)
    def test_shell_open_and_closed_and_draft(self):
        base=self.base();d=Document(base);top=max(d.solid.val().Faces(),key=lambda face:face.Center().z)
        shell=self.feature('shell',body=0,faces=[face_ref(top)],thickness=-1);hollow=self.assertSolid(base+[shell]);self.assertLess(hollow.solid.val().Volume(),d.solid.val().Volume())
        shell['faces']=[];self.assertSolid(base+[shell])
        sides=[face_ref(f) for f in d.solid.val().Faces() if abs(f.normalAt().z)<.1]
        draft=self.feature('draft',body=0,faces=sides,angle=3,neutral=dict(type='origin',plane='XY'))
        drafted=self.assertSolid(base+[draft]);self.assertLess(drafted.solid.val().Volume(),d.solid.val().Volume())
    def test_simple_counterbore_countersink_and_through_holes(self):
        base=self.base();d=Document(base);top=max(d.solid.val().Faces(),key=lambda face:face.Center().z)
        for kind in ('simple','counterbore','countersink'):
            with self.subTest(kind=kind):
                f=self.feature('hole',plane=dict(type='face',face=face_reference(top)),x=0,y=0,diameter=4,depth=10,hole_type=kind,head_diameter=8,head_depth=3,head_angle=90)
                hole=self.assertSolid(base+[f]);self.assertLess(hole.solid.val().Volume(),d.solid.val().Volume());self.assertGreater(hole.solid.val().Volume(),7000)
        f['through_all']=True;self.assertSolid(base+[f]);f['x']=100
        with self.assertRaises(ModelError):Document(base+[f])
    def test_symmetric_through_all_to_object_and_taper_preserve_holes(self):
        s=self.sketch();f=self.feature('extrude',source=self.source(s),depth=10,direction='symmetric',operation='add')
        d=self.assertSolid([s,f]);self.assertAlmostEqual(d.solid.val().BoundingBox().zmin,-5);self.assertAlmostEqual(d.solid.val().BoundingBox().zmax,5)
        target=self.feature('construction_plane',mode='offset',offset=17,reference=dict(type='origin',plane='XY'))
        f.update(extent='to object',target=dict(type='construction',id=target['id']),direction='one side');d=self.assertSolid([target,s,f]);self.assertAlmostEqual(d.solid.val().BoundingBox().zmax,17)
        base=self.base();hole=self.sketch(origin=[0,0,25],entities=[entity('circle',center=[0,0],radius=2)])
        cut=self.feature('extrude',source=self.source(hole),depth=-1,extent='through all',operation='cut')
        d=self.assertSolid(base+[hole,cut]);self.assertAlmostEqual(d.solid.val().Volume(),8000-math.pi*4*20,places=4)
        ring=self.sketch(entities=[entity('rectangle',center=[0,0],width=20,height=20),entity('circle',center=[0,0],radius=2)])
        r=max(profile_regions(ring),key=lambda r:len(r['holes']));source=dict(type='sketch',sketch=ring['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested')
        taper=self.feature('extrude',source=source,depth=10,taper=3,operation='add');d=self.assertSolid([ring,taper])
        center=cq.Solid.makeCylinder(1,10,(0,0,0));self.assertAlmostEqual(d.solid.val().intersect(center).Volume(),0,places=7)
        taper['direction']='symmetric';d=self.assertSolid([ring,taper]);self.assertAlmostEqual(d.solid.val().BoundingBox().zmin,-5,places=5)
    def test_oblique_and_negative_to_object_limits_and_disconnected_sweep_rejected(self):
        s=self.sketch(entities=[entity('circle',center=[0,0],radius=2)])
        frame=dict(origin=[0,0,10],u=[1,0,0],normal=[0,.2,1])
        f=self.feature('extrude',source=self.source(s),depth=1,extent='to object',target=dict(type='frame',frame=frame),operation='add')
        d=self.assertSolid([s,f]);box=d.solid.val().BoundingBox();self.assertAlmostEqual(box.zmax,10.4,places=5)
        f['depth']=-1;f['target']['frame']['origin']=[0,0,-10];d=self.assertSolid([s,f]);self.assertAlmostEqual(d.solid.val().BoundingBox().zmin,-10.4,places=5)
        path=self.sketch('XZ',entities=[entity('line',a=[0,0],b=[0,10]),entity('line',a=[0,15],b=[0,20])])
        sweep=self.feature('sweep',source=self.source(s),path=dict(sketch=path['id'],entities=[e['id'] for e in path['entities']]),operation='add')
        with self.assertRaises(ModelError):Document([s,path,sweep])

    def test_new_tools_save_load_undo_redo_and_invalid_inputs(self):
        base=self.base();d=Document(base);top=max(d.solid.val().Faces(),key=lambda face:face.Center().z)
        shell=self.feature('shell',body=0,faces=[face_ref(top)],thickness=-1);d.commit(base+[shell]);volume=d.solid.val().Volume()
        d.undo();self.assertAlmostEqual(d.solid.val().Volume(),8000);d.redo();self.assertAlmostEqual(d.solid.val().Volume(),volume)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shell.fcad';d.save(path);self.assertAlmostEqual(Document.load(path).solid.val().Volume(),volume)
        bad=copy.deepcopy(shell);bad['thickness']=-100;before=copy.deepcopy(d.features)
        with self.assertRaises(ModelError):d.commit(base+[bad])
        self.assertEqual(d.features,before)
        with self.assertRaises(ModelError):Document([self.feature('loft',sections=[],operation='add')])
