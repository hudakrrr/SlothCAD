"""Cheap, orthographic viewport manipulators; geometry is committed by Apply."""
import math
import os
import threading
import time
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QEvent, QTimer, QObject, Signal
from PySide6.QtGui import QColor, QPen, QPolygonF, QPainterPath, QPainter, QBrush, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

# On-screen distance one drag increment covers; the value step is the 1/2/5 number at that size.
DRAG_STEP_PIXELS = 4
EXACT_DELAY_MS = 160
EXACT_DRAG_MS = 35      # while dragging the exact outline is refreshed this often when the rebuild is quick
EXACT_QUICK_MS = 180    # a rebuild slower than this falls back to the quick preview until the value rests
# The kernel rebuild behind the exact outline runs on a worker thread so the window never
# freezes while dragging. Tests and offscreen runs stay synchronous and deterministic.
ASYNC_EXACT = os.environ.get('QT_QPA_PLATFORM', '') not in ('offscreen', 'minimal') and os.environ.get('SLOTHCAD_SYNC_EXACT', '') != '1'
from i18n import tr

_CORE_SHIFTS = ((0, 0), (.6, 0), (0, .6))
_GLOW_SHIFTS = ((-1.6, 0), (1.6, 0), (0, -1.6), (0, 1.6))

def stroke_fast(p, path, color, dashed=False, glow=0, core=3):
    """Draw a preview outline as a few 1 px strokes.

    Qt strokes wide antialiased lines through its slow general stroker: long preview edges cost
    a few hundred milliseconds per repaint, which is what made dragging feel laggy. One pixel
    strokes stay on the fast line rasteriser (about a millisecond); a few slightly shifted copies
    give the same visual weight and a soft glow.
    """
    p.save()
    if glow:
        haze = QColor(color); haze.setAlpha(glow); p.setPen(QPen(haze, 1.0))
        for dx, dy in _GLOW_SHIFTS:
            p.translate(dx, dy); p.drawPath(path); p.translate(-dx, -dy)
    p.setPen(QPen(color, 1.0, Qt.DashLine if dashed else Qt.SolidLine))
    for dx, dy in _CORE_SHIFTS[:max(1, core)]:
        p.translate(dx, dy); p.drawPath(path); p.translate(-dx, -dy)
    p.restore()

COLORS=('#ee6269','#4bc889','#579df4')


class _ExactSignals(QObject):
    done = Signal(object)    # (token, value, key, outcome, milliseconds), queued to the UI thread


class ViewportGizmo:
    def __init__(self,workspace):
        self.workspace=workspace;self.state=None;self.dragging=False;self.consume_release=False;self.axis=0;self.hover=None
        self._exact_signals=_ExactSignals(workspace);self._exact_signals.done.connect(self._exact_done)
        self._exact_running=False;self._exact_again=False;self._exact_token=0
        self.editor=QDoubleSpinBox(workspace);self.editor.setObjectName('gizmoDistance')
        self.editor.setDecimals(4);self.editor.setRange(-100000,100000);self.editor.setSuffix(' mm')
        self.editor.setKeyboardTracking(False);self.editor.setFixedSize(166,34)
        self.editor.valueChanged.connect(self.typed);self.editor.installEventFilter(workspace);self.editor.hide()
        # When the value rests for a moment the real kernel result replaces the cheap preview.
        self.exact_result=None;self.exact_path_key=None;self.exact_path=None;self.last_exact_ms=0.;self.bar_rect=None;self.removed_path=None
        self.exact_timer=QTimer(workspace);self.exact_timer.setSingleShot(True);self.exact_timer.setInterval(EXACT_DELAY_MS)
        self.exact_timer.timeout.connect(self.compute_exact)

    def clear(self):
        self.exact_timer.stop();self.exact_result=None
        self._exact_token+=1;self._exact_again=False     # a rebuild still running is dropped when it arrives
        if self.workspace.faded_bodies:self.workspace.faded_bodies=set()
        self.dragging=False;self.consume_release=False;self.state=None;self.editor.hide();self.hover=None;self.workspace.update()

    def configure(self,key,kind,origin,directions,values,paths,setter,symmetric=False,taper=0,label=None,minimum=None,offset_paths=True,ghost=None,
                  labels=None,exact=None,exact_key=None,limits=None,exact_job=None):
        """``kind``: 'move' (X/Y/Z handles), 'extrude' (depth arrow), 'value' (one labelled
        arrow for a size such as a fillet radius), 'spacing' (several independent labelled
        values, ``ghost`` receives all of them) or 'preview' (an outline only, no arrows).
        ``exact(value)`` returns ``(outlines, error)`` for the real result; ``exact_key``
        identifies the state it was computed for, so unrelated refreshes keep it."""
        same=self.state is not None and self.state['key']==key
        self.serial=getattr(self,'serial',0)+1     # every configuration gets its own cached preview
        self.state=dict(key=key,kind=kind,origin=np.asarray(origin,float),directions=np.asarray(directions,float),
                        values=np.asarray(values,float),paths=paths,setter=setter,symmetric=symmetric,taper=taper,
                        label=label or 'Depth',minimum=minimum,offset_paths=offset_paths,ghost=ghost,
                        labels=list(labels) if labels else None,exact=exact,exact_key=exact_key,exact_job=exact_job,
                        limits=tuple(limits) if limits else (None,None))
        if not same:self.axis=0;self.dragging=False
        self.axis=min(self.axis,max(0,len(values)-1))
        if kind=='preview':self.editor.hide()
        else:self.sync_editor()
        # Keep an exact outline that still describes the same state; recompute only on change.
        result=self.exact_result
        stale=result is None or exact_key is None or result[3]!=exact_key
        if stale:self.schedule_exact()
        self.workspace.update()

    def clamp(self,value):
        """Keep a value inside the sizes the tool can really build."""
        lo,hi=(self.state.get('limits') or (None,None)) if self.state else (None,None)
        if lo is not None:value=max(float(lo),value)
        if hi is not None:value=min(float(hi),value)
        return value

    def exact_function(self):
        if not self.state:return None
        return self.state.get('exact') or getattr(self.state.get('ghost'),'exact',None)

    def schedule_exact(self):
        if not self.dragging:self.exact_result=None      # while dragging, keep the last real outline until a new one is ready
        if self.exact_function() is None:return
        if self.dragging and self.state is not None and self.state.get('ghost') is not None:
            # These tools already show their live result from cached geometry. A kernel rebuild
            # during the drag only freezes the window (the kernel holds the interpreter lock), so
            # the real outline is built once, when the value rests (see release()).
            self.exact_timer.stop();return
        if self.dragging and self.last_exact_ms<EXACT_QUICK_MS:
            if not self.exact_timer.isActive():self.exact_timer.start(EXACT_DRAG_MS)   # throttle, not debounce
        else:self.exact_timer.start(EXACT_DELAY_MS)

    def compute_exact(self,background=None):
        """Compute the real outline for the current value.

        With a worker-capable tool (``exact_job``) the kernel rebuild runs on a background
        thread. Only one rebuild runs at a time; values that change meanwhile are collapsed
        into a single follow-up that uses the newest state, so the queue never grows.
        """
        self.exact_timer.stop()
        function=self.exact_function();state=self.state
        if function is None or not state:return
        background=ASYNC_EXACT if background is None else background
        value=float(state['values'][0]) if len(state['values']) else 0.
        key=state.get('exact_key');factory=state.get('exact_job') if background else None
        if factory is None:
            started=time.perf_counter()
            try:outcome=function(value)
            except Exception as failure:outcome=(None,str(failure))
            self._install_exact(value,key,outcome,(time.perf_counter()-started)*1000.);return
        if self._exact_running:
            self._exact_again=True;return
        try:job=factory()
        except Exception as failure:
            self._install_exact(value,key,(None,str(failure)),0.);return
        if not callable(job):                      # already decided while preparing (e.g. no feature)
            self._install_exact(value,key,job,0.);return
        self._exact_running=True;token=self._exact_token;signals=self._exact_signals
        def run():
            started=time.perf_counter()
            try:outcome=job()
            except BaseException as failure:outcome=(None,str(failure))
            signals.done.emit((token,value,key,outcome,(time.perf_counter()-started)*1000.))
        threading.Thread(target=run,name='SlothCAD-exact-preview',daemon=True).start()

    def _exact_done(self,payload):
        token,value,key,outcome,milliseconds=payload
        self._exact_running=False
        if token==self._exact_token:self._install_exact(value,key,outcome,milliseconds)
        again=self._exact_again;self._exact_again=False
        if self.state is None:return
        current=self.state.get('exact_key')
        stale=self.exact_result is None or self.exact_result[3]!=current
        if again and stale:self.compute_exact()

    def _install_exact(self,value,key,outcome,milliseconds):
        lines,error=outcome[0],outcome[1]
        warn=outcome[2] if len(outcome)>2 else False      # False, or the edges to highlight
        self.last_exact_ms=milliseconds
        self.exact_result=(value,lines,error,key,warn);self.exact_path_key=None
        # The bodies the extrusion runs into are shown at half opacity so the outline inside shows.
        faded=set(warn.get('hit',[])) if isinstance(warn,dict) else set()
        if faded!=self.workspace.faded_bodies:self.workspace.faded_bodies=faded
        self.workspace.update()

    def sync_editor(self):
        if not self.state:return
        lo,hi=self.state.get('limits') or (None,None)
        self.editor.blockSignals(True)
        self.editor.setRange(-100000 if lo is None else float(lo),100000 if hi is None else float(hi))
        self.editor.setValue(float(self.state['values'][self.axis]));self.editor.blockSignals(False)
        kind=self.state['kind']
        if kind in ('spacing','extrude') and self.state.get('labels'):label=tr(self.state['labels'][self.axis])
        elif kind=='spacing':label='XYZ'[self.axis]
        else:label='XYZ'[self.axis] if kind=='move' else tr(self.state['label'])
        color=COLORS[self.axis] if kind in ('move','spacing') else '#f0ad45'
        self.editor.setPrefix(label+': ');self.editor.setToolTip(tr('Type a distance in mm; Tab switches axes. Apply keeps the change.'))
        self.editor.setStyleSheet(f'QDoubleSpinBox {{border: 2px solid {color}; border-radius: 6px; padding: 3px;}}')
        self.editor.show();self.editor.raise_();self.position_editor()

    def origin(self):
        s=self.state
        return s['origin']+s['values']@s['directions'] if s['kind']=='move' else s['origin']

    def handles(self):
        s=self.state
        if not s or s['kind']=='preview':return []
        w=self.workspace;o=self.origin();base=w.project([o])[0][0];items=[]
        for axis,direction in enumerate(s['directions']):
            unit=w.project([o+direction])[0][0]-base
            # A view-normal axis still has a usable handle and finite drag scale.
            if np.linalg.norm(unit)<w.scale()*.15:
                visual=np.array([-.70710678,-.70710678]);unit=visual*max(1e-12,w.scale())
            else:visual=unit/np.linalg.norm(unit)
            length=78.
            if s['kind']=='spacing':
                value=float(s['values'][axis]);length=max(48.,min(240.,abs(value)*np.linalg.norm(unit)))
                if value<0:visual=-visual
            elif s['kind'] in ('extrude','value'):
                # A two-sided extrusion has one arrow per side, each with its own distance.
                value=s['values'][axis if s['kind']=='extrude' and len(s['values'])>1 else 0]*(.5 if s['symmetric'] else 1)
                length=max(64.,min(240.,abs(value)*np.linalg.norm(unit)))
                if value<0:visual=-visual
            tip=base+visual*length
            items.append((base,tip,unit))
        return items

    def hit(self,position):
        if not self.state:return None
        point=np.array([position.x(),position.y()]);hits=[]
        for axis,(base,tip,unit) in enumerate(self.handles()):
            d=tip-base;t=np.clip((point-base)@d/(d@d),.22,1.)
            distance=np.linalg.norm(point-(base+t*d))
            if distance<=11:hits.append((distance,axis))
        return min(hits)[1] if hits else None

    def press(self,position):
        axis=self.hit(position)
        if axis is None:return False
        self.axis=axis;self.dragging=True;self.consume_release=True;self.start_position=np.array([position.x(),position.y()])
        self.start_values=self.state['values'].copy();self.drag_unit=self.handles()[axis][2].copy()
        self.sync_editor();self.workspace.setCursor(Qt.SizeAllCursor);return True

    def move(self,position):
        if not self.dragging:return False
        delta=np.array([position.x(),position.y()])-self.start_position
        amount=float(delta@self.drag_unit/(self.drag_unit@self.drag_unit))
        if self.state['kind']=='extrude' and self.state['symmetric']:amount*=2
        value=float(self.start_values[self.axis])+amount
        # Increments follow the view scale (1/2/5 steps), now about 4 px per step so values
        # change in fine increments; Shift gives the old coarse steps, Ctrl/Alt finer ones.
        modifiers=QApplication.keyboardModifiers()
        pixels=22 if modifiers&Qt.ShiftModifier else 1.5 if modifiers&(Qt.ControlModifier|Qt.AltModifier) else DRAG_STEP_PIXELS
        step=self.workspace.adaptive_grid_step(pixels) if self.workspace.snap_enabled else 0
        if step:value=round(value/step)*step
        if self.state.get('minimum') is not None:value=max(float(self.state['minimum']),value)
        self.set_value(self.clamp(max(-100000,min(100000,value))));return True

    def release(self):
        if not self.consume_release:return False
        self.consume_release=False;self.dragging=False;self.workspace.setCursor(Qt.ArrowCursor)
        if self.state is not None and self.exact_function() is not None:
            result=self.exact_result
            if result is None or result[3]!=self.state.get('exact_key'):self.exact_timer.start(EXACT_DELAY_MS)
        self.workspace.update();return True

    def set_value(self,value):
        if not self.state or not math.isfinite(value):return
        value=self.clamp(float(value))
        self.state['setter'](self.axis,float(value))
        # The setter refreshes the whole editor, which re-configures this gizmo; only keep the
        # exact outline when it still matches, otherwise it is recomputed after a short rest.
        if self.state:self.sync_editor()
        self.workspace.update()

    def typed(self,value):self.set_value(value)

    def key(self,event):
        if not self.state or self.state['kind']=='preview':return False
        if event.key()==Qt.Key_Escape and self.dragging:
            saved=self.start_values.copy();self.dragging=False
            for axis,value in enumerate(saved):self.state['setter'](axis,float(value))
            self.workspace.drag=True;self.workspace.setCursor(Qt.ArrowCursor);self.sync_editor();return True
        if event.key() in (Qt.Key_Tab,Qt.Key_Backtab):
            self.editor.interpretText();self.axis=(self.axis+(-1 if event.key()==Qt.Key_Backtab else 1))%len(self.state['values'])
            self.sync_editor();self.editor.setFocus();self.editor.selectAll();return True
        if event.text() and event.text() in '0123456789-+.,':
            self.editor.setFocus();self.editor.selectAll();self.editor.lineEdit().setText(event.text().replace(',','.'));return True
        return False

    def position_editor(self):
        if not self.state or self.state['kind']=='preview':return
        w=self.workspace;bar=self.bar_rect
        # Always in the bottom-left corner, in line with the readout, so it never covers the part
        # and is always reachable; beside the readout when it fits, above it otherwise.
        height=self.editor.height();width=self.editor.width()
        y=int(w.height()-84+14-height/2)
        x=int((bar.right() if bar is not None else 16)+10)
        if x+width>w.width()-8:x=16;y=int(w.height()-84-height-6)
        self.editor.move(max(8,x),max(8,y))

    def paint(self,p):
        s=self.state
        if not s:return
        self.position_editor();w=self.workspace;p.save();p.setRenderHint(QPainter.Antialiasing,True)
        color=QColor('#f0ad45' if s['kind'] in ('extrude','value') else '#5ebbd5' if s['kind']!='preview' else '#7fd1a8')
        path_key=(getattr(self,'serial',0),w.camera_key(),tuple(s['values']),s['symmetric'])
        def quick_path():
            """The cheap value-based preview. Built only when it is going to be shown: it used to
            be rebuilt on every camera frame even while the exact outline was what got drawn."""
            if getattr(self,'path_key',None)==path_key:return self.path
            if s.get('ghost') is not None:
                # Tool-specific live preview: polylines recomputed from the current value.
                removed=QPainterPath()
                try:
                    if s['kind']=='spacing':lines=s['ghost'](tuple(float(v) for v in s['values']))
                    else:lines=s['ghost'](float(s['values'][0]) if len(s['values']) else 0.)
                except Exception:lines=[]
                if isinstance(lines,dict):   # {'lines': new/kept outline, 'removed': geometry the operation cuts away}
                    removed=self.build_outline_path(lines.get('removed',[]))
                    lines=lines.get('lines',[])
                self.removed_path=removed
                built=self.build_outline_path(lines)
            else:
                offset=s['values']@s['directions'] if s['kind']=='move' else s['directions'][0]*s['values'][0]
                factor=.5 if s['symmetric'] else 1.
                arrays=[]
                for points in s['paths']:
                    base=np.asarray(points['points'] if isinstance(points,dict) else points,float)
                    if s['kind'] in ('extrude','value') and isinstance(points,dict):offset=np.asarray(points['normal'])*s['values'][0]
                    if s['kind']=='value' and not s['offset_paths']:offset=offset*0
                    ends=[base+offset] if s['kind']=='move' else [base+offset*factor]+([base-offset*factor] if s['symmetric'] else [])
                    if s['kind']=='extrude' and len(s['values'])>1:
                        # Two sides: the second end lies along the second arrow.
                        # Each profile keeps its own normal; the second arrow says which way along it.
                        second=s['directions'][1]
                        if isinstance(points,dict):
                            normal=np.asarray(points['normal'],float);second=normal*np.sign(second@normal)
                        ends.append(base+second*abs(float(s['values'][1])))
                    for end in ends:
                        arrays.append(end)
                        if s['kind']=='extrude' or s['kind']=='value' and s['offset_paths']:
                            for j in np.linspace(0,len(base)-1,min(5,len(base)),dtype=int):arrays.append(np.array([base[j],end[j]]))
                built=self.build_outline_path(arrays)    # one projection call for the whole preview
            self.path_key=path_key;self.path=built
            return built
        path=None
        # Preview outline: a soft wide underlay with a crisp dashed line on top. Once the
        # value rests, the kernel's real result is drawn solid instead (red if it cannot be built).
        p.setBrush(Qt.NoBrush)
        exact=self.exact_result
        current=float(s['values'][0]) if len(s['values']) else None
        self.exact_failed=None;self.exact_warning=False
        fresh=exact is not None and (s.get('exact_key') is None or exact[3]==s.get('exact_key'))
        # While dragging, an older real outline may stand in for a slow rebuild only for tools
        # without an instant analytic preview, and only for the same state. Fillet/chamfer and
        # the other ghost tools show their live preview at once instead of flashing the
        # outline of an earlier value for a moment.
        holdover=self.dragging and exact is not None and exact[1] is not None and s.get('ghost') is None
        usable=exact is not None and (holdover or (fresh and current is not None and abs(exact[0]-current)<1e-9))
        exact_drawn=False
        if usable:
            if exact[2] is not None:
                self.exact_failed=exact[2];color=QColor('#e5534b')
            elif exact[1] is not None:
                key=(w.camera_key(),exact[0])
                if self.exact_path_key!=key:
                    self.exact_path=self.build_outline_path(exact[1]);self.exact_path_key=key
                path=self.exact_path
                if len(exact)>4 and exact[4]:color=QColor('#e5534b');self.exact_warning=True   # runs into an existing body
                # Big outlines (text, many holes) are stroked in one thin pass: the soft underlay
                # and round joins cost far more than they add when thousands of segments are drawn.
                heavy=path.elementCount()>1500
                if heavy:p.setRenderHint(QPainter.Antialiasing,path.elementCount()<6000)
                stroke_fast(p,path,color,glow=0 if heavy else 70,core=1 if heavy else 3)
                path=None;exact_drawn=True
        if not exact_drawn:path=quick_path()
        cut=getattr(self,'removed_path',None) if s.get('ghost') is not None else None
        if cut is not None and not cut.isEmpty() and path is not None:
            stroke_fast(p,cut,QColor('#e5534b'),dashed=True,glow=60,core=2)
        if path is not None:
            if path.elementCount()>1500:
                # Dash patterns over thousands of segments are very slow to stroke: a plain thin line.
                p.setRenderHint(QPainter.Antialiasing,path.elementCount()<6000)
                stroke_fast(p,path,color,glow=0,core=1)
            else:stroke_fast(p,path,color,dashed=True,glow=60,core=2)
        handles=self.handles()
        for axis,(base,tip,unit) in enumerate(handles):
            accent=QColor(COLORS[axis] if s['kind'] in ('move','spacing') else '#f0ad45')
            if s['kind'] in ('spacing','extrude') and s.get('labels'):label=tr(s['labels'][axis])
            elif s['kind']=='spacing':label='XYZ'[axis]
            else:label='XYZ'[axis] if s['kind']=='move' else tr(s['label'])
            self.draw_arrow(p,base,tip,accent,axis==self.axis,self.dragging and axis==self.axis,label)
        if not handles:
            p.restore();return
        self.draw_anchor(p,handles[0][0],QColor(COLORS[self.axis] if s['kind'] in ('move','spacing') else '#f0ad45'))
        format_value=lambda value:f'{value:+.4f}'.rstrip('0').rstrip('.')
        if s['kind'] in ('spacing','extrude') and s.get('labels'):names=[tr(n) for n in s['labels']]
        elif s['kind']=='spacing':names=[tr(n) for n in 'XYZ']
        if s['kind']=='extrude' and s.get('labels'):values='   '.join(f'{names[i]}: {format_value(v)} mm' for i,v in enumerate(s['values']))
        elif s['kind']=='spacing':values='   '.join(f'{names[i]}: {format_value(v)} mm' for i,v in enumerate(s['values']))
        else:values='   '.join(f'{"XYZ"[i]}: {format_value(v)} mm' for i,v in enumerate(s['values'])) if s['kind']=='move' else f'{tr(s["label"])}: {format_value(s["values"][0])} mm'
        top=(s.get('limits') or (None,None))[1]
        if top is not None and s['kind']!='preview':values+='   ·   '+tr('max')+' '+format_value(top).lstrip('+')+' mm'
        if getattr(self,'exact_failed',None):values+='   ·   '+tr('cannot be built at this size')
        elif getattr(self,'exact_warning',False):values+='   ·   '+tr('intersects a body')
        rect=QRectF(16,w.height()-84,min(w.width()-32,p.fontMetrics().horizontalAdvance(values)+34),28)
        if self.bar_rect is None or abs(self.bar_rect.right()-rect.right())>1:
            self.bar_rect=rect;self.position_editor()
        else:self.bar_rect=rect
        p.setBrush(QColor('#e818232f'));p.setPen(Qt.NoPen);p.drawRoundedRect(rect,14,14)
        accent=QColor(COLORS[self.axis] if s['kind'] in ('move','spacing') else '#f0ad45')
        p.setBrush(accent);p.drawEllipse(QPointF(rect.left()+14,rect.center().y()),4.5,4.5)
        p.setPen(QColor('#eff6ff'));p.drawText(rect.adjusted(24,0,0,0),Qt.AlignCenter,values);p.restore()

    def build_outline_path(self,lines):
        """One painter path for many world-space polylines: a single projection call for all of
        them instead of one per polyline (thousands of numpy round trips for a text outline)."""
        path=QPainterPath()
        arrays=[np.asarray(line,float) for line in lines]
        arrays=[a for a in arrays if len(a)>=2]
        if not arrays:return path
        counts=[len(a) for a in arrays]
        screen=self.workspace.project(np.vstack(arrays))[0]
        start=0
        move=path.moveTo;line_to=path.lineTo
        for count in counts:
            piece=screen[start:start+count];start+=count
            if count>8:
                # Points closer than ~2 px merge into one pixel anyway: thin dense curves (a
                # circle sampled with 64 points that is 30 px wide) before they are stroked.
                lengths=np.hypot(np.diff(piece[:,0]),np.diff(piece[:,1]));average=float(lengths.sum())/(count-1)
                if average<1.5:
                    step=int(np.ceil(2./max(average,1e-3)))
                    piece=np.vstack((piece[::step],piece[-1:]))
            chunk=piece.tolist()
            move(chunk[0][0],chunk[0][1])
            for x,y in chunk[1:]:line_to(x,y)
        return path

    @staticmethod
    def _tube(start,end,color,half_width):
        """Gradient across a shape so it reads as a rounded tube/cone instead of flat paint."""
        side=np.array([-(end[1]-start[1]),end[0]-start[0]]);length=float(np.linalg.norm(side))
        side=side/length if length>1e-9 else np.array([0.,1.])
        a=QPointF(*(end+side*half_width));b=QPointF(*(end-side*half_width))
        gradient=QLinearGradient(a,b)
        gradient.setColorAt(0.0,color.lighter(165));gradient.setColorAt(.45,color);gradient.setColorAt(1.0,color.darker(150))
        return QBrush(gradient)

    def draw_arrow(self,p,base,tip,color,active,dragging,text):
        """Tapered gradient shaft, notched cone head, glow while active and a value badge."""
        d=np.asarray(tip,float)-np.asarray(base,float);length=float(np.linalg.norm(d))
        if length<1e-6:return
        d=d/length;side=np.array([-d[1],d[0]])
        head=23. if active else 20.;half=10.5 if active else 9.
        neck=np.asarray(tip,float)-d*head;base=np.asarray(base,float);tip=np.asarray(tip,float)
        point=lambda v:QPointF(float(v[0]),float(v[1]))
        dark=QColor('#10151c')
        if active:
            glow=QColor(color);glow.setAlpha(120 if dragging else 75)
            p.setPen(QPen(glow,16 if dragging else 12,Qt.SolidLine,Qt.RoundCap));p.drawLine(point(base),point(neck))
            p.setBrush(glow);p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([point(tip+d*5),point(neck+side*(half+6)),point(neck-side*(half+6))]))
        # soft drop shadow, then the shaft and head
        shadow=QColor(0,0,0,70);p.setPen(Qt.NoPen);p.setBrush(shadow)
        offset=np.array([1.5,2.5])
        p.drawPolygon(QPolygonF([point(base+side*3.2+offset),point(neck+side*5.2+offset),point(neck-side*5.2+offset),point(base-side*3.2+offset)]))
        shaft=QPolygonF([point(base+side*2.6),point(neck+side*4.4),point(neck-side*4.4),point(base-side*2.6)])
        p.setPen(QPen(dark,1.6,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin));p.setBrush(self._tube(base,neck,color,4.4));p.drawPolygon(shaft)
        cone=QPolygonF([point(tip),point(neck+side*half),point(neck+d*5.5),point(neck-side*half)])
        p.setBrush(self._tube(neck,tip,color,half));p.drawPolygon(cone)
        # thin highlight along the shaft and the cone
        p.setPen(QPen(QColor(255,255,255,150),1.3,Qt.SolidLine,Qt.RoundCap))
        p.drawLine(point(base+d*12+side*1.2),point(neck+side*1.4))
        p.drawLine(point(neck+side*half*.45+d*3),point(tip-d*4+side*.6))
        # value badge just beyond the tip
        metrics=p.fontMetrics();width=metrics.horizontalAdvance(text)+18;height=metrics.height()+6
        center=tip+d*(12+width/2*abs(d[0])+height/2*abs(d[1]))
        badge=QRectF(center[0]-width/2,center[1]-height/2,width,height)
        p.setBrush(QColor(16,21,28,228));p.setPen(QPen(color,1.6));p.drawRoundedRect(badge,height/2,height/2)
        p.setPen(QColor('#f4f8ff'));p.drawText(badge,Qt.AlignCenter,text)

    def draw_anchor(self,p,base,color):
        """Round pivot where the arrows start, with a ring in the active axis colour."""
        centre=QPointF(float(base[0]),float(base[1]))
        p.setPen(Qt.NoPen);p.setBrush(QColor(0,0,0,70));p.drawEllipse(centre+QPointF(1.2,2),8,8)
        ring=QRadialGradient(centre,9);ring.setColorAt(0,QColor('#ffffff'));ring.setColorAt(.55,QColor('#dce7f5'));ring.setColorAt(1,color)
        p.setBrush(QBrush(ring));p.setPen(QPen(QColor('#10151c'),1.5));p.drawEllipse(centre,7.5,7.5)
        p.setBrush(color);p.setPen(Qt.NoPen);p.drawEllipse(centre,2.6,2.6)
