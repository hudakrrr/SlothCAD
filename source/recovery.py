"""Atomic, per-session autosaves, including unapplied sketch edits."""
import copy,json,os,tempfile,threading,time,uuid,sys,math
from platform_support import replace_file
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,QStandardPaths,Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QListWidget,QLabel,QDialogButtonBox
from model import Document,ModelError
from i18n import tr

def atomic_json(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,temp=tempfile.mkstemp(prefix='.writing-',dir=path.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
  replace_file(temp,path)
 finally:
  if os.path.exists(temp):os.unlink(temp)

def process_alive(pid):
 if isinstance(pid,bool) or not isinstance(pid,int) or pid<=0:return False
 if sys.platform=='win32':
  import ctypes
  from ctypes import wintypes
  kernel=ctypes.WinDLL('kernel32',use_last_error=True)
  kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
  kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
  kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
  handle=kernel.OpenProcess(0x1000,False,pid)
  if not handle:return ctypes.get_last_error()!=87  # Invalid PID is absent; access denial is conservatively live.
  try:
   exit_code=wintypes.DWORD();ok=kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code));return not ok or exit_code.value==259
  finally:kernel.CloseHandle(handle)
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
 except PermissionError:return True

def recovery_files(root,include_live=True):
 result=[]
 for p in Path(root).glob('*.json'):
  try:
   data=json.loads(p.read_text(encoding='utf-8'));assert data['recovery_format']=='slothcad-autosave' and data['version']==1 and isinstance(data['features'],list)
   timestamp=data.get('timestamp',0)
   if isinstance(timestamp,bool) or not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp):continue
   if data.get('source_path') is not None and not isinstance(data['source_path'],str):continue
   if not include_live and process_alive(data.get('process_id')):continue
   result.append((p,data))
  except (OSError,ValueError,KeyError,AssertionError,TypeError):continue
 return sorted(result,key=lambda pair:pair[1].get('timestamp',0),reverse=True)

class Autosave(QObject):
 failed=Signal(str)
 def __init__(self,window):
  super().__init__(window);self.window=window;self.root=Path(os.environ.get('SLOTHCAD_RECOVERY_DIR') or str(Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))/'recovery'));self.path=self.root/(uuid.uuid4().hex+'.json');self.recovered_path=None;self.last=None;self.busy=False;self.closed=False;self.lock=threading.Lock()
  self.timer=QTimer(self);self.timer.setInterval(30000);self.timer.timeout.connect(self.tick);self.timer.start();self.failed.connect(lambda message:window.show_status(tr('Autosave failed:')+' '+message))
 def snapshot(self):
  w=self.window
  data=dict(recovery_format='slothcad-autosave',version=1,process_id=os.getpid(),timestamp=time.time(),source_path=str(w.path) if w.path else None,features=copy.deepcopy(w.doc.features),display=copy.deepcopy(w.doc.display),parameters=copy.deepcopy((w.component_stack[0]['document'] if getattr(w,'component_stack',[]) else w.doc).parameters),pending=copy.deepcopy(w.doc.pending_features),draft=copy.deepcopy(w.draft),draft_index=w.draft_index,precise=copy.deepcopy(w.precise_draft),precise_baseline=copy.deepcopy(w.precise_baseline),precise_redo=copy.deepcopy(w.precise_redo),entity_index=w.entity_index,sketch_undo=copy.deepcopy(w.sketch_undo),sketch_redo=copy.deepcopy(w.sketch_redo),point_redo=copy.deepcopy(w.workspace.point_redo),tool=w.workspace.tool,points=copy.deepcopy(w.workspace.points))
  if w.draft and w.draft.get('kind') in ('sketch3d','surface_sketch'):
   data['spatial_points']=copy.deepcopy(w.spatial_points);data['spatial_kind']=w.spatial_kind;data['spatial_undo']=copy.deepcopy(w.spatial_undo);data['spatial_redo']=copy.deepcopy(w.spatial_redo)
  if getattr(w,'component_stack',[]):
   data['features']=w.assembled_snapshot();data['display']=copy.deepcopy(w.component_stack[0]['document'].display);data['component_path']=[entry['index'] for entry in w.component_stack];data['source_path']=str(w.component_stack[0]['path']) if w.component_stack[0]['path'] else None;data['component_display']=copy.deepcopy(w.doc.display)
  return data
 def tick(self):
  if self.closed or self.busy or self.window.loading:return
  if not (self.window.dirty() or self.window.has_draft() or self.window.doc.pending_features is not None):return
  data=self.snapshot();self.busy=True
  def write():
   try:
    signature=dict(data);signature.pop('timestamp',None)
    if signature!=self.last:
     with self.lock:
      if not self.closed:atomic_json(self.path,data);self.last=signature
   except Exception as error:self.failed.emit(str(error))
   finally:self.busy=False
  threading.Thread(target=write,daemon=True).start()
 def cleanup(self):
  self.timer.stop()
  with self.lock:
   self.closed=True;self.path.unlink(missing_ok=True)
   if self.recovered_path is not None:self.recovered_path.unlink(missing_ok=True)

class RecoveryUI:
 def recover_autosave(self,startup=False):
  items=self.run_busy('Looking for autosave recovery…',lambda progress:recovery_files(self.autosave.root,include_live=False))
  items=[item for item in items if item[0]!=self.autosave.path]
  if not items:
   if not startup:self.show_status('No recoverable autosaves were found.')
   return
  dialog=QDialog(self);dialog.setWindowTitle(tr('Recover autosave'));dialog.resize(560,320);layout=QVBoxLayout(dialog)
  label=QLabel(tr('Choose an interrupted session. Your original project file is unchanged.'));label.setWordWrap(True);layout.addWidget(label);listing=QListWidget();layout.addWidget(listing)
  for p,data in items:listing.addItem((Path(data['source_path']).name if data.get('source_path') else tr('Untitled'))+' · '+time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(data.get('timestamp',0))))
  listing.setCurrentRow(0);buttons=QDialogButtonBox(QDialogButtonBox.Open|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Open).setText(tr('Recover'));buttons.button(QDialogButtonBox.Cancel).setText(tr('Later' if startup else 'Cancel'));buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
  # Without a way to discard, stale autosaves reappear at every startup.
  discard=buttons.addButton(tr('Discard selected'),QDialogButtonBox.DestructiveRole);discard_all=buttons.addButton(tr('Discard all'),QDialogButtonBox.DestructiveRole)
  def remove(rows):
   for row in sorted(rows,reverse=True):
    try:items[row][0].unlink(missing_ok=True)
    except OSError as error:self.show_status(tr('Could not delete autosave:')+' '+str(error));continue
    del items[row];listing.takeItem(row)
   if not items:dialog.reject()
   else:listing.setCurrentRow(0)
  discard.clicked.connect(lambda:remove([listing.currentRow()]) if listing.currentRow()>=0 else None)
  discard_all.clicked.connect(lambda:remove(range(len(items))))
  layout.addWidget(buttons)
  if dialog.exec()!=QDialog.Accepted or not items or listing.currentRow()<0:return
  if not self.begin_new_project():return
  self.stack.setCurrentWidget(self.workspace);self.set_project_chrome(True)
  try:self.restore_autosave(items[listing.currentRow()][1]);self.autosave.recovered_path=items[listing.currentRow()][0];self.autosave.tick()
  except Exception as error:self.error(error)
 def restore_autosave(self,data):
  from geometry import sketch_frame,validate_entity
  source_path=data.get('source_path')
  if source_path is not None and not isinstance(source_path,str):raise ModelError('Invalid recovered project path.')
  recovered_path=Path(source_path) if source_path else None
  parameters=data.get('parameters') if isinstance(data.get('parameters'),dict) else {}
  doc=self.run_busy('Recovering autosave…',lambda progress:Document(data['features'],progress,parameters=parameters));doc.display=copy.deepcopy(data.get('display',{}));doc.pending_features=copy.deepcopy(data.get('pending'))
  stack=[];context=data.get('component_path',[])
  if not isinstance(context,list) or len(context)>32:raise ModelError('Invalid recovered component context.')
  for position in context:
   if not isinstance(position,int) or isinstance(position,bool) or not 0<=position<len(doc.features) or doc.features[position]['kind']!='component':raise ModelError('Invalid recovered component history.')
   f=doc.features[position];stack.append(dict(document=doc,index=position,path=recovered_path if not stack else None,saved_features=[],saved_display={},name=f['name']));doc=Document(f.get('features',[]),parameters=parameters);doc.display=copy.deepcopy(f.get('display',{}))
  if stack:doc.display=copy.deepcopy(data.get('component_display',doc.display))
  draft=copy.deepcopy(data.get('draft'));index=data.get('draft_index')
  if index is not None and (not isinstance(index,int) or not 0<=index<len(doc.features)):raise ModelError('Invalid recovered feature index.')
  if draft and draft.get('kind')=='sketch':
   for e in draft['entities']:validate_entity(e)
   from solid_tools import plane_reference
   result,sketches,frames=doc.preview(doc.features[:index]) if index is not None else (doc.solid,doc.sketches,doc.frames)
   frame=plane_reference(draft['plane_ref'],result,frames) if draft.get('plane_ref') else sketch_frame(draft,result)
  else:frame=None
  if draft and draft.get('kind') in ('sketch3d','surface_sketch'):
   from spatial_sketch import materialize
   state=doc.preview(doc.features[:index]) if index is not None else (doc.solid,doc.sketches,doc.frames)
   materialize(draft,state[0],state[2])
  self.spatial_points=copy.deepcopy(data.get('spatial_points',[]));self.spatial_kind=data.get('spatial_kind','line');self.spatial_undo=copy.deepcopy(data.get('spatial_undo',[]));self.spatial_redo=copy.deepcopy(data.get('spatial_redo',[]))
  self.component_stack=stack;self.doc=doc;self.path=None if stack else recovered_path;self.saved_features=[];self.saved_display={};self.selected=index;self.history_preview_index=None;self.draft=draft;self.draft_index=index;self.precise_draft=copy.deepcopy(data.get('precise'));self.precise_baseline=copy.deepcopy(data.get('precise_baseline'));self.precise_redo=copy.deepcopy(data.get('precise_redo'));self.entity_index=data.get('entity_index');self.sketch_undo=copy.deepcopy(data.get('sketch_undo',[]));self.sketch_redo=copy.deepcopy(data.get('sketch_redo',[]));self.refresh(True)
  if frame:
   self.workspace.set_mode('sketch',draft,frame);self.workspace.tool=data.get('tool','select');self.workspace.points=copy.deepcopy(data.get('points',[]));self.workspace.point_redo=copy.deepcopy(data.get('point_redo',[]));self.sketch_bar.show()
  else:self.workspace.set_mode('model');self.sketch_bar.hide()
  self.show_editor();self.show_status('Recovered session. Save the project to keep your changes.')
