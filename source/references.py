"""Geometric references with body-relative anchors and conservative recovery."""
import math
import numpy as np
import cadquery as cq
from legacy_model import ModelError

class ReferenceError(ModelError):pass

def solids(result):
    if result is None:return []
    shape=result.val() if hasattr(result,'val') else result
    return list(shape.Solids())

# Measurements of kernel shapes are remembered by the shape's identity (its hash, then an exact
# comparison): the wrappers are recreated on every Faces()/Edges() call, so a cache kept on a
# wrapper would never be hit. Shapes are immutable, so an entry stays right for as long as the
# shape lives; the table is bounded.
import collections as _collections
import threading as _threading
_SHAPE_CACHE=_collections.OrderedDict();_SHAPE_CACHE_LOCK=_threading.Lock();_SHAPE_CACHE_LIMIT=40000

def _cached(kind,shape,compute):
    try:key=(kind,shape.hashCode())
    except Exception:return compute(shape)
    with _SHAPE_CACHE_LOCK:
        entry=_SHAPE_CACHE.get(key)
        if entry is not None:
            for owner,value in entry:
                if owner is shape or owner.isSame(shape):
                    _SHAPE_CACHE.move_to_end(key);return value
    value=compute(shape)
    with _SHAPE_CACHE_LOCK:
        _SHAPE_CACHE.setdefault(key,[]).append((shape,value));_SHAPE_CACHE.move_to_end(key)
        while len(_SHAPE_CACHE)>_SHAPE_CACHE_LIMIT:_SHAPE_CACHE.popitem(last=False)
    return value

def bounds(shape):
    low,high=_cached('bounds',shape,lambda s:(lambda b:(np.array([b.xmin,b.ymin,b.zmin]),np.array([b.xmax,b.ymax,b.zmax])))(s.BoundingBox()))
    return low.copy(),high.copy()

def body_reference(body,index=None,count=None,result=None):
    low,high=bounds(body)
    centre,volume=_cached('mass',body,lambda s:(list(s.Center().toTuple()),float(s.Volume())))     # two whole-body integrals
    ref=dict(center=list(centre),size=(high-low).tolist(),volume=volume,faces=sum(len(v) for v in _members(body,'face').values()),edges=sum(len(v) for v in _members(body,'edge').values()))
    from topology import identity
    body_id=identity(result,body)
    if body_id:
        ref['body_id']=body_id
        from topology import entries
        record=next((item for item in entries(result) if item['id']==body_id),{})
        ref['orientation']=record.get('orientation','')
        if record.get('producer'):ref['producer']=record['producer']
    if index is not None:ref['index']=int(index)
    if count is not None:ref['count']=int(count)
    return ref

def resolve_body(result,reference):
    bodies=solids(result)
    if not bodies:raise ReferenceError('The referenced body no longer exists.')
    if not isinstance(reference,dict):raise ReferenceError('Select a target body.')
    if reference.get('body_id'):
        from topology import by_identity
        selected=by_identity(result,reference['body_id'])
        if selected is None:raise ReferenceError('The referenced body identity is missing. Repair its reference; another body will not be substituted.')
        return next((i,b) for i,b in enumerate(bodies) if b.isSame(selected))
    try:
        vector=np.asarray(reference.get('center'),float);size_vector=np.asarray(reference.get('size'),float)
        if vector.shape!=(3,) or size_vector.shape!=(3,) or not np.isfinite(vector).all() or not np.isfinite(size_vector).all() or np.any(size_vector<=0):raise ValueError()
    except (ValueError,TypeError):raise ReferenceError('Invalid saved body reference. Repair its reference.')
    c=np.asarray(reference['center'],float);size=np.asarray(reference['size'],float);scale=max(1.,float(np.linalg.norm(size)))
    ranked=[]
    for i,body in enumerate(bodies):
        r=body_reference(body);distance=float(np.linalg.norm(np.asarray(r['center'])-c))/scale
        size_error=float(np.linalg.norm(np.asarray(r['size'])-size))/scale
        topology=abs(r['faces']-reference.get('faces',r['faces']))+abs(r['edges']-reference.get('edges',r['edges']))
        score=distance+size_error*.25+min(topology,10)*.04
        ranked.append((score,i,body))
    ranked.sort(key=lambda x:x[0]);best=ranked[0]
    if best[0]>.85:raise ReferenceError('The target body changed too much. Repair its body reference.')
    if len(ranked)>1 and ranked[1][0]-best[0]<.04:
        hint=reference.get('index')
        # An explicit slot distinguishes intentional coincident copies while the
        # unchanged body count and exact geometry verify that original slot.
        exact=[r for r in ranked if r[0]<1e-7]
        if len(bodies)==reference.get('count') and any(r[1]==hint for r in exact):return hint,bodies[hint]
        raise ReferenceError('Body reference is ambiguous. Select the intended body in Repair references.')
    return best[1],best[2]

def _members(body,kind):
    """{hash: [faces or edges]} of a body, built once per body (creating the wrappers is the cost)."""
    def build(shape):
        table={}
        for item in (shape.Faces() if kind=='face' else shape.Edges()):table.setdefault(item.hashCode(),[]).append(item)
        return table
    return _cached('members-'+kind,body,build)

def _owner(shape,result,kind):
    bodies=solids(result)
    key=shape.hashCode()
    for i,body in enumerate(bodies):
        if any(shape.isSame(v) for v in _members(body,kind).get(key,())):return i,body,len(bodies)
    return None

def shape_reference(shape,kind,result=None):
    ref=dict(center=list(shape.Center().toTuple()),geometry=shape.geomType())
    if kind=='face':
        ref['area']=float(shape.Area());ref['normal']=list(shape.normalAt().toTuple());ref['edges']=len(shape.Edges())
    else:
        ref['length']=float(shape.Length());ref['endpoints']=[list(v.Center().toTuple()) for v in shape.Vertices()]
        try:ref['direction']=list(shape.tangentAt(.5).toTuple())
        except Exception:pass
    owner=_owner(shape,result,kind) if result is not None else None
    if owner:
        i,body,count=owner;low,high=bounds(body);span=np.maximum(high-low,1e-9);a,b=bounds(shape)
        ref['anchor']=dict(body=body_reference(body,i,count,result),center=((np.asarray(ref['center'])-low)/span).tolist(),low=((a-low)/span).tolist(),high=((b-low)/span).tolist())
        from topology import role
        ref['topology_role']=role(shape,kind,body)
        if kind=='edge':ref['anchor']['endpoints']=[((np.asarray(v)-low)/span).tolist() for v in ref['endpoints']]
    return ref

def match_shape(result,reference,kind,available=None):
    if result is None:raise ReferenceError('The supporting body no longer exists.')
    if not isinstance(reference,dict) or not isinstance(reference.get('center'),list):raise ReferenceError('Invalid saved '+kind+' reference.')
    if kind not in ('face','edge'):raise ReferenceError('Unknown reference type.')
    try:
        center_check=np.asarray(reference['center'],float);measure_check=float(reference['area' if kind=='face' else 'length'])
        if center_check.shape!=(3,) or not np.isfinite(center_check).all() or not math.isfinite(measure_check) or measure_check<=0:raise ValueError()
    except (ValueError,KeyError,TypeError):raise ReferenceError('Invalid saved '+kind+' reference. Repair its reference.')
    bodies=solids(result);owner=None;anchor=reference.get('anchor')
    if anchor:
        index,owner=resolve_body(result,anchor['body']);values=owner.Faces() if kind=='face' else owner.Edges()
        if 'orientation' in anchor['body'] and body_reference(owner,result=result).get('orientation','')!=anchor['body']['orientation']:
            raise ReferenceError('The body orientation changed. Reselect this face or edge in Repair to preserve its meaning.')
    else:
        shape=result.val() if hasattr(result,'val') else result;values=shape.Faces() if kind=='face' else shape.Edges()
    if available is not None:
        # Hash buckets, then the exact test: the list is usually every edge of the body, and
        # comparing each value with each entry made resolving a pick quadratic in the face count.
        buckets={}
        for entry in available:buckets.setdefault(entry.hashCode(),[]).append(entry)
        values=[v for v in values if any(v.isSame(a) for a in buckets.get(v.hashCode(),()))]
    geometry=reference.get('geometry','PLANE' if kind=='face' else None)
    if geometry:values=[v for v in values if v.geomType()==geometry]
    if not values:raise ReferenceError('The referenced '+kind+' no longer exists. Repair its reference.')
    if owner is not None and reference.get('topology_role'):
        from topology import role
        matches=[v for v in values if role(v,kind,owner)==reference['topology_role']]
        if len(matches)==1:
            descriptor=shape_reference(matches[0],kind)
            same=np.linalg.norm(np.asarray(descriptor['center'])-reference['center'])<1e-6 and abs(descriptor['area' if kind=='face' else 'length']-measure_check)<1e-6
            return matches[0],'matched' if same else 'recovered'
    center=np.asarray(reference['center'],float);key='area' if kind=='face' else 'length';measure=float(reference[key]);normal=np.asarray(reference.get('normal',[]),float)
    candidates=[]
    for value in values:
        descriptor=_cached('descriptor-'+kind,value,lambda v:shape_reference(v,kind))
        if kind=='face' and len(normal)==3:
            dot=float(np.asarray(descriptor['normal'])@normal)
            if dot<.97:continue
        if kind=='edge' and 'direction' in reference and 'direction' in descriptor:
            if abs(float(np.asarray(descriptor['direction'])@reference['direction']))<.97:continue
        exact=float(np.linalg.norm(np.asarray(descriptor['center'])-center))+abs(descriptor[key]-measure)/max(1.,math.sqrt(measure) if kind=='face' else measure)
        if anchor:
            low,high=bounds(owner);span=np.maximum(high-low,1e-9);a,b=bounds(value)
            p=(np.asarray(descriptor['center'])-low)/span
            score=float(np.linalg.norm(p-anchor['center']))*3+float(np.linalg.norm((a-low)/span-anchor['low'])+np.linalg.norm((b-low)/span-anchor['high']))*.35
            if kind=='face':score+=abs(descriptor.get('edges',0)-reference.get('edges',descriptor.get('edges',0)))*.03
        else:
            scale=max(1.,math.sqrt(measure) if kind=='face' else measure);score=exact/scale
        candidates.append((score,exact,value))
    candidates.sort(key=lambda x:(x[0],x[1]))
    if not candidates:raise ReferenceError('The referenced '+kind+' changed orientation or disappeared. Repair its reference.')
    best=candidates[0];limit=.45 if anchor else .7
    if len(candidates)>1:
        second=candidates[1]
        if second[0]-best[0]<.04 and not (best[1]<1e-6 and second[1]>1e-4):raise ReferenceError(kind.title()+' reference is ambiguous. Repair references instead of choosing by proximity.')
    if best[0]>limit:raise ReferenceError('The referenced '+kind+' changed too much. Repair its reference.')
    return best[2],('matched' if best[1]<1e-5 else 'recovered')

def reference_slots(feature):
    """Return serializable dict/list paths for every stored face/edge/body pick."""
    result=[]
    def visit(value,path):
        if isinstance(value,dict):
            if 'center' in value and 'area' in value:result.append((path,'face'));return
            if 'center' in value and 'length' in value:result.append((path,'edge'));return
            if 'center' in value and 'volume' in value and 'size' in value:result.append((path,'body'));return
            for key,item in value.items():
                if key!='anchor' and not (value.get('kind')=='component' and key=='features'):visit(item,path+[key])
        elif isinstance(value,list):
            for i,item in enumerate(value):visit(item,path+[i])
    visit(feature,[]);return result

def value_at(feature,path):
    value=feature
    for key in path:value=value[key]
    return value

def replace_at(feature,path,value):
    parent=feature
    for key in path[:-1]:parent=parent[key]
    parent[path[-1]]=value

def inspect_slots(feature,result,frames=None):
    report=[]
    for path,kind in reference_slots(feature):
        ref=value_at(feature,path)
        try:
            if kind=='body':index,shape=resolve_body(result,ref);state='matched' if np.linalg.norm(np.asarray(shape.Center().toTuple())-ref['center'])<1e-5 else 'recovered'
            elif ref.get('surface_id'):shape,state=surface_shape(ref,kind,frames or {})
            else:shape,state=match_shape(result,ref,kind)
            report.append(dict(path=path,kind=kind,state=state,message=''))
        except ModelError as error:report.append(dict(path=path,kind=kind,state='needs repair',message=str(error)))
    return report

def enrich_feature(feature,result):
    for path,kind in reference_slots(feature):
        ref=value_at(feature,path)
        if kind!='body' and not ref.get('anchor') and not ref.get('surface_id'):
            try:shape,state=match_shape(result,ref,kind);replace_at(feature,path,shape_reference(shape,kind,result))
            except ModelError:pass

def surface_reference(shape,kind,id_,frames):
    body=frames.get('_surfaces',{}).get(id_)
    if body is None:raise ModelError('The source surface is missing.')
    import cadquery as cq
    from topology import role
    local=cq.Workplane('XY').newObject([body['shape']])
    return dict(shape_reference(shape,kind,local),surface_id=id_,surface_role=role(shape,kind,body['shape']))

def surface_shape(ref,kind,frames):
    body=frames.get('_surfaces',{}).get(ref.get('surface_id'))
    if body is None:raise ModelError('The source surface is missing or suppressed. Repair its reference.')
    from topology import role
    candidates=body['shape'].Faces() if kind=='face' else body['shape'].Edges()
    matches=[shape for shape in candidates if ref.get('surface_role')==role(shape,kind,body['shape'])]
    if len(matches)==1:return matches[0],'recovered'
    import cadquery as cq
    return match_shape(cq.Workplane('XY').newObject([body['shape']]),ref,kind)
