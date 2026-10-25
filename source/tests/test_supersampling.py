import unittest
from unittest.mock import patch
from types import SimpleNamespace
from gpu_renderer import supersample_size,GpuRenderer
class SupersamplingTests(unittest.TestCase):
    def test_physical_size_doubles_each_dimension(self):
        self.assertEqual(supersample_size(1000,700,8192),(2000,1400));self.assertEqual(supersample_size(600,400,8192),(2400,1600))
    def test_large_viewport_and_texture_limits_skip_expensive_buffer(self):
        self.assertIsNone(supersample_size(4000,3000,16384));self.assertIsNone(supersample_size(1500,1000,2048))
    def test_framebuffer_reused_at_same_size(self):
        r=object.__new__(GpuRenderer);r.gl=SimpleNamespace(glGetIntegerv=lambda e:8192);r.supersample_key=(2000,1400);r.supersample_fbo=object()
        with patch('gpu_renderer.QOpenGLFramebufferObject',side_effect=AssertionError('Reallocated framebuffer')):self.assertIs(r.supersample_target(1000,700),r.supersample_fbo)
