import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from model import Document, ModelError, new_feature
from geometry import new_sketch, base_frame, entity
from constraints import new_constraint, add_constraint, point_ref, line_ref


def box(width=40,height=30,depth=10):
    f=new_feature();f.update(width=width,height=height,depth=depth)
    return f


class ParameterTests(unittest.TestCase):
    def test_expression_field_follows_parameter_and_undo(self):
        feature=box();feature['expressions']={'depth':'thickness * 2'}
        d=Document([feature],parameters={'thickness':5})
        self.assertAlmostEqual(d.solid.val().Volume(),40*30*10,places=5)
        self.assertEqual(d.features[0]['depth'],10)
        d.set_parameters({'thickness':8})
        self.assertAlmostEqual(d.solid.val().Volume(),40*30*16,places=5)
        self.assertTrue(d.undo())
        self.assertEqual(d.parameters,{'thickness':5});self.assertAlmostEqual(d.solid.val().Volume(),40*30*10,places=5)
        self.assertTrue(d.redo())
        self.assertEqual(d.parameters,{'thickness':8});self.assertAlmostEqual(d.solid.val().Volume(),40*30*16,places=5)

    def test_parameters_can_reference_each_other_and_use_units(self):
        feature=box();feature['expressions']={'width':'base + 2 cm'}
        d=Document([feature],parameters={'base':'half * 2','half':15})
        self.assertAlmostEqual(d.features[0]['width'],50)

    def test_hand_edited_value_replaces_the_expression(self):
        feature=box();feature['expressions']={'depth':'t'}
        d=Document([feature],parameters={'t':4})
        edited=copy.deepcopy(d.features);edited[0]['depth']=7        # e.g. an arrow dragged in the viewport
        d.commit(edited)
        self.assertNotIn('expressions',d.features[0]);self.assertEqual(d.features[0]['depth'],7)
        d.set_parameters({'t':99})
        self.assertEqual(d.features[0]['depth'],7)

    def test_bad_parameter_tables_change_nothing(self):
        feature=box();feature['expressions']={'depth':'t'}
        d=Document([feature],parameters={'t':4})
        for bad in ({'t':'t + 1'},{'a':'b','b':'a'},{'1x':3},{'pi':3},{'t':'unknown_name * 2'}):
            with self.assertRaises(ModelError):d.preview(d.features,parameters=bad)
        with self.assertRaises(ModelError):d.set_parameters({'t':'nope'})
        self.assertEqual(d.parameters,{'t':4});self.assertEqual(d.features[0]['depth'],4)

    def test_parameter_that_breaks_the_model_is_reported_and_kept_out(self):
        feature=box();feature['expressions']={'depth':'t'}
        d=Document([feature],parameters={'t':4})
        with self.assertRaises(ModelError):d.set_parameters({'t':0})        # zero depth is not buildable
        self.assertEqual(d.parameters,{'t':4})

    def test_unknown_name_in_a_feature_is_a_feature_error(self):
        feature=box();feature['expressions']={'depth':'missing'}
        with self.assertRaises(ModelError) as raised:Document([feature])
        self.assertIn('missing',str(raised.exception))

    def test_save_load_round_trip_and_dirty_marker(self):
        feature=box();feature['expressions']={'depth':'t'}
        d=Document([feature],parameters={'t':6})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'p.fcad';d.save(path)
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['parameters'],{'t':6});self.assertEqual(data['version'],10)
            loaded=Document.load(path)
            self.assertEqual(loaded.parameters,{'t':6});self.assertFalse(loaded.parameters_dirty())
            loaded.set_parameters({'t':3});self.assertTrue(loaded.parameters_dirty())
            loaded.save(path);self.assertFalse(loaded.parameters_dirty())
            self.assertTrue((Path(folder)/'p.fcad.bak').exists())      # the previous save is kept
            self.assertEqual(json.loads((Path(folder)/'p.fcad.bak').read_text(encoding='utf-8'))['parameters'],{'t':6})

    def test_old_files_without_parameters_still_load(self):
        d=Document([box()])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.fcad';d.save(path)
            data=json.loads(path.read_text(encoding='utf-8'));data['version']=9;data.pop('parameters',None)
            path.write_text(json.dumps(data),encoding='utf-8')
            self.assertEqual(Document.load(path).parameters,{})

    def test_sketch_dimension_uses_document_parameter(self):
        sketch=new_sketch(base_frame('XY'),'S')
        line=entity('line',a=[0,0],b=[10,0]);sketch['entities']=[line]
        from expressions import using_parameters
        from constraints import solve
        with using_parameters({'span':60}):
            constraint=new_constraint(sketch,'dimension',[line_ref(line['id'])],10.,'length',expression='span / 2',name='len')
            sketch['constraints']=[constraint]
            solved=solve(sketch)
        a,b=np.asarray(solved['entities'][0]['a']),np.asarray(solved['entities'][0]['b'])
        self.assertAlmostEqual(float(np.linalg.norm(b-a)),30.,places=5)

    def test_preview_memo_distinguishes_parameter_tables(self):
        feature=box();feature['expressions']={'depth':'t'}
        d=Document([feature],parameters={'t':4})
        a=d.preview(d.features,parameters={'t':2})[0].val().Volume()
        b=d.preview(d.features,parameters={'t':5})[0].val().Volume()
        self.assertAlmostEqual(a,40*30*2,places=5);self.assertAlmostEqual(b,40*30*5,places=5)


if __name__=='__main__':
    unittest.main()
