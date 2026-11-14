"""A top title owns its adjacent diagram without moving captions or labels."""
import copy
import unittest
from unittest.mock import patch

import pdf_new_concept_v02_regions as layout


def visual(box=(.30, .01, .98, .95)):
    return {'bbox': list(box), 'text': '', 'kind': 'visual', 'hasVisual': True,
            'visualKinds': ['raster'], 'wordIds': []}


def title(text='시각 전도로', box=(.03, .04, .24, .095), kind='heading', size=28):
    return {'bbox': list(box), 'text': text, 'kind': kind, 'hasVisual': False,
            'fontSize': size, 'wordIds': ['title-word']}


class PanelTitleOrderTests(unittest.TestCase):
    def order(self, blocks, zones=None):
        return layout.order_panel_titles(blocks, zones or [[0, 0, 1, 1]])

    def test_adjacent_large_diagram_follows_its_existing_top_heading(self):
        image, heading = visual(), title()
        before = copy.deepcopy([image, heading])
        result = self.order([image, heading])
        self.assertEqual(result, [heading, image])
        self.assertEqual([image, heading], before)

    def test_only_large_native_title_can_be_promoted_without_a_body_font(self):
        image, heading = visual(), title(kind='text')
        result = self.order([image, heading])
        self.assertIs(result[0], heading)
        self.assertEqual(heading['kind'], 'heading')
        self.assertTrue(heading['localTitleRecovered'])
        self.assertEqual(heading['bbox'], [.03, .04, .24, .095])
        self.assertEqual(heading['wordIds'], ['title-word'])

    def test_fragment_ids_are_assigned_after_title_recovery_with_no_word_loss(self):
        class Page:
            width = height = 1000

        words = [{'text': '시각', 'x0': 30, 'top': 40, 'x1': 120, 'bottom': 92,
                  'size': 28, 'fontname': 'regular'},
                 {'text': '전도로', 'x0': 125, 'top': 40, 'x1': 240, 'bottom': 92,
                  'size': 28, 'fontname': 'regular'}]
        with patch.object(layout, 'repaired_textmap', return_value=(None, [], {})), \
             patch('pdfplumber.utils.extract_words', return_value=copy.deepcopy(words)), \
             patch.object(layout, 'page_zones', return_value=[[0, 0, 1, 1]]), \
             patch.object(layout, 'image_regions', return_value=[{'bbox': [.3, .01, .98, .95], 'kind': 'raster'}]), \
             patch.object(layout, 'table_regions', return_value=[]), \
             patch.object(layout, 'vector_regions', return_value=[]):
            first, native = layout.fragment_page(Page(), {'number': 6, 'nativeText': '시각 전도로'})
            second, _ = layout.fragment_page(Page(), {'number': 6, 'nativeText': '시각 전도로'})
        self.assertEqual(first, second)
        self.assertEqual([(b['id'], b['kind']) for b in first],
                         [('v2p6f0', 'heading'), ('v2p6f1', 'visual')])
        self.assertEqual(first[0]['text'], '시각 전도로')
        self.assertEqual(first[1]['bbox'], [.3, .01, .98, .95])
        self.assertCountEqual([wid for b in first for wid in b['wordIds']], [w['id'] for w in native])

    def test_bottom_caption_and_true_end_heading_never_jump_above_an_image(self):
        for kind in ('heading', 'caption', 'text'):
            blocks = [visual((.03, .002, .97, .88)),
                      title('2025.04.02 미국의 새 관세정책 발표', (.59, .92, .93, .95), kind, 20)]
            before = copy.deepcopy(blocks)
            self.assertEqual(self.order(blocks), before)

    def test_mid_diagram_label_and_early_figure_caption_do_not_become_titles(self):
        for label in [title('시각중추', (.03, .4, .24, .45), 'text'),
                      title('그림 1 시각 전도로', kind='text'),
                      title('Figure 1 visual pathway', kind='text'),
                      title('x=a', kind='heading')]:
            blocks = [visual(), label]
            self.assertEqual(self.order(blocks), copy.deepcopy(blocks))

    def test_competing_top_titles_remain_in_geometric_order(self):
        blocks = [visual(), title('왼쪽 구조', (.03, .04, .24, .095)),
                  title('오른쪽 구조', (.60, .04, .85, .095))]
        self.assertEqual(self.order(blocks), copy.deepcopy(blocks))

    def test_a_plain_label_among_other_native_text_is_not_promoted(self):
        blocks = [visual(), title(kind='text'),
                  title('다른 설명이에요.', (.03, .3, .25, .34), 'text', 12)]
        self.assertEqual(self.order(blocks), copy.deepcopy(blocks))

    def test_each_slide_panel_keeps_its_own_title_and_visual(self):
        image1, heading1 = visual((.3, .01, .98, .48)), title('첫째 구조', (.03, .04, .24, .075), 'text')
        image2, heading2 = visual((.3, .511, .98, .98)), title('둘째 구조', (.03, .54, .24, .575), 'text')
        result = self.order([image1, heading1, image2, heading2], [[0, 0, 1, .5], [0, .5, 1, 1]])
        self.assertEqual(result, [heading1, image1, heading2, image2])

    def test_other_panel_title_cannot_claim_an_earlier_panels_visual(self):
        blocks = [visual((.3, .01, .98, .48)), title('다음 판넬', (.03, .54, .24, .575), 'text')]
        result = self.order(blocks, [[0, 0, 1, .5], [0, .5, 1, 1]])
        self.assertEqual(result, copy.deepcopy(blocks))

    def test_small_icon_small_font_and_large_top_gap_remain_unchanged(self):
        for blocks in [[visual((.8, .01, .9, .08)), title(kind='text')],
                       [visual(), title(kind='text', size=12)],
                       [visual((.3, 0, .98, .95)), title(box=(.03, .11, .24, .16))]]:
            self.assertEqual(self.order(blocks), copy.deepcopy(blocks))


if __name__ == '__main__':
    unittest.main()
