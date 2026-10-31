"""Editors and selections for construction and solid features."""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu,QToolButton,QComboBox,QListWidget,QAbstractItemView,QLabel,QCheckBox
from geometry import identifier,profile_regions,axes,new_sketch,frame_on_face,face_reference
from solid_tools import CONSTRUCTIONS,SOLID_TOOLS,face_ref,plane_reference
from model import ModelError
from i18n import tr
from ui_icons import icon
from expression_spin import SidedSpinBox
from option_labels import option_label

# ISO metric screws: clearance hole (medium series), tap drill and the socket-head counterbore / countersink sizes.
HOLE_STANDARDS={
    'M2':dict(clearance=2.4,tap=1.6,head=4.4,head_depth=2.2,sink=4.4),
    'M2.5':dict(clearance=2.9,tap=2.05,head=5.5,head_depth=2.7,sink=5.5),
    'M3':dict(clearance=3.4,tap=2.5,head=6.5,head_depth=3.4,sink=6.3),
    'M4':dict(clearance=4.5,tap=3.3,head=8.0,head_depth=4.4,sink=8.4),
    'M5':dict(clearance=5.5,tap=4.2,head=10.0,head_depth=5.4,sink=10.4),
    'M6':dict(clearance=6.6,tap=5.0,head=11.0,head_depth=6.5,sink=12.6),
    'M8':dict(clearance=9.0,tap=6.8,head=15.0,head_depth=8.5,sink=16.8),
    'M10':dict(clearance=11.0,tap=8.5,head=18.0,head_depth=10.5,sink=20.8),
    'M12':dict(clearance=13.5,tap=10.2,head=20.0,head_depth=12.5,sink=24.0),
}


class LazyChoices(list):
    """Cheap choices now, the rest (``load()``) only when somebody looks at the list.

    Listing every planar face of a big body (areas, normals, labels, a combo item each) took
    over a second each time an editor was rebuilt, even though nobody opened the dropdown.
    """
    def __init__(self,cheap,loader):
        super().__init__(cheap);self.loader=loader


class LazyReferenceBox(QComboBox):
    """A reference combo that adds its expensive entries when it is first opened or queried."""
    def __init__(self,choices,current):
        super().__init__();self.choices=choices;self.current_reference=current;self.filled=False
    def fill(self):
        if self.filled:return
        self.filled=True
        selected=QComboBox.currentData(self);current=selected if selected is not None else self.current_reference
        self.blockSignals(True)
        try:
            QComboBox.clear(self);QComboBox.addItem(self,tr('Select…'),None)
            for name,data in self.choices.loader():QComboBox.addItem(self,tr(name),copy.deepcopy(data))
            index=next((i for i in range(1,QComboBox.count(self)) if QComboBox.itemData(self,i)==current),0)
            if current and not index:QComboBox.addItem(self,tr('Saved reference'),copy.deepcopy(current));index=QComboBox.count(self)-1
            QComboBox.setCurrentIndex(self,index)
        finally:self.blockSignals(False)
    def showPopup(self):
        self.fill();super().showPopup()
    # Python-level readers see the complete list, so code (and tests) that inspect the items
    # behave exactly as before; only the editor rebuild no longer pays for it.
    def count(self):self.fill();return QComboBox.count(self)
    def itemData(self,index,*args):self.fill();return QComboBox.itemData(self,index,*args)
    def itemText(self,index):self.fill();return QComboBox.itemText(self,index)
    def findData(self,*args,**kwargs):self.fill();return QComboBox.findData(self,*args,**kwargs)
    def findText(self,*args,**kwargs):self.fill();return QComboBox.findText(self,*args,**kwargs)
    def setCurrentIndex(self,index):self.fill();QComboBox.setCurrentIndex(self,index)


class SolidUI:
    def init_solid_tools(self):
        self.solid_menu=QMenu(self);self.solid_modify_menu=QMenu(self);self.construction_menu=QMenu(self);self.tool_choices_key=None
        for kind in SOLID_TOOLS:
            menu=self.solid_modify_menu if kind in ('shell','draft') else self.solid_menu
            a=menu.addAction(tr(kind.title()));a.setData(kind);a.setProperty('_icon_name',kind);a.setIcon(icon(kind));a.triggered.connect(lambda checked=False,k=kind:self.start_solid_tool(k))
        for title,kind,mode in [('Offset plane','construction_plane','offset'),('Angled plane','construction_plane','angled'),('Midplane','construction_plane','midplane'),('Three-point plane','construction_plane','three points'),('Axis','construction_axis','two points')]:
            a=self.construction_menu.addAction(tr(title));a.setProperty('_i18n_text',title);a.setProperty('_icon_name',{'offset':'offset_plane','angled':'angled_plane','midplane':'midplane','three points':'three_point_plane','two points':'construction_axis'}[mode]);a.setIcon(icon(a.property('_icon_name')));a.triggered.connect(lambda checked=False,k=kind,m=mode:self.start_solid_tool(k,m))
        for key,menu in [('solid_tools',self.solid_menu),('solid_modify',self.solid_modify_menu),('construct',self.construction_menu)]:
            from tool_palette import bind_dropdown
            bind_dropdown(self,key,self.body_buttons[key],menu)
        self.workspace.solid_face_picked.connect(self.pick_solid_face)
        self.workspace.path_picked.connect(self.path_picked)
        self.workspace.construction_point_picked.connect(self.pick_construction_point)

    def tool_context(self):
        index=self.draft_index if self.draft_index is not None else self.feature_insert_index(self.draft or {})
        key=(id(self.doc),self.doc.revision,index)
        if getattr(self,'solid_context_key',None)!=key:
            state=self.run_busy('Preparing feature references…',lambda report:self.doc.preview(self.doc.features[:index],progress=report)) if index<len(self.doc.features) else (self.doc.solid,self.doc.sketches,self.doc.frames)
            result,sketches,frames=state
            def choices(report):
                profiles=[];paths=[]
                for s in sketches.values():
                    if frames[s['id']].get('spatial'):
                        usable=[e['id'] for e in s['entities'] if e['kind']!='point']
                        paths.extend((s['name']+' · '+e['kind'],dict(sketch=s['id'],entities=[e['id']])) for e in s['entities'] if e['kind']!='point')
                        if len(usable)>1:paths.append((s['name']+' · connected curves',dict(sketch=s['id'],entities=usable)))
                        continue
                    for i,r in enumerate(profile_regions(s)):
                        profiles.append((f'{s["name"]} · profile {i+1}',dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested')))
                    usable=[e for e in s['entities'] if e['kind'] in ('line','arc','spline','conic')]
                    for i,e in enumerate(usable):paths.append((f'{s["name"]} · {e["kind"]} {i+1}',dict(sketch=s['id'],entities=[e['id']])))
                    if len(usable)>1:paths.append((s['name']+' · connected curves',dict(sketch=s['id'],entities=[e['id'] for e in usable])))
                return profiles,paths
            profiles,paths=self.run_busy('Finding sketch profiles…',choices)
            self.solid_context_key=key;self.solid_context=(result,sketches,frames);self.profile_choices=profiles;self.path_choices=paths
        return self.solid_context

    def plane_choices(self):
        """Origin and construction planes now; planar body faces load when the list is opened."""
        result,sketches,frames=self.tool_context();options=[(p+' plane',dict(type='origin',plane=p)) for p in ('XY','XZ','YZ')]
        for f in self.doc.features[:self.draft_index if self.draft_index is not None else len(self.doc.features)]:
            if f['kind']=='construction_plane' and f['id'] in frames:options.append((f['name'],dict(type='construction',id=f['id'])))
        if not result:return options
        def everything():
            full=list(options)
            for i,face in enumerate(result.val().Faces()):
                if face.geomType()=='PLANE':full.append((self.face_label(i,face),dict(type='face',face=face_reference(face),origin='projected')))
            return full
        return LazyChoices(options,everything)

    def axis_choices(self):
        result,sketches,frames=self.tool_context();options=[(p+' axis',dict(type='origin',axis=p)) for p in ('X','Y','Z')]
        for f in self.doc.features:
            if f['kind']=='construction_axis' and f['id'] in frames:options.append((f['name'],dict(type='construction',id=f['id'])))
        for s in sketches.values():
            if s['kind']=='surface_sketch':continue
            for i,e in enumerate(s['entities']):
                if e['kind']=='line':options.append((f'{s["name"]} · line {i+1}',dict(type='sketch_line',sketch=s['id'],entity=e['id'])))
        options.append(('Two points',dict(type='points',start=[0,0,0],end=[10,0,0])))
        return options

    @staticmethod
    def face_label(i,face):
        c=face.Center().toTuple();return f'Face {i+1} · {face.geomType().lower()} · ({c[0]:g}, {c[1]:g}, {c[2]:g})'

    def reference_combo(self,form,key,label,choices,current,callback,refresh=False):
        if isinstance(choices,LazyChoices):
            box=LazyReferenceBox(choices,current);QComboBox.addItem(box,tr('Select…'),None)
            for name,data in choices:QComboBox.addItem(box,tr(name),copy.deepcopy(data))
            index=next((i for i in range(1,QComboBox.count(box)) if QComboBox.itemData(box,i)==current),0)
            if current and not index:
                if isinstance(current,dict) and current.get('type')=='face':
                    # A saved face reference: show it as such until the full list is opened.
                    QComboBox.addItem(box,tr('Saved reference'),copy.deepcopy(current));index=QComboBox.count(box)-1
                else:QComboBox.addItem(box,tr('Saved reference'),copy.deepcopy(current));index=QComboBox.count(box)-1
            QComboBox.setCurrentIndex(box,index)
        else:
            box=QComboBox();box.addItem(tr('Select…'),None)
            for name,data in choices:box.addItem(tr(name),copy.deepcopy(data))
            index=next((i for i in range(1,box.count()) if box.itemData(i)==current),0)
            if current and not index:box.addItem(tr('Saved reference'),copy.deepcopy(current));index=box.count()-1
            box.setCurrentIndex(index)
        def changed(i):
            self.parameter_changed(callback,copy.deepcopy(box.itemData(i)))
            if refresh:self.show_editor()
        box.currentIndexChanged.connect(changed);form.addRow(tr(label),box);self.widgets[key]=box;return box

    def vector_fields(self,form,key,label,value,callback):
        for index,axis in enumerate('XYZ'):
            def update(number,i=index):
                values=list(value);values[i]=number;value[:]=values;callback(values)
            self.spin(form,key+axis,tr(label)+' '+axis,value[index],update)

    def start_solid_tool(self,kind,mode=None):
        if not self.abandon():return
        if kind in ('shell','draft','hole') and self.doc.solid is None:self.error('Create a body first.');return
        self.draft_index=None;self.selected=None;self.workspace.set_mode('model');self.tool_context()
        f=dict(kind=kind,id=identifier(),name=tr(kind.replace('_',' ').title()),enabled=True,operation='add')
        plane=dict(type='origin',plane='XY');axis=dict(type='origin',axis='Z')
        if kind=='construction_plane':f.update(mode=mode,reference=plane,second=dict(type='frame',frame=dict(origin=[0,0,10],u=[1,0,0],normal=[0,0,1])),offset=10.,angle=45.,axis=dict(type='origin',axis='X'),p1=[0,0,0],p2=[10,0,0],p3=[0,10,0])
        elif kind=='construction_axis':f.update(reference=dict(type='points',start=[0,0,0],end=[0,0,10]))
        elif kind in ('revolve','sweep'):
            f['source']=copy.deepcopy(self.profile_choices[0][1]) if self.profile_choices and kind=='revolve' else None
            if kind=='revolve':
                f.update(angle=360.,axis=axis)
                if f['source']:
                    frame=self.doc.frames[f['source']['sketch']];o,u,v,n=axes(frame);f['axis']=dict(type='points',start=o.tolist(),end=(o+v*10).tolist())
            else:f.update(path=None,frenet=False)
        elif kind=='loft':f.update(sections=[],ruled=False)
        elif kind=='shell':f.update(thickness=-1.,body=0,faces=[])
        elif kind=='draft':f.update(angle=3.,body=0,faces=[],neutral=plane)
        elif kind=='hole':f.update(plane=plane,x=0.,y=0.,depth=10.,diameter=5.,hole_type='simple',head_diameter=10.,head_depth=3.,head_angle=90.,through_all=False,direction='inward',operation='cut')
        if kind=='hole' and self.doc.solid is not None:
            faces=[face for face in self.doc.solid.val().Faces() if face.geomType()=='PLANE']
            if faces:f['plane']=dict(type='face',face=face_reference(max(faces,key=lambda face:face.Center().z)))
        self.draft=f;self.set_scene_responsive(self.visible_solid(),self.scene_sketches(),materials=self.body_materials());self.show_editor()
        if kind in ('construction_plane','construction_axis'):
            self.begin_construction_pick();return
        # Selections are made by clicking in the workspace from the start (the lists stay as an
        # alternative): faces for shell / draft, the supporting face for a hole, sketch profiles
        # for revolve / sweep / loft.
        if kind in ('shell','draft') and self.doc.solid is not None:
            self.enable_face_pick();self.show_status(tr('Click the faces to open (Shift+drag draws a selection box); drag to orbit.') if kind=='shell' else tr('Click the faces to draft (Shift+drag draws a selection box); drag to orbit.'))
        elif kind=='hole' and self.doc.solid is not None:
            self.enable_face_pick('plane');self.show_status(tr('Click the face the hole starts on; drag to orbit.'))
        elif kind in ('revolve','sweep','loft'):
            self.begin_profile_pick()

    def begin_profile_pick(self):
        """Click sketch profiles (or planar faces) in the workspace: revolve/sweep profile, loft sections."""
        self.workspace.set_path_picking(False);self.workspace.set_extrusion_selection([],True);self.workspace.setFocus()
        kind=(self.draft or {}).get('kind')
        self.show_status(tr('Click each section in order: a closed sketch profile or a planar face.') if kind=='loft' else
                         tr('Click the closed sketch profile (or planar face) to use.'))

    PATH_TOOLS=('sweep','pipe','rib','web','surface_sweep','path_pattern')

    def begin_path_pick(self):
        """Click a sketch curve in the workspace to use it (with the curves joined to it) as the path."""
        if self.draft is None or self.draft.get('kind') not in self.PATH_TOOLS:return
        self.workspace.set_extrusion_selection([],False);self.workspace.set_path_picking(True);self.workspace.setFocus()
        self.show_status(tr('Click a sketch curve to use it as the path (connected curves are taken together).'))

    def path_picked(self,reference):
        f=self.draft
        if f is None or f.get('kind') not in self.PATH_TOOLS:return
        f['path']=dict(reference);self.invalidate_preview();self.show_editor()
        self.show_status(tr('Path selected · click another curve to change it.'))

    def path_buttons(self,kind):
        """The panel buttons that switch the workspace between picking the profile and the path."""
        if kind=='sweep':
            self.button('Click the profile in the workspace',self.begin_profile_pick)
        self.button('Click the path in the workspace',self.begin_path_pick)

    def highlight_references(self):
        """Draw the chosen profile, loft sections and path over the model in the workspace."""
        f=self.draft
        if f is None or f.get('kind') not in self.PATH_TOOLS+('loft','revolve'):return
        paths=[]
        try:
            result,sketches,frames=self.tool_context()
            from geometry import sample
            def sketch_lines(sketch_id,entity_ids):
                sketch=sketches.get(sketch_id);frame=frames.get(sketch_id)
                if sketch is None or frame is None or frame.get('spatial'):return
                o,u,v,n=axes(frame);lookup={e['id']:e for e in sketch['entities']}
                for id_ in entity_ids:
                    if id_ in lookup and lookup[id_]['kind']!='point':
                        points=np.asarray(sample(lookup[id_]),float)
                        if len(points)>=2:paths.append(o+points[:,0,None]*u+points[:,1,None]*v)
            sources=([f['source']] if isinstance(f.get('source'),dict) else [])+[s for s in f.get('sections',[]) if isinstance(s,dict)]
            for source in sources:
                if source.get('type')=='face' and result is not None:
                    from geometry import resolve_face
                    try:face=resolve_face(result,source['face'])
                    except Exception:continue
                    for edge in face.outerWire().Edges():
                        paths.append(np.array([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,2 if edge.geomType()=='LINE' else 24)]))
                elif source.get('sketch'):sketch_lines(source['sketch'],source.get('entities',[]))
            path=f.get('path')
            if isinstance(path,dict) and path.get('sketch'):sketch_lines(path['sketch'],path.get('entities',[]))
        except Exception:paths=[]
        self.workspace.reference_highlight=paths;self.workspace.update()

    def pick_solid_face(self,index):
        f=self.draft
        if not f or not 0<=index<len(self.workspace.faces):return
        from body_tools import BODY_TOOLS
        if f['kind'] in BODY_TOOLS:self.pick_body(index);return
        face=self.workspace.faces[index]
        try:
            if f['kind'] in __import__('spatial_sketch').SPATIAL_TOOLS:
                from references import shape_reference
                result,sketches,frames=self.tool_context();ref=shape_reference(face,'face',result)
                for id_,body in frames.get('_surfaces',{}).items():
                    if any(face.isSame(own) for own in body['shape'].Faces()):ref=__import__('references').surface_reference(face,'face',id_,frames);break
                f['face']=ref;self.workspace.solid_face_picking=False
            elif str(self.workspace.solid_pick_key).startswith('cylinder_axis:'):
                key=self.workspace.solid_pick_key.split(':',1)[1]
                if face.geomType()!='CYLINDER':
                    self.show_status(tr('That face is not round. Click the wall of a shaft or a round hole.'));return
                from advanced_ui import cylinder_axis
                start,end=cylinder_axis(face);f[key]=dict(type='points',start=start,end=end)
                self.workspace.solid_face_picking=False
            elif f['kind'] in ('thread','coil'):
                self.use_cylinder_face(face);return
            elif f['kind'] in __import__('advanced_patterns').PATTERN_TOOLS and f.get('object_type','features')!='faces':
                self.pick_body(index);return
            elif f['kind'] in ('shell','draft')+__import__('face_tools').FACE_TOOLS+__import__('advanced_patterns').PATTERN_TOOLS:
                ref=face_ref(face,self.tool_context()[0]);refs=f.setdefault('faces',[])
                existing=next((r for r in refs if self.face_is_selected(face,[r],self.tool_context()[0])),None)
                if existing:refs.remove(existing)
                else:
                    refs.append(ref)
                    if f['kind'] in ('shell','draft'):
                        # Clicking a face of another body makes that body the one being shelled / drafted.
                        context=self.tool_context()[0]
                        owner=next((i for i,b in enumerate(context.val().Solids()) if any(face.isSame(x) for x in b.Faces())),None) if context else None
                        if owner is not None and owner!=f.get('body'):f['body']=owner;f['faces']=[ref]
            else:
                reference=dict(type='face',face=face_reference(face),origin='projected');key=self.workspace.solid_pick_key
                if key=='target' and f['kind']=='extrude':f[key]=reference
                else:f[key]=reference
                self.workspace.solid_face_picking=False
            self.invalidate_preview();self.show_editor()
        except Exception as error:self.error(error)

    def enable_point_pick(self,key,axis_key=None):
        self.workspace.solid_face_picking=False;self.workspace.construction_point_picking=True;self.construction_pick_key=(key,axis_key)
        self.workspace.setFocus();self.show_status('Choose a model corner or sketch point.')

    def pick_construction_point(self,coordinates):
        key,axis_key=self.construction_pick_key
        if axis_key:self.draft[axis_key][key]=list(coordinates)
        else:self.draft[key]=list(coordinates)
        self.workspace.construction_point_picking=False;self.invalidate_preview();self.show_editor()
        following={'p1':'p2','p2':'p3','start':'end'}.get(key)
        if following and self.draft.get('kind') in ('construction_plane','construction_axis'):
            self.enable_point_pick(following,axis_key)
            self.show_status(tr('Point set. Click the next point.'))

    def enable_face_pick(self,key='faces'):
        if self.draft_index is not None:
            result,sketches,frames=self.tool_context();self.workspace.set_mode('model')
            self.set_scene_responsive(result,[(s,frames[id_]) for id_,s in sketches.items()],materials=self.body_materials())
        self.workspace.construction_point_picking=False;self.workspace.solid_face_picking=True;self.workspace.solid_pick_key=key;self.workspace.setFocus()
        self.show_status('Click a face in the workspace; drag to orbit. Click again to toggle multiple faces.')

    def solid_feature_editor(self):
        f=self.draft;kind=f['kind'];self.feature_action_row(f);form=self.form(tr(kind.replace('_',' ').title()));self.name_field(form,f)
        result,sketches,frames=self.tool_context()
        def planes(key,label):
            self.reference_combo(form,key,label,self.plane_choices(),f.get(key),lambda value:f.update({key:value}))
            if result:self.button('Pick '+label.lower()+' face',lambda:self.enable_face_pick(key))
        def axis(key):
            self.reference_combo(form,key,'Axis',self.axis_choices(),f.get(key),lambda value:f.update({key:value}),True)
            if result:self.button('Use the axis of a round face',lambda:self.enable_face_pick('cylinder_axis:'+key))
            ref=f.get(key)
            if ref and ref.get('type')=='points':
                for field in ('start','end'):
                    self.vector_fields(form,key+field,field.title(),ref[field],lambda value,k=field:ref.update({k:value}))
                    self.button('Pick '+field+' point',lambda checked=False,field=field:self.enable_point_pick(field,key))
        if kind=='construction_plane':
            self.combo(form,'mode','Plane type',['offset','angled','midplane','three points'],f['mode'],lambda value:self.change_construction_mode(value))
            if f['mode']=='three points':
                for key in ('p1','p2','p3'):
                    self.vector_fields(form,key,key.upper(),f[key],lambda value,k=key:f.update({k:value}))
                    self.button('Pick '+key.upper(),lambda checked=False,key=key:self.enable_point_pick(key))
            else:
                planes('reference','Reference plane')
                if f['mode']=='offset':self.spin(form,'offset','Offset',f['offset'],lambda value:f.update(offset=value))
                elif f['mode']=='midplane':planes('second','Second plane')
                else:axis('axis');self.spin(form,'angle','Angle',f['angle'],lambda value:f.update(angle=value))
            self.button('Create sketch on this plane',self.commit_plane_sketch)
        elif kind=='construction_axis':
            axis('reference')
            if result:self.button('Click two points instead',lambda:self.begin_construction_pick())
        elif kind in ('revolve','sweep'):
            self.reference_combo(form,'source','Profile',self.profile_choices,f.get('source'),lambda value:f.update(source=value))
            if kind=='revolve':
                axis('axis');self.spin(form,'angle','Angle',f['angle'],lambda value:f.update(angle=value))
                sym=QCheckBox(tr('Symmetric (half the angle on each side)'));sym.setChecked(bool(f.get('symmetric',False)))
                sym.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(symmetric=value),bool(on)));form.addRow(sym);self.widgets['symmetric']=sym
            else:
                self.reference_combo(form,'path','Path',self.path_choices,f.get('path'),lambda value:f.update(path=value))
                self.path_buttons('sweep')
                self.reference_combo(form,'guide','Guide curve (optional)',self.path_choices,f.get('guide'),lambda value:f.update(guide=value) if value else f.pop('guide',None))
                check=QCheckBox(tr('Frenet orientation'));check.setChecked(f.get('frenet',False));check.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(frenet=value),on));form.addRow(check)
                self.note('The profile must meet the start of the connected path and be perpendicular to it. Tight bends may self-intersect.')
        elif kind=='loft':
            self.button('Click the sections in the workspace',self.begin_profile_pick)
            selector=self.reference_combo(form,'loft_profile','Next section',self.profile_choices,None,lambda value:None)
            listing=QListWidget();listing.setMaximumHeight(140)
            for section in f['sections']:listing.addItem(next((label for label,data in self.profile_choices if data==section),'Saved profile'))
            form.addRow('Sections in order',listing)
            def add():
                value=selector.currentData()
                if value and value not in f['sections']:f['sections'].append(copy.deepcopy(value));self.invalidate_preview();self.show_editor()
            def remove():
                row=listing.currentRow()
                if row>=0:f['sections'].pop(row);self.invalidate_preview();self.show_editor()
            def move(delta):
                row=listing.currentRow();other=row+delta
                if row>=0 and 0<=other<len(f['sections']):f['sections'][row],f['sections'][other]=f['sections'][other],f['sections'][row];self.invalidate_preview();self.show_editor()
            self.button('Add section',add);self.button('Remove section',remove)
            self.button('Move section up',lambda:move(-1));self.button('Move section down',lambda:move(1))
            check=QCheckBox(tr('Ruled loft'));check.setChecked(f['ruled']);check.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(ruled=value),on));form.addRow(check)
        elif kind in ('shell','draft'):
            bodies=result.val().Solids() if result else []
            self.reference_combo(form,'body','Body',[(self.body_label(result,i),i) for i in range(len(bodies))],f.get('body',0),lambda value:self.change_body(value),True)
            if kind=='shell':self.shell_thickness(form,f)
            else:planes('neutral','Neutral plane');self.spin(form,'angle','Draft angle',f['angle'],lambda value:f.update(angle=value))
            listing=QListWidget();listing.setSelectionMode(QAbstractItemView.MultiSelection);listing.setMaximumHeight(180)
            faces=bodies[f.get('body',0)].Faces() if bodies and f.get('body') is not None else []
            selected_faces=self.matched_face_objects(f['faces'],result)
            for i,face in enumerate(faces):
                listing.addItem(self.face_label(i,face));listing.item(i).setSelected(any(face.isSame(selected) for selected in selected_faces))
            def selected():
                self.parameter_changed(lambda value:f.update(faces=value),[face_ref(faces[listing.row(item)]) for item in listing.selectedItems()]);self.highlight_solid_faces()
            listing.itemSelectionChanged.connect(selected);form.addRow('Open faces' if kind=='shell' else 'Draft faces',listing);self.widgets['solid_faces']=listing
            self.button('Pick faces in workspace',lambda:self.enable_face_pick())
            self.note('Shell: select faces to remove, or leave empty for a closed hollow body.' if kind=='shell' else 'Draft rotates selected faces about the neutral plane. Positive angles remove material in the plane-normal direction.')
        elif kind=='hole':
            planes('plane','Supporting plane');self.combo(form,'hole_type','Hole type',['simple','counterbore','countersink'],f['hole_type'],lambda value:self.change_hole_type(value))
            point_sketches=[(s['name'],s['id']) for s in sketches.values() if not frames[s['id']].get('spatial') and any(e['kind']=='point' for e in s['entities'])]
            if point_sketches:
                self.reference_combo(form,'points_sketch','At the points of sketch',point_sketches,f.get('points_sketch'),lambda value:self.change_hole_points(value),True)
            if not f.get('points_sketch'):
                for key,label in [('x','X'),('y','Y')]:self.spin(form,key,label,f[key],lambda value,k=key:f.update({k:value}))
            standard=QComboBox();standard.addItem(tr('Custom size'),'')
            for name in HOLE_STANDARDS:standard.addItem(name,name)
            standard.setCurrentIndex(max(0,standard.findData(f.get('standard',''))))
            fit=QComboBox()
            for label,value in [('Clearance','clearance'),('Tap drill','tap')]:fit.addItem(tr(label),value)
            fit.setCurrentIndex(max(0,fit.findData(f.get('fit','clearance'))))
            standard.currentIndexChanged.connect(lambda i:self.apply_hole_standard(standard.itemData(i),fit.currentData()))
            fit.currentIndexChanged.connect(lambda i:self.apply_hole_standard(standard.currentData(),fit.itemData(i)))
            form.addRow(tr('Standard size'),standard);form.addRow(tr('Fit'),fit);self.widgets['hole_standard']=standard;self.widgets['hole_fit']=fit
            for key,label in [('diameter','Diameter'),('depth','Depth')]:self.spin(form,key,label,f[key],lambda value,k=key:f.update({k:value}),True)
            if not f.get('through_all'):
                tip=self.spin(form,'tip_angle','Drill point angle (0 = flat bottom)',f.get('tip_angle',0.),lambda value:f.update(tip_angle=value))
                tip.setRange(0,179);tip.setToolTip(tr('118° is a standard twist-drill point.'))
            self.combo(form,'hole_direction','Direction',['inward','outward'],f['direction'],lambda value:f.update(direction=value))
            check=QCheckBox(tr('Through all'));check.setChecked(f.get('through_all',False));check.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(through_all=value),on));form.addRow(check)
            if f['hole_type']!='simple':
                self.spin(form,'head_diameter','Head diameter',f['head_diameter'],lambda value:f.update(head_diameter=value),True)
                key='head_depth' if f['hole_type']=='counterbore' else 'head_angle';self.spin(form,key,'Head depth' if key=='head_depth' else 'Included angle',f[key],lambda value:f.update({key:value}),True)
            self.note('X and Y are coordinates on the supporting plane. A face support starts at its center; inward points into the body.')
        if kind in ('revolve','sweep','loft'):self.combo(form,'operation','Operation',['add','cut','intersect','new'],f.get('operation','add'),lambda value:f.update(operation=value))
        self.highlight_solid_faces()
        active=QCheckBox(tr('Active'));active.setChecked(f.get('enabled',True));active.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(enabled=value),on));form.addRow(active)

    @staticmethod
    def matched_face_objects(refs,result):
        from references import match_shape
        selected=[]
        for ref in refs:
            try:selected.append(match_shape(result,ref,'face')[0])
            except ModelError:pass
        return selected

    @staticmethod
    def face_is_selected(face,refs,result):
        return any(face.isSame(candidate) for candidate in SolidUI.matched_face_objects(refs,result))

    def highlight_solid_faces(self):
        selected=self.matched_face_objects(self.draft.get('faces',[]),self.tool_context()[0])
        self.workspace.solid_selected_faces={i for i,face in enumerate(self.workspace.faces) if any(face.isSame(candidate) for candidate in selected)};self.workspace.update()

    def change_body(self,value):self.draft.update(body=value,faces=[])

    def shell_thickness(self,form,f):
        """Wall thickness as a plain positive number plus Inside / Outside, as in Fusion's Shell."""
        box=SidedSpinBox(-1 if float(f.get('thickness',-1))<=0 else 1);box.setDecimals(4);box.setRange(-100000,100000);box.setSingleStep(1.)
        box.setValue(float(f.get('thickness',-1)) or -1.)
        box.valueChanged.connect(lambda v:self.parameter_changed(lambda value:f.update(thickness=value),v))
        self.widgets['thickness']=box;form.addRow(tr('Wall thickness'),box)
        side=QComboBox()
        for label,value in (('Inside the body','inside'),('Outside the body','outside')):side.addItem(tr(label),value)
        side.setCurrentIndex(0 if box.sign<0 else 1)
        def changed(i):
            box.sign=-1 if side.itemData(i)=='inside' else 1
            box.setValue(box.sign*max(abs(box.value()),.0001))
        side.currentIndexChanged.connect(changed);form.addRow(tr('Wall side'),side);self.widgets['shell_side']=side
    def change_construction_mode(self,value):
        self.draft['mode']=value;self.show_editor();self.begin_construction_pick()

    def begin_construction_pick(self):
        """Start the click-in-the-workspace selection that fits the construct tool."""
        f=self.draft
        if f is None:return
        if f['kind']=='construction_axis':
            self.enable_point_pick('start','reference')
            self.show_status(tr('Click the first point of the axis (a corner or a sketch point), then the second.'))
        elif f['kind']=='construction_plane':
            if f.get('mode')=='three points':
                self.enable_point_pick('p1');self.show_status(tr('Click three points (corners or sketch points) one after another.'))
            elif f.get('mode')=='midplane':
                self.enable_face_pick('reference');self.show_status(tr('Click the first face, then choose the second plane on the right.'))
            elif self.doc.solid is not None:
                self.enable_face_pick('reference');self.show_status(tr('Click a face to build the plane from (or choose a plane on the right).'))
    def change_hole_type(self,value):
        self.draft['hole_type']=value
        if self.draft.get('standard'):self.apply_hole_standard(self.draft['standard'],self.draft.get('fit','clearance'))
        else:self.show_editor()

    def change_hole_points(self,value):
        f=self.draft
        if value:f['points_sketch']=value
        else:f.pop('points_sketch',None)

    def apply_hole_standard(self,name,fit):
        """Set diameter (and head size) from a metric screw size: clearance hole or tap drill."""
        f=self.draft;f['fit']=fit or 'clearance'
        if not name:
            f.pop('standard',None);self.invalidate_preview();self.show_editor();return
        data=HOLE_STANDARDS[name];f['standard']=name
        f['diameter']=data['tap'] if f['fit']=='tap' else data['clearance']
        if f.get('hole_type')=='counterbore':f['head_diameter']=data['head'];f['head_depth']=data['head_depth']
        elif f.get('hole_type')=='countersink':f['head_diameter']=data['sink'];f['head_angle']=90.
        self.invalidate_preview();self.show_editor()
    def commit_plane_sketch(self):
        id_=self.draft['id'];self.apply_feature()
        if self.draft is None and id_ in self.doc.frames:self.sketch_on_construction(id_)
    def sketch_on_construction(self,id_):
        if not self.abandon():return
        frame=copy.deepcopy(self.doc.frames[id_]);self.draft=new_sketch(frame,'Sketch on construction plane');self.draft['plane_ref']=dict(type='construction',id=id_)
        self.draft_index=None;self.sketch_undo=[];self.sketch_redo=[];self.entity_index=None;self.precise_draft=None
        self.workspace.set_mode('sketch',self.draft,frame);self.set_tool('rectangle')
