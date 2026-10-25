"""The bundled icon pack (Iconoir based) covers every tool and is picked up by icon()."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
import tool_help
import ui_icons

PACK=Path(__file__).resolve().parent.parent/'assets'/'icons'


class IconPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_every_tool_has_a_light_and_a_dark_icon(self):
        missing=[k for k in tool_help.HELP if not (PACK/(k+'.png')).exists() or not (PACK/(k+'-dark.png')).exists()]
        self.assertEqual(missing,[])
    def test_license_of_the_third_party_icons_is_shipped(self):
        self.assertTrue((PACK/'LICENSE-Iconoir.txt').exists())
        self.assertTrue((PACK.parent.parent.parent/'THIRD-PARTY-NOTICES.md').exists())
    def test_icon_uses_the_pack_when_it_is_active(self):
        old=os.environ.get('SLOTHCAD_ICON_DIR');os.environ['SLOTHCAD_ICON_DIR']=str(PACK)
        try:
            ui_icons._pack_icon.cache_clear()
            icon=ui_icons.icon('extrude');self.assertFalse(icon.isNull())
            self.assertNotEqual(type(icon.availableSizes()),type(None))
            self.assertTrue(icon.availableSizes())      # a bitmap icon has fixed sizes; the vector engine has none
        finally:
            if old is None:os.environ.pop('SLOTHCAD_ICON_DIR',None)
            else:os.environ['SLOTHCAD_ICON_DIR']=old
            ui_icons._pack_icon.cache_clear()
    def test_switch_off(self):
        old=os.environ.get('SLOTHCAD_ICON_DIR');os.environ['SLOTHCAD_ICON_DIR']='none'
        try:self.assertEqual(ui_icons.pack_folders(),[])
        finally:
            if old is None:os.environ.pop('SLOTHCAD_ICON_DIR',None)
            else:os.environ['SLOTHCAD_ICON_DIR']=old


if __name__=='__main__':unittest.main()
