"""Cell serialization preserves whole source strings and TeX/code symbols."""
import unittest

from pdf_table_cells import markdown_cell, valid_cell


class TableCellTests(unittest.TestCase):
    def test_readable_long_cell_has_no_arbitrary_character_limit(self):
        for count in (120, 121, 500, 10000):
            text = '가' * count
            self.assertTrue(valid_cell(text))
            self.assertEqual(markdown_cell(text), text)

    def test_pipe_escape_is_lossless_for_math_code_existing_slashes_and_plain_text(self):
        for text in (r'\(|r|<1\)', r'\(\|r\|<1\)', r'\(\left|x\right|\)',
                     r'\(P(A|B)\)', r'\(\lvert x\rvert\)', '`left | right`',
                     '`r"\\|"`', '`flags |= mask`', '`a || b`', 'A | B | C',
                     '헤더 | 설명', r'끝 \| 및 \\|'):
            with self.subTest(text=text):
                before = text
                encoded = markdown_cell(text)
                self.assertEqual(encoded.replace(r'\|', '|'), text)
                self.assertEqual(text, before)
                self.assertEqual(encoded.count('|'), text.count('|'))
                self.assertEqual(len(encoded), len(text) + text.count('|'))
        self.assertEqual(markdown_cell(r'\(|r|<1\)'), r'\(\|r\|<1\)')
        self.assertEqual(markdown_cell(r'\(\|r\|<1\)'), r'\(\\|r\\|<1\)')

    def test_newline_control_and_source_id_rejections_are_preserved(self):
        for text in ('', '  ', None, 1, True, 'left\nright', 'left\rright', 'a\tb',
                     '\x00x', 'a\x1fb', 'a\x7fb', 'a\x85b', 'a\u2028b', 'a\u2029b',
                     '원문 v2p3f12 영역', '`v2p3f12`', r'\(v2p3f12\)'):
            with self.subTest(text=text):
                self.assertFalse(valid_cell(text))
                with self.assertRaises(ValueError):markdown_cell(text)

    def test_real_html_is_rejected_without_mistaking_math_or_code_for_html(self):
        for text in ('<script>bad</script>', '<b>강조</b>', '<img src="x">', '<br/>',
                     '<!-- hidden -->', '<!DOCTYPE html>', '<p class="a">텍스트</p>'):
            with self.subTest(text=text):
                self.assertFalse(valid_cell(text))
                with self.assertRaises(ValueError):markdown_cell(text)
        for text in (r'\(|r|<1\)', r'\(a<b>c\)', '`std::vector<int> | x`',
                     '비교 a < b', '&lt;b&gt;', '보통 셀', '`` `a|b` ``'):
            with self.subTest(text=text):self.assertTrue(valid_cell(text))


if __name__ == '__main__':
    unittest.main()
