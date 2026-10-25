"""Associative sketch projection with exact rational curve control points."""
import copy
import numpy as np
import cadquery as cq
from OCP.Geom import Geom_TrimmedCurve
from OCP.GeomConvert import GeomConvert
from geometry import axes,wire_for,validate_entity,identifier
from references import match_shape
from legacy_model import ModelError


def project_edge(edge,frame,mode='project'):
    if mode not in ('project','include'):raise ModelError('Choose Project or Include geometry.')
    o,u,v,n=axes(frame);adaptor=edge._geomAdaptor()
    trimmed=Geom_TrimmedCurve(adaptor.Curve().Curve(),adaptor.FirstParameter(),adaptor.LastParameter())
    spline=GeomConvert.CurveToBSplineCurve_s(trimmed);spline.SetNotPeriodic()
    points=np.array([spline.Pole(i).Coord() for i in range(1,spline.NbPoles()+1)])
    if mode=='include' and np.max(np.abs((points-o)@n))>1e-6:
        raise ModelError('Include geometry must lie in this sketch plane. Use Project, or include it in a 3D sketch.')
    points2=np.column_stack(((points-o)@u,(points-o)@v))
    if np.max(np.linalg.norm(points2-points2[0],axis=1))<1e-8:
        return dict(kind='point',p=points2[0].tolist())
    if edge.geomType()=='LINE':return dict(kind='line',a=points2[0].tolist(),b=points2[-1].tolist())
    if edge.geomType() in ('CIRCLE','ELLIPSE') and edge.IsClosed():
        conic=adaptor.Circle() if edge.geomType()=='CIRCLE' else adaptor.Ellipse()
        c=np.asarray(conic.Location().Coord())-o;center=[float(c@u),float(c@v)]
        a=conic.Radius() if edge.geomType()=='CIRCLE' else conic.MajorRadius()
        b=conic.Radius() if edge.geomType()=='CIRCLE' else conic.MinorRadius()
        x=np.asarray(conic.XAxis().Direction().Coord())*a;y=np.asarray(conic.YAxis().Direction().Coord())*b
        matrix=np.array([[x@u,y@u],[x@v,y@v]]);directions,radii,_=np.linalg.svd(matrix)
        if radii[1]>1e-8:
            if abs(radii[0]-radii[1])<1e-8:return dict(kind='circle',center=center,radius=float(radii[0]))
            return dict(kind='ellipse',center=center,major=(np.asarray(center)+directions[:,0]*radii[0]).tolist(),minor_radius=float(radii[1]))
    knots=[float(spline.Knot(i)) for i in range(1,spline.NbKnots()+1) for _ in range(spline.Multiplicity(i))]
    return dict(kind='spline',basis='bspline',degree=spline.Degree(),points=points2.tolist(),
                knots=knots,weights=[spline.Weight(i) for i in range(1,spline.NbPoles()+1)],closed=bool(edge.IsClosed()))


def source_edges(reference,result,sketches,frames):
    if not isinstance(reference,dict):raise ModelError('Choose model edges or sketch entities to project.')
    if reference.get('type')=='edge':
        ref=reference['edge']
        shape=__import__('references').surface_shape(ref,'edge',frames)[0] if ref.get('surface_id') else match_shape(result,ref,'edge')[0]
        return [('edge',shape)]
    if reference.get('type')=='sketch':
        id_=reference.get('sketch');s=sketches.get(id_)
        if s is None:raise ModelError('The projection source sketch is missing or later in history. Repair its source.')
        lookup={e['id']:e for e in s['entities']};output=[]
        for entity_id in reference.get('entities',[]):
            e=lookup.get(entity_id)
            if e is None:raise ModelError('A projected sketch entity was removed. Repair its source.')
            if frames[id_].get('spatial'):
                output.append((entity_id,frames[id_]['edges'][entity_id]));continue
            # Construction sources are usable references even though wire_for
            # intentionally excludes them from extrusion profiles.
            temporary=copy.deepcopy(s);temporary['entities']=[dict(item,construction=False) for item in s['entities']]
            if e['kind']=='point':
                o,u,v,n=axes(frames[id_]);p=np.asarray(e['p']);output.append((entity_id,cq.Vertex.makeVertex(*(o+p[0]*u+p[1]*v))));continue
            from solid_tools import path_wire
            if e['kind'] in ('line','arc','spline','conic'):
                wire=path_wire(dict(sketch=id_,entities=[entity_id]),{id_:temporary},frames)
            else:wire=wire_for(temporary,[entity_id],frames[id_])
            output.extend((entity_id+':'+str(i),edge) for i,edge in enumerate(wire.Edges()))
        if not output:raise ModelError('Choose at least one source sketch entity.')
        return output
    raise ModelError('Unsupported projection source.')


def resolve(sketch,result,sketches,frames,frame):
    links=sketch.get('projections',[])
    if not links:return copy.deepcopy(sketch)
    if not isinstance(links,list) or len(links)>1000:raise ModelError('Invalid sketch projection list.')
    output=copy.deepcopy(sketch);entities=[e for e in output['entities'] if not e.get('projection')]
    constraints=[c for c in output.get('constraints',[]) if not c.get('projection_lock')]
    seen=set()
    for link in links:
        key=link.get('id')
        if not isinstance(key,str) or not key or key in seen:raise ModelError('Invalid or duplicate projection ID.')
        seen.add(key)
        if not link.get('enabled',True):continue
        for source_id,edge in source_edges(link.get('source'),result,sketches,frames):
            if isinstance(edge,cq.Vertex):
                o,u,v,n=axes(frame);delta=np.array(edge.Center().toTuple())-o
                if link.get('mode')=='include' and abs(float(delta@n))>1e-6:raise ModelError('Included point is outside the sketch plane.')
                ent=dict(kind='point',p=[float(delta@u),float(delta@v)])
            else:ent=project_edge(edge,frame,link.get('mode','project'))
            ent.update(id=key+':'+source_id,projection=key,construction=link.get('construction',False));validate_entity(ent)
            entities.append(ent)
            from constraints import Layout,fixed_values
            layout=Layout([ent]);ref=dict(kind='entity',entity=ent['id'])
            constraints.append(dict(id=ent['id']+':lock',kind='fix',refs=[ref],fixed=fixed_values(layout,ref,layout.x).tolist(),projection_lock=True))
    if len({e['id'] for e in entities})!=len(entities):raise ModelError('Projected geometry has duplicate entity IDs.')
    output['entities']=entities;output['constraints']=constraints;return output


def break_link(sketch,projection_id):
    result=copy.deepcopy(sketch)
    if not any(link['id']==projection_id for link in result.get('projections',[])):raise ModelError('Select linked geometry first.')
    result['projections']=[link for link in result['projections'] if link['id']!=projection_id]
    affected={e['id'] for e in result['entities'] if e.get('projection')==projection_id}
    for e in result['entities']:
        if e.get('projection')==projection_id:e.pop('projection')
    result['constraints']=[c for c in result.get('constraints',[]) if not(c.get('projection_lock') and c['refs'][0]['entity'] in affected)]
    return result
