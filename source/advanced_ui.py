"""Shared selection editors for direct modeling and extended CAD tools."""
import copy
import numpy as np
from PySide6.QtWidgets import QListWidget,QAbstractItemView,QCheckBox,QComboBox
from option_labels import option_label,tool_label
from geometry import identifier
from references import body_reference
from face_tools import FACE_TOOLS
from ui_icons import icon
from i18n import tr

from advanced_patterns import PATTERN_TOOLS
from surface_tools import SURFACE_TOOLS
from special_solids import SPECIAL_TOOLS
ADVANCED_TOOLS=FACE_TOOLS+PATTERN_TOOLS+SURFACE_TOOLS+SPECIAL_TOOLS

def cylinder_axis(face):
    """Start and end point (lists) of the axis of a cylindrical face, spanning the face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder();axis=cylinder.Axis();location=axis.Location();direction=axis.Direction()
    o=np.array([location.X(),location.Y(),location.Z()]);d=np.array([direction.X(),direction.Y(),direction.Z()])
    values=[float((np.array(v.toTuple())-o)@d) for v in face.Vertices()]
    low,high=min(values),max(values)
    if high-low<1e-6:high=low+10.
    return (o+d*low).tolist(),(o+d*high).tolist()


class AdvancedUI:
    def integer(self,form,key,label,value,callback,minimum=1,maximum=200):
        from PySide6.QtWidgets import QSpinBox
        widget=QSpinBox();widget.setRange(minimum,maximum);widget.setValue(value)
        widget.valueChanged.connect(lambda value:self.parameter_changed(callback,value));form.addRow(tr(label),widget);self.widgets[key]=widget

    def init_advanced_tools(self):
        from PySide6.QtWidgets import QMenu
        self.surface_menu=QMenu(tr('Surface'),self);surface_action=self.solid_menu.addMenu(self.surface_menu);surface_action.setIcon(icon('surface_patch'));surface_action.setProperty('_icon_name','surface_patch');surface_action.setProperty('_i18n_text','Surface')
        for kind in ADVANCED_TOOLS:
            menu=self.solid_menu if kind in SPECIAL_TOOLS else self.surface_menu if kind in SURFACE_TOOLS else self.body_pattern_menu if kind in PATTERN_TOOLS else self.solid_modify_menu
            action=menu.addAction(icon(kind),tr(tool_label(kind)))
            action.setProperty('_i18n_text',tool_label(kind));action.setData(kind);action.setProperty('_icon_name',kind)
            action.triggered.connect(lambda checked=False,k=kind:self.start_advanced_tool(k))

    def start_advanced_tool(self,kind):
        if not self.abandon():return
        self.draft_index=None;self.selected=None;self.workspace.set_mode('model')
        self.draft=dict(id=identifier(),kind=kind,name=tr(tool_label(kind)),enabled=True,targets=[],faces=[],distance=1.,factor=1.1,pivot=[0.,0.,0.],source=None,replacement=None,object_type="features",features=[],columns=2,rows=1,spacing_x=20.,spacing_y=20.,count=4,angle=360.,axis=dict(type="origin",axis="Z"),plane=dict(type="origin",plane="XY"),path=None,orient=False,surfaces=[],sections=[],vector=[0.,0.,10.],thickness=1.,tolerance=.001,make_solid=False,consume=True,keep="positive",extend_direction="all",shape="box",origin=[0.,0.,0.],width=10.,length=10.,height=10.,radius=5.,top_radius=0.,minor_radius=1.,diameter=1.,pitch=2.,hollow=False,left_hand=False,thread_type="external",thread_depth=.6,thread_width=1.2,operation="new" if kind in ('primitive','pipe','coil') else "join")
        self.show_editor()
        if kind in FACE_TOOLS and kind!='scale' and self.doc.solid is not None:
            self.enable_face_pick('faces');self.show_status(tr('Click the faces to use (Shift+drag draws a selection box); drag to orbit.'))
        elif kind in ('pipe','rib','web','surface_sweep'):
            self.begin_path_pick()
        elif kind in ('thread','coil'):
            self.default_pattern_selection()
            if self.doc.solid is not None:
                self.enable_face_pick('cylinder');self.show_status(tr('Click a cylindrical face (a shaft or a hole wall) to put the thread or coil on it.'))
        elif kind in ('rib','web'):
            self.default_pattern_selection();self.begin_path_pick()
        elif kind in PATTERN_TOOLS:
            chosen=self.default_pattern_selection()
            if kind=='path_pattern' and chosen:self.begin_path_pick()
            elif self.doc.solid is not None and not chosen:
                self.enable_face_pick('targets');self.show_status(tr('Click the body to pattern in the workspace.'))

    def default_pattern_selection(self):
        """Make a pattern work right away: the only body is the target, the last feature the one repeated.

        Returns True when a target body was chosen automatically.
        """
        f=self.draft
        result=self.tool_context()[0]
        bodies=result.val().Solids() if result else []
        chosen=False
        if len(bodies)==1:
            f['targets']=[body_reference(bodies[0],0,1,result)];chosen=True
        index=len(self.doc.features)
        for feature in reversed(self.doc.features[:index]):
            if feature.get('id') and feature.get('enabled',True) and feature['kind'] not in ('sketch','construction_plane','construction_axis'):
                f['features']=[feature['id']];break
        if f['kind']=='feature_mirror':f['plane']=dict(type='origin',plane='YZ')
        self.show_editor()
        return chosen

    def use_cylinder_face(self,face):
        """Thread / coil: take the axis, radius, length and body from a clicked cylindrical face."""
        f=self.draft
        if face.geomType()!='CYLINDER':
            self.show_status(tr('That face is not cylindrical. Click the wall of a shaft or a round hole.'));return
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder();axis=cylinder.Axis();location=axis.Location();direction=axis.Direction()
        o=np.array([location.X(),location.Y(),location.Z()]);d=np.array([direction.X(),direction.Y(),direction.Z()])
        values=[float((np.array(v.toTuple())-o)@d) for v in face.Vertices()]
        low,high=min(values),max(values)
        if high-low<1e-6:self.show_status(tr('That face is not cylindrical. Click the wall of a shaft or a round hole.'));return
        f['axis']=dict(type='points',start=(o+d*low).tolist(),end=(o+d*high).tolist())
        f['radius']=float(cylinder.Radius());f['height']=float(high-low)
        if f['kind']=='thread':
            centre=np.array(face.Center().toTuple());radial=centre-(o+d*float((centre-o)@d))
            normal=np.array(face.normalAt().toTuple())
            f['thread_type']='external' if float(normal@radial)>0 else 'internal'
            pitch=f.get('pitch',2.);f['thread_depth']=round(min(pitch*.6,f['radius']*.4),3);f['thread_width']=round(min(pitch*.6,pitch*.9),3)
        result=self.tool_context()[0]
        bodies=result.val().Solids() if result else []
        owner=next((i for i,b in enumerate(bodies) if any(face.isSame(x) for x in b.Faces())),None)
        if owner is not None:f['targets']=[body_reference(bodies[owner],owner,len(bodies),result)]
        self.workspace.solid_face_picking=False
        self.invalidate_preview();self.show_editor()
        self.show_status(tr('Cylinder taken: radius, length and axis are set. Adjust pitch and size, then Preview.'))

    def advanced_selection(self,form,key,label,choices,current):
        listing=QListWidget();listing.setSelectionMode(QAbstractItemView.MultiSelection);listing.setMaximumHeight(130)
        for name,value in choices:
            listing.addItem(name);listing.item(listing.count()-1).setSelected(value in current)
        def changed():
            values=[copy.deepcopy(choices[listing.row(item)][1]) for item in listing.selectedItems()]
            self.parameter_changed(lambda value:self.draft.update({key:value}),values)
            if key=='faces':self.highlight_solid_faces()
        listing.itemSelectionChanged.connect(changed);form.addRow(tr(label),listing);self.widgets[key]=listing
        return listing

    def advanced_editor(self):
        f=self.draft;kind=f['kind'];self.feature_action_row(f);form=self.form(tr(tool_label(kind)));self.name_field(form,f)
        result,sketches,frames=self.tool_context()
        if kind in SURFACE_TOOLS:
            self.surface_editor(form,f,result,frames);return
        bodies=result.val().Solids() if result else []
        choices=[(tr('Body')+' '+str(i+1),body_reference(b,i,len(bodies),result)) for i,b in enumerate(bodies)]
        self.advanced_selection(form,'targets','Target bodies',choices,f.get('targets',[]))
        if kind=='press_pull':
            self.combo(form,'press_type','Selection type',['faces','profile'],f.get('press_type','faces'),lambda value:self.press_pull_type(value))
            if f.get('press_type')=='profile':
                self.reference_combo(form,'source','Profile',self.profile_choices,f.get('source'),lambda value:f.update(source=value));self.spin(form,'distance','Distance',f.get('distance',1.),lambda value:f.update(distance=value));self.combo(form,'operation','Operation',['new','join','cut','intersect'],f.get('operation','new'),lambda value:f.update(operation=value));return
        if kind in SPECIAL_TOOLS:
            self.special_editor(form,f,result);return
        if kind in PATTERN_TOOLS:
            self.advanced_pattern_editor(form,f,result)
            return
        if kind=='scale':
            self.spin(form,'factor','Scale factor',f.get('factor',1.1),lambda value:f.update(factor=value),True)
            self.vector_fields(form,'pivot','Scale center',f.setdefault('pivot',[0.,0.,0.]),lambda value:f.update(pivot=value))
        else:
            from solid_tools import face_ref
            self.advanced_selection(form,'faces','Faces',[(self.face_label(i,face),face_ref(face,result)) for i,face in enumerate(result.val().Faces() if result else [])],f.get('faces',[]))
            self.button('Pick faces in workspace',lambda:self.enable_face_pick('faces'))
            if kind in ('press_pull','offset_face'):self.spin(form,'distance','Distance',f.get('distance',1.),lambda value:f.update(distance=value))
            elif kind=='split_face':self.reference_combo(form,'source','Splitting profile',self.profile_choices+[(name,dict(type='path',**ref)) for name,ref in self.path_choices],f.get('source'),lambda value:f.update(source=value))
            elif kind=='replace_face':self.reference_combo(form,'replacement','Replacement plane',self.plane_choices(),f.get('replacement'),lambda value:f.update(replacement=value))
            self.highlight_solid_faces()
        if kind=='replace_face':self.note('Replace Face supports parallel planar replacements. Other surface boundaries need surface modeling first.')

    def advanced_pattern_editor(self,form,f,result):
        self.note('1. Choose what to repeat: features, faces or whole bodies.  2. Click the body in the workspace (or tick it in Target bodies).  3. Set the count and spacing: the result previews by itself.')
        if f.get('object_type','features')!='faces':self.button('Click the body in the workspace',lambda:self.enable_face_pick('targets'))
        self.combo(form,'object_type','Objects',['features','faces','bodies'],f.get('object_type','features'),lambda value:self.pattern_type(value))
        if f.get('object_type')=='features':
            index=self.draft_index if self.draft_index is not None else len(self.doc.features)
            choices=[(h['name'],h['id']) for h in self.doc.features[:index] if h.get('id') and h['kind'] not in ('sketch','construction_plane','construction_axis') and h.get('enabled',True)]
            self.advanced_selection(form,'features','Features',choices,f.get('features',[]))
        elif f.get('object_type')=='faces':
            from solid_tools import face_ref
            self.advanced_selection(form,'faces','Feature faces',[(self.face_label(i,face),face_ref(face,result)) for i,face in enumerate(result.val().Faces() if result else [])],f.get('faces',[]))
            self.button('Pick faces in workspace',lambda:self.enable_face_pick('faces'))
        kind=f['kind']
        if kind in ('feature_rectangular','feature_mirror'):
            self.reference_combo(form,'plane','Plane',self.plane_choices(),f.get('plane'),lambda value:f.update(plane=value))
        if kind=='feature_rectangular':
            for key,label in [('columns','Columns'),('rows','Rows')]:self.integer(form,key,label,f.get(key,2 if key=='columns' else 1),lambda value,k=key:f.update({k:value}),1,200)
            self.spacing_mode(form,f)
            extent=f.get('spacing_mode')=='extent'
            for key,label in [('spacing_x','X length' if extent else 'X spacing'),('spacing_y','Y length' if extent else 'Y spacing')]:self.spin(form,key,label,f.get(key,20.),lambda value,k=key:f.update({k:value}))
        elif kind in ('feature_circular','path_pattern'):
            self.integer(form,'count','Positions',f.get('count',4),lambda value:f.update(count=value),2,500)
            if kind=='feature_circular':
                self.reference_combo(form,'axis','Axis',self.axis_choices(),f.get('axis'),lambda value:f.update(axis=value))
                self.spin(form,'angle','Angle',f.get('angle',360.),lambda value:f.update(angle=value))
            else:
                self.reference_combo(form,'path','Path',self.path_choices,f.get('path'),lambda value:f.update(path=value))
                self.button('Click the path in the workspace',self.begin_path_pick)
                box=QCheckBox(tr('Orient along path'));box.setChecked(f.get('orient',False));box.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(orient=value),on));form.addRow(box)

    def spacing_mode(self,form,f):
        """Pattern distance given as the spacing between copies or as the overall length (Fusion's Distance Type)."""
        box=QComboBox()
        for value in ('spacing','extent'):box.addItem(tr(option_label(value)),value)
        box.setCurrentIndex(max(0,box.findData(f.get('spacing_mode','spacing'))))
        def changed(i):
            f['spacing_mode']=box.itemData(i);self.invalidate_preview();self.show_editor()
        box.currentIndexChanged.connect(changed);form.addRow(tr('Distance type'),box);self.widgets['spacing_mode']=box

    def pattern_type(self,value):
        self.draft['object_type']=value;self.show_editor()

    def surface_editor(self,form,f,result,frames):
        kind=f['kind']
        curves=self.profile_choices+[(name,dict(type='path',**ref)) for name,ref in self.path_choices]
        if kind in ('surface_extrude','surface_revolve','surface_sweep','surface_patch'):
            self.reference_combo(form,'source','Boundary',curves,f.get('source'),lambda value:f.update(source=value))
            if kind=='surface_extrude':self.vector_fields(form,'vector','Extrusion',f.setdefault('vector',[0.,0.,10.]),lambda value:f.update(vector=value))
            elif kind=='surface_revolve':
                self.reference_combo(form,'axis','Axis',self.axis_choices(),f.get('axis'),lambda value:f.update(axis=value));self.spin(form,'angle','Angle',f.get('angle',360.),lambda value:f.update(angle=value))
            elif kind=='surface_sweep':self.reference_combo(form,'path','Path',self.path_choices,f.get('path'),lambda value:f.update(path=value));self.path_buttons('surface_sweep')
        elif kind=='surface_loft':
            box=self.reference_combo(form,'section','Next section',curves,None,lambda value:None)
            listing=QListWidget()
            for ref in f.get('sections',[]):listing.addItem(next((name for name,data in curves if data==ref),'Saved section'))
            form.addRow(tr('Sections in order'),listing)
            def add():
                if box.currentData():f.setdefault('sections',[]).append(copy.deepcopy(box.currentData()));self.invalidate_preview();self.show_editor()
            def remove():
                if listing.currentRow()>=0:f['sections'].pop(listing.currentRow());self.invalidate_preview();self.show_editor()
            self.button('Add section',add);self.button('Remove section',remove)
        else:
            from surface_tools import bodies
            self.advanced_selection(form,'surfaces','Surface bodies',[(body['name'],id_) for id_,body in bodies(frames).items()],f.get('surfaces',[]))
            if kind=='surface_trim':
                self.reference_combo(form,'plane','Trim plane',self.plane_choices(),f.get('plane'),lambda value:f.update(plane=value));self.combo(form,'keep','Keep side',['positive','negative'],f.get('keep','positive'),lambda value:f.update(keep=value))
            elif kind=='surface_extend':
                self.spin(form,'distance','Extension',f.get('distance',5.),lambda value:f.update(distance=value),True);self.combo(form,'extend_direction','Directions',['all','u','v'],f.get('extend_direction','all'),lambda value:f.update(extend_direction=value))
            elif kind=='surface_thicken':self.spin(form,'thickness','Thickness',f.get('thickness',1.),lambda value:f.update(thickness=value))
            elif kind=='surface_stitch':
                self.spin(form,'tolerance','Tolerance',f.get('tolerance',.001),lambda value:f.update(tolerance=value),True)
                box=QCheckBox(tr('Make solid'));box.setChecked(f.get('make_solid',False));box.toggled.connect(lambda value:self.parameter_changed(lambda value:f.update(make_solid=value),value));form.addRow(box)
            box=QCheckBox(tr('Consume source surfaces'));box.setChecked(f.get('consume',True));box.toggled.connect(lambda value:self.parameter_changed(lambda value:f.update(consume=value),value));form.addRow(box)

    def special_editor(self,form,f,result):
        kind=f['kind']
        def size(key,label,positive=True):self.spin(form,key,label,f[key],lambda value:f.update({key:value}),positive)
        if kind=='primitive':
            self.combo(form,'shape','Primitive',['box','cylinder','sphere','cone','torus'],f.get('shape','box'),lambda value:self.primitive_type(value))
            self.vector_fields(form,'origin','Origin',f['origin'],lambda value:f.update(origin=value))
            for key in dict(box=['width','length','height'],cylinder=['radius','height'],sphere=['radius'],cone=['radius','top_radius','height'],torus=['radius','minor_radius'])[f['shape']]:size(key,key.replace('_',' ').title(),key!='top_radius')
        elif kind in ('coil','thread'):
            self.note('Click the round wall of a shaft or a hole in the workspace: its axis, radius and length are taken over. ' + ('The thread is cut as a helical groove (external on a shaft, internal in a hole). Pitch = distance between turns.' if kind=='thread' else 'The coil is a wire wound around that axis (a spring). Pitch = distance between turns.'))
            self.button('Click a cylindrical face in the workspace',lambda:self.enable_face_pick('cylinder'))
            self.reference_combo(form,'axis','Axis',self.axis_choices(),f.get('axis'),lambda value:f.update(axis=value))
            for key in ('radius','pitch','height'):size(key,key.title())
            if kind=='coil':size('diameter','Wire diameter')
            else:
                self.combo(form,'thread_type','Thread type',['external','internal'],f.get('thread_type','external'),lambda value:f.update(thread_type=value))
                size('thread_depth','Thread depth');size('thread_width','Thread width')
            box=QCheckBox(tr('Left hand'));box.setChecked(f.get('left_hand',False));box.toggled.connect(lambda value:self.parameter_changed(lambda value:f.update(left_hand=value),value));form.addRow(box)
        else:
            self.reference_combo(form,'path','Path',self.path_choices,f.get('path'),lambda value:f.update(path=value))
            self.path_buttons(kind)
            if kind=='pipe':
                size('diameter','Diameter');size('thickness','Wall thickness')
                box=QCheckBox(tr('Hollow'));box.setChecked(f.get('hollow',False));box.toggled.connect(lambda value:self.parameter_changed(lambda value:f.update(hollow=value),value));form.addRow(box)
            else:
                self.note('Rib: a thin supporting wall that stands on the sketch line you picked (it grows from the sketch plane along its normal), used to stiffen a part between two walls. Web: the same wall centred on the sketch plane, half above and half below, for cross-bracing. Draw the line or curve of the wall in a sketch, click it, then set the wall Thickness and Height.')
                size('thickness','Thickness');size('height','Height')
        if kind!='thread':self.combo(form,'operation','Operation',(['new'] if kind in ('primitive','pipe','coil') else [])+['join','cut','intersect'],f.get('operation','new'),lambda value:f.update(operation=value))
        if kind=='thread':self.note('Creates a modeled helical groove. Radius and axis must match the selected cylinder. Dimensions are explicit; no thread standards are implied.')

    def primitive_type(self,value):
        self.draft['shape']=value;self.show_editor()

    def press_pull_type(self,value):
        self.draft.update(press_type=value,operation='new',faces=[]);self.show_editor()
