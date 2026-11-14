"""Only serialized Markdown quote prefixes change; source math/code stays intact."""
import unittest

from pdf_new_concept_ver99_checks import repair_prose_serialization


class DisplayQuoteRepairTests(unittest.TestCase):
    def test_display_quote_prefix_is_removed_without_changing_expression(self):
        for opening,closing in [('$$','$$'),(r'\[',r'\]')]:
            with self.subTest(opening=opening):
                self.assertEqual(repair_prose_serialization(opening+'\n> W = \\int_a^b F(x)\\,dx\n'+closing),
                                 opening+'\nW = \\int_a^b F(x)\\,dx\n'+closing)

    def test_actual_inequalities_and_mixed_lines_are_unchanged(self):
        for value in ['$$\nx > 0\n$$','$$\nx\n> 0\n$$','$$\n>0\n$$',r'\(x > 0\)',
                      '$$\n\\begin{aligned}\n> x > 0\n\\end{aligned}\n$$']:
            with self.subTest(value=value):self.assertEqual(repair_prose_serialization(value),value)

    def test_empty_quote_separator_in_two_display_equations_is_removed(self):
        for opening,closing in [('$$','$$'),(r'\[',r'\]')]:
            for separator in ('>', '> ', '  >\t'):
                with self.subTest(opening=opening,separator=separator):
                    first=r'V=\int_a^b A(x)\,dx'
                    second=r'V=\int_c^d A(y)\,dy'
                    value=opening+'\n> '+first+'\n'+separator+'\n> '+second+'\n'+closing
                    expected=opening+'\n'+first+'\n'+('  ' if separator.startswith('  ') else '')+'\n'+second+'\n'+closing
                    repaired=repair_prose_serialization(value)
                    self.assertEqual(repaired,expected)
                    self.assertEqual(repair_prose_serialization(repaired),expected)

    def test_empty_quote_line_does_not_allow_partial_or_comparison_repair(self):
        values=['$$\nx > 0\n>\n> y > 0\n$$',
                '$$\n>0\n>\n> y > 0\n$$',
                '$$\n> x > 0\n>\ny > 0\n$$']
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(repair_prose_serialization(value),value)

    def test_equation_relational_operators_survive_quote_removal(self):
        value='$$\n> x > 0\n>\n> y \\geq x\n$$'
        self.assertEqual(repair_prose_serialization(value),
                         '$$\nx > 0\n\ny \\geq x\n$$')

    def test_code_is_not_interpreted_as_a_display_equation(self):
        for value in ['```text\n$$\n> W = Fd\n$$\n```',
                      '```text\n$$\n> x > 0\n>\n> y > 0\n$$\n```']:
            self.assertEqual(repair_prose_serialization(value),value)


if __name__=='__main__':unittest.main()
