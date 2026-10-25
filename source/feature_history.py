"""Dependency inspection and atomic history mutations."""
import copy
from legacy_model import ModelError

CONTEXT_TOOLS={'fillet','chamfer','shell','draft','body_move','body_mirror','body_rectangular','body_circular','body_split','body_combine','press_pull','offset_face','split_face','replace_face','scale'}


def graph(features):
    ids={f.get('id') for f in features if f.get('id')};output={};previous_solid=None;component_joints={}
    for index,f in enumerate(features):
        key=f.get('id') or '@'+str(index);deps=set()
        def visit(value,field=None):
            if isinstance(value,dict):
                for k,v in value.items():
                    if value.get('kind')=='component' and k=='features':continue
                    if k not in ('id','name','entities','fixed','parameters','region_key') or isinstance(v,list) and k=='entities':visit(v,k)
            elif isinstance(value,list):
                for item in value:visit(item,field)
            elif isinstance(value,str):
                if value in ids and value!=key:deps.add(value)
                if field=='body_id':
                    producer=value.split(':',1)[0]
                    if producer in ids and producer!=key:deps.add(producer)
        visit(f)
        explicit_picks=any(k in f for k in ('targets','edge_refs','body_ref'))
        if previous_solid and (f.get('kind') in CONTEXT_TOOLS and not explicit_picks or f.get('operation') in ('cut','intersect')):deps.add(previous_solid)
        if f.get('kind')=='joint':
            # 'fixed' is skipped by visit() (sketch entities use it as a flag), so the
            # fixed component must be added explicitly or a joint could be reordered above it.
            if isinstance(f.get('fixed'),str) and f['fixed'] in ids and f['fixed']!=key:deps.add(f['fixed'])
            for component in (f.get('moving'),f.get('fixed')):
                if component in component_joints:deps.add(component_joints[component])
            component_joints[f.get('moving')]=key
        output[key]=deps
        if f.get('enabled',True) and f.get('kind') not in ('sketch','sketch_move','construction_plane','construction_axis'):previous_solid=key
    return output


def descendants(features,key):
    relations=graph(features);result=set();pending={key}
    while pending:
        next_ids={id_ for id_,inputs in relations.items() if inputs&pending}-result
        result|=next_ids;pending=next_ids
    result.discard(key);return result


def validate_order(candidate,dependencies):
    positions={f.get('id') or '@'+str(i):i for i,f in enumerate(candidate)}
    enabled={f.get('id') or '@'+str(i) for i,f in enumerate(candidate) if f.get('enabled',True)}
    names={f.get('id') or '@'+str(i):f.get('name','Unnamed') for i,f in enumerate(candidate)}
    for key in enabled:
        for dependency in dependencies.get(key,set()):
            if dependency not in positions:raise ModelError(f'{names[key]} requires a missing feature. Repair its dependency.')
            if dependency not in enabled:raise ModelError(f'{names[key]} depends on suppressed feature {names[dependency]}. Suppress its dependents too, or repair their inputs.')
            if positions[dependency]>=positions[key]:raise ModelError(f'Cannot reorder {names[key]} before required feature {names[dependency]}.')


def reordered(features,index,destination):
    if not isinstance(index,int) or not isinstance(destination,int) or not 0<=index<len(features) or not 0<=destination<len(features):raise ModelError('Choose valid feature positions.')
    if not features[index].get('id'):raise ModelError('This legacy feature needs a persistent identity before it can be safely reordered.')
    candidate=copy.deepcopy(features);item=candidate.pop(index);candidate.insert(destination,item)
    validate_order(candidate,graph(features));return candidate


def suppression(features,index,enabled,cascade=False):
    if not isinstance(index,int) or not 0<=index<len(features):raise ModelError('Choose a valid history feature.')
    candidate=copy.deepcopy(features);key=candidate[index].get('id') or '@'+str(index)
    affected={key}|(descendants(features,key) if cascade and not enabled else set())
    for i,f in enumerate(candidate):
        if (f.get('id') or '@'+str(i)) in affected:f['enabled']=bool(enabled)
    validate_order(candidate,graph(features));return candidate
