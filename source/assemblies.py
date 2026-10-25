"""Nested component documents and explicit one-axis assembly motion."""
import copy
import cadquery as cq
import numpy as np
from legacy_model import ModelError,number
from solid_tools import unit,point
from topology import entries,orientation_key

ASSEMBLY_TOOLS=('component','joint')

def components(frames):return frames.get('_components',{})

def transform(shape,pose):
    origin=point(pose.get('origin',[0,0,0]));axis=unit(pose.get('axis',[0,0,1]));angle=number(pose.get('angle',0),'Component angle')
    return (shape.rotate((0,0,0),tuple(axis),angle) if angle else shape).translate(tuple(origin))

def component_point(component,coordinates):
    vertex=transform(cq.Vertex.makeVertex(*coordinates),component['pose'])
    motion=component.get('motion')
    if motion:
        anchor=np.asarray(motion['anchor']);axis=np.asarray(motion['direction'])
        if motion['type'] in ('revolute','cylindrical','mate'):vertex=vertex.rotate(tuple(anchor),tuple(anchor+axis),motion['value'])
        amount=motion['value'] if motion['type']=='slider' else motion['translation']
        vertex=vertex.translate(tuple(np.asarray(motion.get('offset',[0,0,0]))+axis*amount))
    return np.asarray(vertex.Center().toTuple())

def mate_pose(feature,result,component):
    """Rotation and translation that bring a face of ``component`` onto a face of another body.

    The two planar faces end up coincident with opposing normals (touching), or with equal normals
    (``flip``: flush). The face centres are brought together unless ``mate_center`` is off, and
    ``mate_offset`` leaves a gap along the target normal. Returns ``(anchor, axis, angle, vector)``.
    """
    from references import match_shape
    moving_ref=(feature.get('mate_moving') or {}).get('face');target_ref=(feature.get('mate_target') or {}).get('face')
    if not isinstance(moving_ref,dict) or not isinstance(target_ref,dict):raise ModelError('Pick a face of the moving component and a face of the other body to mate.')
    if result is None:raise ModelError('A mate needs bodies to align.')
    face_m,_=match_shape(result,moving_ref,'face');face_t,_=match_shape(result,target_ref,'face')
    if face_m.geomType()!='PLANE' or face_t.geomType()!='PLANE':raise ModelError('Mates align planar faces. Choose flat faces.')
    owners=lambda face:{item['id'] for item in entries(result) if any(face.isSame(own) for own in item['shape'].Faces())}
    members=set(component['members'])
    if not owners(face_m)&members:raise ModelError('The first face must belong to the moving component.')
    if owners(face_t)&members:raise ModelError('The second face must belong to a different component or body.')
    nm=np.asarray(face_m.normalAt().toTuple());nt=np.asarray(face_t.normalAt().toTuple())
    nm/=np.linalg.norm(nm);nt/=np.linalg.norm(nt)
    wanted=nt if feature.get('flip',False) else -nt
    axis=np.cross(nm,wanted);sine=float(np.linalg.norm(axis));cosine=float(nm@wanted)
    if sine<1e-9:
        if cosine>0:axis=np.array([0.,0.,1.]);angle=0.
        else:
            helper=np.eye(3)[int(np.argmin(np.abs(nm)))];axis=np.cross(nm,helper);axis/=np.linalg.norm(axis);angle=180.
    else:
        axis=axis/sine;angle=float(np.degrees(np.arctan2(sine,cosine)))
    cm=np.asarray(face_m.Center().toTuple());ct=np.asarray(face_t.Center().toTuple())
    gap=number(feature.get('mate_offset',0),'Mate offset')
    if feature.get('mate_center',True):vector=ct+nt*gap-cm
    else:vector=nt*(float((ct-cm)@nt)+gap)
    return cm,axis,angle,vector


def validate_tree(features,ancestors=(),depth=0):
    if depth>32:raise ModelError('Component nesting exceeds 32 levels.')
    ids=[f.get('id') for f in features if f.get('id')]
    if len(ids)!=len(set(ids)):raise ModelError('Feature IDs must be unique within each component history.')
    for f in features:
        if f.get('kind')=='component':
            id_=f.get('id')
            if not id_ or id_ in ancestors:raise ModelError('Component ancestry contains a missing identity or a cycle.')
            child=f.get('features',[])
            if not isinstance(child,list):raise ModelError('A component needs its own feature history.')
            validate_tree(child,ancestors+(id_,),depth+1)

def operation(f,result,frames,progress=None):
    registry=dict(components(frames));surfaces=dict(frames.get('_surfaces',{}));records=list(entries(result));kind=f['kind']
    if kind=='component':
        from model import build_state
        validate_tree([f]);id_=f['id']
        if id_ in registry:raise ModelError('Duplicate component identity.')
        local,sketches,child_frames=build_state(copy.deepcopy(f.get('features',[])),progress=progress)
        pose=f.get('pose',{});members=[]
        for item in entries(local):
            body=transform(item['shape'],pose);key=id_+'/'+item['id'];members.append(key);records.append(dict(id=key,shape=body,producer=id_,orientation=orientation_key(item.get('orientation',''),('component',pose.get('angle',0),pose.get('axis',[0,0,1])) if pose.get('angle',0)%360 else item.get('orientation',''))))
        for key,body in child_frames.get('_surfaces',{}).items():
            full=id_+'/'+key;surfaces[full]=dict(shape=transform(body['shape'],pose),name=f['name']+' / '+body['name'],producer=id_)
        registry[id_]=dict(name=f['name'],members=members,surfaces=[id_+'/'+key for key in child_frames.get('_surfaces',{})],pose=copy.deepcopy(pose),grounded=bool(f.get('grounded',False)),children=copy.deepcopy({key:dict(name=value['name'],pose=value['pose']) for key,value in components(child_frames).items()}))
    else:
        moving=f.get('moving');fixed=f.get('fixed')
        if moving not in registry or fixed is not None and fixed not in registry:raise ModelError('A joint component is missing, suppressed or later in history.')
        if moving==fixed:raise ModelError('A joint needs two distinct components, or the assembly origin.')
        component=copy.deepcopy(registry[moving])
        if component['grounded']:raise ModelError('Unground the moving component before adding a joint.')
        if component.get('joint'):raise ModelError('This component already has a driving joint. Edit that joint or suppress it first.')
        present={item['id'] for item in records}
        if any(id_ not in present for id_ in component['members']):raise ModelError('The component bodies changed topology outside their own history. Edit the component history before adding a joint.')
        ancestor=fixed
        while ancestor is not None:
            if ancestor==moving:raise ModelError('This joint would create a cyclic assembly chain.')
            ancestor=registry[ancestor].get('fixed')
        joint=f.get('joint_type','rigid')
        if joint not in ('rigid','revolute','slider','cylindrical','mate'):raise ModelError('Choose a supported joint type.')
        if joint=='mate':
            # Face to face: the pose comes from the two faces, in world coordinates.
            anchor,axis,angle,offset=mate_pose(f,result,component);translation=0.;value=0.
            component_value=angle
        else:
            value=number(f.get('value',0),'Joint position');minimum=number(f.get('minimum',-360),'Minimum');maximum=number(f.get('maximum',360),'Maximum')
            if minimum>maximum or not minimum<=value<=maximum:raise ModelError('Joint position is outside its motion limits.')
            anchor=point(f.get('anchor',[0,0,0]));axis=unit(f.get('direction',[0,0,1]));offset=point(f.get('offset',[0,0,0]))
            if fixed is not None:
                base=registry[fixed];end=component_point(base,anchor+axis);anchor=component_point(base,anchor);axis=unit(end-anchor)
            translation=value if joint=='slider' else number(f.get('translation',0),'Axial position') if joint=='cylindrical' else 0.
            angle=value if joint in ('revolute','cylindrical') else 0.
            component_value=value
        def move(shape):return (shape.rotate(tuple(anchor),tuple(anchor+axis),angle) if angle else shape).translate(tuple(offset+axis*translation))
        ids=set(component['members'])
        records=[dict(item,shape=move(item['shape']),producer=f['id'],orientation=orientation_key(item.get('orientation',''),('joint',round(angle%360,9),tuple(axis))) if angle%360 else item.get('orientation','')) if item['id'] in ids else item for item in records]
        for key in component['surfaces']:surfaces[key]=dict(surfaces[key],shape=move(surfaces[key]['shape']))
        component['joint']=f['id'];component['fixed']=fixed;component['motion']=dict(type=joint,value=component_value,translation=translation,anchor=anchor.tolist(),direction=axis.tolist(),offset=offset.tolist());registry[moving]=component
    next_frames=dict(frames);next_frames['_components']=registry;next_frames['_surfaces']=surfaces
    shapes=[item['shape'] for item in records]
    if shapes:
        if any(not shape.isValid() for shape in shapes):raise ModelError('Component motion produced invalid geometry.')
        result=cq.Workplane('XY').newObject([cq.Compound.makeCompound(shapes) if len(shapes)>1 else shapes[0]]);result._slothcad_bodies=records
    return result,next_frames

def assembled_features(stack,current):
    output=copy.deepcopy(current.features);display=copy.deepcopy(current.display)
    for entry in reversed(stack):
        parent=copy.deepcopy(entry['document'].features);parent[entry['index']]['features']=output;parent[entry['index']]['display']=display
        output=parent;display=copy.deepcopy(entry['document'].display)
    return output
