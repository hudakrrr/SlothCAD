"""Explicit target selection and transactional downstream reference repair."""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QMenu,QToolButton,QListWidget,QAbstractItemView,QCheckBox,
 QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton)
from body_tools import BODY_TOOLS,LABELS
from references import (body_reference,resolve_body,reference_slots,value_at,replace_at,
 shape_reference,match_shape)
from geometry import identifier
from model import build_state,ModelError
from i18n import tr
from ui_icons import icon


_SUMMARIES={}
def _body_summary(body):
    """``(volume, centre of mass)`` of a body, cached: both are a full volume integration, which
    takes a noticeable time on the interface thread for big (e.g. imported mesh) bodies."""
    key=body.hashCode()
    for other,value in _SUMMARIES.get(key,()):
        if other.isSame(body):return value
    value=(body.Volume(),body.Center().toTuple())
    if len(_SUMMARIES)>256:_SUMMARIES.clear()
    _SUMMARIES.setdefault(key,[]).append((body,value))
    return value

class RecoveryDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle(tr('Inspect / Repair references'));self.resize(820,620)
        w=window.workspace;self.return_view=(w.mode,w.active,w.active_frame,w.tool,copy.deepcopy(w.points));self.previewing=False;self.applied=False
        self.return_state={key:copy.deepcopy(getattr(w,key)) for key in ("measure_active","measure_selection","measure_result","measure_hover","cursor","construction_mode","dimension_locks","dimension_index","dimension_text","dimension_typing","center","span","zoom","pan","yaw","pitch","aligned","selected_edges","solid_selected_faces","selected_entity","solid_face_picking","solid_pick_key","construction_point_picking")}
        self.candidate=copy.deepcopy(window.doc.pending_features if window.doc.pending_features is not None else window.doc.features)
        layout=QVBoxLayout(self);self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.history=QListWidget();layout.addWidget(self.history,1)
        self.history.currentRowChanged.connect(self.select_feature)
        self.slots=QComboBox();self.slots.currentIndexChanged.connect(self.select_slot);layout.addWidget(self.slots)
        self.replacements=QComboBox();layout.addWidget(self.replacements)
        row=QHBoxLayout();layout.addLayout(row)
        show=QPushButton(tr('Show selected reference'));show.clicked.connect(self.show_reference);row.addWidget(show)
        self.replace_button=QPushButton(tr('Replace selected reference'));self.replace_button.clicked.connect(self.replace_reference);row.addWidget(self.replace_button)
        apply=QPushButton(tr('Rebuild and apply repairs'));apply.clicked.connect(self.apply_repairs);row.addWidget(apply)
        discard=QPushButton(tr('Discard pending edit'));discard.clicked.connect(self.discard_pending);row.addWidget(discard)
        close=QPushButton(tr('Close'));close.clicked.connect(self.reject);row.addWidget(close)
        self.detail=QLabel();self.detail.setWordWrap(True);layout.addWidget(self.detail)
        self.refresh_report()

    def refresh_report(self):
        window=self.window
        self.report=window.run_busy('Inspecting downstream references…',lambda progress:window.doc.inspect_history(self.candidate,progress))
        self.history.blockSignals(True);self.history.clear()
        for row in self.report:
            self.history.addItem(f'{row["index"]+1}. {row["name"]} · '+tr(row['state']))
            if row['state']=='needs repair':self.history.item(row['index']).setForeground(Qt.red)
            self.history.item(row['index']).setToolTip(row['message'])
        self.history.blockSignals(False)
        failing=next((r['index'] for r in self.report if r['state']=='needs repair'),None)
        recovered=sum(r['state']=='recovered' for r in self.report)
        self.summary.setText(tr('Pending upstream edit; the committed model is unchanged.') if window.doc.pending_features is not None else tr('Inspecting the committed feature history.'))
        self.summary.setText(self.summary.text()+f'\n{recovered} '+tr('features recovered')+(' · '+tr('Rebuild is blocked at feature')+f' {failing+1}' if failing is not None else ' · '+tr('All features rebuild successfully.')))
        self.history.setCurrentRow(failing if failing is not None else max(0,len(self.report)-1))

    def select_feature(self,index):
        self.slots.blockSignals(True);self.slots.clear();self.replacements.clear();self.prefix_state=None
        if not 0<=index<len(self.candidate):self.slots.blockSignals(False);return
        row=self.report[index];self.detail.setText(tr(row['message']) or tr('Select a stored face, edge or body reference to inspect or replace it.'))
        labels={'support':'Sketch support','source':'Source','sources':'Sources','plane':'Supporting plane','target':'Target','reference':'Reference plane','second':'Second plane','neutral':'Neutral plane','faces':'Faces','edge_refs':'Edges','body_ref':'Body','targets':'Target bodies','tools':'Tool bodies'}
        for path,kind in reference_slots(self.candidate[index]):
            text=' / '.join(str(part+1) if isinstance(part,int) else tr(labels.get(part,part.title())) for part in path)
            self.slots.addItem(text+' · '+tr(kind),(path,kind))
        try:
            self.prefix_state=self.window.run_busy('Preparing repair candidates…',lambda progress:build_state(copy.deepcopy(self.candidate[:index]),progress))
        except Exception as error:self.detail.setText(tr('Repair the earlier failing feature first.')+'\n'+str(error))
        self.slots.blockSignals(False);self.select_slot(self.slots.currentIndex())

    def select_slot(self,index):
        self.replacements.clear();self.replace_button.setEnabled(False)
        if not self.prefix_state or index<0:return
        result=self.prefix_state[0]
        frames=self.prefix_state[2]
        path,kind=self.slots.itemData(index);feature=self.candidate[self.history.currentRow()];old=value_at(feature,path)
        shapes=(result.val().Solids() if kind=='body' else result.val().Faces() if kind=='face' else result.val().Edges()) if result is not None else []
        for i,shape in enumerate(shapes):
            reference=body_reference(shape,i,len(shapes),result) if kind=='body' else shape_reference(shape,kind,result)
            c=shape.Center().toTuple();text=f'{tr(kind.title())} {i+1} · '+(shape.geomType()+' · ' if kind!='body' else '')+f'({c[0]:g}, {c[1]:g}, {c[2]:g})'
            self.replacements.addItem(text,reference)
        if kind!='body':
            from references import surface_reference
            for surface_id,body in frames.get('_surfaces',{}).items():
                for shape in body['shape'].Faces() if kind=='face' else body['shape'].Edges():
                    shapes.append(shape);self.replacements.addItem(body['name']+' · '+shape.geomType(),surface_reference(shape,kind,surface_id,frames))
        self.replace_button.setEnabled(self.replacements.count()>0)
        try:
            if kind=='body':matched,shape=resolve_body(result,old);state='matched'
            else:
                from references import surface_shape
                shape,state=surface_shape(old,kind,frames) if old.get('surface_id') else match_shape(result,old,kind);matched=next(i for i,s in enumerate(shapes) if s.isSame(shape))
            self.replacements.setCurrentIndex(matched);self.detail.setText(tr('Current reference')+': '+tr(state)+' · '+self.replacements.currentText())
        except Exception as error:self.detail.setText(str(error))

    def show_reference(self):
        if not self.prefix_state or self.slots.currentIndex()<0 or self.replacements.currentIndex()<0:return
        window=self.window;result,sketches,frames=self.prefix_state;path,kind=self.slots.currentData();ref=self.replacements.currentData()
        from surface_tools import scene
        from references import surface_shape
        view=scene(result,frames)
        if view is None:return
        window.workspace.set_mode('model');window.set_scene_responsive(view,[(s,frames[id_]) for id_,s in sketches.items()],fit=True,materials=window.body_materials())
        if kind=='edge':
            edge,state=surface_shape(ref,'edge',frames) if ref.get('surface_id') else match_shape(result,ref,'edge');window.workspace.selected_edges={i for i,(shape,points) in enumerate(window.workspace.solid_edges) if edge.isSame(shape)}
            window.workspace.set_mode('edge');window.workspace.selected_edges={i for i,(shape,points) in enumerate(window.workspace.solid_edges) if edge.isSame(shape)}
        else:
            candidates=[resolve_body(result,ref)[1]] if kind=='body' else [surface_shape(ref,'face',frames)[0] if ref.get('surface_id') else match_shape(result,ref,'face')[0]]
            faces=[face for body in candidates for face in body.Faces()] if kind=='body' else candidates
            window.workspace.solid_selected_faces={i for i,face in enumerate(window.workspace.faces) if any(face.isSame(candidate) for candidate in faces)}
        self.previewing=True;window.workspace.update()

    def done(self,result):
        if self.previewing and not self.applied:
            window=self.window;mode,active,frame,tool,points=self.return_view
            window.workspace.set_mode(mode,active,frame);window.workspace.tool=tool;window.workspace.points=points
            window.set_scene_responsive(window.visible_solid(),window.scene_sketches(),materials=window.body_materials())
            for key,value in self.return_state.items():setattr(window.workspace,key,value)
            if window.workspace.measure_active:window.workspace.setCursor(Qt.CrossCursor)
            window.workspace.update()
        super().done(result)

    def replace_reference(self):
        if self.slots.currentIndex()<0 or self.replacements.currentIndex()<0:return
        path,kind=self.slots.currentData();replace_at(self.candidate[self.history.currentRow()],path,copy.deepcopy(self.replacements.currentData()))
        self.refresh_report()

    def apply_repairs(self):
        window=self.window
        try:
            window.run_busy('Rebuilding repaired history…',lambda progress:window.doc.commit(self.candidate,progress))
            self.applied=True;window.draft=None;window.draft_index=None;window.precise_draft=None;window.history_preview_index=None;window.workspace.set_mode('model');window.refresh();self.accept()
        except Exception as error:self.detail.setText(str(error));self.refresh_report()

    def discard_pending(self):
        self.applied=True;self.window.doc.pending_features=None;self.window.doc.pending_error=None;self.window.cancel();self.reject()

class BodyUI:
    def init_body_tools(self):
        self.body_menu=QMenu(self)
        for kind in BODY_TOOLS:
            a=self.body_menu.addAction(tr(LABELS[kind]));a.setData(kind);a.setProperty('_icon_name',kind);a.setIcon(icon(kind));a.triggered.connect(lambda checked=False,k=kind:self.start_body_tool(k))
        from tool_palette import bind_dropdown
        self.body_pattern_menu=QMenu(self);self.body_modify_menu=QMenu(self)
        for action in self.body_menu.actions():
            target=self.body_pattern_menu if action.data() in ('body_mirror','body_rectangular','body_circular') else self.body_modify_menu
            target.addAction(action)
        bind_dropdown(self,'body_patterns',self.body_buttons['body_patterns'],self.body_pattern_menu)
        bind_dropdown(self,'body_tools',self.body_buttons['body_tools'],self.body_modify_menu)
        self.recovery_dialog=None

    def open_reference_recovery(self):
        # Failed commits retain their candidate separately; opening Repair never
        # abandons that upstream edit or overwrites the last valid document.
        self.recovery_dialog=RecoveryDialog(self);self.recovery_dialog.exec()

    def start_body_tool(self,kind):
        if not self.abandon():return
        if self.doc.solid is None:self.error('Create a body first.');return
        self.draft_index=None;self.selected=None;self.workspace.set_mode('model')
        f=dict(kind=kind,id=identifier(),name=tr(LABELS[kind]),enabled=True,targets=[])
        plane=dict(type='origin',plane='XY');axis=dict(type='origin',axis='Z')
        if kind=='body_move':f.update(dx=0.,dy=0.,dz=0.,angle=0.,axis=axis,copy=False)
        elif kind=='body_mirror':f.update(plane=plane,keep_original=True)
        elif kind=='body_rectangular':f.update(plane=plane,columns=2,rows=1,spacing_x=20.,spacing_y=20.)
        elif kind=='body_circular':f.update(axis=axis,count=4,angle=360.)
        elif kind=='body_split':f.update(plane=plane,keep='both')
        elif kind=='body_combine':f.update(tools=[],operation='join',keep_tools=False)
        self.draft=f;self.show_editor()
        # Body tools start in click-a-body mode: selecting a body brings up its move arrows
        # (Move) or its settings right away; dragging empty space still orbits the view.
        w=self.workspace
        w.construction_point_picking=False;w.solid_face_picking=True;w.solid_pick_key='targets';w.setFocus()
        self.show_status(tr('Click a body to select it, arrows then appear to move it live; drag to orbit.') if kind=='body_move'
                         else tr('Click a body to select it; drag to orbit.'))

    def pick_body(self,index):
        if not 0<=index<len(self.workspace.faces):return
        face=self.workspace.faces[index];result=self.tool_context()[0]
        if result is None:return
        bodies=result.val().Solids();index=next((i for i,b in enumerate(bodies) if any(face.isSame(f) for f in b.Faces())),None)
        if index is None:self.show_status('Select a body from the feature input, before this operation.');return
        ref=body_reference(bodies[index],index,len(bodies),result);key=self.workspace.solid_pick_key
        if key not in ('targets','tools'):key='targets'
        refs=self.draft.setdefault(key,[])
        existing=next((r for r in refs if resolve_body(result,r)[0]==index),None)
        if existing:refs.remove(existing)
        else:
            if self.draft['kind']=='body_combine' and key=='targets':refs.clear()
            refs.append(ref)
        self.invalidate_preview();self.show_editor()

    def body_feature_editor(self):
        f=self.draft;kind=f['kind'];self.feature_action_row(f);form=self.form(LABELS[kind]);self.name_field(form,f)
        result,sketches,frames=self.tool_context();bodies=result.val().Solids() if result else []
        for key,label in ([('targets','Target body'),('tools','Tool bodies')] if kind=='body_combine' else [('targets','Target bodies')]):
            listing=QListWidget();listing.setMaximumHeight(130);listing.setSelectionMode(QAbstractItemView.SingleSelection if kind=='body_combine' and key=='targets' else QAbstractItemView.MultiSelection)
            selected=set()
            for ref in f.get(key,[]):
                try:selected.add(resolve_body(result,ref)[0])
                except ModelError:pass
            for i,b in enumerate(bodies):
                volume,c=_body_summary(b);listing.addItem(f'{self.body_label(result,i)} · {volume:g} mm³ · ({c[0]:g}, {c[1]:g}, {c[2]:g})');listing.item(i).setSelected(i in selected)
            def changed(listing=listing,key=key):
                refs=[body_reference(bodies[listing.row(item)],listing.row(item),len(bodies),result) for item in listing.selectedItems()]
                self.parameter_changed(lambda value:f.update({key:value}),refs);self.highlight_body_targets(result)
            listing.itemSelectionChanged.connect(changed);form.addRow(tr(label),listing);self.widgets[key]=listing
            self.button('Pick '+label.lower()+' in workspace',lambda checked=False,key=key:self.enable_face_pick(key))
        def plane():self.reference_combo(form,'plane','Reference plane',self.plane_choices(),f.get('plane'),lambda value:f.update(plane=value))
        def axis():
            self.reference_combo(form,'axis','Axis',self.axis_choices(),f.get('axis'),lambda value:f.update(axis=value),True)
            ref=f.get('axis')
            if ref and ref.get('type')=='points':
                for key in ('start','end'):self.vector_fields(form,key,key.title(),ref[key],lambda value,key=key:ref.update({key:value}))
        def check(key,label):
            widget=QCheckBox(tr(label));widget.setChecked(f.get(key,False));widget.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update({key:value}),on));form.addRow(widget);self.widgets[key]=widget
        if kind=='body_move':
            for key,label in [('dx','Translation X'),('dy','Translation Y'),('dz','Translation Z')]:self.spin(form,key,label,f[key],lambda value,key=key:f.update({key:value}))
            axis();self.spin(form,'angle','Rotation angle',f['angle'],lambda value:f.update(angle=value));check('copy','Create copies')
        elif kind=='body_mirror':plane();check('keep_original','Keep originals')
        elif kind=='body_rectangular':
            plane()
            from PySide6.QtWidgets import QSpinBox
            for key,label in [('columns','Columns'),('rows','Rows')]:
                widget=QSpinBox();widget.setRange(1,200);widget.setValue(f[key]);widget.valueChanged.connect(lambda value,key=key:self.parameter_changed(lambda value:f.update({key:value}),value));form.addRow(tr(label),widget);self.widgets[key]=widget
            self.spacing_mode(form,f)
            extent=f.get('spacing_mode')=='extent'
            for key,label in [('spacing_x','X length' if extent else 'X spacing'),('spacing_y','Y length' if extent else 'Y spacing')]:self.spin(form,key,label,f[key],lambda value,key=key:f.update({key:value}))
        elif kind=='body_circular':
            axis()
            from PySide6.QtWidgets import QSpinBox
            widget=QSpinBox();widget.setRange(2,200);widget.setValue(f['count']);widget.valueChanged.connect(lambda value:self.parameter_changed(lambda value:f.update(count=value),value));form.addRow(tr('Total positions'),widget);self.widgets['count']=widget
            self.spin(form,'angle','Pattern angle',f['angle'],lambda value:f.update(angle=value));self.note('Full circles include the original and omit the duplicate 360° position. Partial patterns include both ends.')
        elif kind=='body_split':plane();self.combo(form,'keep','Keep side',['both','positive','negative'],f['keep'],lambda value:f.update(keep=value))
        elif kind=='body_combine':self.combo(form,'operation','Operation',['join','cut','intersect'],f['operation'],lambda value:f.update(operation=value));check('keep_tools','Keep tool bodies')
        self.highlight_body_targets(result);self.note('Only explicitly selected bodies are changed. Copies and patterns remain separate bodies; use Combine to join them.')
        self.button('Inspect / Repair references',self.open_reference_recovery)

    def highlight_body_targets(self,result):
        refs=self.draft.get('targets',[])+self.draft.get('tools',[]);selected=[]
        for ref in refs:
            try:selected.append(resolve_body(result,ref)[1])
            except ModelError:pass
        # Resolve body ownership once per body, rather than rematching each face.
        selected_faces=[face for body in selected for face in body.Faces()]
        self.workspace.solid_selected_faces={i for i,face in enumerate(self.workspace.faces) if any(face.isSame(candidate) for candidate in selected_faces)};self.workspace.update()
