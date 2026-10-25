"""Section view (a movable cutting plane through the model) and saved camera views."""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame,QHBoxLayout,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,QToolButton,
                               QInputDialog)
from i18n import tr

AXES={'XY':(0.,0.,1.),'XZ':(0.,1.,0.),'YZ':(1.,0.,0.)}


class SectionPanel(QFrame):
    """A small floating bar: which plane, where along its normal, and which side to keep."""
    def __init__(self,window):
        super().__init__(window.workspace);self.window=window;self.setObjectName('floatPanel')
        layout=QHBoxLayout(self);layout.setContentsMargins(8,4,8,4);layout.setSpacing(8)
        title=QLabel(tr('Section'));title.setProperty('_i18n_text','Section');layout.addWidget(title)
        self.plane=QComboBox()
        for name,label in (('XY','XY plane'),('XZ','XZ plane'),('YZ','YZ plane')):self.plane.addItem(tr(label),name)
        layout.addWidget(self.plane)
        self.position=QDoubleSpinBox();self.position.setDecimals(3);self.position.setRange(-100000,100000);self.position.setSingleStep(1.)
        self.position.setSuffix(' mm');layout.addWidget(self.position)
        self.flip=QCheckBox(tr('Keep the other side'));layout.addWidget(self.flip)
        close=QToolButton();close.setText('✕');close.setToolTip(tr('Close the section view'));close.clicked.connect(window.end_section);layout.addWidget(close)
        self.plane.currentIndexChanged.connect(self.changed_plane)
        self.position.valueChanged.connect(lambda *_:self.apply())
        self.flip.toggled.connect(lambda *_:self.apply())
        self.hide()

    def changed_plane(self,*_):
        self.position.blockSignals(True);self.position.setValue(self.window.section_default(self.plane.currentData()));self.position.blockSignals(False)
        self.apply()

    def apply(self):
        axis=np.asarray(AXES[self.plane.currentData()]);distance=float(self.position.value())
        if self.flip.isChecked():axis,distance=-axis,-distance
        self.window.workspace.set_section(dict(normal=axis.tolist(),distance=distance,plane=self.plane.currentData(),position=float(self.position.value()),flip=self.flip.isChecked()))

    def place(self):
        workspace=self.window.workspace;self.adjustSize()
        self.move(max(8,(workspace.width()-self.width())//2-120),max(8,workspace.height()-self.height()-14))
        self.raise_()


class SectionUI:
    def init_section(self):
        self.section_panel=SectionPanel(self);self.workspace.resized.connect(self.section_panel.place)

    def section_default(self,plane):
        """The middle of the model along the plane's normal, so the first cut shows something."""
        shape=self.workspace.mesh_shape
        if shape is None:return 0.
        box=shape.BoundingBox();axis={'XY':2,'XZ':1,'YZ':0}[plane]
        low=(box.xmin,box.ymin,box.zmin)[axis];high=(box.xmax,box.ymax,box.zmax)[axis]
        return round((low+high)/2,3)

    def toggle_section(self,on):
        if on:
            panel=self.section_panel;panel.plane.blockSignals(True);panel.position.blockSignals(True)
            panel.position.setValue(self.section_default(panel.plane.currentData()))
            panel.plane.blockSignals(False);panel.position.blockSignals(False)
            panel.show();panel.place();panel.apply()
            self.show_status(tr('Section view · move the plane with the position box; the cut side is shown in orange.'))
        else:
            self.section_panel.hide();self.workspace.set_section(None)
        button=getattr(self,'section_button',None)
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
