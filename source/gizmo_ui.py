"""Bind viewport manipulators to transactional feature parameters."""
import copy
import json
import math
import numpy as np
from PySide6.QtWidgets import QComboBox
from geometry import axes, sample, identifier, world
from model import ModelError,extrusion_sources
from i18n import tr

def toward_zero(value,places=4):
    """Round magnitude down so a limit survives being written into a 4-decimal field."""
    if value is None:return None
    scale=10.**places
    return math.floor(abs(value)*scale)/scale*(1 if value>=0 else -1)


class GizmoUI:
    def feature_insert_index(self,feature):
        if feature.get('kind')!='sketch_move':return len(self.doc.features)
        sketch_id=feature.get('sketch');matches=[i for i,f in enumerate(self.doc.features)
            if f.get('id')==sketch_id or f.get('kind')=='sketch_move' and f.get('sketch')==sketch_id]
        return max(matches)+1 if matches else len(self.doc.features)

    def start_sketch_move(self):
        sketch_id=None
        if self.workspace.mode=='sketch':
            sketch_id=self.draft['id']
            if not self.finish_sketch():return
        elif self.selected is not None and self.doc.features[self.selected]['kind']=='sketch':
            sketch_id=self.doc.features[self.selected]['id']
        if not self.doc.sketches:self.show_status(tr('Create a sketch first.'));return
        if not self.abandon():return
        self.draft_index=None;self.selected=None
        self.draft=dict(id=identifier(),kind='sketch_move',name=tr('Move sketch'),enabled=True,
                        sketch=sketch_id or next(reversed(self.doc.sketches)),dx=0.,dy=0.,dz=0.)
        self.workspace.set_mode('model');self.show_editor()

    def sketch_move_editor(self):
        f=self.draft;self.feature_action_row(f);form=self.form('Move sketch');self.name_field(form,f)
        _,sketches,_=self.tool_context();combo=QComboBox()
        if self.draft_index is None:sketches=self.doc.sketches
        for id_,s in sketches.items():combo.addItem(s['name'],id_)
        combo.setCurrentIndex(combo.findData(f.get('sketch')))
        combo.currentIndexChanged.connect(lambda i:self.parameter_changed(lambda value:f.update(sketch=value),combo.itemData(i)))
        form.addRow(tr('Sketch'),combo);self.widgets['move_sketch']=combo
        for key,label in [('dx','Translation X'),('dy','Translation Y'),('dz','Translation Z')]:
            self.spin(form,key,label,f.get(key,0),lambda v,k=key:f.update({k:v}))
        self.note('Drag the X/Y/Z handles or type exact distances. Tab switches axes. Moving a sketch updates its downstream features. Dashed lines are drag guides; Preview builds the exact result. Apply keeps the change.')

    # Tools with one draggable size arrow: kind -> (field, label, minimum, sign).
    # ``sign`` maps the arrow's value to the field: a shell's arrow points into the
    # body, so dragging inward makes the (negative = inward) thickness larger.
    VALUE_HANDLES={'fillet':('radius','Radius',.01,1),'chamfer':('radius','Distance',.01,1),'shell':('thickness','Thickness',None,-1),
                   'offset_face':('distance','Distance',None,1),'press_pull':('distance','Distance',None,1),
                   'construction_plane':('offset','Offset',None,1),'hole':('depth','Depth',.01,1)}

    def value_handle_spec(self,f):
        """The arrow for a one-value tool, or None when it does not apply right now."""
        spec=self.VALUE_HANDLES.get(f['kind'])
        if spec is None:return None
        if f['kind']=='construction_plane' and f.get('mode','offset')!='offset':return None
        if f['kind']=='hole' and f.get('through_all'):return None
        if f['kind'] in ('fillet','chamfer') and not f.get('edge_refs'):return None
        if f['kind'] in ('shell','offset_face') and not f.get('faces'):return None
        if f['kind']=='press_pull' and not (f.get('source') if f.get('press_type')=='profile' else f.get('faces')):return None
        return spec

    def value_handle_geometry(self,f,result,sketches,frames):
        """(origin, direction, live preview) for a value arrow, placed where the value acts."""
        import handle_previews as H
        import cadquery as cq
        def polyline(edge,count=None):
            count=count or (2 if edge.geomType()=='LINE' else 40)
            return np.array([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,count)])
        def outline(face):return H.chain_loop([polyline(edge) for edge in face.outerWire().Edges()])
        def body_of(shape,kind):
            for body in result.val().Solids():
                if any(shape.isSame(item) for item in (body.Edges() if kind=='edge' else body.Faces())):return body
            return result.val()
        kind=f['kind']
        if kind in ('fillet','chamfer'):
            from model import resolve_edges
            edges=resolve_edges(result,f['edge_refs'])
            if not edges:return None
            box=result.val().BoundingBox();eps=max(1e-4,(box.xlen+box.ylen+box.zlen)*1e-4);convexity={}
            curvature_step=eps*10
            def sample(edge,body,faces,t):
                point=np.asarray(edge.positionAt(float(t)).toTuple());tangent=np.asarray(edge.tangentAt(float(t)).toTuple())
                n1=np.asarray(faces[0].normalAt(cq.Vector(*point)).toTuple());n2=np.asarray(faces[1].normalAt(cq.Vector(*point)).toTuple())
                outward=n1+n2;outward=outward/np.linalg.norm(outward) if np.linalg.norm(outward)>1e-9 else n1
                # Concave (inside) corners have material on one side of the diagonal across
                # the faces; convex edges have none on either side.
                # Point-in-solid tests cost up to a tenth of a second each on a large body, so an edge
                # is classified once (at the first station asked about) and the answer reused.
                convex=convexity.get(edge.hashCode())
                if convex is None:
                    try:convex=not any(bool(body.isInside(cq.Vector(*(point+(a-b)*eps)))) for a,b in ((n1,n2),(n2,n1)))
                    except Exception:convex=True
                    convexity[edge.hashCode()]=convex
                normal_at=lambda i,q:np.asarray(faces[i].normalAt(cq.Vector(*q)).toTuple())
                return H.edge_station(point,tangent,n1,n2,convex,normal_at,curvature_step),point,(-outward if convex else outward)
            stations_per_edge=[];arrow=None;nearest=None
            pick=getattr(self,'edge_pick_point',None)
            def face_key(face):return tuple(round(float(c),4) for c in face.Center().toTuple())
            owners={}
            def faces_of(edge,body):
                """The faces that share ``edge``: one pass over the body's faces (cached per body)
                instead of testing every face against every picked edge."""
                key=body.hashCode()
                if key not in owners:
                    index={}
                    for face in body.Faces():
                        for e in face.Edges():index.setdefault(e.hashCode(),[]).append(face)
                    owners[key]=index
                return [face for face in owners[key].get(edge.hashCode(),()) if any(edge.isSame(e) for e in face.Edges())]
            for edge in edges:
                body=body_of(edge,'edge');faces=faces_of(edge,body)
                if len(faces)<2:continue
                count=2 if edge.geomType()=='LINE' else 13
                vertex=lambda t,edge=edge:tuple(round(float(c),5) for c in edge.positionAt(t).toTuple())
                stations_per_edge.append(dict(stations=[sample(edge,body,faces,t)[0] for t in np.linspace(0,1,count)],
                                              faces=(face_key(faces[0]),face_key(faces[1])),vertices=(vertex(0.),vertex(1.)),
                                              straight=edge.geomType()=='LINE'))
                # The arrow starts at the point that was picked (or the middle of the first edge when
                # there is none) and points toward the centre of the rounding: into the material at
                # a convex edge, into the open corner at a concave one.
                if pick is not None:
                    ts=np.linspace(0,1,41)
                    gaps=np.linalg.norm(np.array([edge.positionAt(float(t)).toTuple() for t in ts])-pick,axis=1)
                    i=int(np.argmin(gaps))
                    if nearest is None or gaps[i]<nearest[0]:nearest=(float(gaps[i]),edge,body,faces,float(ts[i]))
                elif arrow is None:_,point,outward=sample(edge,body,faces,.5);arrow=(point,outward)
            if nearest is not None:
                _,edge,body,faces,t=nearest;_,point,outward=sample(edge,body,faces,t);arrow=(point,outward)
            if arrow is None:return None
            ghost=H.edge_ghost(stations_per_edge,chamfer=kind=='chamfer')
            edge_lines=[polyline(edge) for edge in edges]
            return arrow[0],arrow[1],lambda value:edge_lines+ghost(value)
        if kind=='construction_plane':
            from solid_tools import plane_reference
            o,u,v,n=axes(plane_reference(f.get('reference',{'type':'origin','plane':'XY'}),result,frames))
            size=10.
            if result is not None:
                box=result.val().BoundingBox();size=max(10.,.35*max(box.xlen,box.ylen,box.zlen))
            return o,n,H.plane_ghost(o,u,v,n,size)
        if kind=='hole':
            from solid_tools import plane_reference
            plane=f.get('plane');plane=dict(plane,origin=None) if isinstance(plane,dict) else plane
            o,u,v,n=axes(plane_reference(plane,result,frames));origin=o+u*float(f.get('x',0))+v*float(f.get('y',0))
            direction=-n if f.get('direction','inward')=='inward' else n
            return origin,direction,H.hole_ghost(origin,u,v,direction,f.get('diameter',5),f.get('hole_type','simple'),f.get('head_diameter',10),f.get('head_depth',3),f.get('head_angle',90))
        if kind=='press_pull' and f.get('press_type')=='profile':
            from solid_tools import profile
            outer,inner,frame=profile(f['source'],result,sketches,frames);o,u,v,n=axes(frame)
            loops=[H.chain_loop([polyline(edge,48) for edge in wire.Edges()]) for wire in [outer]+inner]
            return np.asarray(outer.Center().toTuple()),n,H.prism_ghost(loops,n)
        from references import match_shape
        face,_=match_shape(result,f['faces'][0],'face')
        center=np.asarray(face.Center().toTuple());normal=np.asarray(face.normalAt().toTuple())
        # Start the arrow at the clicked point on whichever selected face contains it.
        clicked=getattr(self.workspace,'last_face_pick',None);start=center
        if clicked is not None:
            for reference in f['faces']:
                try:candidate=match_shape(result,reference,'face')[0]
                except Exception:continue
                c=np.asarray(candidate.Center().toTuple());n=np.asarray(candidate.normalAt().toTuple())
                if abs(float((clicked-c)@n))<=1e-3*max(1.,float(np.linalg.norm(c))):
                    face,center,normal=candidate,c,n;start=np.asarray(clicked,float)-n*float((clicked-c)@n);break
        if kind=='shell':
            # Arrow on the opened face, pointing into the body: the wall grows inward.
            body=body_of(face,'face');box=body.BoundingBox()
            corners=np.asarray([[x,y,z] for x in (box.xmin,box.xmax) for y in (box.ymin,box.ymax) for z in (box.zmin,box.zmax)])
            depth=max(0.,-float(np.min((corners-center)@normal)))
            return start,-normal,H.shell_ghost(outline(face),center,normal,depth)
        loops=[outline(match_shape(result,ref,'face')[0]) for ref in f['faces']]
        return start,normal,H.prism_ghost(loops,normal)

    def history_with(self,draft):
        """The history up to and including ``draft`` (the feature as Apply would insert it)."""
        features=copy.deepcopy(self.doc.features)
        if self.draft_index is None:
            position=self.feature_insert_index(draft);features.insert(position,draft)
        else:
            position=self.draft_index;features[position]=draft
        return features[:position+1]

    def value_limits(self,f,spec):
        """(lowest, highest) arrow value the tool can really build; None means unbounded."""
        key,label,minimum,sign=spec;kind=f['kind']
        if kind in ('fillet','chamfer'):
            self.calculate_edge_size_limit()
            limit=getattr(self,'edge_size_limit',None)
            hi=None
            if limit is not None and getattr(self,'edge_size_limit_bounded',True):hi=max(float(minimum or 0.),toward_zero(float(limit)*.995))
            return minimum,hi
        if kind in ('shell','offset_face','press_pull'):
            cache=self.__dict__.setdefault('value_limit_cache',{})
            ident=json.dumps({k:v for k,v in f.items() if k not in (key,'name','enabled')},sort_keys=True,default=str)
            cache_key=(id(self.doc),self.doc.revision,self.draft_index,ident)
            if cache_key in cache:return cache[cache_key]
            if self.history_limits_async():
                # Worker processes search while the window stays usable; until they answer the arrow
                # is capped at the largest size already known to build (or not at all).
                self.request_history_limits(cache_key,f,key,sign,minimum)
                return self.__dict__.setdefault('value_limit_partial',{}).get(cache_key,(minimum,None))
            def builds(value):
                trial=copy.deepcopy(f);trial[key]=value*sign
                try:self.doc.preview(self.history_with(trial));return True
                except Exception:return False
            diagonal=1000.
            try:
                box=self.tool_context()[0].val().BoundingBox()
                diagonal=max(10.,2*math.sqrt(box.xlen**2+box.ylen**2+box.zlen**2))
            except Exception:pass
            current=abs(float(f.get(key,0.) or 0.))
            def reach(direction):
                good=0.;bad=None;probe=max(1.,current,diagonal/50)
                while probe<=diagonal:
                    if builds(direction*probe):good=probe;probe*=2
                    else:bad=probe;break
                if bad is None:return None
                for _ in range(8):      # 0.4 % of the bracket; every step is a full history rebuild
                    middle=(good+bad)/2
                    if builds(direction*middle):good=middle
                    else:bad=middle
                return toward_zero(direction*good*.995)
            def operation(report):
                title='Finding the largest size that can be built…'
                report(0,2,title);high=reach(1.);report(1,2,title);low=reach(-1.);report(2,2,title)
                return low,high
            try:lo,hi=self.run_busy('Finding the sizes this tool can build…',operation)
            except Exception:lo,hi=None,None
            if minimum is not None:lo=minimum if lo is None else max(lo,minimum)
            cache[cache_key]=(lo,hi);return lo,hi
        return minimum,None

    def history_limit_pair(self,negative,positive,minimum):
        """Arrow limits from the largest working magnitude in each direction (None = no bound)."""
        lo=None if negative is None else toward_zero(-negative*.995)
        hi=None if positive is None else toward_zero(positive*.995)
        if minimum is not None:lo=minimum if lo is None else max(lo,minimum)
        return lo,hi

    def exact_feature_job(self):
        """Prepare the exact outline of the current draft.

        Everything that reads UI state (the draft, the history, the tool context) is copied
        here, on the UI thread. The result is either a finished outcome tuple, or a function
        that only needs the kernel and can run on a worker thread while the UI stays alive.
        """
        import handle_previews as H
        f=self.draft
        if f is None:return None,'No feature'
        def polyline(edge):
            count=2 if edge.geomType()=='LINE' else 40
            return np.array([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,count)])
        try:
            context=self.tool_context();base=context[0]
            if f.get('kind') in ('fillet','chamfer'):self.draft.setdefault('auto_fit',True)
            doc=self.doc
            # On a body with hundreds of faces the exact outline is a full kernel rebuild, and the
            # kernel holds the interpreter lock for each step of it: the window stalls for as long
            # as it runs. The analytic arrow preview is shown instead, and the real result is
            # built when the feature is applied.
            from model import _is_large
            large=base is not None and _is_large(base)
            if f.get('kind')=='extrude':
                # Decided here (not through resolved_feature, which may open a busy dialog while dragging).
                draft=copy.deepcopy(f)
                if draft.get('operation')=='auto':draft['operation']='add'
                probe_history=None
                if base is not None and not large and draft.get('operation','add') not in ('cut','intersect'):
                    probe=copy.deepcopy(draft);probe['operation']='intersect';probe_history=self.history_with(probe)
                result,sketches,frames=context
                def extrusion_job():
                    hit=[]
                    if probe_history is not None:
                        try:
                            common,_,_=doc.preview(probe_history)   # the volume shared with existing bodies
                            shared=common.val()
                            for index,body in enumerate(base.val().Solids()):
                                try:
                                    if body.intersect(shared).Volume()>1e-6:hit.append(index)
                                except Exception:pass
                        except Exception:hit=[]
                    # The extrusion's own outline, so it stays visible even when it lies inside a body
                    # (an extrusion that merges into a body creates no new faces to outline).
                    # Plain distance extrusions of sketch profiles are outlined straight from the
                    # profile loops (milliseconds); other cases build the real prism.
                    from preview_lines import prism_lines
                    quick=prism_lines(draft,extrusion_sources(draft),sketches,frames)
                    if quick is not None:return quick,None,({'hit':hit} if hit else False)
                    from solid_tools import extrude as build_prism
                    lines=[]
                    for source in extrusion_sources(draft):
                        prism=build_prism(source,draft,result,sketches,frames)
                        lines+=[polyline(e) for e in prism.Edges()]
                    return lines,None,({'hit':hit} if hit else False)
                job=extrusion_job
            else:
                if large and base is not None:return None,None,False
                draft=self.resolved_feature(prompt=False)
                if draft is None:return None,'No feature'
                history=self.history_with(draft)
                def feature_job():
                    solid,_,_=doc.preview(history)
                    if solid is None:return None,'The feature produced no solid.'
                    if base is None:return [polyline(e) for e in solid.val().Edges()],None,False
                    return H.changed_outlines(base.val(),solid.val(),polyline),None,False
                job=feature_job
        except Exception as error:
            return None,str(error)
        def guarded():
            from mesh_cache import KERNEL_LOCK
            try:
                with KERNEL_LOCK:return job()
            except Exception as error:return None,str(error)
        return guarded

    def exact_feature_outlines(self,value=None):
        """Outlines of what Apply would create for the current draft: the same history rebuild
        (``Document.preview``) that Preview and Apply use, diffed against the state before it.
        Synchronous form of :meth:`exact_feature_job`."""
        job=self.exact_feature_job()
        return job() if callable(job) else job

    def exact_state_key(self):
        f=self.draft
        return json.dumps({k:v for k,v in f.items()},sort_keys=True,default=str) if f else None

    def sync_sketch_gizmo(self):
        """Arrows with live previews for the sketch tools that take a size or spacing."""
        w=self.workspace;f=self.draft;tool=w.tool;frame=w.active_frame;gizmo=w.gizmo
        if frame is None or f is None:gizmo.clear();return
        o,u,v,n=axes(frame)
        def outlines(entities,count=48):
            result=[]
            for entity in entities:
                try:points=np.asarray(sample(entity,count),float)
                except Exception:continue
                if len(points)>=2:result.append(np.array([world(frame,p) for p in points]))
            return result
        if tool in ('fillet','chamfer'):
            from sketch_corners import modify_corner
            corners=[list(c) for c in getattr(self,'sketch_corners',[])]
            if not corners:gizmo.clear();return
            size=float(getattr(self,'sketch_corner_size',1.));tolerance=12/max(w.scale(),1e-12)
            entities=copy.deepcopy(f['entities']);original={e['id']:e for e in entities}
            def run(value):
                current=copy.deepcopy(entities);last_before=None;connectors=[]
                for point in corners:
                    last_before=current;current=modify_corner(current,point,tool,float(value),tolerance)
                    connectors.append(current[-1])
                run.connectors=connectors
                return last_before,current
            def feasible(value):
                try:run(value);return True
                except Exception:return False
            # The largest size every picked corner accepts; the arrow can never go past it.
            cache=self.__dict__.setdefault('sketch_limit_cache',{})
            ident=(tool,json.dumps(corners),json.dumps(entities,sort_keys=True,default=str),round(tolerance,9))
            if ident not in cache:
                high=None
                if feasible(.01):
                    points=np.vstack([np.asarray(sample(e,24),float) for e in entities if e['kind']!='point'] or [np.zeros((1,2))])
                    cap=max(10.,float(np.ptp(points[:,0])+np.ptp(points[:,1]))*4)
                    good=.01;probe=max(size,1.)
                    while probe<=cap and feasible(probe):good=probe;probe*=2
                    if probe<=cap:
                        bad=probe
                        for _ in range(18):
                            middle=(good+bad)/2
                            if feasible(middle):good=middle
                            else:bad=middle
                        high=toward_zero(good*.995)
                else:high=.01
                cache.clear();cache[ident]=high
            top=cache[ident];effective=size if top is None else min(size,top)
            try:before,after=run(effective)
            except Exception:gizmo.clear();return
            connector=after[-1]
            line=np.asarray(sample(connector,33),float);a,b=line[0],line[-1];middle=line[len(line)//2]
            # The arrow starts at the corner that was picked and runs along its bisector into the
            # wedge, toward the centre of the rounding, like the arrow of a solid fillet.
            info={}
            try:modify_corner(before,corners[-1],tool,effective,tolerance,info)
            except Exception:info={}
            vertex=np.asarray(info.get('vertex',middle),float)
            inward=(a+b)/2-vertex
            if float(np.linalg.norm(inward))<1e-9:
                chord=b-a;inward=np.array([-chord[1],chord[0]])
            inward=inward/max(float(np.linalg.norm(inward)),1e-12)
            base=np.asarray(world(frame,vertex),float);direction=np.asarray(world(frame,vertex+inward),float)-base
            def preview(value):
                """The new arc/line of every picked corner, and the sketch parts it cuts away."""
                import handle_previews as H
                try:_,result=run(value if top is None else min(value,top))
                except Exception:return []
                connectors=list(run.connectors)
                final={e['id']:e for e in result}
                extent=float(np.ptp(np.vstack([np.asarray(sample(e,24),float) for e in result]),axis=0).max())
                slack=.02+extent*1e-4
                covered=[np.asarray(sample(e,160),float) for e in result]
                cut=[]
                for id_,source in original.items():
                    if final.get(id_)==source:continue
                    for run_points in H.removed_runs(np.asarray(sample(source,160),float),covered,slack):
                        cut.append(np.array([world(frame,p) for p in run_points]))
                return {'lines':outlines(connectors,64),'removed':cut}
            def setter(axis,value):
                widget=self.widgets.get('sketch_corner_size')
                if widget is not None:widget.setValue(value)
                else:self.parameter_changed(lambda x:setattr(self,'sketch_corner_size',x),value)
            gizmo.configure(('sketch_corner',tool,len(corners)),'value',base,[direction],[effective],[],setter,
                            label='Fillet radius' if tool=='fillet' else 'Chamfer distance',minimum=.01,ghost=preview,
                            limits=(.01,top))
            return
        selection=sorted(i for i in w.pattern_selection if 0<=i<len(f['entities']))
        if tool not in ('mirror','circular','rectangular') or not selection:
            gizmo.clear();return
        from geometry import mirror_entities,circular_entities,rectangular_entities
        sources=copy.deepcopy([f['entities'][i] for i in selection])
        try:
            if tool=='rectangular':
                points=np.vstack([np.asarray(sample(e,24),float) for e in sources])
                centre=(points.min(axis=0)+points.max(axis=0))/2
                pick=getattr(w,'pattern_pick',None)
                if pick is not None and pick[0] in selection:centre=np.asarray(pick[1],float)   # where the source was clicked
                origin=np.asarray(world(frame,centre),float)
                columns,rows=int(self.pattern_columns),int(self.pattern_rows)
                def preview(values):
                    try:return outlines(rectangular_entities(copy.deepcopy(sources),columns,rows,values[0],values[1]),24)
                    except Exception:return []
                def setter(axis,value):
                    widget=self.widgets.get('pattern_dx' if axis==0 else 'pattern_dy')
                    if widget is not None:widget.setValue(value)
                gizmo.configure(('sketch_pattern',tool,columns,rows),'spacing',origin,[u,v],[self.pattern_spacing_x,self.pattern_spacing_y],[],setter,
                                ghost=preview,labels=['X spacing','Y spacing'])
                return
            if tool=='circular':
                if self.pattern_center is None:gizmo.clear();return
                copies=circular_entities(sources,self.pattern_center,self.pattern_copies)
            else:
                if self.pattern_axis is None or self.pattern_axis>=len(f['entities']):gizmo.clear();return
                copies=mirror_entities(sources,copy.deepcopy(f['entities'][self.pattern_axis]))
        except Exception:
            gizmo.clear();return
        lines=outlines(copies,24)
        gizmo.configure(('sketch_pattern',tool,len(copies),len(lines)),'preview',np.zeros(3),np.zeros((0,3)),[],[],lambda axis,value:None,ghost=lambda value:lines)

    def sync_gizmo(self):
        w=self.workspace;f=self.draft
        if f is not None and f.get('kind')=='sketch' and w.mode=='sketch' and not w.measure_active:
            self.sync_sketch_gizmo();return
        if f is None or w.measure_active:
            w.gizmo.clear();return
        value_spec=None if f['kind'] in ('body_move','sketch_move','extrude') else self.value_handle_spec(f)
        if f['kind'] not in ('body_move','sketch_move','extrude') and value_spec is None:
            w.gizmo.clear();return
        if f['kind']=='extrude' and (not ('sources' in f or 'source' in f) or f.get('extent','distance')!='distance'):
            w.gizmo.clear();return
        # Translation/depth/size updates reuse sampled geometry, never rerun the kernel.
        changing={'dx','dy','dz','depth','depth2','name','enabled','operation','signed_depth'} if value_spec is None else {'name','enabled','auto_fit',value_spec[0]}
        geometry_key=(id(self.doc),self.doc.revision,self.draft_index,f['kind'],
                      json.dumps({k:v for k,v in f.items() if k not in changing},sort_keys=True,default=str))
        try:
            if getattr(self,'gizmo_geometry_key',None)!=geometry_key:
                result,sketches,frames=self.tool_context()
                def prepare(progress):
                    if value_spec is not None:return self.value_handle_geometry(f,result,sketches,frames)
                    paths=[];centers=[];direction=None
                    if f['kind']=='sketch_move':
                        s=sketches.get(f.get('sketch'))
                        if s is None:raise ModelError('Select a sketch to move.')
                        o,u,v,n=axes(frames[s['id']])
                        if frames[s['id']].get('spatial'):
                            if s['kind']=='surface_sketch':raise ModelError('A surface sketch follows its supporting face. Move the supporting body instead.')
                            paths.extend(__import__('spatial_sketch').sampled(s,frames[s['id']]))
                        for ent in ([] if frames[s['id']].get('spatial') else s['entities']):
                            pts=np.asarray(sample(ent),float)
                            if len(pts):paths.append(o+pts[:,0,None]*u+pts[:,1,None]*v)
                        if not paths:raise ModelError('The sketch has no geometry.')
                        all_points=np.vstack(paths);centers=[(all_points.min(axis=0)+all_points.max(axis=0))/2]
                    elif f['kind']=='body_move':
                        from references import resolve_body
                        from solid_tools import axis_reference
                        if not f.get('targets'):return None
                        a,d=axis_reference(f.get('axis',{'type':'origin','axis':'Z'}),result,sketches,frames)
                        bodies=[]
                        for ref in f['targets']:
                            index,body=resolve_body(result,ref)
                            if not any(body.isSame(other) for other in bodies):bodies.append(body)
                        for body in bodies:
                            if f.get('angle',0):body=body.rotate(tuple(a),tuple(a+d),float(f['angle']))
                            centers.append(np.asarray(body.Center().toTuple()))
                            for edge in body.Edges():
                                count=2 if edge.geomType()=='LINE' else 40
                                paths.append(np.array([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,count)]))
                    else:
                        from preview_lines import source_loops
                        quick=source_loops(extrusion_sources(f),sketches,frames)
                        offset_value=float(f.get('offset',0))
                        if quick is not None:
                            # Straight from the profile loops: building a kernel wire per selected
                            # profile made every click cost time proportional to the selection.
                            for n,rings,center in quick:
                                if direction is None:direction=n
                                centers.append(center+n*offset_value)
                                for ring in rings:paths.append(dict(points=ring+n*offset_value,normal=n))
                        else:
                            from solid_tools import profile
                            for source in extrusion_sources(f):
                                outer,inner,frame=profile(source,result,sketches,frames);o,u,v,n=axes(frame)
                                if direction is None:direction=n
                                centers.append(np.asarray(outer.Center().toTuple())+n*offset_value)
                                for wire in [outer]+inner:
                                    for edge in wire.Edges():
                                        count=2 if edge.geomType()=='LINE' else 48
                                        paths.append(dict(points=np.array([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,count)])+n*offset_value,normal=n))
                        # Multi-plane sources share one depth but keep their own normals.
                        # One manipulator belongs to the first selected profile.
                    self.gizmo_normal_outward=False
                    if f['kind']=='extrude' and result is not None and direction is not None and centers:
                        try:
                            import cadquery as cq
                            shape=result.val();box=shape.BoundingBox()
                            eps=max(1e-3,(box.xlen+box.ylen+box.zlen)*1e-4);c=np.asarray(centers[0],float);d=np.asarray(direction,float)
                            outside=not shape.isInside(cq.Vector(*(c+d*eps)));inside=bool(shape.isInside(cq.Vector(*(c-d*eps))))
                            self.gizmo_normal_outward=bool(outside and inside)
                        except Exception:self.gizmo_normal_outward=False
                    return np.mean(centers,axis=0) if f['kind']!='extrude' else centers[0],paths,direction
                self.gizmo_geometry=self.run_busy('Preparing workspace handles…',prepare)
                self.gizmo_geometry_key=geometry_key
            if self.gizmo_geometry is None:w.gizmo.clear();return
            if value_spec is not None:
                key,label,minimum,sign=value_spec;center,direction,ghost=self.gizmo_geometry
                lo,hi=self.value_limits(f,value_spec)
                shown=float(f.get(key,0.) or 0.)*sign
                if lo is not None:shown=max(float(lo),shown)
                if hi is not None:shown=min(float(hi),shown)
                def set_value(axis,value,key=key,sign=sign):
                    widget=self.widgets.get(key)
                    if widget is not None:widget.setValue(value*sign)
                    else:self.parameter_changed(lambda v:f.update({key:v}),value*sign)
                w.gizmo.configure((f['id'],self.draft_index,key),'value',center,[direction],[shown],[],set_value,
                                  label=label,minimum=minimum,ghost=ghost,exact=self.exact_feature_outlines,exact_key=self.exact_state_key(),
                                  limits=(lo,hi),exact_job=self.exact_feature_job)
                return
            center,paths,direction=self.gizmo_geometry
            move=f['kind']!='extrude'
            # A cut from a face sketch removes material behind the face, so its arrow points
            # into the body; dragging along it makes the (negative-direction) depth larger.
            flip=-1. if (not move and f.get('operation')=='cut' and f.get('direction')!='symmetric'
                         and getattr(self,'gizmo_normal_outward',False)) else 1.
            values=[f.get(k,0.) for k in ('dx','dy','dz')] if move else [f.get('depth',0.)*flip]
            directions=np.eye(3) if move else [np.asarray(direction,float)*flip]
            two_sided=not move and f.get('direction')=='two sides'
            if two_sided:
                # Two arrows pointing away from each other: side 1 along the depth, side 2 the
                # other way (solid_tools.extrude builds it along -n*|depth2|*sign(depth)).
                depth=float(f.get('depth',0.) or 0.);second=abs(float(f.get('depth2',depth) or 0.))
                directions=[np.asarray(direction,float)*flip,-np.asarray(direction,float)*(1. if depth>=0 else -1.)]
                values=[depth*flip,second]
            def setter(axis,value):
                if two_sided and axis==1:
                    # The second distance is a length away from the first side; dragging past the
                    # profile stops just short of zero instead of flipping it.
                    value=max(abs(value),1e-3) if value>0 else 1e-3
                    widget=self.widgets.get('depth2')
                    if widget is not None:widget.setValue(value)
                    else:self.parameter_changed(lambda v:f.update(depth2=v),value)
                    return
                key=('dx','dy','dz')[axis] if move else 'depth'
                value=value*flip if not move else value
                widget=self.widgets.get(key)
                if widget is not None:widget.setValue(value)
                else:self.parameter_changed(lambda v:f.update({key:v}),value)
            w.gizmo.configure((f['id'],self.draft_index,flip,two_sided),'move' if move else 'extrude',center,directions,values,paths,setter,f.get('direction')=='symmetric',f.get('taper',0),
                              labels=['Side 1','Side 2'] if two_sided else None,
                              exact=self.exact_feature_outlines if not move else None,exact_key=self.exact_state_key() if not move else None,
                              exact_job=self.exact_feature_job if not move else None)
        except Exception as error:
            w.gizmo.clear();self.show_status(str(error))
