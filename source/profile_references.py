"""Stable segment roles for associative planar region selections."""
from geometry import profile_geometry,profile_regions
from legacy_model import ModelError


def roles(sketch):
    groups={};mapping={}
    for e in profile_geometry(sketch):
        id_=e['id']
        if '~' not in id_:mapping[id_]=id_;continue
        parent,interval=id_.rsplit('~',1);part,lo,hi=interval.rsplit(':',2)
        groups.setdefault(parent+'~'+part,[]).append((float(lo),float(hi),id_))
    for parent,values in groups.items():
        for i,(_,_,id_) in enumerate(sorted(values)):mapping[id_]=parent+':segment:'+str(i)
    return mapping


def recover(source,sketch):
    candidates=profile_regions(sketch);mapping=roles(sketch)
    key=lambda r:sorted(mapping[id_] for id_ in r['entities'])
    exact=[r for r in candidates if set(r['entities'])==set(source.get('entities',[]))]
    if len(exact)==1:
        source.setdefault('region_key',key(exact[0]));return exact[0]
    saved=source.get('region_key')
    if saved:
        matches=[r for r in candidates if key(r)==saved]
        if len(matches)==1:
            source['entities']=list(matches[0]['entities'])
            if source.get('profile_mode')=='nested':source['holes']=matches[0]['holes']
            return matches[0]
        raise ModelError('The sketch region changed topology or is ambiguous. Reselect its extrusion profile to repair it.')
    return None
