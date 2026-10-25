"""Fast native rasterization with depth-aware antialiasing and a NumPy fallback."""
import ctypes
import numpy as np
from build_renderer import build

class Rasterizer:
    def __init__(self):
        self.native=None;self.error=None;self.size=None
        try:
            library=ctypes.CDLL(str(build()));self.native=library.slothcad_render;self.library=library
            ptr=ctypes.c_void_p;integer=ctypes.c_int
            self.native.argtypes=[ptr,ptr,ptr,ptr,ptr,integer,integer,integer,integer,ptr,ptr,ptr,ptr,ptr,ptr]
            self.native.restype=integer
        except Exception as e:
            self.error=str(e)
        self.calls=0
        if self.native and not self._self_test():
            self.native=None;self.error='The native viewport module gave wrong results; using the built-in renderer.'

    def _self_test(self):
        """One tiny frame through the native module before trusting it."""
        try:
            screen=np.array([[1.,1.],[30.,2.],[3.,30.]]);z=np.zeros(3)
            pixels,depth,ids=self.render(screen,z,np.array([[0,1,2]]),np.array([7]),np.array([[200,100,50]]),32,32)
            ok=ids[8,8]==7 and ids[31,31]==-1 and tuple(pixels[8,8])==(200,100,50,255)
        except Exception:
            ok=False
        self.size=None;self.calls=0
        return bool(ok)

    def render(self,screen,z,triangles,faces,colors,width,height,antialias=True):
        self.calls+=1;factor=2 if antialias else 1
        screen=np.ascontiguousarray(screen,dtype=np.float64);z=np.ascontiguousarray(z,dtype=np.float64)
        triangles=np.ascontiguousarray(triangles,dtype=np.int32);faces=np.ascontiguousarray(faces,dtype=np.int32);colors=np.ascontiguousarray(colors,dtype=np.uint8)
        if width<1 or height<1 or screen.ndim!=2 or screen.shape[1]!=2 or z.shape!=(len(screen),) or triangles.ndim!=2 or triangles.shape[1]!=3 or faces.shape!=(len(triangles),) or colors.shape!=(len(triangles),3):
            raise ValueError('Invalid raster buffer dimensions.')
        if len(triangles) and (triangles.min()<0 or triangles.max()>=len(screen)):
            raise ValueError('Triangle indices are outside the vertex buffer.')
        if not np.isfinite(screen).all() or not np.isfinite(z).all():raise ValueError('Raster coordinates must be finite.')
        if self.native:
            size=(width,height,factor)
            if self.size!=size:
                self.high_z=np.empty((height*factor,width*factor),np.float32)
                self.high_id=np.empty((height*factor,width*factor),np.int32)
                self.high_rgb=np.empty((height*factor,width*factor,3),np.uint8)
                self.pixels=np.empty((height,width,4),np.uint8);self.depth=np.empty((height,width),np.float32);self.ids=np.empty((height,width),np.int32);self.size=size
            ptr=lambda a:ctypes.c_void_p(a.ctypes.data)
            code=self.native(ptr(screen),ptr(z),ptr(triangles),ptr(faces),ptr(colors),len(triangles),width,height,factor,
                             ptr(self.high_z),ptr(self.high_id),ptr(self.high_rgb),ptr(self.pixels),ptr(self.depth),ptr(self.ids))
            if code:raise RuntimeError('Invalid native viewport dimensions.')
            return self.pixels,self.depth,self.ids
        return numpy_render(screen,z,triangles,faces,colors,width,height,factor)

def numpy_render(screen,z,triangles,faces,colors,width,height,factor=1):
    """Portable fallback; also an independent numerical reference for native tests."""
    sw,sh=width*factor,height*factor;screen=screen*factor
    pixels=np.zeros((sh,sw,4),np.uint8);depth=np.full((sh,sw),-np.inf,np.float32);ids=np.full((sh,sw),-1,np.int32)
    for i,tri in enumerate(triangles):
        a,b,c=screen[tri]
        x0=max(0,int(np.floor(min(a[0],b[0],c[0]))));x1=min(sw-1,int(np.ceil(max(a[0],b[0],c[0]))))
        y0=max(0,int(np.floor(min(a[1],b[1],c[1]))));y1=min(sh-1,int(np.ceil(max(a[1],b[1],c[1]))))
        if x0>x1 or y0>y1:continue
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-12:continue
        yy,xx=np.mgrid[y0:y1+1,x0:x1+1];xx=xx+.5;yy=yy+.5
        u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        w=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        zz=u*z[tri[0]]+w*z[tri[1]]+(1-u-w)*z[tri[2]]
        region=depth[y0:y1+1,x0:x1+1];mask=(u>=-1e-7)&(w>=-1e-7)&(u+w<=1+1e-7)&(zz>region)
        region[mask]=zz[mask];ids[y0:y1+1,x0:x1+1][mask]=faces[i];pixels[y0:y1+1,x0:x1+1][mask]=[*colors[i],255]
    if factor==1:return pixels,depth,ids
    rgba=np.zeros((height,width,4),np.uint8);out_z=np.full((height,width),-np.inf,np.float32);out_ids=np.full((height,width),-1,np.int32)
    count=np.zeros((height,width),np.uint32);rgb=np.zeros((height,width,3),np.uint32)
    for sy in range(factor):
        for sx in range(factor):
            sample=pixels[sy::factor,sx::factor];valid=sample[:,:,3]>0;count+=valid;rgb+=sample[:,:,:3]
            zz=depth[sy::factor,sx::factor];near=zz>out_z;out_z[near]=zz[near];out_ids[near]=ids[sy::factor,sx::factor][near]
    rgba[:,:,:3]=rgb//np.maximum(count,1)[:,:,None];rgba[:,:,3]=(count*255+factor*factor//2)//(factor*factor)
    return rgba,out_z,out_ids
