"""Deterministic CAD workflow audit: analytic oracles and chained edits."""
import copy,math,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
import cadquery as cq
from geometry import entity,new_sketch,base_frame,identifier,profile_regions,regions,sample,wire_for,transform_entity
from model import Document,ModelError,edge_reference
from references import body_reference
from solid_tools import face_ref,path_wire
from exchange import import_step,export_dxf,import_dxf
from curves import edge_for,evaluate
from measure import calculate_measurement
from trim import trim_entities
from constraints import new_constraint,add_constraint,drag,line_ref,point_ref,validate_constraints,ConstraintConflict
from recovery import atomic_json,recovery_files,process_alive

def feature(kind,**values):return dict(kind=kind,id=identifier(),name=kind,enabled=True,**values)
def sketch(*items,plane='XY',origin=None):
 s=new_sketch(base_frame(plane));s['entities']=list(items)
 if origin:s['frame']['origin']=origin
 return s
def source(s,index=0):
 p=profile_regions(s)[index];return dict(type='sketch',sketch=s['id'],entities=p['entities'],holes=p['holes'],profile_mode='nested')
def base():
 s=sketch(entity('rectangle',center=[0,0],width=40,height=30));return [s,feature('extrude',source=source(s),depth=12,operation='add')]
def ref(d,i=0):
 b=d.solid.val().Solids();return body_reference(b[i],i,len(b))

class WorkflowAuditTests(unittest.TestCase):
 def test_seeded_profile_plane_sign_and_scale_matrix(self):
  rng=np.random.default_rng(2718)
  for plane in ('XY','XZ','YZ'):
   for sign in (-1,1):
    for scale in (.1,1.,10.):
     with self.subTest(plane=plane,sign=sign,scale=scale):
      w,h=rng.uniform(3,9,2)*scale;depth=sign*2*scale;s=sketch(entity('rectangle',center=[2*scale,-scale],width=w,height=h),plane=plane)
      d=Document([s,feature('extrude',source=source(s),depth=depth,operation='add')]);self.assertTrue(d.solid.val().isValid());self.assertAlmostEqual(d.solid.val().Volume(),w*h*abs(depth),delta=w*h*abs(depth)*1e-7)
 def test_nested_regions_and_holes_with_all_boolean_directions(self):
  outer=entity('rectangle',center=[0,0],width=40,height=30);inner=entity('rectangle',center=[0,0],width=20,height=12);hole=entity('circle',center=[0,0],radius=2);s=sketch(outer,inner,hole)
  for p in profile_regions(s):
   f=feature('extrude',source=dict(type='sketch',sketch=s['id'],entities=p['entities'],holes=p['holes'],profile_mode='nested'),depth=5,operation='add');d=Document([s,f]);self.assertTrue(d.solid.val().isValid())
  self.assertEqual(len(profile_regions(s)),3)
  d=Document(base());volume=d.solid.val().Volume()
  for operation,expected in [('cut',volume-3*math.pi*4),('intersect',3*math.pi*4)]:
   hs=sketch(entity('circle',center=[0,0],radius=2),origin=[0,0,12]);f=feature('extrude',source=source(hs),depth=-3,operation=operation);out=Document(d.features+[hs,f]);self.assertAlmostEqual(out.solid.val().Volume(),expected,places=6)
 def test_long_feature_chain_and_upstream_edit(self):
  d=Document(base());top=max(d.solid.val().Faces(),key=lambda f:f.Center().z)
  hole=feature('hole',plane=dict(type='face',face=face_ref(top,d.solid)),hole_type='counterbore',diameter=4,depth=12,head_diameter=8,head_depth=3,x=0,y=0);d.commit(d.features+[hole])
  vertical=next(e for e in d.solid.val().Edges() if e.geomType()=='LINE' and abs(e.Center().x-20)<1e-6 and abs(e.Center().z-6)<1e-6)
  d.commit(d.features+[feature('fillet',edge_refs=[edge_reference(vertical,d.solid)],radius=1)])
  d.commit(d.features+[feature('body_move',targets=[ref(d)],dx=0,dy=40,dz=0,angle=0,copy=True)])
  d.commit(d.features+[feature('body_rectangular',targets=[ref(d,1)],columns=3,rows=1,spacing_x=50,spacing_y=0,plane={'type':'origin','plane':'XY'})])
  d.commit(d.features+[feature('body_split',targets=[ref(d,0)],plane={'type':'frame','frame':{'origin':[0,0,6],'u':[1,0,0],'normal':[0,0,1]}},keep='both')]);before=copy.deepcopy(d.features);oldvolume=d.solid.val().Volume();self.assertEqual(len(d.solid.val().Solids()),5)
  changed=copy.deepcopy(before);changed[0]['entities'][0]['width']=44;changed[1]['depth']=14;d.commit(changed);self.assertTrue(d.solid.val().isValid());self.assertGreater(d.solid.val().Volume(),oldvolume);self.assertFalse(any(row['state']=='needs repair' for row in d.inspect_history()))
  d.undo();self.assertEqual(d.features,before);d.redo();self.assertAlmostEqual(d.features[1]['depth'],14)
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'chain.fcad';d.save(p);self.assertAlmostEqual(Document.load(p).solid.val().Volume(),d.solid.val().Volume(),places=5)
 def test_body_visibility_and_appearance_follow_split_and_undo(self):
  features=base();s=sketch(entity('rectangle',center=[70,0],width=10,height=10));d=Document(features+[s,feature('extrude',source=source(s),depth=12,operation='add')]);d.display={'materials':{'0':{'color':'#ff0000','finish':'matte'},'1':{'color':'#00ff00','finish':'metallic'}},'bodies':{'1':False}}
  d.commit(d.features+[feature('body_split',targets=[ref(d)],plane={'type':'frame','frame':{'origin':[0,0,6],'u':[1,0,0],'normal':[0,0,1]}},keep='both')]);self.assertEqual(d.display['materials']['2']['color'],'#00ff00');self.assertFalse(d.display['bodies']['2']);self.assertEqual(d.display['materials']['0']['color'],'#ff0000');self.assertEqual(d.display['materials']['1']['color'],'#ff0000')
  d.undo();self.assertEqual(d.display['materials']['1']['color'],'#00ff00');self.assertFalse(d.display['bodies']['1'])
 def test_pattern_copy_split_combine_volume_accounting(self):
  d=Document(base());original=d.solid.val().Volume();d.commit(d.features+[feature('body_move',targets=[ref(d)],dx=10,dy=0,dz=0,angle=0,copy=True)]);self.assertAlmostEqual(d.solid.val().Volume(),2*original)
  refs=[ref(d,i) for i in (0,1)];d.commit(d.features+[feature('body_combine',targets=[refs[0]],tools=[refs[1]],operation='cut',keep_tools=True)]);self.assertAlmostEqual(d.solid.val().Solids()[0].Volume(),10*30*12,places=6);self.assertEqual(len(d.solid.val().Solids()),2)
  d.undo();d.commit(d.features+[feature('body_combine',targets=[refs[0]],tools=[refs[1]],operation='join',keep_tools=False)]);self.assertEqual(len(d.solid.val().Solids()),1);self.assertAlmostEqual(d.solid.val().Volume(),50*30*12,places=6)
 def test_large_body_pattern_rebuild_visibility_and_step_exchange(self):
  d=Document(base());volume=d.solid.val().Volume();d.commit(d.features+[feature('body_rectangular',targets=[ref(d)],columns=12,rows=8,spacing_x=50,spacing_y=40,plane={'type':'origin','plane':'XY'})]);self.assertEqual(len(d.solid.val().Solids()),96);self.assertAlmostEqual(d.solid.val().Volume(),96*volume,places=4)
  d.display={'materials':{'95':{'color':'#2675ad','finish':'matte'}},'bodies':{'95':False}}
  d.commit(d.features+[feature('body_split',targets=[ref(d)],plane={'type':'frame','frame':{'origin':[0,0,6],'u':[1,0,0],'normal':[0,0,1]}},keep='both')]);self.assertEqual(len(d.solid.val().Solids()),97);self.assertFalse(d.display['bodies']['96']);self.assertEqual(d.display['materials']['96']['color'],'#2675ad')
  d.undo();self.assertEqual(len(d.solid.val().Solids()),96);self.assertFalse(d.display['bodies']['95']);d.redo()
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'pattern.step';d.export(p);loaded=Document([import_step(p)]);self.assertEqual(len(loaded.solid.val().Solids()),97);self.assertAlmostEqual(loaded.solid.val().Volume(),96*volume,places=4)
 def test_measure_curves_matches_kernel_length_and_distance(self):
  e=entity('ellipse',center=[0,0],major=[20,0],minor_radius=1)
  result=calculate_measurement([dict(kind='edge',label='Ellipse',entity=e,frame=base_frame('XY')),dict(kind='point',label='Point',point=[0,0,0])]);self.assertAlmostEqual(result['properties'][0]['length'],edge_for(e).Length(),places=8);self.assertAlmostEqual(result['distance'],1,places=8)
  e=entity('conic',a=[0,0],control=[5,12],b=[10,0],weight=.3,range=[.2,.8]);result=calculate_measurement([dict(kind='edge',label='Conic',entity=e,frame=base_frame('XZ'))]);self.assertAlmostEqual(result['properties'][0]['length'],edge_for(e).Length(),places=8)
 def test_sweep_uses_same_exact_control_curve(self):
  e=entity('spline',basis='bspline',degree=3,points=[[0,0],[0,4],[8,8],[10,12]]);s=sketch(e,plane='XZ');wire=path_wire(dict(sketch=s['id'],entities=[e['id']]),{s['id']:s},{s['id']:s['frame']});self.assertAlmostEqual(wire.Length(),edge_for(e).Length(),places=8)
  profile=sketch(entity('circle',center=[0,0],radius=.4));d=Document([profile,s,feature('sweep',source=source(profile),path=dict(sketch=s['id'],entities=[e['id']]),operation='add')]);self.assertTrue(d.solid.val().isValid());self.assertGreater(d.solid.val().Volume(),0)
 def test_trim_repeated_curves_then_extrude_retained_region(self):
  for weight in (.3,1.,3.):
   e=entity('conic',a=[0,0],control=[5,10],b=[10,0],weight=weight);bottom=entity('line',a=[0,0],b=[10,0]);divider=entity('line',a=[5,-1],b=[5,12]);s=sketch(e,bottom,divider);self.assertEqual(len(regions(s)),2)
   trimmed=trim_entities(s['entities'],0,evaluate(e,.75));self.assertTrue(any(t['kind']=='conic' for t in trimmed));s['entities']=trimmed;self.assertEqual(len(regions(s)),1);d=Document([s,feature('extrude',source=source(s),depth=2,operation='add')]);self.assertTrue(d.solid.val().isValid())
 def test_constraints_repeated_drag_conflicts_and_save(self):
  e=entity('line',a=[0,0],b=[10,0]);s=sketch(e);s=add_constraint(s,new_constraint(s,'horizontal',[line_ref(e['id'])]));s=add_constraint(s,new_constraint(s,'dimension',[line_ref(e['id'])],10,'length'))
  for x,y in [(20,12),(-4,8),(30,-10),(0,0)]:s=drag(s,point_ref(e['id'],'b'),[x,y]);validate_constraints(s);self.assertAlmostEqual(math.dist(s['entities'][0]['a'],s['entities'][0]['b']),10,places=7)
  before=copy.deepcopy(s)
  with self.assertRaises(ConstraintConflict):add_constraint(s,new_constraint(s,'dimension',[line_ref(e['id'])],11,'length'))
  self.assertEqual(s,before)
 def test_seeded_dxf_curve_trim_transform_round_trips(self):
  rng=np.random.default_rng(42)
  with tempfile.TemporaryDirectory() as directory:
   for i in range(12):
    a=float(rng.uniform(3,20));b=float(rng.uniform(.5,2));lo=float(rng.uniform(.05,.3));hi=float(rng.uniform(.6,.95));e=entity('ellipse',center=[0,0],major=[a,0],minor_radius=b,range=[lo,hi]);angle=float(rng.uniform(-math.pi,math.pi));matrix=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]]);e=transform_entity(e,matrix,[i,2]);p=Path(directory)/'round.dxf';export_dxf(p,[e]);loaded,w,u=import_dxf(p);self.assertFalse(w);np.testing.assert_allclose(sample(e,20),sample(loaded[0],20),atol=1e-7)
 def test_recovery_utf8_live_process_checks_and_bad_metadata(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'árvíz.json';data={'recovery_format':'slothcad-autosave','version':1,'features':[],'source_path':'árvíztűrő.fcad','timestamp':1,'process_id':os.getpid()};atomic_json(p,data);self.assertEqual(recovery_files(directory)[0][1]['source_path'],'árvíztűrő.fcad');self.assertEqual(recovery_files(directory,False),[]);self.assertTrue(process_alive(os.getpid()));self.assertFalse(process_alive(-1))
   for i,change in enumerate([{'timestamp':'yesterday'},{'timestamp':float('nan')},{'source_path':42}]):atomic_json(Path(directory)/f'bad-{i}.json',dict(data,**change))
   atomic_json(Path(directory)/'not-an-object.json',[]);self.assertEqual(len(recovery_files(directory)),1)
 def test_windows_process_probe_never_uses_kill(self):
  kernel=Mock();kernel.OpenProcess.return_value=100
  def query(handle,code):code._obj.value=259;return 1
  kernel.GetExitCodeProcess.side_effect=query
  with patch('recovery.sys.platform','win32'),patch('ctypes.WinDLL',return_value=kernel,create=True),patch('recovery.os.kill') as kill:
   self.assertTrue(process_alive(123));kill.assert_not_called();kernel.CloseHandle.assert_called_once_with(100)
 def test_invalid_features_leave_all_committed_state_unchanged(self):
  d=Document(base());before=copy.deepcopy(d.features);volume=d.solid.val().Volume();revision=d.revision
  for f in [feature('body_move',targets=[]),feature('body_rectangular',targets=[ref(d)],columns=999,rows=999),feature('shell',body=0,faces=[],thickness=-200),feature('revolve',source=source(d.features[0]),axis={'type':'origin','axis':'X'},angle=0),feature('loft',sections=[],operation='add')]:
   with self.assertRaises(ModelError):d.commit(before+[f])
   self.assertEqual(d.features,before);self.assertEqual(d.revision,revision);self.assertAlmostEqual(d.solid.val().Volume(),volume)
 def test_revolve_loft_shell_draft_then_round_trip_exchange(self):
  s=sketch(entity('rectangle',center=[8,0],width=4,height=8),plane='XZ');d=Document([s,feature('revolve',source=source(s),axis={'type':'origin','axis':'Z'},angle=270,operation='add')]);self.assertAlmostEqual(d.solid.val().Volume(),.75*math.pi*(100-36)*8,places=5)
  a=sketch(entity('circle',center=[0,0],radius=4));b=sketch(entity('circle',center=[0,0],radius=6),origin=[0,0,10]);d=Document([a,b,feature('loft',sections=[source(a),source(b)],operation='add',ruled=True)]);self.assertAlmostEqual(d.solid.val().Volume(),math.pi*10/3*(16+24+36),places=5)
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'löft.step';d.export(p);imported=Document([import_step(p)]);self.assertAlmostEqual(imported.solid.val().Volume(),d.solid.val().Volume(),places=5)
