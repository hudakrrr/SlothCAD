"""Live previews behind the drag arrows (pure geometry, no kernel)."""
import math,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import handle_previews as H


class EdgePreviewTests(unittest.TestCase):
    def test_fillet_on_a_box_edge_is_a_quarter_round_of_the_radius(self):
        s=H.edge_station([0,0,10],[1,0,0],[0,0,1],[0,-1,0],True)
        rail_a,rail_b,arc=H.edge_ghost([[s,s]])(2)[:3]
        np.testing.assert_allclose(rail_a[0],[0,2,10],atol=1e-9);np.testing.assert_allclose(rail_b[0],[0,0,8],atol=1e-9)
        center=np.array([0,2,8.]);np.testing.assert_allclose(np.linalg.norm(arc-center,axis=1),2,atol=1e-9)

    def test_chamfer_is_a_straight_bevel(self):
        s=H.edge_station([0,0,10],[1,0,0],[0,0,1],[0,-1,0],True)
        profile=H.edge_ghost([[s]],chamfer=True)(3)[2]
        np.testing.assert_allclose(profile,[[0,3,10],[0,0,7]],atol=1e-9)

    def test_inside_corner_rounds_into_the_open_side(self):
        s=H.edge_station([0,0,0],[1,0,0],[0,0,1],[0,1,0],False)
        np.testing.assert_allclose(s['v1'],[0,1,0],atol=1e-9);np.testing.assert_allclose(s['v2'],[0,0,1],atol=1e-9)

    def test_tangent_faces_have_nothing_to_round(self):
        self.assertIsNone(H.edge_station([0,0,0],[1,0,0],[0,0,1],[0,0,1],True))


class CurvedFacePreviewTests(unittest.TestCase):
    def test_fillet_next_to_concave_cylinder_matches_kernel(self):
        # Flat face y=0 meets a concave cylinder (centre (50,-20), r=40); the flat-face
        # formula previewed the rounding ~3.5x too large while dragging.
        p=np.array([50-math.sqrt(1200),0.,5.]);axis=np.array([50.,-20.,5.])
        n_flat=np.array([0.,-1.,0.])
        def n_cyl(q):d=axis-np.asarray(q);d[2]=0;return d/np.linalg.norm(d)
        s=H.edge_station(p,[0,0,1],n_flat,n_cyl(p),True,lambda i,q:n_flat if i==0 else n_cyl(q),.01)
        a,b,arc=[np.asarray(x) for x in H.edge_ghost([[s]])(15)]
        ends=sorted([tuple(np.round(arc[0][:2],2)),tuple(np.round(arc[-1][:2],2))])
        self.assertEqual(ends,[(7.57,0.),(19.14,5.45)])


class OutlinePreviewTests(unittest.TestCase):
    def test_polygon_offset_moves_inward_for_both_windings(self):
        square=np.array([[0,0],[10,0],[10,10],[0,10]],float)
        for loop in (square,square[::-1]):
            out=H.offset_loop_2d(loop,1)[:-1]
            self.assertTrue(np.all(out>=1-1e-9) and np.all(out<=9+1e-9))

    def test_shell_preview_has_an_inner_rim_and_floor(self):
        top=np.array([[-5,-5,10],[5,-5,10],[5,5,10],[-5,5,10],[-5,-5,10]],float)
        rim,floor=H.shell_ghost(top,[0,0,10],[0,0,1],10)(2)[:2]
        self.assertAlmostEqual(float(np.max(np.abs(rim[:,0]))),3);self.assertAlmostEqual(float(floor[0,2]),2)

    def test_hole_preview_reaches_the_dragged_depth(self):
        lines=H.hole_ghost([0,0,10],[1,0,0],[0,1,0],[0,0,-1],6)(4)
        self.assertAlmostEqual(float(lines[1][0][2]),6);self.assertAlmostEqual(float(np.linalg.norm(lines[0][0][:2])),3)

    def test_wire_segments_chain_in_order_even_when_reversed(self):
        loop=H.chain_loop([[[0,0,0],[1,0,0]],[[1,1,0],[1,0,0]],[[1,1,0],[0,1,0]]])
        np.testing.assert_allclose(loop,[[0,0,0],[1,0,0],[1,1,0],[0,1,0]])


if __name__=='__main__':unittest.main()
