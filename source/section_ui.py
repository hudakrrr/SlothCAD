"""Section view (a movable cutting plane through the model) and saved camera views."""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame,QHBoxLayout,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,QToolButton,
                               QInputDialog)
from i18n import tr

AXES={'XY':(0.,0.,1.),'XZ':(0.,1.,0.),'YZ':(1.,0.,0.)}
CAP_FILL='#f0ad45'


def clip_mesh(vertices,triangles,normal,distance):
    """Cut a triangle mesh with a plane, keeping ``normal . x <= distance``.

    Triangles that cross the plane are split exactly at it (dropping them whole left jagged
    walls). Returns ``(vertices, triangles, owner)``: ``owner`` is the original triangle of each
    new one, so per-triangle data (face ids, colours) can follow.
    """
    vertices=np.asarray(vertices,float);triangles=np.asarray(triangles)
    side=vertices@np.asarray(normal,float)-float(distance);inside=side<=1e-9
    flags=inside[triangles];full=flags.all(axis=1);crossing=np.flatnonzero(flags.any(axis=1)&~full)
    extra=[];new=[];owner=[];count=len(vertices)
    for t in crossing:
        corners=triangles[t];ring=[]
        for k in range(3):
            a,b=int(corners[k]),int(corners[(k+1)%3])
            if inside[a]:ring.append(a)
            if inside[a]!=inside[b]:
                r=side[a]/(side[a]-side[b]);extra.append(vertices[a]+(vertices[b]-vertices[a])*r);ring.append(count+len(extra)-1)
        for k in range(1,len(ring)-1):new.append((ring[0],ring[k],ring[k+1]));owner.append(t)
    kept=np.flatnonzero(full)
    if extra:vertices=np.vstack((vertices,np.asarray(extra)))
    if new:
        return vertices,np.vstack((triangles[kept],np.asarray(new,dtype=triangles.dtype))),np.concatenate((kept,np.asarray(owner,dtype=kept.dtype)))
    return vertices,triangles[kept],kept


def section_cap(shape,normal,distance):
    """The cut faces of ``shape`` on the section plane: ``[(triangles (n,3,3), edge polylines)]``.

    The kernel intersects the solid with the plane, so the cap is exact, holes included."""
    import cadquery as cq
    normal=np.asarray(normal,float);box=shape.BoundingBox()
    center=np.array([(box.xmin+box.xmax)/2,(box.ymin+box.ymax)/2,(box.zmin+box.zmax)/2])
    point=center-normal*(center@normal-distance);size=max(10.,box.DiagonalLength*2+10)
    common=shape.intersect(cq.Face.makePlane(size,size,cq.Vector(*point),cq.Vector(*normal)))
    pieces=[]
    for face in common.Faces():
        points,triangles=face.tessellate(max(.01,box.DiagonalLength/800))
        corners=np.array([[p.x,p.y,p.z] for p in points])
        edges=[np.array([e.positionAt(float(t)).toTuple() for t in np.linspace(0,1,2 if e.geomType()=='LINE' else 48)]) for e in face.Edges()]
        if len(triangles):pieces.append((corners[np.asarray(triangles)],edges))
    return pieces


def paint_section(w,p):
    """The cut face (when the camera looks at it), the plane outline and the drag arrow."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor,QPen,QBrush,QPolygonF,QPainter
    section=w.section
    if not section or w.mode=='sketch' or w.mesh_shape is None:return
    normal,distance=w.section_plane()
    # Everything kept lies behind the plane when the eye is on the removed side, so the cap is
    # in front of the model there and can be painted over it; from the other side it is hidden.
    eye=w.eye_distance();toward=w.rotation()[2]
    facing=float(toward@normal)>1e-6 if eye is None else float((np.asarray(w.center,float)+toward*eye)@normal)>distance
    cap=w.section_cap_for(section)
    if facing and cap:
        p.save();p.setRenderHint(QPainter.Antialiasing,False)
        fill=QColor(CAP_FILL);fill.setAlpha(225);p.setPen(Qt.NoPen)
        for triangles,_ in cap:
            screen=w.project(triangles.reshape(-1,3))[0].reshape(-1,3,2)
            p.setBrush(fill)
            for tri in screen:p.drawPolygon(QPolygonF([QPointF(*tri[0]),QPointF(*tri[1]),QPointF(*tri[2])]))
            hatch=QBrush(QColor(120,70,10,110),Qt.BDiagPattern);p.setBrush(hatch)
            for tri in screen:p.drawPolygon(QPolygonF([QPointF(*tri[0]),QPointF(*tri[1]),QPointF(*tri[2])]))
        p.setRenderHint(QPainter.Antialiasing,True)
        for _,edges in cap:
            for edge in edges:w.draw_polyline(p,w.project(edge)[0],'#b96c1a',2)
        p.restore()
    handle=w.section_handle()
    if handle is None:return
    base,tip,_=handle
    frame=section.get('frame')
    if frame is not None:
        corners=w.project(np.asarray(frame,float))[0]
        pen=QPen(QColor(CAP_FILL),1.4,Qt.DashLine);p.setPen(pen);p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(*c) for c in corners]))
    label=f"{tr('Section')}: {section.get('position',0.):+.3f}".rstrip('0').rstrip('.')+' mm'
    w.gizmo.draw_arrow(p,base,tip,QColor(CAP_FILL),w.section_drag is not None,w.section_drag is not None,label)
    w.gizmo.draw_anchor(p,base,QColor(CAP_FILL))


class SectionPanel(QFrame):
    """A small floating bar: which plane, where along its normal, and which side to keep."""
    def __init__(self,window):
        super().__init__(window.workspace);self.window=window;self.setObjectName('floatPanel')
        self.face_base=None
        layout=QHBoxLayout(self);layout.setContentsMargins(8,4,8,4);layout.setSpacing(8)
        title=QLabel(tr('Section analysis'));title.setProperty('_i18n_text','Section analysis');layout.addWidget(title)
        self.plane=QComboBox()
        for name,label in (('XY','XY plane'),('XZ','XZ plane'),('YZ','YZ plane')):self.plane.addItem(tr(label),name)
        layout.addWidget(self.plane)
        pick=QToolButton();pick.setText(tr('Pick face'));pick.setToolTip(tr('Click a flat face of the model: the section runs parallel to it'))
        pick.clicked.connect(window.pick_section_face);layout.addWidget(pick);self.pick_button=pick
        self.position=QDoubleSpinBox();self.position.setDecimals(3);self.position.setRange(-100000,100000);self.position.setSingleStep(1.)
        self.position.setSuffix(' mm');self.position.setToolTip(tr('Distance of the cut along the plane normal · or drag the arrow in the view'));layout.addWidget(self.position)
        self.flip=QCheckBox(tr('Keep the other side'));layout.addWidget(self.flip)
        close=QToolButton();close.setText('✕');close.setToolTip(tr('Close the section view'));close.clicked.connect(window.end_section);layout.addWidget(close)
        self.plane.currentIndexChanged.connect(self.changed_plane)
        self.position.valueChanged.connect(lambda *_:self.apply())
        self.flip.toggled.connect(lambda *_:self.apply())
        self.hide()

    def base(self):
        """``(axis, origin)``: the plane moves along ``axis``, position 0 passes through ``origin``."""
        name=self.plane.currentData()
        if name=='face' and self.face_base is not None:return self.face_base
        return np.asarray(AXES.get(name,AXES['XY']),float),np.zeros(3)

    def changed_plane(self,*_):
        self.position.blockSignals(True);self.position.setValue(self.window.section_default(*self.base()));self.position.blockSignals(False)
        self.apply()

    def use_face(self,axis,origin):
        self.face_base=(np.asarray(axis,float),np.asarray(origin,float))
        if self.plane.findData('face')<0:self.plane.addItem(tr('Picked face'),'face')
        self.plane.blockSignals(True);self.plane.setCurrentIndex(self.plane.findData('face'));self.plane.blockSignals(False)
        self.position.blockSignals(True);self.position.setValue(self.window.section_default(*self.face_base));self.position.blockSignals(False)
        self.apply()

    def apply(self):
        axis,origin=self.base();position=float(self.position.value())
        point=origin+axis*position;normal=-axis if self.flip.isChecked() else axis
        section=dict(normal=normal.tolist(),distance=float(normal@point),plane=self.plane.currentData(),position=position,
                     flip=self.flip.isChecked(),axis=axis.tolist())
        shape=self.window.workspace.mesh_shape
        if shape is not None:
            # The arrow sits where the plane crosses the middle of the model; a square shows the plane.
            box=shape.BoundingBox();center=np.array([(box.xmin+box.xmax)/2,(box.ymin+box.ymax)/2,(box.zmin+box.zmax)/2])
            anchor=center-axis*((center-point)@axis);half=max(5.,box.DiagonalLength*.6)
            helper=np.array([1.,0,0]) if abs(axis[0])<.9 else np.array([0,1.,0]);u=np.cross(axis,helper);u/=np.linalg.norm(u);v=np.cross(axis,u)
            section.update(anchor=anchor.tolist(),frame=[(anchor+half*(a*u+b*v)).tolist() for a,b in ((-1,-1),(1,-1),(1,1),(-1,1))])
        self.window.workspace.set_section(section)

    def place(self):
        workspace=self.window.workspace;self.adjustSize()
        # Bottom left, clear of the view bar in the bottom-right corner.
        self.move(16,max(8,workspace.height()-self.height()-14))
        self.raise_()


class SectionUI:
    def init_section(self):
        self.section_panel=SectionPanel(self);self.workspace.resized.connect(self.section_panel.place)
        self.workspace.section_dragged.connect(self.section_dragged)
        self.workspace.section_face_picked.connect(self.section_face_picked)

    def section_default(self,axis=None,origin=None):
        """The middle of the model along the plane's normal, so the first cut shows something."""
        shape=self.workspace.mesh_shape
        if shape is None:return 0.
        if isinstance(axis,str):axis,origin=np.asarray(AXES[axis],float),np.zeros(3)
        axis=np.asarray(axis if axis is not None else AXES['XY'],float);origin=np.zeros(3) if origin is None else np.asarray(origin,float)
        box=shape.BoundingBox()
        corners=np.array([[x,y,z] for x in (box.xmin,box.xmax) for y in (box.ymin,box.ymax) for z in (box.zmin,box.zmax)])
        along=(corners-origin)@axis
        return round(float(along.min()+along.max())/2,3)

    def section_dragged(self,position):
        self.section_panel.position.setValue(round(float(position),3))

    def pick_section_face(self):
        self.workspace.section_face_picking=True;self.workspace.setCursor(Qt.CrossCursor)
        self.show_status(tr('Click a flat face: the section plane is placed parallel to it. Esc cancels.'))

    def section_face_picked(self,index):
        w=self.workspace;w.section_face_picking=False;w.setCursor(Qt.ArrowCursor)
        if not 0<=index<len(w.faces):return
        face=w.faces[index]
        if face.geomType()!='PLANE':self.show_status(tr('That face is curved. Pick a flat face for the section plane.'));return
        center=face.Center();normal=face.normalAt(center)
        self.section_panel.use_face(np.array(normal.toTuple()),np.array(center.toTuple()))
        self.show_status(tr('Section parallel to the picked face · drag the arrow to move it.'))

    def toggle_section(self,on):
        if on:
            panel=self.section_panel;panel.plane.blockSignals(True);panel.position.blockSignals(True)
            panel.position.setValue(self.section_default(*panel.base()))
            panel.plane.blockSignals(False);panel.position.blockSignals(False)
            panel.show();panel.place();panel.apply()
            self.show_status(tr('Section analysis · drag the arrow or type the position; the cut face is shown hatched in orange.'))
        else:
            self.section_panel.hide();self.workspace.section_face_picking=False;self.workspace.set_section(None)
        for button in (getattr(self,'section_button',None),getattr(self,'inspect_buttons',{}).get('section')):
            if button is not None and button.isChecked()!=bool(on):
                button.blockSignals(True);button.setChecked(bool(on));button.blockSignals(False)

    def end_section(self):
        self.toggle_section(False)

    # ---- saved camera views ----------------------------------------------------------------
    def populate_view_selector(self,select=None):
        box=self.view_selector;box.blockSignals(True);box.clear()
        for name in ('Iso','Top','Front','Right'):box.addItem(tr(name),name)
        views=self.doc.display.get('views',{}) if isinstance(self.doc.display,dict) else {}
        for name in sorted(views):box.addItem('★ '+name,'view:'+name)
        box.addItem(tr('Save current view…'),'save-view')
        if views:box.addItem(tr('Delete saved view…'),'delete-view')
        index=box.findData(select) if select is not None else -1
        box.setCurrentIndex(max(0,index));box.blockSignals(False)

    def view_selected(self,index):
        data=self.view_selector.itemData(index)
        if data is None:return
        if data=='save-view':
            self.save_camera_view();return
        if data=='delete-view':
            self.delete_camera_view();return
        if isinstance(data,str) and data.startswith('view:'):
            self.restore_camera_view(data[5:]);return
        self.view_preset(data)

    def save_camera_view(self):
        w=self.workspace
        if w.mode=='sketch':
            self.show_status(tr('Views are saved from the 3D view, not while sketching.'));self.populate_view_selector();return
        name,ok=QInputDialog.getText(self,tr('Save current view'),tr('Name of the view'))
        name=name.strip()
        if not ok or not name:self.populate_view_selector();return
        state=dict(yaw=float(w.yaw),pitch=float(w.pitch),center=[float(v) for v in w.center],span=float(w.span),zoom=float(w.zoom),
                   pan=[float(v) for v in w.pan],perspective=bool(w.perspective))
        self.doc.display.setdefault('views',{})[name]=state
        self.populate_view_selector('view:'+name);self.update_title()
        self.show_status(tr('View saved:')+' '+name)

    def restore_camera_view(self,name):
        w=self.workspace;state=self.doc.display.get('views',{}).get(name)
        if state is None or w.mode=='sketch':return
        w.flush_motion();w.finish_camera_animation();start=w.camera_state()
        w.aligned=None;w.yaw=float(state['yaw']);w.pitch=float(state['pitch']);w.center=np.asarray(state['center'],float)
        w.span=float(state['span']);w.zoom=float(state['zoom']);w.pan=np.asarray(state['pan'],float)
        self.set_perspective(bool(state.get('perspective',False)))
        w.begin_camera_transition(start);w.update()

    def delete_camera_view(self):
        views=self.doc.display.get('views',{})
        if not views:return
        name,ok=QInputDialog.getItem(self,tr('Delete saved view'),tr('View'),sorted(views),0,False)
        if ok and name in views:
            del views[name]
            if not views:self.doc.display.pop('views',None)
            self.update_title()
        self.populate_view_selector()

    def set_perspective(self,on):
        on=bool(on)
        if on!=bool(self.doc.display.get('perspective',False)):
            if on:self.doc.display['perspective']=True
            else:self.doc.display.pop('perspective',None)
            self.update_title()
        w=self.workspace
        if w.perspective!=on:
            w.perspective=on;w.pick_cache=None;w.cache_key=None;w.background_key=None;w.update()
        button=getattr(self,'perspective_button',None)
        if button is not None and button.isChecked()!=on:
            button.blockSignals(True);button.setChecked(on);button.blockSignals(False)
