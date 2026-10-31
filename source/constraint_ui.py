"""Sketch constraint interaction, asynchronous drag previews and annotations."""
import copy
import math
import threading
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMenu, QLabel, QListWidget, QComboBox, QDoubleSpinBox,QLineEdit,QCheckBox,QDialog,QVBoxLayout,QTableWidget,QTableWidgetItem,QPushButton,QDialogButtonBox
from constraints import (LABELS,new_constraint,add_constraint,solve,drag,reference_value,
                         ConstraintConflict,handles,edges,point_ref,Layout,constraint_status,unfix,resolve_dimensions)
from i18n import tr
from ui_icons import icon
from geometry import sample

INSTRUCTIONS={
 'fix':'Pick a curve to fix the whole entity, or a point to fix only that point.',
 'unfix':'Pick geometry to remove its Fix constraints.',
 'midpoint':'Pick a point, then the straight edge whose midpoint it should follow.',
 'concentric':'Pick two circles or arcs.',
 'collinear':'Pick two straight edges on the same supporting line.',
 'point_on_object':'Pick a point, then a straight edge, circle or arc.',
 'coincident':'Pick two points, or a point and a line/circle. Click the origin to anchor a point.',
 'horizontal':'Pick a straight edge.', 'vertical':'Pick a straight edge.',
 'parallel':'Pick two straight edges.', 'perpendicular':'Pick two straight edges.',
 'equal':'Pick two straight edges, or two circles / arcs.',
 'symmetry':'Pick two points, then the straight mirror axis.',
 'tangent':'Pick a straight edge and a circle / arc, or two circles / arcs.',
 'dimension':'Pick an edge/circle, two points, or two straight edges; then choose the dimension.'}

class ConstraintUI:
    def init_constraints(self):
        self.constraint_kind='coincident';self.constraint_refs=[];self.constraint_feedback='';self.constraint_conflicts=[]
        self.constraint_menu=QMenu(self)
        for kind,label in LABELS.items():
            action=self.constraint_menu.addAction(tr(label));action.setData(kind);action.setProperty('_icon_name',kind);action.setIcon(icon(kind))
            action.triggered.connect(lambda checked=False,k=kind:self.start_constraint(k))
        from tool_palette import bind_dropdown
        bind_dropdown(self,'constraint',self.tool_buttons['constraint'],self.constraint_menu)
        w=self.workspace
        w.constraint_picked.connect(self.constraint_pick)
        w.sketch_drag_started.connect(self.begin_sketch_drag)
        w.sketch_drag_moved.connect(self.move_sketch_drag)
        w.sketch_drag_finished.connect(self.finish_sketch_drag)
        w.sketch_drag_cancelled.connect(self.cancel_sketch_drag)
        w.constraint_selected.connect(self.constraint_label_selected)
        w.constraint_delete_requested.connect(self.delete_constraint)
        w.constraint_edit_requested.connect(self.edit_constraint_label)
        self.drag_baseline=None;self.drag_generation=0;self.drag_result=None;self.drag_running=False;self.drag_target=None
        self.drag_timer=QTimer(self);self.drag_timer.setInterval(16);self.drag_timer.timeout.connect(self.poll_sketch_drag)

    def start_constraint(self,kind):
        self.set_tool('constraint')
        if self.workspace.tool!='constraint':return
        self.constraint_kind=kind;self.constraint_refs=[];self.constraint_feedback='';self.constraint_conflicts=[]
        self.workspace.constraint_kind=kind;self.workspace.constraint_refs=self.constraint_refs;self.show_editor()

    def constraint_pick(self,ref):
        if ref in self.constraint_refs:self.constraint_refs.remove(ref)
        else:self.constraint_refs.append(ref)
        self.constraint_feedback='';self.show_editor();self.workspace.update()

    def constraint_error(self,error):
        self.constraint_feedback=tr(str(error));self.constraint_conflicts=getattr(error,'constraint_ids',[])
        self.workspace.constraint_feedback=self.constraint_feedback;self.show_status(self.constraint_feedback)
        self.show_editor();self.workspace.update()

    def install_constraint_sketch(self,result):
        self.draft['entities']=result['entities'];self.draft['constraints']=result.get('constraints',[])
        self.workspace.sketch_cache.pop(self.draft['id'],None)
        self.entity_index=None;self.precise_draft=None;self.precise_baseline=None;self.workspace.selected_entity=None
        self.constraint_feedback='';self.constraint_conflicts=[];self.workspace.constraint_feedback=''
        self.workspace.update();self.show_editor()

    def apply_sketch_constraint(self):
        try:
            value=self.constraint_value.value() if self.constraint_kind=='dimension' else None
            mode=self.constraint_mode.currentData() if self.constraint_kind=='dimension' else None
            if self.constraint_kind=='unfix':
                linked={e['id'] for e in self.draft['entities'] if e.get('projection')}
                if any(r.get('entity') in linked for r in self.constraint_refs):raise ValueError('Break the projection link before editing this geometry.')
                result=unfix(self.draft,self.constraint_refs)
                if result['constraints']==self.draft.get('constraints',[]):raise ValueError('The selected geometry is not fixed.')
                self.sketch_change();self.constraint_refs.clear();self.install_constraint_sketch(result);return
            c=new_constraint(self.draft,self.constraint_kind,self.constraint_refs,value,mode,
                reference=self.constraint_reference.isChecked() if self.constraint_kind=='dimension' else False,
                expression=self.constraint_expression.text().strip() or None if self.constraint_kind=='dimension' else None,
                name=self.constraint_name.text().strip() or None if self.constraint_kind=='dimension' else None)
            snapshot=copy.deepcopy(self.draft)
            result=self.run_busy('Solving sketch constraints…',lambda report:add_constraint(snapshot,c))
            self.sketch_change();self.constraint_refs.clear();self.install_constraint_sketch(result)
            self.show_status(LABELS[c['kind']]+' constraint added.')
        except Exception as error:self.constraint_error(error)

    def selected_constraint(self):
        row=self.constraint_list.currentRow()
        return self.draft.get('constraints',[])[row] if row>=0 else None

    def constraint_by_id(self,constraint_id):
        if not self.draft or self.draft.get('kind')!='sketch' or not constraint_id:return None
        return next((c for c in self.draft.get('constraints',[]) if c.get('id')==constraint_id),None)

    def constraint_label_selected(self,constraint_id):
        """A dimension or constraint label was clicked in the sketch (empty id: cleared)."""
        c=self.constraint_by_id(constraint_id)
        self.entity_index=None;self.precise_draft=None
        self.show_editor()
        if c is not None:
            what=tr('Dimension') if c['kind']=='dimension' else tr(LABELS.get(c['kind'],c['kind']))
            self.show_status(what+' '+tr('selected · Delete removes it (the sketch stays) · double-click edits the value' if c['kind']=='dimension' else 'selected · Delete removes it (the sketch stays)'))

    def delete_constraint(self,constraint_id):
        c=self.constraint_by_id(constraint_id)
        self.workspace.selected_constraint=None
        if c is None:self.workspace.update();return
        if c.get('projection_lock'):self.show_status(tr('Break the projection link before editing this geometry.'));return
        self.sketch_change();self.draft['constraints']=[item for item in self.draft['constraints'] if item is not c]
        self.constraint_feedback='';self.constraint_conflicts=[];self.workspace.constraint_feedback='';self.workspace.constraint_refs=[]
        self.workspace.update();self.show_editor()
        self.show_status(tr('Dimension deleted; the sketch geometry is kept.') if c['kind']=='dimension' else tr('Constraint deleted; the sketch geometry is kept.'))

    def edit_constraint_label(self,constraint_id):
        c=self.constraint_by_id(constraint_id)
        if c is not None and c['kind']=='dimension':self.edit_sketch_dimension(c)

    def remove_sketch_constraint(self):
        c=self.selected_constraint()
        if c is None:return
        self.delete_constraint(c.get('id')) if c.get('id') else None

    def edit_sketch_dimension(self,c=None):
        c=c if c is not None else self.selected_constraint()
        if c is None or c['kind']!='dimension':return
        from PySide6.QtWidgets import QInputDialog
        if c.get('reference'):return
        expression=None
        if c.get('expression'):
            expression,ok=QInputDialog.getText(self,tr('Edit dimension'),tr('Expression'),text=c['expression']);value=c['value']
        else:
            value,ok=QInputDialog.getDouble(self,tr('Edit dimension'),'Value ('+('degrees' if c['mode']=='angle' else 'mm')+')',c['value'],-1e9,1e9,6)
        if not ok:return
        try:
            snapshot=copy.deepcopy(self.draft)
            replacement=new_constraint(snapshot,'dimension',c['refs'],value,c['mode']);replacement['id']=c['id']
            for key in ('name','expression','reference'):
                if key in c:replacement[key]=c[key]
            if expression is not None:replacement['expression']=expression
            snapshot['constraints']=[replacement if item['id']==c['id'] else item for item in snapshot['constraints']]
            result=self.run_busy('Solving sketch constraints…',lambda report:solve(snapshot,seeds=[r.get('entity') for r in c['refs']]))
            self.sketch_change();self.install_constraint_sketch(result)
        except Exception as error:self.constraint_error(error)

    def sketch_parameters(self):
        dialog=QDialog(self);dialog.setWindowTitle(tr('Sketch parameters'));dialog.resize(540,360)
        layout=QVBoxLayout(dialog);table=QTableWidget(0,2);table.setHorizontalHeaderLabels([tr('Name'),tr('Expression')]);table.horizontalHeader().setStretchLastSection(True);layout.addWidget(table)
        for name,value in self.draft.get('parameters',{}).items():
            row=table.rowCount();table.insertRow(row);table.setItem(row,0,QTableWidgetItem(name));table.setItem(row,1,QTableWidgetItem(str(value)))
        add=QPushButton(tr('Add parameter'));add.clicked.connect(lambda:table.insertRow(table.rowCount()));layout.addWidget(add)
        remove=QPushButton(tr('Delete selected parameter'));remove.clicked.connect(lambda:table.removeRow(table.currentRow()));layout.addWidget(remove)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        def apply():
            try:
                parameters={}
                for row in range(table.rowCount()):
                    name=table.item(row,0);value=table.item(row,1)
                    if name is None or value is None:raise ValueError('Enter both a parameter name and an expression.')
                    key=name.text().strip()
                    if key in parameters:raise ValueError('Duplicate parameter name: '+key)
                    parameters[key]=value.text().strip()
                candidate=copy.deepcopy(self.draft);candidate['parameters']=parameters
                result=self.run_busy('Solving sketch constraints…',lambda _:solve(candidate))
                self.sketch_change();self.draft['parameters']=parameters;self.install_constraint_sketch(result);dialog.accept()
            except Exception as error:self.constraint_error(error)
        buttons.accepted.connect(apply);dialog.exec()

    def constraint_editor(self):
        fingerprint=repr((self.draft['entities'],self.draft.get('constraints',[]),self.draft.get('parameters',{})))
        if getattr(self,'constraint_status_key',None)!=fingerprint:
            snapshot=copy.deepcopy(self.draft)
            self.constraint_status_value=self.run_busy('Checking sketch degrees of freedom…',lambda _:constraint_status(snapshot));self.constraint_status_key=fingerprint
        status=self.constraint_status_value
        self.workspace.constrained_entities=set(status.get('constrained_entities',[]))
        self.note(tr('Fully constrained') if status['fully_constrained'] else tr('Degrees of freedom')+f": {status['degrees_of_freedom']}")
        self.button('Sketch parameters',self.sketch_parameters)
        active=self.workspace.tool=='constraint'
        if active:
            self.note('<b>'+tr(LABELS[self.constraint_kind])+'</b><br>'+tr(INSTRUCTIONS[self.constraint_kind]))
            for i,r in enumerate(self.constraint_refs):
                index=next((j+1 for j,e in enumerate(self.draft['entities']) if e['id']==r.get('entity')),0)
                self.note(f'{i+1}. '+('Origin' if not index else f'Geometry {index} · {r["kind"]} · {r.get("point",r.get("edge",""))}'))
            if self.constraint_kind=='dimension':
                f=self.form('Driving dimension');self.constraint_mode=QComboBox()
                refs=self.constraint_refs
                modes=[('Length','length')]
                if len(refs)==1 and refs[0]['kind']=='circle':modes=[('Diameter','diameter'),('Radius','radius')]
                elif len(refs)==1 and refs[0]['kind']=='line':modes=[('Length','length'),('Angle to X','angle')]
                elif len(refs)==2 and all(r['kind']=='point' for r in refs):modes=[('Distance','distance'),('Horizontal distance','dx'),('Vertical distance','dy')]
                elif len(refs)==2 and all(r['kind']=='line' for r in refs):modes=[('Angle','angle')]
                for text,data in modes:self.constraint_mode.addItem(tr(text),data)
                f.addRow('Type',self.constraint_mode);self.constraint_value=QDoubleSpinBox();self.constraint_value.setDecimals(6);self.constraint_value.setRange(-1e9,1e9);f.addRow('Value',self.constraint_value)
                def default_value():
                    mode=self.constraint_mode.currentData();value=10.
                    try:
                        vals=[reference_value(self.draft['entities'],r) for r in refs]
                        if mode=='length':value=float(np.linalg.norm(vals[0][1]-vals[0][0]))
                        elif mode in ('diameter','radius'):value=vals[0][1]*(2 if mode=='diameter' else 1)
                        elif mode in ('distance','dx','dy'):
                            delta=vals[1]-vals[0];value=float(np.linalg.norm(delta)) if mode=='distance' else float(delta[0 if mode=='dx' else 1])
                        elif mode=='angle':
                            a=vals[0][1]-vals[0][0];base=0 if len(vals)==1 else math.atan2(*(vals[1][1]-vals[1][0])[::-1])
                            value=math.degrees(math.atan2(a[1],a[0]) if len(vals)==1 else base-math.atan2(a[1],a[0]))
                    except (ValueError,IndexError,TypeError):pass
                    self.constraint_value.setSuffix(' °' if mode=='angle' else ' mm');self.constraint_value.setValue(value)
                self.constraint_mode.currentIndexChanged.connect(default_value);default_value()
                self.constraint_reference=QCheckBox(tr('Reference dimension'));f.addRow(self.constraint_reference)
                self.constraint_expression=QLineEdit();self.constraint_expression.setPlaceholderText(tr('Optional expression, e.g. pitch * 2'));f.addRow(tr('Expression'),self.constraint_expression)
                self.constraint_name=QLineEdit();self.constraint_name.setPlaceholderText(tr('Optional dimension name'));f.addRow(tr('Name'),self.constraint_name)
                self.constraint_reference.toggled.connect(lambda value:(self.constraint_value.setEnabled(not value),self.constraint_expression.setEnabled(not value)))
            self.constraint_apply_button=self.button('Apply constraint',self.apply_sketch_constraint,True)
            self.button('Clear picks',lambda:self.start_constraint(self.constraint_kind))
            self.button('Done',lambda:self.set_tool('select'))
        if self.constraint_feedback:
            label=QLabel(self.constraint_feedback);label.setWordWrap(True);label.setStyleSheet('color: #d65b55;');self.editor_layout.addWidget(label)
        constraints=self.draft.get('constraints',[])
        if constraints or active:
            self.constraint_list=QListWidget();self.constraint_list.setMaximumHeight(130)
            for c in constraints:
                units='°' if c.get('mode')=='angle' else 'mm'
                text=tr(LABELS[c['kind']])+(f' · {c["value"]:g} {units}' if 'value' in c else '')
                if c.get('name'):text=c['name']+' = '+text
                if c.get('reference'):text+=' · '+tr('Reference')
                if c.get('expression'):text+=' · '+c['expression']
                self.constraint_list.addItem(text)
                if c['id'] in self.constraint_conflicts:self.constraint_list.item(self.constraint_list.count()-1).setForeground(Qt.red)
            self.editor_layout.addWidget(QLabel(tr('Constraints')));self.editor_layout.addWidget(self.constraint_list)
            chosen=self.workspace.selected_constraint
            row=next((i for i,c in enumerate(constraints) if chosen and c.get('id')==chosen),-1)
            if row>=0:self.constraint_list.setCurrentRow(row)
            self.constraint_list.itemClicked.connect(lambda item:self.highlight_constraint())
            self.edit_constraint_button=self.button('Edit selected dimension',self.edit_sketch_dimension);self.edit_constraint_button.setEnabled(False)
            self.remove_constraint_button=self.button('Remove selected constraint',self.remove_sketch_constraint);self.remove_constraint_button.setEnabled(False)
            if row>=0:self.highlight_constraint()

    def highlight_constraint(self):
        c=self.selected_constraint();self.workspace.constraint_refs=c['refs'] if c else []
        self.workspace.selected_constraint=c.get('id') if c else None
        self.edit_constraint_button.setEnabled(c is not None and c['kind']=='dimension' and not c.get('reference'));self.remove_constraint_button.setEnabled(c is not None);self.workspace.update()

    def begin_sketch_drag(self,ref,start):
        self.drag_generation+=1;self.drag_baseline=copy.deepcopy(self.draft);self.drag_ref=ref;self.drag_start=start
        self.drag_target=None;self.drag_result=None;self.drag_running=False;self.workspace.sketch_drag_preview=True
        self.drag_timer.start()

    def cancel_sketch_drag(self):
        if self.drag_baseline is None:return
        baseline=self.drag_baseline;self.drag_baseline=None;self.drag_generation+=1;self.drag_timer.stop()
        self.workspace.sketch_drag_preview=False;self.install_constraint_sketch(baseline)

    def move_sketch_drag(self,position):
        if self.drag_baseline is None:return
        self.drag_target=list(position);self.drag_generation+=1
        self.poll_sketch_drag()

    def poll_sketch_drag(self):
        if self.drag_baseline is None:return
        if self.drag_result is not None:
            generation,result=self.drag_result;self.drag_result=None;self.drag_running=False
            if generation==self.drag_generation and not isinstance(result,Exception):self.preview_sketch_drag(result)
        if not self.drag_running and self.drag_target is not None:
            generation=self.drag_generation;snapshot=self.drag_baseline;ref=self.drag_ref;position=self.drag_target;start=self.drag_start
            self.drag_target=None;self.drag_running=True
            def work():
                try:result=drag(snapshot,ref,position,start)
                except Exception as error:result=error
                if self.drag_baseline is snapshot:self.drag_result=(generation,result)
            threading.Thread(target=work,daemon=True).start()

    def preview_sketch_drag(self,result):
        self.draft['entities']=result['entities'];w=self.workspace
        samples=[(i,e,sample(e)) for i,e in enumerate(result['entities'])]
        w.sketch_cache[self.draft['id']]=(repr(result['entities']),[],samples,set());w.update()

    def finish_sketch_drag(self,position):
        if self.drag_baseline is None:return
        baseline=self.drag_baseline;ref=self.drag_ref;start=self.drag_start
        self.drag_baseline=None;self.drag_generation+=1;self.drag_timer.stop();self.workspace.sketch_drag_preview=False
        try:
            result=self.run_busy('Solving sketch constraints…',lambda report:drag(baseline,ref,position,start))
            if result['entities']!=baseline['entities']:
                self.sketch_undo.append(self.sketch_snapshot(baseline));self.sketch_undo=self.sketch_undo[-100:];self.sketch_redo=[]
            self.install_constraint_sketch(result)
        except Exception as error:
            self.draft['entities']=baseline['entities'];self.constraint_error(error)


def pick_reference(workspace,position,kind,exclude=()):
    """Screen-distance picking; endpoints outrank edges when a point is needed."""
    sketch=workspace.active;entities=sketch['entities'];local=workspace.local_at(position,workspace.active_frame)
    if local is None:return None
    layout=Layout(entities)
    def value_of(ref):return getattr(layout,ref['kind'])(ref,layout.x)
    candidates=[];scale=workspace.scale();point_kinds=('coincident','symmetry','dimension','drag','midpoint','point_on_object','fix','unfix')
    if kind in point_kinds and not(kind in ('midpoint','point_on_object') and exclude):
        refs=[r for e in entities for r in handles(e)]
        if kind!='drag' and (kind!='dimension' or exclude and exclude[0]['kind']=='point'):refs.insert(0,point_ref(None,'origin'))
        for ref in refs:
            if ref in exclude:continue
            distance=float(np.linalg.norm(value_of(ref)-local))*scale
            if distance<=9:candidates.append((distance,ref))
        if candidates:return min(candidates,key=lambda pair:pair[0])[1]
    for e in entities:
        for ref in edges(e):
            if ref in exclude:continue
            if kind in ('horizontal','vertical','parallel','perpendicular','symmetry','collinear') and ref['kind']!='line':continue
            if kind=='concentric' and ref['kind']!='circle':continue
            value=value_of(ref)
            if ref['kind']=='circle':
                if e['kind']=='arc':
                    from geometry import nearest_on_entity
                    distance=float(np.linalg.norm(nearest_on_entity(e,local)-local))     # only the drawn part of the arc counts
                else:distance=abs(float(np.linalg.norm(local-value[0]))-value[1])
            else:
                a,b=value;direction=b-a;t=np.clip(float((local-a)@direction)/max(float(direction@direction),1e-20),0,1)
                distance=float(np.linalg.norm(local-(a+t*direction)))
            if distance*scale<=9:candidates.append((distance*scale,ref))
    if candidates:return min(candidates,key=lambda pair:pair[0])[1]
    if kind in ('drag','fix','unfix'):
        index=workspace.entity_at(position)
        if index is not None:return dict(kind='entity',entity=entities[index]['id'])
    return None


def paint_constraints(w,p):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor,QPen
    entities=w.active['entities'];frame=w.active_frame;layout=Layout(entities)
    def value_of(ref):return getattr(layout,ref['kind'])(ref,layout.x)
    def screen(point):return w.project_local([point],frame)[0]
    def line(a,b,color='#43a9c2',width=2):
        p.setPen(QPen(QColor(color),width));p.drawLine(QPointF(*a),QPointF(*b))
    w.constraint_label_rects=[]
    chosen=getattr(w,'selected_constraint',None)
    selected=next((c for c in w.active.get('constraints',[]) if c.get('id')==chosen),None)
    highlighted=list(w.constraint_refs)+[r for r in (selected or {}).get('refs',[]) if r not in w.constraint_refs]
    for ref in highlighted:
        try:
            value=value_of(ref)
            if ref['kind']=='point':
                xy=screen(value);p.setPen(QPen(QColor('#43bfd4'),2));p.setBrush(Qt.NoBrush);p.drawEllipse(QPointF(*xy),6,6)
            elif ref['kind']=='line':line(screen(value[0]),screen(value[1]),'#43bfd4',4)
            elif ref['kind']=='circle':
                owner=layout.entities.get(ref.get('entity'))
                if owner is not None and owner['kind']=='arc':points=sample(owner,64)
                else:
                    center,radius=value;angles=np.linspace(0,2*math.pi,96)
                    points=center+radius*np.column_stack((np.cos(angles),np.sin(angles)))
                w.draw_polyline(p,w.project_local(points,frame),'#43bfd4',3)
        except (ValueError,KeyError):continue
    symbols={'coincident':'○','horizontal':'H','vertical':'V','parallel':'∥','perpendicular':'⊥','equal':'=','symmetry':'↔','tangent':'T','fix':'F','midpoint':'M','concentric':'◎','collinear':'CL','point_on_object':'PO'}
    for c in w.active.get('constraints',[]):
        try:
            if c['kind']=='fix' and c['refs'][0]['kind']=='entity':
                selected=layout.entities[c['refs'][0]['entity']];points=sample(selected);xy=screen(points[0]);p.setPen(QColor(w.theme_color('#087ba5')));w.static_text(p,float(xy[0]+7),float(xy[1]-7),'F');continue
            values=[value_of(r) for r in c['refs']];ref=c['refs'][0];v=values[0]
            anchor=v if ref['kind']=='point' else (v[0]+v[1])/2 if ref['kind']=='line' else v[0]+[v[1],0]
            xy=screen(anchor)
            if c['kind']=='dimension':
                if ref['kind']=='line' and len(values)==1 and c['mode']=='length':
                    a,b=map(screen,v);d=b-a;normal=np.array([-d[1],d[0]])/max(np.linalg.norm(d),1)*18
                    line(a,a+normal);line(b,b+normal);line(a+normal,b+normal);xy=(a+b)/2+normal
                elif len(values)==2 and all(r['kind']=='point' for r in c['refs']):
                    a,b=map(screen,values);line(a,b);xy=(a+b)/2
                prefix={'radius':'R ','diameter':'Ø '}.get(c['mode'],'')
                label=prefix+f'{c["value"]:g} '+('°' if c['mode']=='angle' else 'mm')
                if c.get('reference'):label='('+label+')'
            else:label=symbols[c['kind']]
            # Every label is a clickable target: click selects it, Delete removes it (the
            # geometry stays), double-click edits a dimension's value.
            from PySide6.QtCore import QRectF
            metrics=p.fontMetrics();x=float(xy[0]+7);y=float(xy[1]-7)
            rect=QRectF(x-4,y-metrics.ascent()-2,metrics.horizontalAdvance(label)+8,metrics.height()+4)
            active=c.get('id') is not None and c.get('id')==chosen
            if c['kind']=='dimension' or active:
                fill=QColor('#f0ad45') if active else QColor(w.theme_color('#eaf0f5'));fill.setAlpha(235 if active else 215)   # the canvas colour: readable in every theme
                p.setPen(QPen(QColor('#b96c1a' if active else w.theme_color('#087ba5')),1.2));p.setBrush(fill)
                p.drawRoundedRect(rect,4,4);p.setBrush(Qt.NoBrush)
            p.setPen(QColor('#10151c') if active else QColor(w.theme_color('#087ba5')));w.static_text(p,x,y,label)
            if c.get('id') is not None:w.constraint_label_rects.append((rect,c['id']))
        except (ValueError,KeyError,TypeError):continue
