"""Fillets and chamfers at junctions between sketch curve primitives."""
import copy
import math
import numpy as np
from geometry import entity, EPS
from legacy_model import ModelError
from trim import primitives,fragment,at,parameter,intersections


def corner_edges(entities):
    """Return editable primitives with their source entity and local edge id."""
    records=[]
    for source,e in enumerate(entities):
        if e['kind']=='point':continue
        try:
            if e['kind'] in ('spline','conic','ellipse','slot'):
                points=np.asarray(__import__('geometry').sample(e,256),dtype=float)
                lengths=np.linalg.norm(np.diff(points,axis=0),axis=1)
                cumulative=np.concatenate(([0.],np.cumsum(lengths)))
                p={'kind':'path','points':points,'cumulative':cumulative,'length':float(cumulative[-1]),
                   'closed':np.linalg.norm(points[0]-points[-1])<EPS}
                parts=[p]
            else:parts=primitives(e)
        except Exception:continue
        for part,p in enumerate(parts):
            if p['kind']=='path':length=p['length']
            elif p['kind']=='line':length=float(np.linalg.norm(p['b']-p['a']))
            else:length=abs(float(p['sweep']))*float(p['radius'])
            if length>EPS:records.append((source,part,p,length))
    return records


def _tangent(p,side):
    if p['kind']=='path':return _point_tangent(p,side,0.)[1]
    if p['kind']=='line':d=p['b']-p['a']
    else:
        angle=p['angle']+(0 if side==0 else p['sweep'])
        d=np.array([-math.sin(angle),math.cos(angle)])*p['sweep']
    if side:d=-d
    length=np.linalg.norm(d)
    return d/max(length,EPS)


def _endpoint(p,side):
    if p['kind']=='path':return p['points'][-1 if side else 0]
    return at(p,side)


def _bounds(p):
    if p['kind']=='line':points=np.asarray([p['a'],p['b']])
    elif p['kind']=='curve':return p['center']-p['radius'],p['center']+p['radius']
    else:points=p['points']
    return np.min(points,axis=0),np.max(points,axis=0)


def _ray(record,t,direction):
    """Make an outward-facing curve fragment starting at parameter t."""
    _,_,p,total=record
    end=1. if direction>0 else 0.
    if p['kind']=='path':
        d0=t*total;d1=end*total
        points=[_point_tangent(p,0,d0)[0]]
        if direction>0:points.extend(p['points'][(p['cumulative']>d0+EPS)&(p['cumulative']<d1-EPS)])
        else:points.extend(p['points'][(p['cumulative']>d1+EPS)&(p['cumulative']<d0-EPS)][::-1])
        points.append(_point_tangent(p,0,d1)[0]);points=np.asarray(points)
        cumulative=np.concatenate(([0.],np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))))
        rayp={'kind':'path','points':points,'cumulative':cumulative,'length':float(cumulative[-1]),'closed':False}
    elif p['kind']=='curve':
        angle=p['angle']+t*p['sweep'];rayp={'kind':'curve','center':p['center'],'radius':p['radius'],'angle':angle,'sweep':p['sweep']*(end-t),'closed':False}
    else:
        q=_point_tangent(p,0,t*total)[0]
        boundary=_endpoint(p,1 if direction>0 else 0)
        rayp={'kind':'line','a':q,'b':boundary}
    available=abs(end-t)*total
    return {'record':record,'t':t,'direction':direction,'p':rayp,'length':available}


def _path_line_parts(p):
    cumulative=p['cumulative'];points=p['points'];total=p['length']
    for i,(a,b) in enumerate(zip(points[:-1],points[1:])):
        if np.linalg.norm(b-a)>EPS:yield {'kind':'line','a':a,'b':b},cumulative[i]/total,cumulative[i+1]/total


def _intersection_parts(record):
    p=record[2]
    if p['kind']=='path':
        for piece,lo,hi in _path_line_parts(p):yield piece,lo,hi
    else:yield p,0.,1.


def _box_near(bounds,point,tolerance):
    low,high=bounds
    return bool(np.all(point>=low-tolerance) and np.all(point<=high+tolerance))


def _angle_in_wedge(u,v,direction):
    if np.linalg.norm(direction)<1e-9:return 0.
    angle=lambda q:math.atan2(q[1],q[0])%(2*math.pi)
    start,end=angle(u),angle(v);target=angle(direction);sweep=(end-start)%(2*math.pi)
    if sweep>math.pi:start,end=end,start;sweep=2*math.pi-sweep
    offset=(target-start)%(2*math.pi)
    if offset<=sweep:return 0.
    return min(offset-sweep,2*math.pi-offset)


def _path_parameter(p,point):
    points=p['points'];delta=np.diff(points,axis=0);lengths=p['cumulative'][1:]-p['cumulative'][:-1]
    t=np.clip(np.sum((point-points[:-1])*delta,axis=1)/np.maximum(lengths**2,EPS),0,1)
    nearest=points[:-1]+delta*t[:,None];i=int(np.argmin(np.sum((nearest-point)**2,axis=1)))
    return float((p['cumulative'][i]+t[i]*lengths[i])/p['length'])


def _point_tangent(p,side,distance):
    if p['kind']=='path':
        total=p['length'];arc_distance=total-distance if side else distance
        cumulative=p['cumulative'];points=p['points']
        i=int(np.clip(np.searchsorted(cumulative,arc_distance,side='right')-1,0,len(cumulative)-2))
        delta=points[i+1]-points[i];length=max(float(cumulative[i+1]-cumulative[i]),EPS)
        tangent=delta/length
        if side:tangent=-tangent
        point=points[i]+delta*np.clip((arc_distance-cumulative[i])/length,0,1)
        return point,tangent
    if p['kind']=='line':
        start,end=(p['a'],p['b']) if side==0 else (p['b'],p['a'])
        tangent=(end-start)/np.linalg.norm(end-start)
        return start+tangent*distance,tangent
    r=float(p['radius']);sweep=float(p['sweep']);angle=p['angle']+(sweep if side else 0)
    start=at(p,1 if side else 0);direction=-1 if side else 1
    # Arc distance always advances in the primitive's signed sweep direction.
    # Omitting sign(sweep) made reverse-facing arcs report points on the wrong
    # side while their tangent vectors still pointed correctly, so fillets
    # either bent outward or trimmed the source curve away.
    theta=angle+direction*np.sign(sweep)*distance/r
    point=p['center']+r*np.array([math.cos(theta),math.sin(theta)])
    tangent=direction*np.sign(sweep)*np.array([-math.sin(theta),math.cos(theta)])
    return point,tangent


def _arc_through_center(a,b,center,radius,tangent_start):
    ta=math.atan2(a[1]-center[1],a[0]-center[0]);tb=math.atan2(b[1]-center[1],b[0]-center[0])
    ccw=(tb-ta)%(2*math.pi);tangent_ccw=np.array([-math.sin(ta),math.cos(ta)])
    sweep=ccw if tangent_ccw@tangent_start>=0 else ccw-2*math.pi
    mid_angle=ta+sweep/2;mid=center+radius*np.array([math.cos(mid_angle),math.sin(mid_angle)])
    return entity('arc',a=a.tolist(),mid=mid.tolist(),b=b.tolist())


def _fragment(p,lo,hi):
    if p['kind']!='path':return [fragment(p,lo,hi)]
    cumulative=p['cumulative'];points=p['points'];a=lo*p['length'];b=hi*p['length']
    start=_point_tangent(p,0,a)[0];end=_point_tangent(p,0,b)[0]
    internal=points[(cumulative>a+EPS)&(cumulative<b-EPS)]
    chain=np.vstack((start,internal,end))
    return [entity('line',a=x.tolist(),b=y.tolist()) for x,y in zip(chain[:-1],chain[1:]) if np.linalg.norm(y-x)>EPS]


def _ray_count(entries,vertex):
    rays=[]
    for record,side,_ in entries:
        direction=_tangent(record[2],side)
        if not any(float(direction@other)>.999 for other in rays):rays.append(direction)
    return len(rays)


def _fillet_points(first,side1,second,side2,radius,initial,vertex):
    """Find tangent points on line or circular arc sketch primitives."""
    p1,l1=first[2],first[3];p2,l2=second[2],second[3];u=_tangent(p1,side1);v=_tangent(p2,side2)
    if np.linalg.norm(u+v)<1e-8:raise ModelError('Choose a corner with a visible change in direction.')
    best=None
    for sign1 in (-1.,1.):
        for sign2 in (-1.,1.):
            s=np.clip(np.asarray(initial,dtype=float),1e-5,np.array([l1,l2])*.85)
            for _ in range(32):
                q1,t1=_point_tangent(p1,side1,float(s[0]));q2,t2=_point_tangent(p2,side2,float(s[1]))
                n1=sign1*np.array([-t1[1],t1[0]]);n2=sign2*np.array([-t2[1],t2[0]])
                residual=q1+radius*n1-q2-radius*n2
                if np.linalg.norm(residual)<1e-7*max(1.,radius):break
                jac=np.empty((2,2));h=max(1e-5,radius*1e-4)
                for j in range(2):
                    ss=s.copy();ss[j]=min((l1,l2)[j]*.9,ss[j]+h)
                    qq1,tt1=_point_tangent(p1,side1,float(ss[0]));qq2,tt2=_point_tangent(p2,side2,float(ss[1]))
                    rr=qq1+radius*sign1*np.array([-tt1[1],tt1[0]])-qq2-radius*sign2*np.array([-tt2[1],tt2[0]])
                    jac[:,j]=(rr-residual)/(ss[j]-s[j] if ss[j]!=s[j] else h)
                try:step=np.linalg.solve(jac,-residual)
                except np.linalg.LinAlgError:break
                if not np.all(np.isfinite(step)):break
                s=np.clip(s+np.clip(step,-radius*2,radius*2),1e-5,np.array([l1,l2])*.9)
            q1,t1=_point_tangent(p1,side1,float(s[0]));q2,t2=_point_tangent(p2,side2,float(s[1]))
            c1=q1+radius*sign1*np.array([-t1[1],t1[0]]);c2=q2+radius*sign2*np.array([-t2[1],t2[0]])
            error=float(np.linalg.norm(c1-c2))
            center=(c1+c2)/2
            # There are up to four mathematical offset-curve solutions.  Only
            # keep the one whose centre is in the corner wedge selected by the
            # two outward rays. Without this check the shortest solution can
            # be the external fillet; trimming to its tangent points then cuts
            # the wrong ends of the source edges (sometimes deleting one).
            if _angle_in_wedge(u,v,center-np.asarray(vertex,dtype=float))>1e-5:
                continue
            if error<1e-5*max(1.,radius) and s[0]<l1*.9 and s[1]<l2*.9:
                score=float(s.sum())
                if best is None or score<best[0]:best=(score,q1,q2,center,t1)
    if best is None:raise ModelError('That fillet radius does not fit the two selected sketch curves.')
    _,a,b,center,tangent=best
    return a,b,_arc_through_center(a,b,center,radius,-tangent)


def _closed_outlines(entities):
    """Sampled outlines of the closed shapes (circle, rectangle, polygon, ...) in a sketch."""
    result=[]
    for index,e in enumerate(entities):
        if e.get('construction') or e['kind']=='point':continue
        try:points=np.asarray(__import__('geometry').sample(e,160),dtype=float)
        except Exception:continue
        if len(points)>=4 and np.linalg.norm(points[0]-points[-1])<1e-6:result.append((index,points))
    return result


def _inside(point,outline):
    x,y=float(point[0]),float(point[1]);px,py=outline[:,0],outline[:,1];qx,qy=np.roll(px,-1),np.roll(py,-1)
    dy=np.where(qy!=py,qy-py,1e-300)
    crossing=((py>y)!=(qy>y))&(x<(qx-px)*(y-py)/dy+px)
    return bool(np.count_nonzero(crossing)%2)


def _inner_rays(ray1,ray2,outlines):
    """How many of the two rays run inside some other closed shape (0 = a true outline corner).

    A fillet at the union of overlapping shapes belongs on the outside of the combined
    outline, like the edge fillet of the extruded body, not on the crossing lines inside it.
    """
    count=0
    for ray in (ray1,ray2):
        owner=ray['record'][0]
        try:
            distance=max(1e-3,min(float(ray['length'])*.05,.5))
            probe=_point_tangent(ray['p'],0,distance)[0]
        except Exception:continue
        if any(index!=owner and _inside(probe,outline) for index,outline in outlines):count+=1
    return count


def modify_corner(entities,point,kind,size,tolerance,info=None):
    if kind not in ('fillet','chamfer'):raise ModelError('Unknown corner tool.')
    if not math.isfinite(size) or size<=EPS:raise ModelError('Corner size must be greater than zero.')
    point=np.asarray(point,dtype=float);records=corner_edges(entities);candidates=[];junctions={}
    # A closed circle's parameter seam is arbitrary. Keep it away from the
    # cursor so a perfectly ordinary intersection at angle 0 is not mistaken
    # for an endpoint and rejected as non-editable.
    for record in records:
        p=record[2]
        if p.get('kind')=='curve' and p.get('closed') and abs(abs(p['sweep'])-2*math.pi)<1e-7:
            offset=point-p['center']
            if np.linalg.norm(offset)>EPS:
                p['angle']=math.atan2(offset[1],offset[0])-math.copysign(.17320508075688773,p['sweep'])
    # Junctions include line/arc, arc/arc, spline, conic, ellipse, slot and
    # polygon primitives. Smooth sampled joints are filtered by their tangent.
    for record in records:
        for side in (0,1):
            q=_endpoint(record[2],side);key=tuple(np.round(q,7))
            junctions.setdefault(key,[]).append((record,side,q))
    for entries in junctions.values():
        if len(entries)<2:continue
        for i,(first,side1,q1) in enumerate(entries):
            for second,side2,q2 in entries[i+1:]:
                if first[0]==second[0] and first[1]==second[1]:continue
                if np.linalg.norm(q1-q2)>max(EPS*10,1e-7):continue
                q=(q1+q2)/2;distance=float(np.linalg.norm(q-point))
                if distance>tolerance:continue
                ray1=_ray(first,0.,1.) if side1==0 else _ray(first,1.,-1.)
                ray2=_ray(second,0.,1.) if side2==0 else _ray(second,1.,-1.)
                u=_tangent(ray1['p'],0);v=_tangent(ray2['p'],0)
                angle=math.acos(float(np.clip(u@v,-1,1)))
                if angle<math.radians(8) or angle>math.radians(172):continue
                if _ray_count(entries,q)!=2:continue
                candidates.append((distance,0.,q,ray1,ray2,angle))
    # Also find interior intersections (for example a line ending on a circle,
    # or two crossing arcs). The raw cursor offset chooses the intended wedge.
    relevant=[record for record in records if _box_near(_bounds(record[2]),point,tolerance)]
    segment_cache={}
    for i,first in enumerate(relevant):
        first_parts=segment_cache.setdefault(id(first),[(p,lo,hi) for p,lo,hi in _intersection_parts(first) if _box_near(_bounds(p),point,tolerance)])
        for second in relevant[i+1:]:
            if first[0]==second[0] and first[1]==second[1]:continue
            second_parts=segment_cache.setdefault(id(second),[(p,lo,hi) for p,lo,hi in _intersection_parts(second) if _box_near(_bounds(p),point,tolerance)])
            for p1,lo1,hi1 in first_parts:
                for p2,lo2,hi2 in second_parts:
                    try:contacts=intersections(p1,p2)
                    except Exception:continue
                    for contact in contacts:
                        distance=float(np.linalg.norm(contact-point))
                        if distance>tolerance:continue
                        t1=lo1+(hi1-lo1)*parameter(p1,contact);t2=lo2+(hi2-lo2)*parameter(p2,contact)
                        if min(t1,1-t1,t2,1-t2)<1e-7:continue
                        for direction1 in (-1.,1.):
                            for direction2 in (-1.,1.):
                                ray1=_ray(first,t1,direction1);ray2=_ray(second,t2,direction2)
                                u=_tangent(ray1['p'],0);v=_tangent(ray2['p'],0)
                                angle=math.acos(float(np.clip(u@v,-1,1)))
                                if angle<math.radians(8) or angle>math.radians(172):continue
                                wedge=_angle_in_wedge(u,v,point-contact)
                                candidates.append((distance,1.+wedge,contact,ray1,ray2,angle))
    if not candidates:raise ModelError('Click a corner where two sketch curves meet.')
    outlines=_closed_outlines(entities);closed={index for index,_ in outlines}
    near=tolerance*.5
    def preference(c):
        # Where two CLOSED shapes cross, the wedges inside either shape are never part of the
        # combined outline, and a click on (or right next to) the vertex cannot tell the wedges
        # apart by its offset: prefer the true outline corners then. Curves that are not closed
        # shapes (a line through a circle, say) keep every wedge valid and the click's side decides.
        both_closed=c[3]['record'][0] in closed and c[4]['record'][0] in closed
        if both_closed and c[0]<=near:return (0,_inner_rays(c[3],c[4],outlines),c[0],c[1])
        return (1,c[0],c[1],0)
    _,_,vertex,ray1,ray2,angle=min(candidates,key=preference)
    if info is not None:info['vertex']=[float(vertex[0]),float(vertex[1])]
    first,second=ray1['record'],ray2['record']
    if entities[first[0]].get('construction',False)!=entities[second[0]].get('construction',False):
        raise ModelError('Construction curves cannot be joined to regular sketch curves.')
    if kind=='chamfer':
        if size>=min(ray1['length'],ray2['length'])-EPS:raise ModelError('Chamfer distance is too large for the adjacent sketch edges.')
        a,_=_point_tangent(ray1['p'],0,size);b,_=_point_tangent(ray2['p'],0,size)
        connector=entity('line',a=a.tolist(),b=b.tolist())
    else:
        initial=np.array([size/math.tan(angle/2)]*2)
        rayrecords=[(first[0],first[1],ray1['p'],ray1['length']),(second[0],second[1],ray2['p'],ray2['length'])]
        if np.any(initial>=np.array([ray1['length'],ray2['length']])*.9):raise ModelError('Fillet radius is too large for the adjacent sketch edges.')
        a,b,connector=_fillet_points(rayrecords[0],0,rayrecords[1],0,size,initial,vertex)
    if entities[first[0]].get('construction'):connector['construction']=True
    ranges={}
    for ray,endpoint in ((ray1,a),(ray2,b)):
        record=ray['record'];lo,hi=ranges.get((record[0],record[1]),(0.,1.))
        along=_path_parameter(ray['p'],endpoint) if ray['p']['kind']=='path' else parameter(ray['p'],endpoint)
        span=(1.-ray['t']) if ray['direction']>0 else ray['t']
        cut=ray['t']+ray['direction']*along*span
        if EPS<ray['t']<1.-EPS:
            ranges[(record[0],record[1])]=[(0.,ray['t']),(cut,1.)] if ray['direction']>0 else [(0.,cut),(ray['t'],1.)]
        else:
            if ray['direction']>0:lo=cut
            else:hi=cut
            ranges[(record[0],record[1])]=(lo,hi)
    affected={first[0],second[0]};result=[]
    for index,e in enumerate(entities):
        if index not in affected:result.append(copy.deepcopy(e));continue
        pieces=[]
        for source,part,p,length in records:
            if source!=index:continue
            intervals=ranges.get((index,part),[(0.,1.)])
            if isinstance(intervals,tuple):intervals=[intervals]
            for lo,hi in intervals:
                if hi-lo<EPS:continue
                fragments=_fragment(p,lo,hi)
                for piece in fragments:
                    if e.get('construction'):piece['construction']=True
                    if not pieces:piece['id']=e['id']
                    pieces.append(piece)
        result.extend(pieces)
    result.append(connector);return result
