import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cadquery as cq
from model import Document, ModelError, new_feature, edge_reference, maximum_edge_size

class SolidTests(unittest.TestCase):
    def box(self):
        f=new_feature(); f.update(width=40,height=30,depth=10)
        return f
    def test_cut_and_parametric_edit(self):
        box=self.box(); hole=new_feature(); hole.update(profile='circle',radius=3,depth=12,z=-1,operation='cut')
        d=Document([box,hole]); self.assertAlmostEqual(d.solid.val().Volume(),12000-90*3.141592653589793,places=5)
        changed=copy.deepcopy(d.features); changed[0]['width']=50; d.commit(changed)
        self.assertAlmostEqual(d.solid.val().Volume(),15000-90*3.141592653589793,places=5)
        self.assertTrue(d.undo()); self.assertEqual(d.features[0]['width'],40)
        self.assertTrue(d.redo()); self.assertEqual(d.features[0]['width'],50)
    def test_late_edit_reuses_unchanged_feature_prefix(self):
        box=self.box();hole=new_feature();hole.update(profile='circle',radius=3,depth=12,z=-1,operation='cut')
        d=Document([box,hole]);changed=copy.deepcopy(d.features);changed[-1]['radius']=4;reports=[]
        d.commit(changed,progress=lambda done,total,text:reports.append((done,total,text)))
        self.assertTrue(reports);self.assertEqual(max(total for _,total,_ in reports),1)

    def test_history_prefix_preview_and_revert_are_non_destructive_and_undoable(self):
        box=self.box();hole=new_feature();hole.update(profile='circle',radius=3,depth=12,z=-1,operation='cut')
        d=Document([box,hole]);full_volume=d.solid.val().Volume();original=copy.deepcopy(d.features)
        preview,_,_=d.preview(d.features[:1]);self.assertAlmostEqual(preview.val().Volume(),12000);self.assertEqual(d.features,original)
        self.assertTrue(d.commit(d.features[:1]));self.assertEqual(len(d.features),1);self.assertAlmostEqual(d.solid.val().Volume(),12000)
        self.assertTrue(d.undo());self.assertEqual(d.features,original);self.assertAlmostEqual(d.solid.val().Volume(),full_volume,places=6)

    def test_failed_edit_is_transactional(self):
        d=Document([self.box()]); original=copy.deepcopy(d.features)
        broken=new_feature('fillet'); broken['radius']=100
        with self.assertRaises(ModelError): d.commit(original+[broken])
        self.assertEqual(d.features,original); self.assertEqual(len(d.undo_stack),0)
        self.assertAlmostEqual(d.solid.val().Volume(),12000)
    def test_roundtrip_and_exports(self):
        d=Document([self.box()])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'project.fcad'; d.save(p); loaded=Document.load(p)
            self.assertEqual(loaded.features,d.features)
            step=Path(td)/'part.step'; stl=Path(td)/'part.stl'
            loaded.export(step); loaded.export(stl)
            imported=cq.importers.importStep(str(step))
            self.assertAlmostEqual(imported.val().Volume(),12000,places=4)
            self.assertGreater(stl.stat().st_size,100)
    def test_planes_polygon_and_negative_depth(self):
        for plane in ['XY','XZ','YZ']:
            f=self.box(); f.update(plane=plane,depth=-10)
            self.assertAlmostEqual(Document([f]).solid.val().Volume(),12000)
        f=new_feature(); f.update(profile='polygon',points=[[0,0],[10,0],[0,10]],depth=5)
        self.assertAlmostEqual(Document([f]).solid.val().Volume(),250)
    def test_intersect_and_edge_operations(self):
        f=self.box(); clip=self.box(); clip.update(width=20,height=20,depth=20,operation='intersect')
        self.assertAlmostEqual(Document([f,clip]).solid.val().Volume(),4000)
        for kind in ['fillet','chamfer']:
            d=Document([f,new_feature(kind)])
            self.assertTrue(d.solid.val().isValid()); self.assertLess(d.solid.val().Volume(),12000)
    def test_selected_edge_maximum_size_uses_kernel_operation(self):
        body=cq.Workplane('XY').box(20,12,10);ref=[edge_reference(list(body.val().Edges())[0])]
        for kind in ('fillet','chamfer'):
            limit,bounded=maximum_edge_size(body,kind,ref,hint=1)
            self.assertTrue(bounded);self.assertGreater(limit,11.9);self.assertLess(limit,12.01)

    def test_solid_corner_feature_accepts_all_incident_edges(self):
        from model import edge_reference
        box=self.box();base=Document([box]).solid.val();target=(-20.,-15.,0.)
        incident=[edge for edge in base.Edges() if any(all(abs(a-b)<1e-7 for a,b in zip(vertex.Center().toTuple(),target)) for vertex in edge.Vertices())]
        self.assertEqual(len(incident),3)
        for kind in ('fillet','chamfer'):
            feature=new_feature(kind);feature['edge_refs']=[edge_reference(edge) for edge in incident]
            feature['radius']=.8;doc=Document([box,feature])
            self.assertTrue(doc.solid.val().isValid());self.assertLess(doc.solid.val().Volume(),base.Volume())

    def test_difficult_multi_edge_corner_retries_individual_edges(self):
        from model import apply_edge_operation,_edge_trial_is_valid
        shape=cq.Workplane('XY').box(20,12,10)
        picked=[edge for edge in shape.val().Edges() if
                (np.allclose(edge.Center().toTuple(),(-10,-6,0),atol=1e-7) or
                 np.allclose(edge.Center().toTuple(),(0,6,-5),atol=1e-7))]
        self.assertEqual(len(picked),2)
        for kind in ('fillet','chamfer'):
            with self.subTest(kind=kind):
                try:combined=getattr(shape.newObject(picked),kind)(6)
                except Exception:combined=None
                self.assertFalse(_edge_trial_is_valid(combined))
                result=apply_edge_operation(shape,picked,kind,6)
                self.assertTrue(result.val().isValid())
                self.assertLess(result.val().Volume(),shape.val().Volume())

    def test_suppression_and_empty_rejected(self):
        f=self.box(); f['enabled']=False
        self.assertIsNone(Document([f]).solid)
        hole=self.box(); hole['operation']='cut'
        with self.assertRaises(ModelError): Document([self.box(),hole])
        with self.assertRaises(ModelError): Document([hole])
    def test_invalid_values_and_format(self):
        for value in [0,-1,float('nan'),float('inf')]:
            f=self.box(); f['width']=value
            with self.assertRaises(ModelError): Document([f])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.fcad'; p.write_text(json.dumps({'format':'slothcad','version':99}))
            with self.assertRaises(ModelError): Document.load(p)

if __name__=='__main__': unittest.main()
