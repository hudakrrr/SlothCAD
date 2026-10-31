"""Regression tests for the 0.14 bug list: sketch circle/arc/ellipse, click-picked paths,
pattern defaults, threads, palette sub-lists and construction plane hover."""
import math,os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from app import Window,VERSION
from geometry import entity,profile_regions


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.resize(1300,860);self.w.show();self.app.processEvents()
        self.ws=self.w.workspace;self.errors=[];self.w.error=lambda e,*a:self.errors.append(str(e))
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()
    def sketch(self,plane,entities):
        w=self.w;w.start_sketch();w.support_picked({'type':'plane','plane':plane});self.app.processEvents()
        w.draft['entities']=entities;self.ws.active=w.draft;w.show_editor();w.finish_sketch();self.app.processEvents()
    def extrude(self,index,depth,operation='add'):
        w=self.w;sketch=list(w.doc.sketches.values())[index];region=profile_regions(sketch)[0]
        w.start_extrude();self.app.processEvents()
        w.extrusion_picked(dict(type='sketch',sketch=sketch['id'],entities=region['entities'],holes=region['holes'],profile_mode='nested'))
        w.draft['depth']=depth;w.draft['operation']=operation;w.apply_feature();self.app.processEvents()


class SketchTools(Base):
    def draw(self,tool,points):
        w=self.w;w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        self.ws.snap_enabled=False;w.set_tool(tool);created=[];self.ws.entity_created.connect(created.append)
        for x,y in points:
            self.ws.cursor=np.array([x,y],float);self.ws.draw_point(np.array([x,y],float))
        return created
    def test_version(self):self.assertEqual(VERSION,'0.15.2')
    def test_three_point_circle(self):
        created=self.draw('circle_3p',[(10,0),(0,10),(-10,0)])
        self.assertEqual(len(created),1);self.assertEqual(created[0]['kind'],'circle')
        self.assertAlmostEqual(created[0]['radius'],10.,places=6);np.testing.assert_allclose(created[0]['center'],[0,0],atol=1e-9)
    def test_center_arc_is_an_arc_and_can_pass_half_a_turn(self):
        created=self.draw('center_arc',[(0,0),(10,0),(0,10)])
        self.assertEqual(created[0]['kind'],'arc')
        # Dragging the end point round the far side keeps growing the sweep past 180 degrees.
        ws=self.ws;ws.arc_sweep=None
        for angle in (60,120,170,200,250):
            geometry=ws.center_arc_geometry([0,0],[10,0],[10*math.cos(math.radians(angle)),10*math.sin(math.radians(angle))])
        self.assertAlmostEqual(math.degrees(ws.arc_sweep),250,places=3)
        self.assertEqual(len(geometry),3)
    def test_ellipse_is_created_with_the_clicked_extents(self):
        created=self.draw('ellipse',[(0,0),(20,0),(0,8)])
        self.assertEqual(created[0]['kind'],'ellipse');self.assertEqual(created[0]['major'],[20.,0.]);self.assertEqual(created[0]['minor_radius'],8.)


class SolidTools(Base):
    def test_sweep_and_pipe_paths_are_picked_in_the_workspace(self):
        w=self.w;ws=self.ws
        self.sketch('XY',[entity('circle',center=[0.,0.],radius=3.)])
        self.sketch('XZ',[entity('line',a=[0.,0.],b=[0.,20.]),entity('arc',a=[0.,20.],mid=[3.,26.],b=[10.,28.])])
        path_sketch=list(w.doc.sketches.values())[1];frame=w.doc.frames[path_sketch['id']]
        position=ws.project_local(np.array([[0.,10.]]),frame)[0]
        w.start_solid_tool('sweep');self.app.processEvents()
        self.assertTrue(ws.extrude_selecting);self.assertIsNone(w.draft['source'])
        profile_sketch=list(w.doc.sketches.values())[0];region=profile_regions(profile_sketch)[0]
        w.profile_picked(dict(type='sketch',sketch=profile_sketch['id'],entities=region['entities'],holes=region['holes'],profile_mode='nested'))
        self.assertTrue(ws.path_picking)
        hit=ws.curve_at(QPointF(float(position[0]),float(position[1])))
        self.assertEqual(len(hit['entities']),2)      # the line and the arc joined to it
        w.path_picked(dict(sketch=hit['sketch'],entities=list(hit['entities'])));self.app.processEvents()
        self.assertEqual(len(w.draft['path']['entities']),2);self.assertGreaterEqual(len(ws.reference_highlight),3)
        w.preview_feature(quiet=True);self.assertEqual(self.errors,[])
        w.cancel();self.app.processEvents()
        w.start_advanced_tool('pipe');self.app.processEvents()
        self.assertTrue(ws.path_picking)

    def test_patterns_work_straight_away(self):
        w=self.w
        self.sketch('XY',[entity('rectangle',center=[0.,0.],width=60.,height=40.)]);self.extrude(0,10.)
        self.sketch('XY',[entity('circle',center=[-20.,0.],radius=4.)]);self.extrude(1,6.,'cut')
        for kind in ('feature_rectangular','feature_circular','feature_mirror'):
            w.start_advanced_tool(kind);self.app.processEvents()
            self.assertEqual(len(w.draft['targets']),1);self.assertEqual(len(w.draft['features']),1)
            w.preview_feature(quiet=True);self.assertTrue(w.preview_active,kind)
            w.cancel();self.app.processEvents()

    def test_thread_from_clicked_cylinder_cuts_the_body(self):
        w=self.w
        self.sketch('XY',[entity('circle',center=[0.,0.],radius=8.)]);self.extrude(0,25.)
        w.start_advanced_tool('thread');self.app.processEvents()
        index=next(i for i,f in enumerate(self.ws.faces) if f.geomType()=='CYLINDER')
        w.pick_solid_face(index);self.app.processEvents()
        self.assertAlmostEqual(w.draft['radius'],8.);self.assertAlmostEqual(w.draft['height'],25.)
        self.assertEqual(w.draft['thread_type'],'external')
        w.preview_feature(quiet=True);self.assertTrue(w.preview_active)

    def test_a_new_extrusion_starts_at_zero_depth(self):
        w=self.w
        self.sketch('XY',[entity('rectangle',center=[0.,0.],width=60.,height=40.)])
        w.start_extrude();self.app.processEvents()
        sketch=list(w.doc.sketches.values())[0];region=profile_regions(sketch)[0]
        w.extrusion_picked(dict(type='sketch',sketch=sketch['id'],entities=region['entities'],holes=region['holes'],profile_mode='nested'))
        self.assertEqual(w.draft['depth'],0.)
        w.preview_feature(quiet=True);self.assertEqual(self.errors,[])   # reported in the status bar, no dialog

    def test_surface_submenu_lists_all_rows(self):
        w=self.w;palette=w.tool_palettes['solid_tools'];palette.toggle();self.app.processEvents()
        action=next(b.property('_action') for b in palette.buttons if b.property('_action').menu() and b.property('_action').menu() is w.surface_menu)
        palette.activate(action);self.app.processEvents()
        self.assertGreater(palette.height(),200)
        self.assertGreater(palette.scroll.height(),150)

    def test_construction_plane_glows_under_the_cursor(self):
        w=self.w;ws=self.ws
        self.sketch('XY',[entity('rectangle',center=[0.,0.],width=60.,height=40.)]);self.extrude(0,10.)
        w.start_solid_tool('construction_plane','offset');w.apply_feature();self.app.processEvents()
        w.start_sketch();self.app.processEvents()
        ws.grab();self.app.processEvents()
        self.assertTrue(ws.construction_polygons)
        poly=next(iter(ws.construction_polygons.values()));centre=poly.boundingRect().center()
        hit=ws.pick(centre)
        self.assertEqual(hit['type'],'construction')


if __name__=='__main__':unittest.main()
