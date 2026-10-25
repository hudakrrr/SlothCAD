import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Document, ModelError, new_feature, edge_reference
from geometry import new_sketch, base_frame, entity, profile_regions


def plate():
    f=new_feature();f.update(width=40,height=30,depth=10,id='plate',name='Plate');return f


def top_edge(document):
    edge=next(e for e in document.solid.val().Edges() if abs(e.Center().z-10)<1e-6)
    return edge_reference(edge,document.solid)


class EdgeModeTests(unittest.TestCase):
    def feature(self,kind,document,**fields):
        f=dict(kind=kind,name=kind,enabled=True,id=kind+'1',radius=2.,edges='vertical',edge_refs=[top_edge(document)]);f.update(fields);return f

    def test_two_distance_chamfer_removes_the_expected_material(self):
        base=Document([plate()]);length=40.
        c=self.feature('chamfer',base,mode='two_distance',distance2=4.)
        volume=Document([plate(),c]).solid.val().Volume()
        self.assertAlmostEqual(volume,12000-.5*2*4*length,places=4)

    def test_distance_angle_chamfer(self):
        base=Document([plate()])
        c=self.feature('chamfer',base,mode='distance_angle',angle=30.)
        volume=Document([plate(),c]).solid.val().Volume()
        self.assertAlmostEqual(volume,12000-.5*2*(2*math.tan(math.radians(30)))*40,places=4)

    def test_bad_chamfer_values_are_rejected(self):
        base=Document([plate()])
        for fields in (dict(mode='distance_angle',angle=0.),dict(mode='distance_angle',angle=90.),dict(mode='two_distance',distance2=-1.),dict(mode='nonsense')):
            with self.assertRaises(ModelError):Document([plate(),self.feature('chamfer',base,**fields)])

    def test_variable_fillet_lies_between_the_two_constant_ones(self):
        base=Document([plate()])
        small=Document([plate(),self.feature('fillet',base,radius=2.)]).solid.val().Volume()
        large=Document([plate(),self.feature('fillet',base,radius=5.)]).solid.val().Volume()
        variable=Document([plate(),self.feature('fillet',base,mode='variable',radius=2.,radius_end=5.)]).solid.val().Volume()
        self.assertLess(large,variable);self.assertLess(variable,small)

    def test_size_limit_search_honours_the_mode(self):
        from model import maximum_edge_size, edge_options
        base=Document([plate()])
        c=self.feature('chamfer',base,mode='two_distance',radius=1.,distance2=2.)
        symmetric,_=maximum_edge_size(base.solid,'chamfer',[top_edge(base)],hint=1.)
        limits=[]
        for flip in (False,True):
            c['flip']=flip
            limits.append(maximum_edge_size(base.solid,'chamfer',[top_edge(base)],hint=1.,options=edge_options(c))[0])
        # the doubled second leg lies on the 10 mm side face for one orientation: it reaches the limit sooner
        self.assertLess(min(limits),symmetric*.75)


class ExtrudeOptionTests(unittest.TestCase):
    def setUp(self):
        self.sketch=new_sketch(base_frame('XY'),'S')
        self.sketch['entities']=[entity('rectangle',center=[0,0],width=40,height=30),entity('circle',center=[0,0],radius=5)]
        region=max(profile_regions(self.sketch),key=lambda r:len(r['holes']))
        self.source=dict(type='sketch',sketch=self.sketch['id'],entities=region['entities'],holes=region['holes'],profile_mode='nested')

    def volume(self,**fields):
        f=dict(kind='extrude',id='e',name='e',enabled=True,sources=[self.source],depth=10.,operation='add',signed_depth=False);f.update(fields)
        return Document([copy.deepcopy(self.sketch),f]).solid.val().Volume()

    def test_two_sided_extrusion_uses_both_distances(self):
        area=40*30-math.pi*25
        self.assertAlmostEqual(self.volume(direction='two sides',depth=10.,depth2=4.),area*14,places=3)

    def test_two_sided_needs_a_distance_extent(self):
        with self.assertRaises(ModelError):self.volume(direction='two sides',extent='through all')

    def test_thin_wall_sides(self):
        t=2.
        inside=(40*30-36*26)+math.pi*(49-25)
        outside=(44*34-40*30)+math.pi*(25-9)
        self.assertAlmostEqual(self.volume(thin=t,thin_side='inside'),inside*10,places=2)
        self.assertAlmostEqual(self.volume(thin=t,thin_side='outside'),outside*10,places=2)
        centered=self.volume(thin=t,thin_side='centered')
        self.assertAlmostEqual(centered,((42*32-38*28)+math.pi*(36-16))*10,places=2)

    def test_wall_thicker_than_the_profile_is_rejected(self):
        with self.assertRaises(ModelError):self.volume(thin=16.,thin_side='inside')


class HoleAndSweepTests(unittest.TestCase):
    def hole(self,points):
        return dict(kind='hole',id='h',name='h',enabled=True,operation='cut',plane=dict(type='origin',plane='XY'),x=0.,y=0.,depth=4.,diameter=4.,
                    hole_type='simple',head_diameter=10.,head_depth=3.,head_angle=90.,through_all=False,direction='inward',points_sketch=points['id'])

    def test_holes_at_every_sketch_point(self):
        points=new_sketch(base_frame('XY'),'Points')
        points['entities']=[entity('point',p=[-10,0]),entity('point',p=[10,0]),entity('point',p=[0,8])]
        points['frame']=dict(origin=[0,0,10],u=[1,0,0],normal=[0,0,1])      # on the top face of the plate
        document=Document([plate(),points,self.hole(points)])
        self.assertAlmostEqual(12000-document.solid.val().Volume(),3*math.pi*4*4,places=3)

    def test_hole_without_points_reports_it(self):
        points=new_sketch(base_frame('XY'),'Points');points['entities']=[entity('line',a=[0,0],b=[5,0])]
        points['frame']=dict(origin=[0,0,10],u=[1,0,0],normal=[0,0,1])
        with self.assertRaises(ModelError):Document([plate(),points,self.hole(points)])

    def test_sweep_with_guide_curve(self):
        profile=new_sketch(base_frame('XY'),'Profile');profile['entities']=[entity('circle',center=[0,0],radius=2)]
        path=new_sketch(base_frame('XZ'),'Path');path['entities']=[entity('line',a=[0,0],b=[0,30])]
        guide=new_sketch(base_frame('XZ'),'Guide');guide['entities']=[entity('line',a=[5,0],b=[5,30])]
        region=profile_regions(profile)[0]
        source=dict(type='sketch',sketch=profile['id'],entities=region['entities'],holes=[],profile_mode='nested')
        f=dict(kind='sweep',id='s',name='s',enabled=True,operation='add',source=source,frenet=False,
               path=dict(sketch=path['id'],entities=[path['entities'][0]['id']]),guide=dict(sketch=guide['id'],entities=[guide['entities'][0]['id']]))
        document=Document([profile,path,guide,f])
        self.assertAlmostEqual(document.solid.val().Volume(),math.pi*4*30,delta=1.)


if __name__=='__main__':
    unittest.main()
