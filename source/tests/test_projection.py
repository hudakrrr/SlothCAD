import copy,unittest,math,tempfile
from pathlib import Path
import cadquery as cq
import numpy as np
from geometry import new_sketch,base_frame,entity,identifier,profile_regions
from projection import project_edge,resolve,break_link
from references import shape_reference
from constraints import drag,point_ref
from model import Document,ModelError
from curves import edge_for

class ProjectionTests(unittest.TestCase):
    def source(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=10)];return s
    def test_projected_sketch_updates_preserves_ids_and_extrudes(self):
        a=self.source();b=new_sketch(base_frame('XY'));b['frame']['origin'][2]=10;b['projections']=[dict(id=identifier(),source=dict(type='sketch',sketch=a['id'],entities=[a['entities'][0]['id']]),mode='project')]
        d=Document([a,b]);ids=[e['id'] for e in d.sketches[b['id']]['entities']];r=profile_regions(d.sketches[b['id']])[0]
        e=dict(id=identifier(),kind='extrude',name='Projected block',enabled=True,source=dict(type='sketch',sketch=b['id'],entities=r['entities']),depth=3,operation='add');d.commit(d.features+[e]);self.assertAlmostEqual(d.solid.val().Volume(),600)
        changed=copy.deepcopy(d.features);changed[0]['entities'][0]['width']=30;d.commit(changed);self.assertAlmostEqual(d.solid.val().Volume(),900);self.assertEqual(ids,[e['id'] for e in d.sketches[b['id']]['entities']])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'projected.fcad';d.save(p);self.assertAlmostEqual(Document.load(p).solid.val().Volume(),900)
    def test_project_circle_to_tilted_plane_is_exact_rational_ellipse(self):
        frame=dict(origin=[0,0,0],u=[1,0,0],normal=[0,math.sqrt(.5),math.sqrt(.5)])
        e=project_edge(cq.Edge.makeCircle(10),frame);self.assertEqual(e['kind'],'ellipse');curve=edge_for(dict(e,id='test'));self.assertTrue(curve.IsClosed())
        face=cq.Face.makeFromWires(cq.Wire.assembleEdges([curve]));self.assertAlmostEqual(face.Area(),math.pi*100*math.sqrt(.5),places=5)
    def test_include_rejects_non_coplanar_and_project_collapsed_edge_is_point(self):
        edge=cq.Edge.makeLine((0,0,3),(10,0,3))
        with self.assertRaisesRegex(ModelError,'Include geometry'):project_edge(edge,base_frame('XY'),'include')
        self.assertEqual(project_edge(cq.Edge.makeLine((0,0,0),(0,0,5)),base_frame('XY'))['kind'],'point')
    def test_missing_source_is_feedback_and_undo_keeps_previous_model(self):
        a=self.source();b=new_sketch(base_frame('XY'));b['projections']=[dict(id=identifier(),source=dict(type='sketch',sketch=a['id'],entities=[a['entities'][0]['id']]))];d=Document([a,b]);before=copy.deepcopy(d.features)
        changed=copy.deepcopy(before);changed[0]['entities']=[]
        with self.assertRaisesRegex(ModelError,'projected sketch entity'):d.commit(changed)
        self.assertEqual(d.features,before);self.assertEqual(d.inspect_history(d.pending_features)[1]['state'],'needs repair')
    def test_break_link_removes_locks_and_allows_editing(self):
        a=self.source();b=new_sketch(base_frame('XY'));link=dict(id=identifier(),source=dict(type='sketch',sketch=a['id'],entities=[a['entities'][0]['id']]))
        b['projections']=[link];b=resolve(b,None,{a['id']:a},{a['id']:a['frame']},b['frame']);locked=drag(b,point_ref(b['entities'][0]['id'],'a'),[5,5]);np.testing.assert_allclose(locked['entities'][0]['a'],b['entities'][0]['a'],atol=1e-7)
        free=break_link(b,link['id']);self.assertFalse(free['constraints']);self.assertFalse(free['projections'])
