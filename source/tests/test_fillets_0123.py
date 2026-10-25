"""Fillet/chamfer robustness: clear failures, working fallbacks, tangent chains."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cadquery as cq
from model import Document,ModelError,edge_reference,apply_edge_operation,maximum_edge_size
from geometry import base_frame,new_sketch,entity,regions,identifier
from edge_chain import end_directions,tangent_chain


def extrusion(sketch,depth):
    return dict(kind='extrude',id=identifier(),name='Extrude',enabled=True,depth=depth,operation='add',
                source={'type':'sketch','sketch':sketch['id'],'entities':regions(sketch)[0]})


class FilletRobustnessTests(unittest.TestCase):
    def box(self):return cq.Workplane('XY').box(20,12,10)

    def test_oversized_fillet_fails_cleanly_and_largest_size_works(self):
        body=self.box();edge=[e for e in body.val().Edges() if e.geomType()=='LINE'][0]
        with self.assertRaises(ModelError) as caught:apply_edge_operation(body,[edge],'fillet',50)
        self.assertIn('cannot be built',str(caught.exception))
        limit,bounded=maximum_edge_size(body,'fillet',[edge_reference(edge,body)],hint=50)
        self.assertTrue(bounded);self.assertGreater(limit,0)
        result=apply_edge_operation(body,[edge],'fillet',limit*.98)
        self.assertTrue(result.val().isValid());self.assertEqual(len(result.val().Solids()),1)

    def test_auto_fit_builds_an_oversized_fillet_with_the_largest_size_that_fits(self):
        body=self.box();edge=[e for e in body.val().Edges() if e.geomType()=='LINE'][0];report={}
        result=apply_edge_operation(body,[edge],'fillet',50,fit=True,report=report)
        self.assertTrue(result.val().isValid());self.assertEqual(len(result.val().Solids()),1)
        self.assertEqual(len(report['reduced']),1);self.assertLess(report['reduced'][0][1],50);self.assertEqual(report['skipped'],[])
        self.assertLess(result.val().Volume(),body.val().Volume())

    def test_auto_fit_feature_rebuilds_and_reports(self):
        from model import EDGE_REPORTS
        base=Document([]);s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=20,height=12)]
        d=Document([s,extrusion(s,10)]);edges=[e for e in d.solid.val().Edges() if e.geomType()=='LINE'][:2]
        fillet=dict(kind='fillet',id=identifier(),name='Fillet',enabled=True,radius=40.,auto_fit=True,edge_refs=[edge_reference(e,d.solid) for e in edges])
        d.commit(d.features+[fillet]);self.assertTrue(d.solid.val().isValid());self.assertIn(fillet['id'],EDGE_REPORTS)

    def test_vertex_group_fillet_keeps_one_valid_body(self):
        body=self.box();corner=(10.,6.,5.)
        edges=[e for e in body.val().Edges() if any(all(abs(a-b)<1e-6 for a,b in zip(v.Center().toTuple(),corner)) for v in e.Vertices())]
        self.assertEqual(len(edges),3)
        for kind in ('fillet','chamfer'):
            result=apply_edge_operation(body,edges,kind,2)
            self.assertTrue(result.val().isValid());self.assertEqual(len(result.val().Solids()),1)

    def test_tangent_chain_selects_the_whole_rounded_outline(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('slot',a=[-10,0],b=[10,0],width=8)]
        d=Document([s,extrusion(s,6)]);edges=list(d.solid.val().Edges())
        top_line=next(i for i,e in enumerate(edges) if e.geomType()=='LINE' and abs(e.Center().z-6)<1e-6)
        chain=tangent_chain(end_directions(edges),top_line)
        self.assertEqual(len(chain),4)
        self.assertTrue(all(abs(edges[i].Center().z-6)<1e-6 for i in chain))
        fillet=dict(kind='fillet',id=identifier(),name='Fillet',enabled=True,radius=1.5,edge_refs=[edge_reference(edges[i],d.solid) for i in chain])
        d.commit(d.features+[fillet]);self.assertTrue(d.solid.val().isValid())


if __name__=='__main__':unittest.main()
