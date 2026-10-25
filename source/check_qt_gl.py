"""Run the actual PySide renderer in a real Qt OpenGL context (desktop session)."""
from types import SimpleNamespace
import numpy as np
from PySide6.QtGui import QGuiApplication,QOpenGLContext,QOffscreenSurface
from PySide6.QtOpenGL import QOpenGLFramebufferObject,QOpenGLFramebufferObjectFormat
from gpu_renderer import GpuRenderer,surface_format

def main():
    app=QGuiApplication([])
    context=QOpenGLContext();context.setFormat(surface_format())
    if not context.create():raise RuntimeError('No Qt OpenGL context. Run this check in your desktop session.')
    surface=QOffscreenSurface();surface.setFormat(context.format());surface.create()
    if not context.makeCurrent(surface):raise RuntimeError('Could not make the Qt OpenGL context current.')
    fmt=QOpenGLFramebufferObjectFormat();fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    target=QOpenGLFramebufferObject(64,64,fmt);assert target.isValid()
    renderer=GpuRenderer(context);gl=context.functions()
    view=SimpleNamespace(width=lambda:64,height=lambda:64,devicePixelRatioF=lambda:1,
        defaultFramebufferObject=target.handle,show_aa=True,revision=1,
        vertices=np.array([[-.8,-.8,0],[.8,-.8,0],[0,.8,0]]),triangles=np.array([[0,1,2]]),face_ids=np.array([0]),body_ids=np.array([0]),
        triangle_materials=lambda:(np.array([[75.,174.,214.]]),np.array([0.])),
        rotation=lambda:np.eye(3),scale=lambda:32,span=2,center=np.zeros(3),pan=np.zeros(2),hover=None,selected_source=None,mode='model',theme='dark')
    for aa,mode in [(False,'model'),(True,'model'),(True,'sketch')]:
        view.show_aa=aa;view.mode=mode;view.revision+=1
        target.bind();gl.glClearColor(0,0,0,1);gl.glClear(0x4000)
        renderer.draw(view)
        error=gl.glGetError();assert error==0, f'{mode}, AA {aa}: 0x{error:04x}'
        image=target.toImage();assert image.pixelColor(32,32).blue()>30, 'Solid did not render'
    # Perspective camera, section plane (cut and cap colour) and a translucent body.
    view.mode='model';view.show_aa=True
    cases=[('perspective',dict(eye_distance=lambda:6.,section_plane=lambda:None,has_translucent_bodies=lambda:False)),
           ('section',dict(eye_distance=lambda:None,section_plane=lambda:(np.array([0.,0.,1.]),-.5),has_translucent_bodies=lambda:False)),
           ('translucent',dict(eye_distance=lambda:None,section_plane=lambda:None,has_translucent_bodies=lambda:True,
                               triangle_materials=lambda:(np.array([[75.,174.,214.]]),np.array([40.]))))]
    for name,extra in cases:
        for key,value in extra.items():setattr(view,key,value)
        view.revision+=1
        target.bind();gl.glClearColor(0,0,0,1);gl.glClear(0x4000)
        renderer.draw(view)
        error=gl.glGetError();assert error==0, f'{name}: 0x{error:04x}'
        if name!='section':
            assert target.toImage().pixelColor(32,32).blue()>20, name+' did not render'
    print('PASS: actual PySide mesh drawing, float uniforms, and supersampling in model/sketch mode; no GL errors.')
    print('PASS: perspective camera, section plane and translucent bodies draw without GL errors.')
    renderer.destroy();del target;context.doneCurrent()
if __name__=='__main__':main()
