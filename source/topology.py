"""Persistent provenance for bodies, independent of their geometric position.

Identity is attached to each immutable rebuild result, never stored in a global
shape cache. Uncertain topology changes receive new identities and require repair.
"""
import hashlib
import numpy as np
from legacy_model import ModelError


def entries(result):
    return getattr(result,'_slothcad_bodies',[]) if result is not None else []


def identity(result,body):
    return next((item['id'] for item in entries(result) if item['shape'].isSame(body)),None)


def by_identity(result,body_id):
    matches=[item['shape'] for item in entries(result) if item['id']==body_id]
    if len(matches)!=1:return None
    return matches[0]


def orientation_key(parent,rotation):
    def normalized(value):
        if isinstance(value,(list,tuple,np.ndarray)):return tuple(normalized(item) for item in value)
        if isinstance(value,(int,float,np.number)):return round(float(value),9)
        return value
    return hashlib.sha256((parent+repr(normalized(rotation))).encode()).hexdigest()[:24] if rotation else parent

def register(previous,current,feature,context=None):
    if current is None:return
    bodies=list(current.val().Solids())
    old=entries(previous);assigned={};used=set()
    for j,body in enumerate(bodies):
        exact=[i for i,item in enumerate(old) if i not in used and item['shape'].isSame(body)]
        if len(exact)==1:
            i=exact[0];assigned[j]=old[i]['id'];used.add(i)
    # One changed body can be identified without a proximity guess. This covers
    # ordinary cuts, fillets, dimensions and single-body direct transforms.
    remaining=[i for i in range(len(old)) if i not in used]
    pending=[j for j in range(len(bodies)) if j not in assigned]
    if len(remaining)==len(pending)==1:
        assigned[pending[0]]=old[remaining[0]]['id']
    elif feature.get('kind') in ('body_move','body_mirror','scale','press_pull','offset_face','replace_face','split_face','feature_rectangular','feature_circular','feature_mirror','path_pattern','primitive','pipe','coil','rib','web','thread') and len(bodies)==len(old):
        # These tools replace selected bodies in place by explicit construction.
        for j in pending:
            if j in remaining:assigned[j]=old[j]['id']
    # Boolean cleanup can recreate unchanged TopoDS objects. Preserve identity
    # only when the full geometric signature matches uniquely.
    # Signatures (volume, area, face and edge counts) are expensive on large bodies, so they are
    # computed on demand and once per body: unchanged bodies are matched by identity above and
    # never need one.
    memo={}
    def signature(body):
        key=id(body)
        if key not in memo:
            b=body.BoundingBox()
            memo[key]=tuple(round(float(v),7) for v in (b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax,body.Volume(),body.Area()))+(len(body.Faces()),len(body.Edges()))
        return memo[key]
    for j,body in enumerate(bodies):
        if j in assigned:continue
        matches=[i for i,item in enumerate(old) if i not in used and signature(item['shape'])==signature(body)]
        if len(matches)==1:
            i=matches[0];assigned[j]=old[i]['id'];used.add(i)
    token=feature.get('id') or hashlib.sha256((feature.get('kind','')+':'+feature.get('name','')).encode()).hexdigest()[:24]
    new_ids={j:f'{token}:body:{k}' for k,j in enumerate(j for j in range(len(bodies)) if j not in assigned)}
    if feature.get('kind')=='body_rectangular':
        from references import resolve_body
        parents=[identity(previous,resolve_body(previous,ref)[1]) for ref in feature.get('targets',[])]
        keys=[f'{token}:rect:{parent}:{r}:{c}' for r in range(feature.get('rows',1))
              for c in range(feature.get('columns',2)) if r or c for parent in parents]
        pending=sorted(new_ids)
        if len(keys)==len(pending) and all(parents):new_ids=dict(zip(pending,keys))
    previous_records={item['id']:item for item in old};transforms={};copy_parents={};rotation=None
    if feature.get('kind') in ('body_move','body_mirror') and previous is not None:
        from references import resolve_body
        from solid_tools import axis_reference,plane_reference
        from geometry import axes
        sketches,frames=context or ({},{})
        picked=[identity(previous,resolve_body(previous,ref)[1]) for ref in feature.get('targets',[])]
        if feature['kind']=='body_move':
            angle=float(feature.get('angle',0))%360
            direction=axis_reference(feature.get('axis',dict(type='origin',axis='Z')),previous,sketches,frames)[1] if angle else None
            rotation=('rotate',round(angle,9),tuple(round(float(x),9) for x in direction)) if angle else None
            copying=feature.get('copy',False)
        else:
            normal=axes(plane_reference(feature.get('plane'),previous,frames))[3];rotation=('mirror',tuple(round(float(x),9) for x in normal));copying=feature.get('keep_original',True)
        if copying:copy_parents=dict(zip(sorted(new_ids),picked))
        else:transforms={key:rotation for key in picked}
    current._slothcad_bodies=[]
    for j,body in enumerate(bodies):
        id_=assigned[j] if j in assigned else new_ids[j];record=previous_records.get(id_)
        unchanged=record is not None and (record['shape'].isSame(body) or signature(record['shape'])==signature(body))
        producer=record.get('producer') if unchanged else feature.get('id')
        parent_record=previous_records.get(copy_parents.get(j)) if j in copy_parents else record
        orientation=(parent_record or {}).get('orientation','')
        if j in copy_parents or id_ in transforms:orientation=orientation_key(orientation,rotation)
        current._slothcad_bodies.append(dict(id=id_,shape=body,producer=producer,orientation=orientation))
    ids=[item['id'] for item in current._slothcad_bodies]
    if len(ids)!=len(set(ids)):raise ModelError('Body identity collision. Repair the feature history.')


def role(shape,kind,body):
    """Scale-independent role; only used as an exact, unique topology match."""
    from references import _cached
    return _cached(f'role-{kind}-{body.hashCode()}',shape,lambda s:_role(s,kind,body))


def _role(shape,kind,body):
    from references import bounds
    low,high=bounds(body);span=np.maximum(high-low,1e-9);a,b=bounds(shape)
    values=[shape.geomType(),kind]
    values.extend(round(float(v),7) for v in np.r_[((a-low)/span),((b-low)/span)])
    if kind=='face':values.extend(round(float(v),7) for v in shape.normalAt().toTuple())
    return hashlib.sha256(repr(values).encode()).hexdigest()[:24]
