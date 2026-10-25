import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import Mock,patch,call
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtCore import QEvent
from workspace import Workspace
from gpu_renderer import prepare_solid_state
from model import Document
from test_sketch_model import base_part

class SolidDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        # A global QPainter mock must not intercept queued paints from prior windows.
        self.app.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents()
        self.w=Workspace();self.w.resize(600,400);self.w.set_scene(Document(base_part()).solid,[],True)
    def tearDown(self):self.w.gpu_enabled=False;self.w.hide();self.w.deleteLater();self.app.processEvents()
    def test_solid_state_resets_depth_and_visibility_before_clear(self):
        gl=Mock();prepare_solid_state(gl,True)
        calls=gl.mock_calls
        self.assertLess(calls.index(call.glClearDepthf(1.0)),calls.index(call.glClear(0x0100)))
        gl.glDepthMask.assert_called_once_with(True);gl.glColorMask.assert_called_once_with(True,True,True,True)
        gl.glDepthRangef.assert_called_once_with(0.,1.)
        for cap in (0x0B90,0x0B44,0x0C11):gl.glDisable.assert_any_call(cap)
    def test_gpu_draw_failure_displays_body_and_retains_error(self):
        self.w.gpu_enabled=True;self.w.rasterizer=None
        self.w.gpu=Mock();self.w.gpu.info={};self.w.gpu.uploads=0;self.w.gpu.draw.side_effect=RuntimeError('simulated GPU draw failure')
        image=QImage(600,400,QImage.Format_ARGB32_Premultiplied);painter=QPainter(image)
        factory=Mock(return_value=painter);factory.Antialiasing=QPainter.Antialiasing
        try:
            with patch('workspace.QPainter',factory):self.w.paintGL()
        finally:
            if painter.isActive():painter.end()
        self.assertTrue(self.w.software_body_fallback);self.assertIn('simulated GPU draw failure',self.w.graphics_diagnostics())
        self.assertTrue(np.any(self.w.face_buffer>=0));self.assertNotEqual(image.pixelColor(300,200),QColor(self.w.theme_color('#eaf0f5')))
    def test_software_body_renderer_is_created_only_when_needed(self):
        self.w.rasterizer=None;image=QImage(600,400,QImage.Format_ARGB32_Premultiplied);image.fill(0)
        p=QPainter(image);self.w.draw_software_body(p);p.end()
        self.assertIsNotNone(self.w.rasterizer);self.assertGreater(image.pixelColor(300,200).alpha(),0)
    def test_visibility_toggle_restores_mesh_after_empty_scene(self):
        solid=Document(base_part()).solid;revision=self.w.revision
        self.w.set_scene(None,[]);self.assertEqual(len(self.w.triangles),0)
        self.w.set_scene(solid,[],True);self.assertGreater(len(self.w.triangles),0);self.assertGreater(self.w.revision,revision)
