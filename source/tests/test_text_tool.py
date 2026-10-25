"""Sketch text: text boxes laid out like a document, live outline, panel settings, placing."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication, QPlainTextEdit

import text_tool as T
from app import Window
from model import Document
from geometry import profile_regions


def bounds(layout):
    pts = np.vstack(layout.loops)
    return pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()


def style(**kw):
    base = dict(text='Hello World', font=T.default_font(), size_pt=24.)
    base.update(kw)
    return T.TextStyle.from_dict(base)


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_text_becomes_closed_loops_inside_the_box(self):
        lay = T.layout_text(style(), (0, 0, 120, 30))
        self.assertGreater(len(lay.loops), 5)
        x0, x1, y0, y1 = bounds(lay)
        self.assertGreaterEqual(x0, -.5); self.assertLessEqual(x1, 120.5)
        self.assertGreaterEqual(y0, -.5); self.assertLessEqual(y1, 30.5)
        self.assertFalse(lay.overflow_x or lay.overflow_y)
        self.assertTrue(all(len(loop) >= 3 for loop in lay.loops))

    def test_horizontal_alignment(self):
        rect = (0, 0, 150, 30)
        left = bounds(T.layout_text(style(halign='left'), rect))
        center = bounds(T.layout_text(style(halign='center'), rect))
        right = bounds(T.layout_text(style(halign='right'), rect))
        self.assertLess(left[0], 2.5)                       # starts at the left edge
        self.assertAlmostEqual((center[0] + center[1]) / 2, 75., delta=2.5)
        self.assertGreater(right[1], 150 - 2.5)             # ends at the right edge
        self.assertLess(left[1], center[1]); self.assertLess(center[1], right[1])

    def test_vertical_alignment(self):
        rect = (0, 0, 150, 60)
        top = bounds(T.layout_text(style(valign='top'), rect))
        middle = bounds(T.layout_text(style(valign='middle'), rect))
        bottom = bounds(T.layout_text(style(valign='bottom'), rect))
        self.assertGreater(top[3], 60 - 4)
        self.assertAlmostEqual((middle[2] + middle[3]) / 2, 30., delta=4.)
        self.assertLess(bottom[2], 4)
        self.assertGreater(top[2], middle[2]); self.assertGreater(middle[2], bottom[2])

    def test_size_in_points_scales_the_outline(self):
        small = bounds(T.layout_text(style(size_pt=12.), (0, 0, 200, 50)))
        large = bounds(T.layout_text(style(size_pt=48.), (0, 0, 400, 100)))
        ratio = (large[1] - large[0]) / (small[1] - small[0])
        self.assertAlmostEqual(ratio, 4., delta=.15)
        # Cap height of 24 pt text is about 17 pt = 6 mm.
        cap = bounds(T.layout_text(style(text='H', size_pt=24.), (0, 0, 50, 30)))
        self.assertAlmostEqual(cap[3] - cap[2], 24 * T.PT_MM * .72, delta=1.2)

    def test_wrapping_and_overflow(self):
        long = style(text='The quick brown fox jumps over the lazy dog', size_pt=18.)
        wrapped = T.layout_text(long, (0, 0, 60, 80))
        self.assertGreater(wrapped.lines, 2)
        self.assertLessEqual(bounds(wrapped)[1], 60.5)
        self.assertFalse(wrapped.overflow_x)
        unwrapped = T.layout_text(T.TextStyle.from_dict({**long.to_dict(), 'wrap': False}), (0, 0, 60, 80))
        self.assertEqual(unwrapped.lines, 1)
        self.assertTrue(unwrapped.overflow_x)
        tiny_box = T.layout_text(long, (0, 0, 60, 5))
        self.assertTrue(tiny_box.overflow_y)

    def test_explicit_line_breaks_and_spacing(self):
        two = T.layout_text(style(text='AB\nCD'), (0, 0, 100, 60))
        self.assertEqual(two.lines, 2)
        tight = T.layout_text(style(text='AB\nCD', spacing=1.0), (0, 0, 100, 60)).height
        loose = T.layout_text(style(text='AB\nCD', spacing=2.0), (0, 0, 100, 60)).height
        self.assertGreater(loose, tight * 1.4)

    def test_justify_fills_the_box_width_except_the_last_line(self):
        text = 'one two three four five six seven eight nine ten eleven twelve'
        lay = T.layout_text(style(text=text, size_pt=14., halign='justify'), (0, 0, 70, 80))
        self.assertGreater(lay.lines, 2)
        self.assertLessEqual(bounds(lay)[1], 70.5)
        # The first line reaches the right edge although its words do not fill it naturally.
        rows = {}
        for loop in lay.loops:
            rows.setdefault(round(float(loop[:, 1].max()) / 3), []).append(float(loop[:, 0].max()))
        first_row = rows[max(rows)]
        self.assertGreater(max(first_row), 70 - 3.5)

    def test_underline_adds_a_bar_and_empty_text_gives_nothing(self):
        plain = T.layout_text(style(text='ab'), (0, 0, 60, 20))
        underlined = T.layout_text(style(text='ab', underline=True), (0, 0, 60, 20))
        self.assertLess(bounds(underlined)[2], bounds(plain)[2] + 1e-9)
        self.assertEqual(T.layout_text(style(text='   '), (0, 0, 60, 20)).loops, [])

    def test_bad_settings_are_rejected(self):
        for bad in (dict(size_pt=0), dict(spacing=0), dict(halign='diagonal'), dict(valign='sideways')):
            with self.assertRaises(ValueError):
                T.layout_text(style(**bad), (0, 0, 10, 10))

    def test_rect_corners_may_be_given_in_any_order(self):
        a = bounds(T.layout_text(style(), (0, 0, 100, 30)))
        b = bounds(T.layout_text(style(), (100, 30, 0, 0)))
        np.testing.assert_allclose(a, b, atol=1e-9)

    def test_text_extrudes_like_any_sketch_geometry(self):
        lay = T.layout_text(style(text='Ho', size_pt=36.), (0, 0, 60, 30))
        from geometry import new_sketch, base_frame, identifier
        sketch = new_sketch(base_frame('XY'))
        sketch['entities'] = T.polygon_entities(lay)
        regions = profile_regions(sketch)
        self.assertGreaterEqual(len(regions), 2)
        # 'o' is a ring: a region with a hole.
        self.assertTrue(any(r['holes'] for r in regions))
        region = max(regions, key=lambda r: len(r['entities']))
        feature = dict(kind='extrude', id=identifier(), name='Extrude', enabled=True, depth=3., operation='add',
                       source=dict(type='sketch', sketch=sketch['id'], entities=region['entities'], holes=region['holes']))
        doc = Document([sketch, feature])
        self.assertGreater(doc.solid.val().Volume(), 10.)


class TextToolUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Window(); self.errors = []; self.w.error = self.errors.append
        self.w.show(); self.app.processEvents(); self.w.workspace.snap_enabled = False
        self.w.doc = Document([]); self.w.refresh(); self.w.start_sketch()
        self.w.support_picked({'type': 'plane', 'plane': 'XY'}); self.app.processEvents()
        self.ws = self.w.workspace

    def tearDown(self):
        self.w.draft = None; self.w.hide(); self.w.deleteLater(); self.app.processEvents()
        self.assertEqual(self.errors, [])

    def draw_box(self, a=(0., 0.), b=(100., 40.)):
        self.w.start_text_tool()
        self.assertEqual(self.ws.tool, 'text')
        self.ws.draw_point(np.array(a)); self.ws.draw_point(np.array(b)); self.app.processEvents()

    def test_two_clicks_make_a_text_box_with_a_panel_and_live_outline(self):
        self.draw_box()
        self.assertIsNotNone(self.w.text_draft)
        self.assertEqual(self.w.text_draft['rect'], [0., 0., 100., 40.])
        self.assertIsNotNone(self.ws.text_box)
        self.assertGreater(len(self.ws.text_box['loops']), 3)
        for key in ('text_content', 'text_font', 'text_size', 'text_bold', 'text_italic', 'text_underline', 'text_spacing',
                    'text_wrap', 'text_box_x', 'text_box_y', 'text_box_w', 'text_box_h', 'text_halign_left',
                    'text_halign_center', 'text_halign_right', 'text_halign_justify', 'text_valign_top',
                    'text_valign_middle', 'text_valign_bottom', 'text_readout'):
            self.assertIn(key, self.w.widgets, key)
        self.assertEqual(self.w.draft['entities'], [])        # nothing is in the sketch yet

    def test_box_too_small_is_rejected(self):
        self.w.start_text_tool()
        self.ws.draw_point(np.array([0., 0.])); self.ws.draw_point(np.array([0., 5.])); self.app.processEvents()
        self.assertIsNone(self.w.text_draft)

    def test_settings_update_the_outline_live(self):
        self.draw_box()
        before = np.vstack(self.ws.text_box['loops'])
        self.w.widgets['text_size'].setValue(48.); self.app.processEvents()
        after = np.vstack(self.ws.text_box['loops'])
        self.assertGreater(np.ptp(after[:, 0]), np.ptp(before[:, 0]) * 1.5)
        count = len(self.ws.text_box['loops'])
        self.w.widgets['text_content'].setPlainText('Different'); self.app.processEvents()
        self.assertEqual(self.w.text_draft['style']['text'], 'Different')
        self.assertNotEqual(len(self.ws.text_box['loops']), count)   # 'Different' has other letters than 'Text'
        self.assertGreater(len(self.ws.text_box['loops']), 0)

    def test_alignment_buttons_move_the_text_inside_the_box(self):
        self.draw_box((0., 0.), (160., 60.))
        self.w.widgets['text_size'].setValue(20.); self.app.processEvents()
        spans = {}
        for name in ('left', 'center', 'right'):
            self.w.widgets[f'text_halign_{name}'].click(); self.app.processEvents()
            pts = np.vstack(self.ws.text_box['loops']); spans[name] = (pts[:, 0].min(), pts[:, 0].max())
        self.assertLess(spans['left'][0], 3)
        self.assertAlmostEqual(sum(spans['center']) / 2, 80., delta=3)
        self.assertGreater(spans['right'][1], 157)
        heights = {}
        for name in ('top', 'middle', 'bottom'):
            self.w.widgets[f'text_valign_{name}'].click(); self.app.processEvents()
            pts = np.vstack(self.ws.text_box['loops']); heights[name] = (pts[:, 1].min() + pts[:, 1].max()) / 2
        self.assertGreater(heights['top'], heights['middle']); self.assertGreater(heights['middle'], heights['bottom'])

    def test_box_fields_move_and_resize_the_box(self):
        self.draw_box()
        self.w.widgets['text_box_w'].setValue(50.); self.w.widgets['text_box_x'].setValue(10.); self.app.processEvents()
        x0, y0, x1, y1 = self.w.text_draft['rect']
        self.assertAlmostEqual(x0, 10.); self.assertAlmostEqual(x1 - x0, 50.); self.assertAlmostEqual(y1 - y0, 40.)
        self.assertEqual(self.ws.text_box['rect'], [x0, y0, x1, y1])

    def test_overflow_is_reported(self):
        self.draw_box((0., 0.), (30., 10.))
        self.w.widgets['text_content'].setPlainText('A rather long sentence that cannot fit'); self.app.processEvents()
        self.assertTrue(self.ws.text_box['overflow'])
        self.assertIn('⚠', self.w.widgets['text_readout'].text())

    def test_fit_box_to_text(self):
        self.draw_box((0., 0.), (200., 100.))
        self.w.widgets['text_wrap'].setChecked(False); self.w.text_fit_box(); self.app.processEvents()
        x0, y0, x1, y1 = self.w.text_draft['rect']
        info = self.w.text_info
        self.assertAlmostEqual(x1 - x0, info.width, delta=.01)
        self.assertAlmostEqual(y1 - y0, info.height, delta=.01)
        self.assertAlmostEqual(y1, 100., delta=1e-6)          # the top-left corner stays
        self.assertFalse(self.ws.text_box['overflow'])

    def test_place_text_adds_polygons_and_is_undoable(self):
        self.draw_box()
        self.w.apply_text(); self.app.processEvents()
        entities = self.w.draft['entities']
        self.assertGreater(len(entities), 3)
        self.assertTrue(all(e['kind'] == 'polygon' for e in entities))
        self.assertIsNone(self.w.text_draft); self.assertIsNone(self.ws.text_box)
        self.assertEqual(self.ws.tool, 'text')                # ready for the next box
        self.assertGreater(len(self.w.sketch_undo), 0)            # one undo step restores the empty sketch
        self.assertEqual(self.w.sketch_undo[-1]['entities'], [])

    def test_the_last_style_is_offered_for_the_next_box(self):
        self.draw_box()
        self.w.widgets['text_size'].setValue(33.); self.w.widgets['text_bold'].setChecked(True)
        self.w.widgets['text_halign_center'].click(); self.app.processEvents()
        self.w.apply_text()
        self.ws.draw_point(np.array([0., 50.])); self.ws.draw_point(np.array([80., 90.])); self.app.processEvents()
        style = self.w.text_draft['style']
        self.assertEqual(style['size_pt'], 33.); self.assertTrue(style['bold']); self.assertEqual(style['halign'], 'center')

    def test_escape_cancels_and_places_nothing(self):
        self.draw_box()
        self.assertTrue(self.w.escape_pressed())
        self.assertIsNone(self.w.text_draft); self.assertEqual(self.w.draft['entities'], [])
        self.assertEqual(self.ws.tool, 'text')

    def test_enter_in_a_number_box_places_but_enter_in_the_text_edits_a_new_line(self):
        self.draw_box()
        edit = self.w.widgets['text_content']
        self.assertIsInstance(edit, QPlainTextEdit)
        self.assertFalse(self.w.enter_pressed(edit))           # newline stays with the editor
        self.assertIsNotNone(self.w.text_draft)
        self.assertTrue(self.w.enter_pressed(self.w.widgets['text_size']))
        self.assertIsNone(self.w.text_draft); self.assertGreater(len(self.w.draft['entities']), 3)

    def test_switching_tools_and_finishing_keep_a_typed_text(self):
        self.draw_box()
        self.w.set_tool('line')
        self.assertIsNone(self.w.text_draft); self.assertGreater(len(self.w.draft['entities']), 3)
        self.w.set_tool('text')
        self.ws.draw_point(np.array([0., 50.])); self.ws.draw_point(np.array([80., 90.])); self.app.processEvents()
        placed = len(self.w.draft['entities'])
        self.assertTrue(self.w.finish_sketch())
        sketch = [f for f in self.w.doc.features if f['kind'] == 'sketch'][0]
        self.assertGreater(len(sketch['entities']), placed)

    def test_blank_text_is_not_placed(self):
        self.draw_box()
        self.w.widgets['text_content'].setPlainText('   '); self.app.processEvents()
        self.assertEqual(self.ws.text_box['loops'], [])
        self.w.apply_text()
        self.assertEqual(len(self.errors), 1)                  # "Text cannot be empty."
        self.errors.clear()
        self.assertEqual(self.w.draft['entities'], [])

    def test_a_second_box_cannot_start_while_one_is_open(self):
        self.draw_box()
        self.ws.draw_point(np.array([200., 0.])); self.app.processEvents()
        self.assertEqual(self.ws.points, [])
        self.assertEqual(self.w.text_draft['rect'], [0., 0., 100., 40.])


if __name__ == '__main__':
    unittest.main()
