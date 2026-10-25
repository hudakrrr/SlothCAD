"""Patterns of bodies, feature material changes and removable face groups."""
import cadquery as cq
import numpy as np
import math
from legacy_model import ModelError,number
from body_tools import count
from references import resolve_body
from solid_tools import plane_reference,axis_reference,path_wire,selected_faces,valid
from geometry import axes

PATTERN_TOOLS=('feature_rectangular','feature_circular','feature_mirror','path_pattern')

def transforms(f,result,sketches,frames):
    kind=f['kind']
    if kind=='feature_mirror':
        o,u,v,n=axes(plane_reference(f.get('plane'),result,frames))
        return [lambda shape:shape.mirror(tuple(n),tuple(o))]
    if kind=='feature_rectangular':
        columns=count(f.get('columns',2),'Columns');rows=count(f.get('rows',1),'Rows')
        if columns*rows>500:raise ModelError('Use no more than 500 pattern positions.')
        x=number(f.get('spacing_x',20),'X spacing');y=number(f.get('spacing_y',20),'Y spacing')
        if f.get('spacing_mode')=='extent':             # the value is the whole length of the pattern
            x=x/(columns-1) if columns>1 else x;y=y/(rows-1) if rows>1 else y
        if columns*rows<2 or columns>1 and abs(x)<1e-9 or rows>1 and abs(y)<1e-9:raise ModelError('Use at least two positions with nonzero spacing.')
        o,u,v,n=axes(plane_reference(f.get('plane',dict(type='origin',plane='XY')),result,frames))
        return [lambda shape,shift=tuple(u*x*c+v*y*r):shape.translate(shift) for r in range(rows) for c in range(columns) if r or c]
    positions=count(f.get('count',4),'Positions',500)
    if positions<2:raise ModelError('Choose at least two pattern positions.')
    if kind=='feature_circular':
        a,d=axis_reference(f.get('axis'),result,sketches,frames);angle=number(f.get('angle',360),'Angle')
        if not 0<abs(angle)<=360:raise ModelError('Enter a nonzero angle up to 360 degrees.')
        step=angle/(positions if abs(abs(angle)-360)<1e-7 else positions-1)
        return [lambda shape,angle=i*step:shape.rotate(tuple(a),tuple(a+d),angle) for i in range(1,positions)]
    path=path_wire(f.get('path'),sketches,frames);start=path.positionAt(0).toTuple();start=np.asarray(start);t0=np.asarray(path.tangentAt(0).toTuple())
    def along(shape,t):
        end=np.asarray(path.positionAt(t).toTuple());t1=np.asarray(path.tangentAt(t).toTuple())
        if f.get('orient',False):
            cross=np.cross(t0,t1);dot=float(np.clip(t0@t1,-1,1));angle=math.degrees(math.acos(dot))
            if angle>1e-7:
                if np.linalg.norm(cross)<1e-8:cross=np.cross(t0,np.eye(3)[np.argmin(np.abs(t0))])
                shape=shape.rotate(tuple(start),tuple(start+cross),angle)
        return shape.translate(tuple(end-start))
    return [lambda shape,t=i/(positions if path.IsClosed() else positions-1):along(shape,t) for i in range(1,positions)]

def effects(f,result,history):
    from model import build_state
    ids=f.get('features',[])
    if not ids or len(set(ids))!=len(ids):raise ModelError('Select one or more distinct earlier features.')
    added=[];removed=[]
    for id_ in ids:
        index=next((i for i,h in enumerate(history) if h.get('id')==id_ and h.get('enabled',True)),None)
        if index is None:raise ModelError('A patterned feature is missing, suppressed or later in history.')
        before,_,_=build_state(history[:index]);after,_,_=build_state(history[:index+1])
        if after is None:raise ModelError('Patterns need features that change solid material.')
        if before is None:added.extend(after.val().Solids())
        else:
            add=after.val().cut(before.val());cut=before.val().cut(after.val())
            if add.Volume()>1e-8:added.extend(add.Solids())
            if cut.Volume()>1e-8:removed.extend(cut.Solids())
    if not added and not removed:raise ModelError('These features do not add or remove material. Select a solid feature.')
    return added,removed

def operation(f,result,sketches,frames,history):
    if result is None:raise ModelError('Create a body first.')
    picked=[resolve_body(result,r) for r in f.get('targets',[])]
    if not picked or len({i for i,b in picked})!=len(picked):raise ModelError('Select distinct target bodies explicitly.')
    actions=transforms(f,result,sketches,frames);mode=f.get('object_type','features')
    if mode=='bodies':
        if len(actions)*len(picked)>500:raise ModelError('This pattern exceeds 500 body copies.')
        generated=[fn(b) for fn in actions for i,b in picked]
        for shape in generated:valid(shape,'Pattern')
        return cq.Compound.makeCompound(list(result.val().Solids())+generated)
    if mode=='features':added,removed=effects(f,result,history)
    elif mode=='faces':
        if len(picked)!=1:raise ModelError('Face patterns need one target body.')
        faces=selected_faces(result,f.get('faces',[]));body=picked[0][1]
        if not faces or any(not any(face.isSame(own) for own in body.Faces()) for face in faces):raise ModelError('Select a complete face group on the target body.')
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
        builder=BRepAlgoAPI_Defeaturing();builder.SetShape(body.wrapped)
        for face in faces:builder.AddFaceToRemove(face.wrapped)
        builder.Build()
        if not builder.IsDone():raise ModelError('The selected faces cannot be healed into a removable feature. Include all faces of the hole or boss.')
        base=valid(cq.Shape.cast(builder.Shape()),'Face pattern recovery');add=body.cut(base);cut=base.cut(body)
        added=add.Solids() if add.Volume()>1e-8 else [];removed=cut.Solids() if cut.Volume()>1e-8 else []
        if not added and not removed:raise ModelError('These faces do not define a removable feature.')
    else:raise ModelError('Choose bodies, features or faces.')
    output=list(result.val().Solids())
    for index,body in picked:
        edited=body
        for fn in actions:
            for shape in added:edited=edited.fuse(fn(shape))
            for shape in removed:edited=edited.cut(fn(shape))
        edited=valid(edited.clean(),'Pattern')
        if len(edited.Solids())!=1:raise ModelError('Patterned material is disconnected from the target. Use a body pattern for separate copies.')
        output[index]=edited
    return cq.Compound.makeCompound(output) if len(output)>1 else output[0]
