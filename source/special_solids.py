"""Parametric primitives and path-based engineering solids."""
import math
import cadquery as cq
import numpy as np
from legacy_model import ModelError,number,positive
from solid_tools import valid,path_wire,axis_reference
from references import resolve_body

SPECIAL_TOOLS=('primitive','pipe','coil','rib','web','thread')

def orient(shape,origin,direction):
    d=np.asarray(direction,float);z=np.array([0.,0.,1.]);cross=np.cross(z,d);angle=math.degrees(math.acos(float(np.clip(z@d,-1,1))))
    if angle>1e-8:
        if np.linalg.norm(cross)<1e-8:cross=np.array([1.,0.,0.])
        shape=shape.rotate((0,0,0),tuple(cross),angle)
    return shape.translate(tuple(origin))

def primitive(f):
    shape=f.get('shape','box');o=np.asarray(f.get('origin',[0,0,0]),float)
    if o.shape!=(3,) or not np.all(np.isfinite(o)):raise ModelError('Enter a finite primitive origin.')
    if shape=='box':solid=cq.Solid.makeBox(positive(f.get('width',10),'Width'),positive(f.get('length',10),'Length'),positive(f.get('height',10),'Height'))
    elif shape=='sphere':solid=cq.Solid.makeSphere(positive(f.get('radius',5),'Radius'),angleDegrees1=-90,angleDegrees2=90)
    elif shape=='cylinder':solid=cq.Solid.makeCylinder(positive(f.get('radius',5),'Radius'),positive(f.get('height',10),'Height'))
    elif shape=='cone':
        r=positive(f.get('radius',5),'Base radius');top=number(f.get('top_radius',0),'Top radius')
        if top<0 or abs(top-r)<1e-9:raise ModelError('Cone top radius must be nonnegative and differ from the base radius.')
        solid=cq.Solid.makeCone(r,top,positive(f.get('height',10),'Height'))
    elif shape=='torus':
        r=positive(f.get('radius',5),'Major radius');minor=positive(f.get('minor_radius',1),'Minor radius')
        if minor>=r:raise ModelError('Torus minor radius must be smaller than its major radius.')
        solid=cq.Solid.makeTorus(r,minor)
    else:raise ModelError('Unknown primitive shape.')
    return solid.translate(tuple(o))

def helix(f,thread=False):
    radius=positive(f.get('radius',5),'Radius');pitch=positive(f.get('pitch',2),'Pitch');height=positive(f.get('height',10),'Height')
    if height/pitch>200:raise ModelError('Use no more than 200 helical turns per feature.')
    clockwise=bool(f.get('left_hand',False));path=cq.Wire.makeHelix(pitch,height,radius,lefthand=clockwise)
    if thread:
        depth=positive(f.get('thread_depth',pitch*.35),'Thread depth');width=positive(f.get('thread_width',pitch*.6),'Thread width')
        if depth>=radius or width>=pitch*.95:raise ModelError('Thread depth must be below the radius and width must be below 95% of pitch.')
        if f.get('thread_type','external')=='external':points=[(radius-depth,0,0),(radius+.05,0,-width/2),(radius+.05,0,width/2),(radius-depth,0,0)]
        else:points=[(radius+depth,0,0),(radius-.05,0,-width/2),(radius-.05,0,width/2),(radius+depth,0,0)]
        outer=cq.Wire.makePolygon(points)
    else:
        diameter=positive(f.get('diameter',1),'Wire diameter')
        if diameter>=pitch or diameter>=2*radius:raise ModelError('Coil diameter must be smaller than the pitch and twice the helix radius.')
        tangent=path.tangentAt(0);outer=cq.Wire.makeCircle(diameter/2,(radius,0,0),tangent)
    solid=cq.Solid.sweep(outer,[],path,True,True,transitionMode='round')
    return valid(solid,'Thread' if thread else 'Coil')

def path_solid(f,sketches,frames):
    path=path_wire(f.get('path'),sketches,frames);start=np.asarray(path.positionAt(0).toTuple());tangent=np.asarray(path.tangentAt(0).toTuple())
    if f['kind']=='pipe':
        radius=positive(f.get('diameter',5),'Diameter')/2;outer=cq.Wire.makeCircle(radius,tuple(start),tuple(tangent));inner=[]
        if f.get('hollow',False):
            thickness=positive(f.get('thickness',1),'Wall thickness')
            if thickness>=radius:raise ModelError('Pipe thickness must be less than half its diameter.')
            inner=[cq.Wire.makeCircle(radius-thickness,tuple(start),tuple(tangent))]
    else:
        thickness=positive(f.get('thickness',1),'Thickness');height=positive(f.get('height',5),'Height')
        frame=frames.get(f['path'].get('sketch'));n=np.asarray(frame['normal']);side=np.cross(tangent,n)
        if np.linalg.norm(side)<1e-8:raise ModelError('Rib paths must lie in the sketch plane.')
        side/=np.linalg.norm(side);bottom=-height/2 if f['kind']=='web' else 0.;top=bottom+height
        outer=cq.Wire.makePolygon([tuple(start+side*x+n*y) for x,y in ((-thickness/2,bottom),(thickness/2,bottom),(thickness/2,top),(-thickness/2,top),(-thickness/2,bottom))]);inner=[]
    return valid(cq.Solid.sweep(outer,inner,path,True,False,transitionMode='round'),f['kind'].title())

# The helical tool is turned by an odd angle: its first profile plane would otherwise lie exactly
# on the seam of a round body and the boolean operation silently returns nothing.
def operation(f,result,sketches,frames):
    kind=f['kind']
    if kind=='primitive':tool=valid(primitive(f),'Primitive')
    elif kind in ('coil','thread'):
        tool=helix(f,kind=='thread').rotate((0,0,0),(0,0,1),37.3);a,d=axis_reference(f.get('axis',dict(type='origin',axis='Z')),result,sketches,frames);tool=orient(tool,a,d)
    else:tool=path_solid(f,sketches,frames)
    if kind in ('primitive','coil','pipe') and f.get('operation','new')=='new':
        shapes=list(result.val().Solids())+[tool] if result is not None else [tool]
        return cq.Compound.makeCompound(shapes) if len(shapes)>1 else shapes[0]
    if result is None:raise ModelError('Create a target body first, or choose New body.')
    refs=f.get('targets',[]);picked=[resolve_body(result,ref) for ref in refs]
    if not picked or len({i for i,b in picked})!=len(picked):raise ModelError('Select distinct target bodies explicitly.')
    output=list(result.val().Solids());op='cut' if kind=='thread' else f.get('operation','join')
    if op not in ('join','cut','intersect'):raise ModelError('Choose New body, Join, Cut or Intersect.')
    for index,body in picked:
        if body.intersect(tool).Volume()<1e-9:raise ModelError('This feature misses the target body. Check its path, position and size.')
        edited=body.fuse(tool) if op=='join' else body.cut(tool) if op=='cut' else body.intersect(tool)
        edited=valid(edited.clean(),kind.title())
        if op=='join' and len(edited.Solids())!=1:raise ModelError('The feature must connect to the target body.')
        output[index]=edited
    return cq.Compound.makeCompound(output) if len(output)>1 else output[0]
