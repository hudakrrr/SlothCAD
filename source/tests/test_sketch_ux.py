import copy
import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window
from model import Document, new_feature
from geometry import entity, new_sketch, base_frame
from constraints import validate_constraints
from requirements import missing_inputs
from i18n import set_language


class SketchUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.language=patch('app.load_language',return_value='en');self.language.start()
        self.w=Window();self.w.resize(1100,800);self.w.show();self.app.processEvents()
        self.w.support_picked(dict(type='plane',plane='XY'));self.app.processEvents()
        self.auto=patch.object(Window,'auto_constraints_enabled',return_value=True);self.auto.start()

    def tearDown(self):
        self.auto.stop();self.w.hide();self.w.deleteLater();self.app.processEvents();self.language.stop();set_language('en')

    def kinds(self):return [c['kind'] for c in self.w.draft.get('constraints',[])]

    # ---- auto constraints -------------------------------------------------------------------
    def test_end_point_on_an_end_point_is_made_coincident(self):
        self.w.add_entity(entity('line',a=[0,5],b=[10,12]))
        self.w.add_entity(entity('line',a=[10,12],b=[20,3]))
        self.assertIn('coincident',self.kinds());validate_constraints(self.w.draft)

    def test_end_point_on_a_circle_or_line_becomes_point_on_object(self):
        self.w.add_entity(entity('circle',center=[0,0],radius=10))
        self.w.add_entity(entity('line',a=[10,0],b=[25,7]))
        self.assertIn('point_on_object',self.kinds())

    def test_near_horizontal_and_vertical_lines_become_exact(self):
        self.w.add_entity(entity('line',a=[3,4],b=[23,4.5]))
        self.assertIn('horizontal',self.kinds())
        line=self.w.draft['entities'][-1];self.assertAlmostEqual(line['a'][1],line['b'][1],places=7)
        self.w.add_entity(entity('line',a=[40,0],b=[40.3,20]))
        self.assertIn('vertical',self.kinds())
        self.w.add_entity(entity('line',a=[50,0],b=[60,20]))             # clearly slanted: left alone
        self.assertEqual(self.kinds().count('horizontal')+self.kinds().count('vertical'),2)

    def test_origin_is_joined(self):
        self.w.add_entity(entity('line',a=[0,0],b=[10,10]))
        refs=[r for c in self.w.draft['constraints'] if c['kind']=='coincident' for r in c['refs']]
        self.assertTrue(any(r.get('entity') is None and r.get('point')=='origin' for r in refs))

    def test_it_can_be_switched_off(self):
        self.auto.stop()
        with patch.object(Window,'auto_constraints_enabled',return_value=False):
            self.w.add_entity(entity('line',a=[0,0],b=[10,0.1]))
        self.assertEqual(self.kinds(),[])
        self.auto.start()

    def test_a_conflicting_inference_is_skipped_not_fatal(self):
        self.w.add_entity(entity('line',a=[0,5],b=[10,5]))
        self.w.add_entity(entity('line',a=[10,5],b=[10,25]))
        before=len(self.w.draft['entities'])
        self.w.add_entity(entity('line',a=[10,25],b=[0,5.01]))           # closes the triangle; end meets the first line's start
        self.assertEqual(len(self.w.draft['entities']),before+1);validate_constraints(self.w.draft)

    # ---- extend / offset / transform through the interface ---------------------------------------
    def test_extend_tool_runs_a_line_on_to_the_wall(self):
        self.auto.stop()
        with patch.object(Window,'auto_constraints_enabled',return_value=False):
            self.w.add_entity(entity('line',a=[0,0],b=[10,0]));self.w.add_entity(entity('line',a=[30,-10],b=[30,10]))
        self.w.set_tool('extend');self.app.processEvents()
        self.w.trim_entity(0,[9,0])
        self.assertEqual(self.w.draft['entities'][0]['b'],[30.,0.])
        self.auto.start()

    def test_offset_tool_creates_curves_and_undo_removes_them(self):
        self.auto.stop()
        with patch.object(Window,'auto_constraints_enabled',return_value=False):
            self.w.add_entity(entity('rectangle',center=[0,0],width=20,height=10))
        self.w.start_pattern('offset');self.app.processEvents()
        self.assertIn('offset_distance',self.w.widgets)
        self.w.workspace.pattern_selection={0};self.w.offset_distance=3.;self.w.apply_offset();self.app.processEvents()
        self.assertEqual(len(self.w.draft['entities']),1+4)
        xs=[v for e in self.w.draft['entities'][1:] for v in (e['a'][0],e['b'][0])];self.assertAlmostEqual(max(xs),13,places=5)
        self.w.undo();self.assertEqual(len(self.w.draft['entities']),1)
        self.auto.start()

    def test_transform_tool_moves_copies_and_rotates(self):
        self.auto.stop()
        with patch.object(Window,'auto_constraints_enabled',return_value=False):
            self.w.add_entity(entity('line',a=[0,0],b=[10,0]))
        self.w.start_pattern('transform');self.app.processEvents()
        self.w.workspace.pattern_selection={0}
        self.w.transform_mode='move';self.w.transform_dx=5;self.w.transform_dy=2;self.w.transform_copy=True;self.w.apply_transform()
        self.assertEqual(len(self.w.draft['entities']),2);self.assertEqual(self.w.draft['entities'][1]['a'],[5.,2.])
        self.w.workspace.pattern_selection={0};self.w.transform_mode='rotate';self.w.transform_copy=False;self.w.transform_angle=90;self.w.transform_cx=0;self.w.transform_cy=0
        self.w.apply_transform()
        np.testing.assert_allclose(self.w.draft['entities'][0]['b'],[0,10],atol=1e-9)
        self.auto.start()

    def test_ribbon_and_palette_offer_the_new_tools(self):
        for key in ('extend','offset'):self.assertIn(key,self.w.tool_buttons)
        tools={b.property('_tool') for b in self.w.draw_palette.buttons}
        self.assertTrue({'extend','offset','transform','trim'}<=tools)


class RequirementTests(unittest.TestCase):
    def test_each_tool_lists_what_it_still_needs(self):
        self.assertEqual(missing_inputs(dict(kind='revolve',source=None,axis=None)),['a profile to revolve','an axis'])
        self.assertEqual(missing_inputs(dict(kind='loft',sections=[1])),['at least two profiles, in order'])
        self.assertEqual(missing_inputs(dict(kind='loft',sections=[1,2])),[])
        self.assertTrue(missing_inputs(dict(kind='body_combine',targets=[1],tools=[])))
        self.assertTrue(missing_inputs(dict(kind='fillet',edge_refs=[])))
        self.assertEqual(missing_inputs(dict(kind='fillet',edge_refs=[{}])),[])
        self.assertTrue(missing_inputs(dict(kind='joint',moving=None)))
        self.assertTrue(missing_inputs(dict(kind='joint',moving='a',joint_type='mate')))
        self.assertEqual(missing_inputs(dict(kind='extrude')),[])        # extrusions have their own source check
        self.assertTrue(missing_inputs(dict(kind='feature_rectangular',targets=[],features=[],object_type='features')))

    def test_apply_is_disabled_until_the_selection_is_made(self):
        app=QApplication.instance() or QApplication([])
        with patch('app.load_language',return_value='en'):
            w=Window();w.show();app.processEvents()
            s=new_sketch(base_frame('XY'),'S')
            f=new_feature();f.update(width=20,height=10,depth=5,id='box1')
            w.doc=Document([f]);w.refresh(True);app.processEvents()
            w.start_body_tool('body_move');app.processEvents()
            self.assertFalse(w.widgets['missing_hint'].isHidden())
            self.assertIn('Still needed',w.widgets['missing_hint'].text())
            w.apply_feature();self.assertEqual(len(w.doc.features),1)       # nothing is applied, no dialog
            self.assertIn('Still needed',w.statusBar().currentMessage())
            w.hide();w.deleteLater();app.processEvents()


if __name__=='__main__':
    unittest.main()
