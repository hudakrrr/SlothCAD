import copy,unittest
from model import Document,ModelError
from geometry import new_sketch,base_frame,entity,identifier,profile_regions
from feature_history import graph,descendants

class HistoryTests(unittest.TestCase):
    def model(self):
        a=new_sketch(base_frame('XY'),'A');a['entities']=[entity('rectangle',center=[0,0],width=20,height=10)]
        b=new_sketch(base_frame('XY'),'B');b['entities']=[entity('circle',center=[40,0],radius=3)]
        e=dict(id=identifier(),kind='extrude',name='Extrude A',enabled=True,source=dict(type='sketch',sketch=a['id'],entities=profile_regions(a)[0]['entities']),depth=5,operation='add')
        return Document([a,b,e])
    def test_dependency_inspection_and_safe_reorder_undo(self):
        d=self.model();ids=[f['id'] for f in d.features];self.assertEqual(d.dependencies()[ids[2]],{ids[0]});self.assertEqual(descendants(d.features,ids[0]),{ids[2]})
        original=copy.deepcopy(d.features);volume=d.solid.val().Volume();d.reorder(1,2);self.assertEqual(d.features[-1]['id'],ids[1]);self.assertAlmostEqual(d.solid.val().Volume(),volume);d.undo();self.assertEqual(d.features,original)
    def test_unsafe_reorder_is_atomic_and_names_required_input(self):
        d=self.model();before=copy.deepcopy(d.features)
        with self.assertRaisesRegex(ModelError,'required feature A'):d.reorder(2,0)
        self.assertEqual(d.features,before)
    def test_suppression_requires_explicit_cascade_and_preserves_undo(self):
        d=self.model();before=copy.deepcopy(d.features)
        with self.assertRaisesRegex(ModelError,'suppressed feature A'):d.suppress(0)
        self.assertEqual(d.features,before);d.suppress(0,cascade=True);self.assertFalse(d.features[0]['enabled']);self.assertFalse(d.features[2]['enabled']);self.assertIsNone(d.solid)
        d.undo();self.assertAlmostEqual(d.solid.val().Volume(),1000);self.assertEqual(d.features,before)
    def test_projection_sources_are_dependencies(self):
        d=self.model();b=d.features[1];b['projections']=[dict(id=identifier(),source=dict(type='sketch',sketch=d.features[0]['id'],entities=[d.features[0]['entities'][0]['id']]))]
        self.assertIn(d.features[0]['id'],graph(d.features)[b['id']])
