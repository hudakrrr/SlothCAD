"""File exchange actions and editable imported-solid features."""
import copy
from pathlib import Path
from PySide6.QtWidgets import QFileDialog,QInputDialog,QCheckBox
from exchange import import_step,import_dxf,export_dxf
from geometry import new_sketch,base_frame
from i18n import tr

class ExchangeUI:
 def import_step_file(self):
  if not self.abandon():return
  filename,_=QFileDialog.getOpenFileName(self,tr('Import STEP'),'',tr('STEP solid (*.step *.stp)'))
  if not filename:return
  try:
   before=len(self.doc.solids())
   feature=self.run_busy('Importing STEP…',lambda progress:import_step(filename));self.run_busy('Rebuilding model…',lambda progress:self.doc.commit(self.doc.features+[feature],progress))
   self.apply_import_colors(feature,before)
   self.selected=len(self.doc.features)-1;self.workspace.set_mode('model');self.refresh(True)
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
   replacement=self.run_busy('Importing STEP…',lambda progress:import_step(filename));self.draft.update(brep=replacement['brep'],source_name=replacement['source_name']);self.invalidate_preview();self.show_editor()
  except Exception as error:self.error(error)
