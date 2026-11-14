"""Font/page evidence, ambiguity and ordinary-v preservation; no API calls."""
import copy
import unittest
from unittest.mock import patch

from pdf_symbol_bullets import clean_titles, verified_line, repair_symbol_chars


def line(text='v 속도 v와 V의 관계', font='ABCDEF+Wingdings-Regular', gap=6):
    return {'text': text, 'chars': [
        {'text': 'v', 'fontname': font, 'x0': 10, 'x1': 20},
        {'text': text[2:3], 'fontname': 'Helvetica', 'x0': 20 + gap, 'x1': 40}]}


class Page:
    def __init__(self, lines):
        self.lines = lines

    def extract_text_lines(self, **kwargs):
        return self.lines


class Pdf:
    def __init__(self, lines):
        self.pages = [Page(lines), Page([line(font='Times-Italic')])]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SymbolBulletTests(unittest.TestCase):
    def test_only_confirmed_separated_wingdings_marker(self):
        self.assertEqual(verified_line(line()), ('v속도v와V의관계', '속도 v와 V의 관계'))
        for font in ('Helvetica', 'Times-Italic', 'Symbol', 'Wingdings2', 'Wingdings-3', ''):
            self.assertIsNone(verified_line(line(font=font)))
        for text in ('v', 'v속도', 'V 속도', 'v(t)', 'velocity', 'v = dx/dt'):
            # Ordinary math font must never be inferred to be a bullet.
            self.assertIsNone(verified_line(line(text=text, font='Times-Italic')))
        self.assertIsNotNone(verified_line(line(gap=0)))
        self.assertIsNone(verified_line(line(gap=-2)))
        self.assertIsNone(verified_line({'text': 'v 속도', 'chars': []}))

    def test_exact_page_title_and_all_other_content_preserved(self):
        raw = {'hierarchy': {'nodes': [
            {'title': 'v 속도 v와 V의 관계', 'page': 1},
            {'title': 'v 속도 v와 V의 관계', 'page': 2},
            {'title': 'v 전압', 'page': 1},
            {'title': 'v(t)', 'page': 1},
            {'title': 'v 속도 v와 V의 관계'}]},
            'sections': [{'title': 'v 속도 v와 V의 관계', 'evidence': [{'page': 1}],
                'body': 'v 속도 v와 V의 관계\n$v = dx/dt$\n```cpp\nv++;\n```',
                'parts': [{'title': 'v 속도 v와 V의 관계', 'evidence': [{'page': 1}, {'page': 2}]}]}],
            'concepts': [{'name': 'v 속도 v와 V의 관계', 'entries': [{'evidence': [{'page': 1}],
                'definition': 'v는 속도예요.', 'explanation': 'v = dx/dt', 'easyExplanation': '변수 v'}]}]}
        before = copy.deepcopy(raw)
        with patch('pdfplumber.open', return_value=Pdf([line()])):
            value = clean_titles('/unused', raw)
            again = clean_titles('/unused', value)
        self.assertEqual(raw, before)
        self.assertEqual(value, again)
        self.assertEqual(value['hierarchy']['nodes'][0]['title'], '속도 v와 V의 관계')
        self.assertEqual(value['hierarchy']['nodes'][1:], raw['hierarchy']['nodes'][1:])
        self.assertEqual(value['sections'][0]['body'], raw['sections'][0]['body'])
        self.assertEqual(value['sections'][0]['parts'], raw['sections'][0]['parts'])
        self.assertEqual(value['concepts'][0]['name'], '속도 v와 V의 관계')
        self.assertEqual(value['concepts'][0]['entries'], raw['concepts'][0]['entries'])

    def test_same_page_ordinary_v_ambiguity_preserves_title(self):
        raw = {'nodes': [{'title': 'v 속도 v와 V의 관계', 'page': 1}]}
        with patch('pdfplumber.open', return_value=Pdf([line(), line(font='Helvetica')])):
            self.assertEqual(clean_titles('/unused', raw), raw)

    def test_unavailable_source_preserves_everything(self):
        raw = {'nodes': [{'title': 'v 속도 v와 V의 관계', 'page': 1}]}
        with patch('pdfplumber.open', side_effect=OSError('missing')):
            self.assertEqual(clean_titles('/unused', raw), raw)

    def test_touching_marker_matches_saved_title_with_inserted_space(self):
        # Actual source metrics: 97.6044 -> 97.6099, no extracted space.
        source = line('v전체 강의의 열쇳말', gap=.005476)
        raw = {'hierarchy': {'nodes': [{'title': 'v 전체 강의의 열쇳말', 'page': 1}]},
               'sections': [{'title': 'v전체 강의의 열쇳말', 'page': 1}],
               'concepts': [{'name': 'v 전체 강의의 열쇳말', 'pages': [1]}]}
        with patch('pdfplumber.open', return_value=Pdf([source])):
            cleaned = clean_titles('/unused', raw)
        self.assertEqual(cleaned['hierarchy']['nodes'][0]['title'], '전체 강의의 열쇳말')
        self.assertEqual(cleaned['concepts'][0]['name'], '전체 강의의 열쇳말')
        self.assertEqual(cleaned['sections'][0]['title'], '전체 강의의 열쇳말')
        self.assertEqual(raw['concepts'][0]['name'], 'v 전체 강의의 열쇳말')

    def test_source_repair_preserves_latin_math_code_and_other_symbol_fonts(self):
        chars = [{'text': 'v', 'fontname': 'INPILL+Wingdings-Regular', 'x0': 10},
                 {'text': 'v V velocity v(t) v = dx/dt v++;', 'fontname': 'Times-Italic'},
                 {'text': 'v', 'fontname': 'Symbol'},
                 {'text': 'v', 'fontname': 'Wingdings2'},
                 {'text': 'v', 'fontname': 'Wingdings-3'},
                 {'text': 'V', 'fontname': 'Wingdings'}]
        before = copy.deepcopy(chars)
        repaired, count = repair_symbol_chars(chars)
        self.assertEqual(count, 1)
        self.assertEqual(repaired[0], {**chars[0], 'text': '❖'})
        self.assertEqual(repaired[1:], chars[1:])
        self.assertEqual(chars, before)
        self.assertEqual(repair_symbol_chars(repaired), (repaired, 0))

    def test_repaired_bullet_is_heading_punctuation_not_a_variable(self):
        from pdf_study_hierarchy import title_text
        self.assertEqual(title_text('❖전체 강의의 열쇳말'), '전체 강의의 열쇳말')
        self.assertEqual(title_text('v 속도와 V 전압'), 'v 속도와 V 전압')


if __name__ == '__main__':
    unittest.main()
