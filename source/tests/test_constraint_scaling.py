import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from geometry import entity, new_sketch, base_frame
from constraints import new_constraint, solve, drag, validate_constraints, line_ref, point_ref, Layout, SPARSE_FROM


class LargeSketchTests(unittest.TestCase):
    def chain(self,count):
        lines=[entity('line',a=[i*10,0.],b=[i*10+9,3.+(i%3)]) for i in range(count)]
        sketch=new_sketch(base_frame('XY'));sketch['entities']=lines;constraints=sketch.setdefault('constraints',[])
        for e in lines:constraints.append(new_constraint(sketch,'horizontal',[line_ref(e['id'])]))
        for a,b in zip(lines[:-1],lines[1:]):
            constraints.append(new_constraint(sketch,'coincident',[point_ref(a['id'],'b'),point_ref(b['id'],'a')]))
        for e in lines:constraints.append(new_constraint(sketch,'dimension',[line_ref(e['id'])],8.,'length'))
        return sketch,lines

    def test_long_chain_solves_exactly_and_quickly(self):
        sketch,lines=self.chain(50)
        self.assertGreaterEqual(len(Layout(lines).x),SPARSE_FROM)        # exercises the grouped-Jacobian path
        started=time.perf_counter();solved=solve(sketch);elapsed=time.perf_counter()-started
        validate_constraints(solved)
        for e in solved['entities']:
            self.assertAlmostEqual(float(np.linalg.norm(np.asarray(e['b'])-np.asarray(e['a']))),8.,places=5)
            self.assertAlmostEqual(e['a'][1],e['b'][1],places=6)
        self.assertLess(elapsed,5.)

    def test_dragging_a_long_chain_keeps_every_relation(self):
        sketch,lines=self.chain(50);solved=solve(sketch)
        moved=drag(solved,point_ref(lines[10]['id'],'b'),[100.,5.])
        validate_constraints(moved)


if __name__=='__main__':
    unittest.main()
