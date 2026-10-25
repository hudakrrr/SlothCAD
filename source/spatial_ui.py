"""Spatial curve editing with viewport picking and precise coordinate input."""
import copy
import numpy as np
from PySide6.QtWidgets import QListWidget,QCheckBox
from geometry import identifier,base_frame
from spatial_sketch import SPATIAL_TOOLS,materialize,sampled
from references import shape_reference
from i18n import tr
from ui_icons import icon

class SpatialUI:
    def init_spatial(self):
        for label,kind in [('3D sketch','sketch3d'),('Sketch on surface','surface_sketch')]:
            action=self.construction_menu.addAction(icon(kind),tr(label));action.setData(kind);action.setProperty('_icon_name',kind);action.setProperty('_i18n_text',label);action.triggered.connect(lambda checked=False,k=kind:self.start_spatial(k))
        self.spatial_points=[];self.spatial_kind='line';self.spatial_coordinate=[0.,0.,0.];self.spatial_undo=[];self.spatial_redo=[];self.workspace.spatial_point_picked.connect(self.add_spatial_point)

    def start_spatial(self,kind):
        if not self.abandon():return
        self.draft_index=None;self.selected=None;self.workspace.set_mode('model')
        self.draft=dict(id=identifier(),kind=kind,name=tr('3D sketch' if kind=='sketch3d' else 'Surface sketch'),enabled=True,entities=[],face=None,drawing_plane='XY',plane_offset=0.,snap=True)
        self.spatial_undo=[];self.spatial_redo=[];self.spatial_points=[];self.spatial_coordinate=[0.,0.,0.] if kind=='sketch3d' else [0.,0.];self.show_editor()

    def spatial_editor(self):
        f=self.draft;self.feature_action_row(f);form=self.form(tr('3D sketch' if f['kind']=='sketch3d' else 'Surface sketch'));self.name_field(form,f)
        result,sketches,frames=self.tool_context()
        if f['kind']=='surface_sketch':
            choices=[(self.face_label(i,face),shape_reference(face,'face',result)) for i,face in enumerate(result.val().Faces() if result else [])]
            for id_,body in frames.get('_surfaces',{}).items():
                local=__import__('cadquery').Workplane('XY').newObject([body['shape']])
                for i,face in enumerate(body['shape'].Faces()):choices.append((body['name']+' · '+self.face_label(i,face),__import__('references').surface_reference(face,'face',id_,frames)))
            self.reference_combo(form,'face','Supporting face',choices,f.get('face'),lambda value:self.spatial_face(value))
            self.button('Pick supporting face',lambda:self.enable_face_pick('face'))
            self.note('U and V are native surface parameters: angles on cylinders, lengths on planes. Curves are built on the surface, not on its tangent plane.')
        else:
            self.combo(form,'drawing_plane','Drawing plane',['XY','XZ','YZ'],f.get('drawing_plane','XY'),lambda value:f.update(drawing_plane=value));self.spin(form,'plane_offset','Plane offset',f.get('plane_offset',0),lambda value:f.update(plane_offset=value))
            self.note('Click to draw on the selected coordinate plane. Change plane or offset between points to create a 3D path. Coordinates below allow exact X/Y/Z input.')
        self.combo(form,'curve','Curve',['line','arc','spline','point'],self.spatial_kind,lambda value:self.change_spatial_kind(value))
        dimension=3 if f['kind']=='sketch3d' else 2
        if len(self.spatial_coordinate)!=dimension:self.spatial_coordinate=[0.]*dimension
        for i,label in enumerate('XYZ' if dimension==3 else 'UV'):
            self.spin(form,'coordinate'+label,label,self.spatial_coordinate[i],lambda value,i=i:self.spatial_coordinate.__setitem__(i,value))
        self.button('Add point from coordinates',lambda:self.add_spatial_point(self.spatial_coordinate))
        if self.spatial_kind=='spline':
            closed=QCheckBox(tr('Closed spline'));closed.setChecked(f.get('curve_closed',False));closed.toggled.connect(lambda on:f.update(curve_closed=on));form.addRow(closed)
            self.note(tr('Points')+': '+str(len(self.spatial_points)));self.button('Finish spline',self.finish_spatial_curve)
        self.button('End curve / clear pending points',self.clear_spatial_points)
        listing=QListWidget();listing.setMaximumHeight(130)
        for i,e in enumerate(f['entities']):listing.addItem(str(i+1)+'. '+tr(e['kind'].title()))
        form.addRow(tr('Geometry'),listing);self.widgets['spatial_entities']=listing
        def delete():
            row=listing.currentRow()
            if row>=0:self.spatial_checkpoint();f['entities'].pop(row);self.invalidate_preview();self.show_editor()
        self.button('Delete selected geometry',delete)
        self.refresh_spatial_preview()

    def spatial_face(self,value):self.draft['face']=value;self.spatial_points=[];self.refresh_spatial_preview()
    def change_spatial_kind(self,value):self.spatial_kind=value;self.spatial_points=[];self.show_editor()
    def clear_spatial_points(self):self.spatial_checkpoint();self.spatial_points=[];self.refresh_spatial_preview();self.show_editor()

    def spatial_snapshot(self):return dict(entities=copy.deepcopy(self.draft['entities']),points=copy.deepcopy(self.spatial_points),coordinate=copy.deepcopy(self.spatial_coordinate))
    def spatial_checkpoint(self):self.spatial_undo.append(self.spatial_snapshot());self.spatial_undo=self.spatial_undo[-100:];self.spatial_redo=[]
    def spatial_history(self,redo=False):
        source=self.spatial_redo if redo else self.spatial_undo;destination=self.spatial_undo if redo else self.spatial_redo
        if not source:return
        destination.append(self.spatial_snapshot());state=source.pop();self.draft['entities']=state['entities'];self.spatial_points=state['points'];self.spatial_coordinate=state['coordinate'];self.invalidate_preview();self.show_editor()

    def add_spatial_point(self,point):
        f=self.draft
        if not f or f['kind'] not in SPATIAL_TOOLS:return
        point=list(map(float,point));expected=3 if f['kind']=='sketch3d' else 2
        if len(point)!=expected:return
        if self.spatial_points and np.linalg.norm(np.asarray(point)-self.spatial_points[-1])<1e-8:return
        self.spatial_checkpoint();self.spatial_coordinate=list(point);self.spatial_points.append(point)
        required={'point':1,'line':2,'arc':3}.get(self.spatial_kind)
        if required and len(self.spatial_points)>=required:
            self.finish_spatial_curve(True);self.spatial_points=[point] if self.spatial_kind=='line' else []
        self.show_editor()

    def finish_spatial_curve(self,automatic=False):
        if not self.spatial_points:return
        if not automatic:self.spatial_checkpoint()
        candidate=copy.deepcopy(self.draft);candidate['entities'].append(dict(id=identifier(),kind=self.spatial_kind,points=copy.deepcopy(self.spatial_points),closed=bool(self.draft.get('curve_closed',False)) if self.spatial_kind=='spline' else False))
        result,sketches,frames=self.tool_context()
        try:self.run_busy('Building spatial curve…',lambda report:materialize(candidate,result,frames))
        except Exception as error:self.show_status(str(error));return
        self.draft['entities']=candidate['entities'];self.spatial_points=[];self.invalidate_preview();self.refresh_spatial_preview()

    def refresh_spatial_preview(self):
        try:
            result,sketches,frames=self.tool_context();frame=materialize(self.draft,result,frames);paths=sampled(self.draft,frame)
            if self.spatial_points:
                entity=dict(id='preview',kind='point' if len(self.spatial_points)==1 else 'line' if len(self.spatial_points)==2 else 'spline',points=self.spatial_points)
                temp=dict(self.draft,entities=[entity]);paths+=sampled(temp,materialize(temp,result,frames))
            self.workspace.reference_highlight=paths;self.workspace.spatial_face=frame.get('face')
        except Exception:self.workspace.reference_highlight=[];self.workspace.spatial_face=None
        self.workspace.spatial_edit=self.draft;self.workspace.update()
