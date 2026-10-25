import os, sys, unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import struct
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app import Window
from spacemouse import Profile, shape_axes, to_motion


class SpaceMouseWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.lang=patch('app.load_language',return_value='en');self.lang.start()
        self.w=Window();self.w.show();self.app.processEvents()
        self.c=self.w.spacemouse
        from spacemouse import SpaceMouseController
        self.c.stop()

    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents();self.lang.stop()

    def test_controller_exists(self):
        self.assertIsNotNone(self.c);self.assertTrue(self.w.actions.get('SpaceMouse…'))

    def test_push_right_pans_and_twist_spins(self):
        ws=self.w.workspace;pan,yaw=ws.pan.copy(),ws.yaw
        self.c.profile.deadzone=0
        point=[[5.,5.,5.]];before=ws.project(point)[0][0].copy()
        ws.apply_navigation(dict(pan_x=1.,pan_y=0.,zoom=0.,tilt=0.,spin=0.),.1)
        self.assertGreater(ws.project(point)[0][0][0],before[0])
        ws.apply_navigation(dict(pan_x=0.,pan_y=0.,zoom=0.,tilt=0.,spin=1.),.1)
        self.assertNotEqual(ws.yaw,yaw)

    def test_zoom_and_pitch_limits(self):
        ws=self.w.workspace;zoom=ws.zoom
        ws.apply_navigation(dict(zoom=1.,tilt=50.),.1)
        self.assertGreater(ws.zoom,zoom);self.assertLessEqual(ws.pitch,90)

    def test_packet_to_motion(self):
        self.c.profile=Profile()
        self.c.feed_report(0xC62B,bytes([1])+struct.pack('<hhh',300,0,0))
        motion=to_motion(shape_axes(self.c.raw,self.c.profile),self.c.profile)
        self.assertGreater(motion['pan_x'],0)

    def test_button_runs_assigned_action(self):
        seen=[];self.c.actions['Fit view']=lambda:seen.append(1);self.c.profile.buttons={'2':'Fit view'}
        self.c.feed_buttons(0b10);self.assertEqual(seen,[1])

    def test_settings_dialog_without_device_does_not_crash(self):
        with patch('spacemouse_ui.QDialog.exec',return_value=0):self.w.spacemouse_settings()

    def test_axis_reverse_off_and_speed(self):
        p=Profile();p.deadzone=0;p.curve=1.
        base=shape_axes([200,200,0,0,0,0],p)
        p.axis_reverse[0]=True;p.axis_active[1]=False;p.axis_speed[0]=2.
        out=shape_axes([200,200,0,0,0,0],p)
        self.assertAlmostEqual(out[0],-2*base[0]);self.assertEqual(out[1],0.)
        again=Profile.from_json(p.to_json());self.assertEqual(again.axis_reverse,p.axis_reverse);self.assertEqual(again.axis_speed,p.axis_speed)

    def test_orbit_keeps_the_screen_centre_fixed_when_zoomed_in_and_panned(self):
        import numpy as np
        ws=self.w.workspace;ws.set_mode('model');ws.zoom=40.;ws.pan=np.array([120.,-60.])
        centre=np.array([ws.width()/2,ws.height()/2])
        # the world point that is at the middle of the screen (on the plane through the view centre)
        s=ws.scale();pivot=ws.center+ws.rotation().T@np.array([-ws.pan[0]/s,ws.pan[1]/s,0.])
        ws.apply_navigation(dict(tilt=.5,spin=.8),.1)
        after=ws.project([list(pivot)])[0][0]
        self.assertLess(float(np.linalg.norm(after-centre)),1.5)

    def test_fit_button_clicks_fit_by_default(self):
        seen=[];self.c.profile=Profile();self.c.actions['Fit view']=lambda:seen.append(1)
        self.c.feed_report(0xC631,bytes([3])+(1<<1).to_bytes(4,'little'))     # button 2 on the Pro Wireless
        self.assertEqual(seen,[1])

    def test_rotation_lock_and_rotate_only_exclude_each_other(self):
        self.c.toggle_rotation_lock();self.assertTrue(self.c.rotation_locked)
        self.c.toggle_rotate_only();self.assertTrue(self.c.rotate_only);self.assertFalse(self.c.rotation_locked)
        self.assertEqual((self.c.profile.buttons['27'],self.c.profile.buttons['9']),('Lock rotation','Turn 90°'))

    def test_turn_object_is_a_quarter_turn_clockwise_from_above(self):
        import numpy as np
        ws=self.w.workspace;ws.set_mode('model');ws.aligned=None;ws.finish_camera_animation()
        point=[[10.,0.,0.]];before=ws.project(point)[0][0]-np.array([ws.width()/2,ws.height()/2])
        ws.turn_object(90.);ws.finish_camera_animation()
        for _ in range(3):ws.turn_object(90.);ws.finish_camera_animation()
        full=ws.project(point)[0][0]-np.array([ws.width()/2,ws.height()/2])
        self.assertLess(float(np.linalg.norm(full-before)),1e-6)       # four quarter turns are a full circle


if __name__=='__main__':unittest.main()
