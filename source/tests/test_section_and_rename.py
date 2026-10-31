"""Section analysis (exact clipping, cut face, drag arrow, face plane) and browser renaming."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity,profile_regions
from section_ui import clip_mesh


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window();self.w.resize(1300,860);self.w.show();self.app.processEvents()
        self.ws=self.w.workspace;self.errors=[];self.w.error=lambda e,*a:self.errors.append(str(e))
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()
    def body(self,entities,depth=20,operation='add'):
        w=self.w;w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        w.draft['entities']=entities;self.ws.active=w.draft;w.show_editor();w.finish_sketch();self.app.processEvents()
        s=list(w.doc.sketches.values())[-1];r=profile_regions(s)[0]
        w.start_extrude();w.extrusion_picked(dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested'))
        w.draft.update(depth=depth,operation=operation);w.apply_feature();self.app.processEvents()
    def items(self,kind):
        found=[]
        def walk(node):
            for i in range(node.childCount()):
                child=node.child(i);data=child.data(0,Qt.UserRole)
                if data and data.get('type')==kind:found.append(child)
                walk(child)
        walk(self.w.objects.invisibleRootItem());return found


class Section(Base):
    def test_clip_mesh_splits_crossing_triangles_at_the_plane(self):
        vertices=np.array([[0,0,0],[10,0,0],[0,0,10]],float)
        out,triangles,owner=clip_mesh(vertices,np.array([[0,1,2]]),np.array([0,0,1.]),4.)
        self.assertLessEqual(float(out[triangles].reshape(-1,3)[:,2].max()),4+1e-9)
        self.assertTrue(np.isclose(out[triangles].reshape(-1,3)[:,2],4).any());self.assertTrue((owner==0).all())

    def test_cut_face_drag_and_face_plane(self):
        self.body([entity('rectangle',center=[0,0],width=40,height=30)]);self.body([entity('circle',center=[0,0],radius=6)],operation='cut')
        w,ws=self.w,self.ws;ws.fit();w.inspect_buttons['section'].click();self.app.processEvents()
        self.assertTrue(w.section_button.isChecked());self.assertAlmostEqual(w.section_panel.position.value(),10.)
        ws.compute_section_cap();cap=ws.section_cap_for(ws.section)
        area=sum(float(np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1).sum())/2 for t,_ in cap)
        self.assertAlmostEqual(area,40*30-np.pi*36,delta=2.)      # the cut face, with the hole left open
        base,tip,_=ws.section_handle();start=QPoint(*map(int,(base+tip)/2))
        QTest.mousePress(ws,Qt.LeftButton,Qt.NoModifier,start);QTest.mouseMove(ws,start+QPoint(0,-60));ws.flush_motion()
        QTest.mouseRelease(ws,Qt.LeftButton,Qt.NoModifier,start+QPoint(0,-60));self.app.processEvents()
        self.assertGreater(w.section_panel.position.value(),10.)
        index=next(i for i,f in enumerate(ws.faces) if f.geomType()=='PLANE' and abs(f.normalAt(f.Center()).x-1)<1e-6)
        w.pick_section_face();w.section_face_picked(index)
        self.assertEqual(w.section_panel.plane.currentData(),'face');self.assertTrue(np.allclose(ws.section['normal'],[1,0,0]))
        w.inspect_buttons['section'].click();self.assertIsNone(ws.section);self.assertEqual(self.errors,[])


class Rename(Base):
    def test_rename_sketch_with_undo_and_body_name_follows_the_body(self):
        self.body([entity('rectangle',center=[0,0],width=40,height=30)],10);self.body([entity('circle',center=[50,0],radius=5)],10)
        w=self.w;w.rebuild_objects()
        self.items('sketches')[0].setText(0,'Base plate');self.app.processEvents()
        self.assertEqual(w.doc.features[0]['name'],'Base plate')
        w.undo();self.assertNotEqual(w.doc.features[0]['name'],'Base plate');w.redo();self.assertEqual(w.doc.features[0]['name'],'Base plate')
        w.rebuild_objects();self.items('bodies')[1].setText(0,'Pin');self.app.processEvents()
        self.assertEqual(w.doc.body_names()[1],'Pin')
        self.body([entity('circle',center=[0,0],radius=3)],10,'cut')
        self.assertIn('Pin',w.doc.body_names());self.assertEqual(self.errors,[])


    def test_tools_show_the_browser_names(self):
        self.body([entity('rectangle',center=[0,0],width=40,height=30)],10);self.body([entity('circle',center=[50,0],radius=5)],10,'new')
        w=self.w;w.rebuild_objects()
        self.items('bodies')[0].setText(0,'Plate');self.items('bodies')[1].setText(0,'Pin');self.items('sketches')[1].setText(0,'Pin sketch')
        from references import body_reference
        w.start_body_tool('body_combine');bodies=w.doc.solids()
        w.set_slot_value(w.current_slots[0],body_reference(bodies[0],0,2,w.doc.solid));w.set_slot_value(w.current_slots[1],body_reference(bodies[1],1,2,w.doc.solid))
        self.assertEqual([w.describe_slot(s) for s in w.current_slots],['Plate','Pin'])
        listing=w.widgets['targets'];self.assertEqual([listing.item(i).text().split(' · ')[0] for i in range(listing.count())],['Plate','Pin'])
        w.cancel();w.start_extrude();self.assertIn('Pin sketch · profile 1',[name for name,_ in w.profile_choices]);w.cancel()
        self.body([entity('circle',center=[0,0],radius=3)],10,'cut')      # the plate changes after the 'new' extrusion
        w.timeline_edit(3);result=w.tool_context()[0];self.assertEqual(w.body_label(result,0),'Plate');w.cancel()
        self.assertEqual(self.errors,[])


class Export(Base):
    def test_hidden_bodies_are_left_out_of_exports(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PySide6.QtWidgets import QFileDialog
        self.body([entity('rectangle',center=[0,0],width=40,height=30)],10);self.body([entity('circle',center=[50,0],radius=5)],10,'new')
        w=self.w;w.doc.display.setdefault('bodies',{})['1']=False;w.refresh()
        captured=[]
        original=w.doc.export_items
        with patch.object(w.doc,'export_items',side_effect=lambda visible_only=False:captured.append(original(visible_only)) or captured[-1]):
            with tempfile.TemporaryDirectory() as folder:
                target=str(Path(folder)/'out.step')
                with patch('analysis_ui._setting',side_effect=lambda key,default:default),patch.object(QFileDialog,'getSaveFileName',return_value=(target,'')):
                    w.export_format('step')
                self.assertTrue(Path(target).exists())
        self.assertEqual(len(captured[-1]),1);self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
