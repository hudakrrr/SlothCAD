"""Portable STEP bases and analytic DXF sketch exchange in millimeters."""
import base64,io,zlib,copy,math
from pathlib import Path
from functools import lru_cache
import cadquery as cq
import numpy as np
from geometry import entity,identifier,validate_entity,arc_data,sample
from legacy_model import ModelError

MESH_TRIANGLE_LIMIT=60000      # a mesh becomes one kernel face per triangle before it is merged


def _hex(color):
    r,g,b=(max(0,min(255,int(round(float(v)*255)))) for v in color.toTuple()[:3])
    return '#{:02x}{:02x}{:02x}'.format(r,g,b)


def _step_parts(path):
    """``[(name, colour or None, solid)]`` from the STEP product structure (names and colours kept)."""
    try:root=cq.Assembly.importStep(str(path))
    except Exception:return []
    parts=[]
    def visit(node,location,color,depth=0):
        if depth>64:return
        here=location*node.loc if getattr(node,'loc',None) is not None else location
        shade=node.color if getattr(node,'color',None) is not None else color
        if node.obj is not None:
            shape=node.obj.val() if hasattr(node.obj,'val') else node.obj
            try:placed=shape.moved(here)
            except Exception:placed=shape
            for solid in placed.Solids():parts.append((node.name,_hex(shade) if shade is not None else None,solid))
        for child in node.children:visit(child,here,shade,depth+1)
    try:visit(root,cq.Location(),None)
    except Exception:return []
    return parts


def _checked_solids(solids,label):
    if not solids:raise ModelError(label+' must contain closed solid bodies.')
    repaired=[]
    for solid in solids:
        if not solid.isValid():
            # Many real-world files are slightly out of tolerance; try a kernel repair first.
            try:solid=solid.fix()
            except Exception:pass
        repaired.append(solid)
    if any(not solid.isValid() for solid in repaired):raise ModelError(label+' contains solids the kernel reports as invalid, even after repair.')
    return repaired


def _import_feature(solids,path,names=None,colors=None):
    buf=io.BytesIO();cq.Compound.makeCompound(solids).exportBrep(buf)
    feature=dict(kind='import_solid',id=identifier(),name=Path(path).stem,enabled=True,source_name=Path(path).name,
                 brep=base64.b64encode(zlib.compress(buf.getvalue())).decode('ascii'),scale=1.,dx=0.,dy=0.,dz=0.,angle=0.)
    if names:feature['part_names']=[str(n) for n in names]
    if colors and any(colors):feature['part_colors']=[c or '' for c in colors]
    return feature


def import_step(path):
    """A STEP file as an ``import_solid`` feature. Part names and colours are kept when it has them."""
    parts=_step_parts(path)
    if not parts:
        # A STEP file can hold several root shapes; .val() would keep only the first.
        shapes=cq.importers.importStep(str(path)).vals()
        solids=[solid for shape in shapes if hasattr(shape,'Solids') for solid in shape.Solids()]
        return _import_feature(_checked_solids(solids,'STEP'),path)
    solids=_checked_solids([p[2] for p in parts],'STEP')
    return _import_feature(solids,path,[p[0] for p in parts],[p[1] for p in parts])


def import_iges(path):
    """IGES solids; closed shells made of surfaces are sewn into solids."""
    from OCP.IGESControl import IGESControl_Reader
    reader=IGESControl_Reader()
    if not reader.ReadFile(str(path)):raise ModelError('The IGES file could not be read.')
    reader.TransferRoots()
    shape=cq.Shape.cast(reader.OneShape())
    solids=list(shape.Solids())
    if not solids:solids=_solids_from_faces(list(shape.Faces()))
    return _import_feature(_checked_solids(solids,'IGES'),path)


def _solids_from_faces(faces):
    """Sew faces together and keep the closed shells as solids."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    if not faces:return []
    sewing=BRepBuilderAPI_Sewing(1e-5)
    for face in faces:sewing.Add(face.wrapped)
    sewing.Perform()
    sewn=cq.Shape.cast(sewing.SewedShape())
    solids=[]
    for shell in sewn.Shells():
        if not shell.Closed():continue
        try:solid=cq.Solid.makeSolid(shell).fix()
        except Exception:continue
        if solid.isValid() and solid.Volume()>1e-9:solids.append(solid.clean())
    return solids


def _triangle_faces(vertices,triangles):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace,BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    if len(triangles)>MESH_TRIANGLE_LIMIT:
        raise ModelError(f'The mesh has {len(triangles):,} triangles; SlothCAD imports meshes of up to {MESH_TRIANGLE_LIMIT:,}. Simplify it first.')
    faces=[]
    for a,b,c in triangles:
        pa,pb,pc=(np.asarray(vertices[i],float) for i in (a,b,c))
        if float(np.linalg.norm(np.cross(pb-pa,pc-pa)))<1e-12:continue
        polygon=BRepBuilderAPI_MakePolygon(gp_Pnt(*pa),gp_Pnt(*pb),gp_Pnt(*pc),True)
        maker=BRepBuilderAPI_MakeFace(polygon.Wire(),True)
        if maker.IsDone():faces.append(cq.Face(maker.Face()))
    return faces


def read_mesh(path):
    """``(vertices, triangles)`` of an STL (ASCII or binary), OBJ or 3MF file."""
    suffix=Path(path).suffix.lower()
    if suffix=='.stl':
        data=Path(path).read_bytes()
        if data[:5].lower()==b'solid' and b'facet' in data[:2000]:
            numbers=[float(t) for line in data.decode('ascii','replace').splitlines() if line.strip().startswith('vertex') for t in line.split()[1:4]]
            points=np.asarray(numbers,float).reshape((-1,3))
        else:
            import struct
            count=struct.unpack('<I',data[80:84])[0]
            if 84+count*50>len(data):raise ModelError('The STL file is truncated.')
            record=np.dtype([('n','<f4',3),('v','<f4',(3,3)),('a','<u2')])
            points=np.frombuffer(data,dtype=record,count=count,offset=84)['v'].reshape((-1,3)).astype(float)
        keys={};vertices=[];triangles=[]
        for point in points:
            key=tuple(np.round(point,6))
            if key not in keys:keys[key]=len(vertices);vertices.append(point)
            triangles.append(keys[key])
        return np.asarray(vertices),np.asarray(triangles,int).reshape((-1,3))
    if suffix=='.obj':
        vertices=[];triangles=[]
        for line in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
            parts=line.split()
            if not parts:continue
            if parts[0]=='v' and len(parts)>=4:vertices.append([float(x) for x in parts[1:4]])
            elif parts[0]=='f' and len(parts)>=4:
                ids=[int(token.split('/')[0]) for token in parts[1:]]
                ids=[i-1 if i>0 else len(vertices)+i for i in ids]
                triangles.extend([ids[0],ids[k],ids[k+1]] for k in range(1,len(ids)-1))
        return np.asarray(vertices,float).reshape((-1,3)),np.asarray(triangles,int).reshape((-1,3))
    if suffix=='.3mf':
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path) as package:
            names=[n for n in package.namelist() if n.lower().endswith('.model')]
            if not names:raise ModelError('The 3MF file has no model.')
            root=ET.fromstring(package.read(names[0]))
        vertices=[];triangles=[]
        for mesh in root.iter():
            if not mesh.tag.endswith('}mesh') and mesh.tag!='mesh':continue
            offset=len(vertices)
            for item in mesh.iter():
                tag=item.tag.rsplit('}',1)[-1]
                if tag=='vertex':vertices.append([float(item.get(k)) for k in ('x','y','z')])
                elif tag=='triangle':triangles.append([offset+int(item.get(k)) for k in ('v1','v2','v3')])
        return np.asarray(vertices,float).reshape((-1,3)),np.asarray(triangles,int).reshape((-1,3))
    raise ModelError('Unsupported mesh format.')


def import_mesh(path):
    """A closed triangle mesh as a solid: triangles are sewn together and coplanar ones merged."""
    vertices,triangles=read_mesh(path)
    if not len(triangles):raise ModelError('The mesh has no triangles.')
    solids=_solids_from_faces(_triangle_faces(vertices,triangles))
    if not solids:raise ModelError('The mesh is not watertight, so it cannot become a solid. Repair the holes in a mesh editor first.')
    return _import_feature(_checked_solids(solids,'Mesh'),path)


def import_model(path):
    """STEP, IGES or a triangle mesh, chosen by the file extension."""
    suffix=Path(path).suffix.lower()
    if suffix in ('.step','.stp'):return import_step(path)
    if suffix in ('.iges','.igs'):return import_iges(path)
    if suffix in ('.stl','.obj','.3mf'):return import_mesh(path)
    raise ModelError('Choose a STEP, IGES, STL, OBJ or 3MF file.')

@lru_cache(maxsize=12)
def _decode(payload):
    try:
        data=zlib.decompress(base64.b64decode(payload,validate=True));shape=cq.Shape.importBrep(io.BytesIO(data))
    except Exception as error:raise ModelError('Invalid embedded STEP geometry.') from error
    if not shape.isValid() or not shape.Solids():raise ModelError('Imported geometry has no valid solids.')
    return shape

def imported_shape(f):
    from legacy_model import number,positive
    shape=_decode(f['brep']);scale=positive(f.get('scale',1),'Import scale')
    if scale!=1:shape=shape.scale(scale)
    angle=number(f.get('angle',0),'Rotation angle')
    if angle:shape=shape.rotate((0,0,0),(0,0,1),angle)
    return shape.translate(tuple(number(f.get(k,0),'Translation') for k in ('dx','dy','dz')))

def import_dxf(path):
    import ezdxf
    from ezdxf import units
    from ezdxf.disassemble import recursive_decompose
    doc=ezdxf.readfile(path);unit=int(doc.header.get('$INSUNITS',0));scale=units.conversion_factor(unit,units.MM) if unit else 1.
    created=[];unsupported=set()
    def point(p):
        p=list(p)
        if len(p)>2 and abs(p[2]*scale)>1e-6:raise ModelError('DXF sketch geometry must lie in the XY plane (Z = 0).')
        return [float(p[0])*scale,float(p[1])*scale]
    def convert(e):
        kind=e.dxftype();items=[]
        if kind in ('LWPOLYLINE','POLYLINE'):
            for part in e.virtual_entities():items.extend(convert(part))
            return items
        if kind=='LINE':items=[entity('line',a=point(e.dxf.start),b=point(e.dxf.end))]
        elif kind=='POINT':items=[entity('point',p=point(e.dxf.location))]
        elif kind in ('CIRCLE','ARC'):
            normal=e.dxf.get('extrusion',(0,0,1))
            if abs(normal[0])+abs(normal[1])>1e-8 or normal[2]<.999:raise ModelError('DXF curves must use the positive XY plane normal.')
            center=point(e.dxf.center);radius=float(e.dxf.radius)*scale
            if kind=='CIRCLE':items=[entity('circle',center=center,radius=radius)]
            else:
                start=math.radians(e.dxf.start_angle);sweep=math.radians((e.dxf.end_angle-e.dxf.start_angle)%360)
                at=lambda t:(np.asarray(center)+radius*np.array([math.cos(t),math.sin(t)])).tolist()
                items=[entity('arc',a=at(start),mid=at(start+sweep/2),b=at(start+sweep))]
        elif kind=='ELLIPSE':
            center=point(e.dxf.center);major=(np.asarray(center)+np.asarray(point(e.dxf.major_axis))).tolist();rx=math.dist(center,major)
            if e.dxf.extrusion.z<.999:raise ModelError('DXF ellipses must use the positive XY plane normal.')
            result=entity('ellipse',center=center,major=major,minor_radius=rx*float(e.dxf.ratio))
            start=float(e.dxf.start_param);span=(float(e.dxf.end_param)-start)%(2*math.pi)
            if span>1e-10 and span<2*math.pi-1e-10:
                start%=2*math.pi;end=start+span
                for lo,hi in [(start,min(end,2*math.pi))]+([(0,end-2*math.pi)] if end>2*math.pi else []):
                    p=copy.deepcopy(result);p['id']=identifier();p['range']=[lo/(2*math.pi),hi/(2*math.pi)];items.append(p)
            else:items=[result]
        elif kind=='SPLINE':
            tool=e.construction_tool();points=[point(p) for p in tool.control_points]
            items=[entity('spline',basis='bspline',points=points,degree=tool.degree,knots=list(tool.knots()),weights=list(tool.weights()) or [1.]*len(points),closed=bool(e.closed))]
        elif kind in ('TEXT','MTEXT'):
            try:
                from geometry import text_polygons
                text=e.dxf.text if kind=='TEXT' else e.plain_text()
                height=float(e.dxf.height if kind=='TEXT' else e.dxf.char_height)*scale
                position=e.dxf.insert
                items=text_polygons(text.replace('\\P',' ').strip(),point(position),height) if text.strip() else []
            except Exception:unsupported.add(kind)
        else:unsupported.add(kind)
        for result in items:
            if e.dxf.layer=='SLOTHCAD_CONSTRUCTION':result['construction']=True
            validate_entity(result)
        return items
    for e in recursive_decompose(doc.modelspace()):created.extend(convert(e))
    if not created:raise ModelError('DXF contains no supported sketch geometry.')
    return created,sorted(unsupported),unit

def export_dxf(path,entities):
    import ezdxf
    from curves import edge_for,limits
    doc=ezdxf.new('R2010');doc.units=4;doc.layers.new('SLOTHCAD_CONSTRUCTION',dxfattribs={'color':8});layout=doc.modelspace()
    for e in entities:
        attrs={'layer':'SLOTHCAD_CONSTRUCTION' if e.get('construction') else '0'};kind=e['kind'];validate_entity(e)
        if kind=='line':layout.add_line(e['a'],e['b'],dxfattribs=attrs)
        elif kind=='point':layout.add_point(e['p'],dxfattribs=attrs)
        elif kind=='circle':layout.add_circle(e['center'],e['radius'],dxfattribs=attrs)
        elif kind=='arc':
            c,r,start,sweep=arc_data(e)
            if sweep<0:start+=sweep;sweep=-sweep
            layout.add_arc(c,r,math.degrees(start)%360,math.degrees(start+sweep)%360,dxfattribs=attrs)
        elif kind=='ellipse':
            edge=edge_for(e);adaptor=edge._geomAdaptor();ell=adaptor.Ellipse();c=ell.Location();axis=ell.XAxis().Direction();a,b=limits(edge)
            layout.add_ellipse((c.X(),c.Y()),(axis.X()*ell.MajorRadius(),axis.Y()*ell.MajorRadius()),ell.MinorRadius()/ell.MajorRadius(),a,b,dxfattribs=attrs)
        elif kind in ('spline','conic'):
            edge=edge_for(e)
            if edge.geomType()=='LINE':
                points=sample(e,2);layout.add_line(points[0],points[-1],dxfattribs=attrs);continue
            curve=edge._geomAdaptor().BSpline().Copy();a,b=limits(edge);curve.Segment(a,b,1e-9)
            controls=[(curve.Pole(i).X(),curve.Pole(i).Y(),0) for i in range(1,curve.NbPoles()+1)]
            knots=[curve.Knot(i) for i in range(1,curve.NbKnots()+1) for _ in range(curve.Multiplicity(i))]
            weights=[curve.Weight(i) for i in range(1,curve.NbPoles()+1)]
            layout.add_rational_spline(controls,weights,degree=curve.Degree(),knots=knots,dxfattribs=attrs)
        elif kind=='slot':
            from geometry import slot_parts
            for part,p in slot_parts(e):
                if part=='line':layout.add_line(p[0].tolist(),p[1].tolist(),dxfattribs=attrs)
                else:
                    c,r,start,sweep=arc_data(dict(a=p[0].tolist(),mid=p[1].tolist(),b=p[2].tolist()))
                    if sweep<0:start+=sweep;sweep=-sweep
                    layout.add_arc(c,r,math.degrees(start)%360,math.degrees(start+sweep)%360,dxfattribs=attrs)
        else:
            points=sample(e);layout.add_lwpolyline(points[:-1] if np.linalg.norm(points[0]-points[-1])<1e-6 else points,close=np.linalg.norm(points[0]-points[-1])<1e-6,dxfattribs=attrs)
    doc.saveas(str(path))


def export_3mf(path,items,tolerance=0.05,angular_tolerance=0.1):
    """Write bodies as a 3MF package (millimetres, one coloured mesh object per body).

    ``items`` is ``[(name, shape, (r, g, b))]`` with colours in 0..1. 3MF is the format slicers and
    print services expect: it carries units and colours, which STL cannot.
    """
    import zipfile
    from xml.sax.saxutils import quoteattr
    objects=[];materials=[]
    for index,(name,shape,rgb) in enumerate(items):
        vertices,triangles=shape.tessellate(float(tolerance),float(angular_tolerance))
        if not triangles:continue
        materials.append((name,rgb))
        rows=''.join(f'<vertex x="{v.x:.6f}" y="{v.y:.6f}" z="{v.z:.6f}"/>' for v in vertices)
        faces=''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in triangles)
        objects.append(f'<object id="{len(objects)+2}" type="model" name={quoteattr(str(name))} pid="1" pindex="{len(materials)-1}">'
                       f'<mesh><vertices>{rows}</vertices><triangles>{faces}</triangles></mesh></object>')
    if not objects:raise ModelError('There is no solid geometry to export as 3MF.')
    base=''.join('<base name={} displaycolor="#{:02X}{:02X}{:02X}FF"/>'.format(quoteattr(str(n)),*(int(round(max(0.,min(1.,c))*255)) for c in rgb)) for n,rgb in materials)
    build=''.join(f'<item objectid="{i+2}"/>' for i in range(len(objects)))
    model=('<?xml version="1.0" encoding="UTF-8"?>'
           '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
           f'<resources><basematerials id="1">{base}</basematerials>{"".join(objects)}</resources><build>{build}</build></model>')
    types=('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
           '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels=('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
          '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as package:
            package.writestr('[Content_Types].xml',types);package.writestr('_rels/.rels',rels);package.writestr('3D/3dmodel.model',model)
        temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
