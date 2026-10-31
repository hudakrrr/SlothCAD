"""File exchange actions and editable imported-solid features."""
import copy
import json
import math
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QTimer
from PySide6.QtWidgets import (QFileDialog,QInputDialog,QCheckBox,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,
                               QDialogButtonBox,QProgressBar,QPushButton)
from exchange import import_dxf,export_dxf,trust_payload
from legacy_model import ModelError
from geometry import new_sketch,base_frame
from i18n import tr
from ui_icons import icon
import platform_support

# (key, label, description, icon) for the File > Import… / Export… format choosers.
IMPORT_FORMATS=(
 ('step','STEP solid (*.step *.stp)','Exact solid bodies with names and colours','import_step'),
 ('stl','STL mesh (*.stl)','Closed triangle mesh, converted to a solid','import_stl'),
 ('iges','IGES solid (*.iges *.igs)','Older exact CAD format','import_solid'),
 ('obj','OBJ mesh (*.obj)','Closed triangle mesh, converted to a solid','import_stl'),
 ('3mf','3MF model (*.3mf)','3D-printing package, converted to a solid','import_stl'),
 ('dxf','DXF drawing (*.dxf)','2D geometry, imported as a sketch','import_dxf'),
)
EXPORT_FORMATS=(
 ('step','STEP solid (*.step *.stp)','Exact solids for other CAD programs','export_step'),
 ('stl','STL mesh (*.stl)','Triangle mesh for 3D printing','export_stl'),
 ('3mf','3MF model (*.3mf)','3D-printing package with colours','export_stl'),
 ('glb','glTF binary (*.glb)','Mesh for viewers, web and rendering','export_stl'),
 ('dxf','DXF sketch (*.dxf)','The selected or current sketch as 2D geometry','export_dxf'),
 ('drawing','Drawing (*.dxf *.svg)','Projected 2D views of the model','export_dxf'),
)
MESH_IMPORT_FILTERS={'stl':'STL mesh (*.stl)','iges':'IGES solid (*.iges *.igs)','obj':'OBJ mesh (*.obj)','3mf':'3MF model (*.3mf)'}

WORKER_SCRIPT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'exchange_worker.py')
WORKER_SHARE=.92     # the worker covers this much of the bar; adding the feature to the model the rest


class ImportCancelled(Exception):
 pass


class ImportProgressDialog(QDialog):
 """Stage, percentage, elapsed time and Cancel for an import running in ``exchange_worker``.

 The worker reports exact fractions where it can; during kernel calls that cannot report
 progress (reading a STEP file, sewing a mesh) the bar eases toward the end of that stage using
 the worker's time estimate, slowing down instead of overshooting.
 """
 def __init__(self,parent,filename):
  super().__init__(parent);self.setWindowTitle(tr('Importing'));self.setModal(True);self.setMinimumWidth(440)
  layout=QVBoxLayout(self)
  name=QLabel(Path(filename).name);name.setStyleSheet('font-weight:600');layout.addWidget(name)
  self.stage_label=QLabel(tr('Starting…'));layout.addWidget(self.stage_label)
  self.bar=QProgressBar();self.bar.setRange(0,1000);self.bar.setFormat('%p%');self.bar.setTextVisible(True);layout.addWidget(self.bar)
  row=QHBoxLayout();self.time_label=QLabel('');self.time_label.setObjectName('subtle');row.addWidget(self.time_label);row.addStretch(1)
  self.cancel_button=QPushButton(tr('Cancel'));self.cancel_button.clicked.connect(self.reject);row.addWidget(self.cancel_button);layout.addLayout(row)
  self.started=time.monotonic();self.stage_started=self.started
  self.start=self.end=self.estimate=0.;self.exact=0.;self.shown=0.
 def set_stage(self,text,start,end,estimate=0.,count=None):
  text=tr(text)
  if count is not None:text=text.replace('{count}',f'{int(count):,}')
  self.stage_label.setText(text);self.start,self.end,self.estimate=float(start),float(end),float(estimate)
  self.exact=max(self.exact,self.start);self.stage_started=time.monotonic();self.tick()
 def set_fraction(self,fraction):
  self.exact=max(self.exact,float(fraction));self.tick()
 def tick(self):
  now=time.monotonic();value=self.exact
  if self.estimate>0 and self.end>self.start:
   eased=1-math.exp(-(now-self.stage_started)/self.estimate)
   value=max(value,self.start+(self.end-self.start)*.95*eased)
  self.shown=max(self.shown,min(1.,value))     # never moves backwards
  self.bar.setValue(int(round(self.shown*1000)))
  elapsed=int(now-self.started);self.time_label.setText(tr('Elapsed:')+f' {elapsed//60}:{elapsed%60:02d}')


class ExchangeUI:
 def import_in_background(self,filename):
  """Run ``exchange.import_model`` in a separate process behind a progress dialog.

  Returns ``(feature, dialog)`` with the dialog still open, so the caller can show the model
  being rebuilt in it, then close it. Raises ``ImportCancelled`` or ``ModelError``.
  """
  from limit_search import _python
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  process=subprocess.Popen([_python(),'-u',WORKER_SCRIPT,str(filename)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,creationflags=flags)
  messages=queue.Queue()
  def read():
   try:
    for line in process.stdout:
     if line.startswith('@@'):messages.put(line[2:])
   except Exception:pass
   try:process.stdout.close()
   except Exception:pass
   messages.put(None)
  threading.Thread(target=read,name='SlothCAD-import-reader',daemon=True).start()
  dialog=ImportProgressDialog(self,filename);outcome={}
  def poll():
   while True:
    try:line=messages.get_nowait()
    except queue.Empty:break
    if line is None:
     if not outcome:outcome['error']='The import stopped unexpectedly.'
     dialog.accept();return
    try:message=json.loads(line)
    except ValueError:continue
    if 'stage' in message:dialog.set_stage(message['stage'],message['start']*WORKER_SHARE,message['end']*WORKER_SHARE,message.get('estimate',0.),message.get('count'))
    elif 'at' in message:dialog.set_fraction(message['at']*WORKER_SHARE)
    elif 'result' in message or 'error' in message:outcome.update(message)
   dialog.tick()
  timer=QTimer(dialog);timer.timeout.connect(poll);timer.start(40)
  try:accepted=dialog.exec()==QDialog.Accepted
  finally:
   timer.stop()
   if process.poll() is None:
    process.kill()
   try:process.wait(5)
   except Exception:pass
  if not accepted:dialog.deleteLater();raise ImportCancelled()
  if 'error' in outcome:dialog.deleteLater();raise ModelError(outcome['error'])
  feature=outcome['result'];trust_payload(feature['brep'])
  return feature,dialog
 def import_feature_file(self,filename):
  """Import a STEP, IGES or mesh file in the background and add it to the model as a feature."""
  try:feature,dialog=self.import_in_background(filename)
  except ImportCancelled:self.show_status(tr('Import cancelled.'));return False
  try:
   # Building the model and its display stays in this process; keep the dialog up meanwhile.
   # No Python timer here: run_busy keeps the interface thread in C++ while the model is rebuilt,
   # and Qt animates the busy bar by itself.
   dialog.set_stage('Adding it to the model…',WORKER_SHARE,1.);dialog.cancel_button.setEnabled(False)
   dialog.bar.setRange(0,0);dialog.setModal(False);dialog.show()
   before=len(self.doc.solids())
   self.run_busy('Rebuilding model…',lambda progress:self.doc.commit(self.doc.features+[feature],progress))
   self.apply_import_colors(feature,before)
   self.selected=len(self.doc.features)-1;self.workspace.set_mode('model');self.refresh(True)
   self.show_status(tr('Imported')+' '+Path(filename).name)
   return True
  finally:dialog.close();dialog.deleteLater()
 def choose_file_format(self,title,formats,setting):
  """Ask which file type to import or export; returns its key or None. The last choice is preselected."""
  try:last=platform_support.settings().value(setting,'')
  except Exception:last=''
  dialog=QDialog(self);dialog.setWindowTitle(tr(title));layout=QVBoxLayout(dialog)
  layout.addWidget(QLabel(tr('Choose a file type:')))
  listing=QListWidget();listing.setIconSize(QSize(32,32));listing.setSpacing(2)
  for key,label,description,icon_name in formats:
   item=QListWidgetItem(icon(icon_name),tr(label)+'\n'+tr(description));item.setData(Qt.UserRole,key);listing.addItem(item)
   if key==last:listing.setCurrentItem(item)
  if listing.currentRow()<0:listing.setCurrentRow(0)
  listing.setMinimumSize(380,min(len(formats),6)*48+8)
  layout.addWidget(listing)
  buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText(tr('Continue'))
  buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);listing.itemActivated.connect(lambda item:dialog.accept())
  layout.addWidget(buttons)
  if dialog.exec()!=QDialog.Accepted or listing.currentItem() is None:return None
  key=listing.currentItem().data(Qt.UserRole)
  try:settings=platform_support.settings();settings.setValue(setting,key);settings.sync()
  except Exception:pass
  return key
 def import_file(self):
  key=self.choose_file_format('Import',IMPORT_FORMATS,'exchange/import_format')
  if key is None:return
  if key=='step':self.import_step_file()
  elif key=='dxf':self.import_dxf_file()
  else:self.import_model_file(tr(MESH_IMPORT_FILTERS[key]))
 def export_file(self):
  key=self.choose_file_format('Export',EXPORT_FORMATS,'exchange/export_format')
  if key is None:return
  if key=='dxf':self.export_dxf_file()
  elif key=='drawing':self.export_drawing_file()
  else:self.export_format(key)
 def import_step_file(self):
  if not self.abandon():return
  filename,_=QFileDialog.getOpenFileName(self,tr('Import STEP'),'',tr('STEP solid (*.step *.stp)'))
  if not filename:return
  try:self.import_feature_file(filename)
  except Exception as error:self.error(error)
 def import_dxf_file(self):
  sketching=self.workspace.mode=='sketch' and self.draft is not None
  if not sketching and not self.abandon():return
  filename,_=QFileDialog.getOpenFileName(self,tr('Import DXF'),'',tr('DXF drawing (*.dxf)'))
  if not filename:return
  try:
   entities,unsupported,units=self.run_busy('Importing DXF…',lambda progress:import_dxf(filename))
   if sketching:
    if self.precise_changed() and not self.apply_entity():return
    self.sketch_change();self.draft['entities'].extend(entities);self.workspace.update();self.show_editor()
   else:
    plane,ok=QInputDialog.getItem(self,tr('Import DXF'),tr('Sketch plane'),['XY','XZ','YZ'],0,False)
    if not ok:return
    sketch=new_sketch(base_frame(plane),Path(filename).stem);sketch['entities']=entities;self.run_busy('Rebuilding model…',lambda progress:self.doc.commit(self.doc.features+[sketch],progress));self.selected=len(self.doc.features)-1;self.refresh(True)
   message=tr('DXF imported.')
   if units==0:message+=' '+tr('Unitless DXF treated as millimeters.')
   if unsupported:message+=' '+tr('Skipped unsupported DXF entities:')+' '+', '.join(unsupported)
   self.show_status(message)
  except Exception as error:self.error(error)
 def export_dxf_file(self):
  if self.workspace.mode=='sketch' and self.draft:
   if self.precise_changed() and not self.apply_entity():return
   entities=copy.deepcopy(self.draft['entities'])
  else:
   sketches=[f for f in self.doc.features if f['kind']=='sketch']
   if not sketches:self.error('Create a sketch before exporting DXF.');return
   selected=self.doc.features[self.selected] if self.selected is not None else None
   if selected and selected['kind']=='sketch':sketch=selected
   else:
    choice,ok=QInputDialog.getItem(self,tr('Export DXF'),tr('Sketch'),[f'{i+1}. {s["name"]}' for i,s in enumerate(sketches)],0,False)
    if not ok:return
    sketch=sketches[int(choice.split('.')[0])-1]
   entities=copy.deepcopy(sketch['entities'])
  filename,_=QFileDialog.getSaveFileName(self,tr('Export DXF'),'sketch.dxf',tr('DXF drawing (*.dxf)'))
  if not filename:return
  if Path(filename).suffix.lower()!='.dxf':filename+='.dxf'
  try:self.run_busy('Exporting DXF…',lambda progress:export_dxf(filename,entities));self.show_status(f'Exported {filename}')
  except Exception as error:self.error(error)
 def imported_feature_editor(self):
  f=self.draft;self.feature_action_row(f);form=self.form('Imported STEP');self.name_field(form,f);self.note(f.get('source_name','STEP'))
  self.spin(form,'scale','Import scale',f.get('scale',1),lambda v:f.update(scale=v),True)
  for key,label in [('dx','Translation X'),('dy','Translation Y'),('dz','Translation Z'),('angle','Rotation angle')]:self.spin(form,key,label,f.get(key,0),lambda v,key=key:f.update({key:v}))
  self.button('Replace STEP source…',self.replace_step_source);self.button('Inspect / Repair references',self.open_reference_recovery)
 def replace_step_source(self):
  filename,_=QFileDialog.getOpenFileName(self,tr('Replace STEP source'),'',tr('STEP solid (*.step *.stp)'))
  if not filename:return
  try:
   replacement,dialog=self.import_in_background(filename);dialog.close();dialog.deleteLater()
   self.draft.update(brep=replacement['brep'],source_name=replacement['source_name']);self.invalidate_preview();self.show_editor()
  except ImportCancelled:self.show_status(tr('Import cancelled.'))
  except Exception as error:self.error(error)
