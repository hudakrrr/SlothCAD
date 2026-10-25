"""Several projects at once: welcome page, tabs in the menu bar, copy/paste between projects."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app import Window
from geometry import entity


class ProjectTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.w=Window(start_with_project=False);self.w.resize(1300,860);self.w.show();self.app.processEvents()
        self.w.error=lambda e,*a:self.fail(str(e))
    def tearDown(self):
        self.w.hide();self.w.deleteLater();self.app.processEvents()
    def sketch(self):
        w=self.w;w.start_sketch();w.support_picked({'type':'plane','plane':'XY'});self.app.processEvents()
        w.draft['entities']=[entity('rectangle',center=[0.,0.],width=20.,height=10.)];w.workspace.active=w.draft;w.show_editor();w.finish_sketch();self.app.processEvents()

    def test_starts_with_the_welcome_page(self):
        self.assertEqual(self.w.sessions,[]);self.assertIs(self.w.stack.currentWidget(),self.w.welcome)
        self.assertTrue(self.w.ribbon_container.isVisible());self.assertFalse(self.w.ribbon_container.isEnabled())

    def test_tabs_live_in_the_menu_bar_without_growing_it(self):
        height=self.w.menu_bar.height();self.w.blank();self.app.processEvents()
        self.assertIs(self.w.tab_row.parentWidget(),self.w.menu_bar);self.assertEqual(self.w.menu_bar.height(),height)
        self.assertEqual(self.w.tabs.count(),1)

    def test_two_projects_keep_their_own_content_and_features_copy_across(self):
        w=self.w;w.blank();self.sketch();self.assertEqual(len(w.doc.features),1)
        w.selected=0;self.assertTrue(w.copy_features())
        w.blank();self.app.processEvents()
        self.assertEqual(len(w.sessions),2);self.assertEqual(len(w.doc.features),0)
        self.assertTrue(w.paste_features());self.assertEqual(len(w.doc.features),1)
        w.tabs.setCurrentIndex(0);self.app.processEvents()
        self.assertEqual(len(w.doc.features),1)
        self.assertNotEqual(w.sessions[0]['doc'] is w.doc,w.sessions[1]['doc'] is w.doc)

    def test_closing_the_last_tab_returns_to_the_welcome_page(self):
        w=self.w;w.blank();w.close_session(w.session_id);self.app.processEvents()
        self.assertEqual(w.sessions,[]);self.assertIs(w.stack.currentWidget(),w.welcome)


if __name__=='__main__':unittest.main()
