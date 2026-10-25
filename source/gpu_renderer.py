"""Persistent OpenGL mesh buffers; camera movement changes uniforms only."""
import itertools
import numpy as np
from PySide6.QtGui import QSurfaceFormat, QVector3D, QVector2D
from PySide6.QtOpenGL import (QOpenGLShader, QOpenGLShaderProgram, QOpenGLBuffer,
                             QOpenGLVertexArrayObject, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat)

VERTEX = '''#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
layout(location=2) in float face;
layout(location=3) in vec3 bodyColor;
layout(location=4) in float materialCode;
uniform vec3 center, right, up, towards;
uniform vec3 projection;
uniform vec3 offset;
uniform float eye;      // 1 / camera distance; 0 selects the orthographic view
out vec3 lightingNormal;
flat out int faceId;
out vec3 baseColor;
flat out int materialId;
out vec3 worldPos;
void main() {
 vec3 p=position-center;
 float depth=dot(p,towards);
 float w=max(1.0-depth*eye,0.02);
 gl_Position=vec4(dot(p,right)*projection.x+offset.x*w,
                  dot(p,up)*projection.y+offset.y*w,
                  -depth*projection.z,w);
 lightingNormal=vec3(dot(normal,right),dot(normal,up),dot(normal,towards));
 faceId=int(face+0.5);
 baseColor=bodyColor; materialId=int(materialCode+0.5); worldPos=position;
}'''
FRAGMENT = '''#version 330 core
in vec3 lightingNormal;
flat in int faceId;
in vec3 baseColor;
flat in int materialId;
in vec3 worldPos;
uniform int highlighted;
uniform float ghost;
uniform vec3 background;
uniform vec4 clipPlane;      // keeps dot(position, xyz) <= w
uniform float clipOn;
uniform float alphaPass;     // 0: opaque bodies, 1: translucent bodies
out vec4 color;
void main() {
 if(clipOn>0.5 && dot(worldPos,clipPlane.xyz)>clipPlane.w) discard;
 // materialId is finish + 10 * tenths of opacity (no tens digit means fully opaque)
 int level=materialId/10;
 int finish=materialId-level*10;
 float alpha=level>0 ? float(level)/10.0 : 1.0;
 if(alphaPass<0.5 && alpha<0.99) discard;
 if(alphaPass>0.5 && alpha>=0.99) discard;
 vec3 n=normalize(lightingNormal);
 float brightness=0.42+0.58*abs(dot(n,normalize(vec3(-0.3,0.4,0.85))));
 vec3 base=baseColor;
 if(finish==2){ float grain=0.86+0.14*sin(worldPos.x*2.2+sin(worldPos.y*0.45)*2.0); base*=grain; }
 float shade=finish==1 ? (0.24+0.76*brightness) : (finish==2 ? (0.55+0.45*brightness) : brightness);
 vec3 c=base*shade;
 if(finish==1){ float sparkle=pow(max(0.0,dot(n,normalize(vec3(-0.3,0.4,0.85)))),16.0); c+=vec3(0.28)*sparkle; }
 if(faceId==highlighted) c=mix(c,vec3(255,190,65)/255.0,0.45);
 // Seen from inside through the cut: the back of the surface stands in for the cut face.
 if(clipOn>0.5 && !gl_FrontFacing) c=vec3(0.86,0.58,0.22);
 c=mix(c,background,ghost);
 color=vec4(c,alpha);
}'''

# The grid as thin screen-space quads: drawn after the solids, depth-tested against them, at half
# strength. Only the parts of the grid that are in front of what is behind them show up, so a body
# below (or crossing) the grid plane is seen through it, and a body in front hides it.
GRID_VERTEX = '''#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 other;
layout(location=2) in float side;
uniform vec3 center, right, up, towards;
uniform vec3 projection;
uniform vec3 offset;
uniform vec2 viewport;
uniform float halfwidth;
uniform float bias;
uniform float flatDepth;
uniform float eye;
vec4 clipOf(vec3 q) {
 vec3 p=q-center;
 float depth=dot(p,towards);
 float w=max(1.0-depth*eye,0.02);
 return vec4(dot(p,right)*projection.x+offset.x*w,
             dot(p,up)*projection.y+offset.y*w,
             -(depth+bias)*projection.z,w);
}
void main() {
 vec4 a=clipOf(position);
 vec4 b=clipOf(other);
 vec2 d=(b.xy/b.w-a.xy/a.w)*0.5*viewport;
 float l=length(d);
 vec2 n=l>1e-6 ? vec2(-d.y,d.x)/l : vec2(0.0,1.0);
 a.xy+=n*side*halfwidth*2.0/viewport*a.w;
 if(flatDepth>0.5) a.z=0.0;
 gl_Position=a;
}'''
GRID_FRAGMENT = '''#version 330 core
uniform vec4 lineColor;
out vec4 color;
void main() { color=lineColor; }'''

RESOLVE_VERTEX = """#version 330 core
void main(){
 vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
 gl_Position=vec4(p*2.0-1.0,0,1);
}"""
RESOLVE_FRAGMENT = """#version 330 core
uniform sampler2D image;
uniform int factor;
out vec4 color;
void main(){
 ivec2 p=ivec2(gl_FragCoord.xy)*factor;
 color=vec4(0);
 for(int y=0;y<factor;y++) for(int x=0;x<factor;x++)
   color+=texelFetch(image,p+ivec2(x,y),0);
 color/=float(factor*factor);
}"""

# 32 M pixels let a 1000×700 viewport render 16× supersampling every frame, which
# is heavy for integrated GPUs. 9 M keeps 16× for small views and uses 4× otherwise.
def supersample_size(width,height,max_size,pixel_budget=9000000):
    for factor in (4,2):
        size=(factor*width,factor*height)
        if max(size)<=max_size and size[0]*size[1]<=pixel_budget:return size
    return None

def surface_format():
    fmt=QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24);fmt.setStencilBufferSize(8);fmt.setSamples(8)
    fmt.setSwapInterval(1)
    return fmt

def mesh_data(vertices,triangles,face_ids,body_ids=None,body_colors=None,material_codes=None,base_data=None):
    """Build GPU vertices. Keep the historical 7-float public format unless material data is requested."""
    extended=body_colors is not None or material_codes is not None
    if not len(triangles):return np.empty((0,11 if extended else 7),np.float32)
    if base_data is None:
        vertices=np.asarray(vertices,dtype=float)
        xyz=vertices[triangles]
        normals=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0])
        accumulated=np.zeros_like(vertices)
        for corner in range(3):np.add.at(accumulated,triangles[:,corner],normals)
        lengths=np.linalg.norm(accumulated,axis=1);lengths[lengths==0]=1
        accumulated/=lengths[:,None]
        base=np.column_stack((xyz.reshape(-1,3),accumulated[triangles].reshape(-1,3),np.repeat(face_ids,3)))
        base=np.ascontiguousarray(base,dtype=np.float32)
    else:
        base=np.asarray(base_data,dtype=np.float32)
        if base.shape!=(len(triangles)*3,7):raise ValueError('Invalid precomputed GPU base mesh.')
    if not extended:return np.ascontiguousarray(base,dtype=np.float32)
    if body_colors is None:body_colors=np.tile(np.array([[75,174,214]],dtype=float)/255.,(len(triangles),1))
    if material_codes is None:material_codes=np.zeros(len(triangles),dtype=float)
    return np.ascontiguousarray(np.column_stack((base,np.repeat(body_colors,3,axis=0),
        np.repeat(material_codes,3))),dtype=np.float32)

def prepare_solid_state(gl,antialias):
    """Isolate the solid pass from state left by Qt's 2D paint engine."""
    gl.glColorMask(True,True,True,True)
    gl.glDepthMask(True);gl.glClearDepthf(1.0);gl.glDepthRangef(0.0,1.0)
    for capability in (0x0BE2,0x0C11,0x0B90,0x0B44,0x8037,0x809E,0x80A0):
        gl.glDisable(capability) # blend, scissor, stencil, cull, offset, alpha/coverage
    gl.glEnable(0x0B71);gl.glDepthFunc(0x0203)
    (gl.glEnable if antialias else gl.glDisable)(0x809D)
    gl.glClear(0x0100)

class GpuRenderer:
    def __init__(self,context):
        self.gl=context.functions();self.program=QOpenGLShaderProgram()
        for kind,source in ((QOpenGLShader.Vertex,VERTEX),(QOpenGLShader.Fragment,FRAGMENT)):
            if not self.program.addShaderFromSourceCode(kind,source):raise RuntimeError(self.program.log())
        if not self.program.link():raise RuntimeError(self.program.log())
        self.uniforms={name:self.program.uniformLocation(name) for name in
            ('center','right','up','towards','projection','offset','highlighted','ghost','background','eye','clipPlane','clipOn','alphaPass')}
        missing=[name for name,location in self.uniforms.items() if location<0]
        if missing:raise RuntimeError('Missing solid shader uniforms: '+', '.join(missing))
        self.vao=QOpenGLVertexArrayObject()
        if not self.vao.create():raise RuntimeError('Could not create the solid vertex array.')
        self.vao.bind()
        self.buffer=QOpenGLBuffer()
        if not self.buffer.create():raise RuntimeError('Could not create the solid vertex buffer.')
        self.buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
        self.revision=None;self.count=0;self.uploads=0
        self.vao.release()
        self.supersample_enabled=True;self.supersample_fbo=None;self.supersample_key=None
        self.resolve_program=QOpenGLShaderProgram()
        for kind,source in ((QOpenGLShader.Vertex,RESOLVE_VERTEX),(QOpenGLShader.Fragment,RESOLVE_FRAGMENT)):
            if not self.resolve_program.addShaderFromSourceCode(kind,source):raise RuntimeError(self.resolve_program.log())
        if not self.resolve_program.link():raise RuntimeError(self.resolve_program.log())
        self.resolve_location=self.resolve_program.uniformLocation('image');self.factor_location=self.resolve_program.uniformLocation('factor')
        self.grid_program=None
        try:
            program=QOpenGLShaderProgram()
            for kind,source in ((QOpenGLShader.Vertex,GRID_VERTEX),(QOpenGLShader.Fragment,GRID_FRAGMENT)):
                if not program.addShaderFromSourceCode(kind,source):raise RuntimeError(program.log())
            if not program.link():raise RuntimeError(program.log())
            self.grid_uniforms={name:program.uniformLocation(name) for name in
                ('center','right','up','towards','projection','offset','viewport','halfwidth','bias','flatDepth','lineColor','eye')}
            self.grid_vao=QOpenGLVertexArrayObject();self.grid_vao.create()
            self.grid_buffer=QOpenGLBuffer();self.grid_buffer.create();self.grid_buffer.setUsagePattern(QOpenGLBuffer.DynamicDraw)
            self.grid_program=program
        except Exception as error:
            self.grid_program=None;self.grid_error=str(error)
        self.info={}
        for name,enum in [('vendor',0x1F00),('renderer',0x1F01),('OpenGL',0x1F02)]:
            value=self.gl.glGetString(enum)
            self.info[name]=value.decode() if isinstance(value,bytes) else str(value)
        self.info['requested samples']=8

    def supersample_target(self,width,height):
        if getattr(self,'max_target_size',None) is None:
            self.max_target_size=int(self.gl.glGetIntegerv(0x0D33))
        size=supersample_size(width,height,self.max_target_size)
        if size is None:return None
        if self.supersample_key!=size:
            fmt=QOpenGLFramebufferObjectFormat();fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil);fmt.setSamples(0)
            fbo=QOpenGLFramebufferObject(*size,fmt)
            if not fbo.isValid():raise RuntimeError('Could not allocate supersampling framebuffer.')
            self.supersample_fbo=fbo;self.supersample_key=size
        return self.supersample_fbo
    def resolve_supersampling(self,w,width,height):
        gl=self.gl
        gl.glBindFramebuffer(0x8D40,w.defaultFramebufferObject());gl.glViewport(0,0,width,height)
        gl.glDisable(0x0B71);gl.glEnable(0x0BE2);gl.glBlendFunc(1,0x0303)
        gl.glActiveTexture(0x84C0);gl.glBindTexture(0x0DE1,self.supersample_fbo.texture())
        if not self.resolve_program.bind():raise RuntimeError('Could not bind supersampling resolve shader.')
        gl.glUniform1i(self.resolve_location,0);gl.glUniform1i(self.factor_location,self.supersample_key[0]//width);self.vao.bind();gl.glDrawArrays(0x0004,0,3)
        self.vao.release();self.resolve_program.release();gl.glBindTexture(0x0DE1,0);gl.glDisable(0x0BE2)
    def draw(self,w):
        gl=self.gl
        width,height=round(w.width()*w.devicePixelRatioF()),round(w.height()*w.devicePixelRatioF())
        gl.glViewport(0,0,width,height)
        gl.glBindFramebuffer(0x8D40,w.defaultFramebufferObject())
        prepare_solid_state(gl,w.show_aa)
        if 'actual samples' not in self.info:self.info['actual samples']=int(gl.glGetIntegerv(0x80A9))
        if not len(w.triangles):
            rot=w.rotation()
            self.draw_grid(w,rot,w.scale(),self.depth_range(w,rot),(width,height),1,'bg')
            gl.glDisable(0x0B71);return
        target=None
        if w.show_aa and getattr(self,'supersample_enabled',False):
            try:target=self.supersample_target(width,height)
            except RuntimeError as err:self.info['Supersampling warning']=str(err);self.supersample_enabled=False
        self.info['Antialiasing']=f'{(self.supersample_key[0]//width)**2}× supersampling' if target else ('MSAA' if w.show_aa else 'off')
        if not target:gl.glBindFramebuffer(0x8D40,w.defaultFramebufferObject())
        if target:
            if not target.bind():raise RuntimeError('Could not bind supersampling framebuffer.')
            gl.glViewport(0,0,*self.supersample_key);prepare_solid_state(gl,False)
            gl.glClearColor(0,0,0,0);gl.glClear(0x4000)
        rot=w.rotation();s=w.scale();depth_range=self.depth_range(w,rot)
        self.draw_grid(w,rot,s,depth_range,(self.supersample_key if target else (width,height)),(self.supersample_key[0]//width if target else 1),'bg')
        self.vao.bind()
        if not self.buffer.bind() or not self.program.bind():raise RuntimeError('Could not bind the solid shader or vertex buffer.')
        changed=self.revision!=w.revision
        if self.revision!=w.revision:
            bases,codes=w.triangle_materials();data=mesh_data(w.vertices,w.triangles,w.face_ids,w.body_ids,bases/255.,codes,getattr(w,'gpu_base_data',None));raw=data.tobytes()
            self.buffer.allocate(raw,len(raw));self.count=len(data);self.revision=w.revision;self.uploads+=1
        for index,size,offset in [(0,3,0),(1,3,12),(2,1,24),(3,3,28),(4,1,40)]:
            self.program.enableAttributeArray(index);self.program.setAttributeBuffer(index,0x1406,offset,size,44)
        for name,value in [('center',w.center),('right',rot[0]),('up',rot[1]),('towards',rot[2]),
            ('projection',(2*s/w.width(),2*s/w.height(),1/depth_range)),
            ('offset',(2*w.pan[0]/w.width(),-2*w.pan[1]/w.height(),0))]:
            self.program.setUniformValue(self.uniforms[name],QVector3D(*map(float,value)))
        highlighted=w.hover or w.selected_source
        gl.glUniform1i(self.uniforms['highlighted'],int(highlighted['index']) if highlighted and highlighted.get('type') in ('face','curved') else -1)
        # PySide can select the integer overload even for a Python float, causing
        # GL_INVALID_OPERATION when the shader uniform is float (Mesa/Qt 6.8).
        gl.glUniform1f(self.uniforms['ghost'],.55 if w.mode=='sketch' else 0.)
        from themes import COLORS
        from PySide6.QtGui import QColor
        color=QColor(COLORS[w.theme]['canvas'])
        self.program.setUniformValue(self.uniforms['background'],QVector3D(color.redF(),color.greenF(),color.blueF()))
        eye=w.eye_distance() if hasattr(w,'eye_distance') else None
        gl.glUniform1f(self.uniforms['eye'],float(1./eye) if eye else 0.)
        plane=w.section_plane() if hasattr(w,'section_plane') else None
        gl.glUniform1f(self.uniforms['clipOn'],1. if plane is not None else 0.)
        normal,distance=plane if plane is not None else (np.array([0.,0.,1.]),0.)
        gl.glUniform4f(self.uniforms['clipPlane'],float(normal[0]),float(normal[1]),float(normal[2]),float(distance))
        gl.glUniform1f(self.uniforms['alphaPass'],0.)
        gl.glDrawArrays(0x0004,0,self.count)
        if getattr(w,'has_translucent_bodies',lambda:False)():
            # Translucent bodies last: blended over the opaque ones, without writing depth.
            gl.glEnable(0x0BE2);gl.glBlendFuncSeparate(0x0302,0x0303,1,0x0303);gl.glDepthMask(False)
            gl.glUniform1f(self.uniforms['alphaPass'],1.)
            gl.glDrawArrays(0x0004,0,self.count)
            gl.glDepthMask(True);gl.glDisable(0x0BE2)
        self.buffer.release();self.vao.release();self.program.release()
        self.draw_grid(w,rot,s,depth_range,(self.supersample_key if target else (width,height)),(self.supersample_key[0]//width if target else 1),'over')
        gl.glDisable(0x0B71)
        if target:self.resolve_supersampling(w,width,height)
        self.info['drawn vertices']=self.count
        if changed:
            error=gl.glGetError()
            if error:raise RuntimeError(f'OpenGL solid draw error: 0x{error:04x}')

    def depth_range(self,w,rot):
        """Depth span of the model along the view axis, from its bounding box (no per-frame pass over every vertex)."""
        key=(w.revision,len(w.vertices))
        if getattr(self,'_bounds_key',None)!=key:
            self._bounds_key=key
            self._corners=None
            if len(w.vertices):
                low=np.min(w.vertices,axis=0);high=np.max(w.vertices,axis=0)
                self._corners=np.array(list(itertools.product(*zip(low,high))),float)
        if self._corners is None:return max(w.span*4.,1.)
        return max(w.span*4.,float(np.max(np.abs((self._corners-w.center)@rot[2])))+1.)

    def draw_grid(self,w,rot,scale,depth_range,size,factor,which='over'):
        """The grid plane over the solids (depth-tested, 50 %). Any problem switches this pass off
        and the CPU fallback takes over."""
        if getattr(self,'grid_program',None) is None or getattr(w,'gl_grid_failed',False):return
        gl=self.gl
        try:
            groups=w.grid_gl_groups(which)
            if not groups:return
            program=self.grid_program;u=self.grid_uniforms
            self.grid_vao.bind();self.grid_buffer.bind()
            if not program.bind():raise RuntimeError('Could not bind the grid shader.')
            for name,value in [('center',w.center),('right',rot[0]),('up',rot[1]),('towards',rot[2]),
                ('projection',(2*scale/w.width(),2*scale/w.height(),1/depth_range)),
                ('offset',(2*w.pan[0]/w.width(),-2*w.pan[1]/w.height(),0))]:
                program.setUniformValue(u[name],QVector3D(*map(float,value)))
            eye=w.eye_distance() if hasattr(w,'eye_distance') else None
            gl.glUniform1f(u['eye'],float(1./eye) if eye else 0.)
            program.setUniformValue(u['viewport'],QVector2D(float(size[0]),float(size[1])))
            background=which=='bg'
            gl.glUniform1f(u['halfwidth'],float(.5*factor));gl.glUniform1f(u['bias'],float(.75/max(scale,1e-9)))
            gl.glUniform1f(u['flatDepth'],1. if background else 0.)
            gl.glDepthMask(False)
            if background:gl.glDisable(0x0B71)        # the background grid is simply drawn first
            else:gl.glEnable(0x0B71);gl.glDepthFunc(0x0203)
            gl.glEnable(0x0BE2);gl.glBlendFuncSeparate(0x0302,0x0303,1,0x0303)
            for (red,green,blue),segments in groups:
                if not len(segments):continue
                a=segments[:,0,:];b=segments[:,1,:]
                one=np.ones((len(a),1));minus=-one
                slots=[(a,b,one),(a,b,minus),(b,a,one),(a,b,one),(b,a,one),(b,a,minus)]
                data=np.stack([np.hstack((p,q,s)) for p,q,s in slots],axis=1).reshape(-1,7).astype(np.float32)
                raw=data.tobytes();self.grid_buffer.allocate(raw,len(raw))
                for index,count,offset in [(0,3,0),(1,3,12),(2,1,24)]:
                    program.enableAttributeArray(index);program.setAttributeBuffer(index,0x1406,offset,count,28)
                gl.glUniform4f(u['lineColor'],float(red),float(green),float(blue),1. if background else .5)
                gl.glDrawArrays(0x0004,0,len(data))
            for index in range(3):program.disableAttributeArray(index)
            program.release();self.grid_buffer.release();self.grid_vao.release()
        except Exception as error:
            w.gl_grid_failed=True;self.info['Grid pass warning']=str(error)
        finally:
            gl.glDisable(0x0BE2);gl.glDepthMask(True)
            if which=='bg':gl.glEnable(0x0B71);gl.glDepthFunc(0x0203)

    def destroy(self):
        self.supersample_fbo=None;self.resolve_program.removeAllShaders()
        self.buffer.destroy();self.vao.destroy();self.program.removeAllShaders()
