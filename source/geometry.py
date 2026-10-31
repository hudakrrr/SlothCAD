"""Sketch entities, frames, profile assembly, and geometric snapping."""
import math
import copy
import uuid
import json
from functools import lru_cache
import numpy as np
import cadquery as cq
from legacy_model import ModelError, number, positive

EPS=1e-6

def identifier(): return uuid.uuid4().hex

def vec(v): return np.array([number(t,'Coordinate') for t in v],dtype=float)

def base_frame(plane):
    return {'origin':[0.,0.,0.], 'u':{'XY':[1.,0.,0.],'XZ':[1.,0.,0.],'YZ':[0.,1.,0.]}[plane],
            'normal':{'XY':[0.,0.,1.],'XZ':[0.,-1.,0.],'YZ':[1.,0.,0.]}[plane]}

_AXES_CACHE={}

def _axes_key(frame):
    """Hashable key of a frame made only of plain numbers (anything else is validated each time)."""
    key=[]
    for name in ('origin','u','normal'):
        values=frame[name]
        if len(values)!=3:return None
        for x in values:
            if isinstance(x,bool) or not isinstance(x,(int,float,np.integer,np.floating)):return None
            key.append(float(x))
    return tuple(key)

def axes(frame):
    """Orthonormal (origin, u, v, normal) of a sketch frame.

    Called for every point converted between sketch and world coordinates (thousands of times
    per rebuild or repaint), and a frame has only a handful of distinct values, so results are
    cached by value and handed out as copies.
    """
    try:key=_axes_key(frame)
    except Exception:key=None
    if key is not None:
        hit=_AXES_CACHE.get(key)
        if hit is not None:return tuple(a.copy() for a in hit)
    o,u,n=map(vec,(frame['origin'],frame['u'],frame['normal']))
    if len(o)!=3 or len(u)!=3 or len(n)!=3: raise ModelError('A sketch frame must contain 3D vectors.')
    if np.linalg.norm(u)<EPS or np.linalg.norm(n)<EPS: raise ModelError('Invalid sketch axes.')
    n=n/np.linalg.norm(n); u=u-n*np.dot(u,n)
    if np.linalg.norm(u)<EPS: raise ModelError('Sketch axes must be perpendicular.')
    u/=np.linalg.norm(u)
    result=(o,u,np.cross(n,u),n)
    if key is not None:
        if len(_AXES_CACHE)>512:_AXES_CACHE.clear()
        _AXES_CACHE[key]=tuple(a.copy() for a in result)
    return result

def world(frame,p):
    o,u,v,n=axes(frame); return o+u*p[0]+v*p[1]

def local(frame,p):
    o,u,v,n=axes(frame); d=vec(p)-o; return np.array([d@u,d@v])

def face_reference(face,result=None):
    if face.geomType()!='PLANE':raise ModelError('Choose a planar face. Curved faces do not have one sketch plane.')
    from references import shape_reference
    return shape_reference(face,'face',result)

def resolve_face(solid,reference):
    from references import match_shape
    face,state=match_shape(solid,reference,'face')
    if face.geomType()!='PLANE':raise ModelError('Choose a planar supporting face.')
    return face

def projected_origin(center,normal):
    """World origin projected onto a plane: stable while the face changes size."""
    n=vec(normal);n=n/np.linalg.norm(n)
    return (n*float(vec(center)@n)).tolist()

def frame_on_face(face,projected=False):
    """Sketch frame on a planar face.

    Legacy frames use the face centre as origin, so geometry drifts when the face
    is resized. ``projected=True`` uses the world origin projected onto the face
    plane instead (the Fusion convention), which keeps sketch geometry in place.
    """
    n=vec(face.normalAt().toTuple()); ref=np.array([1.,0.,0.])
    if abs(n@ref)>.9: ref=np.array([0.,1.,0.])
    u=ref-n*(ref@n); u/=np.linalg.norm(u)
    center=list(face.Center().toTuple())
    return dict(origin=projected_origin(center,n) if projected else center,u=u.tolist(),normal=n.tolist())

def sketch_frame(sketch,solid):
    frame=sketch['frame']
    if sketch.get('support'):
        face=resolve_face(solid,sketch['support']);normal=vec(face.normalAt().toTuple());normal/=np.linalg.norm(normal)
        direction=vec(frame['u']);direction-=normal*(direction@normal)
        if np.linalg.norm(direction)<EPS:direction=vec(frame_on_face(face)['u'])
        direction/=np.linalg.norm(direction)
        center=list(face.Center().toTuple())
        origin=projected_origin(center,normal) if sketch.get('frame_origin')=='projected' else center
        frame=dict(frame,origin=origin,u=direction.tolist(),normal=normal.tolist())
    axes(frame)
    return frame

def new_sketch(frame,name='Sketch',support=None):
    return dict(kind='sketch',id=identifier(),name=name,enabled=True,frame=frame,support=support,entities=[],constraints=[])

def entity(kind,**values): return dict(id=identifier(),kind=kind,**values)

def arc_data(e):
    a,m,b=[vec(e[k]) for k in ('a','mid','b')]
    if any(len(p)!=2 for p in (a,m,b)): raise ModelError('Arc points must have two coordinates.')
    d1,d2=m-a,b-a;matrix=2*np.array([d1,d2]); rhs=np.array([d1@d1,d2@d2])
    if min(np.linalg.norm(d1),np.linalg.norm(d2))<EPS or abs(np.linalg.det(matrix))<=1e-10*np.linalg.norm(matrix[0])*np.linalg.norm(matrix[1]): raise ModelError('Arc points must not lie on a straight line.')
    c=a+np.linalg.solve(matrix,rhs); r=float(np.linalg.norm(a-c))
    ta,tm,tb=[math.atan2(*(p-c)[::-1]) for p in (a,m,b)]
    sweep=(tb-ta)%(2*math.pi)
    if (tm-ta)%(2*math.pi)>sweep: sweep-=2*math.pi
    return c,r,ta,sweep

def _basis_from_major(center,major):
    c=vec(center);m=vec(major);axis=m-c;radius=float(np.linalg.norm(axis))
    if radius<EPS:raise ModelError('Major radius must be greater than zero.')
    u=axis/radius;v=np.array([-u[1],u[0]])
    return c,u,v,radius

def slot_parts(e):
    """Exact slot boundary in local coordinates: two lines and two half-circle arcs.

    Returns ``(kind, points)`` pairs in boundary order, where lines carry
    ``(start, end)`` and arcs carry ``(start, through, end)``. The order matches
    ``sample()`` so display, picking and solids walk the same way.
    """
    a,b=vec(e['a']),vec(e['b']);r=positive(e['width'],'Slot width')/2;d=b-a;length=float(np.linalg.norm(d))
    if length<EPS:raise ModelError('Slot centers must be different points.')
    u=d/length;v=np.array([-u[1],u[0]])
    return [('line',(a+v*r,b+v*r)),('arc',(b+v*r,b+u*r,b-v*r)),('line',(b-v*r,a-v*r)),('arc',(a-v*r,a-u*r,a+v*r))]

def regular_polygon(center,point,sides,mode='inscribed'):
    if isinstance(sides,bool) or int(sides)!=sides or not 3<=int(sides)<=128:raise ModelError('Polygon sides must be between 3 and 128.')
    c=vec(center);p=vec(point);r=float(np.linalg.norm(p-c))
    if r<EPS:raise ModelError('Polygon radius must be greater than zero.')
    start=math.atan2(p[1]-c[1],p[0]-c[0])
    if mode=='circumscribed':r/=math.cos(math.pi/int(sides));start-=math.pi/int(sides)
    elif mode=='edge':
        midpoint=(c+p)/2;normal=np.array([-math.sin(start),math.cos(start)])
        first=c.copy();c=midpoint+normal*r/(2*math.tan(math.pi/int(sides)))
        r=float(np.linalg.norm(first-c));start=math.atan2(first[1]-c[1],first[0]-c[0])
    elif mode!='inscribed':raise ModelError('Unknown polygon sizing mode.')
    angles=start+np.arange(int(sides))*2*math.pi/int(sides)
    return (c+np.column_stack((np.cos(angles),np.sin(angles)))*r).tolist()

def _curve_endpoints(e):
    kind=e['kind']
    if kind in ('ellipse','spline','conic') and ('range' in e or e.get('basis')=='bspline'):
        from curves import sample_curve
        points=sample_curve(e,2);return points[0],points[-1]
    if kind in ('line','arc','conic'):return vec(e['a']),vec(e['b'])
    if kind=='spline':
        pts=e.get('points',[])
        if len(pts)<2:raise ModelError('Spline needs at least two control points.')
        return vec(pts[0]),vec(pts[-1])
    raise ModelError('Entity does not have open endpoints.')

def _catmull_rom(points,steps,closed=False):
    pts=np.asarray(points,dtype=float)
    if len(pts)>2 and np.linalg.norm(pts[0]-pts[-1])<EPS:pts=pts[:-1];closed=True
    if len(pts)<2:raise ModelError('Spline needs at least two control points.')
    if len(pts)==2:return np.linspace(pts[0],pts[1],max(2,steps)+1)
    samples=[];per=max(4,int(math.ceil(steps/max(1,len(pts)-1))))
    ext=np.vstack((pts[-1],pts,pts[0],pts[1])) if closed else np.vstack((pts[0],pts,pts[-1]))
    for i in range(1,len(ext)-2):
        p0,p1,p2,p3=ext[i-1:i+3]
        for t in np.linspace(0,1,per,endpoint=False):
            t2=t*t;t3=t2*t
            q=.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t2+(-p0+3*p1-3*p2+p3)*t3)
            samples.append(q)
    samples.append(pts[0] if closed else pts[-1])
    return np.asarray(samples)

def text_polygons(text,position,height,font='Liberation Sans'):
    """Convert sketch text into ordinary polygon loops using CadQuery's font engine.

    Storing the result as normal polygons keeps files simple: text can be selected,
    mirrored/patterned and extruded without introducing a special font dependency
    into the document schema after creation.
    """
    text=str(text)
    if not text.strip():raise ModelError('Text cannot be empty.')
    height=positive(height,'Text height');position=vec(position)
    if len(position)!=2:raise ModelError('Text position needs two coordinates.')
    shape=None;last=None
    for candidate in (font,'DejaVu Sans','Arial'):
        try:
            shape=cq.Workplane('XY').text(text,height,max(height*.02,.01),combine=False,font=candidate,halign='left',valign='bottom').val();break
        except Exception as err:last=err
    if shape is None:raise ModelError('Could not create text with an installed system font.') from last
    faces=[f for f in shape.Faces() if f.geomType()=='PLANE' and f.normalAt().z>0.9]
    loops=[]
    for face in faces:
        for wire in face.Wires():
            points=[]
            for edge in wire.Edges():
                count=2 if edge.geomType()=='LINE' else 12
                values=np.linspace(0,1,count,endpoint=False)
                for value in values:
                    q=edge.positionAt(float(value));points.append([float(q.x)+position[0],float(q.y)+position[1]])
            if len(points)>=3:
                compact=[]
                for q in points:
                    if not compact or math.dist(compact[-1],q)>1e-7:compact.append(q)
                if len(compact)>=3:loops.append(entity('polygon',points=compact))
    if not loops:raise ModelError('Text did not produce any sketch outlines.')
    return loops

def sample(e,steps=64):
    kind=e['kind']
    if kind in ('ellipse','spline','conic'):
        from curves import sample_curve
        return sample_curve(e,steps)
    if kind=='line': return np.array([e['a'],e['b']],dtype=float)
    if kind=='rectangle':
        x,y=map(float,e['center']); w=positive(e['width'],'Width')/2; h=positive(e['height'],'Height')/2
        return np.array([[x-w,y-h],[x+w,y-h],[x+w,y+h],[x-w,y+h],[x-w,y-h]])
    if kind=='circle':
        r=positive(e['radius'],'Radius'); c=vec(e['center']); t=np.linspace(0,2*math.pi,steps+1)
        return c+np.column_stack((np.cos(t),np.sin(t)))*r
    if kind=='arc':
        c,r,t,s=arc_data(e); angles=np.linspace(t,t+s,steps+1)
        return c+np.column_stack((np.cos(angles),np.sin(angles)))*r
    if kind=='polygon':
        p=np.array(e['points'],dtype=float); return np.vstack((p,p[0]))
    if kind=='ellipse':
        c,u,v,rx=_basis_from_major(e['center'],e['major']);ry=positive(e['minor_radius'],'Minor radius');t=np.linspace(0,2*math.pi,steps+1)
        return c+np.outer(np.cos(t)*rx,u)+np.outer(np.sin(t)*ry,v)
    if kind=='slot':
        a,b=vec(e['a']),vec(e['b']);r=positive(e['width'],'Slot width')/2;d=b-a;length=float(np.linalg.norm(d))
        if length<EPS:raise ModelError('Slot centers must be different points.')
        u=d/length;v=np.array([-u[1],u[0]]);per=max(8,steps//2)
        # Start at a+v*r, walk the upper side, round B, lower side, round A.
        upper_a=a+v*r;upper_b=b+v*r;lower_b=b-v*r;lower_a=a-v*r
        theta=math.atan2(v[1],v[0]);arc_b=np.array([b+np.array([math.cos(t),math.sin(t)])*r for t in np.linspace(theta,theta-math.pi,per+1)])
        arc_a=np.array([a+np.array([math.cos(t),math.sin(t)])*r for t in np.linspace(theta-math.pi,theta-2*math.pi,per+1)])
        return np.vstack(([upper_a,upper_b],arc_b[1:], [lower_a],arc_a[1:]))
    if kind=='spline':return _catmull_rom(e['points'],steps,e.get('closed',False))
    if kind=='conic':
        a,c,b=vec(e['a']),vec(e['control']),vec(e['b']);t=np.linspace(0,1,steps+1)[:,None]
        return (1-t)**2*a+2*(1-t)*t*c+t**2*b
    if kind=='point':return np.array([e['p']],dtype=float)
    raise ModelError('Unknown sketch entity.')

def snap_points(e):
    if 'range' in e:return sample(e,2).tolist()
    if e['kind'] in ('rectangle','polygon'): return sample(e)[:-1].tolist()
    if e['kind']=='circle':
        c=vec(e['center']); r=float(e['radius'])
        return [c.tolist()]+[(c+np.array(p)*r).tolist() for p in [(1,0),(-1,0),(0,1),(0,-1)]]
    if e['kind']=='line': return [e['a'],e['b'],((vec(e['a'])+vec(e['b']))/2).tolist()]
    if e['kind']=='arc': return [e['a'],e['b'],e['mid'],arc_data(e)[0].tolist()]
    if e['kind']=='ellipse':
        c,u,v,rx=_basis_from_major(e['center'],e['major']);ry=float(e['minor_radius'])
        return [c.tolist(),(c+u*rx).tolist(),(c-u*rx).tolist(),(c+v*ry).tolist(),(c-v*ry).tolist()]
    if e['kind']=='slot':return [e['a'],e['b'],((vec(e['a'])+vec(e['b']))/2).tolist()]
    if e['kind']=='spline':return [list(p) for p in e['points']]
    if e['kind']=='conic':return [e['a'],e['b'],e['control']]
    if e['kind']=='point':return [e['p']]
    return []

def nearest_on_entity(e,p):
    p=vec(p)
    if e['kind'] in ('ellipse','spline','conic'):
        from curves import project,evaluate
        return evaluate(e,project(e,p))
    if e['kind']=='point':return vec(e['p'])
    if e['kind'] in ('circle','arc'):
        if e['kind']=='circle': c=vec(e['center']); r=float(e['radius']); angle=0; sweep=2*math.pi
        else: c,r,angle,sweep=arc_data(e)
        d=p-c; length=np.linalg.norm(d)
        q=c+(d/length if length>EPS else np.array([1.,0.]))*r
        if e['kind']=='arc':
            theta=math.atan2(*(q-c)[::-1]); delta=(theta-angle)%(2*math.pi) if sweep>0 else (angle-theta)%(2*math.pi)
            if delta>abs(sweep): q=min([vec(e['a']),vec(e['b'])],key=lambda t:np.linalg.norm(t-p))
        return q
    pts=sample(e);a=pts[:-1];d=pts[1:]-a;length=np.sum(d*d,axis=1)
    t=np.divide(np.sum((p-a)*d,axis=1),length,out=np.zeros(len(length)),where=length>EPS**2)
    candidates=a+d*np.clip(t,0,1)[:,None]
    return candidates[int(np.argmin(np.sum((candidates-p)**2,axis=1)))]

def _segment_intersection(a,b,c,d):
    """Return the finite 2D intersection of two line segments, if one exists."""
    a,b,c,d=map(vec,(a,b,c,d));r=b-a;s=d-c
    den=r[0]*s[1]-r[1]*s[0]
    if abs(den)<1e-12:return None
    q=c-a;t=(q[0]*s[1]-q[1]*s[0])/den;u=(q[0]*r[1]-q[1]*r[0])/den
    if -EPS<=t<=1+EPS and -EPS<=u<=1+EPS:return a+t*r
    return None

def snap_intersections(entities):
    """Exact line/circle/arc intersections with bounding-box pruning."""
    from trim import primitives,intersections,primitive_bounds
    parts=[]
    for e in entities:
        for part in primitives(e):
            if part['kind']=='line':
                if np.linalg.norm(part['b']-part['a'])<=EPS:continue
                low=np.minimum(part['a'],part['b']);high=np.maximum(part['a'],part['b'])
            else:low,high=primitive_bounds(part)
            parts.append((part,e['id'],low,high))
    result=[];seen=set();active=[]
    for index in sorted(range(len(parts)),key=lambda i:parts[i][2][0]):
        a,ida,low,high=parts[index]
        active=[j for j in active if parts[j][3][0]>=low[0]-EPS]
        for j in active:
            b,idb,other_low,other_high=parts[j]
            if ida==idb or high[1]<other_low[1]-EPS or other_high[1]<low[1]-EPS:continue
            for q in intersections(a,b):
                key=tuple(np.round(q,7))
                if key not in seen:seen.add(key);result.append(q)
        active.append(index)
    return result

def snap(p,entities,grid=1.,tolerance=1.,extra=(),intersections=None):
    """Endpoint/center/intersection snaps win over edges, then the adaptive grid."""
    p=vec(p); tolerance=positive(tolerance,'Snap tolerance'); grid=positive(grid,'Grid spacing')
    points=[(vec(q),'vertex / center') for e in entities for q in snap_points(e)]
    points.extend((vec(q),'intersection') for q in (snap_intersections(entities) if intersections is None else intersections))
    points.extend((vec(q),'endpoint') for q in extra)
    if points:
        q,label=min(points,key=lambda pair:np.linalg.norm(pair[0]-p))
        if np.linalg.norm(q-p)<=tolerance: return q,label
    edges=[nearest_on_entity(e,p) for e in entities]
    if edges:
        q=min(edges,key=lambda t:np.linalg.norm(t-p))
        if np.linalg.norm(q-p)<=tolerance: return q,'edge'
    return np.round(p/grid)*grid,'grid'

def validate_entity(e):
    if 'construction' in e and not isinstance(e['construction'],bool):raise ModelError('Construction status must be true or false.')
    sample(e)
    for p in sample(e,8):
        if len(p)!=2 or not np.isfinite(p).all(): raise ModelError('Sketch coordinates must be finite pairs.')
    if e['kind']=='line' and math.dist(e['a'],e['b'])<EPS: raise ModelError('A line needs two different endpoints.')
    if e['kind']=='polygon' and len(e['points'])<3: raise ModelError('Polygon needs at least three points.')
    if e['kind']=='spline' and len(e.get('points',[]))<2:raise ModelError('Spline needs at least two control points.')
    if e['kind']=='point':
        if len(e.get('p',[]))!=2:raise ModelError('Point needs two coordinates.')


def profile_geometry(sketch):
    """Derived boundary fragments; never modify the editable sketch entities."""
    return _profile_geometry(json.dumps(sketch['entities'],sort_keys=True))

@lru_cache(maxsize=32)
def _profile_geometry(encoded):
    from trim import primitives,intersections,parameter,fragment,primitive_bounds,unique_parameters
    entities=json.loads(encoded)
    records=[];parts=[];cuts=[];touched=set()
    for e in entities:
        validate_entity(e)
        if e.get('construction') or e['kind']=='point':continue
        for part_index,p in enumerate(primitives(e)):
            records.append((e,part_index));parts.append(p);cuts.append({0.,1.})
    boxes=[primitive_bounds(p) for p in parts]
    active=[]
    for i in sorted(range(len(parts)),key=lambda index:float(boxes[index][0][0])):
        a=parts[i];lo,hi=boxes[i]
        active=[j for j in active if boxes[j][1][0]>=lo[0]-EPS]
        for j in active:
            if records[i][0]['id']==records[j][0]['id']:continue
            other_lo,other_hi=boxes[j]
            if hi[1]<other_lo[1]-EPS or other_hi[1]<lo[1]-EPS:continue
            for point in intersections(a,parts[j]):
                for index in (i,j):
                    t=min(1.,max(0.,parameter(parts[index],point)))
                    # Snap numerically approximate curve/line intersections to
                    # their true endpoints; otherwise tiny invalid fragments
                    # appear and break region validation during later features.
                    if t<1e-7:t=0.
                    elif t>1.-1e-7:t=1.
                    cuts[index].add(t)
                    touched.add(records[index][0]['id'])
        active.append(i)
    split_ids={records[i][0]['id'] for i in range(len(parts)) if len(cuts[i])>2}
    split_ids.update(e['id'] for e in entities if e['id'] in touched and e['kind'] in ('rectangle','polygon','circle','ellipse','slot'))
    result=[];expanded=set()
    for i,(e,part_index) in enumerate(records):
        # Keep whole untouched entities, including exact circles and legacy IDs.
        # Only generate fragments where topology actually requires subdivision.
        split=e['id'] in split_ids
        if not split:
            if e['id'] not in expanded:result.append(e);expanded.add(e['id'])
            continue
        values=[0.]+[t for t in unique_parameters(cuts[i]) if 1e-9<t<1-1e-9]+[1.]
        if parts[i].get('closed') and not any(abs(t-.5)<=1e-9 for t in values):values=sorted(values+[.5])
        for lo,hi in zip(values[:-1],values[1:]):
            if hi-lo<1e-9:continue
            piece=fragment(parts[i],lo,hi)
            piece['id']=f"{e['id']}~{part_index}:{lo:.10f}:{hi:.10f}"
            result.append(piece)
    return result

def regions(sketch):
    return _regions(json.dumps(sketch['entities'],sort_keys=True))

@lru_cache(maxsize=32)
def _regions(encoded):
    """Return every bounded closed profile in the sketch.

    Open line/arc entities are treated as a planar embedded graph.  Each
    directed edge is walked around the face on its left, which lets two
    neighboring profiles legitimately share the same boundary edge.  The old
    implementation marked an edge as globally used after the first cycle and
    therefore lost adjacent trim-created regions.
    """
    sketch={'entities':json.loads(encoded)};result=[];open_edges=[]
    for e in profile_geometry(sketch):
        validate_entity(e)
        if e.get('construction',False):continue
        if 'range' not in e and (e['kind'] in ('rectangle','circle','polygon','ellipse','slot') or e['kind']=='spline' and (e.get('closed') or math.dist(e['points'][0],e['points'][-1])<EPS)):
            result.append([e['id']])
        elif e['kind'] in ('line','arc','spline','conic','ellipse'):
            open_edges.append(e)

    if not open_edges:return result

    # Merge endpoints by distance, not by rounding: two points 1e-8 apart can
    # round to different keys and silently break an otherwise closed loop.
    buckets={}
    def key(p):
        p=(float(p[0]),float(p[1]));cell=(math.floor(p[0]/EPS),math.floor(p[1]/EPS))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for q in buckets.get((cell[0]+dx,cell[1]+dy),()):
                    if math.dist(p,q)<=EPS:return q
        buckets.setdefault(cell,[]).append(p);return p
    half=[];outgoing={};reverse={}
    unique=[];signatures=set()
    for e in open_edges:
        pts=sample(e,2);mid=(pts[0]+pts[-1])/2 if e['kind']=='line' else pts[len(pts)//2]
        signature=tuple(sorted((key(pts[0]),key(pts[-1]))))+ (key(mid),)
        if signature in signatures:continue
        signatures.add(signature);unique.append(e)
    open_edges=unique
    for edge_index,e in enumerate(open_edges):
        ea,eb=_curve_endpoints(e);a,b=key(ea),key(eb)
        pts=sample(e,24 if e['kind'] in ('arc','spline','conic','ellipse') else 2)
        directions=(pts[1]-pts[0],pts[-2]-pts[-1])
        first=len(half)
        half.append(dict(edge=edge_index,source=a,target=b,forward=True,angle=math.atan2(directions[0][1],directions[0][0])))
        half.append(dict(edge=edge_index,source=b,target=a,forward=False,angle=math.atan2(directions[1][1],directions[1][0])))
        reverse[first]=first+1;reverse[first+1]=first
        outgoing.setdefault(a,[]).append(first);outgoing.setdefault(b,[]).append(first+1)
    # A dangling stroke or a connector between loops bounds no face. Remove
    # graph bridges before walking so a spur cannot corrupt an otherwise valid wire.
    discovery={};low={};bridges=set();clock=0
    for node in outgoing:
        if node in discovery:continue
        clock+=1;discovery[node]=low[node]=clock
        stack=[(node,None,None,iter(outgoing[node]))]
        while stack:
            current,parent,parent_edge,iterator=stack[-1]
            h=next(iterator,None)
            if h is None:
                stack.pop()
                if parent is not None:
                    low[parent]=min(low[parent],low[current])
                    if low[current]>discovery[parent]:bridges.add(parent_edge)
                continue
            edge=half[h]['edge'];target=half[h]['target']
            if edge==parent_edge:continue
            if target not in discovery:
                clock+=1;discovery[target]=low[target]=clock
                stack.append((target,current,edge,iter(outgoing[target])))
            else:low[current]=min(low[current],discovery[target])
    for node,items in outgoing.items():
        items[:]=[h for h in items if half[h]['edge'] not in bridges];items.sort(key=lambda h:half[h]['angle'])

    def next_half(h):
        node=half[h]['target'];items=outgoing.get(node,[]);back=reverse[h]
        if back not in items:return None
        # Immediately clockwise from the reverse edge keeps the current face
        # on the left side of the walk.  Positive-area walks are bounded faces.
        return items[(items.index(back)-1)%len(items)]

    def directed_points(h):
        e=open_edges[half[h]['edge']];pts=sample(e,32 if e['kind'] in ('arc','spline','conic','ellipse') else 2)
        return pts if half[h]['forward'] else pts[::-1]

    seen=set();found=set()
    for seed in range(len(half)):
        if half[seed]['edge'] in bridges:continue
        if seed in seen:continue
        walk=[];local={};h=seed
        while h is not None and h not in local and h not in seen:
            local[h]=len(walk);walk.append(h);h=next_half(h)
        seen.update(walk)
        if h!=seed or len(walk)<2:continue
        points=[]
        for i,item in enumerate(walk):
            pts=directed_points(item)
            points.extend(pts.tolist() if i==0 else pts[1:].tolist())
        if len(points)<3:continue
        poly=np.asarray(points,dtype=float)
        area=.5*float(np.sum(poly[:-1,0]*poly[1:,1]-poly[1:,0]*poly[:-1,1]))
        if not np.allclose(poly[0],poly[-1],atol=EPS):
            area+=.5*float(poly[-1,0]*poly[0,1]-poly[0,0]*poly[-1,1])
        if area<=EPS:continue
        ids=tuple(open_edges[half[item]['edge']]['id'] for item in walk)
        signature=frozenset(ids)
        if signature not in found:
            found.add(signature);result.append(list(ids))
    return result

def wire_for(sketch,ids,frame):
    lookup={e['id']:e for e in sketch['entities']};lookup.update({e['id']:e for e in profile_geometry(sketch)}); edges=[]
    def w(p): return tuple(world(frame,p))
    for id_ in ids:
        if id_ not in lookup: raise ModelError('An extruded profile entity was removed from its sketch.')
        e=lookup[id_]; validate_entity(e); kind=e['kind']
        if e.get('construction',False):raise ModelError('Construction guides cannot be extruded. Change the guide to normal geometry first.')
        if kind=='circle':
            edges.append(cq.Edge.makeCircle(float(e['radius']),w(e['center']),tuple(axes(frame)[3])))
        elif kind in ('ellipse','spline','conic'):
            from curves import edge_for
            o,u,v,n=axes(frame);edges.append(edge_for(e).transformShape(cq.Plane(tuple(o),tuple(u),tuple(n)).rG))
        elif kind=='arc': edges.append(cq.Edge.makeThreePointArc(w(e['a']),w(e['mid']),w(e['b'])))
        elif kind=='slot':
            # True arcs: a polyline would give faceted solids and STEP exports.
            for part,points in slot_parts(e):
                edges.append(cq.Edge.makeLine(*map(w,points)) if part=='line' else cq.Edge.makeThreePointArc(*map(w,points)))
        else:
            points=sample(e)
            for a,b in zip(points[:-1],points[1:]): edges.append(cq.Edge.makeLine(w(a),w(b)))
    wire=cq.Wire.assembleEdges(edges)
    if not wire.IsClosed(): raise ModelError('Select a closed sketch profile. Connect line/arc endpoints using snapping.')
    face=cq.Face.makeFromWires(wire)
    if not face.isValid() or face.Area()<EPS: raise ModelError('Sketch profile is degenerate or self-intersecting.')
    return wire

def region_points(sketch,ids):
    lookup={e['id']:e for e in sketch['entities']};lookup.update({e['id']:e for e in profile_geometry(sketch)})
    if len(ids)==1 and (lookup[ids[0]]['kind'] in ('rectangle','circle','polygon','ellipse','slot') or lookup[ids[0]]['kind']=='spline' and (lookup[ids[0]].get('closed') or math.dist(lookup[ids[0]]['points'][0],lookup[ids[0]]['points'][-1])<EPS)):return sample(lookup[ids[0]])
    remaining=[lookup[i] for i in ids]; points=sample(remaining.pop(0)).tolist()
    while remaining:
        for i,e in enumerate(remaining):
            pts=sample(e).tolist()
            if math.dist(points[-1],pts[0])<EPS: break
            if math.dist(points[-1],pts[-1])<EPS: pts=pts[::-1]; break
        else: raise ModelError('Disconnected profile.')
        points.extend(pts[1:]); remaining.pop(i)
    return np.array(points)


def transform_entity(source,matrix,offset):
    """Exact 2D isometry, including reflected arcs and rotated rectangles."""
    matrix=np.asarray(matrix,dtype=float);offset=vec(offset)
    if matrix.shape!=(2,2) or len(offset)!=2 or not np.allclose(matrix.T@matrix,np.eye(2),atol=1e-8):
        raise ModelError('Sketch copies require a rigid 2D transformation.')
    def point(p):return (matrix@vec(p)+offset).tolist()
    kind=source['kind'];flags={key:copy.deepcopy(source[key]) for key in ('construction','range','basis','degree','knots','weights','weight') if key in source}
    if kind=='rectangle':return entity('polygon',points=[point(p) for p in sample(source)[:-1]],**flags)
    if kind=='polygon':return entity(kind,points=[point(p) for p in source['points']],**flags)
    if kind=='circle':return entity(kind,center=point(source['center']),radius=source['radius'],**flags)
    if kind=='ellipse' and 'range' in source and np.linalg.det(matrix)<0:
        from curves import edge_for,nurbs_data
        data=nurbs_data(edge_for(source));data['points']=[point(p) for p in data['points']];return entity('spline',**data,construction=source.get('construction',False))
    if kind=='ellipse':return entity(kind,center=point(source['center']),major=point(source['major']),minor_radius=source['minor_radius'],**flags)
    if kind=='slot':return entity(kind,a=point(source['a']),b=point(source['b']),width=source['width'],**flags)
    if kind=='spline':return entity(kind,points=[point(p) for p in source['points']],closed=source.get('closed',False),**flags)
    if kind=='conic':return entity(kind,a=point(source['a']),control=point(source['control']),b=point(source['b']),**flags)
    if kind=='point':return entity(kind,p=point(source['p']),**flags)
    if kind in ('line','arc'):return entity(kind,**{key:point(source[key]) for key in ('a','mid','b') if key in source},**flags)
    raise ModelError('Unsupported sketch entity.')

def mirror_entities(sources,guide):
    if guide['kind']!='line':raise ModelError('Select a straight sketch line as the mirror guide.')
    a,b=vec(guide['a']),vec(guide['b']);direction=b-a;length=np.linalg.norm(direction)
    if length<EPS:raise ModelError('The mirror guide must have a nonzero length.')
    direction/=length;matrix=2*np.outer(direction,direction)-np.eye(2)
    return [transform_entity(e,matrix,a-matrix@a) for e in sources if e['id']!=guide['id']]

def circular_entities(sources,center,copies):
    center=vec(center)
    if len(center)!=2:raise ModelError('The pattern center requires two coordinates.')
    if isinstance(copies,bool) or int(copies)!=copies or not 1<=copies<=100:raise ModelError('Choose 1–100 new copies.')
    if len(sources)*(copies+1)>5000:raise ModelError('Reduce the selection or copy count (limit: 5,000 entities).')
    result=[]
    for i in range(1,int(copies)+1):
        theta=2*math.pi*i/(copies+1);c,s=math.cos(theta),math.sin(theta);matrix=np.array([[c,-s],[s,c]])
        result.extend(transform_entity(e,matrix,center-matrix@center) for e in sources)
    return result


def rectangular_entities(sources,columns,rows,spacing_x,spacing_y):
    if isinstance(columns,bool) or int(columns)!=columns or not 1<=int(columns)<=100:raise ModelError('Columns must be between 1 and 100.')
    if isinstance(rows,bool) or int(rows)!=rows or not 1<=int(rows)<=100:raise ModelError('Rows must be between 1 and 100.')
    columns=int(columns);rows=int(rows);spacing_x=number(spacing_x,'X spacing');spacing_y=number(spacing_y,'Y spacing')
    if columns*rows<=1:raise ModelError('Choose at least two pattern positions.')
    if columns>1 and abs(spacing_x)<EPS:raise ModelError('X spacing must be nonzero when using multiple columns.')
    if rows>1 and abs(spacing_y)<EPS:raise ModelError('Y spacing must be nonzero when using multiple rows.')
    if len(sources)*columns*rows>5000:raise ModelError('Reduce the selection or pattern size (limit: 5,000 entities).')
    result=[];matrix=np.eye(2)
    for row in range(rows):
        for column in range(columns):
            if row==0 and column==0:continue
            offset=np.array([column*spacing_x,row*spacing_y],dtype=float)
            result.extend(transform_entity(e,matrix,offset) for e in sources)
    return result


def profile_regions(sketch):
    return _profile_regions(json.dumps(sketch['entities'],sort_keys=True))

@lru_cache(maxsize=32)
def _profile_regions(encoded):
    """Selectable faces in one sketch, with directly nested loops as holes.

    Exact planar kernel containment preserves analytic circles/arcs; sampling is
    used only for screen display and cursor hit testing.
    """
    sketch={'entities':json.loads(encoded)};loops=regions(sketch);frame=base_frame('XY')
    faces=[cq.Face.makeFromWires(wire_for(sketch,ids,frame)) for ids in loops]
    areas=[f.Area() for f in faces];bounds=[f.BoundingBox() for f in faces];parents=[None]*len(loops)
    for i,child in enumerate(faces):
        candidates=[];b=bounds[i]
        for j,parent in enumerate(faces):
            if i==j or areas[j]<=areas[i]+EPS:continue
            a=bounds[j]
            if b.xmin<a.xmin-EPS or b.xmax>a.xmax+EPS or b.ymin<a.ymin-EPS or b.ymax>a.ymax+EPS:continue
            overlap=parent.intersect(child).Area()
            if abs(overlap-areas[i])<=max(EPS,areas[i]*1e-8):candidates.append(j)
        if candidates:parents[i]=min(candidates,key=lambda j:areas[j])
    return [dict(entities=ids,holes=[loops[j] for j,p in enumerate(parents) if p==i],
                 points=region_points(sketch,ids),hole_points=[region_points(sketch,loops[j]) for j,p in enumerate(parents) if p==i])
            for i,ids in enumerate(loops)]
