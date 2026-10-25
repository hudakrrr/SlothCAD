import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication,QGroupBox,QScrollArea
from PySide6.QtCore import QSettings,QPointF,Qt
from PySide6.QtTest import QTest
from app import Window,CollapsibleSection
from geometry import entity,profile_regions,new_sketch,base_frame
from model import Document
class ReusableProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path.cwd());QSettings.setPath(QSettings.NativeFormat,QSettings.UserScope,cls.temp.name);cls.app=QApplication.instance() or QApplication([])
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_inner_rectangle_extrudes_after_outer_at_a_different_height(self):
        w=Window();s=new_sketch(base_frame('XY'));s['entities']=[entity('rectangle',center=[0,0],width=30,height=20),entity('rectangle',center=[0,0],width=10,height=6)]
        outer,inner=profile_regions(s)
        f=dict(kind='extrude',id='outer',name='Outer',depth=5,operation='add',signed_depth=True,source=dict(type='sketch',sketch=s['id'],entities=outer['entities'],profile_mode='nested'))
        w.doc=Document([s,f]);w.workspace.set_mode('model');w.refresh();self.assertEqual(w.scene_sketches(),[])
        w.start_extrude();self.assertEqual(len(w.scene_sketches()),1);w.workspace.align(s['frame'])
        hit=w.workspace.pick(QPointF(*w.workspace.project_local([[0,0]],s['frame'])[0]));self.assertEqual(hit['entities'],inner['entities'])
        w.extrusion_picked(hit);w.draft['depth']=8;w.apply_feature();self.assertAlmostEqual(w.doc.solid.val().Volume(),(600-60)*5+60*8)
        self.assertEqual(len(w.doc.sketches),1);self.assertEqual(len(s['entities']),2)
        w.hide();w.deleteLater();self.app.processEvents()
    def test_trim_click_and_undo_and_compact_sections(self):
        w=Window();w.show();w.support_picked(dict(type='plane',plane='XY'))
        for e in [entity('line',a=[-10,0],b=[10,0]),entity('line',a=[-3,-5],b=[-3,5]),entity('line',a=[3,-5],b=[3,5])]:w.add_entity(e)
        w.set_tool('trim');self.app.processEvents();pos=QPointF(*w.workspace.project_local([[0,0]],w.workspace.active_frame)[0]).toPoint()
        QTest.mouseClick(w.workspace,Qt.LeftButton,pos=pos);self.assertEqual(len(w.draft['entities']),4);w.undo();self.assertEqual(len(w.draft['entities']),3)
        groups=w.editor.findChildren(CollapsibleSection);self.assertTrue(any(g.title()=='Sketch settings' and not g.isChecked() for g in groups))
        self.assertEqual(w.timeline_scroll.height(),44);self.assertGreaterEqual(w.timeline_scroll.height(),w.timeline_buttons[0].height()+8 if w.timeline_buttons else 34)
        w.hide();w.deleteLater();self.app.processEvents()
