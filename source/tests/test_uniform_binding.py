"""Binding dispatch checks; check_qt_gl.py also verifies GL uniform type correctness."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import numpy as np
from PySide6.QtGui import QVector3D
from PySide6.QtOpenGL import QOpenGLShaderProgram
from PySide6.QtWidgets import QApplication
from gpu_renderer import GpuRenderer
class UniformBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_real_qt_accepts_integer_location_for_vector_float_and_int(self):
        p=QOpenGLShaderProgram()
        for value in (QVector3D(0,0,5),.55,1):p.setUniformValue(-1,value)
    def test_production_draw_uses_locations_for_every_uniform(self):
        real=QOpenGLShaderProgram();calls=[]
        class Program:
            def bind(self):return True
            def setUniformValue(self,location,value):
                if not isinstance(location,int):raise AssertionError('Uniform name overload used')
                calls.append(location);real.setUniformValue(-1,value)
            def __getattr__(self,name):return lambda *args:None
        class Noop:
            def bind(self):return True
            def __getattr__(self,name):return lambda *args:None
        class GL(Noop):
            def glGetIntegerv(self,*args):return 8
            def glUniform1i(self,location,value):
                calls.append(location);self.highlight=value
            def glUniform1f(self,location,value):
                calls.append(location);self.ghost=value
        renderer=object.__new__(GpuRenderer);renderer.gl=GL();renderer.program=Program();renderer.vao=Noop();renderer.buffer=Noop();renderer.revision=1;renderer.count=3;renderer.info={}
        names=('center','right','up','towards','projection','offset','highlighted','ghost','background','eye','clipPlane','clipOn','alphaPass');renderer.uniforms=dict(zip(names,range(13)))
        w=SimpleNamespace(width=lambda:600,height=lambda:400,devicePixelRatioF=lambda:1,defaultFramebufferObject=lambda:1,show_aa=True,triangles=np.array([[0,1,2]]),revision=1,rotation=lambda:np.eye(3),scale=lambda:5,span=20,vertices=np.array([[0,0,0],[1,0,0],[0,1,0]]),center=np.array([0,0,5]),pan=np.array([0,0]),hover=None,selected_source=None,mode='model',theme='dark')
        renderer.draw(w);self.assertEqual(calls,list(range(9))+[9,11,12]);self.assertEqual(renderer.info['drawn vertices'],3);self.assertEqual(renderer.gl.highlight,-1)
