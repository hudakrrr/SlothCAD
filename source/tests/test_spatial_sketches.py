import unittest,math,copy
from geometry import identifier
from model import Document,ModelError
from references import shape_reference
from spatial_sketch import wire

class SpatialTests(unittest.TestCase):
    def feature(self,kind,**kw):return dict(id=identifier(),kind=kind,name=kind,enabled=True,**kw)
    def curve(self,kind,points,**kw):return dict(id=identifier(),kind=kind,points=points,**kw)
    def test_3d_path_pipe_and_planar_profile(self):
        e=self.curve('spline',[[0,0,0],[5,2,5],[8,8,10],[20,10,12]])
        s=self.feature('sketch3d',entities=[e]);p=self.feature('pipe',path=dict(sketch=s['id'],entities=[e['id']]),diameter=1,operation='new');d=Document([s,p]);self.assertTrue(d.solid.val().isValid());self.assertGreater(d.solid.val().Volume(),10)
        pts=[[0,0,0],[10,0,0],[10,5,0],[0,5,0]];es=[self.curve('line',[a,b]) for a,b in zip(pts,pts[1:]+pts[:1])];s=self.feature('sketch3d',entities=es);f=self.feature('extrude',source=dict(type='sketch',sketch=s['id'],entities=[e['id'] for e in es]),depth=3,operation='add');d=Document([s,f]);self.assertAlmostEqual(d.solid.val().Volume(),150)
    def test_exact_curve_on_cylinder_and_associative_radius(self):
        base=self.feature('primitive',shape='cylinder',radius=5,height=10,operation='new');d=Document([base]);face=next(f for f in d.solid.val().Faces() if f.geomType()=='CYLINDER');ref=shape_reference(face,'face',d.solid)
        e=self.curve('line',[[0,2],[math.pi,2]]);s=self.feature('surface_sketch',face=ref,entities=[e]);d.commit(d.features+[s]);curve=d.frames[s['id']]['edges'][e['id']];self.assertAlmostEqual(curve.Length(),math.pi*5,places=5)
        for t in (.1,.4,.8):p=curve.positionAt(t);self.assertAlmostEqual(math.hypot(p.x,p.y),5,places=5);self.assertAlmostEqual(p.z,2,places=5)
        changed=copy.deepcopy(d.features);changed[0]['radius']=7;d.commit(changed);self.assertAlmostEqual(d.frames[s['id']]['edges'][e['id']].Length(),math.pi*7,places=5)
    def test_uv_arc_spline_point_and_invalid_3d_are_atomic(self):
        base=self.feature('primitive',shape='cylinder',radius=5,height=10,operation='new');d=Document([base]);face=next(f for f in d.solid.val().Faces() if f.geomType()=='CYLINDER')
        entities=[self.curve('arc',[[0,1],[1,2],[2,1]]),self.curve('spline',[[0,3],[1,4],[2,3]]),self.curve('point',[[1,5]])];s=self.feature('surface_sketch',face=shape_reference(face,'face',d.solid),entities=entities);d.commit(d.features+[s]);self.assertEqual(len(d.frames[s['id']]['edges']),3)
        with self.assertRaises(ModelError):d.commit(d.features+[self.feature('sketch3d',entities=[self.curve('line',[[0,0,0],[0,0,0]])])])
    def test_move_3d_path_updates_pipe_and_surface_reference_recovers(self):
        e=self.curve('line',[[0,0,0],[0,0,10]]);s=self.feature('sketch3d',entities=[e]);move=self.feature('sketch_move',sketch=s['id'],dx=20,dy=3,dz=0);pipe=self.feature('pipe',path=dict(sketch=s['id'],entities=[e['id']]),diameter=2,operation='new');d=Document([s,move,pipe]);self.assertAlmostEqual(d.solid.val().BoundingBox().xmin,19);self.assertAlmostEqual(d.solid.val().Center().y,3)
        from solid_tools import axis_reference
        import numpy as np
        origin,direction=axis_reference(dict(type='sketch_line',sketch=s['id'],entity=e['id']),d.solid,d.sketches,d.frames);np.testing.assert_allclose(origin,[20,3,0]);np.testing.assert_allclose(direction,[0,0,1])
        from geometry import new_sketch,base_frame,entity,profile_regions
        from references import surface_reference
        source=new_sketch(base_frame('XY'));source['entities']=[entity('rectangle',center=[0,0],width=10,height=5)];patch=self.feature('surface_patch',source=dict(type='sketch',sketch=source['id'],entities=profile_regions(source)[0]['entities']));d=Document([source,patch]);face=d.frames['_surfaces'][patch['id']]['shape'].Faces()[0];ref=surface_reference(face,'face',patch['id'],d.frames)
        e=self.curve('line',[[0,0],[1,1]]);uv=self.feature('surface_sketch',face=ref,entities=[e]);d.commit(d.features+[uv]);changed=copy.deepcopy(d.features);changed[0]['frame']['origin'][2]=100;d.commit(changed);self.assertAlmostEqual(d.frames[uv['id']]['edges'][e['id']].Center().z,100);self.assertEqual(d.inspect_history()[-1]['state'],'recovered')

if __name__=='__main__':unittest.main()
