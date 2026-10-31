"""Batched validity checks must give the kernel's own answer on faces with many holes."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cadquery as cq
from OCP.BRep import BRep_Builder
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopoDS import TopoDS
import model,validity


def plate():
    return cq.Workplane().box(100,100,10).faces('>Z').workplane().rarray(10,10,10,10).hole(4)


class ValidityTests(unittest.TestCase):
    def test_matches_kernel_on_valid_bodies(self):
        p=plate().val();edge=max(p.Edges(),key=lambda e:(e.geomType()=='LINE',e.Center().z,e.Length()))
        for shape in (p,p.fillet(1.5,[edge]),p.chamfer(1,None,[edge])):
            self.assertTrue(BRepCheck_Analyzer(shape.wrapped).IsValid())
            self.assertTrue(validity.shape_valid(shape))

    def test_crossing_and_overlapping_holes_are_invalid(self):
        top=max(plate().val().Faces(),key=lambda f:len(f.innerWires()))
        self.assertGreater(len(top.innerWires()),validity.HEAVY_WIRES)
        for extra in (cq.Wire.makeCircle(10,cq.Vector(50,0,5),cq.Vector(0,0,-1)),       # crosses the outline
                      cq.Wire.makeCircle(3.5,cq.Vector(-44,-45,5),cq.Vector(0,0,-1))):   # overlaps a hole
            builder=BRep_Builder();face=TopoDS.Face_s(top.wrapped.EmptyCopied());builder.Add(face,top.outerWire().wrapped)
            for wire in top.innerWires():builder.Add(face,wire.wrapped)
            builder.Add(face,extra.wrapped)
            self.assertFalse(BRepCheck_Analyzer(face).IsValid())
            self.assertFalse(validity.shape_valid(face))
            self.assertFalse(validity.faces_valid([face]))

    def test_fillet_beside_a_perforated_face_is_checked_locally(self):
        # The re-trimmed perforated face must not make the overlap check look at every hole.
        body=plate();p=body.val();edge=max(p.Edges(),key=lambda e:(e.geomType()=='LINE',e.Center().z,e.Length()))
        raw=p.fillet(1.5,[edge]);top=max(raw.Faces(),key=lambda f:len(f.innerWires()))
        self.assertTrue(model._on_base_plane(top,model._base_planes(body)))
        self.assertFalse(model._local_self_intersects(body,raw))


if __name__=='__main__':unittest.main()
