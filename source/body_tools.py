"""Explicitly selected body transformations, patterns, splits and booleans."""
import math
import numpy as np
import cadquery as cq
from legacy_model import ModelError,number
from geometry import axes
from solid_tools import plane_reference,axis_reference,valid
from references import resolve_body,body_reference

BODY_TOOLS=('body_move','body_mirror','body_rectangular','body_circular','body_split','body_combine')
LABELS={'body_move':'Move / Copy','body_mirror':'Body mirror','body_rectangular':'Rectangular pattern','body_circular':'Circular pattern','body_split':'Split body','body_combine':'Combine bodies'}

def count(value,label,maximum=200):
    if not isinstance(value,int) or isinstance(value,bool) or not 1<=value<=maximum:raise ModelError(label+' must be an integer between 1 and '+str(maximum)+'.')
    return value

def body_operation(feature,result,sketches,frames):
    if result is None:raise ModelError('Create a body first.')
    bodies=result.val().Solids();kind=feature['kind'];refs=feature.get('targets',[])
    if not refs:raise ModelError('Select at least one target body explicitly.')
    picked=[resolve_body(result,ref) for ref in refs];indices=[i for i,b in picked]
    if len(set(indices))!=len(indices):raise ModelError('Select distinct target bodies.')
    selected=[b for i,b in picked];generated=[];replacements={}
    if kind=='body_move':
        offset=[number(feature.get(k,0),k.upper()) for k in ('dx','dy','dz')];angle=number(feature.get('angle',0),'Angle')
        if not any(offset) and not angle:raise ModelError('Enter a nonzero translation or rotation.')
        a,d=axis_reference(feature.get('axis',{'type':'origin','axis':'Z'}),result,sketches,frames)
        for i,body in picked:
            shape=body.rotate(tuple(a),tuple(a+d),angle) if angle else body
            shape=shape.translate(tuple(offset));valid(shape,'Move')
            if feature.get('copy',False):generated.append(shape)
            else:replacements[i]=[shape]
    elif kind=='body_mirror':
        frame=plane_reference(feature.get('plane'),result,frames);o,u,v,n=axes(frame)
        for i,body in picked:
            shape=valid(body.mirror(tuple(n),tuple(o)),'Mirror')
            if feature.get('keep_original',True):generated.append(shape)
            else:replacements[i]=[shape]
    elif kind=='body_rectangular':
        columns=count(feature.get('columns',2),'Columns');rows=count(feature.get('rows',1),'Rows')
        if columns*rows*len(selected)>500:raise ModelError('This pattern exceeds 500 bodies. Reduce the count.')
        x=number(feature.get('spacing_x',20),'X spacing');y=number(feature.get('spacing_y',20),'Y spacing')
        if feature.get('spacing_mode')=='extent':       # the value is the whole length of the pattern
            x=x/(columns-1) if columns>1 else x;y=y/(rows-1) if rows>1 else y
        frame=plane_reference(feature.get('plane',{'type':'origin','plane':'XY'}),result,frames);o,u,v,n=axes(frame)
        if columns*rows==1 or columns>1 and abs(x)<1e-9 or rows>1 and abs(y)<1e-9:raise ModelError('Use at least two positions and nonzero spacing for active directions.')
        generated=[b.translate(tuple(u*x*c+v*y*r)) for r in range(rows) for c in range(columns) if c or r for b in selected]
    elif kind=='body_circular':
        copies=count(feature.get('count',4),'Positions');angle=number(feature.get('angle',360),'Pattern angle')
        if copies<2 or not 0<abs(angle)<=360:raise ModelError('Use at least two positions and a nonzero angle up to 360 degrees.')
        if copies*len(selected)>500:raise ModelError('This pattern exceeds 500 bodies. Reduce the count.')
        a,d=axis_reference(feature.get('axis',{'type':'origin','axis':'Z'}),result,sketches,frames)
        step=angle/(copies if abs(abs(angle)-360)<1e-7 else copies-1)
        generated=[b.rotate(tuple(a),tuple(a+d),i*step) for i in range(1,copies) for b in selected]
    elif kind=='body_split':
        frame=plane_reference(feature.get('plane'),result,frames);o,u,v,n=axes(frame);keep=feature.get('keep','both')
        if keep not in ('both','positive','negative'):raise ModelError('Choose both, positive or negative split sides.')
        for i,body in picked:
            box=body.BoundingBox();span=max(10.,math.sqrt(box.xlen**2+box.ylen**2+box.zlen**2)+np.linalg.norm(np.asarray(body.Center().toTuple())-o))*2
            wire=cq.Wire.makePolygon([tuple(o+u*x+v*y) for x,y in ((-span,-span),(span,-span),(span,span),(-span,span),(-span,-span))])
            positive=body.intersect(cq.Solid.extrudeLinear(wire,[],tuple(n*span))).Solids();negative=body.intersect(cq.Solid.extrudeLinear(wire,[],tuple(-n*span))).Solids()
            if not positive or not negative:raise ModelError('The split plane must cross every selected body.')
            replacements[i]=list(positive if keep=='positive' else negative if keep=='negative' else negative+positive)
    elif kind=='body_combine':
        if len(picked)!=1:raise ModelError('Combine requires exactly one target body.')
        tools=[resolve_body(result,ref) for ref in feature.get('tools',[])];tool_indices=[i for i,b in tools]
        if not tools or len(set(tool_indices))!=len(tool_indices) or any(i in indices for i in tool_indices):raise ModelError('Select distinct tool bodies, separate from the target.')
        operation=feature.get('operation','join')
        if operation not in ('join','cut','intersect'):raise ModelError('Choose Join, Cut or Intersect.')
        target=selected[0];compound=cq.Compound.makeCompound([b for i,b in tools])
        if operation=='join':edited=target.fuse(*[b for i,b in tools]).clean()
        elif operation=='cut':
            if target.intersect(compound).Volume()<1e-9:raise ModelError('The tool bodies do not intersect the target.')
            edited=target.cut(compound).clean()
        else:edited=target.intersect(compound).clean()
        valid(edited,'Combine')
        if operation=='join' and len(edited.Solids())!=1:raise ModelError('Join requires touching or overlapping bodies. Disconnected bodies stay separate.')
        replacements[indices[0]]=list(edited.Solids())
        if not feature.get('keep_tools',False):
            for i,b in tools:replacements[i]=[]
    else:raise ModelError('Unknown body tool.')
    output=[shape for i,b in enumerate(bodies) for shape in replacements.get(i,[b])]+generated
    if not output:raise ModelError('This operation would remove all bodies.')
    for b in output:valid(b,'Body operation')
    return cq.Compound.makeCompound(output) if len(output)>1 else output[0]
