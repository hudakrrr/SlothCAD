"""Version 2 documents: standalone sketches and selectable sketch/face extrusions."""
from __future__ import annotations
import copy
import hashlib
import itertools
import json
import math
import os
import shutil
from pathlib import Path
import tempfile
import threading
from collections import OrderedDict
from platform_support import replace_file,set_mode
import cadquery as cq
import numpy as np
from legacy_model import ModelError, number, positive, new_feature, profile_solid
from geometry import axes, sketch_frame, resolve_face, regions, wire_for, profile_regions

SCHEMA = 10

def edge_reference(edge,result=None):
    from references import shape_reference
    return shape_reference(edge,'edge',result)

def extrusion_sources(feature):
    """Return modern multi-extrude sources while accepting legacy single-source features."""
    if 'sources' in feature:
        sources=feature.get('sources')
        if not isinstance(sources,list) or not sources:raise ModelError('Select at least one face or sketch profile to extrude.')
        if any(not isinstance(source,dict) for source in sources):raise ModelError('Invalid extrusion source list.')
        return sources
    source=feature.get('source')
    if not isinstance(source,dict):raise ModelError('Select a face or sketch profile to extrude.')
    return [source]

def resolve_edges(result,references):
    from references import match_shape
    available=list(result.val().Edges()) if result else [];chosen=[]
    for reference in references:
        edge,state=match_shape(result,reference,'edge',available)
        chosen.append(edge);available=[e for e in available if not e.isSame(edge)]
    return chosen

_STATUS=[];_STATUS_LOCK=threading.Lock()

def _shape_status(shape):
    """(is a valid solid, volume) of a shape, remembered for the shapes checked most recently.

    A rebuild used to run the kernel's validity check and a volume integral on the whole
    result several times per feature (after the boolean, in the fallback test and again at
    the end of the feature), which is the dominant cost once a model has big bodies.
    The same shape object is checked only once; ``isEqual`` also compares orientation.
    """
    with _STATUS_LOCK:
        for known,ok,volume in reversed(_STATUS):
            if known.isEqual(shape):return ok,volume
    from validity import shape_valid
    ok=bool(shape_valid(shape) and shape.Solids());volume=float(shape.Volume()) if ok else 0.
    with _STATUS_LOCK:
        _STATUS.append((shape,ok,volume));del _STATUS[:-16]
    return ok,volume

def release_kernel_caches():
    """Forget every remembered kernel measurement and mesh.

    The caches hold references to kernel shapes (so repeated edits stay fast). When a project is
    closed those shapes are no longer needed; dropping them returns the memory to the system.
    Everything is recomputed on demand, so this is always safe.
    """
    with _STATUS_LOCK:
        del _STATUS[:]
    try:
        import references
        with references._SHAPE_CACHE_LOCK:
            references._SHAPE_CACHE.clear()
    except Exception:pass
    try:
        import mesh_cache
        mesh_cache.clear()
    except Exception:pass


def _edge_trial_is_valid(trial):
    try:
        value=trial.val()
        if value is None:return False
        ok,volume=_shape_status(value)
        return ok and volume>1e-9
    except Exception:return False


def _extrusion_boolean(base,tool,solids,operation):
    """Run an extrusion boolean, falling back to per-profile operations if a compound fails."""
    action={'add':'union','cut':'cut','intersect':'intersect'}[operation]
    try:
        combined=getattr(base,action)(tool)
        if _edge_trial_is_valid(combined):return combined
    except Exception:pass
    if operation in ('add','cut') and len(solids)>1:
        current=base
        try:
            for solid in solids:
                current=getattr(current,action)(solid)
                if not _edge_trial_is_valid(current):raise ModelError('A selected profile produced an invalid intermediate solid.')
            return current
        except Exception as error:
            raise ModelError('The selected extrusions could not be joined into a valid solid. Try separating profiles that overlap or touch.') from error
    raise ModelError('The extrusion boolean did not produce a valid solid. Check the profile overlap and direction.')


def _body_boolean(base,tool,solids,operation):
    """An extrusion boolean applied body by body when the model has several bodies.

    Separate bodies may overlap (New body, Combine with kept tools, imports). A boolean against
    all of them as one compound makes the kernel split overlapping bodies against each other,
    so a cut through one body also cut a body lying inside it into pieces. Here only bodies
    whose bounds reach the tool take part, each on its own: a cut or intersect changes each of
    them separately, a join merges the tool with the bodies it reaches. Others stay as they are.
    """
    bodies=list(base.val().Solids())
    if len(bodies)<2:return _extrusion_boolean(base,tool,solids,operation)
    shape=tool.val();box=shape.BoundingBox();gap=1e-6
    def reaches(body):
        b=body.BoundingBox()
        return not (b.xmin>box.xmax+gap or b.xmax<box.xmin-gap or b.ymin>box.ymax+gap or b.ymax<box.ymin-gap or b.zmin>box.zmax+gap or b.zmax<box.zmin-gap)
    reached=[reaches(b) for b in bodies];output=[]
    def single(body):return cq.Workplane('XY').newObject([body])
    if operation=='add':
        touched=[b for b,r in zip(bodies,reached) if r]
        merged=list(shape.Solids()) if not touched else list(_extrusion_boolean(single(touched[0]) if len(touched)==1 else cq.Workplane('XY').newObject([touched[0].fuse(*touched[1:])]),tool,solids,'add').val().Solids())
        placed=False
        for body,r in zip(bodies,reached):
            if not r:output.append(body)
            elif not placed:output.extend(merged);placed=True
        if not placed:output.extend(merged)
    else:
        for body,r in zip(bodies,reached):
            if not r:
                if operation=='cut':output.append(body)
                continue
            try:pieces=_extrusion_boolean(single(body),tool,solids,operation).val().Solids()
            except ModelError:
                if operation=='intersect':continue      # no overlap with this body
                raise
            output.extend(pieces)
    if not output:raise ModelError('The extrusion boolean did not produce a valid solid. Check the profile overlap and direction.')
    return cq.Workplane('XY').newObject([output[0] if len(output)==1 else cq.Compound.makeCompound(output)])


def _participating(result,references):
    """``(base, kept)``: the bodies a feature works on, and the hidden bodies it leaves alone.

    ``references`` are the bodies that were hidden when the feature was made. They are taken out
    before the boolean (so a join does not merge into them, a cut does not cut them and
    through-all ignores them) and put back unchanged afterwards. A reference that no longer
    resolves (the body was removed or changed beyond recognition) simply excludes nothing.
    """
    if result is None or not references:return result,[]
    from references import resolve_body
    bodies=list(result.val().Solids());excluded=set()
    for reference in references:
        try:excluded.add(resolve_body(result,reference)[0])
        except Exception:pass
    if not excluded:return result,[]
    rest=[b for i,b in enumerate(bodies) if i not in excluded]
    base=cq.Workplane('XY').newObject([rest[0] if len(rest)==1 else cq.Compound.makeCompound(rest)]) if rest else None
    return base,[b for i,b in enumerate(bodies) if i in excluded]


def _with_bodies(result,extra):
    """``result`` with the ``extra`` solids added as separate bodies."""
    if not extra:return result
    solids=(list(result.val().Solids()) if result is not None else [])+list(extra)
    return cq.Workplane('XY').newObject([solids[0] if len(solids)==1 else cq.Compound.makeCompound(solids)])


def _solid_count(shape):
    try:return len(shape.Solids())
    except Exception:return 0


def _self_intersects(shape):
    """Strict check that catches fillets whose new surfaces overlap other faces.

    ``isValid`` alone accepts some oversized fillets that fold through the body,
    which then show as seams or cracks and break later features.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
        return not BRepAlgoAPI_Check(shape.wrapped,True,True).IsValid()
    except Exception:return False


def _edge_trial_is_valid_fast(base,trial):
    """Validity of a fillet/chamfer trial, checked only where the operation changed the body.

    The kernel's whole-body validity check costs more than the fillet itself on bodies with
    hundreds of faces. Faces the operation left alone keep their identity, so only the new and
    modified faces (a handful) are analysed; this is what size probing needs.
    """
    try:
        value=trial.val()
        if value is None:return False
        known=getattr(base,'_slothcad_face_ids',None)
        if known is None:
            known={face.hashCode() for face in base.val().Faces()}
            try:base._slothcad_face_ids=known
            except AttributeError:pass
        from validity import faces_valid
        if not faces_valid([face for face in value.Faces() if face.hashCode() not in known]):return False
        return float(value.Volume())>1e-9
    except Exception:return False


LOCAL_CHECK_FACES=120      # bodies with at least this many faces are overlap-checked locally
LOCAL_CHECK_MAX_CHANGED=24 # ... and only when the operation changed at most this many faces


def _base_face_ids(base):
    known=getattr(base,'_slothcad_face_ids',None)
    if known is None:
        known={face.hashCode() for face in base.val().Faces()}
        try:base._slothcad_face_ids=known
        except AttributeError:pass
    return known


def _is_large(base):
    large=getattr(base,'_slothcad_large',None)
    if large is None:
        large=len(base.val().Faces())>=LOCAL_CHECK_FACES
        try:base._slothcad_large=large
        except AttributeError:pass
    return large


def _loose_box(face):
    """A cheap, slightly generous box around a face (the optimal box costs far more)."""
    from references import _cached
    def measure(shape):
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        box=Bnd_Box();BRepBndLib.Add_s(shape.wrapped,box,False)
        x0,y0,z0,x1,y1,z1=box.Get();return np.array([x0,y0,z0]),np.array([x1,y1,z1])
    return _cached('loose-bounds',face,measure)


def _plane_of(face):
    """(unit normal, offset) of a planar face, or None."""
    if face.geomType()!='PLANE':return None
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    plane=BRepAdaptor_Surface(face.wrapped).Plane();d=plane.Axis().Direction();o=plane.Location()
    n=np.array([d.X(),d.Y(),d.Z()]);return n,float(n@np.array([o.X(),o.Y(),o.Z()]))


def _base_planes(base):
    planes=getattr(base,'_slothcad_planes',None)
    if planes is None:
        planes=[p for p in (_plane_of(face) for face in base.val().Faces()) if p is not None]
        try:base._slothcad_planes=planes
        except AttributeError:pass
    return planes


def _on_base_plane(face,planes,tolerance=1e-7):
    plane=_plane_of(face)
    if plane is None:return False
    n,d=plane
    return any(abs(abs(float(n@m))-1)<1e-9 and abs(d-(e if n@m>0 else -e))<=tolerance*max(1.,abs(d)) for m,e in planes)


def _local_self_intersects(base,value):
    """Overlap check restricted to what the operation touched.

    The kernel's whole-body check takes seconds on a body with hundreds of faces (14 s for an
    800-face imported crankshaft) although a fillet can only fold through faces that lie within
    the box of the faces it created or modified. The new faces are grouped by where they are; each
    group is checked together with the faces whose boxes meet the group's box, so distant edges
    of one selection do not drag the whole body into every check.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
        known=_base_face_ids(base)
        faces=list(value.Faces())
        changed=[face for face in faces if face.hashCode() not in known]
        if not changed:return False
        # A fillet that follows a long tangent chain rebuilds dozens of faces; checking them costs
        # more than the operation (13 s on the crankshaft) and the kernel's own validity test has
        # already passed, so only a small, genuinely local change gets the overlap check.
        if len(changed)>LOCAL_CHECK_MAX_CHANGED:return False
        boxes={id(face):_loose_box(face) for face in faces}
        # Faces that only got a new boundary (the big planar faces beside a fillet) are checked as
        # neighbours but do not define where to look: on a plate their box is the whole body.
        planes=_base_planes(base)
        seeds=[face for face in changed if not _on_base_plane(face,planes)] or changed
        # group the new faces whose boxes touch (union-find)
        parent=list(range(len(seeds)))
        def find(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        for i in range(len(seeds)):
            for j in range(i+1,len(seeds)):
                a=boxes[id(seeds[i])];b=boxes[id(seeds[j])]
                if np.all(a[0]<=b[1]) and np.all(b[0]<=a[1]):parent[find(i)]=find(j)
        groups={}
        for i,face in enumerate(seeds):groups.setdefault(find(i),[]).append(face)
        from validity import near_part
        for members in groups.values():
            low=np.min([boxes[id(f)][0] for f in members],axis=0);high=np.max([boxes[id(f)][1] for f in members],axis=0)
            chosen={id(f) for f in members}
            near=[near_part(f,low,high) for f in faces if id(f) not in chosen and np.all(boxes[id(f)][0]<=high) and np.all(boxes[id(f)][1]>=low)]
            compound=cq.Compound.makeCompound(members+near)
            if not BRepAlgoAPI_Check(compound.wrapped,True,True).IsValid():return True
        return False
    except Exception:return False


def _edge_result_quality(base,trial,strict,fast=False):
    """0 = unusable, 1 = valid solid, 2 = valid and clean (same body count, no overlaps)."""
    if not (_edge_trial_is_valid_fast(base,trial) if fast else _edge_trial_is_valid(trial)):return 0
    value=trial.val()
    if _solid_count(value)!=_solid_count(base.val()):return 1
    if not strict:return 2
    overlaps=_local_self_intersects(base,value) if _is_large(base) else _self_intersects(value)
    return 1 if overlaps else 2


# Last auto-fit outcome per feature id, for the UI to explain what was adjusted.
EDGE_REPORTS={}


def _plain_references(edges):
    """Geometry-only edge references that also match on intermediate results."""
    from references import shape_reference
    return [shape_reference(edge,'edge') for edge in edges]


def _healed(result):
    """The same body after tolerance repair and merging of coplanar seams, if that changes it."""
    try:
        shape=result.val();fixed=shape.fix().clean()
        from validity import shape_valid
        if fixed is None or fixed.isSame(shape) or not shape_valid(fixed):return None
        return cq.Workplane('XY').newObject([fixed])
    except Exception:return None


EDGE_MODES={'fillet':('constant','variable'),'chamfer':('equal','two_distance','distance_angle')}


def edge_options(feature):
    """Keyword options of ``apply_edge_operation`` described by a fillet/chamfer feature.

    ``ratio`` is the second chamfer distance (or the end radius of a variable fillet) relative to the
    first one, so a size search can scale both together. ``flip`` swaps the two chamfer faces.
    """
    kind=feature.get('kind');mode=feature.get('mode',EDGE_MODES[kind][0]) if kind in EDGE_MODES else None
    if mode is not None and mode not in EDGE_MODES[kind]:raise ModelError('Unknown '+kind+' mode.')
    size=positive(feature.get('radius',1.),'Size')
    if kind=='chamfer' and mode=='two_distance':
        return dict(ratio=positive(feature.get('distance2',size),'Second distance')/size,flip=bool(feature.get('flip',False)))
    if kind=='chamfer' and mode=='distance_angle':
        angle=number(feature.get('angle',45.),'Angle')
        if not 0<angle<90:raise ModelError('The chamfer angle must be between 0 and 90 degrees.')
        return dict(ratio=math.tan(math.radians(angle)),flip=bool(feature.get('flip',False)))
    if kind=='fillet' and mode=='variable':
        return dict(ratio=positive(feature.get('radius_end',size),'End radius')/size)
    return {}


def _variable_fillet(solid,edges,start,end):
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    maker=BRepFilletAPI_MakeFillet(solid.wrapped)
    for edge in edges:maker.Add(float(start),float(end),edge.wrapped)
    maker.Build()
    if not maker.IsDone():raise ModelError('The variable fillet cannot be built on these edges.')
    return cq.Shape.cast(maker.Shape())


def apply_edge_operation(result,picked,kind,size,quick=False,fit=False,report=None,ratio=None,flip=False):
    """Apply a solid fillet/chamfer and try hard to return a usable body.

    ``ratio`` makes the operation asymmetric: a second chamfer distance, or a fillet whose radius runs
    from ``size`` at the start of every edge to ``size * ratio`` at its end.

    Strategies, in order: all edges at once; all at once on a repaired copy
    (booleans often leave seams the kernel refuses); one edge at a time in
    different orders. Any valid solid is accepted; a clean one (same body count,
    no overlapping faces) is preferred when several strategies work.

    ``fit=True`` (auto-fit) never gives up on an oversized value: each edge gets
    the requested size where it fits and the largest size that works where it does
    not; edges that cannot take any size are skipped. Only when no edge can be
    changed at all is an error raised. ``report`` receives what was adjusted.
    """
    if kind not in ('fillet','chamfer'):raise ModelError('Unknown edge feature type.')
    operation='fillet' if kind=='fillet' else 'chamfer'
    size=float(size)
    # Python deletes an ``except ... as name`` binding when the handler ends, so
    # keep the failure in a separate variable for the final error message.
    failure=ModelError(f'{kind.title()} of {size:g} mm cannot be built on the selected edges. Try a smaller size or fewer edges.')
    strict=False
    if not quick:
        # Only prefer overlap-free results when the input itself passes the check.
        strict=getattr(result,'_slothcad_strict_ok',None)
        if strict is None:
            strict=True if _is_large(result) else not _self_intersects(result.val())
            try:result._slothcad_strict_ok=strict
            except AttributeError:pass
    fallback=[None]
    def attempt(base,edges,value=size,keep=True):
        """Return a clean candidate; remember the first merely valid one as a fallback."""
        # The kernel result is judged before CadQuery's clean-up merges faces: clean-up rebuilds
        # every face, which would hide which faces the operation really changed.
        try:
            solid=base.findSolid()
            if operation=='fillet':
                raw=solid.fillet(float(value),edges) if ratio is None else _variable_fillet(solid,edges,value,value*ratio)
            elif ratio is None:raw=solid.chamfer(float(value),None,edges)
            else:raw=solid.chamfer(float(value)*ratio,float(value),edges) if flip else solid.chamfer(float(value),float(value)*ratio,edges)
            raw_object=base.newObject([raw])
        except Exception as error:
            failure.__cause__=error;return None
        quality=_edge_result_quality(base,raw_object,strict,fast=quick)
        if quality==0:return None
        try:candidate=base.newObject([raw.clean()])
        except Exception:candidate=raw_object
        if candidate is not raw_object and not quick and not _edge_trial_is_valid(candidate):
            candidate=raw_object        # merging faces made it invalid: keep the unmerged result
        if quality==2:return candidate
        if quality==1 and keep and fallback[0] is None:fallback[0]=candidate
        return candidate if quality==1 and not keep else None
    candidate=attempt(result,picked)
    if candidate is not None:return candidate
    refs=_plain_references(picked)
    healed=None if quick else _healed(result)
    if healed is not None:
        try:candidate=attempt(healed,resolve_edges(healed,refs))
        except Exception:candidate=None
        if candidate is not None:return candidate
    if len(picked)>1:
        # Vertex picks commonly select three edges; exhaust their orderings so a
        # locally difficult corner does not make the complete feature unusable.
        # Size probing only needs a quick answer, so it tries two orders at most.
        orders=(tuple(refs),tuple(reversed(refs))) if quick or len(refs)>4 else itertools.permutations(refs)
        for order in orders:
            current=result
            for reference in order:
                try:edge=resolve_edges(current,[reference])[0]
                except Exception:current=None;break
                current=attempt(current,[edge],keep=False)
                if current is None:break
            if current is not None:return current
    if fallback[0] is not None:return fallback[0]
    if not fit or quick:raise failure
    # Auto-fit: edge by edge, shrinking only the edges that need it.
    current=result;reduced=[];skipped=[]
    for index,reference in enumerate(refs):
        try:edge=resolve_edges(current,[reference])[0]
        except Exception:skipped.append(index);continue
        candidate=attempt(current,[edge],keep=False)
        if candidate is not None:current=candidate;continue
        low,high,best=0.,size,None
        for _ in range(11):
            middle=(low+high)/2
            trial=attempt(current,[edge],middle,keep=False)
            if trial is not None:low,best=middle,trial
            else:high=middle
        if best is not None and low>max(1e-4,size*1e-3):current=best;reduced.append((index,low))
        else:skipped.append(index)
    if current is result:raise failure
    if report is not None:report.update(kind=kind,requested=size,reduced=reduced,skipped=skipped,total=len(refs))
    return current


def maximum_edge_size(result,kind,references,hint=1.0,progress=None,options=None):
    """Return ``(largest_working_size, bounded)`` for one edge selection.

    The value is measured by asking OpenCascade to perform the exact same fillet/
    chamfer operation used by a real feature.  All selected edges are tested
    together because their shared maximum can be smaller than the limit of any
    individual edge.  ``bounded`` is false only in the very unusual case where
    even a body-diagonal-sized operation still succeeds.
    """
    if result is None:raise ModelError('Create a body first.')
    if kind not in ('fillet','chamfer'):raise ModelError('Unknown edge feature type.')
    picked=resolve_edges(result,references)
    if not picked:raise ModelError('Select at least one edge.')
    shape=result.val();box=shape.BoundingBox()
    diagonal=math.sqrt(float(box.xlen)**2+float(box.ylen)**2+float(box.zlen)**2)
    cap=max(1e-6,diagonal*1.01)
    tiny=max(1e-7,cap*1e-8)
    tests=0;max_tests=32
    def report(text):
        if progress is not None:progress(min(tests,max_tests),max_tests,text)
    def works(size):
        nonlocal tests
        tests+=1;report(f'Checking {kind} limit · {size:g} mm')
        if not math.isfinite(size) or size<=0:return False
        try:
            trial=apply_edge_operation(result,picked,kind,float(size),quick=True,**(options or {}))
            return trial is not None and trial.val() is not None     # quick builds are validated as they are made
        except Exception:return False

    start=min(cap,max(tiny,float(hint) if math.isfinite(float(hint)) and float(hint)>0 else min(1.0,cap)))
    if works(start):
        low=start;high=min(cap,start*2.0)
        while high<cap and works(high):
            low=high;high=min(cap,high*2.0)
        if high==cap and works(high):
            report(f'{kind.title()} limit is at least {cap:g} mm')
            return float(cap),False
    else:
        high=start;low=start/2.0
        while low>tiny and not works(low):
            high=low;low/=2.0
        if low<=tiny and not works(max(low,tiny)):
            report(f'No valid {kind} size found')
            return 0.0,True
        low=max(low,tiny)

    # At this point low works and high fails.  Nine bisections narrow the bracket to
    # 0.2 %, finer than the arrow can be dragged; every extra trial is a full kernel build.
    for _ in range(9):
        mid=(low+high)/2.0
        if works(mid):low=mid
        else:high=mid
    report(f'Maximum {kind} size ≈ {low:g} mm')
    return float(low),True

def _emit_progress(progress,done,total,text):
    if progress is not None:
        progress(int(done),max(1,int(total)),str(text))

def build_state(features,progress=None,start_state=None,start_index=0,capture=None,history_prefix=None,parameters=None):
    """Build a feature history, optionally resuming from an unchanged cached prefix.

    ``progress`` is deliberately UI-agnostic; callers may relay it to a progress bar.
    ``capture`` receives the state after each feature so Document can reuse unchanged
    history instead of rebuilding the entire project after every late edit.
    ``parameters`` is the document's parameter table; without it the table already active for
    this thread (nested component builds, interface-side rebuilds) is used.
    """
    if parameters is None:
        return _build_state(features,progress,start_state,start_index,capture,history_prefix)
    from expressions import using_parameters
    with using_parameters(parameters):
        return _build_state(features,progress,start_state,start_index,capture,history_prefix)


def _build_state(features,progress=None,start_state=None,start_index=0,capture=None,history_prefix=None):
    if start_state is None:
        result=None; sketches={}; frames={}
    else:
        result=start_state[0];sketches=dict(start_state[1]);frames=dict(start_state[2])
    total=max(1,len(features)-start_index)
    if capture is not None and len(capture)>start_index:
        del capture[start_index:]
    for local_index in range(start_index,len(features)):
        i=local_index;f=features[i]
        _emit_progress(progress,i-start_index,total,f'Building feature {i+1} of {len(features)} · {f.get("name","Unnamed")}')
        if not f.get('enabled',True):
            if capture is not None:capture.append((result,dict(sketches),dict(frames)))
            continue
        try:
            previous_result=result
            from expressions import apply_feature_expressions
            apply_feature_expressions(f)
            from references import enrich_feature,body_reference
            from body_tools import BODY_TOOLS,body_operation
            if result is not None:
                enrich_feature(f,result)
                if f.get('kind') in ('shell','draft') and 'body_ref' not in f:
                    bodies=result.val().Solids();index=f.get('body',0)
                    if isinstance(index,int) and 0<=index<len(bodies):f['body_ref']=body_reference(bodies[index],index,len(bodies),result)
            kind=f['kind']
            from solid_tools import CONSTRUCTIONS,SOLID_TOOLS,construction,plane_reference,extrude,solid_operation
            if kind in __import__('assemblies').ASSEMBLY_TOOLS:
                result,frames=__import__('assemblies').operation(f,result,frames,progress)
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind in __import__('surface_tools').SURFACE_TOOLS:
                from surface_tools import operation as surface_operation
                surface_solid,frames=surface_operation(f,result,sketches,frames)
                if surface_solid is not None:
                    result=cq.Workplane('XY').newObject([cq.Compound.makeCompound(list(result.val().Solids())+list(surface_solid.Solids())) if result is not None else surface_solid]);__import__('topology').register(previous_result,result,f)
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind in CONSTRUCTIONS:
                if f['id'] in frames:raise ModelError('Duplicate construction ID.')
                frames[f['id']]=construction(f,result,sketches,frames)
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind in __import__('spatial_sketch').SPATIAL_TOOLS:
                if f['id'] in frames:raise ModelError('Duplicate sketch identity.')
                frame=__import__('spatial_sketch').materialize(f,result,frames);sketches[f['id']]=f;frames[f['id']]=frame
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind=='sketch':
                if f['id'] in frames: raise ModelError('Duplicate sketch or construction ID.')
                frame=plane_reference(f['plane_ref'],result,frames) if f.get('plane_ref') else sketch_frame(f,result)
                if len({e['id'] for e in f['entities']})!=len(f['entities']):raise ModelError('Duplicate sketch entity ID.')
                from projection import resolve as resolve_projection
                projected=resolve_projection(f,result,sketches,frames,frame)
                projection_changed=projected['entities']!=f['entities'] or projected.get('constraints',[])!=f.get('constraints',[])
                f.update(entities=projected['entities'],constraints=projected.get('constraints',[]))
                from constraints import validate_constraints,resolve_dimensions,solve
                resolved=resolve_dimensions(f)
                if projection_changed or resolved.get("constraints")!=f.get("constraints"):resolved=solve(resolved);f.update(entities=resolved["entities"],constraints=resolved.get("constraints",[]))
                validate_constraints(f)
                regions(f)  # Validate open geometry too, without requiring a solid.
                sketches[f['id']]=f; frames[f['id']]=frame
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind=='sketch_move':
                sketch_id=f.get('sketch')
                if sketch_id not in sketches:raise ModelError('The sketch to move is missing, suppressed or later in history.')
                offset=np.asarray([number(f.get(k,0),k.upper()) for k in ('dx','dy','dz')])
                if sketches[sketch_id]['kind']=='surface_sketch':raise ModelError('A surface sketch follows its supporting face. Move the supporting body instead.')
                frame=dict(frames[sketch_id]);
                if frame.get('spatial'):frame['edges']={key:edge.translate(tuple(offset)) for key,edge in frame['edges'].items()}
                frame['origin']=(np.asarray(frame['origin'])+offset).tolist()
                frames[sketch_id]=frame
                if capture is not None:capture.append((result,dict(sketches),dict(frames)))
                continue
            if kind=='import_solid':
                from exchange import imported_shape
                imported=imported_shape(f);existing=result.val().Solids() if result else []
                result=cq.Workplane('XY').newObject([cq.Compound.makeCompound(existing+imported.Solids())]);tool=None
            elif kind=='extrude' and 'source' not in f and 'sources' not in f:
                tool=profile_solid(f);solids=tool.vals()
            elif kind=='extrude':
                # Through-all measures only the bodies the extrusion may change (not hidden ones).
                visible=_participating(result,f.get('exclude_bodies'))[0] if f.get('extent')=='through all' and f.get('operation')!='new' else result
                solids=[extrude(source,f,result,sketches,frames,bounds_of=visible) for source in extrusion_sources(f)]
                tool=cq.Workplane('XY').newObject([solids[0] if len(solids)==1 else cq.Compound.makeCompound(solids)])
            elif kind in BODY_TOOLS:
                shape=body_operation(f,result,sketches,frames);result=cq.Workplane('XY').newObject([shape]);tool=None
            elif kind in SOLID_TOOLS:
                shape,replaces=solid_operation(f,result,sketches,frames)
                if replaces:
                    result=cq.Workplane('XY').newObject([shape]);tool=None
                else:
                    solids=shape.Solids();tool=cq.Workplane('XY').newObject([shape])
            elif kind in __import__('special_solids').SPECIAL_TOOLS:
                from special_solids import operation as special_operation
                result=cq.Workplane('XY').newObject([special_operation(f,result,sketches,frames)]);tool=None
            elif kind in __import__('advanced_patterns').PATTERN_TOOLS:
                from advanced_patterns import operation as pattern_operation
                shape=pattern_operation(f,result,sketches,frames,(history_prefix or [])+features[:i]);result=cq.Workplane('XY').newObject([shape]);tool=None
            elif kind in __import__('face_tools').FACE_TOOLS:
                from face_tools import operation as face_operation
                shape=face_operation(f,result,sketches,frames);result=cq.Workplane('XY').newObject([shape]);tool=None
            elif kind in ('fillet','chamfer'):
                if result is None: raise ModelError('Create a body first.')
                size=positive(f['radius'],'Size')
                if 'edge_refs' in f:
                    picked=resolve_edges(result,f['edge_refs'])
                    if not picked:raise ModelError('Select at least one edge.')
                    edges=result.newObject(picked)
                else:
                    selectors={'all':None,'vertical':'|Z','top':'>Z','bottom':'<Z'}
                    key=f.get('edges','vertical')
                    if key not in selectors: raise ModelError('Unknown edge selection.')
                    edges=result.edges(selectors[key]) if selectors[key] else result.edges()
                    if not edges.size(): raise ModelError('No edges match this selection.')
                    picked=edges.vals()
                report={};EDGE_REPORTS.pop(f.get('id'),None)
                result=apply_edge_operation(result,picked,kind,size,fit=bool(f.get('auto_fit',False)),report=report,**edge_options(f))
                if report:EDGE_REPORTS[f.get('id')]=report
                tool=None
            else: raise ModelError('Unknown feature type.')
            if tool is not None:
                operation='cut' if kind=='hole' else f.get('operation','add')
                # Preserve version-3 files where signed negative depth implicitly meant Cut.
                # New UI-created extrusions set signed_depth=False and choose operation explicitly.
                if f.get('signed_depth',False) and number(f['depth'],'Depth')<0:operation='cut'
                if operation not in ('add','cut','intersect','new'): raise ModelError('Unknown operation.')
                if operation=='new':
                    # New body: the tool is kept as separate bodies; nothing existing is touched.
                    result=_with_bodies(result,list(tool.val().Solids()))
                else:
                    had_bodies=result is not None
                    # Bodies hidden when the feature was made take no part in it.
                    result,kept=_participating(result,f.get('exclude_bodies'))
                    if result is None:
                        if operation!='add':
                            if had_bodies:raise ModelError('Every body this feature could change is hidden. Show the body, or choose New body.')
                            raise ModelError('A negative extrusion needs an existing body.' if f.get('signed_depth') and f['depth']<0 else 'The first solid feature must add material.')
                        result=tool
                    elif operation=='add': result=_body_boolean(result,tool,solids,operation)
                    elif operation=='cut':
                        if f.get('signed_depth',False) and result.intersect(tool).val().Volume()<=1e-9:
                            raise ModelError('The cut does not intersect a body. Check its direction, start offset and depth.')
                        result=_body_boolean(result,tool,solids,operation)
                    else: result=_body_boolean(result,tool,solids,operation)
                    if result is not None and result.val() is not None:result=_with_bodies(result,kept)
                if result is None or result.val() is None or not _edge_trial_is_valid(result):
                    raise ModelError('The extrusion operation did not produce a valid solid. Check its direction, overlap and selected profiles.')
            from topology import register
            register(previous_result,result,f,(sketches,frames))
            shape=result.val()
            if not _edge_trial_is_valid(result):
                raise ModelError('Operation produced an empty or invalid solid.')
        except Exception as e:
            error=ModelError(f'Feature {i+1} ({f.get("name","Unnamed")}): {e}');error.feature_index=i
            raise error from e
        if capture is not None:capture.append((result,dict(sketches),dict(frames)))
    _emit_progress(progress,total,total,'Model rebuild complete')
    return result,sketches,frames

def rebuild(features): return build_state(features)[0]

def _file_mode(path):
    """Permissions for an atomically replaced file: keep existing, else umask default."""
    try:return os.stat(path).st_mode & 0o7777
    except OSError:
        mask=os.umask(0);os.umask(mask)
        return 0o666 & ~mask

def _compact_states(states,tail=12,interval=10):
    """Keep recent history exact and sparse older checkpoints to avoid retaining every BRep."""
    n=len(states);cut=max(0,n-tail);out=[]
    for i,state in enumerate(states):
        out.append(state if i>=cut or (i+1)%interval==0 else None)
    return out

class Document:
    def __init__(self, features=None, progress=None, tolerant=False, parameters=None):
        """Build a document.

        With ``tolerant=True`` a feature that fails to rebuild does not prevent
        opening: the model is shown up to the last working feature, the full
        history is kept, and ``build_error`` describes the failure so the user can
        edit, suppress or repair it (as Fusion does with a red timeline item).
        """
        self.pending_features=None;self.pending_error=None;self.build_error=None
        self.parameters=self.checked_parameters(parameters)
        self._saved_parameters=copy.deepcopy(self.parameters)
        self.features = copy.deepcopy(features or [])
        self.display = {}
        self.revision=0
        self._states=[]
        # Guards the (features, states, solid, ...) snapshot that background previews read.
        self._lock=threading.RLock();self._preview_memo=OrderedDict()
        try:
            self.solid, self.sketches, self.frames = build_state(self.features,progress=progress,capture=self._states,parameters=self.parameters)
        except ModelError as error:
            index=getattr(error,'feature_index',None)
            if not tolerant or index is None:raise
            # The capture already holds the state after every feature before the failure.
            self.build_error=error;del self._states[index:]
            self.solid,self.sketches,self.frames=self._states[-1] if self._states else (None,{},{})
            self.sketches,self.frames=dict(self.sketches),dict(self.frames)
        self._states=_compact_states(self._states)
        self.undo_stack = []
        self.redo_stack = []
        self._undo_parameters=[];self._redo_parameters=[]

    @staticmethod
    def checked_parameters(parameters):
        """A validated copy of a parameter table: names are identifiers, values numbers or expressions."""
        if parameters is None:return {}
        if not isinstance(parameters,dict):raise ModelError('Document parameters must be a table of names and expressions.')
        from expressions import resolve
        table={}
        for name,value in parameters.items():
            if isinstance(value,bool) or not isinstance(value,(int,float,str)):raise ModelError('Parameter values must be numbers or expressions.')
            table[str(name)]=value
        resolve(table)           # raises for bad names, unknown references and cycles
        return table

    def parameters_dirty(self):
        return self.parameters!=self._saved_parameters

    def _rebuild_candidate(self,candidate,progress=None,parameters=None):
        # Only the unchanged prefix of the history is reused: the nearest stored state before
        # the first changed feature is the starting point (later features are rebuilt).
        parameters=self.parameters if parameters is None else parameters
        with self._lock:
            current=self.features;stored=list(self._states)
            prefix=0;limit=min(len(candidate),len(current))
            # A changed parameter can change any feature that uses it: nothing is reused then.
            if parameters==self.parameters:
                while prefix<limit and candidate[prefix]==current[prefix]:prefix+=1
        checkpoint=min(prefix-1,len(stored)-1);start_state=None
        while checkpoint>=0:
            if stored[checkpoint] is not None:
                start_state=stored[checkpoint];break
            checkpoint-=1
        start_index=checkpoint+1 if start_state is not None else 0
        states=list(stored[:start_index]) if start_index else []
        solid,sketches,frames=build_state(candidate,progress=progress,start_state=start_state,start_index=start_index,capture=states,parameters=parameters)
        return solid,sketches,frames,_compact_states(states)

    PREVIEW_MEMO=6

    @staticmethod
    def _fingerprint(value):
        """The value with long strings (embedded B-reps) replaced by their digest, for cache keys."""
        if isinstance(value,str):
            return value if len(value)<256 else 'sha:'+hashlib.blake2b(value.encode('utf-8','replace'),digest_size=16).hexdigest()
        if isinstance(value,dict):return {k:Document._fingerprint(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [Document._fingerprint(v) for v in value]
        return value

    def preview(self,features,progress=None,parameters=None):
        """The result of ``features`` without changing the document.

        The last few previews are remembered: dragging a value back over a size it already
        passed, or asking the same question twice (overlap probe, size limits), is free.
        """
        candidate=copy.deepcopy(features)
        table=self.parameters if parameters is None else self.checked_parameters(parameters)
        with self._lock:
            if candidate==self.features and table==self.parameters:return self.solid,self.sketches,self.frames
        try:key=json.dumps([self._fingerprint(candidate),table],sort_keys=True,default=str)
        except (TypeError,ValueError):key=None
        if key is not None:
            with self._lock:
                hit=self._preview_memo.get(key)
                if hit is not None:self._preview_memo.move_to_end(key);return hit
        solid,sketches,frames,_=self._rebuild_candidate(candidate,progress,table)
        if key is not None:
            with self._lock:
                self._preview_memo[key]=(solid,sketches,frames)
                while len(self._preview_memo)>self.PREVIEW_MEMO:self._preview_memo.popitem(last=False)
        return solid,sketches,frames

    def commit(self, features, progress=None, parameters=None):
        candidate = copy.deepcopy(features)
        table=self.parameters if parameters is None else self.checked_parameters(parameters)
        if candidate == self.features and table==self.parameters:
            self.pending_features=None;self.pending_error=None
            return False
        try:solid, sketches, frames, states = self._rebuild_candidate(candidate,progress,table)
        except Exception as error:
            self.pending_features=candidate;self.pending_error=error
            raise
        self.pending_features=None;self.pending_error=None
        self.undo_stack.append(copy.deepcopy(self.features));self._undo_parameters.append(copy.deepcopy(self.parameters))
        del self.undo_stack[:-100];del self._undo_parameters[:-100]
        self.redo_stack.clear();self._redo_parameters.clear()
        from body_preferences import remap
        self.display = remap(self.solid, solid, self.display)
        with self._lock:
            self.features, self.solid = candidate, solid
            self.parameters=table
            self.sketches, self.frames, self._states = sketches, frames, states
            self._preview_memo.clear()
        self.revision+=1;self.build_error=None
        return True

    def set_parameters(self,parameters,progress=None):
        """Replace the parameter table and rebuild; one undo step like any other edit."""
        return self.commit(self.features,progress,parameters)

    def dependencies(self):
        from feature_history import graph
        return graph(self.features)

    def reorder(self,index,destination,progress=None):
        from feature_history import reordered
        return self.commit(reordered(self.features,index,destination),progress)

    def suppress(self,index,enabled=False,cascade=False,progress=None):
        from feature_history import suppression
        return self.commit(suppression(self.features,index,enabled,cascade),progress)

    def inspect_history(self,features=None,progress=None):
        from references import inspect_slots
        candidate=copy.deepcopy(self.features if features is None else features);state=(None,{},{});report=[];blocked=False
        for i,feature in enumerate(candidate):
            if progress:progress(i,len(candidate),'Inspecting downstream references…')
            row=dict(index=i,name=feature.get('name','Unnamed'),references=[],state='blocked' if blocked else 'valid' if feature.get('enabled',True) else 'suppressed',message='')
            if not blocked and feature.get('enabled',True):
                row['references']=inspect_slots(feature,state[0],state[2])
                try:
                    state=build_state([feature],start_state=state,history_prefix=candidate[:i],parameters=self.parameters)
                    if any(r['state']=='recovered' for r in row['references']):row['state']='recovered'
                except Exception as error:
                    message=str(error)
                    if message.startswith('Feature 1 '):message='Feature '+str(i+1)+message[len('Feature 1'):]
                    row.update(state='needs repair',message=message);blocked=True
            report.append(row)
        return report

    def undo(self,progress=None):
        if not self.undo_stack: return False
        previous = self.undo_stack[-1]
        table=copy.deepcopy(self._undo_parameters[-1]) if len(self._undo_parameters)==len(self.undo_stack) else copy.deepcopy(self.parameters)
        solid, sketches, frames, states = self._rebuild_candidate(previous,progress,table)
        self.redo_stack.append(copy.deepcopy(self.features));self._redo_parameters.append(copy.deepcopy(self.parameters))
        self.undo_stack.pop()
        if self._undo_parameters:self._undo_parameters.pop()
        from body_preferences import remap
        self.display = remap(self.solid, solid, self.display)
        with self._lock:
            self.features, self.solid = previous, solid
            self.parameters=table
            self.sketches, self.frames, self._states = sketches, frames, states
            self._preview_memo.clear()
        self.pending_features=None;self.pending_error=None
        self.revision+=1;self.build_error=None
        return True

    def redo(self,progress=None):
        if not self.redo_stack: return False
        following = self.redo_stack[-1]
        table=copy.deepcopy(self._redo_parameters[-1]) if len(self._redo_parameters)==len(self.redo_stack) else copy.deepcopy(self.parameters)
        solid, sketches, frames, states = self._rebuild_candidate(following,progress,table)
        self.undo_stack.append(copy.deepcopy(self.features));self._undo_parameters.append(copy.deepcopy(self.parameters))
        self.redo_stack.pop()
        if self._redo_parameters:self._redo_parameters.pop()
        from body_preferences import remap
        self.display = remap(self.solid, solid, self.display)
        with self._lock:
            self.features, self.solid = following, solid
            self.parameters=table
            self.sketches, self.frames, self._states = sketches, frames, states
            self._preview_memo.clear()
        self.pending_features=None;self.pending_error=None
        self.revision+=1;self.build_error=None
        return True

    def save(self, path, backup=True):
        """Write the project atomically. The previous file is kept next to it as ``<name>.fcad.bak``."""
        path = Path(path)
        # Retain the existing on-disk identifier so saved projects remain compatible.
        document = dict(format='slothcad', version=SCHEMA, units='mm')
        if self.parameters:document['parameters']=self.parameters
        document.update(features=self.features, display=self.display)
        payload = json.dumps(document, indent=2, allow_nan=False)
        fd, temp = tempfile.mkstemp(prefix='.slothcad-', dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # mkstemp creates owner-only (0600) files; keep the existing file's
            # permissions, or use the normal default for a new project.
            set_mode(temp,_file_mode(path))
            if backup and path.exists():
                try:shutil.copy2(path,path.with_name(path.name+'.bak'))
                except OSError:pass          # a read-only folder must not stop the save itself
            replace_file(temp,path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        self._saved_parameters=copy.deepcopy(self.parameters)

    @classmethod
    def load(cls, path, progress=None):
        with open(path,encoding='utf-8') as stream: data = json.load(stream)
        if data.get('format') not in ('slothcad','forgecad') or data.get('version') not in (1, 2, 3, 4, 5, 6, 7, 8, 9, SCHEMA):
            raise ModelError('Unsupported project format or version.')
        if data.get('units') != 'mm' or not isinstance(data.get('features'),list):
            raise ModelError('Invalid project data.')
        display=data.get('display',{})
        if not isinstance(display,dict):raise ModelError('Invalid display preferences.')
        for key in ('bodies','sketches','construction','surfaces'):
            values=display.get(key,{})
            if not isinstance(values,dict) or any(not isinstance(k,str) or not isinstance(v,bool) for k,v in values.items()):raise ModelError('Invalid visibility preferences.')
        for key in ('grid','axes','aa','perspective'):
            if key in display and not isinstance(display[key],bool):raise ModelError('Invalid viewport preferences.')
        views=display.get('views',{})
        if not isinstance(views,dict) or any(not isinstance(k,str) or not isinstance(v,dict) for k,v in views.items()):raise ModelError('Invalid saved views.')
        def valid_material(value):
            opacity=value.get('opacity',1.) if isinstance(value,dict) else 1.
            return (isinstance(value,dict) and isinstance(value.get('color','#4baed6'),str) and value.get('finish','matte') in ('matte','metallic','wood')
                    and isinstance(opacity,(int,float)) and not isinstance(opacity,bool) and 0<opacity<=1)
        if 'default_material' in display and not valid_material(display['default_material']):raise ModelError('Invalid default body appearance.')
        materials=display.get('materials',{})
        if not isinstance(materials,dict) or any(not isinstance(k,str) or not valid_material(v) for k,v in materials.items()):raise ModelError('Invalid body appearances.')
        parameters=data.get('parameters',{})
        if not isinstance(parameters,dict):raise ModelError('Invalid document parameters.')
        doc=cls(data['features'],progress=progress,tolerant=True,parameters=parameters)
        doc.display=display
        return doc

    # ---- bodies, export and analysis ---------------------------------------------------------
    def solids(self):
        """Every solid of the model in display order (the order the body visibility refers to)."""
        return list(self.solid.val().Solids()) if self.solid is not None else []

    def body_names(self):
        """A name per solid: the owning component's name, else ``Body n``."""
        from topology import entries
        registry=self.frames.get('_components',{}) if isinstance(self.frames,dict) else {}
        owner={key:component.get('name','Component') for component in registry.values() for key in component.get('members',[])}
        records=entries(self.solid);names=[]
        for index,body in enumerate(self.solids()):
            record=next((r for r in records if r['shape'].isSame(body)),None)
            names.append(owner.get(record['id']) if record and record['id'] in owner else f'Body {index+1}')
        return names

    def body_color(self,index):
        """``(r, g, b)`` in 0..1 of a body's appearance."""
        default=self.display.get('default_material',{}) if isinstance(self.display,dict) else {}
        material=(self.display.get('materials',{}) if isinstance(self.display,dict) else {}).get(str(index),default)
        text=material.get('color','#4baed6') if isinstance(material,dict) else '#4baed6'
        try:
            text=text.lstrip('#');return tuple(int(text[i:i+2],16)/255. for i in (0,2,4))
        except (ValueError,IndexError):
            return (75/255.,174/255.,214/255.)

    def export_items(self,visible_only=False):
        """``[(name, shape, (r, g, b))]`` of what an export contains: solids, then open surfaces."""
        if self.solid is None and not (isinstance(self.frames,dict) and self.frames.get('_surfaces')):
            raise ModelError('Create geometry before exporting.')
        visibility=self.display.get('bodies',{}) if isinstance(self.display,dict) else {}
        items=[]
        for index,(name,body) in enumerate(zip(self.body_names(),self.solids())):
            if visible_only and not visibility.get(str(index),True):continue
            items.append((name,body,self.body_color(index)))
        surfaces=self.frames.get('_surfaces',{}) if isinstance(self.frames,dict) else {}
        shown=self.display.get('surfaces',{}) if isinstance(self.display,dict) else {}
        for id_,body in surfaces.items():
            if visible_only and not shown.get(id_,True):continue
            items.append((body.get('name','Surface'),body['shape'],(.75,.75,.8)))
        if not items:raise ModelError('There is nothing visible to export.')
        return items

    def export(self, path, visible_only=False, tolerance=0.05, angular_tolerance=0.1, colors=True):
        """Export to STEP (with names and colours), STL or 3MF.

        ``visible_only`` leaves out bodies and surfaces hidden in the browser. ``tolerance`` (mm) and
        ``angular_tolerance`` (radians) control the mesh of STL and 3MF files.
        """
        from exchange import export_items_file, export_kind
        export_kind(path, tolerance, angular_tolerance)
        export_items_file(self.export_items(visible_only), path, tolerance, angular_tolerance, colors)

    def mass_properties(self, density=1.0, visible_only=False):
        """Volume, area, mass, centre of mass and inertia of the solids (density in g/cm³)."""
        from analysis import mass_properties
        chosen=self.chosen_bodies(visible_only)
        result=mass_properties([body for _,body in chosen],density)
        result['names']=[name for name,_ in chosen]
        return result

    def chosen_bodies(self, visible_only=False):
        """``[(name, solid)]`` of every body, or only those shown in the browser."""
        visibility=self.display.get('bodies',{}) if isinstance(self.display,dict) else {}
        return [(name,body) for i,(name,body) in enumerate(zip(self.body_names(),self.solids())) if not visible_only or visibility.get(str(i),True)]

    def interferences(self):
        """Overlapping pairs of bodies as ``[(name_a, name_b, volume)]``."""
        from analysis import interferences
        return interferences(list(zip(self.body_names(),self.solids())))

    def bill_of_materials(self):
        from analysis import bill_of_materials
        return bill_of_materials(list(zip(self.body_names(),self.solids())),None)
