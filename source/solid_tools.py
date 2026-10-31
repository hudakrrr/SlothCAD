"""Construction references and validated CAD kernel operations."""
import math
import numpy as np
import cadquery as cq
from legacy_model import ModelError,number,positive
from geometry import axes,base_frame,frame_on_face,resolve_face,wire_for,profile_regions,world,sample,EPS

CONSTRUCTIONS=('construction_plane','construction_axis')
SOLID_TOOLS=('revolve','sweep','loft','shell','draft','hole')

def unit(value):
    a=np.asarray(value,dtype=float)
    if a.shape!=(3,) or not np.all(np.isfinite(a)) or np.linalg.norm(a)<EPS:raise ModelError('Choose two distinct points or a nonzero axis direction.')
    return a/np.linalg.norm(a)

def point(value):
    a=np.asarray(value,dtype=float)
    if a.shape!=(3,) or not np.all(np.isfinite(a)):raise ModelError('Enter finite X, Y and Z coordinates.')
    return a

def plane_reference(ref,result,frames):
    if not isinstance(ref,dict):raise ModelError('Select a reference plane or planar face.')
    kind=ref.get('type')
    if kind=='origin':return base_frame(ref.get('plane','XY'))
    if kind=='face':return frame_on_face(resolve_face(result,ref['face']),projected=ref.get('origin')=='projected')
    if kind=='construction':
        frame=frames.get(ref.get('id'))
        if frame is None or frame.get('axis'):raise ModelError('The construction plane is missing, suppressed or later in history.')
        return frame
    if kind=='frame':axes(ref['frame']);return ref['frame']
    raise ModelError('Unknown plane reference.')

def axis_reference(ref,result,sketches,frames):
    if not isinstance(ref,dict):raise ModelError('Select a rotation or construction axis.')
    kind=ref.get('type')
    if kind=='construction':
        frame=frames.get(ref.get('id'))
        if not frame or not frame.get('axis'):raise ModelError('The construction axis is missing, suppressed or later in history.')
        return point(frame['origin']),unit(frame['normal'])
    if kind=='origin':return np.zeros(3),np.eye(3)[{'X':0,'Y':1,'Z':2}[ref.get('axis','Z')]]
    if kind=='sketch_line':
        s=sketches.get(ref.get('sketch'))
        if not s:raise ModelError('The axis sketch is missing.')
        e=next((e for e in s['entities'] if e['id']==ref.get('entity')),None)
        if not e or e['kind']!='line':raise ModelError('Select a straight sketch line for the axis.')
        if frames[s['id']].get('spatial'):
            edge=frames[s['id']]['edges'][e['id']]
            if edge.geomType()!='LINE':raise ModelError('A curve on a surface is not a straight rotation axis. Choose a straight 3D line or construction axis.')
            a=np.asarray(edge.startPoint().toTuple());b=np.asarray(edge.endPoint().toTuple());return a,unit(b-a)
        a=world(frames[s['id']],e['a']);b=world(frames[s['id']],e['b']);return a,unit(b-a)
    if kind=='plane_normal':
        f=plane_reference(ref['plane'],result,frames);o,u,v,n=axes(f);return o,n
    return point(ref.get('start',[0,0,0])),unit(point(ref.get('end',[0,0,1]))-point(ref.get('start',[0,0,0])))

def construction(feature,result,sketches,frames):
    mode=feature.get('mode','offset');kind=feature['kind']
    if kind=='construction_axis':
        a,d=axis_reference(feature.get('reference',{'type':'points','start':feature.get('start',[0,0,0]),'end':feature.get('end',[0,0,10])}),result,sketches,frames)
        ref=np.eye(3)[np.argmin(np.abs(d))];u=unit(np.cross(d,ref))
        return dict(origin=a.tolist(),u=u.tolist(),normal=d.tolist(),axis=True)
    if mode=='three points':
        a,b,c=[point(feature[k]) for k in ('p1','p2','p3')];u=unit(b-a);n=unit(np.cross(b-a,c-a));o=a
    else:
        frame=plane_reference(feature.get('reference',{'type':'origin','plane':'XY'}),result,frames);o,u,v,n=axes(frame)
        if mode=='offset':o=o+n*number(feature.get('offset',0),'Offset')
        elif mode=='midplane':
            other=plane_reference(feature['second'],result,frames);o2,_,_,n2=axes(other)
            if abs(abs(n@n2)-1)>1e-6:raise ModelError('Midplanes require parallel reference planes.')
            o=o+n*float((o2-o)@n)/2
        elif mode=='angled':
            a,d=axis_reference(feature.get('axis',{'type':'origin','axis':'X'}),result,sketches,frames)
            if abs(float(d@n))>1e-6 or abs(float((a-o)@n))>1e-5:raise ModelError('An angled-plane rotation axis must lie in its reference plane.')
            angle=math.radians(number(feature.get('angle',45),'Angle'))
            def rotate(x):return x*math.cos(angle)+np.cross(d,x)*math.sin(angle)+d*(d@x)*(1-math.cos(angle))
            o=a+rotate(o-a);u=rotate(u);n=rotate(n)
        else:raise ModelError('Unknown construction plane mode.')
    return dict(origin=o.tolist(),u=u.tolist(),normal=n.tolist())

def profile(source,result,sketches,frames):
    if not isinstance(source,dict):raise ModelError('Select a closed sketch profile.')
    if source.get('type')=='face':
        face=resolve_face(result,source['face']);return face.outerWire(),list(face.innerWires()),frame_on_face(face)
    s=sketches.get(source.get('sketch'))
    if s is None:raise ModelError('The profile sketch is missing, suppressed or later in history.')
    if any(e.get('construction') and e['id'] in source.get('entities',[]) for e in s['entities']):raise ModelError('Construction guides cannot be used as solid profiles.')
    if frames[s['id']].get('spatial'):
        wire=__import__('spatial_sketch').wire(source,sketches,frames)
        if not wire.IsClosed():raise ModelError('A solid profile needs a closed planar wire. Use this curve as a path or surface boundary.')
        face=cq.Face.makeFromWires(wire);return wire,[],frame_on_face(face)
    from profile_references import recover
    selected_region=recover(source,s)
    frame=frames[s['id']];holes=source.get('holes',[])
    if source.get('profile_mode')=='nested':
        matches=[selected_region] if selected_region is not None else []
        if len(matches)!=1:raise ModelError('The selected region changed. Select the profile again.')
        holes=matches[0]['holes']
    return wire_for(s,source.get('entities',[]),frame),[wire_for(s,ids,frame) for ids in holes],frame

def valid(shape,label='Operation'):
    # The validity analysis and the volume of the same shape are remembered (model._shape_status):
    # the boolean that follows asks for them again.
    from model import _shape_status
    ok,volume=_shape_status(shape) if shape is not None else (False,0.)
    if not ok or volume<=1e-9:raise ModelError(label+' did not produce a valid solid. Check the references and reduce the size or angle.')
    return shape

def body_corners(result):
    if result is None:raise ModelError('This extent needs an existing body.')
    b=result.val().BoundingBox()
    return np.asarray([[x,y,z] for x in (b.xmin,b.xmax) for y in (b.ymin,b.ymax) for z in (b.zmin,b.zmax)])

def tapered_prism(outer,inner,vector,taper):
    if not taper:
        solid=cq.Solid.extrudeLinear(outer,inner,tuple(vector))
        # A hole touching the outline at one vertex gives an invalid face; cutting the
        # hole prisms out of the plain outline handles that contact.
        from validity import shape_valid
        if not inner or shape_valid(solid):return solid
        solid=cq.Solid.extrudeLinear(outer,[],tuple(vector))
        for wire in inner:solid=solid.cut(cq.Solid.extrudeLinear(wire,[],tuple(vector)))
        return solid
    # CadQuery intentionally ignores inner loops in tapered extrudeLinear.
    solid=cq.Solid.extrudeLinear(outer,[],tuple(vector),taper)
    for wire in inner:solid=solid.cut(cq.Solid.extrudeLinear(wire,[],tuple(vector),-taper))
    return solid

THIN_SIDES=('inside','outside','centered')


def _wire_area(wire):
    try:return float(cq.Face.makeFromWires(wire).Area())
    except Exception:return None


def offset_wire(wire,distance,grow):
    """A closed planar wire moved by ``distance`` towards its inside or (``grow``) outside.

    The kernel's sign convention depends on the wire's orientation, so both signs are tried and the
    result is chosen by the area it encloses.
    """
    base=_wire_area(wire)
    best=None
    for sign in (1.,-1.):
        try:candidates=wire.offset2D(sign*distance,'intersection')
        except Exception:continue
        for candidate in candidates:
            area=_wire_area(candidate)
            if area is None or base is None:continue
            if (area>base)==grow and abs(area-base)>1e-9:
                if best is None:best=(area,candidate)
    return None if best is None else best[1]


def thin_profiles(outer,inner,feature):
    """Ring-shaped profiles ``[(outer, [inner...])]`` of a thin-wall extrusion, or None when it is solid.

    ``thin`` is the wall thickness; ``thin_side`` puts the wall inside the sketched outline, outside
    of it or centred on it. Holes in the profile get walls around them on the matching side.
    """
    thickness=feature.get('thin')
    if not thickness:return None
    thickness=positive(thickness,'Wall thickness');side=feature.get('thin_side','inside')
    if side not in THIN_SIDES:raise ModelError('Choose inside, outside or centered for the wall.')
    inward,outward=(thickness,0.) if side=='inside' else (0.,thickness) if side=='outside' else (thickness/2,thickness/2)
    def edge_pair(wire,hole):
        # (towards the material side, away from it): material lies inside an outline, outside a hole.
        near=wire if not inward else offset_wire(wire,inward,grow=hole)
        far=wire if not outward else offset_wire(wire,outward,grow=not hole)
        if near is None or far is None:raise ModelError('The wall thickness is too large for this profile.')
        return near,far
    rings=[]
    near,far=edge_pair(outer,False)
    rings.append((far,[near]))
    for wire in inner:
        near,far=edge_pair(wire,True)
        rings.append((near,[far]))           # around a hole the material side is the larger outline
    return rings


def extrude(source,feature,result,sketches,frames):
    outer,inner,frame=profile(source,result,sketches,frames);o,u,v,n=axes(frame)
    depth=number(feature.get('depth',10),'Depth');offset=number(feature.get('offset',0),'Start offset')
    extent=feature.get('extent','distance');direction=feature.get('direction','one side');taper=number(feature.get('taper',0),'Taper angle')
    if direction not in ('one side','symmetric','two sides'):raise ModelError('Choose one side, two sides or symmetric extrusion.')
    if abs(taper)>=89:raise ModelError('Taper angle must be between -89 and 89 degrees.')
    if abs(depth)<1e-9:raise ModelError('Depth cannot be zero.')
    sign=1 if depth>0 else -1;start=o+n*offset;shift=tuple(n*offset)
    if offset:outer=outer.translate(shift);inner=[w.translate(shift) for w in inner]
    if extent=='through all':
        projected=(body_corners(result)-start)@n;pad=max(1.,float(np.ptp(projected))*.05)
        if direction!='symmetric' and float(np.max(projected*sign))<=1e-7:raise ModelError('The body lies behind the profile. Reverse the extrusion direction or choose symmetric.')
        depth=sign*(2*(float(np.max(np.abs(projected)))+pad) if direction=='symmetric' else float(np.max(projected*sign))+pad)
    elif extent=='to object':
        if direction=='symmetric':raise ModelError('To-object extrusion uses one side. Choose distance or through-all for a symmetric extrusion.')
        target=plane_reference(feature.get('target'),result,frames);to,tu,tv,tn=axes(target);den=float(n@tn)
        if abs(den)<1e-8:raise ModelError('The target plane is parallel to the extrusion direction.')
        vertices=np.asarray([v.Center().toTuple() for v in outer.Vertices()]);rays=((to-vertices)@tn)/den
        # Circular wires have few vertices: include a bounding box to cover them.
        box=outer.BoundingBox();corners=np.array([[x,y,z] for x in (box.xmin,box.xmax) for y in (box.ymin,box.ymax) for z in (box.zmin,box.zmax)])
        rays=((to-corners)@tn)/den
        if np.min(rays*sign)<=1e-7:raise ModelError('The target must be ahead of the whole profile in the chosen direction.')
        depth=sign*(float(np.max(rays*sign))+max(1.,float(np.ptp(rays))))
    elif extent!='distance':raise ModelError('Unknown extrusion extent.')
    profiles=thin_profiles(outer,inner,feature) or [(outer,inner)]
    def prism(vector):
        pieces=[tapered_prism(o,i,vector,taper) for o,i in profiles]
        return pieces[0] if len(pieces)==1 else pieces[0].fuse(*pieces[1:]).clean()
    if direction=='symmetric':
        a=prism(n*depth/2);b=prism(-n*depth/2);solid=a.fuse(b).clean()
    elif direction=='two sides':
        if extent!='distance':raise ModelError('Two-sided extrusion needs the distance extent.')
        second=number(feature.get('depth2',depth),'Second distance')
        if abs(second)<1e-9:raise ModelError('The second distance cannot be zero.')
        a=prism(n*depth);b=prism(-n*abs(second)*sign);solid=a.fuse(b).clean()
    else:solid=prism(n*depth)
    if extent=='to object':
        bounds=solid.BoundingBox();corners=np.asarray([[x,y,z] for x in (bounds.xmin,bounds.xmax) for y in (bounds.ymin,bounds.ymax) for z in (bounds.zmin,bounds.zmax)])
        span=max(10.,float(np.max(np.linalg.norm(corners-to,axis=1)))*2+10)
        points=[tuple(to+tu*x+tv*y) for x,y in ((-span,-span),(span,-span),(span,span),(-span,span),(-span,-span))]
        wire=cq.Wire.makePolygon(points);keep_direction=-tn*(1 if den*sign>0 else -1)
        slab=cq.Solid.extrudeLinear(wire,[],tuple(keep_direction*span*2));solid=solid.intersect(slab).clean()
    return valid(solid,'Extrusion')

def path_wire(reference,sketches,frames):
    if not isinstance(reference,dict):raise ModelError('Select a connected sweep path.')
    s=sketches.get(reference.get('sketch'))
    if not s:raise ModelError('Select a path sketch.')
    if frames[s['id']].get('spatial'):return __import__('spatial_sketch').wire(reference,sketches,frames)
    ids=reference.get('entities',[]);lookup={e['id']:e for e in s['entities']};edges=[];frame=frames[s['id']]
    if not ids:raise ModelError('Select at least one path curve.')
    for id_ in ids:
        e=lookup.get(id_)
        if not e or e['kind'] not in ('line','arc','spline','conic'):raise ModelError('Sweep paths require connected lines, arcs or splines.')
        w=lambda p:tuple(world(frame,p))
        if e['kind']=='line':edges.append(cq.Edge.makeLine(w(e['a']),w(e['b'])))
        elif e['kind']=='arc':edges.append(cq.Edge.makeThreePointArc(w(e['a']),w(e['mid']),w(e['b'])))
        else:
            from curves import edge_for
            o,u,v,n=axes(frame);edges.append(edge_for(e).transformShape(cq.Plane(tuple(o),tuple(u),tuple(n)).rG))
    wire=cq.Wire.assembleEdges(edges)
    if not wire.isValid() or len(wire.Wires())!=1:raise ModelError('The sweep path must be one connected wire.')
    return wire

def selected_faces(result,refs):
    from references import match_shape
    available=result.val().Faces() if result else [];chosen=[]
    for ref in refs:
        face,state=match_shape(result,ref,'face',available);chosen.append(face);available=[f for f in available if not f.isSame(face)]
    return chosen

def face_ref(face,result=None):
    from references import shape_reference
    return shape_reference(face,'face',result)

def solid_operation(feature,result,sketches,frames):
    kind=feature['kind']
    if kind=='revolve':
        outer,inner,frame=profile(feature['source'],result,sketches,frames);a,d=axis_reference(feature['axis'],result,sketches,frames)
        angle=number(feature.get('angle',360),'Angle')
        if not 0<abs(angle)<=360:raise ModelError('Revolve angle must be nonzero and at most 360 degrees.')
        if angle<0:d=-d;angle=-angle
        _,_,_,n=axes(frame)
        if abs(float(d@n))>1e-6 or abs(float((a-np.asarray(frame['origin']))@n))>1e-5:raise ModelError('The revolve axis must lie in the profile plane.')
        # A profile that straddles the axis would fold over itself (Fusion and FreeCAD refuse it too).
        side=np.cross(n,d)
        samples=np.vstack([np.array([e.positionAt(t).toTuple() for t in np.linspace(0,1,9)]) for e in outer.Edges()])
        distances=(samples-a)@side
        if float(distances.min())<-1e-6 and float(distances.max())>1e-6:
            raise ModelError('The revolve axis passes through the profile. Put the axis on an edge of the profile or outside it, or sketch only half of the shape.')
        solid=cq.Solid.revolve(outer,inner,angle,tuple(a),tuple(a+d))
        if feature.get('symmetric') and angle<360-1e-9:
            solid=solid.rotate(tuple(a),tuple(a+d),-angle/2)        # half of the angle on each side of the profile
        return valid(solid,'Revolve'),False
    if kind=='sweep':
        outer,inner,frame=profile(feature['source'],result,sketches,frames);path=path_wire(feature['path'],sketches,frames)
        # A guide curve (auxiliary spine) steers how the profile turns while it travels along the path.
        guide=path_wire(feature['guide'],sketches,frames) if feature.get('guide') else None
        if guide is not None and feature.get('frenet',False):raise ModelError('Use either a guide curve or Frenet orientation, not both.')
        return valid(cq.Solid.sweep(outer,inner,path,True,bool(feature.get('frenet',False)),mode=guide,transitionMode='round'),'Sweep'),False
    if kind=='loft':
        sources=feature.get('sections',[])
        if len(sources)<2:raise ModelError('Loft needs at least two ordered profiles.')
        profiles=[profile(s,result,sketches,frames) for s in sources];counts={len(p[1]) for p in profiles}
        if len(counts)!=1:raise ModelError('Loft sections must have the same number of inner loops.')
        solid=cq.Solid.makeLoft([p[0] for p in profiles],bool(feature.get('ruled',False)))
        for i in range(len(profiles[0][1])):solid=solid.cut(cq.Solid.makeLoft([p[1][i] for p in profiles],bool(feature.get('ruled',False))))
        return valid(solid,'Loft'),False
    if result is None:raise ModelError('Create a body first.')
    if kind=='hole':
        if feature.get('points_sketch'):
            # One hole at every point of a sketch, drilled along that sketch's normal.
            point_sketch=sketches.get(feature['points_sketch']);point_frame=frames.get(feature['points_sketch'])
            if point_sketch is None or point_frame is None or point_frame.get('spatial'):
                raise ModelError('The sketch with the hole points is missing, suppressed or later in history.')
            locations=[world(point_frame,e['p']) for e in point_sketch['entities'] if e['kind']=='point']
            if not locations:raise ModelError('The selected sketch has no points to drill at. Add sketch points first.')
            o,u,v,n=axes(point_frame)
        else:
            # Hole X/Y are measured from the face centre (their 0,0 default relies on it).
            plane=feature.get('plane');plane=dict(plane,origin=None) if isinstance(plane,dict) else plane
            frame=plane_reference(plane,result,frames);o,u,v,n=axes(frame)
            locations=[o+u*number(feature.get('x',0),'X')+v*number(feature.get('y',0),'Y')]
        d=-n if feature.get('direction','inward')=='inward' else n
        radius=positive(feature.get('diameter',5),'Hole diameter')/2;mode=feature.get('hole_type','simple')
        base_depth=positive(feature.get('depth',10),'Hole depth');pad=1e-5
        if mode not in ('simple','counterbore','countersink'):raise ModelError('Unknown hole type.')
        def one_hole(origin):
            depth=max(1.,float(np.max((body_corners(result)-origin)@d))+1.) if feature.get('through_all') else base_depth
            tool=cq.Solid.makeCylinder(radius,depth+pad,tuple(origin-d*pad),tuple(d))
            tip=number(feature.get('tip_angle',0),'Drill point angle')
            if tip and not feature.get('through_all'):
                if not 0<tip<180:raise ModelError('The drill point angle must be between 0 and 180 degrees.')
                cone=radius/math.tan(math.radians(tip/2))
                tool=tool.fuse(cq.Solid.makeCone(radius,0.,cone,tuple(origin+d*depth),tuple(d)))
            if mode in ('counterbore','countersink'):
                big=positive(feature.get('head_diameter',10),'Head diameter')/2
                if big<=radius:raise ModelError('The head diameter must exceed the hole diameter.')
                if mode=='counterbore':
                    h=positive(feature.get('head_depth',3),'Counterbore depth')
                    if h>depth:raise ModelError('Counterbore depth must not exceed the hole depth.')
                    head=cq.Solid.makeCylinder(big,h+pad,tuple(origin-d*pad),tuple(d))
                else:
                    angle=positive(feature.get('head_angle',90),'Countersink angle')
                    if angle>=180:raise ModelError('Countersink angle must be between 0 and 180 degrees.')
                    h=(big-radius)/math.tan(math.radians(angle/2))
                    if h>depth:raise ModelError('The countersink is deeper than the hole.')
                    head=cq.Solid.makeCone(big+pad*math.tan(math.radians(angle/2)),radius,h+pad,tuple(origin-d*pad),tuple(d))
                tool=tool.fuse(head)
            return tool
        tools=[one_hole(origin) for origin in locations]
        tool=tools[0] if len(tools)==1 else cq.Compound.makeCompound(tools)
        if result.val().intersect(tool).Volume()<=1e-9:raise ModelError('The hole misses the body. Check the supporting plane, position and direction.')
        return valid(tool,'Hole'),False
    bodies=result.val().Solids();index=feature.get('body',0)
    if not isinstance(index,int) or not 0<=index<len(bodies):raise ModelError('Select a valid body.')
    if feature.get('body_ref'):
        from references import resolve_body
        index,body=resolve_body(result,feature['body_ref'])
    else:body=bodies[index]
    local_result=cq.Workplane('XY').newObject([body])
    from topology import entries
    local_result._slothcad_bodies=[item for item in entries(result) if item['shape'].isSame(body)]
    faces=selected_faces(local_result,feature.get('faces',[]))
    if kind=='shell':
        thickness=number(feature.get('thickness',-1),'Thickness')
        if abs(thickness)<EPS:raise ModelError('Shell thickness cannot be zero.')
        edited=body.shell(faces,thickness,kind='intersection')
        valid(edited,'Shell')
        if thickness<0 and (edited.Volume()>=body.Volume()-1e-7 or edited.cut(body).Volume()>max(1e-6,body.Volume()*1e-8)):
            raise ModelError('The inward shell exceeds the available material. Reduce its thickness.')
    elif kind=='draft':
        if not faces:raise ModelError('Select one or more faces to draft.')
        neutral=plane_reference(feature.get('neutral'),result,frames);o,u,v,n=axes(neutral)
        angle=number(feature.get('angle',3),'Draft angle')
        if not 0<abs(angle)<89:raise ModelError('Draft angle must be nonzero and between -89 and 89 degrees.')
        from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCP.gp import gp_Dir,gp_Pln,gp_Pnt
        builder=BRepOffsetAPI_DraftAngle(body.wrapped)
        for face in faces:
            builder.Add(face.wrapped,gp_Dir(*map(float,n)),math.radians(angle),gp_Pln(gp_Pnt(*map(float,o)),gp_Dir(*map(float,n))))
            if not builder.AddDone():raise ModelError('This face cannot be drafted about the neutral plane.')
        builder.Build()
        if not builder.IsDone():raise ModelError('Draft failed. Reduce the angle or change the selected faces.')
        edited=cq.Shape.cast(builder.Shape())
    else:raise ModelError('Unknown solid tool.')
    valid(edited,kind.title());solids=[edited if i==index else s for i,s in enumerate(bodies)]
    return cq.Compound.makeCompound(solids) if len(solids)>1 else edited,True
