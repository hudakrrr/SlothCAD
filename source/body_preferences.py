"""Keep view preferences on surviving bodies when topology changes their order."""
import copy
import numpy as np

def remap(previous, current, display):
    if not any(display.get(key) for key in ('materials', 'bodies', 'body_names')):
        return display
    old = previous.val().Solids() if previous is not None else []
    new = current.val().Solids() if current is not None else []
    def bounds(body):
        b = body.BoundingBox()
        return np.array([b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax])
    before = [bounds(b) for b in old]; after = [bounds(b) for b in new]
    # Index by geometric bounds/volume: unaffected bodies usually retain these
    # exactly even when the entire history has been rebuilt.
    def key(body, box):
        return tuple(round(float(x),6) for x in box) + (round(body.Volume(),6),)
    lookup = {}
    for i,b in enumerate(old): lookup.setdefault(key(b,before[i]),[]).append(i)
    owners = {}; used = set()
    from topology import identity
    identities={identity(previous,b):i for i,b in enumerate(old) if identity(previous,b)}
    for j,b in enumerate(new):
        body_id=identity(current,b)
        if body_id in identities:owners[j]=identities[body_id];used.add(identities[body_id])
    for j,b in enumerate(new):
        if j in owners:continue
        candidates = lookup.get(key(b,after[j]),[])
        candidates = [i for i in candidates if i not in used]
        if candidates:
            i = j if j in candidates else candidates[0]
            owners[j] = i; used.add(i)
    remaining = [i for i in range(len(old)) if i not in used]
    for j,box in enumerate(after):
        if j in owners: continue
        if len(old)==len(new) and j in remaining:
            owners[j]=j; continue
        # Split pieces inherit their original body's appearance and visibility.
        # Only infer an owner when positive-volume bounds overlap unambiguously.
        overlaps=[]
        for i in remaining:
            lengths=np.minimum(before[i][3:],box[3:])-np.maximum(before[i][:3],box[:3])
            if np.all(lengths>1e-8): overlaps.append(i)
        if len(overlaps)==1: owners[j]=overlaps[0]
    result=copy.deepcopy(display)
    for field in ('materials','bodies','body_names'):
        if field in display:
            result[field]={str(j):copy.deepcopy(display[field][str(i)])
                           for j,i in owners.items() if str(i) in display[field]}
    return result
