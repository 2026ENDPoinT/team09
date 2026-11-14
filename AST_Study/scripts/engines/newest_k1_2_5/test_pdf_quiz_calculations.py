import copy
from fractions import Fraction
import unittest
from unittest.mock import patch

from pdf_quiz_calculations import evaluate, display, render_calculations
from pdf_quiz_response import assemble_answers
from test_pdf_quiz_response import draft


class CalculationConstructionTests(unittest.TestCase):
    def test_passage_bindings_are_rendered_before_stem_sections_are_assembled(self):
        raw=draft();q=raw['questions'][0]
        q.update(passage='질량은 {{mass}} kg, 속도는 {{speed}} m/s이다.',
                 stem='운동량을 구하시오.',answer='{{momentum}} kg·m/s',
                 calculations=[{'name':'mass','expression':'2'}, {'name':'speed','expression':'3'},
                               {'name':'momentum','expression':'mass*speed'}])
        assembled=assemble_answers(render_calculations(raw))['questions'][0]
        self.assertIn('질량은 2 kg, 속도는 3 m/s이다.',assembled['stem'])
        self.assertNotIn('{{',assembled['stem'])
        self.assertEqual(assembled['options'][0]['text'],'6 kg·m/s')

    def test_exact_decimal_rational_and_sqrt(self):
        for expression, expected in [('0.1+0.2', '0.3'), ('1/3', '1/3'),
                                     ('sqrt(9/16)', '0.75'), ('2**-3', '0.125')]:
            self.assertEqual(display(evaluate(expression, {})), expected)
        self.assertTrue(display(evaluate('sqrt(2)', {})).startswith('≈1.414213562'))

    def test_long_finite_decimal_is_exact_and_irrational_is_marked_approximate(self):
        for value in (Fraction(1, 2**1024), Fraction(-3, 2**2047), Fraction(7, 5**800)):
            with self.subTest(value=value):
                rendered = display(value)
                self.assertEqual(Fraction(rendered), value)
                self.assertNotIn('≈', rendered)
        self.assertTrue(display(evaluate('sqrt(2)', {})).startswith('≈'))

    def test_extreme_decimal_literal_is_rejected_before_integer_expansion(self):
        for expression in ('1e1000000000', '1e-1000000000'):
            with self.subTest(expression=expression), patch('pdf_quiz_calculations.Fraction') as expand:
                with self.assertRaises(ValueError):
                    evaluate(expression, {})
                expand.assert_not_called()

    def test_impulse_answer_and_explanation_use_same_calculated_value(self):
        raw = draft(); q = raw['questions'][0]
        q.update(calculations=[{'name':'p0','expression':'10'},
                               {'name':'J','expression':'(2+4)*3/2'},
                               {'name':'pf','expression':'p0+J'}],
                 answer='{{pf}} kg·m/s', explanation='충격량은 {{J}}, 최종 운동량은 {{pf}}이다.')
        before = copy.deepcopy(raw)
        q = assemble_answers(render_calculations(raw))['questions'][0]
        self.assertEqual(q['options'][0]['text'], '19 kg·m/s')
        self.assertEqual(q['explanation'], '충격량은 9, 최종 운동량은 19이다.')
        self.assertEqual(q['options'][0]['explanation'], q['explanation'])
        self.assertEqual(raw, before)

    def test_invalid_calculation_keeps_question_and_literal_with_warning(self):
        raw = draft(); q = raw['questions'][0]
        q.update(calculations=[{'name':'x','expression':'1/0'}], answer='{{x}}')
        result = render_calculations(raw)
        self.assertEqual(len(result['questions']), 1)
        self.assertEqual(result['questions'][0]['answer'], '{{x}}')
        self.assertTrue(result['questions'][0]['warnings'])
        self.assertEqual(result['questions'][0]['rawQuestion'], q)

    def test_inline_allowed_expression_and_bad_slot_both_preserve_question(self):
        raw = draft(); q=raw['questions'][0]
        q.update(calculations=[{'name':'u','expression':'-2'}],
                 stem='속도는 −{{abs(u)}}이다.', answer='{{u*2}}', explanation='{{unknown(1)}}')
        result=render_calculations(raw)['questions'][0]
        self.assertEqual(result['stem'], '속도는 −2이다.')
        self.assertEqual(result['answer'], '-4')
        self.assertEqual(result['explanation'], '{{unknown(1)}}')
        self.assertTrue(result['warnings'])

    def test_bad_warning_metadata_does_not_discard_failed_calculation(self):
        for prior in (None, 'invalid', [{}, [], 1, '기존 안내']):
            with self.subTest(prior=prior):
                raw = draft(); q = raw['questions'][0]
                q.update(calculations=[{'name':'x','expression':'1/0'}],
                         answer='{{x}}', warnings=prior)
                result = render_calculations(raw)['questions'][0]
                self.assertEqual(result['answer'], '{{x}}')
                self.assertEqual(result['rawQuestion'], q)
                self.assertTrue(result['warnings'])
                self.assertTrue(all(isinstance(w, str) for w in result['warnings']))
                if isinstance(prior, list):
                    self.assertIn('기존 안내', result['warnings'])

    def test_no_execution_attributes_subscripts_or_unbounded_expressions(self):
        for expression in ["__import__('os').system('true')", '(1).__class__', '[1][0]',
                           '2**1000000', 'unknown+1', '1<<2', 'sqrt(-1)', '1e999',
                           '(lambda: 1)()', 'sqrt(1, 2)', 'True+1']:
            with self.subTest(expression=expression), self.assertRaises((ValueError, ArithmeticError)):
                evaluate(expression, {})

    def test_prior_workbooks_and_source_quotes_unchanged(self):
        raw=draft(); self.assertEqual(render_calculations(raw), raw)
        raw['questions'][0]['calculations']=[{'name':'x','expression':'2'}]
        raw['questions'][0]['evidence'][0]['quote']='{{x}} is a source literal'
        self.assertEqual(render_calculations(raw)['questions'][0]['evidence'], raw['questions'][0]['evidence'])

    def test_explicit_inline_arithmetic_without_binding_array(self):
        raw = draft(); q = raw['questions'][0]
        q.pop('calculations', None)
        q.update(answer='{{=2**2/(2*0.4*10)}} m',
                 explanation='거리의 계산값은 {{=2**2/(2*0.4*10)}} m이다.')
        before = copy.deepcopy(raw)
        rendered = render_calculations(raw)
        self.assertEqual(rendered['questions'][0]['answer'], '0.5 m')
        result = assemble_answers(rendered)['questions'][0]
        self.assertEqual(result['options'][0]['text'], '0.5 m')
        self.assertEqual(result['explanation'], '거리의 계산값은 0.5 m이다.')
        self.assertEqual(raw, before)

    def test_explicit_inline_with_empty_array_and_sequential_bindings(self):
        for bindings, expression, expected in (
            ([], '0.1+0.2', '0.3'),
            ([{'name': 'u', 'expression': '3'},
              {'name': 'v', 'expression': 'u+1'}], 'sqrt(u**2+v**2)', '5'),
        ):
            with self.subTest(expression=expression):
                raw = draft(); q = raw['questions'][0]
                q.update(calculations=bindings, answer='{{= ' + expression + ' }}')
                rendered = render_calculations(raw)['questions'][0]
                self.assertEqual(rendered['answer'], expected)
                self.assertFalse(rendered.get('warnings'))

    def test_explicit_inline_only_renders_owned_display_fields(self):
        raw = draft(); q = raw['questions'][0]
        q.update(calculations=[], stem='값 {{=1/3}}', answer='{{=sqrt(9)}}',
                 explanation='{{=abs(-2)}}', keyPoints=['{{=2**-3}}'],
                 options=[{'id': 'A', 'text': '{{=1+1}}', 'explanation': '{{=2*3}}'}],
                 distractors=[{'text': '{{=3+4}}', 'explanation': '{{=4*2}}'}])
        q['evidence'][0]['quote'] = '{{=1+1}} 원문 표기'
        raw['sources'] = [{'text': '{{=2+2}} 원문'}]
        rendered = render_calculations(raw)
        item = rendered['questions'][0]
        self.assertEqual(item['stem'], '값 1/3')
        self.assertEqual(item['answer'], '3')
        self.assertEqual(item['explanation'], '2')
        self.assertEqual(item['keyPoints'], ['0.125'])
        self.assertEqual(item['options'][0]['text'], '2')
        self.assertEqual(item['options'][0]['explanation'], '6')
        self.assertEqual(item['distractors'][0]['text'], '7')
        self.assertEqual(item['distractors'][0]['explanation'], '8')
        self.assertEqual(item['evidence'], q['evidence'])
        self.assertEqual(rendered['sources'], raw['sources'])

    def test_inline_without_array_does_not_interpret_ordinary_latex_braces(self):
        raw = draft(); q = raw['questions'][0]
        q.pop('calculations', None)
        q.update(stem=r'\frac{{1+2}}{{3}}와 {{x}}는 원문 수식이다.',
                 answer='{{=1+2}}')
        rendered = render_calculations(raw)['questions'][0]
        self.assertEqual(rendered['stem'], q['stem'])
        self.assertEqual(rendered['answer'], '3')
        self.assertFalse(rendered.get('warnings'))

    def test_inline_failures_preserve_every_question_and_original_expression(self):
        expressions = ['1/0', 'sqrt(-1)', '2**17', '2**0.5', '1e1000000000',
                       '(1).__class__', '[1][0]', "__import__('os')", '',
                       '1+' * 130 + '1', 'x' * 513]
        for expression in expressions:
            with self.subTest(expression=expression):
                raw = draft(); q = raw['questions'][0]
                q.update(calculations=[], answer='{{=' + expression + '}}')
                before = copy.deepcopy(raw)
                rendered = render_calculations(raw)
                self.assertEqual(len(rendered['questions']), len(raw['questions']))
                item = rendered['questions'][0]
                self.assertEqual(item['answer'], q['answer'])
                self.assertEqual(item['rawQuestion'], q)
                self.assertTrue(item['warnings'])
                self.assertEqual(raw, before)

    def test_inline_irrational_is_approximate_and_exact_binding_stays_compatible(self):
        raw = draft(); q = raw['questions'][0]
        q.update(calculations=[{'name': 'x', 'expression': '1/3'}],
                 answer='{{x}}; {{=sqrt(2)}}')
        rendered = render_calculations(raw)['questions'][0]
        self.assertTrue(rendered['answer'].startswith('1/3; ≈1.414213562'))
        self.assertEqual(rendered['calculationValues'], {'x': '1/3'})

if __name__ == '__main__': unittest.main()
