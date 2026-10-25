"""World-space and exact UV-on-face curves, usable by path/surface features."""
import cadquery as cq
import numpy as np
from legacy_model import ModelError
from geometry import identifier
from references import match_shape

SPATIAL_TOOLS=('sketch3d','surface_sketch')

def points(entity,dimension):
    pts=np.asarray(entity.get('points',[]),float)
    minimum={'point':1,'line':2,'arc':3,'spline':2}.get(entity.get('kind'))
    if minimum is None or pts.ndim!=2 or pts.shape[1]!=dimension or len(pts)<minimum or not np.all(np.isfinite(pts)):raise ModelError('Spatial curves need finite coordinates and enough control points.')
    if entity['kind'] in ('point','line','arc') and len(pts)!=minimum:raise ModelError('Wrong number of points for the curve.')
    if len(pts)>1000:raise ModelError('Use at most 1000 points per curve.')
    if len(pts)>1 and any(np.linalg.norm(b-a)<1e-8 for a,b in zip(pts[:-1],pts[1:])):raise ModelError('Adjacent curve points must be distinct.')
    return pts

def curve3d(e):
    pts=points(e,3);vec=[cq.Vector(*p) for p in pts]
    if e['kind']=='point':return cq.Vertex.makeVertex(*pts[0])
    if e['kind']=='line':return cq.Edge.makeLine(*vec)
    if e['kind']=='arc':return cq.Edge.makeThreePointArc(*vec)
    return cq.Edge.makeSpline(vec,periodic=bool(e.get('closed',False)))

def curve_on_face(e,face):
    from OCP.BRep import BRep_Tool
    from OCP.Geom2d import Geom2d_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt2d
    from OCP.TColStd import TColStd_Array1OfReal,TColStd_Array1OfInteger
    from OCP.gp import gp_Pnt2d
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepLib import BRepLib
    pts=points(e,2);surface=BRep_Tool.Surface_s(face.wrapped)
    if e['kind']=='point':return cq.Vertex.makeVertex(*[surface.Value(*map(float,pts[0])).Coord(i) for i in (1,2,3)])
    if e['kind']=='arc':
        from OCP.GCE2d import GCE2d_MakeArcOfCircle
        curve=GCE2d_MakeArcOfCircle(*[gp_Pnt2d(*map(float,p)) for p in pts]).Value()
    elif e['kind']=='line':
        poles=TColgp_Array1OfPnt2d(1,2)
        for i,p in enumerate(pts,1):poles.SetValue(i,gp_Pnt2d(*map(float,p)))
        knots=TColStd_Array1OfReal(1,2);mult=TColStd_Array1OfInteger(1,2)
        for i,k in enumerate((0.,1.),1):knots.SetValue(i,k);mult.SetValue(i,2)
        curve=Geom2d_BSplineCurve(poles,knots,mult,1)
    else:
        from OCP.Geom2dAPI import Geom2dAPI_Interpolate
        from OCP.TColgp import TColgp_HArray1OfPnt2d
        p=TColgp_HArray1OfPnt2d(1,len(pts))
        for i,value in enumerate(pts,1):p.SetValue(i,gp_Pnt2d(*map(float,value)))
        builder=Geom2dAPI_Interpolate(p,bool(e.get('closed',False)),1e-7);builder.Perform()
        if not builder.IsDone():raise ModelError('The UV spline cannot be interpolated.')
        curve=builder.Curve()
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN,TopAbs_ON
    for t in np.linspace(curve.FirstParameter(),curve.LastParameter(),81):
        classifier=BRepClass_FaceClassifier(face.wrapped,curve.Value(float(t)),1e-6)
        if classifier.State() not in (TopAbs_IN,TopAbs_ON):raise ModelError('The curve leaves the supporting face. Keep its UV coordinates within the face boundary.')
    builder=BRepBuilderAPI_MakeEdge(curve,surface)
    if not builder.IsDone():raise ModelError('The UV curve cannot be built on this face.')
    edge=builder.Edge();BRepLib.BuildCurves3d_s(edge,1e-7);return cq.Shape.cast(edge)

def materialize(f,result,frames=None):
    if not isinstance(f.get('entities'),list):raise ModelError('A spatial sketch needs a geometry list.')
    ids=[e.get('id') for e in f['entities']]
    if any(not id_ for id_ in ids) or len(ids)!=len(set(ids)):raise ModelError('Spatial entities need unique persistent IDs.')
    face=None
    if f['kind']=='surface_sketch':
        ref=f.get('face')
        if isinstance(ref,dict) and ref.get('surface_id'):
            from references import surface_shape
            face=surface_shape(ref,'face',frames or {})[0]
        else:face=match_shape(result,ref,'face')[0]
    edges={}
    for e in f['entities']:
        shape=curve_on_face(e,face) if face is not None else curve3d(e)
        if not shape.isValid():raise ModelError('This curve is invalid. Check coincident points or arc collinearity.')
        if shape.ShapeType()=='Edge' and shape.Length()<1e-7:raise ModelError('The curve length is too small.')
        edges[e['id']]=shape
    return dict(origin=[0,0,0],u=[1,0,0],normal=[0,0,1],spatial=True,edges=edges,face=face)

def wire(ref,sketches,frames):
    sketch=sketches.get(ref.get('sketch'));frame=frames.get(ref.get('sketch'))
    if not sketch or not frame or not frame.get('spatial'):raise ModelError('The spatial path sketch is missing.')
    ids=ref.get('entities',[])
    if not ids:raise ModelError('Select spatial path curves.')
    shapes=[frame['edges'].get(id_) for id_ in ids]
    if any(shape is None or shape.ShapeType()!='Edge' for shape in shapes):raise ModelError('A spatial path curve is missing or is a point.')
    output=cq.Wire.assembleEdges(shapes)
    if not output.isValid() or len(output.Wires())!=1:raise ModelError('The selected spatial curves must form one connected path.')
    return output

def sampled(f,frame):
    result=[]
    for id_,shape in frame['edges'].items():
        if shape.ShapeType()=='Vertex':result.append(np.asarray([shape.Center().toTuple()]))
        else:result.append(np.asarray([shape.positionAt(float(t)).toTuple() for t in np.linspace(0,1,2 if shape.geomType()=='LINE' else 81)]))
    return result
