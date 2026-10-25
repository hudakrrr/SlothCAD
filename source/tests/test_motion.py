import math
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from unittest.mock import patch
from PySide6.QtCore import Qt,QPointF,QEvent
from PySide6.QtGui import QMouseEvent,QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from workspace import Workspace
from geometry import base_frame,new_sketch,entity

class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.w=Workspace();self.w.resize(600,400);self.w.set_mode('model')
    def tearDown(self):self.w.motion_timer.stop();self.w.deleteLater();self.app.processEvents()
    def start(self,button):
        self.w.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress,QPointF(100,100),QPointF(100,100),button,button,Qt.NoModifier))
    def release(self,point,button):
        self.w.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease,point,point,button,Qt.NoButton,Qt.NoModifier))
    def test_fast_orbit_burst_applies_only_latest_position_with_full_distance(self):
        self.start(Qt.LeftButton);yaw=self.w.yaw;pitch=self.w.pitch
        with patch.object(self.w,'update') as update:
            for i in range(1000):self.w.queue_motion(QPointF(100+i*.1,110),Qt.LeftButton)
            self.assertEqual(update.call_count,0);self.assertEqual(self.w.motion_batches,0)
            self.w.flush_motion()
            self.assertEqual(update.call_count,1);self.assertEqual(self.w.motion_batches,1)
        self.assertAlmostEqual(self.w.yaw,(yaw+99.9*.5)%360);self.assertAlmostEqual(self.w.pitch,pitch+5)
        self.assertIsNone(self.w.pending_motion);self.assertFalse(self.w.motion_timer.isActive())
    def test_release_flushes_last_pan_position_and_cancels_delayed_work(self):
        self.start(Qt.RightButton)
        for i in range(100):self.w.queue_motion(QPointF(100+i,150),Qt.RightButton)
        self.release(QPointF(210,160),Qt.RightButton)
        np.testing.assert_array_equal(self.w.pan,[110,60]);self.assertIsNone(self.w.last)
        self.assertFalse(self.w.motion_timer.isActive());batches=self.w.motion_batches
        QTest.qWait(30);self.assertEqual(self.w.motion_batches,batches)
    def test_hover_burst_picks_once_at_latest_point(self):
        self.w.set_mode('support')
        with patch.object(self.w,'pick',return_value=None) as pick:
            for i in range(1000):self.w.queue_motion(QPointF(i%600,200),Qt.NoButton)
            pick.assert_not_called();self.w.flush_motion();pick.assert_called_once_with(QPointF(399,200))
    def test_pan_does_not_pick_and_fast_out_and_back_is_not_a_click(self):
        self.w.set_mode('support');self.start(Qt.LeftButton)
        self.w.queue_motion(QPointF(300,100),Qt.LeftButton)
        with patch.object(self.w,'pick') as pick:
            self.release(QPointF(100,100),Qt.LeftButton);pick.assert_not_called()
        self.start(Qt.RightButton)
        with patch.object(self.w,'pick') as pick:
            self.w.queue_motion(QPointF(300,100),Qt.RightButton);self.w.flush_motion();pick.assert_not_called()
        np.testing.assert_array_equal(self.w.pan,[200,0])
    def test_sketch_snap_runs_once_and_click_uses_exact_current_position(self):
        frame=base_frame('XY');sketch=new_sketch(frame);self.w.set_mode('sketch',sketch,frame)
        with patch.object(self.w,'snap_at',return_value=np.array([4.,5.])) as snap:
            for i in range(1000):self.w.queue_motion(QPointF(i%600,200),Qt.NoButton)
            snap.assert_not_called();self.w.flush_motion();snap.assert_called_once()
        np.testing.assert_array_equal(self.w.cursor,[4,5])
    def test_timer_consumes_latest_position_without_followup_input(self):
        self.start(Qt.RightButton);self.w.queue_motion(QPointF(175,125),Qt.RightButton)
        # The 16 ms timer fires on its own; wait for it instead of assuming a fixed delay.
        for _ in range(40):
            if self.w.motion_batches:break
            QTest.qWait(10)
        np.testing.assert_array_equal(self.w.pan,[75,25]);self.assertEqual(self.w.motion_batches,1)
    def test_small_slow_pan_steps_preserve_total_distance(self):
        self.start(Qt.RightButton)
        for i in range(1,11):self.w.queue_motion(QPointF(100+i,100+i),Qt.RightButton);self.w.flush_motion()
        np.testing.assert_array_equal(self.w.pan,[10,10]);self.assertTrue(self.w.drag)
    def test_motion_status_repeats_do_not_repaint_statusbar(self):
        messages=[];self.w.message.connect(messages.append)
        for _ in range(1000):self.w.motion_status('same face')
        self.assertEqual(messages,['same face'])
    def test_wheel_burst_accumulates_delta_without_per_event_redraw(self):
        from PySide6.QtCore import QPoint
        with patch.object(self.w,'update') as update:
            for _ in range(10):
                event=QWheelEvent(QPointF(200,200),QPointF(200,200),QPoint(),QPoint(0,12),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
                self.w.wheelEvent(event)
            self.assertEqual(update.call_count,0);self.w.flush_motion();self.assertEqual(update.call_count,1)
        self.assertAlmostEqual(self.w.zoom,1.15)

    def test_zoom_has_no_old_point05_to_30_barrier_and_grid_tracks_scale(self):
        self.w.zoom=1.;self.w.pending_zoom=100.;self.w.flush_motion();self.assertGreater(self.w.zoom,30.)
        fine=self.w.adaptive_grid_step(22);self.w.zoom=1.;self.w.pending_zoom=-100.;self.w.flush_motion();self.assertLess(self.w.zoom,.05)
        coarse=self.w.adaptive_grid_step(22);self.assertGreater(coarse,fine)
    def test_grid_uses_one_readable_engineering_spacing(self):
        for zoom in (.01,.1,1.,10.,100.):
            self.w.zoom=zoom;step=self.w.adaptive_grid_step(22)
            self.assertGreaterEqual(step*self.w.scale(),22-1e-9)
            mantissa=step/10**math.floor(math.log10(step))
            self.assertTrue(any(abs(mantissa-value)<1e-8 for value in (1,2,5,10)))

    def test_horizontal_orbit_is_reversed_in_both_directions(self):
        self.start(Qt.LeftButton);yaw=self.w.yaw
        self.w.queue_motion(QPointF(140,100),Qt.LeftButton);self.w.flush_motion()
        self.assertAlmostEqual(self.w.yaw,(yaw+20)%360)
        self.w.queue_motion(QPointF(60,100),Qt.LeftButton);self.w.flush_motion()
        self.assertAlmostEqual(self.w.yaw,(yaw-20)%360)
