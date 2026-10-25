"""One scene for solids, support-plane selection, face picking, and 2D sketching."""
import math
import os
import time
from collections import deque
import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QLineF, QTimer, QRectF, QEvent, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor,QPainter,QPen,QPolygonF,QImage,QPainterPath,QStaticText,QFont,QTransform
from PySide6.QtWidgets import QWidget
from viewport_gizmo import ViewportGizmo
from render_backend import Rasterizer
from dimensions import values as dimension_values,constrain as dimension_constrain
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from gpu_renderer import GpuRenderer, surface_format, mesh_data
from themes import COLORS,load_theme
from i18n import tr

# Start-up view: a corner view with X running to the lower right.
DEFAULT_YAW, DEFAULT_PITCH = 49., 31.
CAMERA_ANIMATION_MS = 480
ANIMATIONS = os.environ.get('SLOTHCAD_NO_ANIMATION', '') != '1' and os.environ.get('QT_QPA_PLATFORM', '') not in ('offscreen', 'minimal')


def plane_selector_size(span):
    """Edge length of the three origin-plane squares drawn by the plane selector."""
    return min(span * .35, 30)


def plane_selector_center(span):
    """The point midway between the centres of the XY, XZ and YZ selector squares."""
    size = plane_selector_size(span)
    centres = []
    for name in ('XY', 'XZ', 'YZ'):
        o, u, v, n = axes(base_frame(name))
        centres.append(o + (u + v) * size / 2)
    return np.mean(centres, axis=0)


def _matrix_to_quaternion(m):
    m = np.asarray(m, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        k = math.sqrt(trace + 1) * 2
        return np.array([.25 * k, (m[2, 1] - m[1, 2]) / k, (m[0, 2] - m[2, 0]) / k, (m[1, 0] - m[0, 1]) / k])
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        k = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([(m[2, 1] - m[1, 2]) / k, .25 * k, (m[0, 1] + m[1, 0]) / k, (m[0, 2] + m[2, 0]) / k])
    if m[1, 1] > m[2, 2]:
        k = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 2] - m[2, 0]) / k, (m[0, 1] + m[1, 0]) / k, .25 * k, (m[1, 2] + m[2, 1]) / k])
    k = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[1, 0] - m[0, 1]) / k, (m[0, 2] + m[2, 0]) / k, (m[1, 2] + m[2, 1]) / k, .25 * k])


def _quaternion_to_matrix(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def blend_rotation(start, end, t):
    """Interpolate between two view matrices along the shortest path.

    Both views are normally proper rotations. Should one be a reflection (determinant
    -1), it is split into a proper rotation and a screen-x sign; the rotations are
    slerped and the sign is blended so both end views are reproduced exactly.
    """
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    sign_start = -1. if np.linalg.det(start) < 0 else 1.
    sign_end = -1. if np.linalg.det(end) < 0 else 1.
    proper_start = np.diag([sign_start, 1., 1.]) @ start
    proper_end = np.diag([sign_end, 1., 1.]) @ end
    a, b = _matrix_to_quaternion(proper_start), _matrix_to_quaternion(proper_end)
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    if dot > .9995:
        q = a + (b - a) * t
    else:
        theta = math.acos(min(1., dot))
        q = (math.sin((1 - t) * theta) * a + math.sin(t * theta) * b) / math.sin(theta)
    sign = sign_start + (sign_end - sign_start) * t
    return np.diag([sign, 1., 1.]) @ _quaternion_to_matrix(q)
GPU_ENABLED=os.environ.get("SLOTHCAD_RENDERER", "opengl")!="software" and os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal")
WorkspaceBase=QOpenGLWidget if GPU_ENABLED else QWidget
from geometry import (axes,world,local,sample,snap,snap_intersections,regions,region_points,entity,regular_polygon,
                      base_frame,face_reference,profile_regions,snap_points)


def _mesh_tolerance(shape):
    """Use a model-size-aware display tolerance instead of a permanently tiny mesh."""
    try:
        box=shape.BoundingBox();diag=math.sqrt(box.xlen*box.xlen+box.ylen*box.ylen+box.zlen*box.zlen)
    except Exception:diag=100.
    return max(.035,min(.20,diag/2500.))

def prepare_scene_mesh(solid,progress=None,draft=False):
    """Tessellate a solid without touching QWidget state; safe to run in a worker thread.

    ``draft`` meshes about three times coarser; it is used while a value is dragged and is
    replaced by the normal mesh as soon as the result is applied or the drag rests.
    """
    import mesh_cache
    shape=solid.val() if solid is not None else None
    faces=[];face_edges=[];solid_edges=[];vertices=[];triangles=[];ids=[];body_ids=[]
    if shape is None:
        if progress:progress(1,1,tr('Viewport ready'))
        return dict(shape=None,faces=faces,face_edges=face_edges,solid_edges=solid_edges,solid_vertices=[],
                    vertices=np.empty((0,3)),triangles=np.empty((0,3),dtype=int),
                    face_ids=np.array([],dtype=int),body_ids=np.array([],dtype=int),gpu_base_data=np.empty((0,7),np.float32))
    solids=list(shape.Solids())
    body_faces=[list(body.Faces()) for body in solids]
    owned={}
    for faces_ in body_faces:
        for face in faces_:owned.setdefault(face.hashCode(),[]).append(face)
    loose=[face for face in shape.Faces() if not any(face.isSame(own) for own in owned.get(face.hashCode(),[]))]
    if loose:body_faces.append(loose)
    all_solid_edges=list(shape.Edges())
    total=max(1,sum(len(items) for items in body_faces)+len(all_solid_edges));done=0
    linear,angular=mesh_cache.quality(shape,draft);quality_key=(round(linear,6),round(angular,6))
    # Mesh the whole shape once (in parallel) so neighbouring faces share one discretisation
    # of their common edge. Meshing face by face can split a shared edge differently
    # on each side and leave hairline cracks (visible along large fillets).
    try:mesh_cache.mesh(shape,linear,angular)
    except Exception:pass
    vertex_parts=[];triangle_parts=[];id_parts=[];body_parts=[];offset=0
    for body_id,items in enumerate(body_faces):
        for face in items:
            if progress:progress(done,total,tr(f'Preparing viewport face {done+1} of {total}'))
            id_=len(faces);faces.append(face)
            points,tris=mesh_cache.face_mesh(face,quality_key)
            if len(tris):
                vertex_parts.append(points);triangle_parts.append(tris+offset);id_parts.append(np.full(len(tris),id_,dtype=int));body_parts.append(np.full(len(tris),body_id,dtype=int))
            offset+=len(points)
            face_edges.append(mesh_cache.face_outlines(face));done+=1
    vertex_edges={}
    for edge_index,edge in enumerate(all_solid_edges):
        if progress:progress(done,total,tr(f'Preparing viewport edge {done+1} of {total}'))
        polyline,edge_vertices=mesh_cache.edge_data(edge)
        solid_edges.append((edge,polyline))
        for point in edge_vertices:
            key=tuple(round(value,7) for value in point)
            vertex_edges.setdefault(key,(point,set()))[1].add(edge_index)
        done+=1
    vertices=np.concatenate(vertex_parts) if vertex_parts else np.empty((0,3))
    triangles=np.concatenate(triangle_parts) if triangle_parts else np.empty((0,3),dtype=int)
    face_ids=np.concatenate(id_parts) if id_parts else np.array([],dtype=int)
    body_ids=np.concatenate(body_parts) if body_parts else np.array([],dtype=int)
    if progress:progress(total,total,tr('Preparing GPU vertex data'))
    gpu_base_data=mesh_data(vertices,triangles,face_ids)
    if progress:progress(total,total,'Viewport ready')
    solid_vertices=[(np.asarray(point,dtype=float),tuple(sorted(indices))) for point,indices in vertex_edges.values() if len(indices)>1]
    return dict(shape=shape,faces=faces,face_edges=face_edges,solid_edges=solid_edges,solid_vertices=solid_vertices,draft=bool(draft),
                vertices=vertices,triangles=triangles,face_ids=face_ids,body_ids=body_ids,gpu_base_data=gpu_base_data)

class Workspace(WorkspaceBase):
    # Sketch tools that work on a selection of entities (patterns, offset, transform).
    SELECTION_TOOLS=('mirror','circular','rectangular','offset','transform')
    projection_picked=Signal(int)
    spatial_point_picked=Signal(list)
    support_picked=Signal(dict)
    solid_face_picked=Signal(int)
    construction_point_picked=Signal(list)
    extrusion_picked=Signal(dict)
    path_picked=Signal(dict)
    entity_created=Signal(dict)
    tool_requested=Signal(str)
    construction_requested=Signal()
    delete_requested=Signal()
    entity_picked=Signal(int)
    constraint_picked=Signal(dict)
    sketch_drag_started=Signal(dict,list)
    sketch_drag_moved=Signal(list)
    sketch_drag_finished=Signal(list)
    sketch_drag_cancelled=Signal()
    trim_requested=Signal(int,list)
    corner_requested=Signal(list)
    sketch_hover_moved=Signal()
    pattern_selection_changed=Signal()
    mirror_axis_picked=Signal(int)
    pattern_center_picked=Signal(list)
    edge_selection_changed=Signal()
    message=Signal(str)
    resized=Signal()
    graphics_issue=Signal()
    measure_picked=Signal(dict)
    box_selected=Signal(dict)
    slot_picked=Signal(dict)
    def __init__(self):
        super().__init__()
        self.gizmo=ViewportGizmo(self)
        self.theme=load_theme();self.pattern_selection=set();self.pattern_stage='sources';self.pattern_axis=None;self.pattern_center=None;self.polygon_sides=6;self.polygon_mode='inscribed';self.polygon_size=10.;self.polygon_fixed_size=False;self.preparing_sketches=False;self.text_value='Text';self.text_height=5.0;self.text_box=None;self.screen_path_cache={};self.selection_path_cache={};self.layer_seen=None;self.layer_image=None;self.layer_refs=[];self.box=None;self.drag_selects=False;self.press_modifiers=Qt.NoModifier
        self.gpu_enabled=GPU_ENABLED;self.gpu=None;self.gpu_error=None;self.software_body_fallback=False;self.frame_times=deque(maxlen=120);self.pick_cache=None
        if self.gpu_enabled:self.setFormat(surface_format())
        self.setMinimumSize(480,400); self.setMouseTracking(True); self.setFocusPolicy(Qt.StrongFocus)
        self.vertices=np.empty((0,3)); self.triangles=np.empty((0,3),dtype=int); self.face_ids=np.array([],dtype=int);self.body_ids=np.array([],dtype=int);self.gpu_base_data=np.empty((0,7),np.float32)
        self.measure_active=False;self.measure_selection=[];self.measure_result=None;self.measure_hover=None;self.measure_vertices=[]
        self.measure_scene_key=None;self.measure_scene_cache=None
        self.faces=[]; self.face_edges=[];self.solid_edges=[];self.solid_vertices=[];self.selected_edges=set(); self.spatial_scenes=[]; self.sketches=[]; self.active=None; self.active_frame=None
        self.constraint_kind="coincident";self.constraint_refs=[];self.constraint_feedback="";self.sketch_drag_ref=None;self.sketch_drag_active=False;self.sketch_drag_preview=False
        self.construction_point_picking=False;self.solid_face_picking=False;self.solid_pick_key="faces";self.construction_items=[];self.construction_polygons={};self.solid_selected_faces=set()
        self.construction_mode=False
        self.slot_accept=None                 # kinds a click may pick right now (see slot_hit), or None
        self.perspective=False                # perspective camera in the 3D view (sketches stay orthographic)
        self.section=None                     # dict(normal=[x,y,z], distance=mm): the model is cut by that plane
        self.constrained_entities=set()       # sketch entities that are fully constrained (drawn in green)
        self.edge_tangent_chain=True
        self.mode='model'; self.tool='select'; self.grid=1.; self.snap_enabled=True;self.show_grid=True;self.show_axes=True;self.show_aa=True
        self.span=60.; self.center=plane_selector_center(self.span); self.zoom=1.; self.pan=np.zeros(2)
        self.yaw=DEFAULT_YAW; self.pitch=DEFAULT_PITCH; self.aligned=None; self.camera_animation=None
        # While the camera is moving the grid is drawn in a lighter form (see paint_grid);
        # the full grid with labels returns as soon as it has been still for a moment.
        self.faded_bodies=set();self.fade_key=None;self.fade_path=None
        self.camera_busy=False;self.camera_settle=QTimer(self);self.camera_settle.setSingleShot(True);self.camera_settle.setInterval(140)
        self.camera_settle.timeout.connect(self.settle_camera)
        self.hover=None; self.selected_source=None; self.selected_entity=None;self.extrusion_selection=[];self.extrude_selecting=False;self.path_picking=False;self.path_hover=None
        self.dimension_locks={};self.dimension_index=0;self.dimension_text='';self.dimension_typing=False
        self.points=[];self.point_redo=[]; self.cursor=None; self.hover_position=None; self.snap_label=''; self.last=None; self.drag=False
        self.revision=0; self.cache_key=None; self.pixels=None; self.depth=None; self.face_buffer=None
        self.mesh_shape=None;self.mesh_is_draft=False;self.mesh_builds=0;self.materials={};self.material_signature=None
        self.rasterizer=None if self.gpu_enabled else Rasterizer();self.empty_size=None;self.background_key=None;self.background_image=None;self.background_builds=0;self.text_cache={}
        self.sketch_cache={};self.profile_cache={};self.frame_cache={};self.snap_cache_key=None;self.snap_cache_intersections=[]
        # High polling-rate mice must not drive snapping/picking/status work per event.
        self.pending_motion=None;self.pending_zoom=0.;self.press_position=None
        self.motion_events=0;self.motion_batches=0;self.last_motion_status=None;self.last_status_time=0.
        self.motion_timer=QTimer(self);self.motion_timer.setSingleShot(True)
        self.motion_timer.setTimerType(Qt.PreciseTimer);self.motion_timer.setInterval(16)
        self.frame_rate=60.;self.display_rate=60.
        self.motion_timer.timeout.connect(self.flush_motion)
        self.plane_polygons={};self.plane_cache_key=None;self.plane_images={};self.plane_cache_builds=0
        # Keep the viewport free of intrusive hover tooltips; guidance is shown in the UI and overlays instead.
        self.setToolTip('')

    def set_theme(self,name):
        self.theme=name;self.background_key=None;self.plane_cache_key=None;self.text_cache.clear();self.update()
    def theme_color(self,color):
        mapping={'#eaf0f5':'canvas','#526778':'muted','#cddae4':'grid','#bbcbd7':'major','#d2dee7':'grid',
                 '#8d68ac':'sketch','#e8e1ef':'fill','#278fb2':'active','#087ba5':'active','#d6ebf3':'activefill'}
        return COLORS[self.theme].get(mapping.get(color,''),color)
    def entity_at(self,pos):
        from geometry import nearest_on_entity
        point=self.local_at(pos,self.active_frame)
        if point is None:return None
        found=None;distance=10/self.scale()
        for i,e in enumerate(self.active['entities']):
            d=np.linalg.norm(nearest_on_entity(e,point)-point)
            if d<distance:found=i;distance=d
        return found

    def resizeEvent(self,event):
        super().resizeEvent(event);self.resized.emit()

    def rotation(self):
        if self.aligned is not None: return self.aligned
        y,p=map(math.radians,(self.yaw,self.pitch))
        # Rows are the screen-right, screen-up and towards-viewer axes. right x up = towards
        # viewer, so this is a proper (right-handed) rotation like the sketch-plane views:
        # models are no longer mirrored in the 3D view, and sketch transitions are pure turns.
        return np.array([[-math.cos(y),math.sin(y),0],
                         [-math.sin(p)*math.sin(y),-math.sin(p)*math.cos(y),math.cos(p)],
                         [math.cos(p)*math.sin(y),math.cos(p)*math.cos(y),math.sin(p)]])
    def set_frame_rate(self,fps,display=None):
        """Pace camera and pointer updates: one batch per frame at ``fps`` (30..240)."""
        fps=max(30.,min(240.,float(fps)));self.frame_rate=fps
        if display is not None:self.display_rate=float(display)
        self.motion_timer.setInterval(max(1,int(1000./fps)))

    def scale(self): return min(self.width(),self.height())*.76/self.span*self.zoom

    PERSPECTIVE_DISTANCE=1.6      # camera distance from the view centre, in model spans

    def eye_distance(self):
        """Distance of the camera from the view centre, or None for the orthographic view."""
        if self.perspective and self.mode!='sketch':return max(self.span,1e-9)*self.PERSPECTIVE_DISTANCE
        return None

    def project(self,points):
        v=(np.array(points)-self.center)@self.rotation().T
        s=self.scale();eye=self.eye_distance()
        xy=v[:,:2]*[s,-s]
        if eye is not None:xy=xy/np.maximum(1.-v[:,2]/eye,.02)[:,None]
        return xy+[self.width()/2,self.height()/2]+self.pan,v[:,2]
    def frame_axes(self,frame):
        key=tuple(tuple(frame[k]) for k in ('origin','u','normal'))
        if key not in self.frame_cache:
            if len(self.frame_cache)>128:self.frame_cache.clear()
            self.frame_cache[key]=axes(frame)
        return self.frame_cache[key]
    def project_local(self,points,frame):
        o,u,v,n=self.frame_axes(frame);pts=np.asarray(points,dtype=float).reshape((-1,2))
        return self.project(o+pts[:,0,None]*u+pts[:,1,None]*v)[0]
    def unproject(self,position,depth):
        """World point under a screen position at a given view depth (inverse of project)."""
        s=self.scale();eye=self.eye_distance();w=1.-float(depth)/eye if eye is not None else 1.
        view=np.array([(position.x()-self.width()/2-self.pan[0])/s*w,-(position.y()-self.height()/2-self.pan[1])/s*w,float(depth)])
        return np.asarray(self.center,float)+self.rotation().T@view

    def local_at(self,position,frame):
        o,u,v,n=self.frame_axes(frame)
        eye=self.eye_distance()
        if eye is not None:
            # Perspective: the plane maps to the screen projectively, so intersect the eye ray with it.
            camera=np.asarray(self.center,float)+self.rotation().T@np.array([0.,0.,eye])
            ray=self.unproject(position,0.)-camera;denominator=float(ray@n)
            if abs(denominator)<1e-12:return None
            hit=camera+ray*(float((o-camera)@n)/denominator)
            return np.array([float((hit-o)@u),float((hit-o)@v)])
        screen,_=self.project([o,o+u,o+v])
        matrix=np.column_stack((screen[1]-screen[0],screen[2]-screen[0]))
        det=np.linalg.det(matrix)
        if not math.isfinite(float(det)) or abs(det)<np.finfo(float).tiny:return None
        return np.linalg.solve(matrix,np.array([position.x(),position.y()])-screen[0])
    def fit(self):
        self.flush_motion()
        animating=self.camera_animation is not None
        if animating:current=(self.center.copy(),self.span,self.zoom,np.array(self.pan,dtype=float))
        bounds=[self.vertices] if len(self.vertices) else []
        for id_,name,frame in self.construction_items:
            o,u,v,n=axes(frame)
            bounds.append(np.asarray([o-n*10,o+n*10]) if frame.get('axis') else np.asarray([o-u*10-v*10,o+u*10+v*10]))
        for sketch,frame in self.sketches:
            if frame.get('spatial'):
                bounds.extend(__import__('spatial_sketch').sampled(sketch,frame));continue
            for e in sketch['entities']:
                if not e.get('construction'):bounds.append(np.array([world(frame,p) for p in sample(e,16)]))
        if self.active and self.active['entities']:
            bounds += [np.array([world(self.active_frame,p) for p in sample(e,16)]) for e in self.active['entities']]
        for sketch,frame in self.spatial_scenes:bounds.extend(__import__('spatial_sketch').sampled(sketch,frame))
        if bounds:
            points=np.vstack(bounds); low=points.min(axis=0);high=points.max(axis=0)
            self.center=(low+high)/2;self.span=max(float(np.linalg.norm(high-low)),10.)
        else: self.span=60.;self.center=plane_selector_center(self.span)
        self.pan=np.zeros(2);self.zoom=1.
        if animating:
            # The fitted view becomes the new destination; keep gliding from where we are.
            end=self.camera_animation['end'];end.update(center=self.center.copy(),span=float(self.span),zoom=1.,pan=np.zeros(2))
            self.center,self.span,self.zoom,self.pan=current
        self.update()
    def selection_points(self):
        """World points of everything selected in the 3D view: faces, edges, picked extrusion faces."""
        chunks=[]
        faces=set(self.solid_selected_faces)|{s.get('index') for s in self.extrusion_selection if s.get('type')=='face' and s.get('index') is not None}
        for index in faces:
            if index is not None and 0<=index<len(self.face_edges):
                chunks.extend(np.asarray(line,float).reshape((-1,3)) for line in self.face_edges[index] if len(line))
        for index in self.selected_edges:
            if 0<=index<len(self.solid_edges) and len(self.solid_edges[index][1]):chunks.append(np.asarray(self.solid_edges[index][1],float).reshape((-1,3)))
        return np.vstack(chunks) if chunks else np.empty((0,3))

    def fit_selection(self):
        """Frame the selected faces / edges; with nothing selected, frame the whole model."""
        points=self.selection_points()
        if not len(points):self.fit();return False
        self.flush_motion();start=self.camera_state()
        low,high=points.min(axis=0),points.max(axis=0)
        self.center=(low+high)/2;self.span=max(float(np.linalg.norm(high-low))*1.5,5.)
        self.pan=np.zeros(2);self.zoom=1.
        self.begin_camera_transition(start);self.update();return True

    def preset(self,name):
        self.flush_motion();self.finish_camera_animation()
        self.aligned=None;self.yaw,self.pitch={'Iso':(DEFAULT_YAW,DEFAULT_PITCH),'Top':(180,90),'Front':(180,0),'Right':(90,0)}[name];self.update()
    def apply_navigation(self,motion,dt):
        """Move the camera from 6-DOF device input; ``motion`` channels are about -1..1 at full deflection.

        In the 3D views every move is about the point at the middle of the screen (what you look at), not
        about the model's own centre: any pan offset is first folded into the view centre, so zooming in on a
        detail and orbiting keeps that detail in place, and panning is as fast on the screen at any zoom.
        """
        self.finish_camera_animation()
        size=min(self.width(),self.height()) or 600
        dx=motion.get('pan_x',0.)*size*2.2*dt;dy=-motion.get('pan_y',0.)*size*2.2*dt
        three_d=self.mode!='sketch'
        if three_d and (self.pan[0] or self.pan[1]):
            s=self.scale();self.center=np.array(self.center,dtype=float)+self.rotation().T@np.array([-self.pan[0]/s,self.pan[1]/s,0.]);self.pan=np.zeros(2)
        self.zoom=max(1e-120,min(1e120,self.zoom*math.exp(motion.get('zoom',0.)*3.2*dt)))
        if three_d and (motion.get('tilt') or motion.get('spin')):
            self.aligned=None
            self.pitch=max(-90,min(90,self.pitch+motion.get('tilt',0.)*220*dt))
            self.yaw=(self.yaw+motion.get('spin',0.)*260*dt)%360
        if three_d:
            self.center=np.array(self.center,dtype=float)+self.rotation().T@np.array([-dx/self.scale(),dy/self.scale(),0.])
        else:
            self.pan+=np.array([dx,dy])
        self.mark_camera_moving();self.update()

    def turn_object(self,degrees=90.):
        """Turn the model about the vertical axis, clockwise seen from above, with a short glide."""
        if self.mode=='sketch':return
        self.flush_motion();self.finish_camera_animation();start=self.camera_state()
        if self.aligned is None:self.yaw=(self.yaw-degrees)%360
        else:
            a=math.radians(-degrees);c,s=math.cos(a),math.sin(a)
            self.aligned=np.array(self.aligned,dtype=float)@np.array([[c,-s,0],[s,c,0],[0,0,1]])
        self.begin_camera_transition(start);self.update()

    def align(self,frame,animate=True):
        self.flush_motion();self.finish_camera_animation()
        start=self.camera_state()
        o,u,v,n=axes(frame);self.aligned=np.array([u,v,n]);self.center=o
        self.pan=np.zeros(2);self.zoom=1.;self.span=max(self.span,40.)
        if animate:self.begin_camera_transition(start)
        self.update()

    # ---- animated camera transitions (entering/leaving sketch mode, changing sketch plane)
    def camera_state(self):
        return dict(R=np.array(self.rotation(),dtype=float),aligned=None if self.aligned is None else np.array(self.aligned,dtype=float),
                    center=np.array(self.center,dtype=float),span=float(self.span),zoom=float(self.zoom),pan=np.array(self.pan,dtype=float))

    def begin_camera_transition(self,start):
        """Glide from ``start`` to the camera the caller has just set."""
        end=self.camera_state()
        if not ANIMATIONS or not self.isVisible() or self.width()<2 or self.height()<2:return
        same=(np.allclose(start['R'],end['R'],atol=1e-6) and np.allclose(start['center'],end['center'],atol=1e-6)
              and np.allclose(start['pan'],end['pan'],atol=1e-6)
              and abs(math.log(max(start['span'],1e-9)/max(end['span'],1e-9)))<1e-6
              and abs(math.log(max(start['zoom'],1e-120)/max(end['zoom'],1e-120)))<1e-6)
        if same:return
        animation=QVariantAnimation(self);animation.setDuration(CAMERA_ANIMATION_MS);animation.setEasingCurve(QEasingCurve.InOutCubic)
        animation.setStartValue(0.);animation.setEndValue(1.)
        self.camera_animation=dict(start=start,end=end,animation=animation)
        animation.valueChanged.connect(self._camera_step);animation.finished.connect(self.finish_camera_animation)
        self._camera_step(0.);animation.start()

    def _camera_step(self,t):
        info=self.camera_animation
        if not info:return
        t=float(t);start,end=info['start'],info['end']
        self.aligned=blend_rotation(start['R'],end['R'],t)
        self.center=start['center']+(end['center']-start['center'])*t
        self.pan=start['pan']+(end['pan']-start['pan'])*t
        # Scale factors are interpolated in log space so the zoom feels even.
        self.span=math.exp(math.log(max(start['span'],1e-9))*(1-t)+math.log(max(end['span'],1e-9))*t)
        self.zoom=math.exp(math.log(max(start['zoom'],1e-120))*(1-t)+math.log(max(end['zoom'],1e-120))*t)
        self.mark_camera_moving();self.update()

    def finish_camera_animation(self):
        """Jump to the end of a running transition (used when the user takes over)."""
        info=self.camera_animation
        if not info:return
        self.camera_animation=None;info['animation'].stop();info['animation'].deleteLater()
        end=info['end'];self.aligned=end['aligned'];self.center=end['center'].copy();self.span=end['span'];self.zoom=end['zoom'];self.pan=end['pan'].copy()
        self.update()

    def geometry_matches(self,solid,draft=False):
        """True when the shown mesh already is this solid (a coarse draft mesh only satisfies a draft)."""
        shape=solid.val() if solid is not None else None
        if shape is None:return self.mesh_shape is None
        if self.mesh_shape is None or not shape.isSame(self.mesh_shape):return False
        return draft or not self.mesh_is_draft

    def prepare_scene(self,solid,progress=None,draft=False):
        return prepare_scene_mesh(solid,progress,draft)

    def set_scene(self,solid,sketches,fit=False,materials=None,prepared=None,draft=False):
        self.spatial_scenes=[(s,f) for s,f in sketches if f.get('spatial')]
        sketches=[(s,f) for s,f in sketches if not f.get('spatial')]
        shape=solid.val() if solid is not None else None
        material_signature=repr(materials or {})
        same_geometry=(prepared is None and self.geometry_matches(solid,draft))
        same_material=material_signature==self.material_signature
        if same_geometry:
            self.sketches=sketches;self.sketch_cache.clear();self.measure_scene_key=None;self.hover=None;self.selected_source=None
            if not same_material:
                self.materials=materials or {};self.material_signature=material_signature;self.revision+=1
            if fit:self.fit()
            self.update();return
        data=prepared if prepared is not None else prepare_scene_mesh(solid,draft=draft)
        self.mesh_shape=data['shape'];self.mesh_is_draft=bool(data.get('draft',False));self.mesh_builds+=1;self.materials=materials or {};self.material_signature=material_signature
        self.faces=data['faces'];self.face_edges=data['face_edges'];self.solid_edges=data['solid_edges']
        self.solid_vertices=data.get('solid_vertices',[])
        self.vertices=data['vertices'];self.triangles=data['triangles'];self.face_ids=data['face_ids'];self.body_ids=data['body_ids'];self.gpu_base_data=data['gpu_base_data']
        self.sketches=sketches;self.sketch_cache.clear();self.measure_scene_key=None;self.revision+=1;self.hover=None;self.selected_source=None
        if fit: self.fit()
        self.update()
    def live_dimensions(self,points,cursor):
        dims=dimension_values('rectangle' if self.tool=='text' else self.tool,points,cursor)   # a text box is sized like a rectangle
        if self.tool=='polygon' and dims:
            label={'inscribed':'Vertex radius','circumscribed':'Edge radius','edge':'Edge length'}[self.polygon_mode]
            return [(label,dims[0][1],'mm')]
        return dims

    def constrained_cursor(self,points,cursor,locks):
        if self.tool=='polygon' and points and self.polygon_fixed_size and 0 not in locks:locks={**locks,0:self.polygon_size}
        return dimension_constrain('rectangle' if self.tool=='text' else self.tool,points,cursor,locks)

    def reset_dimensions(self):
        self.dimension_locks.clear();self.dimension_index=0;self.dimension_text='';self.dimension_typing=False
    def set_mode(self,mode,active=None,frame=None):
        self.finish_camera_animation();camera_start=self.camera_state()
        self.gizmo.clear()
        self.reference_highlight=[]
        self.spatial_edit=None
        self.set_measure_active(False)
        self.reset_dimensions()
        self.flush_motion()
        self.solid_face_picking=False;self.construction_point_picking=False;self.solid_selected_faces=set()
        self.constrained_entities=set()
        self.mode=mode;self.active=active;self.active_frame=frame;self.pattern_selection.clear();self.pattern_stage='sources';self.pattern_axis=None;self.pattern_center=None
        self.text_box=None;self.path_picking=False;self.path_hover=None
        if mode!='edge':self.selected_edges.clear()
        self.points=[];self.point_redo=[];self.cursor=None;self.hover=None;self.selected_entity=None;self.selected_source=None
        if mode=='sketch': self.construction_mode=False;self.align(frame,animate=False)
        elif self.aligned is not None: self.aligned=None
        self.begin_camera_transition(camera_start)
        self.setCursor(Qt.CrossCursor if mode in ('sketch','support','extrude','edge') else Qt.ArrowCursor)
        self.update()
    def set_extrusion_selection(self,hits,active=True):
        self.extrusion_selection=[dict(hit) for hit in (hits or [])]
        self.extrude_selecting=bool(active)
        self.hover=None;self.update()

    def extrusion_source_key(self,source):
        if source.get('type')=='sketch':
            return ('sketch',source.get('sketch'),tuple(sorted(source.get('entities',[]))))
        if source.get('type')=='face':
            ref=source.get('face',{})
            return ('face',tuple(round(float(v),6) for v in ref.get('center',[])),tuple(round(float(v),6) for v in ref.get('normal',[])),round(float(ref.get('area',0)),6))
        return ('unknown',repr(source))

    def set_tool(self,tool):
        self.reset_dimensions()
        self.flush_motion()
        if self.sketch_drag_active:self.sketch_drag_cancelled.emit()
        self.sketch_drag_ref=None;self.sketch_drag_active=False
        self.tool=tool;self.points=[];self.point_redo=[];self.cursor=None;self.pattern_selection.clear();self.pattern_stage='sources';self.pattern_axis=None;self.pattern_center=None
        if tool!='text':self.text_box=None
        self.update()
    def cancel_tool(self): self.reset_dimensions();self.points=[];self.point_redo=[];self.cursor=None;self.hover=None;self.update()
    def event(self,event):
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Tab,Qt.Key_Backtab) and self.gizmo.state:
            return self.gizmo.key(event)
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Tab,Qt.Key_Backtab) and self.mode=='sketch' and self.points and self.live_dimensions(self.points,self.cursor):
            self.keyPressEvent(event);return True
        return super().event(event)
    def commit_dimension_text(self):
        if not self.dimension_typing:return True
        try:
            value=float(self.dimension_text.replace(',','.'))
            label=self.live_dimensions(self.points,self.cursor)[self.dimension_index][0]
            if not math.isfinite(value) or label not in ('Angle','Bend') and value<=0:raise ValueError()
            self.dimension_locks[self.dimension_index]=value;self.dimension_typing=False
            self.cursor=self.constrained_cursor(self.points,self.cursor,self.dimension_locks);return True
        except (ValueError,IndexError):self.message.emit(tr('Enter a valid dimension; lengths must be greater than zero.'));return False
    def eventFilter(self,obj,event):
        if getattr(self,'gizmo',None) is not None and obj is self.gizmo.editor and event.type()==QEvent.KeyPress:
            if event.key() in (Qt.Key_Tab,Qt.Key_Backtab):return self.gizmo.key(event)
            if event.key()==Qt.Key_Escape:
                if self.gizmo.dragging:self.gizmo.key(event)
                self.gizmo.sync_editor();self.setFocus();return True
        return super().eventFilter(obj,event)

    def keyPressEvent(self,e):
        self.flush_motion()
        if self.gizmo.key(e):e.accept();return
        if e.key()==Qt.Key_Escape and self.sketch_drag_active:
            self.sketch_drag_active=False;self.sketch_drag_ref=None;self.sketch_drag_cancelled.emit();e.accept();return
        if self.measure_active:
            if e.key()==Qt.Key_Escape:self.set_measure_active(False);self.tool_requested.emit(self.tool if self.mode=='sketch' else 'measure_exit')
            e.accept();return
        if self.mode!='sketch' and not self.measure_active and not e.modifiers():
            if e.key()==Qt.Key_Z:self.fit_selection();e.accept();return
            if e.key()==Qt.Key_F:self.fit();e.accept();return
        if self.mode=='sketch' and not e.modifiers() & (Qt.ControlModifier|Qt.AltModifier):
            shortcuts={Qt.Key_L:'line',Qt.Key_R:'rectangle',Qt.Key_C:'circle',Qt.Key_A:'arc',Qt.Key_T:'trim',Qt.Key_V:'select',Qt.Key_E:'extend',Qt.Key_O:'offset'}
            if e.key() in shortcuts:self.tool_requested.emit(shortcuts[e.key()]);e.accept();return
            if not self.points and e.key()==Qt.Key_X:self.construction_requested.emit();e.accept();return
            if not self.points and e.key()==Qt.Key_Delete:self.delete_requested.emit();e.accept();return
        if self.mode=='sketch' and self.tool=='spline' and e.key() in (Qt.Key_Return,Qt.Key_Enter):
            if len(self.points)>=2:
                self.entity_created.emit(entity('spline',basis='bspline',points=[list(p) for p in self.points]));self.points=[];self.cursor=None;self.reset_dimensions();self.update()
            else:self.message.emit(tr('Place at least two spline control points before pressing Enter.'))
            e.accept();return
        dims=self.live_dimensions(self.points,self.cursor) if self.mode=='sketch' else []
        if dims and e.key() in (Qt.Key_Tab,Qt.Key_Backtab):
            if self.commit_dimension_text():self.dimension_index=(self.dimension_index+(-1 if e.key()==Qt.Key_Backtab else 1))%len(dims)
            self.update();e.accept();return
        if dims and e.key() in (Qt.Key_Return,Qt.Key_Enter):
            if self.commit_dimension_text():self.draw_point(self.constrained_cursor(self.points,self.cursor,self.dimension_locks))
            e.accept();return
        if dims and e.key()==Qt.Key_Backspace:
            if self.dimension_typing:self.dimension_text=self.dimension_text[:-1]
            else:self.dimension_locks.pop(self.dimension_index,None);self.dimension_text='';self.dimension_typing=True
            self.update();e.accept();return
        if dims and e.text() and all(c in '0123456789.,-+' for c in e.text()) and not e.modifiers() & (Qt.ControlModifier|Qt.AltModifier):
            if not self.dimension_typing:self.dimension_text='';self.dimension_typing=True
            self.dimension_text+=e.text()
            try:
                value=float(self.dimension_text.replace(',','.'));label=dims[self.dimension_index][0]
                if math.isfinite(value) and (value>0 or label in ('Angle','Bend')):
                    self.dimension_locks[self.dimension_index]=value;self.cursor=self.constrained_cursor(self.points,self.cursor,self.dimension_locks)
            except ValueError:pass
            self.update();e.accept();return
        if e.key()==Qt.Key_Escape: self.cancel_tool(); self.message.emit(tr('Current drawing canceled.'))
        else: super().keyPressEvent(e)

    def camera_key(self):
        return (self.width(),self.height(),self.zoom,self.span,tuple(self.pan),tuple(self.center),tuple(self.rotation().ravel()),self.eye_distance())

    # ---- section plane --------------------------------------------------------------------
    def section_plane(self):
        """``(normal, distance)`` of the active section: the part with ``normal . x > distance`` is cut away."""
        if not self.section:return None
        normal=np.asarray(self.section['normal'],float);length=float(np.linalg.norm(normal))
        if length<1e-12:return None
        return normal/length,float(self.section['distance'])

    def set_section(self,section):
        self.section=section;self.pick_cache=None;self.cache_key=None;self.update()

    def kept_triangles(self):
        """Boolean mask of the triangles the section leaves visible (None when nothing is cut)."""
        plane=self.section_plane()
        if plane is None or not len(self.triangles):return None
        normal,distance=plane
        centroids=self.vertices[self.triangles].mean(axis=1)
        return centroids@normal<=distance+1e-9
    def body_material(self,index):
        value=self.materials.get(str(index),self.materials.get('default',{})) if isinstance(self.materials,dict) else {}
        color=value.get('color','#4baed6') if isinstance(value,dict) else '#4baed6'
        finish=value.get('finish','matte') if isinstance(value,dict) else 'matte'
        try:q=QColor(color);rgb=np.array([q.red(),q.green(),q.blue()],dtype=float)
        except Exception:rgb=np.array([75,174,214],dtype=float)
        code=float({'matte':0,'metallic':1,'wood':2}.get(finish,0))
        opacity=value.get('opacity',1.) if isinstance(value,dict) else 1.
        try:level=int(round(min(1.,max(.1,float(opacity)))*10))
        except (TypeError,ValueError):level=10
        # The renderer reads finish and opacity from one number: finish + 10 * tenths of opacity.
        return rgb,code+(10.*level if level<10 else 0.)

    def has_translucent_bodies(self):
        """True when some body is drawn with less than full opacity."""
        return bool(len(self.triangles)) and bool(np.any(self.triangle_materials()[1]>=10))

    def triangle_materials(self):
        key=(self.revision,repr(self.materials))
        if getattr(self,'triangle_material_key',None)==key:return self.triangle_material_cache
        ids,inverse=np.unique(self.body_ids,return_inverse=True)
        values=[self.body_material(int(body)) for body in ids]
        colors=np.asarray([value[0] for value in values],dtype=float).reshape((-1,3))
        codes=np.asarray([value[1] for value in values],dtype=float)
        self.triangle_material_key=key;self.triangle_material_cache=(colors[inverse],codes[inverse])
        return self.triangle_material_cache

    def rasterize(self):
        key=(self.revision,self.show_aa,self.camera_key(),repr(self.section))
        if self.cache_key==key:return
        width,height=self.width(),self.height()
        if not len(self.vertices):
            # Camera motion cannot change an empty face/depth buffer.
            if self.empty_size!=(width,height):
                self.empty_depth=np.full((height,width),-np.inf,np.float32)
                self.empty_ids=np.full((height,width),-1,np.int32);self.empty_size=(width,height)
            self.pixels=None;self.depth=self.empty_depth;self.face_buffer=self.empty_ids
        else:
            v=(self.vertices-self.center)@self.rotation().T;screen,_=self.project(self.vertices)
            triangles=self.triangles;face_ids=self.face_ids;bases,codes=self.triangle_materials()
            keep=self.kept_triangles()
            if keep is not None:triangles,face_ids,bases,codes=triangles[keep],face_ids[keep],bases[keep],codes[keep]
            normals=np.cross(v[triangles[:,1]]-v[triangles[:,0]],v[triangles[:,2]]-v[triangles[:,0]])
            lengths=np.linalg.norm(normals,axis=1);lengths[lengths==0]=1;normals/=lengths[:,None]
            light=np.array([-.3,.4,.85]);light/=np.linalg.norm(light);brightness=.42+.58*np.abs(normals@light)
            codes=codes%10;shade=brightness.copy();shade=np.where(codes==1,.25+.75*brightness,shade);shade=np.where(codes==2,.55+.45*brightness,shade)
            colors=np.ascontiguousarray(np.clip(shade[:,None]*bases,0,255),dtype=np.uint8)
            self.pixels,self.depth,self.face_buffer=self.rasterizer.render(screen,v[:,2],triangles,face_ids,colors,width,height,self.show_aa)
        self.cache_key=key

    def slot_status(self,hit):
        return {'face':'Click to choose this face','plane':'Click to choose this plane','construction':'Click to choose this construction plane',
                'sketch':'Click to choose this profile','curve':'Click to choose this curve','edge':'Click to choose this edge'}.get(hit.get('type'),'')

    def profile_hit(self,pos):
        """The closed sketch profile under the pointer that is not hidden behind a body, or None."""
        _,body_depth=self.body_hit(pos) if len(self.triangles) else (-1,-np.inf)
        for sketch,frame in reversed(self.sketches):
            p=self.local_at(pos,frame)
            if p is None:continue
            _,depth=self.project([world(frame,p)])
            if depth[0]<body_depth-.01:continue
            for profile in self.cached_profiles(sketch):
                poly=QPolygonF([QPointF(*t) for t in profile['points']])
                if not poly.containsPoint(QPointF(*p),Qt.OddEvenFill):continue
                if any(QPolygonF([QPointF(*t) for t in points]).containsPoint(QPointF(*p),Qt.OddEvenFill) for points in profile['hole_points']):continue
                return dict(type='sketch',sketch=sketch['id'],entities=profile['entities'],holes=profile['holes'],profile_mode='nested')
        return None

    def slot_hit(self,pos):
        """What a click at ``pos`` would choose for the tool's active input.

        ``slot_accept`` is the ordered list of kinds the input takes: 'curve' (sketch lines, arcs,
        splines, taken with the curves joined to them), 'profile' (a closed sketch region), 'plane'
        (an origin or construction plane), 'face', 'edge'. The first kind that has something under the
        pointer wins. The result carries a ``type`` the highlight code understands plus what the
        interface needs to build the reference (face index, 3D point on the face, ...).
        """
        accept=self.slot_accept or ()
        if not (0<=pos.x()<self.width() and 0<=pos.y()<self.height()):return None
        # Faces of a body are in front of the origin-plane squares: try them before planes.
        ordered=sorted(accept,key=lambda k:1 if k=='plane' else 0)
        for kind in ordered:
            if kind=='curve':
                hit=self.curve_at(pos)
                if hit is not None:return dict(type='curve',sketch=hit['sketch'],entities=hit['entities'],lines=hit['lines'],frame=hit['frame'],clicked=hit.get('clicked'))
            elif kind=='edge':
                index=self.edge_at(pos,visible_only=True)
                if index is not None:return dict(type='edge',index=int(index))
            elif kind=='profile':
                hit=self.profile_hit(pos)
                if hit is not None:return hit
            elif kind=='face':
                index,depth=self.body_hit(pos)
                if index>=0:
                    point=self.unproject(pos,depth) if math.isfinite(depth) else None
                    return dict(type='face',index=int(index),point=None if point is None else point.tolist())
            elif kind=='plane':
                for id_,poly in reversed(list(self.construction_polygons.items())):
                    if poly.containsPoint(QPointF(pos),Qt.OddEvenFill):return dict(type='construction',id=id_)
                self.prepare_planes()
                for name,poly in reversed(list(self.plane_polygons.items())):
                    if poly.containsPoint(QPointF(pos),Qt.OddEvenFill):return dict(type='plane',plane=name)
        return None

    def body_hit(self,pos):
        if not (0<=pos.x()<self.width() and 0<=pos.y()<self.height()):return -1,-np.inf
        if not self.gpu_enabled:
            self.rasterize()
            x,y=int(pos.x()),int(pos.y())
            return int(self.face_buffer[y,x]),float(self.depth[y,x])
        if not len(self.triangles):return -1,-np.inf
        index=self.pick_index()
        x,y=int(pos.x()),int(pos.y())
        if index['cells'] is None:candidates=np.arange(len(index['ids']))
        else:
            cell=min(y//self.PICK_CELL,index['rows']-1)*index['columns']+min(x//self.PICK_CELL,index['columns']-1)
            start,stop=index['starts'][cell],index['starts'][cell+1]
            candidates=index['cells'][start:stop]
            if len(index['large']):candidates=np.concatenate((candidates,index['large']))
        if not len(candidates):return -1,-np.inf
        t=index['corners'][candidates];z=index['depths'][candidates];q=np.array([pos.x(),pos.y()])
        a,b,c=t[:,0],t[:,1],t[:,2]
        d=(b[:,1]-c[:,1])*(a[:,0]-c[:,0])+(c[:,0]-b[:,0])*(a[:,1]-c[:,1])
        valid=np.abs(d)>1e-10;safe=np.where(valid,d,1.)
        u=((b[:,1]-c[:,1])*(q[0]-c[:,0])+(c[:,0]-b[:,0])*(q[1]-c[:,1]))/safe
        v=((c[:,1]-a[:,1])*(q[0]-c[:,0])+(a[:,0]-c[:,0])*(q[1]-c[:,1]))/safe
        mask=valid & (u>=-1e-7) & (v>=-1e-7) & (u+v<=1.0000001)
        if not mask.any():return -1,-np.inf
        depths=u*z[:,0]+v*z[:,1]+(1-u-v)*z[:,2]
        depths=np.where(mask,depths,-np.inf);best=int(np.argmax(depths))
        return int(self.face_ids[index['ids'][candidates[best]]]),float(depths[best])

    PICK_CELL=24

    def pick_index(self):
        """The projected triangles of the current view, bucketed on a screen grid.

        Hovering asks "which face is under the pointer" many times per second; testing every
        triangle each time is linear in the model size. With the triangles sorted into 24 px
        cells, a query only looks at the few triangles that overlap the pointer's cell. The
        index is rebuilt when the camera, the mesh or the section plane changes.
        """
        key=(self.revision,self.camera_key(),repr(self.section))
        if self.pick_cache is not None and self.pick_cache[0]==key:return self.pick_cache[1]
        screen,depth=self.project(self.vertices)
        ids=np.arange(len(self.triangles));keep=self.kept_triangles()
        if keep is not None:ids=ids[keep]
        corners=screen[self.triangles[ids]];depths=depth[self.triangles[ids]]
        width,height=max(1,self.width()),max(1,self.height());cell=self.PICK_CELL
        columns=width//cell+1;rows=height//cell+1
        low=corners.min(axis=1);high=corners.max(axis=1)
        visible=(high[:,0]>=0)&(high[:,1]>=0)&(low[:,0]<width)&(low[:,1]<height)
        x0=np.clip(np.floor(low[:,0]/cell),0,columns-1).astype(np.int64);x1=np.clip(np.floor(high[:,0]/cell),0,columns-1).astype(np.int64)
        y0=np.clip(np.floor(low[:,1]/cell),0,rows-1).astype(np.int64);y1=np.clip(np.floor(high[:,1]/cell),0,rows-1).astype(np.int64)
        span=(x1-x0+1)*(y1-y0+1)
        large=np.flatnonzero(visible&(span>64))          # big triangles are tested for every query
        small=np.flatnonzero(visible&(span<=64));counts=span[small];total=int(counts.sum())
        index=dict(ids=ids,corners=corners,depths=depths,columns=columns,rows=rows,large=large,cells=None,starts=None)
        if total<=20_000_000:
            owner=np.repeat(np.arange(len(small)),counts);first=np.cumsum(counts)-counts
            local=np.arange(total)-np.repeat(first,counts)
            wide=(x1-x0+1)[small][owner]
            cell_id=(y0[small][owner]+local//wide)*columns+(x0[small][owner]+local%wide)
            order=np.argsort(cell_id,kind='stable')
            index['cells']=small[owner[order]]
            index['starts']=np.searchsorted(cell_id[order],np.arange(columns*rows+1))
        self.pick_cache=(key,index)
        return index

    def initializeGL(self):
        try:
            self.gpu=GpuRenderer(self.context())
            self.context().aboutToBeDestroyed.connect(self.cleanup_gl)
            print('SlothCAD graphics:',self.graphics_diagnostics(),flush=True)
        except Exception as err:
            self.gpu_error=str(err);self.graphics_issue.emit()

    def cleanup_gl(self):
        if self.gpu is not None:
            self.makeCurrent();self.gpu.destroy();self.gpu=None;self.doneCurrent()

    def graphics_diagnostics(self):
        lines=[tr('Backend:')+' '+tr('OpenGL' if self.gpu_enabled else 'CPU software')]
        if self.gpu:
            lines += [f'{k}: {v}' for k,v in self.gpu.info.items()]
            driver=self.gpu.info.get('renderer','').lower()
            if any(x in driver for x in ('llvmpipe','softpipe','software','swrast')):
                lines.append(tr('WARNING: OpenGL driver is software rendering on the CPU.'))
            lines.append(f'{tr("Mesh uploads:")} {self.gpu.uploads}')
        elif self.gpu_enabled:lines.append(tr('No working OpenGL context yet.')+' '+(self.gpu_error or ''))
        if self.gpu_error:lines.append(tr('Solid renderer error:')+' '+self.gpu_error)
        if self.software_body_fallback:lines.append(tr('Solid display fallback: CPU rasterizer (Qt OpenGL composition).'))
        if self.frame_times:lines.append(f'{tr("Median paint submission:")} {np.median(self.frame_times)*1000:.2f} '+tr('ms (excludes display/driver waits)'))
        lines.append(f'{tr("Display refresh rate:")} {self.display_rate:.0f} Hz · {tr("frame limit:")} {self.frame_rate:.0f} fps')
        lines += [f'{tr("Plane selector cache builds:")} {self.plane_cache_builds}',f'{tr("Motion events / applied batches:")} {self.motion_events} / {self.motion_batches}',f'{tr("Device pixel ratio:")} {self.devicePixelRatioF():g}',f'{tr("Triangles:")} {len(self.triangles)}',
                  __import__('platform_support').software_launch_hint()]
        return '\n'.join(lines)

    def paintGL(self):
        started=time.perf_counter()
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing,self.show_aa)
        p.drawImage(0,0,self.cached_background())
        if self.gpu and not self.software_body_fallback:
            p.beginNativePainting()
            try:self.gpu.draw(self)
            except Exception as err:
                self.gpu_error=str(err);self.software_body_fallback=True
                print('SlothCAD solid renderer error:',self.gpu_error,flush=True)
                self.graphics_issue.emit()
            finally:
                gl=getattr(self.gpu,'gl',None)
                if gl is not None and hasattr(self,'defaultFramebufferObject'):
                    gl.glBindFramebuffer(0x8D40,self.defaultFramebufferObject())
                    gl.glViewport(0,0,round(self.width()*self.devicePixelRatioF()),round(self.height()*self.devicePixelRatioF()))
                p.endNativePainting()
        if self.software_body_fallback or self.gpu is None:
            self.software_body_fallback=True;self.draw_software_body(p)
        self.paint_overlays(p,self.hover or self.selected_source);self.paint_measure(p);p.end()
        self.frame_times.append(time.perf_counter()-started)

    def cached_sketch(self,sketch):
        # Edits replace entities, so a compact value signature invalidates this cache.
        key=repr(sketch['entities'])
        id_=sketch['id'];entry=self.sketch_cache.get(id_)
        if self.preparing_sketches:return entry[1:] if entry else ([],[],set())
        if entry is None or entry[0]!=key:
            loops=regions(sketch);closed={i for ids in loops for i in ids}
            entry=(key,[(ids,region_points(sketch,ids)) for ids in loops],
                   [(i,e,sample(e)) for i,e in enumerate(sketch['entities'])],closed)
            self.sketch_cache[id_]=entry
        return entry[1:]

    def cached_profiles(self,sketch):
        key=repr(sketch['entities']);entry=self.profile_cache.get(sketch['id'])
        if self.preparing_sketches:return entry[1] if entry else []
        if entry is None or entry[0]!=key:
            entry=(key,profile_regions(sketch));self.profile_cache[sketch['id']]=entry
        return entry[1]

    def sketch_fill_path(self,loops,frame):
        """Visual union of closed sketch loops without turning nested loops transparent.

        Profile topology still treats nesting as separate selectable regions/holes; this
        is deliberately only a display rule so an inner profile remains visibly filled
        while sketching instead of looking like an empty cutout.
        """
        path=QPainterPath();path.setFillRule(Qt.WindingFill)
        for _,points in loops:
            projected=np.asarray(self.project_local(points,frame),dtype=float)
            if len(projected)<3:continue
            # Normalize winding so nested loops add to the fill instead of cancelling.
            area=float(np.sum(projected[:-1,0]*projected[1:,1]-projected[1:,0]*projected[:-1,1]))
            if area<0:projected=projected[::-1]
            path.addPolygon(QPolygonF([QPointF(*q) for q in projected]));path.closeSubpath()
        return path

    def project_many(self,arrays,frame=None):
        """Screen coordinates of many polylines in one projection call.

        ``frame`` given: the arrays hold sketch (x, y) points of that frame; otherwise 3D points.
        """
        width=2 if frame is not None else 3
        arrays=[np.asarray(a,dtype=float).reshape((-1,width)) for a in arrays]
        if not arrays:return []
        stack=np.vstack(arrays)
        if frame is not None:
            o,u,v,n=self.frame_axes(frame);stack=o+stack[:,0,None]*u+stack[:,1,None]*v
        screen=self.project(stack)[0];out=[];start=0
        for array in arrays:
            out.append(screen[start:start+len(array)]);start+=len(array)
        return out

    @staticmethod
    def thin_polyline(screen,gap=2.):
        """Drop points of a dense screen-space polyline that would land within ~``gap`` px of each
        other (a circle sampled with 64 points that is 25 px wide): the stroke looks the same and
        costs a fraction. Short or sparse polylines are returned unchanged."""
        count=len(screen)
        if count<=8:return screen
        lengths=np.hypot(np.diff(screen[:,0]),np.diff(screen[:,1]));average=float(lengths.sum())/(count-1)
        if average>=gap*.75:return screen
        step=int(np.ceil(gap/max(average,1e-3)))
        if step<=1:return screen
        return np.vstack((screen[::step],screen[-1:]))

    @staticmethod
    def polylines_path(screens,close=False,fill_rule=None,thin=True):
        path=QPainterPath()
        if fill_rule is not None:path.setFillRule(fill_rule)
        for screen in screens:
            if len(screen)<2:continue
            if thin:screen=Workspace.thin_polyline(screen)
            points=screen.tolist();path.moveTo(points[0][0],points[0][1])
            for x,y in points[1:]:path.lineTo(x,y)
            if close:path.closeSubpath()
        return path

    def sketch_paths(self,sketch,frame,loops,samples,closed):
        """Display paths of one sketch for the current view, rebuilt only when the view or sketch changes."""
        key=(self.camera_key(),sketch['id'])
        hit=self.screen_path_cache.get(sketch['id'])
        if hit is not None and hit[0]==key and hit[1] is loops and hit[2] is samples:return hit[3]
        loop_screens=self.project_many([points for _,points in loops],frame)
        fixed=[]
        for screen in loop_screens:
            if len(screen)<3:continue
            # Normalize winding so nested loops add to the fill instead of cancelling.
            area=float(np.sum(screen[:-1,0]*screen[1:,1]-screen[1:,0]*screen[:-1,1]))
            fixed.append(screen[::-1] if area<0 else screen)
        open_curves=[points for _,ent,points in samples if not ent.get('construction') and ent['kind']!='point' and ent['id'] not in closed]
        dots=[ent['p'] for _,ent,_ in samples if not ent.get('construction') and ent['kind']=='point']
        result=dict(fill=self.polylines_path(fixed,True,Qt.WindingFill),outline=self.polylines_path(loop_screens,True),
                    open=self.polylines_path(self.project_many(open_curves,frame)),loop_screens=loop_screens,
                    dots=self.project_local(dots,frame).tolist() if dots else [])
        if len(self.screen_path_cache)>64:self.screen_path_cache.clear()
        self.screen_path_cache[sketch['id']]=(key,loops,samples,result)
        return result

    def selected_profile_paths(self,sketch,frame,selected):
        """Fill and outline paths of the selected extrusion profiles of one sketch (one set of paths)."""
        profiles=self.cached_profiles(sketch)
        wanted=frozenset(frozenset(source.get('entities',[])) for source in selected)
        key=(self.camera_key(),sketch['id'],wanted)
        hit=self.selection_path_cache.get(sketch['id'])
        if hit is not None and hit[0]==key and hit[1] is profiles:return hit[2]
        chosen=[profile for profile in profiles if frozenset(profile.get('entities',[])) in wanted]
        if not chosen:
            result=None
        else:
            rings=self.project_many([profile['points'] for profile in chosen],frame)
            holes=self.project_many([hole for profile in chosen for hole in profile.get('hole_points',[])],frame)
            result=dict(fill=self.polylines_path(rings+holes,True,Qt.OddEvenFill),
                        rings=self.polylines_path(rings,True),holes=self.polylines_path(holes,True))
        if len(self.selection_path_cache)>16:self.selection_path_cache.clear()
        self.selection_path_cache[sketch['id']]=(key,profiles,result)
        return result

    def profile_path(self,profile,frame):
        path=QPainterPath();path.setFillRule(Qt.OddEvenFill)
        for points in [profile['points']]+profile['hole_points']:
            projected=self.project_local(points,frame);poly=QPolygonF([QPointF(*q) for q in projected])
            path.addPolygon(poly);path.closeSubpath()
        return path

    def draw_profile(self,p,profile,frame,color,fill):
        path=self.profile_path(profile,frame)
        tint=QColor(self.theme_color(fill));tint.setAlpha(128)
        p.fillPath(path,tint)
        # Boundaries are drawn separately, preserving full-opacity outlines.
        self.draw_polyline(p,self.project_local(profile['points'],frame),color,2,True)

    def static_text(self,p,x,y,text,font_key=None):
        key=(text,font_key if font_key is not None else p.font().toString())
        item=self.text_cache.get(key)
        if item is None:
            if len(self.text_cache)>64:self.text_cache.clear()
            item=QStaticText(text);item.setTextFormat(Qt.PlainText);self.text_cache[key]=item
        p.drawStaticText(QPointF(x,y-p.fontMetrics().ascent()),item)

    def pick(self,pos):
        x,y=int(pos.x()),int(pos.y())
        if not (0<=x<self.width() and 0<=y<self.height()): return None
        if self.mode=='support' and not self.extrude_selecting:
            # Construction planes win over what lies behind them, exactly as a click does.
            for id_,poly in reversed(list(self.construction_polygons.items())):
                if poly.containsPoint(QPointF(pos),Qt.OddEvenFill):return {'type':'construction','id':id_}
        face_id,body_depth=self.body_hit(pos) if len(self.triangles) else (-1,-np.inf)
        for sketch,frame in (reversed(self.sketches) if self.mode=='extrude' or self.extrude_selecting else []):
            p=self.local_at(pos,frame)
            if p is None:continue
            _,depth=self.project([world(frame,p)])
            if depth[0]<body_depth-.01:continue
            for profile in self.cached_profiles(sketch):
                poly=QPolygonF([QPointF(*t) for t in profile['points']])
                if not poly.containsPoint(QPointF(*p),Qt.OddEvenFill):continue
                if any(QPolygonF([QPointF(*t) for t in points]).containsPoint(QPointF(*p),Qt.OddEvenFill) for points in profile['hole_points']):continue
                return dict(type='sketch',sketch=sketch['id'],entities=profile['entities'],holes=profile['holes'],profile_mode='nested')
        if face_id>=0:
            face=self.faces[face_id]
            return {'type':'face','index':face_id,'face':face_reference(face)} if face.geomType()=='PLANE' else {'type':'curved','index':face_id}
        if self.mode=='support':
            self.prepare_planes()
            for name,poly in reversed(list(self.plane_polygons.items())):
                if poly.containsPoint(pos,Qt.OddEvenFill): return {'type':'plane','plane':name}
        return None

    PATH_KINDS=('line','arc','spline','conic')

    def set_path_picking(self,on):
        self.path_picking=bool(on);self.path_hover=None
        if on:self.extrude_selecting=False;self.hover=None
        self.update()

    def curve_at(self,pos,tolerance=9.):
        """The open sketch curve (and the connected chain it belongs to) under the cursor."""
        best=None
        for sketch,frame in self.sketches:
            if frame.get('spatial'):continue
            _,items,_=self.cached_sketch(sketch)
            for index,entity,points in items:
                if entity['kind'] not in self.PATH_KINDS or len(points)<2:continue
                screen=self.project_local(points,frame)
                a,b=screen[:-1],screen[1:];d=b-a;length=(d*d).sum(axis=1);length[length==0]=1.
                t=np.clip(((np.array([pos.x(),pos.y()])-a)*d).sum(axis=1)/length,0,1)
                gap=float(np.linalg.norm(a+d*t[:,None]-np.array([pos.x(),pos.y()]),axis=1).min())
                if gap<=tolerance and (best is None or gap<best[0]):best=(gap,sketch,frame,entity['id'])
        if best is None:return None
        _,sketch,frame,entity_id=best
        chain=self.curve_chain(sketch,entity_id)
        lookup={e['id']:e for e in sketch['entities']}
        lines=[sample(lookup[i]) for i in chain]
        return dict(type='curve',sketch=sketch['id'],entities=chain,lines=lines,frame=frame,clicked=entity_id)

    def curve_chain(self,sketch,start_id):
        """Entities joined end to end with ``start_id`` (stops where three curves meet)."""
        _,items,_=self.cached_sketch(sketch)
        ends={};info={}
        def key(point):return (round(float(point[0])*1e4),round(float(point[1])*1e4))
        for index,entity,points in items:
            if entity['kind'] not in self.PATH_KINDS or len(points)<2:continue
            a,b=key(points[0]),key(points[-1]);info[entity['id']]=(a,b)
            ends.setdefault(a,[]).append(entity['id']);ends.setdefault(b,[]).append(entity['id'])
        if start_id not in info:return [start_id]
        chain=[start_id];seen={start_id}
        for side in (0,1):
            current=start_id;point=info[start_id][side]
            while True:
                others=[i for i in ends.get(point,[]) if i!=current]
                if len(ends.get(point,[]))!=2 or not others:break
                nxt=others[0]
                if nxt in seen:break
                seen.add(nxt)
                # Walking from the clicked curve in each direction: the second direction is added in front.
                if side==0:chain.append(nxt)
                else:chain.insert(0,nxt)
                a,b=info[nxt];point=b if a==point else a;current=nxt
        return chain

    def snap_at(self,pos):
        p=self.local_at(pos,self.active_frame)
        if p is None:return None
        if self.preparing_sketches:return p
        if not self.snap_enabled: self.snap_label='free';return p
        key=repr(self.active['entities'])
        if key!=self.snap_cache_key:
            self.snap_cache_key=key;self.snap_cache_intersections=snap_intersections(self.active['entities'])
        q,label=snap(p,self.active['entities'],min(self.grid,self.adaptive_grid_step(22)),11/self.scale(),self.points,self.snap_cache_intersections)
        self.snap_label=label;return q

    def set_measure_active(self,active):
        self.measure_active=bool(active);self.measure_selection=[];self.measure_result=None;self.measure_hover=None;self.hover=None
        if active:self.points=[];self.cursor=None;self.reset_dimensions();self.setCursor(Qt.CrossCursor)
        else:self.setCursor(Qt.CrossCursor if self.mode in ('sketch','support','extrude','edge') else Qt.ArrowCursor)
        self.update()

    def measurement_scene(self,scenes):
        signature=tuple((s['id'],repr(s['entities']),tuple(tuple(sframe[k]) for k in ('origin','u','normal'))) for s,sframe in scenes)
        key=(self.camera_key(),self.revision,self.mode,signature)
        if key==self.measure_scene_key and self.measure_scene_cache is not None:return self.measure_scene_cache
        points=[];edges=[]
        if self.measure_vertices:
            world_points=np.asarray(self.measure_vertices,dtype=float);screens,depths=self.project(world_points)
            for index,(point,screen,depth) in enumerate(zip(world_points,screens,depths)):
                points.append((point,screen,float(depth),'Corner',('body-point',index),False))
        for index,(edge,poly) in enumerate(self.solid_edges):
            poly=np.asarray(poly,dtype=float);screen,depth=self.project(poly)
            edges.append((poly,screen,depth,dict(kind='edge',shape=edge,label='Edge',key=('body-edge',index)),False))
        for sketch,frame in scenes:
            active=self.mode=='sketch' and self.active and sketch['id']==self.active['id']
            for _,entity_,poly in self.cached_sketch(sketch)[1]:
                for index,point in enumerate(snap_points(entity_)):
                    world_point=world(frame,point);screen,depth=self.project([world_point])
                    points.append((world_point,screen[0],float(depth[0]),'Sketch point',('sketch-point',sketch['id'],entity_['id'],index),bool(active)))
                if entity_['kind']=='point':continue
                if entity_['kind'] in ('rectangle','polygon'):
                    candidates=[([a,b],index) for index,(a,b) in enumerate(zip(poly[:-1],poly[1:]))]
                else:candidates=[(poly,None)]
                for line,index in candidates:
                    world_line=np.asarray([world(frame,q) for q in line]);screen,depth=self.project(world_line)
                    descriptor=dict(kind='edge',entity=entity_,frame=frame,label='Sketch edge',key=('sketch-edge',sketch['id'],entity_['id'],index))
                    if index is not None:descriptor['segment']=index
                    edges.append((world_line,screen,depth,descriptor,bool(active)))
        for sketch,frame in self.spatial_scenes:
            for id_,shape in frame['edges'].items():
                if shape.ShapeType()=='Vertex':vertices=[shape.Center().toTuple()]
                else:vertices=[v.Center().toTuple() for v in shape.Vertices()]
                for i,point in enumerate(vertices):
                    screen,depth=self.project([point]);points.append((np.asarray(point),screen[0],float(depth[0]),'Sketch point',('spatial-point',sketch['id'],id_,i),False))
                if shape.ShapeType()=='Edge':
                    poly=np.asarray([shape.positionAt(float(t)).toTuple() for t in np.linspace(0,1,41)]);screen,depth=self.project(poly);edges.append((poly,screen,depth,dict(kind='edge',shape=shape,label='Sketch edge',key=('spatial-edge',sketch['id'],id_)),False))
        self.measure_scene_key=key;self.measure_scene_cache=(points,edges)
        return self.measure_scene_cache

    def measure_pick(self,pos):
        if self.preparing_sketches:return None
        q=np.array([pos.x(),pos.y()]);points=[];edges=[];regions_=[]
        scenes=list(self.sketches)
        if self.mode=='sketch' and self.active:
            scenes=[(self.active,self.active_frame)]+[(s,f) for s,f in scenes if s['id']!=self.active['id']]
        def visible(point):
            screen,depth=self.project([point]);_,front=self.body_hit(QPointF(*screen[0]))
            return depth[0]>=front-max(1e-5,self.span*1e-5)
        def candidate_edge(poly,screen,descriptor,priority=0):
            poly=np.asarray(poly);best=None
            if len(poly)<2:return
            delta=screen[1:]-screen[:-1];den=np.sum(delta*delta,axis=1)
            t=np.clip(np.sum((q-screen[:-1])*delta,axis=1)/np.maximum(den,1e-12),0,1)
            distances=np.linalg.norm(screen[:-1]+t[:,None]*delta-q,axis=1);i=int(np.argmin(distances))
            if distances[i]<9:best=(float(distances[i]),poly[i]+t[i]*(poly[i+1]-poly[i]))
            if best and (priority or visible(best[1])):
                descriptor=dict(descriptor)
                descriptor.update(anchor=best[1].tolist(),contours=[poly.tolist()]);edges.append((best[0],descriptor))
        point_records,edge_records=self.measurement_scene(scenes)
        if point_records:
            distances=np.linalg.norm(np.asarray([record[1] for record in point_records])-q,axis=1)
            for i in np.flatnonzero(distances<=8):
                point,screen,depth,label,key,priority=point_records[int(i)]
                if priority or visible(point):points.append((float(distances[i]),-depth,dict(kind='point',point=list(point),anchor=list(point),label=label,key=key,contours=[])))
        for poly,screen,depth,descriptor,priority in edge_records:candidate_edge(poly,screen,descriptor,priority)
        if points:return min(points,key=lambda item:item[:2])[2]
        if edges:return min(edges,key=lambda item:item[0])[1]
        for sketch,frame in scenes:
            priority=self.mode=='sketch' and self.active and sketch['id']==self.active['id']
            point=self.local_at(pos,frame)
            if point is None:continue
            for profile in self.cached_profiles(sketch):
                poly=QPolygonF([QPointF(*p) for p in profile['points']])
                if not poly.containsPoint(QPointF(*point),Qt.OddEvenFill):continue
                if any(QPolygonF([QPointF(*p) for p in ring]).containsPoint(QPointF(*point),Qt.OddEvenFill) for ring in profile['hole_points']):continue
                anchor=world(frame,point)
                if priority or visible(anchor):regions_.append(dict(kind='face',sketch=sketch,profile=profile,frame=frame,label='Sketch face',key=('sketch-face',sketch['id'],tuple(profile['entities'])),anchor=anchor.tolist(),contours=[[world(frame,p).tolist() for p in ring] for ring in [profile['points']]+profile['hole_points']]))
        face_id,depth=self.body_hit(pos)
        if regions_:return regions_[0]
        if face_id>=0:
            face=self.faces[face_id]
            return dict(kind='face',shape=face,label='Face',key=('body-face',face_id),anchor=list(face.Center().toTuple()),contours=[edge.tolist() for edge in self.face_edges[face_id]])
        # Free sketch points are useful for measurements between drawn geometry and the grid.
        if self.mode=='sketch':
            point=self.snap_at(pos)
            if point is not None:
                anchor=world(self.active_frame,point).tolist()
                return dict(kind='point',point=anchor,anchor=anchor,label='Sketch point',key=('free',tuple(anchor)),contours=[])
        return None

    def paint_measure(self,p):
        if not self.measure_active:return
        color=QColor('#55dce5' if self.theme=='dark' else '#087f95')
        for selection in self.measure_selection+([self.measure_hover] if self.measure_hover else []):
            for contour in selection.get('contours',[]):self.draw_polyline(p,self.project(contour)[0],color.name(),3)
            anchor=self.project([selection['anchor']])[0][0];p.setPen(QPen(color,2));p.setBrush(Qt.NoBrush);p.drawEllipse(QPointF(*anchor),5,5)
        if not self.measure_result or 'points' not in self.measure_result:return
        screen=self.project(self.measure_result['points'])[0];a,b=screen;direction=b-a;length=np.linalg.norm(direction)
        p.setPen(QPen(QColor(self.theme_color('#eaf0f5')),5));p.drawLine(QPointF(*a),QPointF(*b))
        p.setPen(QPen(color,2));p.drawLine(QPointF(*a),QPointF(*b));p.setBrush(color)
        for point in (a,b):
            p.drawEllipse(QPointF(*point),3,3)
            if length>1:
                normal=np.array([-direction[1],direction[0]])/length*6;p.drawLine(QPointF(*(point-normal)),QPointF(*(point+normal)))
        text=f"{self.measure_result['distance']:.4f} mm";width=p.fontMetrics().horizontalAdvance(text)+18
        center=(a+b)/2;rect=QRectF(max(4,min(center[0]-width/2,self.width()-width-4)),max(4,min(center[1]-32,self.height()-30)),width,26)
        p.setBrush(QColor(self.theme_color('#eaf0f5')));p.setPen(QPen(color,1));p.drawRoundedRect(rect,5,5);p.drawText(rect,Qt.AlignCenter,text)

    def edge_at(self,pos,visible_only=False):
        if not self.solid_edges:return None
        q=np.array([pos.x(),pos.y()]);best=None;distance=12.
        front_depth=-np.inf
        if visible_only:
            _,front_depth=self.body_hit(pos)
            if math.isfinite(front_depth):
                try:
                    box=self.mesh_shape.BoundingBox();tolerance=max(.03,math.sqrt(box.xlen**2+box.ylen**2+box.zlen**2)*.01)
                except Exception:tolerance=.05
            else:tolerance=0.
        # Vectorized over every edge segment: the old per-segment Python loop ran on
        # each hover update and made edge picking laggy on detailed models.
        starts,ends,owners=self.edge_segments()
        if not len(owners):return None
        a,za=self.project(starts);b,zb=self.project(ends)
        d=b-a;den=np.einsum('ij,ij->i',d,d)
        t=np.clip(np.einsum('ij,ij->i',q-a,d)/np.where(den>1e-9,den,1.),0,1);t=np.where(den>1e-9,t,0.)
        values=np.linalg.norm(a+d*t[:,None]-q,axis=1)
        if visible_only and math.isfinite(front_depth):
            values=np.where(za+(zb-za)*t<front_depth-tolerance,np.inf,values)
        index=int(np.argmin(values))
        if values[index]<distance:
            self.last_edge_hit_point=starts[index]+(ends[index]-starts[index])*float(t[index])   # where on the edge it was picked
            return int(owners[index])
        return best

    def edge_segments(self):
        """Segment start/end points of all solid edges, cached per scene revision."""
        key=(self.revision,len(self.solid_edges))
        if getattr(self,'edge_segment_key',None)!=key:
            starts=[];ends=[];owners=[]
            for index,(_,points) in enumerate(self.solid_edges):
                points=np.asarray(points,dtype=float).reshape((-1,3))
                if len(points)<2:continue
                starts.append(points[:-1]);ends.append(points[1:]);owners.append(np.full(len(points)-1,index))
            self.edge_segment_cache=(np.vstack(starts),np.vstack(ends),np.concatenate(owners)) if owners else (np.empty((0,3)),np.empty((0,3)),np.empty(0,dtype=int))
            self.edge_segment_key=key
        return self.edge_segment_cache

    def vertex_edges_at(self,pos):
        """Return all incident solid edges when the cursor hits a true vertex."""
        if not self.solid_vertices:return None
        points=np.asarray([item[0] for item in self.solid_vertices]);screen,depth=self.project(points)
        cursor=np.array([pos.x(),pos.y()]);distances=np.linalg.norm(screen-cursor,axis=1)
        nearest=float(np.min(distances))
        if nearest>9:return None
        candidates=np.flatnonzero(distances<=nearest+1.)
        _,front_depth=self.body_hit(pos)
        if math.isfinite(front_depth):
            try:
                box=self.mesh_shape.BoundingBox();tolerance=max(.03,math.sqrt(box.xlen**2+box.ylen**2+box.zlen**2)*.01)
            except Exception:tolerance=.05
            candidates=candidates[depth[candidates]>=front_depth-tolerance]
            if not len(candidates):return None
        index=int(candidates[np.argmax(depth[candidates])])
        self.last_vertex_point=np.asarray(self.solid_vertices[index][0],float)
        return self.solid_vertices[index][1]

    def edge_group(self,index):
        """The clicked edge plus, with Tangent chain on, every edge joined to it smoothly."""
        if not self.edge_tangent_chain or index is None:return [index] if index is not None else []
        key=(self.revision,len(self.solid_edges))
        if getattr(self,'edge_chain_key',None)!=key:
            from edge_chain import end_directions
            self.edge_chain_directions=end_directions([edge for edge,_ in self.solid_edges]);self.edge_chain_key=key
        from edge_chain import tangent_chain
        return tangent_chain(self.edge_chain_directions,index) or [index]

    def selected_edge_objects(self):
        return [self.solid_edges[i][0] for i in sorted(self.selected_edges) if 0<=i<len(self.solid_edges)]

    def mousePressEvent(self,e):
        self.finish_camera_animation()
        self.flush_motion()
        self.setFocus();self.last=QPointF(e.position());self.press_position=QPointF(e.position());self.drag=False;self.press_modifiers=e.modifiers();self.box=None
        if e.button()==Qt.LeftButton and self.gizmo.press(e.position()):return
        if self.measure_active:return
        if self.mode=='edge' and e.button()==Qt.LeftButton:
            self.edge_click_pending=True   # toggled on release unless the pointer was dragged (orbit)
            return
        if self.mode=='sketch' and e.button()==Qt.LeftButton:
            if self.tool=='project':
                index=self.edge_at(e.position(),visible_only=True)
                if index is not None:self.projection_picked.emit(index)
                return
            if self.tool=='constraint':
                from constraint_ui import pick_reference
                ref=pick_reference(self,e.position(),self.constraint_kind,self.constraint_refs)
                if ref is not None:self.constraint_picked.emit(ref)
                return
            if self.tool in self.SELECTION_TOOLS:
                if self.pattern_stage=='center':
                    point=self.snap_at(e.position())
                    if point is not None:self.pattern_center_picked.emit(point.tolist())
                else:
                    index=self.entity_at(e.position())
                    if index is not None:
                        if self.pattern_stage=='axis':
                            if self.active['entities'][index]['kind']=='line':self.mirror_axis_picked.emit(index)
                            else:self.message.emit(tr('Choose a straight sketch line as the mirror guide.'))
                        else:
                            if index in self.pattern_selection:self.pattern_selection.remove(index)
                            else:
                                self.pattern_selection.add(index)
                                try:
                                    from geometry import nearest_on_entity
                                    here=self.local_at(e.position(),self.active_frame)
                                    if here is not None:self.pattern_pick=(index,np.asarray(nearest_on_entity(self.active['entities'][index],here),float).tolist())
                                except Exception:self.pattern_pick=None
                            self.pattern_selection_changed.emit()
                self.update();return
            if self.tool in ('fillet','chamfer'):
                point=self.local_at(e.position(),self.active_frame)
                if point is not None:self.corner_requested.emit(point.tolist())
                return
            if self.tool in ('trim','extend'):
                index=self.entity_at(e.position());point=self.local_at(e.position(),self.active_frame)
                if index is not None and point is not None:self.trim_requested.emit(index,point.tolist())
                return
            point=self.snap_at(e.position())
            if point is None:return
            if self.tool=='select':
                found=None;distance=10/self.scale()
                from geometry import nearest_on_entity
                for i,ent,points in self.cached_sketch(self.active)[1]:
                    d=np.linalg.norm(nearest_on_entity(ent,point)-point)
                    if d<distance:found=i;distance=d
                from constraint_ui import pick_reference
                self.sketch_drag_ref=None if (e.modifiers()&Qt.ShiftModifier or self.drag_selects) else pick_reference(self,e.position(),'drag')
                if self.sketch_drag_ref is not None:
                    if self.sketch_drag_ref['kind']=='line':self.sketch_drag_ref={'kind':'entity','entity':self.sketch_drag_ref['entity']}
                    found=next(i for i,ent in enumerate(self.active['entities']) if ent['id']==self.sketch_drag_ref['entity'])
                start=self.local_at(e.position(),self.active_frame)
                self.sketch_drag_start=start.tolist() if start is not None else point.tolist();self.sketch_drag_active=False
                self.selected_entity=found
                if found is not None:self.entity_picked.emit(found)
            else:
                if not self.commit_dimension_text():return
                self.draw_point(self.constrained_cursor(self.points,point,self.dimension_locks))
        self.update()
    def queue_motion(self,position,buttons):
        self.motion_events+=1
        position=QPointF(position)
        if buttons and self.press_position is not None:
            delta=position-self.press_position
            if abs(delta.x())+abs(delta.y())>2:self.drag=True
        # Replace stale positions; camera deltas use the last applied position.
        self.pending_motion=(position,buttons)
        if not self.motion_timer.isActive():self.motion_timer.start()

    def face_edge_indices(self,face_index):
        """Indices (into ``solid_edges``) of the edges that bound one displayed face."""
        if not 0<=face_index<len(self.faces):return ()
        key=(self.revision,len(self.solid_edges))
        if getattr(self,'edge_lookup_key',None)!=key:
            table={}
            for index,(edge,_) in enumerate(self.solid_edges):table.setdefault(edge.hashCode(),[]).append(index)
            self.edge_lookup=table;self.edge_lookup_key=key
        found=[]
        for edge in self.faces[face_index].Edges():
            for index in self.edge_lookup.get(edge.hashCode(),()):
                if self.solid_edges[index][0].isSame(edge):found.append(index);break
        return tuple(found)

    def select_all_edges(self):
        self.selected_edges=set(range(len(self.solid_edges)))
        self.edge_selection_changed.emit();self.update()

    def clear_edge_selection(self):
        self.selected_edges.clear();self.edge_selection_changed.emit();self.update()

    def toggle_edge_at(self,position):
        group=self.vertex_edges_at(position);picked=getattr(self,'last_vertex_point',None) if group is not None else None
        if group is None:
            index=self.edge_at(position,visible_only=True);group=() if index is None else tuple(self.edge_group(index))
            picked=getattr(self,'last_edge_hit_point',None)
            if not group:
                # Not near an edge: a click on a face takes every edge of that face (Fusion and FreeCAD do the same).
                face_id,depth=self.body_hit(position)
                if face_id>=0:
                    group=self.face_edge_indices(face_id)
                    if math.isfinite(depth):picked=self.unproject(position,depth)
        if group:
            if set(group).issubset(self.selected_edges):self.selected_edges.difference_update(group)
            else:
                self.selected_edges.update(group)
                if picked is not None:self.last_edge_pick=np.asarray(picked,float)   # the arrow starts where you clicked
            self.edge_selection_changed.emit();self.update()

    def mouseMoveEvent(self,e):
        self.queue_motion(e.position(),e.buttons());e.accept()

    def motion_status(self,text):
        now=time.perf_counter()
        if text!=self.last_motion_status and now-self.last_status_time>=.1:
            self.message.emit(tr(text));self.last_motion_status=text;self.last_status_time=now

    def mark_camera_moving(self):
        self.camera_busy=True;self.camera_settle.start()

    def settle_camera(self):
        self.camera_busy=False;self.update()

    # ---- box (rubber band) selection ---------------------------------------------------
    def selection_context(self):
        """What a rubber band selects right now, or None when nothing can be box-selected."""
        if self.measure_active or self.gizmo.dragging or self.construction_point_picking:return None
        if self.mode=='extrude' or self.extrude_selecting:return 'extrude'
        if self.mode=='edge':return 'edge'
        if self.solid_face_picking:return 'faces'
        if self.mode=='sketch' and self.active is not None and self.tool in ('select',)+self.SELECTION_TOOLS:return 'entities'
        return None

    def box_wanted(self):
        if self.selection_context() is None:return False
        return bool(self.press_modifiers&Qt.ShiftModifier) or self.drag_selects

    @staticmethod
    def rect_hits(points,rect,crossing):
        """Does a screen polyline lie inside ``rect`` (window) or touch it (crossing)?"""
        points=np.asarray(points,dtype=float).reshape((-1,2))
        if len(points)==0:return False
        x0,y0,x1,y1=rect
        inside=(points[:,0]>=x0)&(points[:,0]<=x1)&(points[:,1]>=y0)&(points[:,1]<=y1)
        if not crossing:return bool(inside.all())
        if inside.any():return True
        if points[:,0].max()<x0 or points[:,0].min()>x1 or points[:,1].max()<y0 or points[:,1].min()>y1:return False
        # No vertex inside but the bounding boxes overlap: clip each segment against the rectangle.
        for p,q in zip(points[:-1],points[1:]):
            t0,t1=0.,1.;d=q-p;ok=True
            for k,(lo,hi) in enumerate(((x0,x1),(y0,y1))):
                if abs(d[k])<1e-12:
                    if p[k]<lo or p[k]>hi:ok=False;break
                else:
                    u0,u1=(lo-p[k])/d[k],(hi-p[k])/d[k]
                    if u0>u1:u0,u1=u1,u0
                    t0=max(t0,u0);t1=min(t1,u1)
                    if t0>t1:ok=False;break
            if ok:return True
        return False

    def box_rect(self):
        a,b=self.box['start'],self.box['current']
        return (min(a.x(),b.x()),min(a.y(),b.y()),max(a.x(),b.x()),max(a.y(),b.y())),b.x()<a.x()

    def finish_box(self,modifiers):
        rect,crossing=self.box_rect();context=self.selection_context();self.box=None
        if context is None or (rect[2]-rect[0]<4 and rect[3]-rect[1]<4):return
        mode='remove' if modifiers&Qt.ControlModifier else 'add'
        try:
            if context=='edge':self.box_select_edges(rect,crossing,mode)
            elif context=='entities':self.box_select_entities(rect,crossing,mode)
            elif context=='extrude':self.box_select_sources(rect,crossing,mode)
            elif context=='faces':
                self.box_selected.emit(dict(kind='faces',mode=mode,indices=self.faces_in_rect(rect,crossing,planar_only=False)))
        except Exception as error:self.message.emit(str(error))

    def box_select_edges(self,rect,crossing,mode):
        hits=set()
        for index,(_,poly) in enumerate(self.solid_edges):
            screen=self.project(np.asarray(poly,dtype=float).reshape((-1,3)))[0]
            if self.rect_hits(screen,rect,crossing):hits.add(index)
        if mode=='remove':self.selected_edges.difference_update(hits)
        else:self.selected_edges.update(hits)
        self.message.emit(f'{len(self.selected_edges)} '+tr('edges selected'))
        self.edge_selection_changed.emit();self.update()

    def box_select_entities(self,rect,crossing,mode):
        hits=set()
        for index,ent,points in self.cached_sketch(self.active)[1]:
            screen=self.project_local(points,self.active_frame)
            if self.rect_hits(screen,rect,crossing):hits.add(index)
        if mode=='remove':self.pattern_selection.difference_update(hits)
        else:self.pattern_selection.update(hits)
        self.selected_entity=None
        self.message.emit(f'{len(self.pattern_selection)} '+tr('sketch entities selected'))
        self.pattern_selection_changed.emit();self.update()

    def faces_in_rect(self,rect,crossing,planar_only=True):
        """Indices of the front-facing faces whose screen box lies inside / touches the rectangle."""
        if not len(self.triangles):return []
        screen=self.project(self.vertices)[0];towards=self.rotation()[2]
        result=[]
        for index,face in enumerate(self.faces):
            if planar_only and face.geomType()!='PLANE':continue
            rows=np.flatnonzero(self.face_ids==index)
            if not len(rows):continue
            tri=self.triangles[rows];pts=screen[np.unique(tri.ravel())]
            x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0)
            inside=x0>=rect[0] and x1<=rect[2] and y0>=rect[1] and y1<=rect[3]
            touches=not (x1<rect[0] or x0>rect[2] or y1<rect[1] or y0>rect[3])
            if not (touches if crossing else inside):continue
            xyz=self.vertices[tri]
            normal=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]).sum(axis=0)
            if float(normal@towards)<=0:continue            # the back side of the body
            result.append(index)
        return result

    def box_select_sources(self,rect,crossing,mode):
        """Sketch profiles and planar faces inside / touching the rectangle, as extrusion sources."""
        hits=[]
        for sketch,frame in self.sketches:
            for profile in self.cached_profiles(sketch):
                screen=self.project_local(profile['points'],frame)
                if self.rect_hits(screen,rect,crossing):
                    hits.append(dict(type='sketch',sketch=sketch['id'],entities=profile['entities'],holes=profile['holes'],profile_mode='nested'))
        from geometry import face_reference
        for index in self.faces_in_rect(rect,crossing):
            hits.append({'type':'face','index':index,'face':face_reference(self.faces[index])})
        self.box_selected.emit(dict(kind='extrude',mode=mode,hits=hits))

    def paint_box(self,p):
        if self.box is None:return
        (x0,y0,x1,y1),crossing=self.box_rect()
        color=QColor('#58c27d' if crossing else '#4a90e2')
        fill=QColor(color);fill.setAlpha(45)
        pen=QPen(color,1.5)
        if crossing:pen.setStyle(Qt.DashLine)
        p.save();p.setPen(pen);p.setBrush(fill);p.drawRect(QRectF(x0,y0,x1-x0,y1-y0));p.restore()

    def orbit_allowed(self):
        """Left-drag orbits the view in the solid workspace and while picking for a tool."""
        return self.mode in ('model','support','extrude','edge')

    def flush_motion(self):
        self.motion_timer.stop()
        motion=self.pending_motion;zoom=self.pending_zoom
        self.pending_motion=None;self.pending_zoom=0.
        if motion is None and not zoom:return
        self.motion_batches+=1;previous_hover=self.hover;camera_changed=bool(zoom)
        if zoom:
            # No practical viewport zoom barrier: keep only floating-point safety limits.
            factor=math.exp(math.log(1.15)*max(-1000.,min(1000.,float(zoom))))
            self.zoom=max(1e-120,min(1e120,self.zoom*factor))
        if motion is not None:
            position,buttons=motion
            if self.gizmo.consume_release:
                if self.gizmo.dragging:self.gizmo.move(position)
                self.last=position;self.update();return
            if buttons&Qt.LeftButton and not buttons&(Qt.RightButton|Qt.MiddleButton) and self.press_position is not None and self.drag and self.box_wanted():
                self.box=dict(start=QPointF(self.press_position),current=QPointF(position));self.last=position
                self.update();return
            if self.last is not None and buttons:
                delta=position-self.last
                if buttons&(Qt.RightButton|Qt.MiddleButton):
                    self.pan+=np.array([delta.x(),delta.y()]);camera_changed=True
                elif self.orbit_allowed() and buttons&Qt.LeftButton:
                    self.aligned=None;self.yaw=(self.yaw+delta.x()*.5)%360
                    self.pitch=max(-90,min(90,self.pitch+delta.y()*.5));camera_changed=True
                self.last=position
            if self.measure_active:
                self.measure_hover=self.measure_pick(position) if not buttons and not camera_changed else None
                if self.measure_hover:self.motion_status(tr('Measure')+' · '+tr(self.measure_hover['label']))
                self.update()
            elif self.mode=='sketch':
                if self.tool=='select' and buttons&Qt.LeftButton and self.sketch_drag_ref is not None and self.drag:
                    point=self.local_at(position,self.active_frame)
                    if point is not None:
                        if not self.sketch_drag_active:
                            self.sketch_drag_active=True;self.sketch_drag_started.emit(self.sketch_drag_ref,self.sketch_drag_start)
                        if self.snap_enabled:
                            step=self.adaptive_grid_step(22);point=np.round(point/step)*step
                        self.sketch_drag_position=point.tolist();self.sketch_drag_moved.emit(self.sketch_drag_position)
                    self.update();return
                self.cursor=self.local_at(position,self.active_frame) if self.tool=='trim' else self.snap_at(position)
                self.cursor=self.constrained_cursor(self.points,self.cursor,self.dimension_locks)
                if self.cursor is not None:self.motion_status(f'{tr(self.tool.title())} · {self.cursor[0]:.3f}, {self.cursor[1]:.3f} mm · {tr("snap:")} {tr(self.snap_label)}')
                self.hover_position=QPointF(position)
            elif self.mode=='edge':
                index=self.edge_at(position) if not buttons else None
                self.hover={'type':'edge','index':index} if index is not None else None
                if self.hover:self.motion_status('Click an edge to toggle it; multiple edges can be selected.')
            elif self.slot_accept is not None and not self.construction_point_picking:
                self.hover=None if (camera_changed or buttons) else self.slot_hit(position)
                if self.hover:self.motion_status(self.slot_status(self.hover))
            elif self.path_picking:
                self.path_hover=None if (camera_changed or buttons) else self.curve_at(position)
                if self.path_hover:self.motion_status(tr('Click to use this curve as the path'))
            elif self.mode in ('support','extrude') or self.extrude_selecting:
                if camera_changed or buttons:
                    # Picking moving geometry is unnecessary during pan/zoom.
                    self.hover=None
                else:
                    self.hover=self.pick(position)
                    if self.hover:
                        text={'construction':tr('Click to sketch on this construction plane'),'plane':tr('Click to sketch on this origin plane'),'face':tr('Click to add/remove this planar face from the extrusion'),'sketch':tr('Click to add/remove this closed sketch profile from the extrusion'),'curved':tr('Choose a planar face; this face is curved')}[self.hover['type']] if self.extrude_selecting or self.mode=='extrude' else {'construction':tr('Click to sketch on this construction plane'),'plane':tr('Click to sketch on this origin plane'),'face':tr('Click this planar face'),'sketch':tr('Click this closed sketch profile'),'curved':tr('Choose a planar face; this face is curved')}[self.hover['type']]
                        self.motion_status(text)
        if camera_changed:self.mark_camera_moving()
        if motion is not None:
            cube_hover=None if (buttons or self.mode=='sketch') else self.cube_face_at(position)
            if cube_hover!=getattr(self,'cube_hover',None):
                self.cube_hover=cube_hover;self.update()
                if cube_hover:self.motion_status(tr('Click to look from this side'))
        if camera_changed or self.mode=='sketch' or self.hover!=previous_hover or self.path_picking:self.update()

    def mouseReleaseEvent(self,e):
        # Apply the final position even if release arrives before the 16 ms tick.
        self.queue_motion(e.position(),e.buttons()|e.button());self.flush_motion()
        if e.button()==Qt.LeftButton and not self.drag and self.box is None and self.mode!='sketch' and not self.gizmo.dragging:
            side=self.cube_face_at(e.position())
            if side:
                self.look_from(side);self.last=None;self.press_position=None;self.drag=False;self.update();return
        if e.button()==Qt.LeftButton and self.box is not None:
            self.edge_click_pending=False;self.finish_box(e.modifiers());self.last=None;self.press_position=None;self.drag=False;self.sketch_drag_ref=None;self.update();return
        if e.button()==Qt.LeftButton and self.gizmo.release():
            self.last=None;self.press_position=None;self.drag=False;self.update();return
        if e.button()==Qt.LeftButton and getattr(self,'edge_click_pending',False):
            self.edge_click_pending=False
            if self.mode=='edge' and not self.drag:self.toggle_edge_at(e.position())
        if getattr(self,'spatial_edit',None) and not self.measure_active and not self.solid_face_picking and e.button()==Qt.LeftButton and not self.drag:
            self.pick_spatial_point(e.position())
        elif self.slot_accept is not None and not self.construction_point_picking and not self.measure_active and e.button()==Qt.LeftButton and not self.drag and self.mode=='model':
            hit=self.slot_hit(e.position())
            self.slot_picked.emit(hit if hit else dict(type='none'))
        elif self.construction_point_picking and e.button()==Qt.LeftButton and not self.drag:
            hit=self.measure_pick(e.position())
            if hit and hit['kind']=='point':self.construction_point_picked.emit(hit['point'])
            else:self.message.emit(tr('Choose a model corner or sketch point.'))
        elif self.path_picking and e.button()==Qt.LeftButton and not self.drag:
            hit=self.curve_at(e.position())
            if hit is not None:self.path_picked.emit(dict(sketch=hit['sketch'],entities=list(hit['entities'])))
            else:self.message.emit(tr('Click one of the sketch curves to use it as the path.'))
        elif self.solid_face_picking and e.button()==Qt.LeftButton and not self.drag:
            index,depth=self.body_hit(e.position())
            if index>=0:
                if math.isfinite(depth):self.last_face_pick=self.unproject(e.position(),depth)
                self.solid_face_picked.emit(index)
        elif self.mode=='support' and e.button()==Qt.LeftButton and not self.drag and any(poly.containsPoint(e.position(),Qt.OddEvenFill) for poly in self.construction_polygons.values()):
            id_=next(id_ for id_,poly in self.construction_polygons.items() if poly.containsPoint(e.position(),Qt.OddEvenFill));self.support_picked.emit({'type':'construction','id':id_})
        elif self.measure_active and e.button()==Qt.LeftButton and not self.drag:
            hit=self.measure_pick(e.position())
            if hit:self.measure_picked.emit(hit)
        elif e.button()==Qt.LeftButton and not self.drag and (self.mode in ('support','extrude') or self.extrude_selecting):
            hit=self.pick(e.position())
            if hit and hit['type']!='curved':
                if self.mode=='support' and not self.extrude_selecting and hit['type'] in ('plane','face'):self.support_picked.emit(hit)
                elif (self.mode=='extrude' or self.extrude_selecting) and hit['type'] in ('face','sketch'):
                    self.selected_source=hit;self.extrusion_picked.emit(hit)
        if self.sketch_drag_active:
            self.sketch_drag_active=False;self.sketch_drag_finished.emit(self.sketch_drag_position)
        self.sketch_drag_ref=None
        self.last=None;self.press_position=None;self.drag=False;self.update()
    def wheelEvent(self,e):
        self.finish_camera_animation()
        if self.gizmo.dragging:e.accept();return
        delta=e.angleDelta().y()/120. if e.angleDelta().y() else e.pixelDelta().y()/60.
        self.pending_zoom+=delta
        if not self.motion_timer.isActive():self.motion_timer.start()
        e.accept()
    def mouseDoubleClickEvent(self,e):
        if self.gizmo.hit(e.position()) is not None:
            self.gizmo.editor.setFocus();self.gizmo.editor.selectAll();return
        if self.mode!='sketch':self.fit()

    def _circle_from_three(self,a,b,c):
        a,b,c=map(lambda q:np.asarray(q,dtype=float),(a,b,c));u,v=b-a,c-a;d=2*float(u[0]*v[1]-u[1]*v[0])
        if abs(float(d))<1e-9:raise ValueError('Circle points must not be collinear.')
        aa=float(a@a);bb=float(b@b);cc=float(c@c)
        ux=(aa*(b[1]-c[1])+bb*(c[1]-a[1])+cc*(a[1]-b[1]))/d
        uy=(aa*(c[0]-b[0])+bb*(a[0]-c[0])+cc*(b[0]-a[0]))/d
        center=np.array([ux,uy]);return center,float(np.linalg.norm(a-center))

    def center_arc_geometry(self,c,a,cursor):
        """Start, middle and end point of the arc a -> cursor around c.

        The sweep is tracked continuously while the mouse moves, so the arc grows
        in the direction the user is dragging and can pass 180 degrees (like
        Fusion's centre-point arc) instead of snapping to the short way round.
        """
        c,a,cursor=(np.asarray(q,dtype=float) for q in (c,a,cursor))
        r=float(np.linalg.norm(a-c))
        if r<1e-9 or float(np.linalg.norm(cursor-c))<1e-9:return None
        ta=math.atan2(a[1]-c[1],a[0]-c[0]);tb=math.atan2(cursor[1]-c[1],cursor[0]-c[0])
        raw=(tb-ta+math.pi)%(2*math.pi)-math.pi
        previous=getattr(self,'arc_sweep',None)
        if previous is None:sweep=raw
        else:
            turns=round((previous-raw)/(2*math.pi));sweep=raw+2*math.pi*turns
        limit=2*math.pi-1e-3
        sweep=max(-limit,min(limit,sweep));self.arc_sweep=sweep
        if abs(sweep)<1e-6:return None
        mid=c+r*np.array([math.cos(ta+sweep/2),math.sin(ta+sweep/2)]);end=c+r*np.array([math.cos(ta+sweep),math.sin(ta+sweep)])
        return a,mid,end

    def draw_point(self,p):
        self.reset_dimensions()
        if self.tool=='text' and self.text_box is not None:
            # One text box at a time: its settings are in the right panel.
            self.message.emit(tr('Place or cancel the current text before drawing a new text box.'));return
        self.cursor=np.asarray(p,dtype=float)
        self.point_redo=[];self.points.append(p.tolist())
        if len(self.points)<3:self.arc_sweep=None
        try:
            if self.tool=='arc' and len(self.points)==2 and math.dist(*self.points)<1e-6:
                self.points.pop();return
            if self.tool=='line' and len(self.points)==2:
                if math.dist(*self.points)<1e-6:self.points.pop();return
                self.entity_created.emit(entity('line',a=self.points[0],b=self.points[1]));self.points=[self.points[-1]]
            elif self.tool=='rectangle' and len(self.points)==2:
                a,b=map(np.array,self.points);size=np.abs(b-a)
                if min(size)<1e-6:self.points.pop();return
                self.entity_created.emit(entity('rectangle',center=((a+b)/2).tolist(),width=float(size[0]),height=float(size[1])));self.points=[]
            elif self.tool=='center_rectangle' and len(self.points)==2:
                c,q=map(np.array,self.points);size=2*np.abs(q-c)
                if min(size)<1e-6:self.points.pop();return
                self.entity_created.emit(entity('rectangle',center=c.tolist(),width=float(size[0]),height=float(size[1])));self.points=[]
            elif self.tool=='rectangle_3p' and len(self.points)==3:
                a,b,c=map(np.array,self.points);axis=b-a;length=np.linalg.norm(axis)
                if length<1e-6:raise ValueError('First rectangle edge needs two different points.')
                n=np.array([-axis[1],axis[0]])/length;height=float((c-a)@n)
                if abs(height)<1e-6:raise ValueError('Third point must be away from the first edge.')
                self.entity_created.emit(entity('polygon',points=[a.tolist(),b.tolist(),(b+n*height).tolist(),(a+n*height).tolist()]));self.points=[]
            elif self.tool=='circle' and len(self.points)==2:
                r=math.dist(*self.points)
                if r<1e-6:self.points.pop();return
                self.entity_created.emit(entity('circle',center=self.points[0],radius=r));self.points=[]
            elif self.tool=='circle_3p' and len(self.points)==3:
                center,r=self._circle_from_three(*self.points);self.entity_created.emit(entity('circle',center=center.tolist(),radius=r));self.points=[]
            elif self.tool=='arc' and len(self.points)==2:
                if math.dist(*self.points)<1e-6:
                    self.points.pop();self.message.emit(tr('Choose an end point different from the start.'))
            elif self.tool=='arc' and len(self.points)==3:
                from geometry import arc_data
                ent=entity('arc',a=self.points[0],mid=self.points[2],b=self.points[1]);arc_data(ent)
                self.entity_created.emit(ent);self.points=[]
            elif self.tool=='center_arc' and len(self.points)==3:
                c,a,end=map(np.array,self.points)
                if np.linalg.norm(a-c)<1e-6:raise ValueError('Choose a start point away from the center.')
                if np.linalg.norm(end-c)<1e-6:raise ValueError('Choose an end direction away from the center.')
                geometry=self.center_arc_geometry(c,a,end)
                if geometry is None:raise ValueError('Choose a different end angle.')
                self.entity_created.emit(entity('arc',a=geometry[0].tolist(),mid=geometry[1].tolist(),b=geometry[2].tolist()));self.points=[];self.arc_sweep=None
            elif self.tool=='polygon' and len(self.points)==2:
                self.entity_created.emit(entity('polygon',points=regular_polygon(self.points[0],self.points[1],self.polygon_sides,self.polygon_mode)));self.points=[]
            elif self.tool=='ellipse' and len(self.points)==3:
                c,major,q=map(np.array,self.points);axis=major-c;rx=np.linalg.norm(axis)
                if rx<1e-6:raise ValueError('Choose a major-axis point away from the center.')
                n=np.array([-axis[1],axis[0]])/rx;ry=abs(float((q-c)@n))
                if ry<1e-6:raise ValueError('Choose a minor radius away from the major axis.')
                self.entity_created.emit(entity('ellipse',center=c.tolist(),major=major.tolist(),minor_radius=ry));self.points=[]
            elif self.tool=='slot' and len(self.points)==3:
                a,b,q=map(np.array,self.points);axis=b-a;length=np.linalg.norm(axis)
                if length<1e-6:raise ValueError('Slot center points must be different.')
                n=np.array([-axis[1],axis[0]])/length;width=2*abs(float((q-a)@n))
                if width<1e-6:raise ValueError('Choose a slot width away from the center line.')
                self.entity_created.emit(entity('slot',a=a.tolist(),b=b.tolist(),width=width));self.points=[]
            elif self.tool=='spline':
                if len(self.points)>=4 and math.dist(self.points[0],self.points[-1])<1e-6:
                    self.entity_created.emit(entity('spline',basis='bspline',points=self.points[:-1],closed=True));self.points=[];self.cursor=None
                # Variable-length tool; every click adds a control point and Enter finishes it.
                if len(self.points)>1 and math.dist(self.points[-2],self.points[-1])<1e-6:self.points.pop()
            elif self.tool=='conic' and len(self.points)==3:
                self.entity_created.emit(entity('conic',a=self.points[0],b=self.points[1],control=self.points[2]));self.points=[]
            elif self.tool=='point' and len(self.points)==1:
                self.entity_created.emit(entity('point',p=self.points[0]));self.points=[]
            elif self.tool=='text' and len(self.points)==2:
                a,b=map(np.array,self.points);size=np.abs(b-a)
                if min(size)<1e-3:self.points.pop();self.message.emit(tr('Drag the text box larger than a point.'));return
                low,high=np.minimum(a,b),np.maximum(a,b)
                self.entity_created.emit(dict(kind='text_box',rect=[float(low[0]),float(low[1]),float(high[0]),float(high[1])]));self.points=[]
        except Exception as err:
            self.message.emit(tr(str(err))+' '+tr('Choose a bend point away from the chord.') if self.tool=='arc' else tr(str(err)))
            if self.tool=='arc' and len(self.points)>=3:self.points=self.points[:2]
            else:self.points=[]
        self.update()

    def draw_polyline(self,p,points,color,width=1,close=False,fill=None,dashed=False):
        if not len(points):return
        pen=QPen(QColor(self.theme_color(color)),width)
        if dashed:pen.setStyle(Qt.DashLine)
        p.setPen(pen);p.setBrush(QColor(self.theme_color(fill)) if fill else Qt.NoBrush)
        if len(points)==1:p.drawEllipse(QPointF(*points[0]),3,3);return
        poly=QPolygonF([QPointF(*a) for a in points])
        if close:p.drawPolygon(poly)
        else:p.drawPolyline(poly)

    def paintEvent(self,e):
        if self.gpu_enabled:return super().paintEvent(e)
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(0,0,self.cached_background());target=self.hover or self.selected_source
        self.draw_software_body(p)
        self.paint_overlays(p,target)
        self.paint_measure(p)
        p.end()

    def draw_software_body(self,p):
        if self.rasterizer is None:self.rasterizer=Rasterizer()
        self.rasterize();pixels=self.pixels;target=self.hover or self.selected_source
        if pixels is not None and target and target.get('type') in ('face','curved'):
            pixels=pixels.copy();mask=self.face_buffer==target['index']
            pixels[mask,:3]=(pixels[mask,:3]*.55+np.array([255,190,65])*.45).astype(np.uint8)
        if pixels is not None and self.mode=='sketch':
            pixels=pixels.copy();mask=self.face_buffer>=0
            pixels[mask,:3]=(pixels[mask,:3]*.45+np.array(QColor(COLORS[self.theme]['canvas']).getRgb()[:3])*.55).astype(np.uint8)
            pixels[mask,3]=(pixels[mask,3].astype(np.uint16)*150//255).astype(np.uint8)
        if pixels is not None:
            img=QImage(pixels.data,self.width(),self.height(),self.width()*4,QImage.Format_RGBA8888);p.drawImage(0,0,img)

    def prepare_planes(self):
        # Rasterize the translucent selector only when its projection changes.
        # Pointer highlights reuse immutable images instead of repeatedly sending
        # overlapping translucent polygons through the OpenGL paint engine.
        key=(self.camera_key(),self.devicePixelRatioF(),self.font().toString(),self.theme)
        if key==self.plane_cache_key:return
        span=plane_selector_size(self.span);items=[];self.plane_polygons={}
        for name,color,label in [('XY','#529fea','XY · Z normal'),('XZ','#63bd88','XZ · Y normal'),('YZ','#e99271','YZ · X normal')]:
            screen=self.project_local([[0,0],[span,0],[span,span],[0,span]],base_frame(name))
            poly=QPolygonF([QPointF(*t) for t in screen]);self.plane_polygons[name]=poly
            items.append((name,color,label,poly,screen.mean(axis=0)))
        bounds=QRectF()
        metrics=self.fontMetrics()
        for name,color,label,poly,center in items:
            bounds=bounds.united(poly.boundingRect())
            bounds=bounds.united(QRectF(float(center[0]),float(center[1])-metrics.ascent(),metrics.horizontalAdvance(label),metrics.height()))
        bounds=bounds.adjusted(-4,-4,4,4).intersected(QRectF(self.rect())).toAlignedRect()
        self.plane_image_origin=QPointF(bounds.topLeft());self.plane_images={}
        ratio=self.devicePixelRatioF()
        for selected in (None,'XY','XZ','YZ'):
            image=QImage(max(1,math.ceil(bounds.width()*ratio)),max(1,math.ceil(bounds.height()*ratio)),QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio);image.fill(Qt.transparent)
            painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing);painter.setFont(self.font())
            painter.translate(-bounds.x(),-bounds.y())
            for name,color,label,poly,center in items:
                painter.setPen(QPen(QColor(color),2));tint=QColor(color);tint.setAlpha(95 if selected==name else 40)
                painter.setBrush(tint);painter.drawPolygon(poly);painter.setPen(QColor(color));painter.drawText(QPointF(*center),label)
            painter.end();self.plane_images[selected]=image
        self.plane_cache_key=key;self.plane_cache_builds+=1

    def paint_constructions(self,p):
        self.construction_polygons={}
        for id_,name,frame in self.construction_items:
            o,u,v,n=axes(frame);size=max(5.,self.span*.22)
            if frame.get('axis'):
                points=self.project([o-n*size,o+n*size])[0];self.draw_polyline(p,points,'#bc9544',1.5,dashed=True);xy=self.project([o+n*size])[0][0]
            else:
                points=self.project([o-u*size-v*size,o+u*size-v*size,o+u*size+v*size,o-u*size+v*size])[0]
                poly=QPolygonF([QPointF(*q) for q in points]);self.construction_polygons[id_]=poly
                lit=self.mode=='support' and bool(self.hover) and self.hover.get('type')=='construction' and self.hover.get('id')==id_
                if lit:
                    # The plane under the cursor glows so it is clear which one a click will use.
                    glow=QColor('#f0ad45');glow.setAlpha(70);p.setPen(QPen(QColor('#f0ad45'),3));p.setBrush(glow);p.drawPolygon(poly)
                else:
                    p.setPen(QPen(QColor('#bc9544'),1,Qt.DashLine));tint=QColor('#dbbd78');tint.setAlpha(22);p.setBrush(tint);p.drawPolygon(poly)
                xy=points[2]
            p.setPen(QColor(self.theme_color('#9a762c')));self.static_text(p,float(xy[0]+4),float(xy[1]-4),name)

    def paint_body_fade(self,p):
        """Show the bodies in ``faded_bodies`` at about half opacity (a see-through look).

        The solid is drawn first; a 50 % wash in the canvas colour over just those bodies makes
        them read as translucent, so outlines that lie inside them show clearly.
        """
        ids=self.faded_bodies
        if not ids or not len(self.triangles) or len(self.body_ids)!=len(self.triangles):return
        key=(self.revision,self.camera_key(),tuple(sorted(ids)))
        if self.fade_key!=key:
            tris=self.triangles[np.isin(self.body_ids,list(ids))]
            path=QPainterPath();path.setFillRule(Qt.WindingFill)
            if len(tris) and len(tris)<=30000:
                screen=self.project(self.vertices)[0];a,b,c=screen[tris[:,0]],screen[tris[:,1]],screen[tris[:,2]]
                area=(b[:,0]-a[:,0])*(c[:,1]-a[:,1])-(c[:,0]-a[:,0])*(b[:,1]-a[:,1])
                for k in range(len(tris)):
                    q=(a[k],b[k],c[k]) if area[k]>=0 else (a[k],c[k],b[k])    # one winding so the pieces unite
                    path.addPolygon(QPolygonF([QPointF(float(x),float(y)) for x,y in q]));path.closeSubpath()
            self.fade_key=key;self.fade_path=path
        wash=QColor(self.theme_color('#eaf0f5'));wash.setAlpha(128)
        p.save();p.setPen(Qt.NoPen);p.setBrush(wash);p.drawPath(self.fade_path);p.restore()

    def draw_sketch_layers(self,p):
        """Closed sketch loops, open curves, points and the selected extrusion profiles."""
        for sketch,frame in self.sketches:
            loops,samples,closed=self.cached_sketch(sketch)
            # One path per sketch and camera view (all loops projected in a single call):
            # hundreds of separate polygon draws per frame were the main cost of busy sketches.
            paths=self.sketch_paths(sketch,frame,loops,samples,closed)
            tint=QColor(self.theme_color('#e8e1ef'));tint.setAlpha(128);p.fillPath(paths['fill'],tint)
            dense=paths['outline'].elementCount()>3000
            if dense:p.setRenderHint(QPainter.Antialiasing,False)     # thousands of segments: crisp enough, much cheaper
            p.setBrush(Qt.NoBrush);p.setPen(QPen(QColor(self.theme_color('#8d68ac')),2));p.drawPath(paths['outline'])
            if dense:p.setRenderHint(QPainter.Antialiasing,self.show_aa)
            p.setBrush(Qt.NoBrush);p.setPen(QPen(QColor(self.theme_color('#8d68ac')),2));p.drawPath(paths['open'])
            for x,y in paths['dots']:p.drawEllipse(QPointF(x,y),3,3)
        for sketch,frame in self.sketches:
            selected=[source for source in self.extrusion_selection if source.get('type')=='sketch' and source.get('sketch')==sketch.get('id')]
            if not selected:continue
            chosen=self.selected_profile_paths(sketch,frame,selected)
            if chosen is None:continue
            tint=QColor('#ffc45c');tint.setAlpha(105);p.fillPath(chosen['fill'],tint)
            p.setBrush(Qt.NoBrush)
            # A selection of many profiles is outlined in one thin pass: the wide glow is
            # stroked over thousands of segments and is not worth its cost there.
            dense=chosen['rings'].elementCount()+chosen['holes'].elementCount()>800
            if dense:p.setRenderHint(QPainter.Antialiasing,False)
            for color,width,key in (('#d79b24',7,'rings'),('#f5d27a',3,'rings'),('#d79b24',6,'holes'),('#f5d27a',2,'holes')):
                if dense and width>3:continue
                p.setPen(QPen(QColor(self.theme_color(color)),width,Qt.SolidLine,Qt.FlatCap,Qt.BevelJoin));p.drawPath(chosen[key])
            if dense:p.setRenderHint(QPainter.Antialiasing,self.show_aa)

    def paint_sketch_layer(self,p):
        """Draw the sketch layer; for a view that has not moved since the last paint it is a cached image.

        Moving the mouse, picking profiles or dragging a depth arrow repaints the workspace
        many times per second without changing the camera or the sketches, and stroking
        thousands of segments each time was the cost. While the camera moves (a new key on
        every frame) the layer is drawn directly, exactly as before.
        """
        if not self.sketches:return
        cached=[self.cached_sketch(sketch)[0] for sketch,_ in self.sketches]
        signature=(self.camera_key(),self.width(),self.height(),self.devicePixelRatioF(),self.theme,self.show_aa,
                   tuple((sketch['id'],id(loops),tuple(frame['origin']),tuple(frame['u']),tuple(frame['normal'])) for (sketch,frame),loops in zip(self.sketches,cached)),
                   tuple(sorted((source.get('sketch') or '',tuple(sorted(source.get('entities',[])))) for source in self.extrusion_selection if source.get('type')=='sketch')))
        if signature!=self.layer_seen:
            self.layer_seen=signature;self.layer_image=None;self.layer_refs=cached   # referenced, so their ids stay unique
            self.draw_sketch_layers(p);return
        if self.layer_image is None:
            ratio=self.devicePixelRatioF()
            image=QImage(max(1,math.ceil(self.width()*ratio)),max(1,math.ceil(self.height()*ratio)),QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio);image.fill(Qt.transparent)
            q=QPainter(image);q.setRenderHint(QPainter.Antialiasing,self.show_aa);self.draw_sketch_layers(q);q.end()
            self.layer_image=image
        p.drawImage(0,0,self.layer_image)

    def stroke_outlines(self,p,outlines,color,core=3,glow=0,dashed=False):
        """Project and stroke many 3D polylines as one fast path (see viewport_gizmo.stroke_fast)."""
        lines=[np.asarray(o) for o in outlines if len(o)>1]
        if not lines:return
        screen=self.project(np.vstack(lines))[0];path=QPainterPath();start=0
        for line in lines:
            count=len(line);segment=screen[start:start+count];start+=count
            path.moveTo(float(segment[0][0]),float(segment[0][1]))
            for x,y in segment[1:]:path.lineTo(float(x),float(y))
        from viewport_gizmo import stroke_fast
        stroke_fast(p,path,QColor(self.theme_color(color)),dashed=dashed,glow=glow,core=core)

    def paint_overlays(self,p,target):
        self.paint_body_fade(p)
        self.paint_grid_through_bodies(p)
        for sketch,frame in self.spatial_scenes:
            for path in __import__('spatial_sketch').sampled(sketch,frame):self.draw_polyline(p,self.project(path)[0],'#8d68ac',2)
        self.paint_constructions(p)
        self.stroke_outlines(p,[outline for index in self.solid_selected_faces if 0<=index<len(self.face_edges) for outline in self.face_edges[index]],'#d79b24',core=3)
        if self.mode=='support' or (self.slot_accept is not None and 'plane' in self.slot_accept):
            self.prepare_planes()
            selected=self.hover.get('plane') if self.hover else None
            if selected not in self.plane_images:selected=None
            p.drawImage(self.plane_image_origin,self.plane_images[selected])
        self.paint_sketch_layer(p)
        # Hover highlights stay dynamic (they change with every mouse move) and are drawn on top
        # of the static sketch layer.
        if target and target.get('sketch') is not None:
            for sketch,frame in self.sketches:
                if sketch['id']!=target.get('sketch'):continue
                loops,samples,closed=self.cached_sketch(sketch)
                paths=self.sketch_paths(sketch,frame,loops,samples,closed)
                for (ids,_),screen in zip(loops,paths['loop_screens']):
                    if target.get('entities')==ids or ids in target.get('holes',[]):self.draw_polyline(p,screen,'#cb8b21',2,True)
        # Persistent multi-extrude selection: selected profiles remain visibly lit
        # even after the mouse moves to another source.
        if target and target.get('type')=='sketch':
            wanted=frozenset(target.get('entities',[]))
            for sketch,frame in self.sketches:
                if sketch['id']!=target.get('sketch'):continue
                for profile in self.cached_profiles(sketch):
                    if frozenset(profile['entities'])==wanted:
                        tint=QColor('#ffc45c');tint.setAlpha(55)
                        p.fillPath(self.profile_path(profile,frame),tint)
        selected_faces={source.get('index') for source in self.extrusion_selection if source.get('type')=='face' and source.get('index') is not None}
        picked=[edge for index in selected_faces if 0<=index<len(self.face_edges) for edge in self.face_edges[index]]
        self.stroke_outlines(p,picked,'#d79b24',core=1,glow=110)
        self.stroke_outlines(p,picked,'#f5d27a',core=3)
        if target and target.get('type') in ('face','curved'):
            self.stroke_outlines(p,self.face_edges[target['index']],'#cb8b21',core=2)
        if self.mode=='edge':
            hover_index=target.get('index') if target and target.get('type')=='edge' else None
            hovered=set(self.edge_group(hover_index)) if hover_index is not None else set()
            # One projection and one stroke per group: a tangent chain can select hundreds of edges,
            # and stroking each with a wide antialiased pen cost seconds per frame.
            for indices,width in ((sorted(self.selected_edges),3),(sorted(i for i in hovered if i is not None and i not in self.selected_edges),2)):
                lines=[self.solid_edges[i][1] for i in indices if i is not None and 0<=i<len(self.solid_edges) and len(self.solid_edges[i][1])>1]
                if not lines:continue
                screen=self.project(np.vstack(lines))[0];path=QPainterPath();start=0
                for line in lines:
                    count=len(line);segment=screen[start:start+count];start+=count
                    path.moveTo(float(segment[0][0]),float(segment[0][1]))
                    for x,y in segment[1:]:path.lineTo(float(x),float(y))
                from viewport_gizmo import stroke_fast
                stroke_fast(p,path,QColor(self.theme_color('#cb8b21')),core=3 if width==3 else 2)
        if self.mode=='sketch' and self.active:
            loops,samples,_=self.cached_sketch(self.active)
            path=self.sketch_fill_path(loops,self.active_frame)
            tint=QColor(self.theme_color('#d6ebf3'));tint.setAlpha(128);p.fillPath(path,tint)
            for i,ent,points in samples:
                color='#d79b24' if i==self.selected_entity or i in self.pattern_selection else ('#c78bda' if i==self.pattern_axis else ('#2f8f5b' if ent.get('id') in self.constrained_entities else '#087ba5'))
                screen=self.project_local(points,self.active_frame);self.draw_polyline(p,screen,color,2,dashed=ent.get('construction',False))
                for pt in [ent.get('a'),ent.get('b'),ent.get('center'),ent.get('major'),ent.get('control'),ent.get('p')]:
                    if pt is not None:
                        x,y=self.project_local([pt],self.active_frame)[0];p.setBrush(QColor(color));p.drawEllipse(QPointF(x,y),3,3)
            from constraint_ui import paint_constraints
            paint_constraints(self,p)
            if not self.measure_active:self.paint_preview(p)
            self.paint_text_box(p)
        if self.pattern_center is not None and self.mode=='sketch':
            x,y=self.project_local([self.pattern_center],self.active_frame)[0]
            p.setPen(QPen(QColor('#e3a645'),2));p.setBrush(Qt.NoBrush);p.drawEllipse(QPointF(x,y),6,6)
            p.drawLine(QPointF(x-10,y),QPointF(x+10,y));p.drawLine(QPointF(x,y-10),QPointF(x,y+10))
        p.setPen(QColor(self.theme_color('#526778')))
        title={'model':'MODEL · one workspace','support':'CREATE SKETCH · select an origin plane or planar body face','extrude':'EXTRUDE · select one or more sketch profiles or planar faces','edge':'EDGE SELECT · click one or more edges','sketch':f'SKETCH · {self.tool.upper()} · {self.adaptive_grid_step(22):g} mm grid'}[self.mode]
        if self.extrude_selecting:title=f'EXTRUDE · {len(self.extrusion_selection)} SOURCE'+('' if len(self.extrusion_selection)==1 else 'S')+' SELECTED'
        if self.mode=='sketch' and self.tool in self.SELECTION_TOOLS:
            stage_title={'sources':'SELECT SOURCES','axis':'SELECT GUIDE LINE','center':'SELECT CENTER POINT'}[self.pattern_stage]
            title=f'SKETCH · {self.tool.upper()} · {stage_title}'
        if self.measure_active:title='Measure'
        self.static_text(p,18,28,tr(title))
        help_={'model':'Left drag: orbit   Right drag: pan   Wheel: zoom', 'support':'Blue: XY   Green: XZ   Orange: YZ   ·   Use plane buttons if a plane is edge-on',
               'extrude':'Click profiles/faces to toggle selection · all selected sources use the same depth',
               'edge':'Click edges to toggle selection · select several, then Apply in the right panel',
               'sketch':'Type: exact size · Tab: next field · Enter: place · L/R/C/A: draw · T: trim · X: guides · Esc: cancel'}[self.mode]
        if self.extrude_selecting:help_='Click a face/profile to add or remove it · drag to orbit · all selected sources extrude together'
        if self.mode=='sketch' and self.tool in ('fillet','chamfer'):help_='Click a corner where two sketch curves meet.'
        if self.mode=='sketch' and self.tool=='select':help_='Drag points or edges to edit geometry · driving constraints stay enforced · Esc cancels a drag'
        if self.mode=='sketch' and self.tool=='constraint':
            from constraint_ui import INSTRUCTIONS
            help_=INSTRUCTIONS[self.constraint_kind]
        if self.mode=='sketch' and self.tool=='center_arc':help_=['Center arc: click the center point','Center arc: click the start point on the arc','Center arc: move around the center, click where the arc should end'][min(len(self.points),2)]
        if self.mode=='sketch' and self.tool=='circle_3p':help_=['3-point circle: click the first point on the circle','3-point circle: click the second point','3-point circle: click the third point'][min(len(self.points),2)]
        if self.mode=='sketch' and self.tool=='arc':help_=['Arc: click the start point','Arc: click the end point','Arc: click a bend point away from the chord'][min(len(self.points),2)]
        if self.mode=='sketch' and self.tool=='spline':help_='Spline: click points · click the first point to close · Enter finishes open · Esc cancels'
        if self.mode=='sketch' and self.tool=='ellipse':help_=['Ellipse: click center','Ellipse: click the end of the major axis (it reaches the same distance on both sides)','Ellipse: click minor radius'][min(len(self.points),2)]
        if self.mode=='sketch' and self.tool=='slot':help_=['Slot: click first center','Slot: click second center','Slot: click to set width'][min(len(self.points),2)]
        if self.mode=='sketch' and self.tool=='text':help_=['Text: click the first corner of the text box','Text: click the opposite corner'][min(len(self.points),1)] if self.text_box is None else 'Text: set the text and format in the right panel · Ctrl+Enter places it · Esc cancels'
        if self.mode=='sketch' and self.tool in self.SELECTION_TOOLS:
            help_={'sources':'Selecting source geometry · click entities in the viewport or in the list on the right','axis':'Selecting the guide line · click a straight sketch line or choose one in the right panel','center':'Selecting the center point · click the workspace or enter X/Y in the right panel'}[self.pattern_stage]
        if self.path_picking:help_='Click a sketch curve to use it as the path · connected curves are taken together · drag to orbit'
        if self.solid_face_picking:help_='Click a face to select it · Shift+drag a box to select many · drag to orbit'
        if self.box is not None:help_='Release to select · left to right: inside the box · right to left: touching the box · Ctrl+Shift: remove'
        elif self.selection_context() is not None and self.mode in ('extrude','edge'):help_=help_+' · Shift+drag: box select'
        if self.construction_point_picking:help_='Click a model corner or sketch point · the picked coordinates are stored in the feature'
        if self.measure_active:help_='Click any point, corner, edge or face. Select a second object for the shortest distance between them. A third click starts a new measurement.'
        self.static_text(p,18,49,p.fontMetrics().elidedText(tr(help_),Qt.ElideRight,max(20,self.width()-115-getattr(self,'axes_shift',0))))
        self.paint_view_cube(p)

        for path in getattr(self,'reference_highlight',[]):
            self.draw_polyline(p,self.project(path)[0],'#dd76cf',3)
        if self.slot_accept is not None and self.hover:
            if self.hover.get('type')=='curve':
                for points in self.hover.get('lines',[]):self.draw_polyline(p,self.project_local(points,self.hover['frame']),'#f0ad45',4)
            elif self.hover.get('type')=='edge' and 0<=self.hover.get('index',-1)<len(self.solid_edges):
                self.stroke_outlines(p,[self.solid_edges[self.hover['index']][1]],'#cb8b21',core=3)
        if self.path_picking and self.path_hover:
            for points in self.path_hover['lines']:
                self.draw_polyline(p,self.project_local(points,self.path_hover['frame']),'#f0ad45',4)
        self.paint_box(p)
        self.gizmo.paint(p)

    def cached_background(self):
        frame_key=None if self.active_frame is None else tuple(tuple(self.active_frame[k]) for k in ('origin','u','normal'))
        ratio=self.devicePixelRatioF()
        key=(self.camera_key(),self.mode=='sketch',frame_key,self.show_grid,self.show_axes,self.grid,self.show_aa,ratio,self.font().toString(),self.theme,self.gl_draws_background_grid())
        if key!=self.background_key:
            # Two images are reused alternately: allocating and page-faulting a fresh full-window
            # buffer on every camera frame cost more than drawing the grid into it.
            width,height=math.ceil(self.width()*ratio),math.ceil(self.height()*ratio)
            buffers=self.__dict__.setdefault('background_buffers',[None,None]);slot=self.__dict__.get('background_slot',0)^1
            image=buffers[slot]
            if image is None or image.width()!=width or image.height()!=height or image.devicePixelRatio()!=ratio:
                image=QImage(width,height,QImage.Format_RGB32);image.setDevicePixelRatio(ratio);buffers[slot]=image
            self.background_slot=slot;image.fill(QColor(self.theme_color('#eaf0f5')))
            painter=QPainter(image);painter.setFont(self.font());painter.setRenderHint(QPainter.Antialiasing,self.show_aa)
            if self.show_grid:
                if self.mode=='sketch':self.paint_grid(painter)
                else:self.paint_model_grid(painter)
            painter.end();self.background_image=image;self.background_key=key;self.background_builds+=1
        return self.background_image

    def draw_segments(self,p,segments,frame,color,width=1):
        if len(segments)==0:return
        screen=self.project_local(np.asarray(segments,dtype=float).reshape((-1,2)),frame)
        p.setPen(QPen(QColor(self.theme_color(color)),width))
        p.drawLines([QLineF(a,b,c,d) for a,b,c,d in screen.reshape((-1,4)).tolist()])

    def adaptive_grid_step(self,target_pixels=24):
        """Unbounded 1/2/5 engineering grid, limited only by double precision."""
        scale=max(1e-300,min(1e300,abs(self.scale())))
        base=max(1e-300,min(1e300,abs(self.grid)))
        world=max(1e-300,min(1e300,float(target_pixels)/scale))
        exponent=max(-300,min(300,math.floor(math.log10(world)-math.log10(base))))
        power=base*(10.**exponent)
        chosen=None
        for factor in (1.,2.,5.,10.):
            step=factor*power
            if math.isfinite(step) and step*scale>=target_pixels:chosen=step;break
        if chosen is None:chosen=min(1e300,max(1e-300,10.*power))
        # Hysteresis: keep the previous step while it is still readable, so the numbers and lines do not
        # flip back and forth when the zoom hovers around a threshold.
        memory=self.__dict__.setdefault('grid_step_memory',{})
        previous=memory.get(target_pixels)
        if previous is not None and previous!=chosen and .8*target_pixels<=previous*scale<=2.9*target_pixels and previous/base>0:
            ratio=previous/chosen
            if ratio in (.1,.2,.5,.4,.25,2.,5.,10.,1.) or abs(math.log10(ratio))<1.01:chosen=previous
        memory[target_pixels]=chosen
        return chosen

    def grid_label(self,value,step):
        if abs(value)<abs(step)*1e-10:return '0'
        magnitude=abs(step)
        if 1e-4<=magnitude<1e7:
            decimals=max(0,min(12,-math.floor(math.log10(magnitude))))
            text=f'{value:.{decimals}f}'
            return text.rstrip('0').rstrip('.') if '.' in text else text
        return f'{value:.6g}'

    AXIS_COLORS=('#d0545c','#3fa468','#4b86d8')      # world X, Y, Z

    def plane_axis_color(self,vector):
        """The plain colour of an axis line and its ticks; only the numbers adapt to the theme."""
        return self.AXIS_COLORS[int(np.argmax(np.abs(np.asarray(vector,float))))]

    def axis_color(self,vector):
        """The colour of the world axis ``vector`` points along, readable on the current canvas.

        Lightened on dark themes and darkened on light ones so numbers and ticks stay visible.
        """
        base=QColor(self.AXIS_COLORS[int(np.argmax(np.abs(np.asarray(vector,float))))])
        dark_canvas=QColor(COLORS[self.theme].get('canvas','#eaf0f5')).lightness()<128
        mix,target=(.5,255) if dark_canvas else (.32,0)
        return QColor(*[int(round(c*(1-mix)+target*mix)) for c in (base.red(),base.green(),base.blue())])

    def draw_grid_labels(self,p,frame,low,high,step):
        """Axis numbers with a short tick on the axis line, both in the colour of that axis."""
        max_labels=26
        def label_values(a,b):
            # Absolute multiples of a 1/2/5 stride: a label stays where it is while the view moves or zooms
            # (slicing from the first visible line made every label hop whenever the border moved).
            first,last=math.ceil(a/step),math.floor((b+step*.5)/step)
            count=last-first+1
            if count<=0:return np.array([])
            need=max(1,math.ceil(count/max_labels));stride=1
            while stride<need:
                stride=stride*2 if str(stride)[0]=='1' else (stride*5//2 if str(stride)[0]=='2' else stride*2)
            ids=np.arange(first,last+1);return ids[ids%stride==0]*step
        xs=label_values(low[0],high[0]);ys=label_values(low[1],high[1])
        xs=xs[np.abs(xs)>=step*.25];ys=ys[np.abs(ys)>=step*.25]
        width,height=self.width(),self.height()
        o,u,v,n=self.frame_axes(frame)
        font_key=p.font().toString()
        colors=[self.axis_color(vec) for vec in (u,v)]
        # Every label position is projected in one call instead of one call per label.
        for values,axis,dx in ((xs,0,3),(ys,1,4)):
            if not len(values):continue
            local=np.zeros((len(values),2));local[:,axis]=values
            screen=self.project_local(local,frame)
            # The tick lies along the grid line through the label (the other axis direction), so it
            # is parallel to the grid lines in any view, including the tilted 3D one.
            line=self.project_local(np.array([[0.,0.],[0.,1.]] if axis==0 else [[0.,0.],[1.,0.]]),frame)
            direction=line[1]-line[0];length=float(np.linalg.norm(direction))
            perpendicular=direction/length if length>1e-9 else np.array([0.,1.])
            number_color=colors[axis];tick_color=QColor(self.plane_axis_color(u if axis==0 else v))
            for value,(x,y) in zip(values.tolist(),screen.tolist()):
                if -40<x<width+40 and -20<y<height+20:
                    p.setPen(QPen(tick_color,1.8));a=np.array([x,y])-perpendicular*5;b=np.array([x,y])+perpendicular*5
                    p.drawLine(QPointF(*a),QPointF(*b))
                    p.setPen(number_color);self.static_text(p,x+dx,y-3,self.grid_label(value,step),font_key)

    def grid_segments(self,low,high,step,finite=False):
        """Use one density; finite grids end on shared, complete cell boundaries."""
        first=[math.ceil(float(value)/step) for value in low]
        last=[math.floor(float(value)/step) for value in high]
        if finite:
            # the border moves in whole major cells, not one line at a time
            first=[5*math.floor(v/5) for v in first];last=[5*math.ceil(v/5) for v in last]
            low=np.array([value*step for value in first]);high=np.array([value*step for value in last])
        minor=[];major=[]
        for axis in (0,1):
            indices=np.arange(int(first[axis]),int(last[axis])+1)
            if finite:indices=indices[1:-1]            # the border is drawn separately
            lines=np.empty((len(indices),2,2));other=1-axis
            lines[:,:,axis]=(indices*step)[:,None]
            lines[:,0,other]=low[other];lines[:,1,other]=high[other]
            is_major=indices%5==0
            minor.append(lines[~is_major]);major.append(lines[is_major])
        return low,high,np.concatenate(minor),np.concatenate(major)

    def paint_model_grid(self,p,over=False):
        lines=not self.gl_draws_background_grid() or over
        plane='XY';rot=self.rotation()
        if abs(rot[2,2])<.1:plane='XZ' if abs(rot[2,1])>.5 else 'YZ'
        frame=base_frame(plane);o,u,v,n=self.frame_axes(frame);delta=self.center-o;center=np.array([delta@u,delta@v])
        extent=max(1e-300,min(1e300,max(self.width(),self.height())/(2*max(1e-300,abs(self.scale())))*1.15))
        step=self.adaptive_grid_step(24)
        low,high,minor,major=self.grid_segments(center-extent,center+extent,step,finite=True)
        if lines:
            self.draw_segments(p,minor,frame,'#cddae4')
            self.draw_segments(p,major,frame,'#bbcbd7')
        # One closed path gives the four sides identical corners and no overhang.
        corners=[[low[0],low[1]],[high[0],low[1]],[high[0],high[1]],[low[0],high[1]]]
        screen=self.project_local(corners,frame);border=QPainterPath()
        border.moveTo(float(screen[0,0]),float(screen[0,1]))
        for x,y in screen[1:]:border.lineTo(float(x),float(y))
        border.closeSubpath();p.setPen(QPen(QColor(self.theme_color('#bbcbd7')),1));p.drawPath(border)
        if self.show_axes:
            cu,cv=self.plane_axis_color(u),self.plane_axis_color(v)
            if lines and low[1]<=0<=high[1]:self.draw_segments(p,[[[low[0],0],[high[0],0]]],frame,cu,1.4)
            if lines and low[0]<=0<=high[0]:self.draw_segments(p,[[[0,low[1]],[0,high[1]]]],frame,cv,1.4)
            if not over:self.draw_grid_labels(p,frame,low,high,step)

    def paint_grid(self,p,over=False):
        lines=not self.gl_draws_background_grid() or over
        frame=self.active_frame
        corners=[self.local_at(QPointF(x,y),frame) for x,y in [(0,0),(self.width(),0),(0,self.height()),(self.width(),self.height())]]
        if any(c is None for c in corners):return
        step=self.adaptive_grid_step(22)
        low,high,minor,major=self.grid_segments(np.min(corners,axis=0),np.max(corners,axis=0),step)
        if lines:
            self.draw_segments(p,minor,frame,'#d2dee7')
            self.draw_segments(p,major,frame,'#bbcbd7')
        if self.show_axes:
            o,u,v,n=self.frame_axes(frame)
            if lines:
                self.draw_segments(p,[[[low[0],0],[high[0],0]]],frame,self.plane_axis_color(u),1.5)
                self.draw_segments(p,[[[0,low[1]],[0,high[1]]]],frame,self.plane_axis_color(v),1.5)
            if not over:self.draw_grid_labels(p,frame,low,high,step)

    # ---- view cube: the axis helper in the corner, with a see-through orientation box --------------
    CUBE_FACES=(
        # name,        normal,        text right,    text up,       view (yaw, pitch)
        ('TOP',    (0,0,1),  (1,0,0),  (0,1,0),  (180,90)),
        ('BOTTOM', (0,0,-1), (1,0,0),  (0,-1,0), (180,-90)),
        ('FRONT',  (0,-1,0), (1,0,0),  (0,0,1),  (180,0)),
        ('BACK',   (0,1,0),  (-1,0,0), (0,0,1),  (0,0)),
        ('RIGHT',  (1,0,0),  (0,1,0),  (0,0,1),  (90,0)),
        ('LEFT',   (-1,0,0), (0,-1,0), (0,0,1),  (-90,0)),
    )
    CUBE_HALF=21.

    def cube_origin(self):
        return np.array([self.width()-62-getattr(self,'axes_shift',0),96.])

    def cube_faces(self):
        """Screen polygons of the six faces for the current camera (nearest face last)."""
        rot=self.rotation();origin=self.cube_origin();h=self.CUBE_HALF
        def screen(world):
            w=np.asarray(world,float);return origin+np.array([rot[0]@w,-(rot[1]@w)])*h
        faces=[]
        for name,n,r,t,view in self.CUBE_FACES:
            n,r,t=(np.asarray(v,float) for v in (n,r,t))
            corners=[screen(n+r+t),screen(n-r+t),screen(n-r-t),screen(n+r-t)]
            centre=screen(n)
            faces.append(dict(name=name,depth=float(rot[2]@n),polygon=QPolygonF([QPointF(*c) for c in corners]),centre=centre,
                              right=np.array([rot[0]@r,-(rot[1]@r)]),down=np.array([-(rot[0]@t),rot[1]@t]),view=view))
        faces.sort(key=lambda f:f['depth'])
        return faces

    def cube_face_at(self,position):
        """The visible cube face under the mouse, or None."""
        if self.width()<200:return None
        point=QPointF(position)
        for face in reversed(self.cube_faces()):
            if face['depth']>.02 and face['polygon'].containsPoint(point,Qt.OddEvenFill):return face['name']
        return None

    def look_from(self,name):
        face=next((f for f in self.CUBE_FACES if f[0]==name),None)
        if face is None or self.mode=='sketch':return
        self.flush_motion();self.finish_camera_animation();start=self.camera_state()
        self.aligned=None;self.yaw,self.pitch=face[4]
        self.begin_camera_transition(start);self.update()

    def paint_view_cube(self,p):
        dark=QColor(COLORS[self.theme].get('canvas','#eaf0f5')).lightness()<128
        base=QColor('#dfe8f2') if dark else QColor('#51606f')
        hover=getattr(self,'cube_hover',None)
        p.save();p.setRenderHint(QPainter.Antialiasing,True)
        faces=self.cube_faces()
        for face in faces:
            visible=face['depth']>.02
            fill=QColor(base);fill.setAlpha(128 if visible else 34)      # 50 % opacity box
            if visible and face['name']==hover:fill=QColor('#f0ad45');fill.setAlpha(170)
            edge=QColor(base);edge.setAlpha(210 if visible else 90)
            p.setPen(QPen(edge,1.2));p.setBrush(fill);p.drawPolygon(face['polygon'])
        # The axes run along the box's edges from its lowest corner and stick out past it
        # (like Fusion's ViewCube), so they stay clear of the box and the face names.
        origin=self.cube_origin();rot=self.rotation();h=self.CUBE_HALF
        if self.show_axes:
            def screen(world):
                w=np.asarray(world,float);return origin+np.array([rot[0]@w,-(rot[1]@w)])*h
            corner=np.array([-1.,-1.,-1.])
            for axis,color,label in [(0,'#ed5b5b','X'),(1,'#6fd17f','Y'),(2,'#5b9bf0','Z')]:
                direction=np.zeros(3);direction[axis]=1.
                start=screen(corner);tip=screen(corner+direction*2.7)
                p.setPen(QPen(QColor(color),2.2));p.drawLine(QPointF(*start),QPointF(*tip))
                away=tip-start;norm=float(np.linalg.norm(away));away=away/norm if norm>1e-6 else np.array([0.,-1.])
                p.drawText(QPointF(*(tip+away*7-np.array([3.,-4.]))),label)
        # Face names, drawn flat on the visible faces.
        font=QFont(self.font());font.setPixelSize(40);font.setBold(True)
        text_color=QColor('#ffffff') if not dark else QColor('#0e1620')
        text_color=QColor('#10161d') if dark else QColor('#ffffff')
        for face in faces:
            if face['depth']<=.25:continue
            cache=self.__dict__.setdefault('cube_text_cache',{})
            cached=cache.get((face['name'],self.font().toString()))
            if cached is None:
                path=QPainterPath();path.addText(0,0,font,face['name']);box=path.boundingRect()
                path.translate(-box.center());cached=cache[(face['name'],self.font().toString())]=(path,box.width(),box.height())
            path,box_width,box_height=cached
            class _Box:pass
            box=_Box();box.width=lambda:box_width;box.height=lambda:box_height
            scale=min(self.CUBE_HALF*1.55/max(box.width(),1.),self.CUBE_HALF*.7/max(box.height(),1.))
            right,down=face['right'],face['down']
            transform=QTransform(right[0]*scale,right[1]*scale,down[0]*scale,down[1]*scale,float(face['centre'][0]),float(face['centre'][1]))
            p.setPen(Qt.NoPen);p.setBrush(text_color);p.drawPath(transform.map(path))
        p.restore()

    grid_over_bodies=True

    def gl_draws_background_grid(self):
        """True while the graphics card draws the grid lines itself (the painter then only adds numbers)."""
        return bool(self.gpu_enabled and self.gpu is not None and not self.software_body_fallback
                    and getattr(self.gpu,'grid_program',None) is not None and not getattr(self,'gl_grid_failed',False))

    def grid_gl_groups(self,which='over'):
        """Grid lines for the GPU pass: [((r, g, b), world segments (N, 2, 3)), ...].

        ``which`` is 'bg' (the normal grid, drawn before the solids) or 'over' (the half-strength
        grid that is depth-tested against the solids).
        """
        if not self.show_grid:return []
        if which=='over' and (not self.grid_over_bodies or not len(self.triangles)):return []
        frame=self.grid_plane_frame()
        if frame is None:return []
        o,u,v,n=self.frame_axes(frame)
        if self.mode=='sketch':
            corners=[self.local_at(QPointF(x,y),frame) for x,y in [(0,0),(self.width(),0),(0,self.height()),(self.width(),self.height())]]
            if any(c is None for c in corners):return []
            step=self.adaptive_grid_step(22)
            low,high,minor,major=self.grid_segments(np.min(corners,axis=0),np.max(corners,axis=0),step)
        else:
            delta=self.center-o;center=np.array([delta@u,delta@v])
            extent=max(1e-300,min(1e300,max(self.width(),self.height())/(2*max(1e-300,abs(self.scale())))*1.15))
            step=self.adaptive_grid_step(24)
            low,high,minor,major=self.grid_segments(center-extent,center+extent,step,finite=True)
        def world(local):
            local=np.asarray(local,float).reshape(-1,2,2)
            return o+local[:,:,0:1]*u+local[:,:,1:2]*v
        def rgb(color):
            c=QColor(self.theme_color(color));return (c.redF(),c.greenF(),c.blueF())
        groups=[(rgb('#cddae4'),world(minor)),(rgb('#bbcbd7'),world(major))]
        if self.show_axes:
            for vector,segment in ((u,[[[low[0],0],[high[0],0]]] if low[1]<=0<=high[1] else []),(v,[[[0,low[1]],[0,high[1]]]] if low[0]<=0<=high[0] else [])):
                if len(segment):
                    c=QColor(self.plane_axis_color(vector));groups.append(((c.redF(),c.greenF(),c.blueF()),world(segment)))
        return [(c,s) for c,s in groups if len(s)]

    def grid_plane_frame(self):
        """The frame whose grid is on screen: the sketch plane, or the base plane facing the camera."""
        if self.mode=='sketch':return self.active_frame
        rot=self.rotation();plane='XY'
        if abs(rot[2,2])<.1:plane='XZ' if abs(rot[2,1])>.5 else 'YZ'
        return base_frame(plane)

    def paint_grid_through_bodies(self,p):
        """Show the grid over the parts of bodies that lie behind the grid plane.

        The grid is a surface like any other: a body that is in front of it hides it, a body
        that is behind it (below it, seen from above; or a z = 0 body seen from underneath)
        is seen through it. Done per pixel against the body's depth buffer, at half strength.
        Switch off in Settings to get the old look (grid always behind the bodies).
        """
        if not self.grid_over_bodies or not self.show_grid or not len(self.triangles):return
        # The GPU draws this itself (depth-tested, no CPU work). This slower per-pixel version is
        # only the fallback, and it waits until the camera has stopped.
        if self.gpu_enabled and not getattr(self,'gl_grid_failed',False):return
        if self.camera_busy:return
        frame=self.grid_plane_frame()
        if frame is None:return
        o,u,v,n=self.frame_axes(frame)
        width,height=self.width(),self.height()
        # Depth of the grid plane as a function of the screen position (orthographic: a plane).
        corners,depths=self.project(np.array([o,o+u*10.,o+v*10.]))
        matrix=np.column_stack((corners[:,0],corners[:,1],np.ones(3)))
        if abs(np.linalg.det(matrix))<1e-9:return           # plane seen edge-on
        a,b,c=np.linalg.solve(matrix,depths)
        tolerance=.75/max(self.scale(),1e-9)                 # under one pixel: coplanar counts as behind
        vertices,vertex_depth=self.project(self.vertices)
        plane_depth=a*vertices[:,0]+b*vertices[:,1]+c
        if bool(np.all(vertex_depth-plane_depth>=-tolerance)):return     # everything is in front of the grid
        if self.rasterizer is None:self.rasterizer=Rasterizer()
        self.rasterize()
        if self.depth is None or self.depth.shape!=(height,width):return
        ys,xs=np.mgrid[0:height,0:width]
        covered=(self.face_buffer>=0)&(self.depth<=a*xs+b*ys+c+tolerance)
        if not covered.any():return
        layer=QImage(width,height,QImage.Format_ARGB32_Premultiplied);layer.fill(Qt.transparent)
        painter=QPainter(layer);painter.setRenderHint(QPainter.Antialiasing)
        try:
            if self.mode=='sketch':self.paint_grid(painter,over=True)
            else:self.paint_model_grid(painter,over=True)
        finally:painter.end()
        buffer=np.frombuffer(layer.bits(),np.uint8).reshape(height,layer.bytesPerLine()//4,4)
        view=buffer[:,:width,:]
        view[~covered]=0
        p.save();p.setOpacity(.5);p.drawImage(0,0,layer);p.restore()

    def paint_text_box(self,p):
        """The text box rectangle and a live outline of how its text will look."""
        box=self.text_box
        if not box or self.active_frame is None:return
        x0,y0,x1,y1=box['rect'];frame=self.active_frame
        warn=bool(box.get('overflow'))
        if box['loops']:
            path=QPainterPath();path.setFillRule(Qt.OddEvenFill)
            for loop in box['loops']:
                path.addPolygon(QPolygonF([QPointF(*pt) for pt in self.project_local(loop,frame)]));path.closeSubpath()
            tint=QColor('#087ba5');tint.setAlpha(70);p.fillPath(path,tint)
            for loop in box['loops']:self.draw_polyline(p,self.project_local(loop,frame),'#087ba5',1.5,True)
        ring=[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]
        self.draw_polyline(p,self.project_local(ring,frame),'#c45c62' if warn else '#bd8625',2,dashed=True)
        p.setPen(Qt.NoPen);p.setBrush(QColor('#c45c62' if warn else '#bd8625'))
        for corner in ring[:4]:
            x,y=self.project_local([corner],frame)[0];p.drawRect(QRectF(x-3,y-3,6,6))

    def paint_preview(self,p):
        if self.cursor is None or self.tool in self.SELECTION_TOOLS+('fillet','chamfer','extend'):return
        if self.tool=='trim':
            from trim import trim_entities
            screen=self.project_local([self.cursor],self.active_frame)[0];index=self.entity_at(QPointF(*screen))
            if index is not None:
                edge=trim_entities(self.active['entities'],index,self.cursor,preview=True)
                self.draw_polyline(p,self.project_local(sample(edge),self.active_frame),'#c45c62',3)
            return
        points=self.points+[self.cursor.tolist()]
        try:
            if self.tool in ('rectangle','text') and self.points:
                a,b=map(np.array,[self.points[0],self.cursor]);preview=sample(entity('rectangle',center=((a+b)/2).tolist(),width=abs(a[0]-b[0]) or .001,height=abs(a[1]-b[1]) or .001))
            elif self.tool=='center_rectangle' and self.points:
                c,q=map(np.array,[self.points[0],self.cursor]);preview=sample(entity('rectangle',center=c.tolist(),width=max(.001,2*abs(q[0]-c[0])),height=max(.001,2*abs(q[1]-c[1]))))
            elif self.tool=='rectangle_3p' and len(self.points)==2:
                a,b=map(np.array,self.points);axis=b-a;length=np.linalg.norm(axis);n=np.array([-axis[1],axis[0]])/max(length,1e-9);h=float((self.cursor-a)@n);preview=np.array([a,b,b+n*h,a+n*h,a])
            elif self.tool in ('circle','polygon') and self.points:
                if self.tool=='circle':preview=sample(entity('circle',center=self.points[0],radius=math.dist(self.points[0],self.cursor) or .001))
                else:preview=sample(entity('polygon',points=regular_polygon(self.points[0],self.cursor,self.polygon_sides,self.polygon_mode)))
            elif self.tool=='circle_3p' and len(self.points)==2:
                center,r=self._circle_from_three(self.points[0],self.points[1],self.cursor);preview=sample(entity('circle',center=center.tolist(),radius=r))
            elif self.tool=='arc' and len(self.points)==2:preview=sample(entity('arc',a=self.points[0],mid=self.cursor.tolist(),b=self.points[1]))
            elif self.tool=='center_arc' and len(self.points)>=1:
                c=np.array(self.points[0])
                if len(self.points)==1:preview=np.array(self.points+[self.cursor.tolist()])
                else:
                    geometry=self.center_arc_geometry(c,self.points[1],self.cursor)
                    if geometry is None:preview=np.array([c,np.array(self.points[1])])
                    else:preview=np.vstack(([c],sample(entity('arc',a=geometry[0].tolist(),mid=geometry[1].tolist(),b=geometry[2].tolist()),48)))
            elif self.tool=='ellipse' and len(self.points)>=1:
                c=np.array(self.points[0])
                if len(self.points)==1:
                    rx=float(np.linalg.norm(self.cursor-c))
                    # The first click is the centre and the second the END of the major axis, so
                    # the ellipse reaches that far on BOTH sides: show it instead of a bare line.
                    preview=np.array([c-(self.cursor-c),self.cursor]) if rx<1e-6 else sample(entity('ellipse',center=c.tolist(),major=self.cursor.tolist(),minor_radius=max(.001,rx/2)))
                else:
                    major=np.array(self.points[1]);axis=major-c;rx=np.linalg.norm(axis);n=np.array([-axis[1],axis[0]])/max(rx,1e-9);ry=max(.001,abs(float((self.cursor-c)@n)));preview=sample(entity('ellipse',center=c.tolist(),major=major.tolist(),minor_radius=ry))
            elif self.tool=='slot' and len(self.points)>=1:
                if len(self.points)==1:preview=np.array([self.points[0],self.cursor])
                else:
                    a,b=map(np.array,self.points[:2]);axis=b-a;length=np.linalg.norm(axis);n=np.array([-axis[1],axis[0]])/max(length,1e-9);width=max(.001,2*abs(float((self.cursor-a)@n)));preview=sample(entity('slot',a=a.tolist(),b=b.tolist(),width=width))
            elif self.tool=='spline' and self.points:preview=sample(entity('spline',basis='bspline',points=self.points+[self.cursor.tolist()]),64)
            elif self.tool=='conic' and len(self.points)==2:preview=sample(entity('conic',a=self.points[0],b=self.points[1],control=self.cursor.tolist()),64)
            else:preview=points
            self.draw_polyline(p,self.project_local(preview,self.active_frame),'#bd8625',2,dashed=self.construction_mode)
        except Exception:
            if len(points)>=2:self.draw_polyline(p,self.project_local(points,self.active_frame),'#c45c62',1)
        x,y=self.project_local([self.cursor],self.active_frame)[0];p.setPen(QPen(QColor('#d79b24'),2));p.setBrush(Qt.NoBrush);p.drawEllipse(QPointF(x,y),5,5)
        dims=self.live_dimensions(self.points,self.cursor)
        for i,(label,value,unit) in enumerate(dims):
            active=i==self.dimension_index
            text=f'{tr(label)}: '+(self.dimension_text if active and self.dimension_typing else f'{self.dimension_locks.get(i,value):.3f}')+' '+unit
            if i in self.dimension_locks:text+=' · '+tr('locked')
            if active:text='▶ '+text+'  · '+tr('current')
            width=p.fontMetrics().horizontalAdvance(text)+18;bx=max(4,min(x+14,self.width()-width-4));by=max(4,min(y+16+i*32,self.height()-len(dims)*32-4+i*32))
            rect=QRectF(bx,by,width,27)
            if active:
                glow=QColor('#278fb2')
                for spread,alpha in ((8,28),(5,40),(2,65)):
                    tint=QColor(glow);tint.setAlpha(alpha)
                    p.setPen(Qt.NoPen);p.setBrush(tint)
                    p.drawRoundedRect(rect.adjusted(-spread,-spread,spread,spread),7,7)
                active_fill=QColor('#278fb2');active_fill.setAlpha(32)
                p.setBrush(active_fill);p.setPen(Qt.NoPen);p.drawRoundedRect(rect.adjusted(-1,-1,1,1),5,5)
            p.setBrush(QColor(COLORS[self.theme]['canvas']))
            p.setPen(QPen(QColor('#278fb2' if active else '#8d68ac'),2.6 if active else 1.5))
            p.drawRoundedRect(rect,4,4)
            p.setPen(QColor(COLORS[self.theme]['text']));p.drawText(QPointF(bx+8,by+18),text)

    def pick_spatial_point(self,pos):
        f=self.spatial_edit
        if f['kind']=='sketch3d':
            frame=base_frame(f.get('drawing_plane','XY'));o,u,v,n=axes(frame);o=o+n*f.get('plane_offset',0.);frame=dict(frame,origin=o.tolist())
            local=self.local_at(pos,frame)
            if local is None:self.message.emit(tr('Rotate the view so the drawing plane is visible.'));return
            if f.get('snap',True):
                step=self.adaptive_grid_step(22);local=np.round(local/step)*step
            point=o+u*local[0]+v*local[1]
            # Exact snapping to existing model vertices takes precedence.
            candidates=[p for p,indices in self.solid_vertices]
            candidates.extend(np.asarray(p) for e in f.get('entities',[]) for p in e.get('points',[]))
            for sketch,frame in self.spatial_scenes:
                candidates.extend(np.asarray(vertex.Center().toTuple()) for shape in frame['edges'].values() for vertex in shape.Vertices())
            if candidates:
                screens,_=self.project(candidates);dist=np.linalg.norm(screens-[pos.x(),pos.y()],axis=1);index=int(np.argmin(dist))
                if dist[index]<11:point=np.asarray(candidates[index])
            self.spatial_point_picked.emit(point.tolist());return
        face=getattr(self,'spatial_face',None)
        if face is None:self.message.emit(tr('Select a supporting face first.'));return
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        from OCP.gp import gp_Lin,gp_Pnt,gp_Dir
        xy=(np.asarray([pos.x(),pos.y()])-np.asarray([self.width()/2,self.height()/2])-self.pan)/[self.scale(),-self.scale()]
        rotation=self.rotation();origin=self.center+rotation.T@np.array([xy[0],xy[1],self.span*100]);direction=-rotation.T[:,2]
        builder=IntCurvesFace_ShapeIntersector();builder.Load(face.wrapped,1e-6);builder.Perform(gp_Lin(gp_Pnt(*map(float,origin)),gp_Dir(*map(float,direction))),0.,self.span*200)
        if builder.NbPnt()<1:self.message.emit(tr('Click within the supporting face.'));return
        index=min(range(1,builder.NbPnt()+1),key=builder.WParameter);self.spatial_point_picked.emit([builder.UParameter(index),builder.VParameter(index)])
