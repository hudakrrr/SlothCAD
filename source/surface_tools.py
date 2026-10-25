"""Independent open-surface history; surfaces never masquerade as solid bodies."""
import cadquery as cq
import numpy as np
import math
from legacy_model import ModelError,number,positive
from geometry import axes
from solid_tools import path_wire,profile,axis_reference,plane_reference,valid

SURFACE_TOOLS=('surface_extrude','surface_revolve','surface_sweep','surface_loft','surface_patch','surface_trim','surface_extend','surface_stitch','surface_thicken')

def bodies(frames):return frames.get('_surfaces',{})

def selected(f,frames):
    ids=f.get('surfaces',[]);lookup=bodies(frames)
    if not ids or len(set(ids))!=len(ids):raise ModelError('Select distinct surface bodies explicitly.')
    if any(id_ not in lookup for id_ in ids):raise ModelError('A surface body is missing or suppressed. Repair its selection.')
    return [(id_,lookup[id_]['shape']) for id_ in ids]

def boundary(ref,result,sketches,frames):
    if ref and ref.get('type')=='path':return path_wire(ref,sketches,frames)
    return profile(ref,result,sketches,frames)[0]

def validate(shape,label):
    if shape is None or not shape.isValid() or not shape.Faces() or shape.Area()<1e-9:raise ModelError(label+' did not produce a valid surface. Check curve connections and intersections.')
    return shape

def operation(f,result,sketches,frames):
    kind=f['kind'];registry=dict(bodies(frames));shape=None;solid=None;consumed=[]
    if kind in ('surface_extrude','surface_revolve','surface_sweep','surface_patch'):
        wire=boundary(f.get('source'),result,sketches,frames)
        if kind=='surface_extrude':
            from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
            from OCP.gp import gp_Vec
            vector=np.asarray(f.get('vector',[0,0,10]),float)
            if vector.shape!=(3,) or not np.all(np.isfinite(vector)) or np.linalg.norm(vector)<1e-9:raise ModelError('Enter a nonzero finite extrusion vector.')
            shape=cq.Shape.cast(BRepPrimAPI_MakePrism(wire.wrapped,gp_Vec(*map(float,vector))).Shape())
        elif kind=='surface_revolve':
            from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
            from OCP.gp import gp_Ax1,gp_Pnt,gp_Dir
            a,d=axis_reference(f.get('axis'),result,sketches,frames);angle=number(f.get('angle',360),'Angle')
            if not 0<abs(angle)<=360:raise ModelError('Enter a nonzero revolve angle up to 360 degrees.')
            shape=cq.Shape.cast(BRepPrimAPI_MakeRevol(wire.wrapped,gp_Ax1(gp_Pnt(*map(float,a)),gp_Dir(*map(float,d))),math.radians(angle)).Shape())
        elif kind=='surface_sweep':shape=cq.Solid.sweep(wire,[],path_wire(f.get('path'),sketches,frames),False,bool(f.get('frenet',False)),transitionMode='round')
        else:
            if not wire.IsClosed():raise ModelError('Patch needs a closed boundary.')
            try:shape=cq.Face.makeFromWires(wire)
            except Exception:shape=cq.Face.makeNSidedSurface(wire.Edges(),[])
    elif kind=='surface_loft':
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        sections=f.get('sections',[])
        if len(sections)<2:raise ModelError('Surface Loft needs at least two ordered sections.')
        builder=BRepOffsetAPI_ThruSections(False,bool(f.get('ruled',False)),1e-6)
        for ref in sections:builder.AddWire(boundary(ref,result,sketches,frames).wrapped)
        builder.Build()
        if not builder.IsDone():raise ModelError('Surface Loft failed. Check section order and connectivity.')
        shape=cq.Shape.cast(builder.Shape())
    else:
        choices=selected(f,frames);consumed=[id_ for id_,shape in choices]
        if kind=='surface_stitch':
            from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
            tolerance=positive(f.get('tolerance',.001),'Stitch tolerance')
            if tolerance>1:raise ModelError('Stitch tolerance must not exceed 1 mm.')
            builder=BRepBuilderAPI_Sewing(tolerance)
            for id_,shape in choices:builder.Add(shape.wrapped)
            builder.Perform();shape=cq.Shape.cast(builder.SewedShape())
            if f.get('make_solid',False):
                shells=shape.Shells()
                if len(shells)!=1 or not shells[0].Closed():raise ModelError('Stitch to solid needs one watertight closed shell. Repair gaps or leave Make solid off.')
                solid=valid(cq.Solid.makeSolid(shells[0]),'Stitch');shape=None
        elif kind=='surface_thicken':
            thickness=number(f.get('thickness',1),'Thickness')
            if abs(thickness)<1e-9:raise ModelError('Thickness cannot be zero.')
            from OCP.BRepOffset import BRepOffset_MakeOffset
            from OCP.GeomAbs import GeomAbs_Intersection
            solids=[]
            for id_,surface in choices:
                builder=BRepOffset_MakeOffset();builder.Initialize(surface.wrapped,thickness,1e-6,Join=GeomAbs_Intersection,Thickening=True);builder.MakeOffsetShape()
                if not builder.IsDone():raise ModelError('Thicken failed. Reduce thickness or repair surface intersections.')
                solids.append(valid(cq.Shape.cast(builder.Shape()),'Thicken'))
            solid=valid(cq.Compound.makeCompound(solids),'Thicken')
        elif kind=='surface_trim':
            frame=plane_reference(f.get('plane'),result,frames);o,u,v,n=axes(frame);pieces=[]
            for id_,surface in choices:
                box=surface.BoundingBox();span=max(10.,box.DiagonalLength+np.linalg.norm(np.asarray(surface.Center().toTuple())-o))*3
                wire=cq.Wire.makePolygon([tuple(o+u*x+v*y) for x,y in ((-span,-span),(span,-span),(span,span),(-span,span),(-span,-span))])
                direction=n if f.get('keep','positive')=='positive' else -n
                slab=cq.Solid.extrudeLinear(wire,[],tuple(direction*span));piece=surface.intersect(slab)
                validate(piece,'Trim');pieces.append(piece)
            shape=cq.Compound.makeCompound(pieces)
        elif kind=='surface_extend':
            from OCP.BRep import BRep_Tool
            from OCP.BRepTools import BRepTools
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            amount=positive(f.get('distance',5),'Extension');pieces=[]
            for id_,surface in choices:
                faces=surface.Faces()
                if len(faces)!=1:raise ModelError('Extend currently works on individual untrimmed surface faces.')
                face=faces[0];surf=BRep_Tool.Surface_s(face.wrapped);u0,u1,v0,v1=BRepTools.UVBounds_s(face.wrapped)
                if face.innerWires():raise ModelError('Extend a surface without inner trim loops.')
                natural=cq.Shape.cast(BRepBuilderAPI_MakeFace(surf,u0,u1,v0,v1,1e-6).Face())
                if abs(natural.Area()-face.Area())>max(1e-5,face.Area()*1e-6):raise ModelError('Extend requires an untrimmed rectangular UV boundary. Extending arbitrary trim edges is not supported yet.')
                from OCP.gp import gp_Pnt,gp_Vec
                p=gp_Pnt();du=gp_Vec();dv=gp_Vec();surf.D1((u0+u1)/2,(v0+v1)/2,p,du,dv)
                step_u=amount/max(du.Magnitude(),1e-9);step_v=amount/max(dv.Magnitude(),1e-9)
                direction=f.get('extend_direction','all')
                if direction not in ('all','u','v'):raise ModelError('Choose U, V or all extension directions.')
                builder=BRepBuilderAPI_MakeFace(surf,u0-(step_u if direction!='v' else 0),u1+(step_u if direction!='v' else 0),v0-(step_v if direction!='u' else 0),v1+(step_v if direction!='u' else 0),1e-6)
                if not builder.IsDone():raise ModelError('This surface cannot extend beyond its natural domain.')
                pieces.append(cq.Shape.cast(builder.Face()))
            shape=cq.Compound.makeCompound(pieces)
        else:raise ModelError('Unknown surface tool.')
    if shape is not None:
        validate(shape,kind.replace('_',' ').title());registry[f['id']]=dict(shape=shape,name=f['name'],producer=f['id'])
    if f.get('consume',True):
        for id_ in consumed:registry.pop(id_,None)
    next_frames=dict(frames);next_frames['_surfaces']=registry
    return solid,next_frames

def scene(solid,frames,visibility=None):
    shapes=([solid.val()] if solid is not None else [])+[body['shape'] for id_,body in bodies(frames).items() if (visibility or {}).get(id_,True)]
    if not shapes:return None
    if len(shapes)==1 and solid is not None and shapes[0].isSame(solid.val()):return solid
    return cq.Workplane('XY').newObject([cq.Compound.makeCompound(shapes)])
