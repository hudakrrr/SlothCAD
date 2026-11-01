"""Joins keep going when pieces cannot merge: coincident geometry is retried with a fuzzy
tolerance, and pieces that only touch the body along an edge become separate bodies."""
import os,sys,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cadquery as cq
import numpy as np
import model
from geometry import new_sketch,base_frame,entity,profile_regions
from model import Document,EXTRUDE_REPORTS


def plate_under_ring():
    """A rectangle with three concentric circles: the ring between the outer two is extruded up,
    then the band inside the ring plus the corner tips outside it are extruded down."""
    s=new_sketch(base_frame('XY'))
    s['entities']=[entity('rectangle',center=[25,22.5],width=50,height=45)]+[entity('circle',center=[25,22.5],radius=r) for r in (19.3,30.1,31.5)]
    regions=profile_regions(s)
    def source(r):return dict(type='sketch',sketch=s['id'],entities=r['entities'],holes=r['holes'],profile_mode='nested')
    inner,mid,outer=(e['id'] for e in s['entities'][1:])
    def uses(r,id_):return any(e.split('~')[0]==id_ for e in r['entities'])
    ring=[r for r in regions if uses(r,mid) and uses(r,outer)]
    band=[r for r in regions if r['holes']]
    tips=[r for r in regions if uses(r,outer) and not uses(r,mid)]
    ring_feature=dict(kind='extrude',id='ring',name='Ring',depth=12.,operation='add',signed_depth=False,sources=[source(r) for r in ring])
    plate=dict(kind='extrude',id='plate',name='Plate',depth=-1.,operation='add',signed_depth=False,sources=[source(r) for r in band+tips])
    return s,ring_feature,plate,len(tips)


class JoinResilienceTests(unittest.TestCase):
    def test_touching_profiles_of_one_extrusion_make_one_body(self):
        # The eight pieces of a ring cut by a rectangle used to become eight bodies.
        s,ring,plate,tips=plate_under_ring();self.assertEqual(len(ring['sources']),8)
        shape=Document([s,ring]).solid.val()
        self.assertEqual(len(shape.Solids()),1)
        self.assertAlmostEqual(shape.Volume(),3.141592653589793*(31.5**2-30.1**2)*12,delta=1.)

    def test_pieces_touching_along_an_edge_are_kept_as_bodies_and_reported(self):
        s,ring,plate,tips=plate_under_ring();self.assertEqual(tips,4)
        d=Document([s,ring,plate]);shape=d.solid.val()
        # ring, plus the band and the tips: each touches the ring only along an arc at z=0
        self.assertEqual(len(shape.Solids()),2+tips)
        self.assertEqual(EXTRUDE_REPORTS['plate'],{'separate':tips+1})

    def test_join_goes_on_when_the_exact_boolean_fails(self):
        box=cq.Workplane('XY').box(10,10,10)
        tool=cq.Workplane('XY').box(4,4,4).translate((0,0,6))
        original=cq.Workplane.union
        def flaky(self,other=None,clean=True,glue=False,tol=None):
            if tol is None:raise RuntimeError('simulated kernel failure on coincident faces')
            return original(self,other,clean=clean,glue=glue,tol=tol)
        cq.Workplane.union=flaky
        try:result=model._extrusion_boolean(box,tool,tool.val().Solids(),'add')
        finally:cq.Workplane.union=original
        self.assertEqual(len(result.val().Solids()),1)
        self.assertAlmostEqual(result.val().Volume(),1000+48,places=3)

    def test_unfusable_piece_becomes_a_separate_body_instead_of_failing(self):
        box=cq.Workplane('XY').box(10,10,10)
        near=cq.Workplane('XY').box(4,4,4).translate((0,0,6)).val()
        far=cq.Workplane('XY').box(2,2,2).translate((20,0,0)).val()
        original=cq.Workplane.union
        def refuses_far(self,other=None,clean=True,glue=False,tol=None):
            shapes=other.vals() if isinstance(other,cq.Workplane) else [other]
            if any(abs(x.Center().x-20)<1e-6 for x in shapes):raise RuntimeError('simulated failure')
            return original(self,other,clean=clean,glue=glue,tol=tol)
        cq.Workplane.union=refuses_far
        try:result=model._extrusion_boolean(box,cq.Workplane('XY').newObject([cq.Compound.makeCompound([near,far])]),[near,far],'add')
        finally:cq.Workplane.union=original
        self.assertEqual(len(result.val().Solids()),2)
        self.assertAlmostEqual(result.val().Volume(),1000+48+8,places=3)

    def test_overlap_probe_does_not_retry_an_empty_intersection(self):
        box=cq.Workplane('XY').box(10,10,10);far=cq.Workplane('XY').box(2,2,2).translate((20,0,0))
        calls=[];original=cq.Workplane.intersect
        def counted(self,*a,**k):calls.append(k);return original(self,*a,**k)
        cq.Workplane.intersect=counted
        try:
            with self.assertRaises(model.ModelError):model._extrusion_boolean(box,far,far.val().Solids(),'intersect')
        finally:cq.Workplane.intersect=original
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
