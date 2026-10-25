import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from model import Document, ModelError
from geometry import face_reference


def box_component(id_,name,origin,size,pose_origin=(0.,0.,0.),axis=(0.,0.,1.),angle=0.):
    inner=dict(kind='primitive',id=id_+'-box',name=name+' box',enabled=True,shape='box',width=size[0],length=size[1],height=size[2],origin=list(origin),operation='new')
    return dict(kind='component',id=id_,name=name,enabled=True,features=[inner],pose=dict(origin=list(pose_origin),axis=list(axis),angle=angle),grounded=False)


def face_at(document,body_index,normal,toward):
    """A face of the body whose outward normal is ``normal`` and that lies furthest along it."""
    best=None
    for face in document.solids()[body_index].Faces():
        if face.geomType()!='PLANE':continue
        n=np.asarray(face.normalAt().toTuple())
        if np.allclose(n,normal,atol=1e-6):
            if best is None:best=face
    return {'type':'face','face':face_reference(best),'origin':'projected'}


class MateTests(unittest.TestCase):
    def setUp(self):
        # a base block and a cube standing somewhere else, rotated by 90 degrees
        self.base=box_component('base',  'Base',  (0,0,0),(40,40,10))
        self.part=box_component('part','Part',(0,0,0),(10,10,10),pose_origin=(100.,50.,30.),axis=(1.,0.,0.),angle=90.)
        self.document=Document([self.base,self.part])

    def mate(self,**fields):
        joint=dict(kind='joint',id='mate0001',name='Mate',enabled=True,moving='part',fixed=None,joint_type='mate',
                   mate_moving=face_at(self.document,1,(0,0,-1),False),mate_target=face_at(self.document,0,(0,0,1),True),mate_offset=0.)
        joint.update(fields)
        return joint

    def bodies(self,document):
        return {name:body.BoundingBox() for name,body in zip(document.body_names(),document.solids())}

    def test_bottom_of_the_part_lands_on_the_top_of_the_base_centred(self):
        document=Document([self.base,self.part,self.mate()])
        boxes=self.bodies(document)
        part=boxes['Part'];base=boxes['Base']
        self.assertAlmostEqual(part.zmin,base.zmax,places=5)             # touching
        self.assertAlmostEqual((part.xmin+part.xmax)/2,(base.xmin+base.xmax)/2,places=5)
        self.assertAlmostEqual((part.ymin+part.ymax)/2,(base.ymin+base.ymax)/2,places=5)
        self.assertAlmostEqual(part.zmax-part.zmin,10,places=5)          # same size: it was only moved

    def test_gap_and_flush_options(self):
        gap=Document([self.base,self.part,self.mate(mate_offset=2.5)])
        boxes=self.bodies(gap);self.assertAlmostEqual(boxes['Part'].zmin,boxes['Base'].zmax+2.5,places=5)
        uncentred=Document([self.base,self.part,self.mate(mate_center=False)])
        boxes=self.bodies(uncentred);self.assertAlmostEqual(boxes['Part'].zmin,boxes['Base'].zmax,places=5)
        self.assertGreater(abs((boxes['Part'].xmin+boxes['Part'].xmax)/2),1.)     # stayed where it was in the plane

    def test_flush_flips_the_part_over(self):
        top_face=face_at(self.document,1,(0,0,1),False)
        flush=Document([self.base,self.part,self.mate(mate_moving=top_face,flip=True,mate_target=face_at(self.document,0,(0,0,1),True))])
        boxes=self.bodies(flush)
        self.assertAlmostEqual(boxes['Part'].zmax,boxes['Base'].zmax,places=5)   # top faces flush

    def test_following_the_target_when_it_changes(self):
        document=Document([self.base,self.part,self.mate()])
        taller=copy.deepcopy(document.features);taller[0]['features'][0]['height']=25.
        document.commit(taller)
        boxes=self.bodies(document)
        self.assertAlmostEqual(boxes['Part'].zmin,25.,places=5)

    def test_faces_must_come_from_the_right_components(self):
        wrong=self.mate(mate_moving=face_at(self.document,0,(0,0,1),True))      # a face of the base, not of the moving part
        with self.assertRaises(ModelError):Document([self.base,self.part,wrong])
        same=self.mate(mate_target=face_at(self.document,1,(0,0,1),True))
        with self.assertRaises(ModelError):Document([self.base,self.part,same])
        with self.assertRaises(ModelError):Document([self.base,self.part,self.mate(mate_moving=None)])

    def test_curved_faces_are_refused(self):
        cylinder=dict(kind='component',id='cyl',name='Cyl',enabled=True,pose=dict(origin=[0,0,0],axis=[0,0,1],angle=0.),grounded=False,
                      features=[dict(kind='primitive',id='cyl-1',name='c',enabled=True,shape='cylinder',radius=5.,height=10.,origin=[60,60,0],operation='new')])
        document=Document([self.base,cylinder])
        round_face=next(f for f in document.solids()[1].Faces() if f.geomType()=='CYLINDER')
        joint=dict(kind='joint',id='m2',name='M',enabled=True,moving='cyl',fixed=None,joint_type='mate',
                   mate_moving={'type':'face','face':{'center':list(round_face.Center().toTuple()),'area':float(round_face.Area()),'normal':[1,0,0],'geometry':'CYLINDER','edges':1}},
                   mate_target=face_at(document,0,(0,0,1),True))
        with self.assertRaises(ModelError):Document([self.base,cylinder,joint])


if __name__=='__main__':
    unittest.main()
