"""Linux/Windows differences: file replacement, settings location, native module names."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import platform_support
import build_renderer


class ReplaceFileTests(unittest.TestCase):
    def test_retries_a_briefly_locked_target_on_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'new';target=Path(folder)/'old';source.write_text('new');target.write_text('old')
            real=os.replace;calls=[]
            def flaky(a,b):
                calls.append(1)
                if len(calls)<3:raise PermissionError('locked by a virus scanner')
                real(a,b)
            with patch.object(platform_support,'WINDOWS',True),patch('platform_support.os.replace',flaky),patch('platform_support.time.sleep'):
                platform_support.replace_file(source,target)
            self.assertEqual(target.read_text(),'new');self.assertEqual(len(calls),3)

    def test_other_systems_do_not_hide_permission_errors(self):
        with patch.object(platform_support,'WINDOWS',False),patch('platform_support.os.replace',side_effect=PermissionError):
            with self.assertRaises(PermissionError):platform_support.replace_file('a','b')


class NativeModuleNameTests(unittest.TestCase):
    def test_windows_machine_names_map_to_the_shipped_dll(self):
        with patch.object(build_renderer,'WINDOWS',True),patch('build_renderer.platform.machine',return_value='AMD64'):
            path=build_renderer.library_path()
        self.assertEqual(path.suffix,'.dll');self.assertIn('-x86_64-',path.name)

    def test_crlf_checkout_has_the_same_digest(self):
        source=(build_renderer.ROOT/'native_raster.c').read_bytes()
        with patch.object(Path,'read_bytes',return_value=source.replace(b'\n',b'\r\n')):
            crlf=build_renderer.source_digest()
        self.assertEqual(crlf,build_renderer.source_digest())

    def test_prebuilt_windows_dll_matches_the_current_source(self):
        with patch.object(build_renderer,'WINDOWS',True),patch('build_renderer.platform.machine',return_value='AMD64'):
            path=build_renderer.library_path()
        if not (build_renderer.ROOT/'.native').exists() or not any((build_renderer.ROOT/'.native').glob('*.dll')):
            self.skipTest('Linux package without the Windows DLL')
        self.assertTrue(path.exists(),'Rebuild the DLL with build_windows_dll.sh after changing native_raster.c')


class LaunchHintTests(unittest.TestCase):
    def test_hints_name_the_right_launcher(self):
        with patch.object(platform_support,'WINDOWS',True):
            self.assertIn('SlothCAD.bat',platform_support.software_launch_hint())
        with patch.object(platform_support,'WINDOWS',False):
            self.assertIn('slothcad',platform_support.software_launch_hint())


if __name__=='__main__':unittest.main()
