import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,unittest,math,copy,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF,Qt
from PySide6.QtGui import QImage,QPainter,QColor
from geometry import new_sketch,base_frame,entity,profile_regions,arc_data,regions
from model import Document
from workspace import Workspace

def wheel_sketch():
    s=new_sketch(base_frame('XY'));s['entities']=[entity('circle',center=[0,0],radius=20)]
    for i in range(9):
        angle=2*math.pi*i/9;s['entities'].append(entity('circle',center=[14*math.cos(angle),14*math.sin(angle)],radius=2))
    return s

def feature(s,profile):return dict(kind='extrude',name='Perforated disk',depth=5,operation='add',signed_depth=True,
    source=dict(type='sketch',sketch=s['id'],entities=profile['entities'],holes=profile['holes'],profile_mode='nested'))

class NestedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Workspace();self.w.resize(600,400)
    def tearDown(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_one_sketch_creates_a_disk_with_nine_exact_circular_holes(self):
        s=wheel_sketch();profiles=profile_regions(s);self.assertEqual(len(profiles[0]['holes']),9)
        d=Document([s,feature(s,profiles[0])]);shape=d.solid.val()
        self.assertEqual(len(d.sketches),1);self.assertEqual(len(shape.Solids()),1)
        self.assertAlmostEqual(shape.Volume(),math.pi*(400-9*4)*5,places=6)
        self.assertEqual(sum(f.geomType()=='CYLINDER' for f in shape.Faces()),10)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'wheel.fcad';d.save(path);self.assertAlmostEqual(Document.load(path).solid.val().Volume(),shape.Volume(),places=6)
    def test_cursor_selects_main_region_or_inner_circle_without_loop_order_bias(self):
        s=wheel_sketch();frame=s['frame'];self.w.set_scene(None,[(s,frame)]);self.w.set_mode('extrude');self.w.aligned=np.eye(3)
        main=self.w.pick(QPointF(*self.w.project_local([[0,0]],frame)[0]));self.assertEqual(len(main['holes']),9)
        small=self.w.pick(QPointF(*self.w.project_local([[14,0]],frame)[0]));self.assertEqual(small['entities'],[s['entities'][1]['id']]);self.assertEqual(small['holes'],[])
        s['entities'].reverse();self.w.set_scene(None,[(s,frame)])
        main=self.w.pick(QPointF(*self.w.project_local([[0,0]],frame)[0]));self.assertEqual(len(main['holes']),9)
    def test_nested_island_is_a_separate_selectable_profile(self):
        s=new_sketch(base_frame('XY'));s['entities']=[entity('circle',center=[0,0],radius=r) for r in [20,10,3]]
        profiles=profile_regions(s);self.assertEqual(profiles[0]['holes'],[[s['entities'][1]['id']]])
        self.assertEqual(profiles[1]['holes'],[[s['entities'][2]['id']]])
        self.assertEqual(profiles[2]['holes'],[])
    def test_profile_rebuild_tracks_new_holes_added_to_same_sketch(self):
        s=wheel_sketch();f=feature(s,profile_regions(s)[0]);s['entities'].append(entity('circle',center=[0,0],radius=3))
        self.assertAlmostEqual(Document([s,f]).solid.val().Volume(),math.pi*(400-36-9)*5,places=6)
    def test_profile_fill_is_half_transparent_and_holes_are_clear(self):
        s=wheel_sketch();self.w.aligned=np.eye(3);self.w.span=60
        image=QImage(600,400,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.transparent);p=QPainter(image)
        self.w.draw_profile(p,profile_regions(s)[0],s['frame'],'#8d68ac','#e8e1ef');p.end()
        self.assertEqual(image.pixelColor(300,200).alpha(),128)
        x,y=self.w.project_local([[14,0]],s['frame'])[0];self.assertEqual(image.pixelColor(round(x),round(y)).alpha(),0)
    def test_arc_start_end_bend_order_and_invalid_bend_retry(self):
        s=new_sketch(base_frame('XY'));self.w.set_mode('sketch',s,s['frame']);self.w.set_tool('arc');made=[];self.w.entity_created.connect(made.append)
        self.w.draw_point(np.array([-10.,0.]));self.w.draw_point(np.array([10.,0.]));self.w.draw_point(np.array([0.,0.]))
        self.assertEqual(len(self.w.points),2);self.assertEqual(made,[])
        self.w.draw_point(np.array([0.,10.]));self.assertEqual(made[0]['a'],[-10,0]);self.assertEqual(made[0]['b'],[10,0]);self.assertEqual(made[0]['mid'],[0,10]);self.assertEqual(self.w.points,[])
    def test_arc_duplicate_endpoint_keeps_start_for_retry(self):
        self.w.set_tool('arc');self.w.draw_point(np.array([0.,0.]));self.w.draw_point(np.array([0.,0.]))
        self.assertEqual(self.w.points,[[0.,0.]])
    def test_arc_solver_handles_small_arcs_and_large_translated_coordinates(self):
        for center,radius in [(np.array([0.,0.]),.0001),(np.array([1e8,1e8]),10.)]:
            e=entity('arc',a=(center+[-radius,0]).tolist(),mid=(center+[0,radius]).tolist(),b=(center+[radius,0]).tolist())
            c,r,angle,sweep=arc_data(e);np.testing.assert_allclose(c,center,atol=1e-8);self.assertAlmostEqual(r,radius)


class TouchingHoleTests(unittest.TestCase):
    def test_hole_touching_outline_at_one_vertex_extrudes(self):
        # The outline walk passed the shared vertex twice; the invalid wire made every
        # profile of the sketch fail with "degenerate or self-intersecting".
        s=new_sketch(base_frame('XY'))
        points=[(0,0),(5,0),(10,0),(10,10),(0,10)]
        s['entities']=[entity('line',a=list(a),b=list(b)) for a,b in zip(points,points[1:]+points[:1])]
        triangle=[(5,0),(6,3),(4,3)]
        s['entities']+=[entity('line',a=list(a),b=list(b)) for a,b in zip(triangle,triangle[1:]+triangle[:1])]
        found=profile_regions(s)
        outer=max(found,key=lambda r:len(r['entities']))
        self.assertEqual(len(outer['entities']),5);self.assertEqual(len(outer['holes']),1)
        f=dict(kind='extrude',id='e',name='E',enabled=True,depth=2.,operation='add',
               source=dict(type='sketch',sketch=s['id'],entities=outer['entities'],holes=outer['holes'],profile_mode='nested'))
        solid=Document([s,f]).solid.val()
        self.assertTrue(solid.isValid());self.assertAlmostEqual(solid.Volume(),(100-3)*2,places=6)
