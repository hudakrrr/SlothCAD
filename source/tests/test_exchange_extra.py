import copy
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import cadquery as cq
import exchange
import drawing
from model import Document, ModelError, new_feature


def plate(**fields):
    f=new_feature();f.update(width=40,height=30,depth=10,id='plate001',name='Plate');f.update(fields);return f


def with_hole():
    hole=new_feature();hole.update(profile='circle',radius=4,depth=12,z=-1,operation='cut',id='hole0001',name='Hole')
    return Document([plate(),hole])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.document=with_hole();self.volume=self.document.solid.val().Volume()

    def path(self,name):return str(Path(self.folder.name)/name)

    def test_step_keeps_colours_and_names(self):
        self.document.display['materials']={'0':{'color':'#ff0000','finish':'matte'}}
        self.document.export(self.path('c.step'))
        feature=exchange.import_step(self.path('c.step'))
        self.assertEqual(feature['part_colors'],['#ff0000']);self.assertEqual(len(feature['part_names']),1)
        solid=Document([feature]).solid.val()
        self.assertAlmostEqual(solid.Volume(),self.volume,places=2)

    def test_plain_step_import_still_works_without_structure(self):
        cq.exporters.export(cq.Workplane('XY').box(10,10,10),self.path('plain.step'))
        feature=exchange.import_step(self.path('plain.step'))
        self.assertAlmostEqual(Document([feature]).solid.val().Volume(),1000.,places=3)

    def test_stl_is_a_valid_mesh_with_the_right_volume(self):
        self.document.export(self.path('a.stl'),tolerance=.01,angular_tolerance=.05)
        vertices,triangles=exchange.read_mesh(self.path('a.stl'))
        volume=sum(float(np.dot(vertices[a],np.cross(vertices[b],vertices[c])))/6. for a,b,c in triangles)
        self.assertAlmostEqual(volume,self.volume,delta=self.volume*.002)

    def test_export_tolerance_controls_mesh_density(self):
        self.document.export(self.path('coarse.stl'),tolerance=1.,angular_tolerance=.8)
        self.document.export(self.path('fine.stl'),tolerance=.005,angular_tolerance=.05)
        self.assertGreater(os.path.getsize(self.path('fine.stl')),os.path.getsize(self.path('coarse.stl')))
        with self.assertRaises(ModelError):self.document.export(self.path('bad.stl'),tolerance=0)

    def test_3mf_package_and_round_trip(self):
        self.document.display['materials']={'0':{'color':'#00ff00','finish':'matte'}}
        self.document.export(self.path('a.3mf'))
        with zipfile.ZipFile(self.path('a.3mf')) as package:
            self.assertEqual(sorted(package.namelist()),['3D/3dmodel.model','[Content_Types].xml','_rels/.rels'])
            model=package.read('3D/3dmodel.model').decode()
        self.assertIn('unit="millimeter"',model);self.assertIn('displaycolor="#00FF00FF"',model)
        feature=exchange.import_mesh(self.path('a.3mf'))
        self.assertAlmostEqual(Document([feature]).solid.val().Volume(),self.volume,delta=self.volume*.01)

    def test_obj_and_stl_meshes_become_solids(self):
        vertices=np.array([[0,0,0],[10,0,0],[10,10,0],[0,10,0],[0,0,10],[10,0,10],[10,10,10],[0,10,10]],float)
        quads=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
        with open(self.path('cube.obj'),'w') as stream:
            for v in vertices:stream.write('v {} {} {}\n'.format(*v))
            for q in quads:stream.write('f '+' '.join(str(i+1) for i in q)+'\n')
        feature=exchange.import_model(self.path('cube.obj'))
        solid=Document([feature]).solid.val()
        self.assertAlmostEqual(solid.Volume(),1000.,places=3);self.assertEqual(len(solid.Faces()),6)   # triangles merged into planar faces

    def test_open_mesh_is_refused_with_an_explanation(self):
        with open(self.path('open.obj'),'w') as stream:
            stream.write('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        with self.assertRaises(ModelError) as raised:exchange.import_mesh(self.path('open.obj'))
        self.assertIn('watertight',str(raised.exception))

    def test_glb_export(self):
        self.document.export(self.path('a.glb'))
        self.assertEqual(Path(self.path('a.glb')).read_bytes()[:4],b'glTF')

    def test_visible_only_leaves_out_hidden_bodies(self):
        second=copy.deepcopy(plate());second.update(id='plate002',name='Second',operation='add',z=40)
        document=Document([plate(),second])
        self.assertEqual(len(document.solids()),2)
        document.display['bodies']={'1':False}
        self.assertEqual(len(document.export_items(visible_only=True)),1)
        self.assertEqual(len(document.export_items(visible_only=False)),2)
        document.display['bodies']={'0':False,'1':False}
        with self.assertRaises(ModelError):document.export_items(visible_only=True)

    def test_unknown_extension_is_rejected(self):
        with self.assertRaises(ModelError):self.document.export(self.path('a.xyz'))


class AnalysisTests(unittest.TestCase):
    def test_meshes_up_to_100000_triangles_are_accepted(self):
        import exchange
        from legacy_model import ModelError
        self.assertEqual(exchange.MESH_TRIANGLE_LIMIT,100000)
        with self.assertRaisesRegex(ModelError,'100,001 triangles.*up to 100,000'):
            exchange._triangle_faces(np.zeros((3,3)),np.zeros((100001,3),dtype=int))

    def test_mass_properties_of_a_box(self):
        document=Document([plate()])
        result=document.mass_properties(density=7.85)
        self.assertAlmostEqual(result['volume'],12000.,places=3)
        self.assertAlmostEqual(result['mass'],12000*7.85/1000,places=3)
        np.testing.assert_allclose(result['center'],[0,0,5],atol=1e-6)
        m=result['mass'];w,h,d=40.,30.,10.
        expected=sorted([m*(h*h+d*d)/12,m*(w*w+d*d)/12,m*(w*w+h*h)/12])
        np.testing.assert_allclose(result['principal'],expected,rtol=1e-6)

    def test_two_bodies_combine_with_the_parallel_axis_theorem(self):
        second=plate();second.update(id='plate002',z=100,operation='add')
        document=Document([plate(),second])
        result=document.mass_properties(1.)
        self.assertEqual(len(result['bodies']),2)
        np.testing.assert_allclose(result['center'],[0,0,55],atol=1e-6)
        single=result['bodies'][0]
        tensor=np.asarray(result['inertia'])
        self.assertGreater(tensor[0,0],2*single['inertia'][0][0])         # the offset adds m*d² to Ixx

    def test_invalid_density_is_rejected(self):
        for value in (0,-1,float('nan')):
            with self.assertRaises(ModelError):Document([plate()]).mass_properties(value)

    def test_interference_and_bill_of_materials(self):
        a=Document([plate()]).solids()[0]
        b=a.translate((10,0,0))
        c=a.translate((100,0,0))
        from analysis import interferences, bill_of_materials
        found=interferences([('A',a),('B',b),('C',c)])
        self.assertEqual([(x,y) for x,y,_ in found],[('A','B')])
        self.assertAlmostEqual(found[0][2],30*30*10,places=3)
        touching=interferences([('A',a),('T',a.translate((40,0,0)))])
        self.assertEqual(touching,[])                                     # shared faces are not interference
        rows=bill_of_materials([('Plate',a),('Plate',c),('Block',a.scale(.5))],None)
        self.assertEqual({r['name']:r['quantity'] for r in rows},{'Plate':2,'Block':1})


class DrawingTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.shape=with_hole().solid.val()

    def test_dxf_sheet_has_layers_views_and_dimensions(self):
        import ezdxf
        path=str(Path(self.folder.name)/'d.dxf')
        names=drawing.export_dxf(path,self.shape,('front','top','right'))
        self.assertEqual(names,['front','top','right'])
        document=ezdxf.readfile(path)
        layers={layer.dxf.name for layer in document.layers}
        self.assertTrue({'VISIBLE','HIDDEN','DIMENSIONS'}<=layers)
        kinds={e.dxftype() for e in document.modelspace()}
        self.assertTrue({'LWPOLYLINE','DIMENSION','TEXT'}<=kinds)
        # the hole is a circle in the top view and a hidden outline in the front view
        self.assertIn('CIRCLE',kinds)
        hidden=[e for e in document.modelspace() if e.dxf.layer=='HIDDEN']
        self.assertTrue(hidden)

    def test_views_are_laid_out_in_third_angle_projection(self):
        sheet={name:box for name,_,_,box in drawing.layout_views(self.shape,('front','top','right'))}
        front,top,right=sheet['front'],sheet['top'],sheet['right']
        self.assertGreater(top[1],front[3])             # top view above the front view
        self.assertGreater(right[0],front[2])           # right view to the right of it
        self.assertAlmostEqual(front[2]-front[0],40,places=3)    # width
        self.assertAlmostEqual(front[3]-front[1],10,places=3)    # height
        self.assertAlmostEqual(top[3]-top[1],30,places=3)        # depth

    def test_svg_and_options(self):
        path=str(Path(self.folder.name)/'d.svg')
        drawing.export_svg(path,self.shape,('front',),hidden=False,scale=.5,title='Plate')
        text=Path(path).read_text(encoding='utf-8')
        self.assertTrue(text.startswith('<svg'));self.assertIn('scale 1:2',text);self.assertIn('Plate',text)
        self.assertNotIn('stroke-dasharray',text)
        with self.assertRaises(ModelError):drawing.export_svg(path,self.shape,('front',),scale=0)
        with self.assertRaises(ModelError):drawing.export_dxf(path,self.shape,('nonsense',))


if __name__=='__main__':
    unittest.main()
