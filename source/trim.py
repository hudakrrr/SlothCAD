"""Exact intersection-bounded trimming of planar lines, circles and arcs."""
import math
import numpy as np
from geometry import entity,sample,arc_data,vec,EPS
from legacy_model import ModelError
TAU=2*math.pi

_CUT_CACHE={}

def _cached_cuts(entities,index,part,compute):
    """Small cache of trim cut parameters keyed by the exact sketch contents."""
    import json
    try:key=(json.dumps(entities,sort_keys=True,default=float),index,part)
    except (TypeError,ValueError):return compute()
    if key not in _CUT_CACHE:
        if len(_CUT_CACHE)>=64:_CUT_CACHE.clear()
        _CUT_CACHE[key]=tuple(compute())
    return _CUT_CACHE[key]

def unique_parameters(values,tolerance=1e-9):
    """Sorted parameters with near-duplicates merged but no rounding.

    Rounding to a fixed number of decimals moved trimmed endpoints by ~1e-8 on
    larger arcs, so neighboring fragments no longer met at the same point.
    """
    result=[]
    for t in sorted(float(v) for v in values):
        if not result or t-result[-1]>tolerance:result.append(t)
    return result

def primitives(e):
    if e['kind']=='line':return [dict(kind='line',a=vec(e['a']),b=vec(e['b']))]
    if e['kind'] in ('rectangle','polygon'):
        points=sample(e);return [dict(kind='line',a=a,b=b) for a,b in zip(points[:-1],points[1:])]
    if e['kind']=='circle':return [dict(kind='curve',center=vec(e['center']),radius=float(e['radius']),angle=0.,sweep=TAU,closed=True)]
    if e['kind']=='arc':
        center,radius,angle,sweep=arc_data(e);return [dict(kind='curve',center=center,radius=radius,angle=angle,sweep=sweep,closed=False)]
    if e['kind']=='point':return []
    if e['kind']=='slot':
        from geometry import slot_parts
        parts=[]
        for part,points in slot_parts(e):
            if part=='line':parts.append(dict(kind='line',a=points[0],b=points[1]))
            else:
                center,radius,angle,sweep=arc_data(dict(a=points[0].tolist(),mid=points[1].tolist(),b=points[2].tolist()))
                parts.append(dict(kind='curve',center=center,radius=radius,angle=angle,sweep=sweep,closed=False))
        return parts
    if e['kind'] in ('ellipse','spline','conic'):
        from curves import closed,edge_for
        return [dict(kind='kernel',entity=e,closed=closed(e),edge=edge_for(e))]
    points=sample(e,96);return [dict(kind='line',a=a,b=b) for a,b in zip(points[:-1],points[1:])]

def at(p,t):
    if p['kind']=='kernel':
        from curves import evaluate
        lo,hi=p['entity'].get('range',[0,1]);return evaluate(p['entity'],lo+(hi-lo)*t)
    if p['kind']=='line':return p['a']+(p['b']-p['a'])*t
    angle=p['angle']+p['sweep']*t;return p['center']+p['radius']*np.array([math.cos(angle),math.sin(angle)])

def parameter(p,point):
    if p['kind']=='kernel':
        from curves import project
        lo,hi=p['entity'].get('range',[0,1]);return (project(p['entity'],point)-lo)/(hi-lo)
    if p['kind']=='line':
        d=p['b']-p['a'];return float((point-p['a'])@d/(d@d))
    angle=math.atan2(*(point-p['center'])[::-1]);delta=(angle-p['angle'])%TAU if p['sweep']>0 else (p['angle']-angle)%TAU
    if abs(delta-TAU)<1e-9:delta=0.
    return delta/abs(p['sweep'])

def inside(p,point):
    t=parameter(p,point)
    return -1e-7<=t<=1+1e-7 and np.linalg.norm(at(p,min(1,max(0,t)))-point)<EPS*10

def cross(a,b):return a[0]*b[1]-a[1]*b[0]

def intersections(a,b):
    if a['kind']=='kernel' or b['kind']=='kernel':return kernel_intersections(a,b)
    if a['kind']=='line' and b['kind']=='line':
        d=a['b']-a['a'];e=b['b']-b['a'];den=cross(d,e)
        candidates=[a['a'],a['b'],b['a'],b['b']] if abs(den)<1e-12 else [a['a']+d*cross(b['a']-a['a'],e)/den]
    elif a['kind']=='line' or b['kind']=='line':
        line,circle=(a,b) if a['kind']=='line' else (b,a)
        d=line['b']-line['a'];q=line['a']-circle['center'];A=d@d;B=2*d@q;C=q@q-circle['radius']**2;disc=B*B-4*A*C
        if disc<-1e-9:return []
        root=math.sqrt(max(0,disc));candidates=[line['a']+d*((-B+sign*root)/(2*A)) for sign in (-1,1)]
    else:
        delta=b['center']-a['center'];distance=np.linalg.norm(delta);r,s=a['radius'],b['radius']
        if distance<EPS:return [p for p in [at(a,0),at(a,1),at(b,0),at(b,1)] if inside(a,p) and inside(b,p)] if not (a['closed'] and b['closed']) else []
        if distance>r+s+EPS or distance<abs(r-s)-EPS:return []
        along=(r*r-s*s+distance*distance)/(2*distance);height=math.sqrt(max(0,r*r-along*along));u=delta/distance;center=a['center']+along*u;perp=np.array([-u[1],u[0]])
        candidates=[center-height*perp,center+height*perp]
    return [q for q in candidates if inside(a,q) and inside(b,q)]

def fragment(p,lo,hi):
    if p['kind']=='kernel':
        import copy
        part=copy.deepcopy(p['entity']);a,b=part.get('range',[0,1]);part['id']=entity('point')['id'];part['range']=[a+(b-a)*lo,a+(b-a)*hi];part['closed']=False;return part
    if p['kind']=='line':return entity('line',a=at(p,lo).tolist(),b=at(p,hi).tolist())
    return entity('arc',a=at(p,lo).tolist(),mid=at(p,(lo+hi)/2).tolist(),b=at(p,hi).tolist())

def trim_entities(entities,index,point,preview=False):
    """Return a replacement entity list; the clicked interval alone is removed."""
    if not 0<=index<len(entities):raise ModelError('Click a sketch edge to trim.')
    if entities[index]['kind'] in ('ellipse','spline','conic'):return trim_curve(entities,index,point,preview)
    point=vec(point);parts=primitives(entities[index])
    if not parts:raise ModelError('This sketch item has no trimmable edge.')
    def distance(p):
        t=parameter(p,point)
        if p['kind']=='line':t=min(1,max(0,t))
        elif not p['closed'] and t>1:t=min((0,1),key=lambda x:np.linalg.norm(at(p,x)-point))
        return np.linalg.norm(at(p,t)-point)
    selected=min(range(len(parts)),key=lambda i:distance(parts[i]));target=parts[selected]
    def compute():
        cuts=[]
        for j,e in enumerate(entities):
            for k,other in enumerate(primitives(e)):
                if j==index and k==selected:continue
                cuts.extend(parameter(target,q) for q in intersections(target,other))
        return unique_parameters(min(1,max(0,t)) for t in cuts)
    # Hover previews call this on every repaint; the cut points only change when
    # the sketch does, so reuse them instead of re-intersecting everything.
    cuts=list(_cached_cuts(entities,index,selected,compute))
    clicked=parameter(target,point)
    if target.get('closed'):
        cuts=unique_parameters(0. if abs(t-1)<1e-8 else t for t in cuts)
        intervals=[(cuts[i],cuts[(i+1)%len(cuts)]+(1 if i==len(cuts)-1 else 0)) for i in range(len(cuts))] if len(cuts)>1 else []
        clicked%=1
    else:
        cuts=unique_parameters([0.,1.]+[t for t in cuts if 1e-9<t<1-1e-9]);intervals=list(zip(cuts[:-1],cuts[1:]));clicked=min(1,max(0,clicked))
    remove=next((i for i,(lo,hi) in enumerate(intervals) if lo-1e-9<=clicked<=hi+1e-9 or target.get('closed') and lo<=clicked+1<=hi),None)
    if preview:
        return fragment(target,*intervals[remove]) if remove is not None else entities[index]
    kept=[]
    for k,p in enumerate(parts):
        if k!=selected:kept.append(fragment(p,0,1))
        else:kept.extend(fragment(p,lo,hi) for i,(lo,hi) in enumerate(intervals) if i!=remove and hi-lo>1e-8)
    if entities[index].get('construction'):
        for e in kept:e['construction']=True
    if kept:kept[0]['id']=entities[index]['id']
    return entities[:index]+kept+entities[index+1:]

def kernel_edges(e):
    import cadquery as cq
    from curves import edge_for
    if e['kind'] in ('ellipse','spline','conic'):return [edge_for(e)]
    edges=[]
    for p in primitives(e):
        if p['kind']=='line':edges.append(cq.Edge.makeLine((*p['a'],0),(*p['b'],0)))
        elif p.get('closed'):edges.append(cq.Edge.makeCircle(p['radius'],(*p['center'],0)))
        else:edges.append(cq.Edge.makeThreePointArc((*at(p,0),0),(*at(p,.5),0),(*at(p,1),0)))
    return edges

def trim_curve(entities,index,point,preview=False):
    import copy
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from curves import edge_for,project,closed
    original=entities[index];target=edge_for(original);lo,hi=original.get('range',[0.,1.])
    def compute():
        cuts=[]
        for j,e in enumerate(entities):
            if j==index:continue
            for other in kernel_edges(e):
                section=BRepAlgoAPI_Section(target.wrapped,other.wrapped,False);section.Build()
                if not section.IsDone():raise ModelError('Curve intersection failed; the sketch was kept.')
                for vertex in cq.Shape.cast(section.Shape()).Vertices():cuts.append(project(original,vertex.Center().toTuple()[:2]))
        return sorted(set(round(max(lo,min(hi,t)),12) for t in cuts))
    cuts=list(_cached_cuts(entities,index,'curve',compute));clicked=project(original,point)
    cyclic=closed(original)
    if cyclic:
        cuts=sorted(set(0. if abs(t-1)<1e-9 else t for t in cuts))
        intervals=[(cuts[i],cuts[(i+1)%len(cuts)]+(1 if i==len(cuts)-1 else 0)) for i in range(len(cuts))] if len(cuts)>1 else []
    else:
        cuts=sorted(set([lo,hi]+cuts));intervals=list(zip(cuts[:-1],cuts[1:]))
    remove=next((i for i,(a,b) in enumerate(intervals) if a-1e-10<=clicked<=b+1e-10 or cyclic and a<=clicked+1<=b),None)
    def pieces(a,b):
        bounds=[(a,min(1,b))]+([(0,b-1)] if b>1 else [])
        result=[]
        for start,end in bounds:
            if end-start<1e-9:continue
            part=copy.deepcopy(original);part['id']=entity('point')['id'];part['range']=[start,end];part['closed']=False;result.append(part)
        return result
    if preview:
        return pieces(*intervals[remove])[0] if remove is not None else original
    kept=[part for i,bounds in enumerate(intervals) if i!=remove for part in pieces(*bounds)]
    if kept:kept[0]['id']=original['id']
    return entities[:index]+kept+entities[index+1:]

def primitive_bounds(p):
    if p['kind']=='line':return np.minimum(p['a'],p['b']),np.maximum(p['a'],p['b'])
    if p['kind']=='kernel':
        box=p['edge'].BoundingBox();return np.array([box.xmin,box.ymin]),np.array([box.xmax,box.ymax])
    return p['center']-p['radius'],p['center']+p['radius']

def primitive_edge(p):
    import cadquery as cq
    if p['kind']=='kernel':return p['edge']
    if p['kind']=='line':return cq.Edge.makeLine((*p['a'],0),(*p['b'],0))
    if p.get('closed'):return cq.Edge.makeCircle(p['radius'],(*p['center'],0))
    return cq.Edge.makeThreePointArc((*at(p,0),0),(*at(p,.5),0),(*at(p,1),0))

def kernel_intersections(a,b):
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    section=BRepAlgoAPI_Section(primitive_edge(a).wrapped,primitive_edge(b).wrapped,False);section.Build()
    if not section.IsDone():raise ModelError('Curve intersection failed; the sketch was kept.')
    return [np.asarray(v.Center().toTuple()[:2]) for v in cq.Shape.cast(section.Shape()).Vertices()]
