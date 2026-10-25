"""Live dimensions and exact cursor constraints for sketch drawing."""
import math
import numpy as np

def values(tool,points,cursor):
    if not points or cursor is None:return []
    a=np.asarray(points[0]);d=np.asarray(cursor)-a
    if tool=='rectangle':return [('Width',abs(d[0]),'mm'),('Height',abs(d[1]),'mm')]
    if tool=='center_rectangle':return [('Width',2*abs(d[0]),'mm'),('Height',2*abs(d[1]),'mm')]
    if tool in ('circle','polygon'):return [('Radius',np.linalg.norm(d),'mm')]
    if tool=='ellipse' and len(points)==1:return [('Major radius',np.linalg.norm(d),'mm')]
    if tool=='ellipse' and len(points)==2:
        c=np.asarray(points[0]);major=np.asarray(points[1])-c;length=np.linalg.norm(major)
        if length<=1e-12:return []
        n=np.array([-major[1],major[0]])/length
        return [('Minor radius',abs(float((np.asarray(cursor)-c)@n)),'mm')]
    if tool=='slot' and len(points)==1:return [('Center length',np.linalg.norm(d),'mm'),('Angle',math.degrees(math.atan2(d[1],d[0])),'°')]
    if tool=='slot' and len(points)==2:
        a,b=map(np.asarray,points[:2]);axis=b-a;length=np.linalg.norm(axis)
        if length<=1e-12:return []
        n=np.array([-axis[1],axis[0]])/length
        return [('Width',2*abs(float((np.asarray(cursor)-a)@n)),'mm')]
    if tool=='line' or tool=='arc' and len(points)==1:return [('Length',np.linalg.norm(d),'mm'),('Angle',math.degrees(math.atan2(d[1],d[0])),'°')]
    if tool=='arc' and len(points)==2:
        b=np.asarray(points[1]);chord=b-a;length=np.linalg.norm(chord)
        if length<=1e-12:return []
        n=np.array([-chord[1],chord[0]])/length
        return [('Bend',float((np.asarray(cursor)-(a+b)/2)@n),'mm')]
    return []

def constrain(tool,points,cursor,locks):
    if not points or cursor is None:return cursor
    a=np.asarray(points[0]);p=np.asarray(cursor,dtype=float).copy();d=p-a
    if tool=='rectangle':
        for i in range(2):
            if i in locks:p[i]=a[i]+(1 if d[i]>=0 else -1)*locks[i]
    elif tool=='center_rectangle':
        for i in range(2):
            if i in locks:p[i]=a[i]+(1 if d[i]>=0 else -1)*locks[i]/2
    elif tool in ('circle','polygon') or tool=='line' or tool=='arc' and len(points)==1 or tool=='slot' and len(points)==1 or tool=='ellipse' and len(points)==1:
        length=locks.get(0,np.linalg.norm(d));angle=math.radians(locks[1]) if 1 in locks else math.atan2(d[1],d[0]);p=a+length*np.array([math.cos(angle),math.sin(angle)])
    elif tool=='ellipse' and len(points)==2 and 0 in locks:
        c=np.asarray(points[0]);major=np.asarray(points[1])-c;length=np.linalg.norm(major)
        if length>1e-12:
            n=np.array([-major[1],major[0]])/length;sign=1 if (np.asarray(cursor)-c)@n>=0 else -1;p=c+n*locks[0]*sign
    elif tool=='slot' and len(points)==2 and 0 in locks:
        first,second=map(np.asarray,points[:2]);axis=second-first;length=np.linalg.norm(axis)
        if length>1e-12:
            n=np.array([-axis[1],axis[0]])/length;sign=1 if (np.asarray(cursor)-first)@n>=0 else -1;p=first+n*(locks[0]/2)*sign
    elif tool=='arc' and len(points)==2 and 0 in locks:
        b=np.asarray(points[1]);v=b-a;length=np.linalg.norm(v)
        if length<=1e-12:return p
        n=np.array([-v[1],v[0]])/length;p=(a+b)/2+n*locks[0]
    return p
