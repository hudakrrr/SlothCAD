import unittest,math,tempfile
from pathlib import Path
from geometry import new_sketch,base_frame,entity,profile_regions,identifier
from model import Document,ModelError
from surface_tools import bodies,scene
from workspace import prepare_scene_mesh

class SurfaceTests(unittest.TestCase):
    def sketch(self,kind='rectangle',z=0):
        s=new_sketch(base_frame('XY'));s['frame']['origin'][2]=z;s['entities']=[entity('rectangle',center=[0,0],width=10,height=5) if kind=='rectangle' else entity('line',a=[5,0],b=[5,10])];return s
    def source(self,s):
        if s['entities'][0]['kind']=='line':return dict(type='path',sketch=s['id'],entities=[s['entities'][0]['id']])
        return dict(type='sketch',sketch=s['id'],entities=profile_regions(s)[0]['entities'])
    def feature(self,kind,**kw):return dict(id=identifier(),kind=kind,name=kind,enabled=True,**kw)
    def test_surface_extrude_revolve_sweep_loft_are_not_solids(self):
        s=self.sketch();f=self.feature('surface_extrude',source=self.source(s),vector=[0,0,10]);d=Document([s,f]);self.assertIsNone(d.solid);self.assertAlmostEqual(bodies(d.frames)[f['id']]['shape'].Area(),300)
        mesh=prepare_scene_mesh(scene(d.solid,d.frames));self.assertEqual(len(mesh['faces']),4);self.assertGreater(len(mesh['triangles']),0)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'surface.fcad';d.save(p);self.assertEqual(len(bodies(Document.load(p).frames)),1)
        s=self.sketch('line');f=self.feature('surface_revolve',source=self.source(s),axis=dict(type='origin',axis='Y'),angle=360);d=Document([s,f]);self.assertAlmostEqual(bodies(d.frames)[f['id']]['shape'].Area(),math.pi*100,places=5)
        a=self.sketch('line');p=new_sketch(base_frame('XZ'));p['entities']=[entity('line',a=[5,0],b=[5,10])];f=self.feature('surface_sweep',source=self.source(a),path=dict(sketch=p['id'],entities=[p['entities'][0]['id']]));d=Document([a,p,f]);self.assertGreater(bodies(d.frames)[f['id']]['shape'].Area(),0)
        a=self.sketch(z=0);b=self.sketch(z=10);f=self.feature('surface_loft',sections=[self.source(a),self.source(b)],ruled=True);d=Document([a,b,f]);self.assertAlmostEqual(bodies(d.frames)[f['id']]['shape'].Area(),300)
    def test_patch_thicken_trim_extend_and_stitch(self):
        s=self.sketch();patch=self.feature('surface_patch',source=self.source(s));d=Document([s,patch]);self.assertAlmostEqual(bodies(d.frames)[patch['id']]['shape'].Area(),50)
        thick=self.feature('surface_thicken',surfaces=[patch['id']],thickness=2,consume=True);d.commit(d.features+[thick]);self.assertAlmostEqual(d.solid.val().Volume(),100,places=4);self.assertFalse(bodies(d.frames));d.undo();self.assertIsNone(d.solid)
        extend=self.feature('surface_extend',surfaces=[patch['id']],distance=1,consume=True);d.commit(d.features+[extend]);self.assertAlmostEqual(bodies(d.frames)[extend['id']]['shape'].Area(),84)
        trim=self.feature('surface_trim',surfaces=[extend['id']],plane=dict(type='origin',plane='YZ'),keep='positive');d.commit(d.features+[trim]);self.assertAlmostEqual(bodies(d.frames)[trim['id']]['shape'].Area(),42)
        stitch=self.feature('surface_stitch',surfaces=[trim['id']],make_solid=False,tolerance=.001);d.commit(d.features+[stitch]);self.assertAlmostEqual(bodies(d.frames)[stitch['id']]['shape'].Area(),42)
    def test_missing_surface_and_non_watertight_stitch_fail_atomically(self):
        s=self.sketch();p=self.feature('surface_patch',source=self.source(s));d=Document([s,p]);before=list(d.features)
        with self.assertRaisesRegex(ModelError,'watertight'):d.commit(d.features+[self.feature('surface_stitch',surfaces=[p['id']],make_solid=True)])
        self.assertEqual(d.features,before)
        with self.assertRaisesRegex(ModelError,'missing'):d.commit(d.features+[self.feature('surface_thicken',surfaces=['lost'],thickness=1)])

if __name__=='__main__':unittest.main()
