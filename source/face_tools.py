"""Local face edits with explicit ownership and atomic, validated output."""
import cadquery as cq
import numpy as np
from legacy_model import ModelError,number,positive
from solid_tools import selected_faces,profile,plane_reference,valid
from references import resolve_body

FACE_TOOLS=('press_pull','scale','offset_face','split_face','replace_face')

def offset_faces(body,faces,distance):
    from OCP.BRepOffset import BRepOffset_MakeOffset
    from OCP.GeomAbs import GeomAbs_Intersection
    distance=number(distance,'Distance')
    if abs(distance)<1e-9:raise ModelError('Offset distance cannot be zero.')
    builder=BRepOffset_MakeOffset()
    builder.Initialize(body.wrapped,0.,1e-6,Join=GeomAbs_Intersection)
    for face in faces:builder.SetOffsetOnFace(face.wrapped,distance)
    builder.MakeOffsetShape()
    if not builder.IsDone():raise ModelError('These offsets cannot meet without invalid or intersecting faces. Reduce the distance.')
    return valid(cq.Shape.cast(builder.Shape()).clean(),'Offset face')

def operation(f,result,sketches,frames):
    if f['kind']=='press_pull' and f.get('press_type')=='profile':
        from solid_tools import extrude
        tool=extrude(f.get('source'),dict(depth=f.get('distance',1)),result,sketches,frames);op=f.get('operation','new')
        bodies=list(result.val().Solids()) if result else []
        if op=='new':return cq.Compound.makeCompound(bodies+[tool]) if bodies else tool
        if result is None:raise ModelError('Choose New body for the first profile, or select an existing target body.')
        picked=[resolve_body(result,r) for r in f.get('targets',[])]
        if not picked:raise ModelError('Select a target body explicitly.')
        for index,body in picked:
            if op not in ('join','cut','intersect'):raise ModelError('Choose New body, Join, Cut or Intersect.')
            edited=body.fuse(tool) if op=='join' else body.cut(tool) if op=='cut' else body.intersect(tool)
            valid(edited,'Press Pull');bodies[index]=edited.clean()
        return cq.Compound.makeCompound(bodies) if len(bodies)>1 else bodies[0]
    if result is None:raise ModelError('Create a body first.')
    if not f.get('targets'):raise ModelError('Select a target body explicitly.')
    picked=[resolve_body(result,r) for r in f['targets']]
    if len({i for i,b in picked})!=len(picked):raise ModelError('Select distinct bodies.')
    kind=f['kind'];faces=selected_faces(result,f.get('faces',[])) if kind!='scale' else []
    if kind!='scale' and (len(picked)!=1 or not faces):raise ModelError('Select faces on one target body.')
    output=list(result.val().Solids())
    for index,body in picked:
        if any(not any(face.isSame(own) for own in body.Faces()) for face in faces):raise ModelError('Every selected face must belong to the target body.')
        if kind=='scale':
            factor=positive(f.get('factor',1),'Scale factor');pivot=np.asarray(f.get('pivot',[0,0,0]),float)
            if pivot.shape!=(3,) or not np.all(np.isfinite(pivot)):raise ModelError('Enter a finite scale center.')
            edited=body.translate(tuple(-pivot)).scale(factor).translate(tuple(pivot))
        elif kind in ('offset_face','press_pull'):edited=offset_faces(body,faces,f.get('distance',1))
        elif kind=='split_face':
            if len(faces)!=1:raise ModelError('Split Face needs one face.')
            source=f.get('source')
            if source and source.get('type')=='path':
                from solid_tools import path_wire
                wire=path_wire(source,sketches,frames);holes=[]
            else:wire,holes,frame=profile(source,result,sketches,frames)
            from OCP.BRepFeat import BRepFeat_SplitShape
            builder=BRepFeat_SplitShape(body.wrapped);builder.Add(wire.wrapped,faces[0].wrapped)
            for hole in holes:builder.Add(hole.wrapped,faces[0].wrapped)
            builder.Build()
            if not builder.IsDone():raise ModelError('The splitting profile must lie on and intersect the selected face.')
            edited=cq.Shape.cast(builder.Shape())
            if len(edited.Faces())<=len(body.Faces()):raise ModelError('The profile did not divide the selected face.')
        elif kind=='replace_face':
            target=plane_reference(f.get('replacement'),result,frames);o=np.asarray(target['origin']);n=np.asarray(target['normal'])
            if any(face.geomType()!='PLANE' or abs(abs(np.asarray(face.normalAt().toTuple())@n)-1)>1e-6 for face in faces):raise ModelError('Replace Face currently needs parallel planar faces. Curved replacement requires matching extended surface boundaries.')
            distances=[float((o-np.asarray(face.Center().toTuple()))@np.asarray(face.normalAt().toTuple())) for face in faces]
            # Different offsets need separate kernel settings, in one rebuild.
            from OCP.BRepOffset import BRepOffset_MakeOffset
            from OCP.GeomAbs import GeomAbs_Intersection
            builder=BRepOffset_MakeOffset();builder.Initialize(body.wrapped,0.,1e-6,Join=GeomAbs_Intersection)
            for face,distance in zip(faces,distances):builder.SetOffsetOnFace(face.wrapped,distance)
            builder.MakeOffsetShape()
            if not builder.IsDone():raise ModelError('Replacement faces cannot meet the neighboring faces.')
            edited=cq.Shape.cast(builder.Shape()).clean()
        else:raise ModelError('Unknown face editing tool.')
        valid(edited,kind.replace('_',' ').title());output[index]=edited
    return cq.Compound.makeCompound(output) if len(output)>1 else output[0]
