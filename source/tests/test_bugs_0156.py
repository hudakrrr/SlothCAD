"""Regression tests for the 0.15.6 bug list: hidden bodies, New body + Combine cut, two-sided
extrusion handles, selectable/deletable sketch dimensions, Fusion keys, timeline right-click
and the sketch view turn."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtCore import Qt,QEvent,QPointF
from PySide6.QtGui import QKeyEvent,QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity,profile_regions


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.resize(1300,860);self.w.show();self.app.processEvents()
        self.ws=self.w.workspace;self.errors=[];self.w.error=lambda e,*a:self.errors.append(str(e))
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()
    def sketch(self,entities):
        w=self.w;w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        w.draft['entities']=entities;self.ws.active=w.draft;w.show_editor();w.finish_sketch();self.app.processEvents()
    def extrude(self,index,depth,operation,**extra):
        w=self.w;s=list(w.doc.sketches.values())[index];r=profile_regions(s)[0]
        w.start_extrude();self.app.processEvents()
        w.extrusion_picked(dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested'))
        w.draft.update(depth=depth,operation=operation,**extra);w.show_editor();self.app.processEvents()
    def apply(self):self.w.apply_feature();self.app.processEvents()
    def volumes(self):return sorted(round(b.Volume(),1) for b in self.w.doc.solids())


class Bodies(Base):
    def box_and_cylinder(self):
        self.sketch([entity('rectangle',center=[0,0],width=40,height=40)]);self.extrude(0,10,'add');self.apply()
        self.sketch([entity('circle',center=[0,0],radius=8)])

    def test_new_body_keeps_overlapping_bodies_separate(self):
        self.box_and_cylinder();self.extrude(1,20,'new');self.apply()
        self.assertEqual(self.volumes(),[4021.2,16000.0]);self.assertEqual(self.errors,[])

    def test_hidden_body_is_not_joined_or_cut(self):
        self.box_and_cylinder();self.w.doc.display.setdefault('bodies',{})['0']=False;self.w.refresh()
        self.extrude(1,20,'add');self.apply()
        self.assertEqual(self.volumes(),[4021.2,16000.0])
        self.assertTrue(self.w.doc.features[-1].get('exclude_bodies'))
        self.assertIn(False,self.w.doc.display['bodies'].values())     # the box is still hidden

    def test_cut_through_one_body_leaves_an_overlapping_body_whole(self):
        self.box_and_cylinder();self.extrude(1,20,'new');self.apply()
        self.sketch([entity('circle',center=[-15,-15],radius=3)]);self.extrude(2,30,'cut');self.apply()
        self.assertEqual(self.volumes(),[4021.2,15717.3]);self.assertEqual(self.errors,[])

    def test_combine_cut_picked_in_the_viewport(self):
        self.box_and_cylinder();self.extrude(1,20,'new');self.apply()
        bodies=self.w.doc.solids();box=max(bodies,key=lambda b:b.Volume());cylinder=min(bodies,key=lambda b:b.Volume())
        face=lambda body:next(i for i,f in enumerate(self.ws.faces) if any(f.isSame(x) for x in body.Faces()))
        self.w.start_body_tool('body_combine');self.app.processEvents()
        self.w.slot_clicked(dict(type='face',index=face(box)));self.w.slot_clicked(dict(type='face',index=face(cylinder)))
        self.assertEqual((len(self.w.draft['targets']),len(self.w.draft['tools'])),(1,1))
        self.w.draft['operation']='cut';self.apply()
        self.assertEqual(self.volumes(),[13989.4]);self.assertEqual(self.errors,[])


class TwoSidedExtrusion(Base):
    def test_two_arrows_tab_and_values(self):
        self.sketch([entity('rectangle',center=[0,0],width=40,height=40)])
        self.extrude(0,10,'add',direction='two sides',depth2=4)
        g=self.ws.gizmo
        self.assertEqual(len(g.handles()),2);self.assertEqual(g.state['labels'],['Side 1','Side 2'])
        self.assertLess(float(g.state['directions'][0]@g.state['directions'][1]),0)    # pointing apart
        g.key(QKeyEvent(QEvent.KeyPress,Qt.Key_Tab,Qt.NoModifier));self.assertEqual(g.axis,1)
        g.editor.setValue(7.5);self.app.processEvents();self.assertAlmostEqual(self.w.draft['depth2'],7.5)
        self.apply();box=self.w.doc.solids()[0].BoundingBox()
        self.assertAlmostEqual(box.zmin,-7.5,places=5);self.assertAlmostEqual(box.zmax,10,places=5)


class SketchDimensions(Base):
    def test_typed_values_become_dimensions_that_delete_alone(self):
        w,ws=self.w,self.ws
        w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents();ws.snap_enabled=False
        w.set_tool('circle');ws.cursor=np.array([0.,0.]);ws.draw_point(np.array([0.,0.]));ws.cursor=np.array([5.,0.])
        QTest.keyClicks(ws,'6');QTest.keyClick(ws,Qt.Key_Return);self.app.processEvents()
        dims=[c for c in w.draft['constraints'] if c['kind']=='dimension']
        self.assertEqual([(c['mode'],c['value']) for c in dims],[('diameter',12.0)])
        w.set_tool('select');ws.fit();ws.repaint();self.app.processEvents()
        rect=next(r for r,cid in ws.constraint_label_rects if cid==dims[0]['id'])
        QTest.mouseClick(ws,Qt.LeftButton,Qt.NoModifier,rect.center().toPoint());self.app.processEvents()
        self.assertEqual(ws.selected_constraint,dims[0]['id'])
        QTest.keyClick(ws,Qt.Key_Delete);self.app.processEvents()
        self.assertEqual(len(w.draft['entities']),1);self.assertFalse([c for c in w.draft.get('constraints',[]) if c['kind']=='dimension'])


class KeysAndView(Base):
    def test_fusion_keys(self):
        w,ws=self.w,self.ws
        w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        for key,tool in [(Qt.Key_L,'line'),(Qt.Key_R,'rectangle'),(Qt.Key_C,'circle'),(Qt.Key_T,'trim'),(Qt.Key_O,'offset')]:
            QTest.keyClick(ws,key);self.assertEqual(ws.tool,tool)
        QTest.keyClick(ws,Qt.Key_D);self.assertEqual((ws.tool,w.constraint_kind),('constraint','dimension'))

    def test_timeline_right_click_does_not_open_the_tool_description(self):
        self.sketch([entity('rectangle',center=[0,0],width=40,height=40)])
        button=self.w.timeline_buttons[0]
        event=QMouseEvent(QEvent.MouseButtonPress,QPointF(5,5),QPointF(5,5),Qt.RightButton,Qt.RightButton,Qt.NoModifier)
        self.assertFalse(self.w.help_filter.eventFilter(button,event))

    def test_turn_view_is_a_clockwise_quarter_turn_in_sketches_only(self):
        w,ws=self.w,self.ws
        self.assertTrue(w.rotate_view_button.isHidden())
        w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents();ws.finish_camera_animation()
        self.assertFalse(w.rotate_view_button.isHidden())
        o,x=ws.project_local([[0,0],[10,0]],ws.active_frame)
        w.rotate_view_button.click();ws.finish_camera_animation()
        o2,x2=ws.project_local([[0,0],[10,0]],ws.active_frame)
        before,after=x-o,x2-o2
        self.assertAlmostEqual(after[0],0,places=6);self.assertAlmostEqual(after[1],before[0],places=6)   # +X now points down the screen


if __name__=='__main__':unittest.main()
