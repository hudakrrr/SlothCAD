"""Exact sketch curves. Samples are for display; solid profiles keep kernel curves."""
import copy,json,math
from functools import lru_cache
import numpy as np
import cadquery as cq
from OCP.Geom import Geom_BSplineCurve
from OCP.gp import gp_Pnt
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfReal,TColStd_Array1OfInteger
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
from legacy_model import ModelError

KINDS=('ellipse','spline','conic')
def array(cls,values):
 a=cls(1,len(values))
 for i,v in enumerate(values,1):a.SetValue(i,v)
 return a

def bspline(points,degree,knots=None,weights=None):
 points=np.asarray(points,float);n=len(points);degree=int(degree)
 if points.shape!=(n,2) or n<2 or not 1<=degree<min(n,26) or not np.isfinite(points).all():raise ModelError('Invalid spline control points or degree.')
 if knots is None:knots=[0.]*(degree+1)+[i/(n-degree) for i in range(1,n-degree)]+[1.]*(degree+1)
 knots=np.asarray(knots,float)
 if len(knots)!=n+degree+1 or not np.isfinite(knots).all() or np.any(np.diff(knots)<0) or knots[degree]>=knots[n]:raise ModelError('Invalid spline knot vector.')
 unique,mults=np.unique(knots,return_counts=True)
 weights=np.asarray(weights if weights is not None else np.ones(n),float)
 if len(weights)!=n or not np.isfinite(weights).all() or np.any(weights<=0):raise ModelError('Spline weights must be positive and match the control points.')
 curve=Geom_BSplineCurve(array(TColgp_Array1OfPnt,[gp_Pnt(float(x),float(y),0) for x,y in points]),array(TColStd_Array1OfReal,weights.tolist()),array(TColStd_Array1OfReal,unique.tolist()),array(TColStd_Array1OfInteger,mults.tolist()),degree,False)
 return cq.Edge(BRepBuilderAPI_MakeEdge(curve,float(knots[degree]),float(knots[n])).Edge())

def spline_data(e):
 points=copy.deepcopy(e['points']);degree=min(int(e.get('degree',3)),len(points)-1)
 if e.get('knots') is not None:return points,degree,e['knots'],e.get('weights')
 if e.get('closed'):
  weights=copy.deepcopy(e.get('weights'))
  if np.linalg.norm(np.asarray(points[0])-points[-1])<1e-8:points=points[:-1];weights=weights[:-1] if weights else None
  degree=min(degree,len(points)-1);points+=points[:degree]
  # Uniform periodic control polygon represented over its active interval.
  knots=list(range(len(points)+degree+1));return points,degree,knots,(weights+weights[:degree] if weights else None)
 return points,degree,None,e.get('weights')

@lru_cache(maxsize=512)
def _base(key):
 e=json.loads(key);kind=e['kind']
 if kind=='ellipse':
  c=np.asarray(e['center'],float);axis=np.asarray(e['major'],float)-c;rx=float(np.linalg.norm(axis));ry=float(e['minor_radius'])
  if min(rx,ry)<=1e-9:raise ModelError('Ellipse radii must be positive.')
  u=axis/rx
  if ry>rx:u=np.array([-u[1],u[0]]);rx,ry=ry,rx
  return cq.Edge.makeEllipse(rx,ry,(float(c[0]),float(c[1]),0),xdir=(float(u[0]),float(u[1]),0))
 if kind=='conic':return bspline([e['a'],e['control'],e['b']],2,weights=[1,float(e.get('weight',1)),1])
 if kind=='spline' and e.get('basis')=='bspline':return bspline(*spline_data(e))
 # Preserve legacy interpolating Catmull-Rom geometry exactly as cubic segments.
 pts=np.asarray(e['points'],float);closed=e.get('closed',False)
 if len(pts)>2 and np.linalg.norm(pts[0]-pts[-1])<1e-6:pts=pts[:-1];closed=True
 if len(pts)==2:return cq.Edge.makeLine((*pts[0],0),(*pts[1],0))
 ext=np.vstack((pts[-1],pts,pts[0],pts[1])) if closed else np.vstack((pts[0],pts,pts[-1]))
 poles=[]
 for i in range(1,len(ext)-2):
  p0,p1,p2,p3=ext[i-1:i+3];segment=[p1,p1+(p2-p0)/6,p2-(p3-p1)/6,p2]
  poles.extend(segment if not poles else segment[1:])
 count=(len(poles)-1)//3;knots=[0.]*4+[float(i) for i in range(1,count) for _ in range(3)]+[float(count)]*4
 return bspline(poles,3,knots)

def base_edge(e):return _base(json.dumps({k:v for k,v in e.items() if k not in ('id','range','construction')},sort_keys=True))
def limits(edge):
 a=edge._geomAdaptor();return a.FirstParameter(),a.LastParameter()
def edge_for(e):
 edge=base_edge(e);lo,hi=map(float,e.get('range',[0,1]))
 if not 0<=lo<hi<=1:raise ModelError('Invalid trimmed curve interval.')
 if lo==0 and hi==1:return edge
 a,b=limits(edge);return edge.trim(a+(b-a)*lo,a+(b-a)*hi)
def evaluate(e,t):
 edge=base_edge(e);a,b=limits(edge);p=edge._geomAdaptor().Value(a+(b-a)*float(t));return np.array([p.X(),p.Y()])
def sample_curve(e,steps):
 edge=edge_for(e);a,b=limits(edge);curve=edge._geomAdaptor()
 return np.array([[p.X(),p.Y()] for p in (curve.Value(float(t)) for t in np.linspace(a,b,max(2,steps)+1))])
def project(e,point):
 edge=base_edge(e);a,b=limits(edge);lo,hi=e.get('range',[0,1]);p=GeomAPI_ProjectPointOnCurve(gp_Pnt(float(point[0]),float(point[1]),0),edge._geomAdaptor().Curve().Curve(),a+(b-a)*lo,a+(b-a)*hi)
 if not p.NbPoints():raise ModelError('Could not project onto curve.')
 return (p.LowerDistanceParameter()-a)/(b-a)
def closed(e):return 'range' not in e and (e['kind']=='ellipse' or e.get('closed',False))

def nurbs_data(edge):
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomConvert import GeomConvert
    a,b=limits(edge);adaptor=edge._geomAdaptor()
    curve=GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(adaptor.Curve().Curve(),a,b))
    points=[[curve.Pole(i).X(),curve.Pole(i).Y()] for i in range(1,curve.NbPoles()+1)]
    knots=[curve.Knot(i) for i in range(1,curve.NbKnots()+1) for _ in range(curve.Multiplicity(i))]
    weights=[curve.Weight(i) for i in range(1,curve.NbPoles()+1)]
    return dict(basis='bspline',points=points,degree=curve.Degree(),knots=knots,weights=weights,closed=edge.IsClosed())
