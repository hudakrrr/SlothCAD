"""Original CAD glyph geometry on a 32-unit canvas.

Visual language (shared by every icon, so a tool reads at a glance):
- Bodies are shaded isometric solids in the viewport's body blue.
- Finished sketch profiles are purple, like sketches in the viewport.
- Sketch geometry being drawn is teal with amber end/control points.
- New material or the result of a tool is teal; the face, edge or point a tool
  changes is amber; removed material is red and dashed.
- Planes and axes are amber construction geometry; surfaces are thin blue sheets
  with iso-curves (no thickness), so they never look like solids.
Geometry stays inside a two-unit safe area and uses no font glyphs. Artwork is
drawn from scratch for SlothCAD; it follows common CAD conventions but copies no
other program's icons.
"""
import math

C=math.cos(math.radians(30))


def _n(v):return f'{v:.2f}'.rstrip('0').rstrip('.') if isinstance(v,float) else str(v)


def attrs(color='ink', fill='none', width=None, dash=None, opacity=None):
    result=f' stroke="__{color}__" fill="{fill if fill == "none" else "__"+fill+"__"}"' if color!='none' else f' stroke="none" fill="{fill if fill == "none" else "__"+fill+"__"}"'
    if width is not None:result+=f' stroke-width="{width}"'
    if dash is not None:result+=f' stroke-dasharray="{dash}"'
    if opacity is not None:result+=f' fill-opacity="{opacity}"'
    return result


def path(d, **kw):return '<path d="'+d+'"'+attrs(**kw)+'/>'
def line(x1,y1,x2,y2,**kw):return path(f'M{_n(x1)} {_n(y1)}L{_n(x2)} {_n(y2)}',**kw)
def poly(points,closed=True,**kw):return path('M'+'L'.join(f'{_n(float(x))} {_n(float(y))}' for x,y in points)+('Z' if closed else ''),**kw)
def circle(x,y,r,**kw):return f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}"'+attrs(**kw)+'/>'
def ellipse(x,y,rx,ry,**kw):return f'<ellipse cx="{_n(x)}" cy="{_n(y)}" rx="{_n(rx)}" ry="{_n(ry)}"'+attrs(**kw)+'/>'
def rect(x,y,w,h,rx=0,**kw):return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="{_n(rx)}"'+attrs(**kw)+'/>'
def group(content,transform):return f'<g transform="{transform}">'+content+'</g>'
def node(x,y,r=1.7):return circle(x,y,r,color='warm',fill='panel',width=1.5)
def dot(x,y,r=1.5,color='warm'):return circle(x,y,r,color=color,fill=color,width=1)
def center(x,y,s=3):return line(x-s,y,x+s,y,color='warm',width=1.3)+line(x,y-s,x,y+s,color='warm',width=1.3)


def arrow(x1,y1,x2,y2,color='accent',both=False,width=1.9,head=3.4):
    angle=math.atan2(y2-y1,x2-x1)
    def tip(x,y,a):
        dx=math.cos(a)*head;dy=math.sin(a)*head
        return path(f'M{_n(x-dx-dy*.6)} {_n(y-dy+dx*.6)}L{_n(x)} {_n(y)}L{_n(x-dx+dy*.6)} {_n(y-dy-dx*.6)}',color=color,width=width)
    return line(x1,y1,x2,y2,color=color,width=width)+tip(x2,y2,angle)+(tip(x1,y1,angle+math.pi) if both else '')


def arc_arrow(cx,cy,r,a0,a1,color='accent',width=1.8,head=3.):
    """Circular arrow from angle a0 to a1 (degrees, screen orientation)."""
    p=lambda a:(cx+r*math.cos(math.radians(a)),cy+r*math.sin(math.radians(a)))
    (x0,y0),(x1,y1)=p(a0),p(a1);large=1 if abs(a1-a0)>180 else 0;sweep=1 if a1>a0 else 0
    tangent=math.radians(a1+(90 if a1>a0 else -90));dx=math.cos(tangent)*head;dy=math.sin(tangent)*head
    tip=path(f'M{_n(x1-dx-dy*.6)} {_n(y1-dy+dx*.6)}L{_n(x1)} {_n(y1)}L{_n(x1-dx+dy*.6)} {_n(y1-dy-dx*.6)}',color=color,width=width)
    return path(f'M{_n(x0)} {_n(y0)}A{_n(r)} {_n(r)} 0 {large} {sweep} {_n(x1)} {_n(y1)}',color=color,width=width)+tip


# --- Isometric solids -------------------------------------------------------

def iso(x,y,z,s=1.):return ((x-y)*C*s,(x+y)*.5*s-z*s)


def _place(points,cx,cy):
    xs=[p[0] for p in points];ys=[p[1] for p in points]
    dx=cx-(min(xs)+max(xs))/2;dy=cy-(min(ys)+max(ys))/2
    return dx,dy


def block(cx,cy,w,d,h,s=1.,color='body',top=None,left=None,right=None,width=1.4,ghost=False):
    """Shaded isometric box centred on (cx, cy). Face overrides take a colour token."""
    corners=[iso(x,y,z,s) for x in (0,w) for y in (0,d) for z in (0,h)]
    dx,dy=_place(corners,cx,cy)
    q=lambda x,y,z:(iso(x,y,z,s)[0]+dx,iso(x,y,z,s)[1]+dy)
    T=[q(0,0,h),q(w,0,h),q(w,d,h),q(0,d,h)];R=[q(w,0,h),q(w,d,h),q(w,d,0),q(w,0,0)];L=[q(0,d,h),q(w,d,h),q(w,d,0),q(0,d,0)]
    if ghost:
        return ''.join(poly(face,color='muted',width=1.1,dash='2 2') for face in (T,R,L))
    out=poly(T,color='ink',fill=top or color,opacity=.45 if top else .18,width=width)
    out+=poly(L,color='ink',fill=left or color,opacity=.45 if left else .34,width=width)
    out+=poly(R,color='ink',fill=right or color,opacity=.5 if right else .52,width=width)
    return out


def block_points(cx,cy,w,d,h,s=1.):
    """Screen-space projector for points on a block placed like block()."""
    corners=[iso(x,y,z,s) for x in (0,w) for y in (0,d) for z in (0,h)]
    dx,dy=_place(corners,cx,cy)
    return lambda x,y,z:(iso(x,y,z,s)[0]+dx,iso(x,y,z,s)[1]+dy)


def part(q,x0,y0,z0,w,d,h,color='body',width=1.3,top=None,right=None,left=None):
    """Box from (x0,y0,z0) with size (w,d,h) in a shared block frame ``q``."""
    x1,y1,z1=x0+w,y0+d,z0+h
    T=[q(x0,y0,z1),q(x1,y0,z1),q(x1,y1,z1),q(x0,y1,z1)];R=[q(x1,y0,z1),q(x1,y1,z1),q(x1,y1,z0),q(x1,y0,z0)];L=[q(x0,y1,z1),q(x1,y1,z1),q(x1,y1,z0),q(x0,y1,z0)]
    return (poly(T,color='ink',fill=top or color,opacity=.45 if top else .18,width=width)+poly(L,color='ink',fill=left or color,opacity=.45 if left else .34,width=width)
            +poly(R,color='ink',fill=right or color,opacity=.5 if right else .52,width=width))


def iso_ellipse(q,x,y,z,r,**kw):
    """Horizontal circle (normal Z) of radius r at (x, y, z) in a block's frame."""
    cx,cy=q(x,y,z);sx=q(x+r,y-r,z)[0]-cx
    return ellipse(cx,cy,abs(sx),abs(sx)*.577,**kw)


def cylinder(cx,cy,rx,h,color='body',width=1.4):
    ry=rx*.42;top=cy-h/2;bottom=cy+h/2
    side=path(f'M{_n(cx-rx)} {_n(top)}V{_n(bottom)}A{_n(rx)} {_n(ry)} 0 0 0 {_n(cx+rx)} {_n(bottom)}V{_n(top)}',color='ink',fill=color,opacity=.38,width=width)
    return side+ellipse(cx,top,rx,ry,color='ink',fill=color,opacity=.2,width=width)


def plane(points,color='warm',opacity=.14,**kw):return poly(points,color=color,fill=color,opacity=opacity,**kw)


def sheet(d,color='blue',opacity=.16,curves=()):
    """Open surface: one outline, a light fill and iso-curves, never side faces."""
    return path(d,color=color,fill=color,opacity=opacity,width=1.6)+''.join(path(c,color=color,width=.9) for c in curves)


ART={}

# --- Sketch drawing ---------------------------------------------------------
ART['line']=line(5,26,27,6,color='accent',width=2)+node(5,26)+node(27,6)
ART['rectangle']=rect(5,8,22,16,color='accent',width=2)+node(5,24)+node(27,8)
ART['center_rectangle']=rect(5,8,22,16,color='accent',width=2)+line(5,8,27,24,color='muted',dash='2 2',width=1)+line(5,24,27,8,color='muted',dash='2 2',width=1)+node(16,16)+node(27,8)
ART['rectangle_3p']=poly([(4,17),(19,6),(28,17),(13,28)],color='accent',width=2)+node(4,17)+node(19,6)+node(28,17)
ART['circle']=circle(16,16,11,color='accent',width=2)+line(16,16,27,16,color='muted',width=1.1,dash='2 2')+center(16,16)+node(27,16)
ART['circle_3p']=circle(16,16,11,color='accent',width=2)+node(16,5)+node(6.47,21.5)+node(25.53,21.5)
ART['arc']=path('M5 22A12 12 0 0 1 27 22',color='accent',width=2)+node(5,22)+node(16,10.5)+node(27,22)
ART['center_arc']=path('M4.5 19A12 12 0 0 1 24.5 8.5',color='accent',width=2)+line(16,19,4.5,19,color='muted',dash='2 2',width=1.1)+line(16,19,24.5,8.5,color='muted',dash='2 2',width=1.1)+center(16,19)+node(4.5,19)+node(24.5,8.5)
ART['polygon']=poly([(16,4),(26.39,10),(26.39,22),(16,28),(5.61,22),(5.61,10)],color='accent',width=2)+line(16,16,26.39,10,color='muted',dash='2 2',width=1.1)+center(16,16)+node(26.39,10)
ART['ellipse']=ellipse(16,16,12,7.5,color='accent',width=2)+line(16,16,28,16,color='muted',dash='2 2',width=1.1)+line(16,16,16,8.5,color='muted',dash='2 2',width=1.1)+center(16,16)
ART['slot']=path('M10 10H22A6 6 0 0 1 22 22H10A6 6 0 0 1 10 10Z',color='accent',width=2)+line(10,16,22,16,color='muted',dash='2 2',width=1.1)+node(10,16)+node(22,16)
ART['spline']=path('M4 24L9 6L22 27L28 7',color='muted',dash='2 2',width=1)+path('M4 24C9 6 22 27 28 7',color='accent',width=2.1)+''.join(node(x,y) for x,y in [(4,24),(9,6),(22,27),(28,7)])
ART['conic']=path('M5 26L16 5L27 26',color='muted',dash='2 2',width=1)+path('M5 26Q16 5 27 26',color='accent',width=2.1)+node(5,26)+node(16,5)+node(27,26)
ART['point']=line(16,7,16,25,color='muted',width=1,dash='2 2')+line(7,16,25,16,color='muted',width=1,dash='2 2')+circle(16,16,3.2,color='accent',fill='accent',width=1.4)
# A serif-free letter built from strokes: no font dependency.
ART['text']=path('M6 8V5H26V8M16 5V27M12 27H20',color='accent',width=2.2)+line(4,29.5,28,29.5,color='muted',dash='2 2',width=1)

# --- Sketch modify ----------------------------------------------------------
ART['mirror']=line(16,3,16,29,color='warm',dash='3 2',width=1.4)+poly([(4,8),(12,14),(5,24)],color='ink',fill='ink',opacity=.1,width=1.8)+poly([(28,8),(20,14),(27,24)],color='accent',fill='accent',opacity=.16,width=1.8)
ART['circular']=circle(16,16,10,color='muted',dash='2 2',width=1)+center(16,16,2.5)+''.join(circle(16+10*math.cos(a),16+10*math.sin(a),3,color='ink' if i==0 else 'accent',fill='panel',width=1.8) for i,a in enumerate(math.radians(d) for d in (-90,-18,54,126,198)))
ART['rectangular']=''.join(rect(x,y,7,7,rx=1,color='ink' if (x,y)==(4,4) else 'accent',fill='ink' if (x,y)==(4,4) else 'accent',opacity=.12,width=1.8) for x in (4,21) for y in (4,21))+arrow(12.5,7.5,19.5,7.5,color='muted',width=1.2,head=2.4)+arrow(7.5,12.5,7.5,19.5,color='muted',width=1.2,head=2.4)
# Plain open scissors: two finger rings, two crossing blades and the pivot.
ART['trim']=(path('M11.3 19.6L21.6 4.2Q23.4 3.4 23.2 5.6L14.4 21.4',color='ink',fill='ink',opacity=.18,width=1.7)
             +path('M20.7 19.6L10.4 4.2Q8.6 3.4 8.8 5.6L17.6 21.4',color='ink',fill='ink',opacity=.18,width=1.7)
             +circle(9.5,24,4.2,color='accent',width=2.2)+circle(22.5,24,4.2,color='accent',width=2.2)+dot(16,13.6,1.5))
ART['sketch_fillet']=path('M5 28V15M17 5H28',color='accent',width=2)+path('M5 15A10 10 0 0 1 15 5H17',color='warm',width=2.4)+path('M5 15V5H15',color='muted',dash='2 2',width=1)
ART['sketch_chamfer']=path('M5 28V15M15 5H28',color='accent',width=2)+line(5,15,15,5,color='warm',width=2.4)+path('M5 15V5H15',color='muted',dash='2 2',width=1)
ART['construction']=line(5,26,27,6,color='warm',dash='4 3',width=2.2)+node(5,26)+node(27,6)
ART['sketch_move']=poly([(3,20),(14,14),(29,21),(18,27)],color='sketch',fill='sketch',opacity=.12,width=1.5)+path('M8 20L13 17.5L19 20.5',color='sketch',width=1.6)+arrow(16,20,16,4)+arrow(16,20,28,14,color='warm')
ART['project']=(block(16,8.5,12,12,5,.85)+plane([(3,23),(16,17),(29,23),(16,29.5)],color='sketch',opacity=.1,width=1.2)
                +''.join(line(x,y,x,y+12.5,color='muted',dash='2 2',width=1) for x,y in ((6.9,11.5),(16,15.5),(25.1,11.5)))+path('M6.9 24L16 28L25.1 24',color='sketch',width=2.4))

# --- Constraints ------------------------------------------------------------
# Geometry in ink, the relation itself in amber.
ART['coincident']=line(4,26,15,15,width=1.8)+line(15,15,28,9,width=1.8)+circle(15,15,3.6,color='warm',fill='warm',opacity=.35,width=1.8)
ART['horizontal']=line(4,13,28,13,color='accent',width=2.2)+node(4,13)+node(28,13)+rect(9,19,14,7,rx=3.5,color='warm',width=1.6)+circle(16,22.5,1.7,color='warm',fill='warm')
ART['vertical']=line(13,4,13,28,color='accent',width=2.2)+node(13,4)+node(13,28)+rect(19,9,7,14,rx=3.5,color='warm',width=1.6)+circle(22.5,16,1.7,color='warm',fill='warm')
ART['parallel']=line(4,15,22,4,color='accent',width=2)+line(10,28,28,17,color='accent',width=2)+line(12,18,16,12,color='warm',width=1.8)+line(16,20.5,20,14.5,color='warm',width=1.8)
ART['perpendicular']=path('M6 4V27H28',color='accent',width=2.2)+path('M6 19H14V27',color='warm',width=1.8)
ART['dimension']=line(5,10,5,28,color='muted',width=1)+line(27,10,27,28,color='muted',width=1)+arrow(5,14,27,14,color='warm',both=True,head=3,width=1.6)+line(5,25,27,25,color='accent',width=2)+node(5,25)+node(27,25)+line(12,7,20,7,color='warm',width=2.2)
ART['equal']=line(4,8,22,8,color='accent',width=2)+line(10,26,28,26,color='accent',width=2)+path('M10 15H22M10 19H22',color='warm',width=2)
ART['symmetry']=line(16,3,16,29,color='warm',dash='3 2',width=1.4)+node(6,16)+node(26,16)+arrow(9,16,13.5,16,color='warm',width=1.4,head=2.3)+arrow(23,16,18.5,16,color='warm',width=1.4,head=2.3)+path('M4 7L8 4M28 7L24 4',color='accent',width=1.6)
ART['tangent']=circle(14,12,8,color='accent',width=2)+line(3,20,29,20,width=1.8)+dot(14,20,2)
ART['constraint']=line(4,26,14,14,color='accent',width=2)+circle(21,11,7,color='accent',width=2)+circle(14,14,2.4,color='warm',fill='panel',width=1.6)+path('M6 7L9 4L12 7',color='warm',width=1.5)+path('M22 25H28M22 28H28',color='warm',width=1.5)
ART['fix']=rect(8,14,16,14,rx=2.5,color='warm',fill='warm',opacity=.2,width=1.8)+path('M11 14V10A5 5 0 0 1 21 10V14',width=2)+circle(16,20.5,1.8,fill='ink')
ART['unfix']=rect(8,14,16,14,rx=2.5,color='muted',fill='muted',opacity=.12,width=1.8)+path('M11 14V10A5 5 0 0 1 20.5 7.5',width=2)+circle(16,20.5,1.8,fill='ink')
ART['midpoint']=line(4,22,28,22,color='accent',width=2)+node(4,22)+node(28,22)+poly([(16,17),(19,22),(16,27),(13,22)],color='warm',fill='warm',opacity=.5,width=1.5)+arrow(16,5,16,13,color='warm',width=1.5,head=2.5)
ART['concentric']=circle(16,16,12,color='accent',width=2)+circle(16,16,6.5,color='accent',width=2)+center(16,16,2.4)
ART['collinear']=line(3,28,29,4,color='muted',dash='2 2',width=1)+line(4,27,13,18.7,color='accent',width=2.4)+line(18,14.1,28,4.9,color='accent',width=2.4)+node(13,18.7)+node(18,14.1)
ART['point_on_object']=path('M3 24C10 6 22 6 29 24',color='accent',width=2)+circle(16,10.6,2.8,color='warm',fill='warm',opacity=.4,width=1.6)+arrow(23,27,17.5,13.5,color='warm',width=1.4,head=2.5)

# --- Objects ----------------------------------------------------------------
ART['body']=block(16,16,12,12,12,.95)
ART['sketch']=plane([(3,17),(16,10),(29,17),(16,24)],color='sketch',opacity=.1,width=1.3)+path('M9 17L16 13.5L23 17L16 20.5Z',color='sketch',width=1.9)+path('M19 10L26 3L29 6L22 13L18 14Z',color='warm',fill='warm',opacity=.3,width=1.4)

# --- Solid creation ---------------------------------------------------------
q=block_points(16,19,14,14,10,.9)
ART['extrude']=(block(16,19,14,14,10,.9,color='accent')+poly([q(0,14,0),q(14,14,0),q(14,0,0)],closed=False,color='sketch',width=2.6)
                +arrow(16,q(7,7,10)[1]+2,16,2.5,color='warm',width=2.2,head=3.6))
# Half profile beside a dashed axis, the swept result ghosted, and the turn.
ART['revolve']=(ellipse(9,8,7,2.4,color='muted',dash='2 2',width=1)+line(2,8,2,22,color='muted',dash='2 2',width=1)
                +path('M9 6H23V12H17V22H9Z',color='sketch',fill='sketch',opacity=.3,width=2)
                +line(9,2.5,9,29.5,color='warm',dash='3 2',width=1.5)+path('M22 25.6A12 3.4 0 0 1 3 26.8',color='accent',width=2)+path('M3.2 29.6L3 26.8L5.8 25.6',color='accent',width=2))
ART['sweep']=(path('M7 25C17 25 15 9 26 9',color='muted',dash='2 2',width=1.1)+path('M4.5 21.5C17 21.5 13 5.5 25.5 5.5L26.5 12.5C17.5 12.5 21 28.5 4.5 28.5Z',color='accent',fill='accent',opacity=.18,width=1.6)
              +ellipse(4.5,25,2.6,3.5,color='sketch',fill='sketch',opacity=.35,width=1.8)+ellipse(26,9,2.6,3.5,color='accent',width=1.6))
ART['loft']=(path('M6 8L4 24M26 8L28 24',color='accent',width=1.5)+path('M6 8L4 24L16 29.5L28 24L26 8Z',color='none',fill='accent',opacity=.14)
             +ellipse(16,8,10,3.4,color='sketch',fill='sketch',opacity=.25,width=1.9)+poly([(4,24),(16,18.5),(28,24),(16,29.5)],color='sketch',fill='sketch',opacity=.25,width=1.9))
q=block_points(16,17,16,16,9,.95)
ART['hole']=(block(16,17,16,16,9,.95)+iso_ellipse(q,8,8,9,3.6,color='red',fill='panel',width=1.7)
             +line(q(8,8,9)[0],2.5,q(8,8,9)[0],q(8,8,9)[1]-3,color='red',width=1.5,dash='2 1.6')+path(f'M{_n(q(8,8,9)[0]-3.4)} {_n(q(8,8,9)[1])}V{_n(q(8,8,9)[1]+7)}M{_n(q(8,8,9)[0]+3.4)} {_n(q(8,8,9)[1])}V{_n(q(8,8,9)[1]+7)}',color='red',dash='2 1.6',width=1.1))
ART['primitive']=block(10,21,9,9,8,.9)+cylinder(22,19,5,11)+circle(15,7.5,5,color='ink',fill='body',opacity=.3,width=1.4)
_tube='M7.5 26C7.5 15 13 9.5 24 9.5'
ART['pipe']=(path(_tube,color='accent',width=8)+path(_tube,color='panel',width=4.6)
             +path(_tube,color='accent',width=1.1,dash='2 2')+ellipse(24.5,9.5,1.6,4,color='accent',fill='panel',width=1.6)+ellipse(7.5,26.5,4,1.6,color='sketch',width=1.7))
ART['coil']=path('M8 6C8 2 24 2 24 6S8 12 8 12S24 12 24 17S8 22 8 22S24 22 24 27',color='accent',width=2.4)+line(16,2.5,16,29.5,color='warm',dash='2 2',width=1)
# Side view of an L bracket with a triangular rib (gusset) between its legs.
ART['rib']=(path('M4 4H9V23H28V28H4Z',color='ink',fill='body',opacity=.4,width=1.7)
            +poly([(9,8),(9,23),(24,23)],color='accent',fill='accent',opacity=.45,width=1.9))
# Top view of a plate stiffened by a network of thin ribs.
ART['web']=(rect(4,4,24,24,rx=1.5,color='ink',fill='body',opacity=.22,width=1.7)
            +path('M4 12H28M4 20H28M12 4V28M20 4V28',color='accent',width=2.4))
ART['thread']=(path('M11 11H21V29H11Z',color='ink',fill='body',opacity=.3,width=1.5)+''.join(path(f'M11 {y}L21 {y+2.6}',color='warm',width=1.7) for y in (12.5,16.5,20.5,24.5))
               +path('M7 4H25V11H7Z',color='ink',fill='body',opacity=.45,width=1.6)+line(13,4,13,11,width=1)+line(19,4,19,11,width=1))

# --- Edge and face modify ---------------------------------------------------
# A block whose front-top edge is rounded (fillet) or bevelled (chamfer).
for kind in ('fillet','chamfer'):
    top=poly([(8,8),(11,5),(29,5),(26,8)],color='ink',fill='body',opacity=.18,width=1.4)
    side=path('M26 8L29 5V22L22 29V18'+('Q22 12 26 8Z' if kind=='fillet' else 'L26 8Z'),color='ink',fill='body',opacity=.52,width=1.4)
    front=poly([(4,18),(22,18),(22,29),(4,29)],color='ink',fill='body',opacity=.34,width=1.4)
    strip='M8 8H26'+('Q22 12 22 18' if kind=='fillet' else 'L22 18')+'H4'+('Q4 12 8 8Z' if kind=='fillet' else 'L8 8Z')
    ART[kind]=top+side+front+path(strip,color='warm',fill='warm',opacity=.42,width=1.6)
    if kind=='fillet':ART[kind]+=line(5.2,12.6,23.2,12.6,color='warm',width=.9)
q=block_points(16,17,16,16,10,.95)
ART['shell']=(block(16,17,16,16,10,.95,top='panel')+poly([q(2.5,2.5,10),q(13.5,2.5,10),q(13.5,13.5,10),q(2.5,13.5,10)],color='warm',fill='warm',opacity=.22,width=1.5)
              +poly([q(2.5,2.5,10),q(2.5,13.5,10),q(2.5,13.5,3),q(2.5,2.5,3)],color='none',fill='body',opacity=.35)+poly([q(2.5,2.5,10),q(13.5,2.5,10),q(13.5,2.5,3),q(2.5,2.5,3)],color='none',fill='body',opacity=.5)+poly([q(2.5,2.5,3),q(13.5,2.5,3),q(13.5,13.5,3),q(2.5,13.5,3)],color='ink',fill='body',opacity=.15,width=1))
q=block_points(15,17,14,12,14,.8)
ART['draft']=(poly([q(0,0,14),q(14,0,14),q(14,12,14),q(0,12,14)],color='ink',fill='body',opacity=.18,width=1.4)+poly([q(0,12,14),q(14,12,14),q(14,12,0),q(0,12,0)],color='ink',fill='body',opacity=.34,width=1.4)
              +poly([q(14,0,14),q(14,12,14),q(18,12,0),q(18,0,0)],color='ink',fill='warm',opacity=.45,width=1.6)+line(*q(14,12,14),*q(14,12,0),color='muted',dash='2 2',width=1)+path('M'+' '.join(_n(v) for v in q(14,12,5))+'L'+' '.join(_n(v) for v in q(15.4,12,5)),color='warm',width=1.4)+arc_arrow(q(14,12,14)[0],q(14,12,14)[1],9,90,72,color='warm',width=1.3,head=2))
ART['press_pull']=block(16,20,15,15,6,.9)+arrow(16,16.5,16,3.5,both=True,color='warm',width=2)+poly([block_points(16,20,15,15,6,.9)(x,y,6) for x,y in ((0,0),(15,0),(15,15),(0,15))],color='warm',fill='warm',opacity=.4,width=1.6)
q=block_points(16,21,15,15,6,.9)
ART['offset_face']=(block(16,21,15,15,6,.9)+poly([(x,y-7) for x,y in (q(0,0,6),q(15,0,6),q(15,15,6),q(0,15,6))],color='warm',fill='warm',opacity=.3,width=1.7)
                    +''.join(line(x,y,x,y-7,color='warm',dash='2 2',width=1) for x,y in (q(15,0,6),q(15,15,6),q(0,15,6)))+arrow(16,q(7.5,7.5,6)[1],16,q(7.5,7.5,6)[1]-6.5,color='accent',width=1.8,head=2.6))
ART['scale']=block(11,21,9,9,7,.9)+block(17,15,16,16,13,.95,ghost=True)+arrow(14,19,25,7,color='accent',width=1.9)
q=block_points(16,17,16,16,10,.95)
ART['split_face']=(block(16,17,16,16,10,.95)+poly([q(0,16,10),q(8,16,10),q(8,16,0),q(0,16,0)],color='warm',fill='warm',opacity=.4,width=1.4)+line(*q(8,16,10),*q(8,16,0),color='warm',width=2.4))
q=block_points(15,21,14,14,6,.9)
ART['replace_face']=(block(15,21,14,14,6,.9)+poly([q(0,0,6),q(14,0,6),q(14,14,6),q(0,14,6)],color='red',dash='2 1.8',width=1.4)
                     +plane([(3,10),(17,3),(30,9),(16,16.5)],width=1.7)+arrow(15,q(7,7,6)[1],15.5,10.5,color='accent',width=1.7,head=2.5))

# --- Body tools -------------------------------------------------------------
ART['body_move']=block(13,19,11,11,8,.85)+arrow(13,15,13,2.5,color='blue')+arrow(16,20,29,26.5,color='red')+arrow(10,20,2,24.5,color='green',width=1.7)+arc_arrow(13,13,8,200,250,color='warm',width=1.4,head=2.2)
ART['body_mirror']=block(7.5,17,7,7,9,.85)+block(24.5,17,7,7,9,.85,color='accent')+line(16,3,16,29,color='warm',dash='3 2',width=1.4)
ART['body_rectangular']=''.join(block(x,y,6,6,5,.8,color='body' if i==0 else 'accent',width=1.2) for i,(x,y) in enumerate([(9,9),(23,9),(9,23),(23,23)]))+line(14,9,18,9,color='muted',dash='1.5 1.5',width=1)+line(9,14,9,18,color='muted',dash='1.5 1.5',width=1)
ART['body_circular']=circle(16,16,10.5,color='muted',dash='2 2',width=1)+center(16,16,2)+''.join(block(16+10.5*math.cos(math.radians(a)),16+10.5*math.sin(math.radians(a)),4.5,4.5,4,.75,color='body' if i==0 else 'accent',width=1.1) for i,a in enumerate((-90,0,90,180)))
q=block_points(16,17,22,13,11,.85)
ART['body_split']=(part(q,0,0,0,8,13,11)+poly([q(11,-3,-2),q(11,16,-2),q(11,16,14),q(11,-3,14)],color='warm',fill='warm',opacity=.14,width=1.3,dash='3 2')
                   +part(q,14,0,0,8,13,11,color='accent'))
ART['body_combine']=block(12,18,12,12,9,.9)+block(20,13,12,12,9,.9,color='accent')+circle(26,25,4.2,color='warm',fill='panel',width=1.6)+path('M23.6 25H28.4M26 22.6V27.4',color='warm',width=1.6)

# --- Feature patterns (repeat features on a body, not whole bodies) ----------
def _plate(cx,cy):return block_points(cx,cy,20,16,4,.9),block(cx,cy,20,16,4,.9)
q,p=_plate(16,18)
ART['feature_rectangular']=p+''.join(iso_ellipse(q,x,y,4,1.9,color='ink' if (x,y)==(4,4) else 'accent',fill='panel',width=1.6) for x in (4,10,16) for y in (4,12))
q,p=_plate(16,18)
ART['feature_circular']=p+iso_ellipse(q,10,8,4,6,color='muted',dash='1.5 1.5',width=1)+''.join(iso_ellipse(q,10+6*math.cos(math.radians(a)),8+6*math.sin(math.radians(a)),4,1.5,color='ink' if i==0 else 'accent',fill='panel',width=1.5) for i,a in enumerate(range(0,360,60)))
q,p=_plate(16,19)
ART['feature_mirror']=p+line(*q(10,-2,4),*q(10,18,4),color='warm',dash='2.4 2',width=1.4)+block(*q(4.5,8,6.5),3.5,5,5,.9,width=1.1)+block(*q(15.5,8,6.5),3.5,5,5,.9,color='accent',width=1.1)
ART['path_pattern']=path('M3 26C10 6 20 30 29 7',color='muted',dash='2 2',width=1.1)+''.join(block(x,y,4.5,4.5,4,.75,color='body' if i==0 else 'accent',width=1.1) for i,(x,y) in enumerate([(5,20),(12,13.5),(20,19),(27,10)]))

# --- Construction -----------------------------------------------------------
_pl=lambda dy=0:[(3,16+dy),(16,9+dy),(29,16+dy),(16,23+dy)]
ART['construction_plane']=plane(_pl(),width=1.6)+line(16,16,16,4,color='accent',width=1.6)+path('M13.6 6.6L16 4L18.4 6.6',color='accent',width=1.6)
ART['offset_plane']=plane(_pl(6),color='muted',opacity=.08,width=1.2)+plane(_pl(-6),width=1.6)+arrow(22,19,22,11,color='accent',width=1.7,head=2.6)
ART['angled_plane']=plane([(3,22),(16,15),(29,22),(16,29)],color='muted',opacity=.08,width=1.1)+plane([(3,22),(16,29),(23,12),(10,5)],width=1.7)+line(3,22,16,29,color='accent',width=2.2)+path('M21 22.5Q23 19 21.5 16',color='accent',width=1.5)
ART['midplane']=plane(_pl(8),color='muted',opacity=.08,width=1.1)+plane(_pl(-8),color='muted',opacity=.08,width=1.1)+plane(_pl(),width=1.8)+line(16,3,16,29,color='accent',dash='2 2',width=1)
ART['three_point_plane']=plane(_pl(),width=1.6)+node(6,16)+node(17,10.5)+node(22,20)
ART['construction_axis']=cylinder(16,17,7,14,color='body')+line(16,2.5,16,29.5,color='warm',dash='4 2',width=2)

# --- Surfaces: thin blue sheets with iso-curves -------------------------------
ART['surface_patch']=sheet('M4 22Q10 3 27 8Q22 30 4 22Z',curves=('M9 12Q17 10 25 14','M6 18Q15 16 22 22'))
ART['surface_extrude']=sheet('M4 25C9 19 13 26 19 21L19 9C13 14 9 7 4 13Z',curves=('M8 11V24','M12 13V24','M16 12V22'))+path('M4 25C9 19 13 26 19 21',color='sketch',width=2)+arrow(24,22,24,7,color='accent',width=1.7,head=2.6)
ART['surface_revolve']=sheet('M7 7C13 9 13 23 7 25L25 25C19 23 19 9 25 7Z',curves=('M10 12H22','M11 16H21','M10 20H22'))+line(16,3,16,29,color='warm',dash='3 2',width=1.2)+path('M7 7C13 9 13 23 7 25',color='sketch',width=2)
ART['surface_sweep']=sheet('M4 18C14 18 13 6 26 6L28 12C16 12 17 25 6 25Z',curves=('M10 18L12 24.5','M16 12L20 18','M21 8L24 12'))+line(4,18,6,25,color='sketch',width=2)
ART['surface_loft']=sheet('M5 7Q16 3 27 7L28 25Q16 29 4 25Z',curves=('M10 6L9 26','M16 5V27','M22 6L23 26'))+path('M5 7Q16 3 27 7',color='sketch',width=2)+path('M4 25Q16 29 28 25',color='sketch',width=2)
ART['surface_trim']=sheet('M4 20Q10 6 18 9L18 26Q10 27 4 20Z',curves=('M8 13Q12 18 9 24','M13 9Q16 17 13 26'))+path('M18 9Q24 11 28 20Q24 27 18 26',color='red',dash='2 2',width=1.4)+line(18,3,18,29,color='warm',width=1.8)
ART['surface_extend']=sheet('M4 20Q9 7 18 9L18 26Q10 27 4 20Z',curves=('M8 13Q12 18 9 24',))+path('M18 9Q24 10 27 15L27 27Q23 26 18 26',color='blue',dash='2 2',width=1.4)+arrow(19,17.5,27,17.5,color='accent',width=1.7,head=2.6)
ART['surface_stitch']=sheet('M3 8L15 6L15 26L3 24Z',curves=('M9 7V25',))+sheet('M17 6L29 8L29 24L17 26Z',curves=('M23 7V25',))+''.join(line(13,y,19,y-1,color='warm',width=1.6) for y in (10,15,20,25))
ART['surface_thicken']=sheet('M4 12Q16 4 28 12',color='blue')+path('M4 12Q16 4 28 12L28 20Q16 12 4 20Z',color='ink',fill='accent',opacity=.25,width=1.4)+arrow(16,14,16,23,color='accent',width=1.6,head=2.4)

# --- Assemblies and 3D sketches --------------------------------------------
ART['component']=block(13,19,10,10,8,.85)+block(20,11,8,8,6,.85,color='accent')+path('M3 4V9M3 4H8M29 28V23M29 28H24',color='warm',width=1.8)
ART['joint']=block(9,21,9,9,7,.8)+block(23,11,8,8,6,.8,color='accent')+circle(16,16,4.5,color='warm',fill='panel',width=1.8)+dot(16,16,1.6)+arc_arrow(16,16,8,200,290,color='warm',width=1.4,head=2.2)
ART['sketch3d']=arrow(9,24,28,24,color='red',width=1.3,head=2.4)+arrow(9,24,9,4,color='blue',width=1.3,head=2.4)+arrow(9,24,3,29.5,color='green',width=1.3,head=2.2)+path('M12 20Q16 6 26 9',color='accent',width=2.2)+node(12,20)+node(26,9)
ART['surface_sketch']=sheet('M3 20Q12 2 29 9Q24 30 3 20Z',curves=('M9 12Q17 9 25 13',))+path('M7 19Q14 12 24 17',color='accent',width=2.3)+node(7,19)+node(24,17)

# --- Inspect, history and application ---------------------------------------
ART['select']=poly([(7,4),(7,26),(13,20.5),(17.5,29),(21.5,27),(17,18.5),(25,18)],color='ink',fill='ink',opacity=.14,width=1.8)
# Caliper: beam with fixed and sliding jaws, the measured gap in amber.
ART['measure']=path('M3 9H29V14H3Z',color='ink',fill='ink',opacity=.08,width=1.6)+path('M5 14V27L9 23V14M23 14V27L19 23V14',width=1.6)+''.join(line(x,9,x,11.5,width=1) for x in (8,11,14,17,20,23,26))+arrow(10.5,20,17.5,20,color='warm',both=True,width=1.4,head=2.2)
ART['repair']=path('M6 4L13 11L11 13L4 6C3 12 8 16 13 14L25 28L28 25L14 13C16 8 12 3 6 4Z',color='ink',fill='ink',opacity=.1,width=1.6)+path('M19 5H28V14',color='accent',width=1.6)+arc_arrow(19,14,7,-90,-5,color='accent',width=1.6,head=2.4)
ART['edit']=rect(4,6,19,21,rx=1.5,width=1.6)+path('M13 21L24 8L28 11L17 24L12 25Z',color='warm',fill='warm',opacity=.3,width=1.5)+line(22,10,26,13,color='warm',width=1.1)
ART['warning']=poly([(16,3),(29.5,27),(2.5,27)],color='warm',fill='warm',opacity=.3,width=1.8)+line(16,11,16,18.5,width=2.4)+circle(16,23,1.2,fill='ink')
ART['finish']=path('M5 17L13 25L27 7',color='green',width=2.8)
ART['cancel']=path('M7 7L25 25M25 7L7 25',color='red',width=2.6)
ART['delete']=path('M6 8H26M12 8V4H20V8M8 8L10 28H22L24 8M14 13V23M18 13V23',color='red',width=1.8)
ART['grid']=''.join(line(v,4,v,28,color='muted',width=1)+line(4,v,28,v,color='muted',width=1) for v in (4,10,16,22,28))+path('M4 16H28M16 4V28',color='accent',width=1.8)
ART['aa']=path('M4 27V22H9V17H14V12H19V7H24V3',color='muted',width=1.4)+path('M6 29Q8 12 28 6',color='accent',width=2.4)
ART['axes']=arrow(10,22,29,22,color='red',width=1.7,head=3)+arrow(10,22,10,3,color='blue',width=1.7,head=3)+arrow(10,22,3,29,color='green',width=1.7,head=3)
ART['fit']=path('M3 10V3H10M22 3H29V10M29 22V29H22M10 29H3V22',width=1.9)+block(16,16,9,9,7,.9,color='accent',width=1.3)
# Perspective: a box whose far face is smaller, with the converging edges drawn.
ART['perspective']=poly([(4,10),(22,10),(22,28),(4,28)],width=1.7)+poly([(11,5),(27,5),(27,21),(11,21)],width=1.3,color='muted')+''.join(line(a,b,c,d,color='accent',width=1.5) for a,b,c,d in ((4,10,11,5),(22,10,27,5),(22,28,27,21)))
# Section: a block cut by a plane (amber) with the removed corner shown dashed.
ART['section']=block(15,19,12,12,8,.9)+poly([(3,16),(18,6),(30,12),(15,22)],color='warm',fill='warm',opacity=.25,width=1.5)+line(6,26,26,26,color='red',width=1.2,dash='2 2')
ART['extend']=line(4,22,20,22,color='sketch',width=2.2)+line(20,22,27,22,color='accent',width=2.2,dash='2 2')+line(27,8,27,28,width=1.8)+arrow(14,15,21,15,color='accent',width=1.6,head=2.6)
ART['offset']=path('M6 24V10Q6 6 10 6H26',color='sketch',width=2.2)+path('M11 24V13Q11 11 13 11H26',color='accent',width=1.8)+arrow(3,3,8,8,color='warm',width=1.4,head=2.2)
ART['transform']=rect(5,12,12,12,rx=1,color='sketch',width=1.8)+rect(14,5,12,12,rx=1,color='accent',width=1.6,dash='2 2')+arrow(12,12,19,8,color='warm',width=1.6,head=2.6)
ART['undo']=path('M6 12H19C25 12 28 15 28 20.5C28 26 24 28.5 19 28.5H11',width=2.1)+path('M12 6L6 12L12 18',color='accent',width=2.1)
ART['redo']=group(ART['undo'],'translate(32 0) scale(-1 1)')
ART['new']=path('M7 3H19L25 9V29H7ZM19 3V9H25',width=1.7)+path('M11 20H21M16 15V25',color='accent',width=2)
ART['open']=path('M3 26V7H12L15 11H26V15M3 26L8 15H29L24 26Z',fill='ink',opacity=.08,width=1.7)+arrow(20,24,20,17,color='accent',width=1.5,head=2.2)
ART['save']=path('M5 4H24L28 8V28H5ZM10 4V12H22V4M10 28V18H23V28',fill='ink',opacity=.08,width=1.7)+line(18,6.5,18,9.5,color='accent',width=2)
ART['settings']=circle(16,16,4.5,width=1.8)+circle(16,16,9.5,width=1.8)+''.join(line(16+math.cos(a)*9.5,16+math.sin(a)*9.5,16+math.cos(a)*13,16+math.sin(a)*13,color='ink',width=3) for a in (i*math.pi/4 for i in range(8)))
ART['help']=circle(16,16,12.5,width=1.7)+path('M12 12C12 7 21 7 21 12C21 15.5 16 15 16 19.5',color='accent',width=2.2)+circle(16,24,1.3,color='accent',fill='accent')
ART['unknown']=poly([(16,3),(29,16),(16,29),(3,16)],color='warm',width=1.7)+path('M12.5 12.5C12.5 8 20 8 20 12.5C20 15.5 16 15.5 16 19',color='warm',width=1.8)+circle(16,23,1,color='warm',fill='warm')

# File exchange: a document with a solid or a drawing, and an in/out arrow.
def _doc(content):return path('M10 4H22L28 10V29H10ZM22 4V10H28',width=1.5,fill='panel')+content
_solid_doc=block(19,20,7,7,5,.8,width=1.1)
_drawing_doc=rect(13.5,14,11,9,color='sketch',width=1.3)+circle(19,18.5,2.6,color='sketch',width=1.3)
_in=arrow(2.5,9,10,16.5,color='accent',width=2,head=3)
_out=arrow(13,13,3,3,color='warm',width=2,head=3)
ART['import_solid']=_doc(_solid_doc)+_in
ART['import_step']=_doc(_solid_doc)+_in+line(3,27,8,27,color='accent',width=1.6)
ART['export_step']=_doc(_solid_doc)+_out
ART['import_dxf']=_doc(_drawing_doc)+_in
ART['export_dxf']=_doc(_drawing_doc)+_out
ART['export_stl']=_doc(poly([(13,25),(19,14),(25,25)],color='ink',fill='body',opacity=.3,width=1.2)+line(19,14,19,25,width=.9)+line(13,25,19,20,width=.9)+line(25,25,19,20,width=.9))+_out
ART['apply']=ART['finish']

# Toolbar group buttons get their own family icons.
ART['solid_tools']=block(11,20,9,9,8,.85)+cylinder(22,17,5,13,color='accent')+path('M3 4H9M6 1.5V6.5',color='warm',width=1.6)
# "More modify": a block whose top face is being changed (amber, with a push/pull arrow) and
# an ellipsis for the further tools in the menu. It no longer borrows the fillet artwork.
ART['solid_modify']=(block(13,16.5,12,12,8,.92,top='warm')+arrow(13,10.5,13,2.6,color='accent',width=1.9,head=2.8)
                     +''.join(dot(x,29,1.45,'ink') for x in (19,23.2,27.4)))
ART['body_patterns']=ART['body_rectangular']
ART['body_tools']=ART['body_move']
ART['construct']=ART['construction_plane']
ART['axis']=ART['construction_axis']
ICON_KEYS=frozenset(ART)


def svg_source(kind,colors):
    # Drawn on a 32-unit grid, then shrunk 6% around the centre so antialiased
    # strokes never touch the icon border at any scale (Qt's rasterizer bleeds ~1px).
    content=ART.get(kind,ART['unknown'])
    for key,value in colors.items():content=content.replace('__'+key+'__',value)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
            '<g transform="matrix(.94 0 0 .94 .96 .96)" fill="none" stroke="'+colors['ink']+'" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">'+content+'</g></svg>').encode()
