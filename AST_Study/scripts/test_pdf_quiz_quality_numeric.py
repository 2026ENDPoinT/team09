"""Exact, bounded arithmetic regressions for equal-valued integral options."""
import copy
from fractions import Fraction
import unittest

from pdf_quiz_quality import _integral_value, local_issues
from test_pdf_quiz_quality import mcq, codes


class QuizNumericIntegralTests(unittest.TestCase):
    def assert_equal_options(self, left, right, expected):
        self.assertEqual(_integral_value(left), expected)
        self.assertEqual(_integral_value(right), expected)
        question = mcq()
        question['options'][0]['text'], question['options'][3]['text'] = left, right
        finding = next(i for i in local_issues(question) if i['code'] == 'equal_value_integral_options')
        self.assertIn('A·D', finding['message'])
        self.assertIn('재검토', finding['message'])

    def test_actual_pi_options_from_different_models_both_equal_nine_pi(self):
        self.assert_equal_options(r'\(\int_0^3 \pi x^2 dx\)',
            r'\(\int_0^3 2\pi x dx\)', ((1, Fraction(9)),))

    def test_actual_opposite_spring_coordinate_options_both_equal_360(self):
        self.assert_equal_options(r'\int_0^{12} 5x dx', r'\int_0^{12} 5(12-x)dx',
            ((0, Fraction(360)),))

    def test_variable_substitution_and_different_bounds_can_have_equal_values(self):
        self.assert_equal_options(r'\int_0^1 x dx', r'\int_0^2 t/4 dt', ((0, Fraction(1, 2)),))

    def test_pi_and_rational_parts_are_kept_exact_and_separate(self):
        self.assert_equal_options(r'\int_0^1 (\pi x+1/2)dx',
            r'\int_0^2 (\pi t/4+1/4)dt', ((0, Fraction(1, 2)), (1, Fraction(1, 2))))
        self.assertNotEqual(_integral_value(r'\int_0^1 \pi dx'),
                            _integral_value(r'\int_0^1 3.14159 dx'))

    def test_negative_fractional_bounds_and_unicode_powers_are_exact(self):
        self.assert_equal_options('∫₋₁¹−x²dx', r'\int_{1}^{-1} y^2dy', ((0, Fraction(-2, 3)),))
        self.assert_equal_options(r'\int_{-1/2}^{1/2} x^2 dx',
            r'\int_0^1 \frac{1}{4}y^2 dy', ((0, Fraction(1, 12)),))
        self.assert_equal_options('∫₀³πx²dx', r'\int_0^3 \pi t^2 dt', ((1, Fraction(9)),))

    def test_latex_rational_coefficients_decimal_text_and_unary_precedence(self):
        self.assertEqual(_integral_value(r'\int_0^1 \frac{3}{2}x^2 dx'), ((0, Fraction(1, 2)),))
        self.assertEqual(_integral_value(r'\int_0^1 \frac{x^2}{2}dx'), ((0, Fraction(1, 6)),))
        self.assert_equal_options(r'\int_{0.0}^{1.0} .5x dx', r'\int_0^1 x/2dx', ((0, Fraction(1, 4)),))
        self.assertEqual(_integral_value(r'\int_0^1 -x^2dx'), ((0, Fraction(-1, 3)),))
        self.assertEqual(_integral_value(r'\int_0^1 (-x)^2dx'), ((0, Fraction(1, 3)),))

    def test_expansion_and_zero_integrals_use_exact_fractions(self):
        self.assert_equal_options(r'\int_0^1 (1-x)^2dx', r'\int_0^1 (1-2x+x^2)dx',
            ((0, Fraction(1, 3)),))
        self.assert_equal_options(r'\int_{-1}^1 x^3dx', r'\int_0^1 0dx', ())

    def test_different_numeric_values_are_not_flagged(self):
        question = mcq()
        question['options'][0]['text'] = r'\int_0^3 \pi x^2dx'
        question['options'][1]['text'] = r'\int_0^3 \pi xdx'
        self.assertNotIn('equal_value_integral_options', codes(question))

    def test_functions_parameters_and_variable_denominators_are_unsupported(self):
        values = [r'\int_0^1 sin(x)dx', r'\int_0^1 \sin(x)dx', r'\int_0^1 exp(x)dx',
            r'\int_0^1 \sqrt{x}dx', r'\int_a^1 xdx', r'\int_0^1 k*x dx',
            r'\int_0^1 (x+y)dx', r'\int_0^1 x/x dx', r'\int_0^1 1/(x+1)dx',
            r'\int_0^{\pi} xdx', r'\int_0^1 x/\pi dx']
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(_integral_value(value))

    def test_unsupported_forms_and_malicious_syntax_are_never_evaluated(self):
        values = [r'\int_0^1 __import__(os)dx', r'\int_0^1 open(file)dx',
            r'\int_0^1 \input{private}dx', r'\int_0^1 [x for x in range(3)]dx',
            r'\int_0^1 xdx=1/2', r'2\int_0^1 xdx', r'\int_0^1 xdx+\int_0^1 xdx',
            r'\int_0^1 xdx J', r'\int_0^1 x/0dx', r'\int_0^1 x!dx',
            r'\int_0^1 \frac{x}{x}dx']
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(_integral_value(value))

    def test_resource_heavy_exponents_depth_and_lengths_are_unsupported(self):
        values = [r'\int_0^1 x^{999999999999999999999999999}dx',
            r'\int_0^1 x^{33}dx', r'\int_0^1 x^{-1}dx', r'\int_0^1 x^{1/2}dx',
            r'\int_0^1 (x+\pi)^{32}dx', '\\int_0^1 '+'('*22+'x'+')'*22+'dx',
            '\\int_0^1 '+'x+'*140+'x dx', '\\int_0^1 '+' '*4100+'x dx',
            r'\int_0^1 99999999999999999999999999999999x dx']
        for value in values:
            with self.subTest(value=value[:80]):
                self.assertIsNone(_integral_value(value))

    def test_same_numeric_value_is_policy_hold_even_for_explicit_model_question(self):
        question = mcq()
        question['stem'] = '주어진 물리 조건을 직접 나타내는 모델의 적분식은?'
        question['options'][0]['text'] = r'\int_0^3 \pi x^2dx'
        question['options'][2]['text'] = r'\int_0^3 2\pi xdx'
        finding = next(i for i in local_issues(question) if i['code']=='equal_value_integral_options')
        self.assertIn('복수정답으로 해석할 여지', finding['message'])
        self.assertNotIn('모두 정답', finding['message'])

    def test_partial_inputs_and_source_quotes_are_not_changed_or_integrated(self):
        for value in (None, 3, [], {}):
            self.assertIsNone(_integral_value(value))
        question = mcq()
        question['options'][0]['text'] = r'\int_0^1 xdx'
        question['options'][2]['text'] = r'\int_0^1 (1-y)dy'
        question['evidence'] = [{'quote': r'원문 \int_0^1 k*x dx'}]
        before = copy.deepcopy(question)
        self.assertIn('equal_value_integral_options', codes(question))
        self.assertEqual(question, before)


if __name__ == '__main__':
    unittest.main()
