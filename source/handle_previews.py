"""Live previews for drag arrows: cheap polylines rebuilt from the current value.

Everything here is plain NumPy so a drag never waits for the CAD kernel. The
kernel data (edge stations, face outlines, body depth) is gathered once when a
tool's arrow is set up; Preview/Apply still build the exact geometry.
"""
import math
import numpy as np


def _unit(v):
    v=np.asarray(v,dtype=float);n=float(np.linalg.norm(v))
    return v/n if n>1e-12 else None


def _arc(center,a,b,count=9):
    """Circular arc from a to b around center (|a-c| == |b-c|), the short way."""
    radius=float(np.linalg.norm(a-center));points=[]
    for t in np.linspace(0,1,count):
        d=_unit((1-t)*(a-center)+t*(b-center))
        points.append(center+(d if d is not None else a-center)*radius)
    return np.asarray(points)


# --- Fillet / chamfer --------------------------------------------------------

def edge_station(point,tangent,n1,n2,convex):
    """Where an edge's fillet/chamfer starts on each face, per unit size.

    ``v1``/``v2`` run along each face, away from the edge; ``alpha`` is the angle
    of the wedge they span (the material for a convex edge, the open corner for a
    concave one). Returns None when the faces are tangent (nothing to round).
    """
    t=_unit(tangent);n1=_unit(n1);n2=_unit(n2)
    if t is None or n1 is None or n2 is None:return None
    other=-n2 if convex else n2
    v1=_unit(np.cross(t,n1));v2=_unit(np.cross(t,n2))
    if v1 is None or v2 is None:return None
    if v1@(other)<0:v1=-v1
    other=-n1 if convex else n1
    if v2@(other)<0:v2=-v2
    alpha=math.acos(max(-1.,min(1.,float(v1@v2))))
    if alpha<1e-3 or alpha>math.pi-1e-3:return None
    return dict(point=np.asarray(point,float),v1=v1,v2=v2,alpha=alpha)


def _line_intersection(p0,p1,q0,q1,tolerance):
    """Point where two (nearly) intersecting 3D lines cross, or None if parallel/skew."""
    d=p1-p0;e=q1-q0;cross=np.cross(d,e);denom=float(cross@cross)
    if denom<=1e-12*float(d@d)*float(e@e)+1e-30:return None
    w=q0-p0
    t=float(np.cross(w,e)@cross)/denom;s=float(np.cross(w,d)@cross)/denom
    a=p0+d*t;b=q0+e*s
    if float(np.linalg.norm(a-b))>tolerance:return None
    return (a+b)/2


def edge_ghost(edges,chamfer=False):
    """Preview of a fillet (or chamfer) of size ``value`` on several edges.

    ``edges`` is a list of dicts ``stations`` (from :func:`edge_station`), ``faces``
    (hashable ids of the two faces), ``vertices`` (ids of the start/end vertex) and
    ``straight``. Plain lists of stations are accepted too. Where two selected edges meet
    at a vertex and their rails lie on the same face, the rails are cut at the point
    where they cross, the way the real fillet's boundary lines meet, and the cross
    sections that would sit inside such a corner are left out.
    """
    entries=[]
    for item in edges:
        if isinstance(item,dict):entries.append(item)
        else:entries.append(dict(stations=item,faces=None,vertices=None,straight=False))

    def build(value):
        value=max(0.,float(value))
        if value<=0:return []
        rails=[];sections=[]
        for index,entry in enumerate(entries):
            usable=[s for s in entry['stations'] if s is not None]
            if not usable:continue
            straight=bool(entry.get('straight')) and len(usable)>=2
            def corner(s):
                half=s['alpha']/2
                setback=value if chamfer else value/math.tan(half)
                return s['point']+s['v1']*setback,s['point']+s['v2']*setback,half
            if straight:
                first,last=usable[0],usable[-1]
                mid=dict(first,point=(first['point']+last['point'])/2)
                picks=[(0,first),(.5,mid),(1,last)]
                pair=[corner(first),corner(last)]
                rail_a=np.asarray([pair[0][0],pair[1][0]]);rail_b=np.asarray([pair[0][1],pair[1][1]])
            else:
                points=[corner(s) for s in usable]
                rail_a=np.asarray([c[0] for c in points]);rail_b=np.asarray([c[1] for c in points])
                chosen=np.linspace(0,len(usable)-1,min(3,len(usable))).round().astype(int)
                picks=[(int(i)/(max(1,len(usable)-1)),usable[int(i)]) for i in dict.fromkeys(chosen.tolist())]
            faces=entry.get('faces') or (None,None)
            rails.append(dict(edge=index,pts=rail_a,face=faces[0],straight=straight,vertices=entry.get('vertices')))
            rails.append(dict(edge=index,pts=rail_b,face=faces[1],straight=straight,vertices=entry.get('vertices')))
            sections.append((index,picks,straight))
        # Cut rails where neighbouring selected edges' rails cross on a shared face.
        trimmed=set()
        for i in range(len(rails)):
            for j in range(i+1,len(rails)):
                r,t=rails[i],rails[j]
                if r['edge']==t['edge'] or r['face'] is None or r['face']!=t['face']:continue
                if not (r['straight'] and t['straight'] and r['vertices'] and t['vertices']):continue
                shared=[(a,b) for a in (0,1) for b in (0,1) if r['vertices'][a]==t['vertices'][b]]
                if len(shared)!=1:continue
                a_end,b_end=shared[0]
                size=max(float(np.linalg.norm(r['pts'][1]-r['pts'][0])),float(np.linalg.norm(t['pts'][1]-t['pts'][0])),1e-6)
                cross=_line_intersection(r['pts'][0],r['pts'][1],t['pts'][0],t['pts'][1],size*1e-4+1e-6)
                if cross is None:continue
                r['pts'][a_end]=cross;t['pts'][b_end]=cross
                trimmed.add((r['edge'],a_end));trimmed.add((t['edge'],b_end))
        lines=[np.asarray(r['pts']) for r in rails]
        for index,picks,straight in sections:
            for fraction,s in picks:
                if straight and ((fraction==0 and (index,0) in trimmed) or (fraction==1 and (index,1) in trimmed)):continue
                half=s['alpha']/2
                setback=value if chamfer else value/math.tan(half)
                a=s['point']+s['v1']*setback;b=s['point']+s['v2']*setback
                if chamfer:lines.append(np.asarray([a,b]))
                else:
                    w=_unit(s['v1']+s['v2'])
                    if w is None:continue
                    lines.append(_arc(s['point']+w*(value/math.sin(half)),a,b))
        return lines
    return build


def changed_outlines(base,result,polyline):
    """Boundary polylines of the faces a fillet/chamfer really created.

    ``base`` and ``result`` are kernel shapes; a face of ``result`` counts as new when it
    is not a base face and its sample points do not lie on any same-type base face (so
    faces that were merely trimmed by the operation are not drawn).
    """
    base_faces=list(base.Faces());lines=[]
    def derived(face):
        """True when ``face`` is an existing face that was only trimmed or enlarged."""
        kind=face.geomType()
        if kind=='PLANE':
            try:
                normal=np.asarray(face.normalAt().toTuple(),float);centre=np.asarray(face.Center().toTuple(),float)
                for candidate in base_faces:
                    if candidate.geomType()!='PLANE':continue
                    n=np.asarray(candidate.normalAt().toTuple(),float)
                    if abs(float(normal@n))>1-1e-6 and abs(float((centre-np.asarray(candidate.Center().toTuple(),float))@n))<1e-5:return True
            except Exception:return False
            return False
        try:vertices,_=face.tessellate(0.25)
        except Exception:return False
        if not len(vertices):return False
        picks=[vertices[0],vertices[len(vertices)//2],vertices[-1]]
        import cadquery as cq
        for candidate in base_faces:
            if candidate.geomType()!=kind:continue
            close=0
            for v in picks:
                try:close+=candidate.distance(cq.Vertex.makeVertex(float(v.x),float(v.y),float(v.z)))<1e-4
                except Exception:pass
            if close>=2:return True
        return False
    for face in result.Faces():
        if any(face.isSame(candidate) for candidate in base_faces):continue
        if derived(face):continue
        for edge in face.Edges():lines.append(polyline(edge))
    return lines


# --- Prisms: offset face, press/pull, extrude-like previews -------------------

def prism_ghost(loops,direction,connectors=5,keep_base=False):
    """Outlines moved by ``value`` along ``direction`` plus a few side lines."""
    direction=np.asarray(direction,float);loops=[np.asarray(loop,float) for loop in loops]
    def build(value):
        shift=direction*float(value);lines=[]
        for loop in loops:
            if keep_base:lines.append(loop)
            moved=loop+shift;lines.append(moved)
            for j in np.linspace(0,len(loop)-1,min(connectors,len(loop)),dtype=int):lines.append(np.asarray([loop[j],moved[j]]))
        return lines
    return build


def plane_ghost(origin,u,v,normal,size):
    origin,u,v,normal=(np.asarray(x,float) for x in (origin,u,v,normal))
    square=np.asarray([origin+u*x+v*y for x,y in ((-size,-size),(size,-size),(size,size),(-size,size),(-size,-size))])
    def build(value):
        moved=square+normal*float(value)
        return [moved,np.asarray([moved[0],moved[2]]),np.asarray([moved[1],moved[3]])]+[np.asarray([square[i],moved[i]]) for i in range(4)]
    return build


# --- Hole ------------------------------------------------------------------

def _ring(center,u,v,radius,count=41):
    return np.asarray([center+(u*math.cos(t)+v*math.sin(t))*radius for t in np.linspace(0,2*math.pi,count)])


def hole_ghost(origin,u,v,direction,diameter,hole_type='simple',head_diameter=10.,head_depth=3.,head_angle=90.):
    """Drilled cylinder of the current depth, with its counterbore or countersink head."""
    origin,u,v,direction=(np.asarray(x,float) for x in (origin,u,v,direction))
    radius=float(diameter)/2;head=float(head_diameter)/2
    def build(value):
        depth=max(0.,float(value));bottom=origin+direction*depth
        lines=[_ring(origin,u,v,radius),_ring(bottom,u,v,radius)]
        for t in np.linspace(0,2*math.pi,4,endpoint=False):
            side=(u*math.cos(t)+v*math.sin(t))*radius;lines.append(np.asarray([origin+side,bottom+side]))
        if hole_type=='counterbore' and head>radius:
            level=origin+direction*min(depth,float(head_depth))
            lines+=[_ring(origin,u,v,head),_ring(level,u,v,head)]
        elif hole_type=='countersink' and head>radius:
            h=min(depth,(head-radius)/math.tan(math.radians(max(1.,float(head_angle))/2)))
            lines.append(_ring(origin,u,v,head))
            for t in np.linspace(0,2*math.pi,4,endpoint=False):
                d=u*math.cos(t)+v*math.sin(t);lines.append(np.asarray([origin+d*head,origin+direction*h+d*radius]))
        return lines
    return build


# --- Shell -----------------------------------------------------------------

def chain_loop(segments,tolerance=1e-6):
    """Join sampled edge polylines of a wire into one ordered closed loop."""
    segments=[np.asarray(s,float) for s in segments if len(s)>=2]
    if not segments:return np.empty((0,3))
    loop=list(segments.pop(0))
    while segments:
        end=loop[-1];best=None
        for i,s in enumerate(segments):
            for reverse in (False,True):
                start=s[-1] if reverse else s[0];d=float(np.linalg.norm(start-end))
                if best is None or d<best[0]:best=(d,i,reverse)
        d,i,reverse=best;s=segments.pop(i);s=s[::-1] if reverse else s
        loop.extend(s[1:] if d<=max(tolerance,1e-4) else s)
    return np.asarray(loop)


def offset_loop_2d(points,distance,limit=4.):
    """Miter offset of a closed 2D polygon; positive distance moves inward."""
    p=np.asarray(points,float)
    if len(p)>1 and np.allclose(p[0],p[-1]):p=p[:-1]
    if len(p)<3:return p
    area=.5*float(np.sum(p[:,0]*np.roll(p[:,1],-1)-np.roll(p[:,0],-1)*p[:,1]))
    sign=1. if area>0 else -1.
    out=[]
    for i in range(len(p)):
        d0=_unit(p[i]-p[i-1]);d1=_unit(p[(i+1)%len(p)]-p[i])
        if d0 is None:d0=d1
        if d1 is None:d1=d0
        if d0 is None:out.append(p[i]);continue
        # Inward normals of the two edges at this corner; the corner moves along their
        # bisector by distance / cos(half angle), capped for very sharp corners.
        n0=np.array([-d0[1],d0[0]])*sign;n1=np.array([-d1[1],d1[0]])*sign
        m=_unit(n0+n1)
        if m is None:m=n0
        c=float(m@n0);scale=min(limit,1./c) if c>1e-9 else limit
        out.append(p[i]+m*distance*scale)
    out.append(out[0]);return np.asarray(out)


def shell_ghost(loop,center,normal,depth):
    """Inner rim and floor of a shell opened at a planar face.

    ``value`` is the wall thickness measured into the body (positive = inward
    walls, the usual shell). ``depth`` is how far the body extends behind the face.
    """
    loop=np.asarray(loop,float);center=np.asarray(center,float);n=_unit(normal)
    helper=np.array([1.,0.,0.]) if abs(n[0])<.9 else np.array([0.,1.,0.])
    u=_unit(np.cross(n,helper));v=np.cross(n,u)
    flat=np.column_stack(((loop-center)@u,(loop-center)@v))
    def build(value):
        t=float(value)
        if abs(t)<1e-9 or len(flat)<3:return []
        rim2=offset_loop_2d(flat,t)
        rim=center+np.outer(rim2[:,0],u)+np.outer(rim2[:,1],v)
        floor=rim-n*max(0.,float(depth)-t)
        lines=[rim,floor]
        for j in np.linspace(0,len(rim)-1,min(5,len(rim)),dtype=int):lines.append(np.asarray([rim[j],floor[j]]))
        return lines
    return build


# --- Sketch corner tools -------------------------------------------------------

def removed_runs(points,others,tolerance):
    """Runs of the polyline ``points`` that none of the polylines in ``others`` covers.

    Used to show which part of a sketch curve a fillet or chamfer will cut away.
    """
    points=np.asarray(points,float)
    if len(points)<2:return []
    segments=[]
    for line in others:
        line=np.asarray(line,float)
        if len(line)>=2:segments.append(np.stack((line[:-1],line[1:]),axis=1))
    if not segments:return [points]
    seg=np.concatenate(segments)
    a=seg[:,0];ab=seg[:,1]-a;den=np.maximum((ab*ab).sum(axis=1),1e-18)
    covered=np.zeros(len(points),bool)
    for i,p in enumerate(points):
        t=np.clip(((p-a)*ab).sum(axis=1)/den,0.,1.)
        covered[i]=float(np.min(np.linalg.norm(a+ab*t[:,None]-p,axis=1)))<=tolerance
    runs=[];current=[]
    for i,is_covered in enumerate(covered):
        if not is_covered:
            if not current and i>0:current.append(points[i-1])
            current.append(points[i])
        elif current:
            current.append(points[i]);runs.append(np.asarray(current));current=[]
    if current:runs.append(np.asarray(current))
    return runs
