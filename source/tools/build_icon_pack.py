"""Builds SlothCAD's icon pack from Iconoir (MIT, https://github.com/iconoir-icons/iconoir) plus a few
icons drawn in the same style (24 px grid, 1.5 px round strokes).

    python build_iconoir_pack.py <output folder>

Writes <tool>.png (dark strokes, for light interfaces) and <tool>-dark.png (light strokes) at 128 px,
and <tool>.svg.  Iconoir's SVGs are downloaded once into <output>/_iconoir.
"""
import os
import sys
import urllib.request

BASE='https://raw.githubusercontent.com/iconoir-icons/iconoir/main/icons/regular/'

# SlothCAD tool name -> Iconoir icon name
ICONOIR={
 'select':'cursor-pointer','line':'linear','rectangle':'square-3d-corner-to-corner','center_rectangle':'square-3d-from-center',
 'rectangle_3p':'square-3d-three-points','circle':'one-point-circle','circle_3p':'three-points-circle','arc':'arc-3d',
 'center_arc':'arc-3d-center-point','ellipse':'ellipse-3d','polygon':'hexagon','spline':'ease-curve-control-points',
 'conic':'ease-in-out','point':'position','text':'text','trim':'scissor','rectangular':'view-grid',
 'sketch_move':'drag','dimension':'ruler-arrows','finish':'check','cancel':'xmark','fix':'lock','unfix':'lock-slash',
 'sketch':'design-pencil','extrude':'extrude','sweep':'sweep-3d','loft':'loft-3d','hole':'cube-hole',
 'primitive':'cube','pipe':'pipe-3d','coil':'spiral','shell':'box','draft':'face-3d-draft',
 'scale':'scale-frame-enlarge','replace_face':'cube-replace-face',
 'body_combine':'union','body_move':'axes','body_rectangular':'grid-plus','feature_rectangular':'grid-plus','path_pattern':'curve-array',
 'solid_tools':'cube','body':'cube','solid_modify':'tools','body_tools':'combine','body_patterns':'grid-plus','construct':'perspective-view',
 'sketch3d':'bridge-3d','surface_sweep':'sweep-3d',
 'surface_loft':'loft-3d','surface_stitch':'union-alt','surface_trim':'intersect-alt','surface_extend':'enlarge',
 'component':'packages','joint':'link','measure':'ruler-combine','repair':'wrench',
}

# Same style, drawn here.  (24 x 24, stroke 1.5, round caps and joins.)  d = path list, plus optional extras.
def P(*d,dash=None):return ('path',d,dash)
def C(cx,cy,r):return ('circle',(cx,cy,r),None)
def R(x,y,w,h,rx=0):return ('rect',(x,y,w,h,rx),None)
CUSTOM={
 'slot':[R(3,8,18,8,4)],
 'sketch_fillet':[P('M4 20V12C4 7.58 7.58 4 12 4H20'),P('M4 12V4H12',dash='1.5 2.5')],
 'chamfer':[P('M4 20V10L10 4H20'),P('M4 10V4H10',dash='1.5 2.5')],
 'circular':[C(12,12,8.5),C(12,3.8,1.6),C(20.2,12,1.6),C(12,20.2,1.6),C(3.8,12,1.6)],
 'construction':[P('M4 20L20 4',dash='3 3'),C(4,20,1.3),C(20,4,1.3)],
 'coincident':[P('M3 19L10 12'),P('M14 12L21 5'),C(12,12,2)],
 'horizontal':[P('M3 12H21'),P('M3 8V16'),P('M21 8V16')],
 'vertical':[P('M12 3V21'),P('M8 3H16'),P('M8 21H16')],
 'parallel':[P('M5 20L13 4'),P('M11 20L19 4')],
 'perpendicular':[P('M4 20H20'),P('M12 20V4'),P('M12 16H16V20')],
 'tangent':[C(12,14,6),P('M3 8H21')],
 'equal':[P('M5 9H19'),P('M5 15H19')],
 'concentric':[C(12,12,9),C(12,12,4.5)],
 'collinear':[P('M3 17L9 13'),P('M15 9L21 5'),P('M9 13L15 9',dash='1.5 2.5')],
 'midpoint':[P('M3 17H21'),C(12,17,2),P('M12 4V13',dash='2 2.5')],
 'point_on_object':[P('M3 19C6 6 18 6 21 19'),C(12,9.6,2)],
 'symmetry':[P('M12 3V21',dash='2.5 2.5'),C(6.5,8,2.2),C(17.5,8,2.2),C(6.5,16,2.2),C(17.5,16,2.2)],
 'revolve':[P('M12 3V21',dash='2.5 2.5'),P('M12 7H18V17H12'),P('M6.5 17C3.5 14.5 3.5 9.5 6.5 7'),P('M4.2 8.5L6.5 7L7.4 9.6')],
 'thread':[P('M9 3H15V6H9Z'),P('M10 6V21H14V6'),P('M10 10H14'),P('M10 13.5H14'),P('M10 17H14')],
 'rib':[P('M3 19H21V21H3Z'),P('M5 19V6L19 19')],
 'web':[R(3,6,18,12),P('M12 6V18'),P('M3 12H21')],
 'offset_plane':[P('M3 7L12 3L21 7L12 11Z'),P('M3 16L12 12L21 16L12 20Z')],
 'angled_plane':[P('M3 18L12 14L21 18L12 22Z'),P('M6 14V5L18 3V12Z')],
 'midplane':[P('M4 5L12 2L20 5L12 8Z'),P('M4 19L12 16L20 19L12 22Z'),P('M4 12L12 9L20 12L12 15Z',dash='2 2.5')],
 'three_point_plane':[P('M4 17L12 4L21 14Z'),C(4,17,1.7),C(12,4,1.7),C(21,14,1.7)],
 'construction_axis':[P('M4 20L20 4'),C(4,20,1.8),C(20,4,1.8)],
 'surface_extrude':[P('M3 20C8 16 16 24 21 20'),P('M12 14V3'),P('M8.5 6.5L12 3L15.5 6.5')],
 'surface_revolve':[P('M12 3V21',dash='2.5 2.5'),P('M12 5C17 6 17 12 12 13'),P('M20 14C19 18 15 21 11 20')],
 'surface_thicken':[P('M3 9C8 5 16 13 21 9'),P('M3 15C8 11 16 19 21 15'),P('M3 9V15'),P('M21 9V15')],
}

# Redrawn so that the picture says what the tool does.
CUSTOM.update({
 # mirrored triangles across a dashed axis
 'mirror':[P('M12 3V21',dash='2 2.5'),P('M9 19V6L3 19Z'),P('M15 19V6L21 19Z')],
  # an L-shaped part and its dashed mirror image across a solid axis
 'body_mirror':[P('M12 3V21'),P('M10 19H3V5H6V16H10Z'),P('M14 19H21V5H18V16H14Z',dash='2.2 2.2')],
 # a block whose hole is repeated on the other side of a dashed axis
 'feature_mirror':[P('M3 8H21V18H3Z'),P('M12 4V22',dash='2 2.5'),C(7.5,13,2.2),('circle',(16.5,13,2.2),'2 1.6')],
 # the top face of a block divided by a curve
 'split_face':[P('M3 9L12 4L21 9L12 14Z'),P('M3 9V15L12 20L21 15V9'),P('M12 14V20'),P('M7.5 6.5C10 11 13 7 16.5 11.5')],
 # a solid above the sketch plane, its outline brought down onto the plane
 'project':[P('M12 1.8L16.2 4.1V8.9L12 11.2L7.8 8.9V4.1Z'),P('M7.8 4.1L12 6.4L16.2 4.1'),P('M12 6.4V11.2'),
            P('M12 13V16'),P('M10 14.3L12 16.3L14 14.3'),
            P('M3 19.5L12 16.5L21 19.5L12 22.5Z'),P('M8 19.5L12 18.2L16 19.5L12 20.8Z',dash='1.6 1.6')],
 # two points facing each other across the axis
 'symmetry':[P('M12 3V21',dash='2 2.5'),C(5,12,2),C(19,12,2),P('M7 12H9.5'),P('M14.5 12H17')],
 # a pad raised on a base, with the arrow that pulls it
 'press_pull':[P('M3 20H21V14H15V8H9V14H3Z'),P('M12 6.5V1.5'),P('M9.5 4L12 1.5L14.5 4')],
 # a face moved out by a distance: original, new position (dashed) and the arrow
 'offset_face':[P('M3 6H14V18H3Z'),P('M19 5V19',dash='2 2.5'),P('M14 12H20.5'),P('M18.2 9.7L20.5 12L18.2 14.3')],
 # a part divided in two along a dashed cut line
 'body_split':[P('M3 7H10V17H3Z'),P('M14 7H21V17H14Z'),P('M12 3V21',dash='2 2.5')],
 # a patch with its boundary curves and corner points
 'surface_patch':[P('M3 8C7 5 10 11 14 8C17 6 19 6 21 8'),P('M3 17C7 14 10 20 14 17C17 15 19 15 21 17'),P('M3 8V17'),P('M21 8V17'),C(3,8,1.2),C(21,8,1.2),C(3,17,1.2),C(21,17,1.2)],
 # two shapes tied together
 'constraint':[R(3,7,7,7,1),C(18,10.5,3.5),P('M10 10.5H14.5',dash='2 2'),P('M3 19H21')],
 # a curved sheet with a curve drawn on it
 'surface_sketch':[P('M3 8C8 4 16 12 21 8V17C16 21 8 13 3 17Z'),P('M7 13C9 10 12 12 14 9.5C15 8.5 16 9 17 10',dash='2 2')],
 # profile beside its axis, with the turning arrow
 'revolve':[P('M12 3V21',dash='2.5 2.5'),P('M12 7H18V17H12'),P('M3.5 12C3.5 8.5 6 6 9 5.2'),P('M9 5.2L7 3.6'),P('M9 5.2L7.4 7.2')],
})

# Solid fillet and chamfer: a cube whose front vertical edge is rounded / cut off.
# Section analysis: a block with the cutting plane through it; the cut-away half is dashed.
CUSTOM['section']=[P('M4 9L10 6H20V16L14 19H4Z'),P('M4 9H14V19'),P('M14 9L20 6'),P('M9 3.5V21.5L13 19.5',dash='2 2'),P('M9 3.5L13 1.5V19.5',dash='2 2')]
CUSTOM['sketch_chamfer']=list(CUSTOM['chamfer'])      # the flat corner drawing stays for sketches
_cube_sides=[P('M12 3L20 7.5V16.5L16.4 18.5'),P('M12 3L4 7.5V16.5L7.6 18.5'),
             P('M4 7.5L7.6 9.5'),P('M20 7.5L16.4 9.5'),P('M7.6 9.5V18.5'),P('M16.4 9.5V18.5')]
CUSTOM['fillet']=_cube_sides+[P('M7.6 9.5Q12 13.2 16.4 9.5'),P('M7.6 18.5Q12 22.2 16.4 18.5')]
CUSTOM['chamfer']=_cube_sides+[P('M7.6 9.5H16.4'),P('M7.6 18.5H16.4')]
CUSTOM['body_circular']=CUSTOM['circular'];CUSTOM['feature_circular']=CUSTOM['circular']

# Sketch editing tools: extend a line to a wall, offset an outline, move / copy geometry.
CUSTOM.update({
 'extend':[P('M3 17H14'),P('M14 17H20',dash='1.8 2.2'),P('M21 4V20'),P('M9 11H15'),P('M12.5 8.5L15 11L12.5 13.5')],
 'offset':[P('M4 20V8C4 5.8 5.8 4 8 4H20'),P('M9 20V11C9 9.9 9.9 9 11 9H20',dash='2 2.2'),P('M3 3L7 7')],
 'transform':[R(3,11,10,10,1),R(11,3,10,10,1),P('M8 8L12 4'),P('M9.5 4H12V6.5')],
})

def svg_for_custom(items,color):
    out=['<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" '
         f'stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">']
    for kind,data,dash in items:
        extra=f' stroke-dasharray="{dash}"' if dash else ''
        if kind=='path':
            for d in data:out.append(f'<path d="{d}"{extra}/>')
        elif kind=='circle':out.append(f'<circle cx="{data[0]}" cy="{data[1]}" r="{data[2]}"{extra}/>')
        else:out.append(f'<rect x="{data[0]}" y="{data[1]}" width="{data[2]}" height="{data[3]}" rx="{data[4]}"/>')
    out.append('</svg>')
    return ''.join(out)

def fetch(folder,name):
    path=os.path.join(folder,name+'.svg')
    if not os.path.exists(path):
        with urllib.request.urlopen(BASE+name+'.svg',timeout=30) as response:
            data=response.read()
        open(path,'wb').write(data)
    return open(path,encoding='utf-8').read()

def main(out):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import QByteArray,Qt
    from PySide6.QtGui import QGuiApplication,QImage,QPainter
    from PySide6.QtSvg import QSvgRenderer
    app=QGuiApplication.instance() or QGuiApplication([])
    cache=os.path.join(out,'_iconoir');os.makedirs(cache,exist_ok=True)
    sources={}
    for key,name in ICONOIR.items():sources[key]=('iconoir',fetch(cache,name))
    for key,items in CUSTOM.items():sources[key]=('custom',items)
    ink={'':'#2e3944','-dark':'#e8eef3'}
    count=0
    for key,(kind,data) in sources.items():
        for suffix,color in ink.items():
            svg=data.replace('currentColor',color) if kind=='iconoir' else svg_for_custom(data,color)
            if suffix=='':open(os.path.join(out,key+'.svg'),'w',encoding='utf-8').write(svg)
            renderer=QSvgRenderer(QByteArray(svg.encode('utf-8')))
            image=QImage(128,128,QImage.Format_ARGB32);image.fill(Qt.transparent)
            painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
            from PySide6.QtCore import QRectF
            renderer.render(painter,QRectF(0,0,128,128));painter.end()
            image.save(os.path.join(out,key+suffix+'.png'));count+=1
    print('tools:',len(sources),'| from Iconoir:',len(ICONOIR),'| drawn in the same style:',len(CUSTOM),'| files:',count)

if __name__=='__main__':
    main(sys.argv[1] if len(sys.argv)>1 else 'iconoir-pack')
