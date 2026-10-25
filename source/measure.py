"""Read-only geometry measurements with exact closest-point witnesses."""
import numpy as np
import math
import cadquery as cq
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from geometry import world,axes,sample,wire_for
from legacy_model import ModelError


def selection_shape(selection):
    if 'shape' in selection:return selection['shape']
    if selection['kind']=='point':return cq.Vertex.makeVertex(*selection['point'])
    frame=selection['frame']
    if selection['kind']=='face':
        sketch=selection['sketch'];profile=selection['profile']
        return cq.Face.makeFromWires(wire_for(sketch,profile['entities'],frame),[wire_for(sketch,ids,frame) for ids in profile['holes']])
    e=selection['entity'];kind=e['kind']
    def w(point):return tuple(world(frame,point))
    if 'segment' in selection:
        points=sample(e);i=selection['segment'];return cq.Edge.makeLine(w(points[i]),w(points[i+1]))
    if kind in ('ellipse','spline','conic'):
        from curves import edge_for
        o,u,v,n=axes(frame);return edge_for(e).transformShape(cq.Plane(tuple(o),tuple(u),tuple(n)).rG)
    if kind=='circle':return cq.Edge.makeCircle(float(e['radius']),w(e['center']),tuple(axes(frame)[3]))
    if kind=='arc':return cq.Edge.makeThreePointArc(w(e['a']),w(e['mid']),w(e['b']))
    if kind=='slot':
        from geometry import slot_parts
        return cq.Wire.assembleEdges([cq.Edge.makeLine(*map(w,p)) if part=='line' else cq.Edge.makeThreePointArc(*map(w,p)) for part,p in slot_parts(e)])
    points=sample(e)
    edges=[cq.Edge.makeLine(w(a),w(b)) for a,b in zip(points[:-1],points[1:])]
    if not edges:raise ModelError('This item has no measurable boundary.')
    return edges[0] if len(edges)==1 else cq.Wire.assembleEdges(edges)


def calculate_measurement(selections):
    if not 1<=len(selections)<=2:raise ModelError('Select one or two measurement objects.')
    shapes=[selection_shape(selection) for selection in selections];properties=[]
    for selection,shape in zip(selections,shapes):
        info={'label':selection['label'],'kind':selection['kind']}
        if selection['kind']=='edge':
            info['length']=float(sum(edge.Length() for edge in shape.Edges()))
            if len(shape.Edges())==1 and shape.Edges()[0].geomType()=='CIRCLE':info['radius']=float(shape.Edges()[0].radius())
        elif selection['kind']=='face':info['area']=float(shape.Area())
        else:info['point']=list(shape.Center().toTuple())
        properties.append(info)
    result={'properties':properties}
    if len(shapes)==2:
        distance=BRepExtrema_DistShapeShape(shapes[0].wrapped,shapes[1].wrapped)
        if not distance.IsDone():distance.Perform()
        if not distance.IsDone() or distance.NbSolution()<1:raise ModelError('Could not measure this geometry pair.')
        a=distance.PointOnShape1(1).Coord();b=distance.PointOnShape2(1).Coord()
        result.update(distance=float(distance.Value()),points=[list(a),list(b)],delta=(np.asarray(b)-np.asarray(a)).tolist())
        vectors=[]
        for selection,shape in zip(selections,shapes):
            if selection['kind']=='face' and shape.geomType()=='PLANE':vectors.append(('face',np.array(shape.normalAt().toTuple())))
            elif selection['kind']=='edge' and len(shape.Edges())==1 and shape.Edges()[0].geomType()=='LINE':vectors.append(('edge',np.array(shape.Edges()[0].tangentAt(.5).toTuple())))
        if len(vectors)==2:
            dot=float(np.clip(abs(vectors[0][1]@vectors[1][1]),0,1))
            result['angle']=math.degrees(math.asin(dot) if vectors[0][0]!=vectors[1][0] else math.acos(dot))
    return result
