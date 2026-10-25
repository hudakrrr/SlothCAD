"""Component history editing inside the existing application workspace."""
import copy
from pathlib import Path
from PySide6.QtWidgets import QMenu,QCheckBox,QSlider,QFileDialog
from PySide6.QtCore import Qt
from geometry import identifier
from model import Document
from assemblies import components,assembled_features
from i18n import tr
from ui_icons import icon

class AssemblyUI:
    def init_assemblies(self):
        self.component_stack=[];self.assembly_menu=QMenu(tr('Assembly'),self)
        assembly_action=self.solid_menu.addMenu(self.assembly_menu);assembly_action.setIcon(icon('component'));assembly_action.setProperty('_icon_name','component');assembly_action.setProperty('_i18n_text','Assembly')
        for label,kind in [('New component','component'),('Joint','joint')]:
            action=self.assembly_menu.addAction(icon(kind),tr(label));action.setData(kind);action.setProperty('_icon_name',kind);action.setProperty('_i18n_text',label);action.triggered.connect(lambda checked=False,k=kind:self.start_assembly(k))
        action=self.assembly_menu.addAction(icon('component'),tr('Insert part from file…'));action.setData('insert_part');action.setProperty('_icon_name','component');action.setProperty('_i18n_text','Insert part from file…')
        action.triggered.connect(lambda checked=False:self.insert_part_file())
        self.return_component_action=self.assembly_menu.addAction(icon('component'),tr('Return to parent assembly'));self.return_component_action.triggered.connect(self.close_component)

    def start_assembly(self,kind):
        if not self.abandon():return
        self.draft_index=None;self.selected=None;self.workspace.set_mode('model')
        self.draft=dict(id=identifier(),kind=kind,name=tr('Component' if kind=='component' else 'Joint'),enabled=True)
        if kind=='component':self.draft.update(features=[],pose=dict(origin=[0.,0.,0.],axis=[0.,0.,1.],angle=0.),grounded=False)
        else:self.draft.update(moving=None,fixed=None,joint_type='revolute',value=0.,minimum=-360.,maximum=360.,anchor=[0.,0.,0.],direction=[0.,0.,1.],offset=[0.,0.,0.],translation=0.)
        self.show_editor()

    def assembly_editor(self):
        f=self.draft;self.feature_action_row(f);form=self.form(tr(f['kind'].title()));self.name_field(form,f)
        if f['kind']=='component':
            pose=f.setdefault('pose',dict(origin=[0.,0.,0.],axis=[0.,0.,1.],angle=0.))
            self.vector_fields(form,'origin','Position',pose['origin'],lambda value:pose.update(origin=value));self.vector_fields(form,'axis','Rotation axis',pose['axis'],lambda value:pose.update(axis=value));self.spin(form,'angle','Rotation',pose['angle'],lambda value:pose.update(angle=value))
            check=QCheckBox(tr('Grounded'));check.setChecked(f.get('grounded',False));check.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(grounded=value),on));form.addRow(check)
            self.note(tr('Features')+': '+str(len(f.get('features',[]))))
            def edit():
                id_=f['id'];self.apply_feature()
                if self.draft is None:
                    index=next((i for i,item in enumerate(self.doc.features) if item.get('id')==id_),None)
                    if index is not None:self.open_component(index)
            self.button('Edit component history',edit)
            if f.get('source_file'):
                self.note(tr('Source file')+': '+str(f['source_file']))
                self.button('Reload from source file',self.reload_part_source)
        else:
            registry=components(self.tool_context()[2]);choices=[(item['name'],id_) for id_,item in registry.items()]
            self.reference_combo(form,'moving','Moving component',choices,f.get('moving'),lambda value:f.update(moving=value))
            self.reference_combo(form,'fixed','Fixed component',[('Assembly origin',None)]+choices,f.get('fixed'),lambda value:f.update(fixed=value))
            self.combo(form,'joint_type','Joint type',['rigid','revolute','slider','cylindrical','mate'],f.get('joint_type','revolute'),lambda value:self.change_joint_type(value))
            if f['joint_type']=='mate':
                self.mate_fields(form,f)
                return
            for key,label in [('anchor','Joint origin'),('direction','Joint axis'),('offset','Alignment offset')]:self.vector_fields(form,key,label,f[key],lambda value,k=key:f.update({k:value}))
            if f['joint_type']!='rigid':
                for key,label in [('minimum','Minimum'),('maximum','Maximum'),('value','Position')]:self.spin(form,key,label,f[key],lambda value,k=key:f.update({k:value}))
                slider=QSlider(Qt.Horizontal);slider.setRange(0,1000);span=f['maximum']-f['minimum'];slider.setValue(round(1000*(f['value']-f['minimum'])/span) if span>0 else 0)
                def move(value):
                    position=f['minimum']+(f['maximum']-f['minimum'])*value/1000
                    self.parameter_changed(lambda number:f.update(value=number),position);self.widgets['value'].blockSignals(True);self.widgets['value'].setValue(position);self.widgets['value'].blockSignals(False)
                slider.valueChanged.connect(move);slider.sliderReleased.connect(self.preview_feature);form.addRow(tr('Motion preview'),slider);self.widgets['motion']=slider
                if f['joint_type']=='cylindrical':self.spin(form,'translation','Axial position',f.get('translation',0),lambda value:f.update(translation=value))
            self.note('The joint drives one component relative to the assembled position. Joint origin and axis are local to the fixed component, or world coordinates when using Assembly origin. Motion is limited; interference is not a collision constraint.')

    def change_joint_type(self,value):self.draft['joint_type']=value;self.show_editor()

    @staticmethod
    def baked_part_features(features):
        """The history of another project made self-contained: parameter expressions keep their last values."""
        baked=copy.deepcopy(features)
        def clean(items):
            for f in items:
                for key in ('expressions','expression_values'):f.pop(key,None)
                for c in f.get('constraints',[]) if isinstance(f.get('constraints'),list) else []:
                    if isinstance(c,dict) and c.get('kind')=='dimension':c.pop('expression',None)
                if f.get('kind')=='component':clean(f.get('features',[]))
        clean(baked)
        return baked

    def load_part_features(self,filename):
        document=self.run_busy('Opening part…',lambda report:Document.load(filename,progress=report))
        if document.build_error is not None:raise document.build_error
        return self.baked_part_features(document.features)

    def insert_part_file(self):
        """Insert another project as a component: its feature history is copied in (and can be reloaded)."""
        self.ensure_session()
        if not self.abandon():return
        filename,_=QFileDialog.getOpenFileName(self,tr('Insert part'),'',tr('SlothCAD projects (*.fcad)'))
        if not filename:return
        try:
            features=self.load_part_features(filename)
            component=dict(id=identifier(),kind='component',name=Path(filename).stem,enabled=True,features=features,
                           pose=dict(origin=[0.,0.,0.],axis=[0.,0.,1.],angle=0.),grounded=False,source_file=str(filename))
            self.run_busy('Rebuilding model…',lambda report:self.doc.commit(self.doc.features+[component],progress=report))
            self.selected=len(self.doc.features)-1;self.workspace.set_mode('model');self.refresh(True)
        except Exception as error:self.error(error)

    def reload_part_source(self):
        f=self.draft
        if f is None or not f.get('source_file'):return
        try:
            f['features']=self.load_part_features(f['source_file']);self.invalidate_preview();self.show_editor()
            self.show_status(tr('Reloaded from the source file. Apply to keep the update.'))
        except Exception as error:self.error(error)

    def mate_fields(self,form,f):
        """Mate: bring a face of the moving component against a face of another body."""
        def status(key):
            ref=f.get(key)
            if not ref:return tr('not picked yet')
            face=ref.get('face',{});c=face.get('center',[0,0,0])
            return f"{tr('picked')} · ({c[0]:g}, {c[1]:g}, {c[2]:g})"
        self.note(tr('1. Pick a face of the moving component, 2. pick the face it should touch.'))
        self.note(tr('Moving face')+': '+status('mate_moving'));self.button('Pick moving face',lambda:self.enable_face_pick('mate_moving'))
        self.note(tr('Target face')+': '+status('mate_target'));self.button('Pick target face',lambda:self.enable_face_pick('mate_target'))
        self.spin(form,'mate_offset','Gap',f.get('mate_offset',0.),lambda value:f.update(mate_offset=value))
        flush=QCheckBox(tr('Flush (faces point the same way)'));flush.setChecked(bool(f.get('flip',False)))
        flush.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(flip=value),bool(on)));form.addRow(flush)
        center=QCheckBox(tr('Center the faces on each other'));center.setChecked(bool(f.get('mate_center',True)))
        center.toggled.connect(lambda on:self.parameter_changed(lambda value:f.update(mate_center=value),bool(on)));form.addRow(center)
        self.note(tr('A mate is re-evaluated whenever the model is rebuilt, so the part follows if the faces move.'))

    def open_component(self,index):
        if not self.abandon():return
        if not 0<=index<len(self.doc.features) or self.doc.features[index]['kind']!='component':return
        f=self.doc.features[index]
        try:child=self.run_busy('Opening component history…',lambda report:Document(f.get('features',[]),progress=report,parameters=self.doc.parameters))
        except Exception as error:self.error(error);return
        child.display=copy.deepcopy(f.get('display',{}))
        self.component_stack.append(dict(document=self.doc,index=index,path=self.path,saved_features=self.saved_features,saved_display=self.saved_display,name=f['name']))
        self.doc=child;self.path=None;self.saved_features=copy.deepcopy(child.features);self.saved_display=copy.deepcopy(child.display);self.draft=None;self.draft_index=None;self.selected=None;self.workspace.set_mode('model');self.refresh(True)
        self.show_status(tr('Editing component')+': '+' / '.join(entry['name'] for entry in self.component_stack))

    def close_component(self):
        if not self.component_stack or not self.abandon():return
        entry=self.component_stack[-1];parent=entry['document'];candidate=copy.deepcopy(parent.features);candidate[entry['index']]['features']=copy.deepcopy(self.doc.features);candidate[entry['index']]['display']=copy.deepcopy(self.doc.display)
        try:self.run_busy('Rebuilding assembly…',lambda report:parent.commit(candidate,progress=report))
        except Exception as error:self.error(error);return
        self.component_stack.pop();self.doc=parent;self.path=entry['path'];self.saved_features=entry['saved_features'];self.saved_display=entry['saved_display'];self.selected=entry['index'];self.workspace.set_mode('model');self.refresh(True)

    def assembled_snapshot(self):return assembled_features(self.component_stack,self.doc)

    def save_assembly(self,path):
        features=self.assembled_snapshot();doc=self.run_busy('Saving assembly…',lambda report:Document(features,progress=report,parameters=self.component_stack[0]['document'].parameters));doc.display=copy.deepcopy(self.component_stack[0]['document'].display);doc.save(path)
        self.component_stack[0]['document']._saved_parameters=copy.deepcopy(doc.parameters)
        root=self.component_stack[0];root['path']=Path(path);root['saved_features']=copy.deepcopy(features);root['saved_display']=copy.deepcopy(doc.display)
        self.saved_features=copy.deepcopy(self.doc.features);self.saved_display=copy.deepcopy(self.doc.display);self.update_title();return True
