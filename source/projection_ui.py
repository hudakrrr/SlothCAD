"""In-app Project/Include editor with explicit associative source selection."""
import copy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox,QListWidget,QListWidgetItem,QAbstractItemView,QCheckBox
from geometry import identifier,sample
from projection import resolve,break_link
from references import shape_reference
from i18n import tr

class ProjectionUI:
    def init_projection(self):
        self.projection_choices=[];self.workspace.projection_picked.connect(self.projection_pick)
        self.workspace.reference_highlight=[]

    def start_projection(self):
        self.set_tool('project')

    def projection_editor(self):
        result,sketches,frames=self.tool_context();form=self.form('Project / Include geometry')
        mode=QComboBox();mode.addItem(tr('Project'),'project');mode.addItem(tr('Include'),'include');mode.setToolTip(tr('Project flattens onto the sketch plane. Include keeps the geometry as it is.'));form.addRow(tr('Mode'),mode);self.widgets['projection_mode']=mode
        sources=QComboBox();sources.addItem(tr('Model edges'),None)
        for id_,s in sketches.items():sources.addItem(s['name'],id_)
        form.addRow(tr('Source'),sources);self.widgets['projection_source']=sources
        listing=QListWidget();listing.setSelectionMode(QAbstractItemView.ExtendedSelection);listing.setMaximumHeight(220);form.addRow(listing);self.widgets['projection_entities']=listing
        construction=QCheckBox(tr('Construction geometry'));form.addRow(construction);self.widgets['projection_construction']=construction
        def populate():
            listing.clear();self.projection_choices=[];id_=sources.currentData()
            if id_ is None:
                for i,edge in enumerate(result.val().Edges() if result else []):
                    item=QListWidgetItem(f'{tr("Edge")} {i+1} · {edge.geomType()} · {edge.Length():.3f} mm');listing.addItem(item)
                    self.projection_choices.append((dict(type='edge',edge=shape_reference(edge,'edge',result)),edge))
                from references import surface_reference
                for surface_id,body in frames.get('_surfaces',{}).items():
                    for i,edge in enumerate(body['shape'].Edges()):
                        listing.addItem(body['name']+' · '+tr('Edge')+' '+str(i+1));self.projection_choices.append((dict(type='edge',edge=surface_reference(edge,'edge',surface_id,frames)),edge))
            else:
                for i,e in enumerate(sketches[id_]['entities']):
                    listing.addItem(f'{i+1}. '+tr(e['kind'].title()));self.projection_choices.append((dict(type='sketch',sketch=id_,entities=[e['id']]),e))
        sources.currentIndexChanged.connect(populate);populate()
        def highlight():
            selected=[listing.row(item) for item in listing.selectedItems()];paths=[]
            for row in selected:
                ref,shape=self.projection_choices[row]
                if ref['type']=='edge':paths.append(np.array([shape.positionAt(float(t)).toTuple() for t in np.linspace(0,1,40)]))
                else:
                    if frames[ref['sketch']].get('spatial'):
                        edge=frames[ref['sketch']]['edges'][shape['id']]
                        paths.append(np.asarray([edge.Center().toTuple()]) if edge.ShapeType()=='Vertex' else np.asarray([edge.positionAt(float(t)).toTuple() for t in np.linspace(0,1,40)]));continue
                    from geometry import axes
                    o,u,v,n=axes(frames[ref['sketch']]);points=np.asarray(sample(shape));paths.append(o+points[:,0,None]*u+points[:,1,None]*v)
            self.workspace.reference_highlight=paths;self.workspace.update()
        listing.itemSelectionChanged.connect(highlight)
        self.button('Project selected geometry',self.apply_projection,True)
        self.note('What this does: it copies edges of your solid, or lines of another sketch, into THIS sketch so you can draw next to them and make profiles that line up exactly. Project flattens the geometry onto this sketch plane (use it for edges on other faces or at an angle); Include keeps it as it is (it should already lie in this plane). The copy stays linked and follows the source until you press Break link. How: click edges on the model, or pick them in the list, then press the button.')
        links=QComboBox()
        for i,link in enumerate(self.draft.get('projections',[])):links.addItem(f'{tr("Projected geometry")} {i+1}',link['id'])
        form.addRow(tr('Linked geometry'),links);self.widgets['projection_link']=links
        self.button('Break selected projection link',self.break_projection)
        self.button('Done',lambda:self.set_tool('select'))

    def projection_pick(self,index):
        if self.workspace.tool!='project':return
        listing=self.widgets.get('projection_entities');source=self.widgets.get('projection_source')
        if listing is None or source.currentData() is not None:return
        if not 0<=index<len(self.workspace.solid_edges):return
        edge=self.workspace.solid_edges[index][0]
        for row,(ref,shape) in enumerate(self.projection_choices):
            if ref['type']=='edge' and shape.isSame(edge):
                item=listing.item(row);item.setSelected(not item.isSelected());return
        self.show_status(tr('This edge is later than the sketch in history. Choose an earlier source.'))

    def apply_projection(self):
        try:
            listing=self.widgets['projection_entities'];selected=[listing.row(item) for item in listing.selectedItems()]
            if not selected:raise ValueError('Select at least one source edge or sketch entity.')
            candidate=copy.deepcopy(self.draft)
            for row in selected:
                source=self.projection_choices[row][0]
                candidate.setdefault('projections',[]).append(dict(id=identifier(),source=copy.deepcopy(source),mode=self.widgets['projection_mode'].currentData(),construction=self.widgets['projection_construction'].isChecked()))
            result,sketches,frames=self.tool_context()
            from solid_tools import plane_reference
            from geometry import sketch_frame
            frame=plane_reference(candidate['plane_ref'],result,frames) if candidate.get('plane_ref') else sketch_frame(candidate,result)
            projected=self.run_busy('Projecting associative geometry…',lambda _:resolve(candidate,result,sketches,frames,frame))
            self.sketch_change();self.draft['projections']=projected['projections'];self.install_constraint_sketch(projected)
        except Exception as error:self.constraint_error(error)

    def break_projection(self):
        key=self.draft['entities'][self.entity_index].get('projection') if self.entity_index is not None else self.widgets.get('projection_link').currentData() if self.widgets.get('projection_link') is not None else None
        try:
            result=break_link(self.draft,key);self.sketch_change();self.draft['projections']=result['projections'];self.install_constraint_sketch(result)
        except Exception as error:self.constraint_error(error)
