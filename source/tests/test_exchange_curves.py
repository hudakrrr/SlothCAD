import copy,math,tempfile,unittest
from pathlib import Path
import cadquery as cq
import numpy as np
import ezdxf
from geometry import entity,new_sketch,base_frame,wire_for,regions,sample,nearest_on_entity,profile_geometry,identifier
from curves import edge_for,evaluate
from trim import trim_entities
from exchange import import_step,import_dxf,export_dxf
from model import Document,ModelError

class ExchangeCurveTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def ellipse(self):return entity('ellipse',center=[0,0],major=[10,0],minor_radius=5)
 def test_ellipse_exact_profile_and_volume(self):
  s=new_sketch(base_frame('XY'));s['entities']=[self.ellipse()];wire=wire_for(s,regions(s)[0],s['frame']);self.assertEqual(wire.Edges()[0].geomType(),'ELLIPSE');self.assertAlmostEqual(cq.Face.makeFromWires(wire).Area(),math.pi*50,places=7)
  f=dict(kind='extrude',id=identifier(),name='Ellipse',enabled=True,source={'type':'sketch','sketch':s['id'],'entities':regions(s)[0]},depth=4,operation='add');d=Document([s,f]);self.assertAlmostEqual(d.solid.val().Volume(),200*math.pi,places=6)
 def test_control_spline_and_rational_conic(self):
  s=entity('spline',points=[[0,0],[5,10],[10,0]],basis='bspline');np.testing.assert_allclose(evaluate(s,.5),[5,5]);self.assertEqual(edge_for(s).geomType(),'BSPLINE')
  c=entity('conic',a=[0,0],control=[5,10],b=[10,0],weight=.5);np.testing.assert_allclose(evaluate(c,.5),[5,10/3]);bad=copy.deepcopy(c);bad['weight']=0
  with self.assertRaises(ModelError):edge_for(bad)
 def test_legacy_spline_shape_and_periodic_control_spline(self):
  old=entity('spline',points=[[0,0],[5,10],[10,0]]);np.testing.assert_allclose(evaluate(old,.5),[5,10])
  closed=entity('spline',points=[[0,0],[10,0],[10,10],[0,10]],basis='bspline',closed=True);np.testing.assert_allclose(evaluate(closed,0),evaluate(closed,1));self.assertTrue(edge_for(closed).IsClosed())
  sketch=new_sketch(base_frame('XY'));sketch['entities']=[closed];self.assertTrue(wire_for(sketch,regions(sketch)[0],sketch['frame']).IsClosed())
 def test_exact_projection_and_ellipse_partition(self):
  e=self.ellipse();p=nearest_on_entity(e,[6,4]);self.assertAlmostEqual((p[0]/10)**2+(p[1]/5)**2,1,places=10)
  line=entity('line',a=[0,-10],b=[0,10]);sketch=new_sketch(base_frame('XY'));sketch['entities']=[e,line];parts=profile_geometry(sketch);self.assertTrue(any(p['kind']=='ellipse' for p in parts));self.assertEqual(len(regions(sketch)),2)
  for region in regions(sketch):self.assertAlmostEqual(cq.Face.makeFromWires(wire_for(sketch,region,sketch['frame'])).Area(),25*math.pi,places=7)
 def test_curve_trimming_preserves_basis_and_crossings(self):
  e=self.ellipse();line=entity('line',a=[0,-10],b=[0,10]);trimmed=trim_entities([e,line],0,[10,0]);self.assertEqual(trimmed[0]['kind'],'ellipse');self.assertEqual(trimmed[0]['range'],[.25,.75]);self.assertEqual(trimmed[0]['id'],e['id'])
  curve=entity('conic',a=[0,0],control=[5,10],b=[10,0],weight=.7);cross=entity('line',a=[5,-1],b=[5,10]);kept=trim_entities([curve,cross],0,[8,2]);self.assertEqual(kept[0]['kind'],'conic');self.assertEqual(kept[0]['weight'],.7);np.testing.assert_allclose(sample(kept[0])[-1],evaluate(curve,.5),atol=1e-8)
  trimmed_line=trim_entities([line,e],0,[0,0]);self.assertEqual(len(trimmed_line),3);self.assertAlmostEqual(trimmed_line[0]['b'][1],-5,places=8);self.assertAlmostEqual(trimmed_line[1]['a'][1],5,places=8)
 def test_step_embedded_portable_multi_body_and_editor_transform(self):
  source=self.root/'source.step';shapes=[cq.Workplane('XY').box(10,20,30).val(),cq.Workplane('XY').box(4,4,4).translate((30,0,0)).val()];cq.exporters.export(cq.Compound.makeCompound(shapes),str(source));f=import_step(source);source.unlink();d=Document([f]);self.assertEqual(len(d.solid.val().Solids()),2);self.assertAlmostEqual(d.solid.val().Volume(),6064,places=6)
  saved=self.root/'project.fcad';d.save(saved);loaded=Document.load(saved);self.assertAlmostEqual(loaded.solid.val().Volume(),6064,places=6);changed=copy.deepcopy(d.features);changed[0].update(scale=2,dx=10);d.commit(changed);self.assertAlmostEqual(d.solid.val().Volume(),6064*8,places=5);d.undo();self.assertAlmostEqual(d.solid.val().Volume(),6064,places=6)
 def test_step_import_preserves_existing_bodies_and_invalid_is_transactional(self):
  p=self.root/'one.step';cq.exporters.export(cq.Workplane('XY').box(10,10,10),str(p));f=import_step(p);d=Document([f]);second=copy.deepcopy(f);second.update(id=identifier(),dx=30);d.commit(d.features+[second]);self.assertEqual(len(d.solid.val().Solids()),2);old=copy.deepcopy(d.features);bad=copy.deepcopy(old);bad[0]['brep']='bad'
  with self.assertRaises(ModelError):d.commit(bad)
  self.assertEqual(d.features,old)
 def test_dxf_analytic_round_trip_trimmed_rational_and_construction(self):
  entities=[entity('line',a=[0,0],b=[3,4],construction=True),entity('circle',center=[20,0],radius=2),self.ellipse(),entity('conic',a=[0,0],control=[5,10],b=[10,0],weight=.6),entity('spline',points=[[0,0],[4,8],[10,0]],basis='bspline',range=[.2,.8])]
  p=self.root/'curves.dxf';export_dxf(p,entities);loaded,unsupported,unit=import_dxf(p);self.assertFalse(unsupported);self.assertEqual(unit,4);self.assertEqual(len(loaded),5);self.assertTrue(loaded[0]['construction']);self.assertEqual(loaded[2]['kind'],'ellipse')
  for old,new in zip(entities[3:],loaded[3:]):np.testing.assert_allclose(sample(old,20),sample(new,20),atol=1e-7)
 def test_dxf_units_bulge_insert_and_unsupported_feedback(self):
  p=self.root/'inches.dxf';doc=ezdxf.new();doc.units=1;m=doc.modelspace();m.add_lwpolyline([(0,0,1),(2,0,0)],format='xyb');block=doc.blocks.new('square');block.add_line((0,0),(1,0));m.add_blockref('square',(4,0));m.add_solid([(0,0),(1,0),(0,1),(1,1)]);doc.saveas(p);items,unsupported,units=import_dxf(p);self.assertEqual(len(items),2);self.assertEqual(items[0]['kind'],'arc');self.assertIn('SOLID',unsupported);self.assertAlmostEqual(math.dist(items[1]['a'],items[1]['b']),25.4)
 def test_dxf_rejects_nonplanar_and_empty(self):
  for entities in [lambda m:m.add_line((0,0,1),(2,0,2)),lambda m:m.add_solid([(0,0),(1,0),(0,1),(1,1)])]:
   doc=ezdxf.new();entities(doc.modelspace());p=self.root/'bad.dxf';doc.saveas(p)
   with self.assertRaises(ModelError):import_dxf(p)

 def test_dxf_text_becomes_sketch_outlines(self):
  doc=ezdxf.new();doc.units=4;doc.modelspace().add_text('AB',dxfattribs={'insert':(5,5),'height':10});p=self.root/'text.dxf';doc.saveas(p)
  items,unsupported,units=import_dxf(p)
  self.assertFalse(unsupported);self.assertTrue(items);self.assertTrue(all(e['kind']=='polygon' for e in items))
  xs=[x for e in items for x,_ in e['points']];ys=[y for e in items for _,y in e['points']]
  self.assertGreaterEqual(min(xs),4.5);self.assertGreaterEqual(min(ys),4.5);self.assertLess(max(ys)-min(ys),12)

 def test_mirrored_trimmed_ellipse_stays_exact(self):
  from geometry import transform_entity
  e=self.ellipse();e['range']=[.1,.35];mirrored=transform_entity(e,np.diag([-1.,1.]),[2,3]);points=sample(e,100)@np.diag([-1.,1.])+[2,3]
  for p in points[::10]:self.assertLess(np.linalg.norm(nearest_on_entity(mirrored,p)-p),1e-7)
  self.assertEqual(edge_for(mirrored).geomType(),'BSPLINE')
