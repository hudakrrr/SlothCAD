import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from unittest.mock import patch
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from app import Window
from model import Document, ModelError, new_feature
from i18n import set_language


def box(**fields):
    f=new_feature();f.update(width=40,height=30,depth=10,id='box00001',name='Box');f.update(fields);return f


class ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.resize(900,700);self.w.show();self.app.processEvents()
        self.w.doc=Document([box()]);self.w.refresh(True);self.app.processEvents()
        self.ws=self.w.workspace

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    # ---- perspective ----------------------------------------------------------------------
    def test_orthographic_by_default_and_perspective_is_a_projective_map(self):
        points=np.array([[0,0,0],[20,15,0],[20,15,10],[-20,-15,10]],float)
        ortho=self.ws.project(points)[0]
        self.ws.perspective=True;self.app.processEvents()
        persp=self.ws.project(points)[0]
        self.assertIsNotNone(self.ws.eye_distance())
        self.assertFalse(np.allclose(ortho,persp))
        # the view centre stays where it was
        centre=self.ws.project([self.ws.center])[0][0]
        self.ws.perspective=False
        np.testing.assert_allclose(centre,self.ws.project([self.ws.center])[0][0],atol=1e-9)

    def test_unproject_and_local_at_invert_the_perspective_projection(self):
        self.ws.perspective=True
        for depth_point in ([5.,3.,10.],[-12.,8.,0.],[0.,0.,0.]):
            screen,depth=self.ws.project([depth_point])
            back=self.ws.unproject(QPointF(*screen[0]),float(depth[0]))
            np.testing.assert_allclose(back,depth_point,atol=1e-6)
        frame=dict(origin=[0.,0.,10.],u=[1.,0.,0.],normal=[0.,0.,1.])
        for local in ([3.,4.],[-9.,2.],[0.,0.]):
            world=np.array([local[0],local[1],10.])
            screen=self.ws.project([world])[0][0]
            np.testing.assert_allclose(self.ws.local_at(QPointF(*screen),frame),local,atol=1e-6)

    def test_sketches_stay_orthographic(self):
        self.ws.perspective=True
        self.assertIsNotNone(self.ws.eye_distance())
        self.ws.mode='sketch'
        self.assertIsNone(self.ws.eye_distance())
        self.ws.mode='model'

    def test_perspective_flag_is_saved_with_the_project(self):
        self.w.set_perspective(True);self.assertTrue(self.ws.perspective);self.assertTrue(self.w.perspective_button.isChecked())
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'v.fcad';self.w.doc.save(path)
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['display']['perspective'])
            loaded=Document.load(path);self.assertTrue(loaded.display['perspective'])
        self.w.set_perspective(False);self.assertNotIn('perspective',self.w.doc.display)

    # ---- picking index ---------------------------------------------------------------------
    def test_grid_index_picks_exactly_what_a_full_scan_picks(self):
        self.ws.gpu_enabled=True        # use the CPU index that backs picking in the OpenGL view
        try:
            screen,depth=self.ws.project(self.ws.vertices)
            corners=screen[self.ws.triangles];zs=depth[self.ws.triangles]
            def brute(x,y):
                a,b,c=corners[:,0],corners[:,1],corners[:,2]
                d=(b[:,1]-c[:,1])*(a[:,0]-c[:,0])+(c[:,0]-b[:,0])*(a[:,1]-c[:,1])
                ok=np.abs(d)>1e-10;d=np.where(ok,d,1.)
                u=((b[:,1]-c[:,1])*(x-c[:,0])+(c[:,0]-b[:,0])*(y-c[:,1]))/d
                v=((c[:,1]-a[:,1])*(x-c[:,0])+(a[:,0]-c[:,0])*(y-c[:,1]))/d
                mask=ok&(u>=-1e-7)&(v>=-1e-7)&(u+v<=1.0000001)
                if not mask.any():return -1
                depths=np.where(mask,u*zs[:,0]+v*zs[:,1]+(1-u-v)*zs[:,2],-np.inf)
                return int(self.ws.face_ids[int(np.argmax(depths))])
            rng=np.random.default_rng(3);hits=0
            for _ in range(150):
                x,y=rng.uniform(0,self.ws.width()),rng.uniform(0,self.ws.height())
                expected=brute(x,y);got=self.ws.body_hit(QPointF(x,y))[0]
                self.assertEqual(got,expected);hits+=expected>=0
            self.assertGreater(hits,10)
        finally:self.ws.gpu_enabled=False

    # ---- section view ----------------------------------------------------------------------
    def test_section_removes_the_cut_side_from_picking_and_software_drawing(self):
        total=len(self.ws.triangles)
        self.w.toggle_section(True);self.app.processEvents()
        panel=self.w.section_panel
        panel.position.setValue(10.)        # at the top face: nothing is cut yet
        self.assertEqual(int(self.ws.kept_triangles().sum()),total)
        panel.position.setValue(5.);self.app.processEvents()
        kept=self.ws.kept_triangles();self.assertLess(int(kept.sum()),total)
        panel.flip.click();self.app.processEvents()
        self.assertTrue(np.allclose(self.ws.section['normal'],[0,0,-1]))     # Change side keeps the other half
        other=self.ws.kept_triangles()
        self.assertLess(int(other.sum()),total);self.assertFalse(np.any(kept&other&False))
        panel.flip.click();self.assertTrue(np.allclose(self.ws.section['normal'],[0,0,1]))      # and back
        self.w.end_section();self.assertIsNone(self.ws.section_plane());self.assertFalse(self.w.section_panel.isVisible())
        self.assertFalse(self.w.section_button.isChecked())

    # ---- saved views, zoom to selection, opacity ------------------------------------------
    def test_save_restore_and_delete_a_camera_view(self):
        self.ws.yaw,self.ws.pitch=123.,22.;self.ws.zoom=2.5
        with patch('section_ui.QInputDialog.getText',return_value=('Detail',True)):self.w.save_camera_view()
        self.assertIn('Detail',self.w.doc.display['views']);self.assertEqual(self.w.view_selector.currentData(),'view:Detail')
        self.ws.yaw,self.ws.pitch=10.,10.;self.ws.zoom=1.
        self.w.restore_camera_view('Detail')
        self.assertAlmostEqual(self.ws.yaw,123.);self.assertAlmostEqual(self.ws.zoom,2.5)
        with patch('section_ui.QInputDialog.getItem',return_value=('Detail',True)):self.w.delete_camera_view()
        self.assertNotIn('views',self.w.doc.display)
        with tempfile.TemporaryDirectory() as folder:      # views survive a save and load
            self.w.doc.display['views']={'A':dict(yaw=1.,pitch=2.,center=[0,0,0],span=50.,zoom=1.,pan=[0,0],perspective=False)}
            path=Path(folder)/'v.fcad';self.w.doc.save(path);self.assertIn('A',Document.load(path).display['views'])

    def test_bad_saved_views_are_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'v.fcad';self.w.doc.save(path)
            data=json.loads(path.read_text(encoding='utf-8'));data['display']['views']=[1,2];path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ModelError):Document.load(path)

    def test_zoom_to_selection_frames_only_the_selected_face(self):
        face=max(range(len(self.ws.faces)),key=lambda i:self.ws.faces[i].Center().z)
        before=self.ws.span
        self.ws.solid_selected_faces={face}
        self.assertTrue(self.ws.fit_selection())
        np.testing.assert_allclose(self.ws.center,[0,0,10],atol=1e-6)
        self.ws.solid_selected_faces=set()
        self.assertFalse(self.ws.fit_selection())            # nothing selected: fits everything

    def test_opacity_is_encoded_for_the_renderer_and_validated(self):
        self.w.doc.display['materials']={'0':{'color':'#ff0000','finish':'metallic','opacity':.4}}
        self.w.refresh();self.app.processEvents()
        colors,codes=self.ws.triangle_materials()
        self.assertTrue(self.ws.has_translucent_bodies())
        self.assertEqual(float(codes[0]),1+10*4)                 # metallic finish, four tenths
        self.w.doc.display['materials']={'0':{'color':'#ff0000','finish':'matte'}}
        self.w.refresh();self.assertFalse(self.ws.has_translucent_bodies())
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'o.fcad';self.w.doc.display['materials']={'0':{'color':'#ff0000','finish':'matte','opacity':1.5}}
            self.w.doc.save(path)
            with self.assertRaises(ModelError):Document.load(path)

    def test_saving_writes_a_thumbnail_used_by_the_recent_list(self):
        from sessions_ui import thumbnail_path
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'SLOTHCAD_THUMBNAIL_DIR':str(Path(folder)/'thumbs')}):
            target=Path(folder)/'thumb.fcad'
            self.w.path=target;self.assertTrue(self.w.save());self.app.processEvents()
            picture=thumbnail_path(target);self.assertTrue(picture.exists())
            from PySide6.QtGui import QImage
            image=QImage(str(picture));self.assertFalse(image.isNull());self.assertEqual(image.width(),220)
            with patch.object(type(self.w),'recent_files',return_value=[str(target)]):
                self.w.welcome.refresh_recent()
            self.assertEqual(self.w.welcome.recent.count(),1)


if __name__=='__main__':
    unittest.main()
