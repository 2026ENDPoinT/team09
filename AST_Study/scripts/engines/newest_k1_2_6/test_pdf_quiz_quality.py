"""Offline regressions for observable quiz defects and conservative boundaries."""
import copy
import unittest

from pdf_quiz_quality import local_issues, quality_text


def word(stem, answer):
    return {'type': 'word', 'stem': stem, 'answer': answer,
            'explanation': '조건에 해당하는 용어이다.', 'options': [], 'keyPoints': []}


def mcq():
    return {'type': 'mcq', 'stem': '옳은 것은?', 'answer': 'A',
            'explanation': 'A만 주어진 조건을 만족한다.',
            'options': [{'id': k, 'text': '선지 ' + k,
                         'explanation': '정답이다.' if k == 'A' else '조건을 만족하지 않는다.'}
                        for k in 'ABCD'], 'keyPoints': []}


def codes(question):
    return {issue['code'] for issue in local_issues(question)}


class QuizLocalQualityTests(unittest.TestCase):
    def test_actual_ballistic_pendulum_answer_is_exposed(self):
        q = word('탄동 진자에서 총알이 나무토막에 박힌 뒤 함께 상승한다. '
                 '상승 높이로 총알의 속력을 측정하는 이 장치의 이름을 쓰시오.', '탄동 진자')
        self.assertIn('answer_in_stem', codes(q))

    def test_korean_spacing_and_attached_particles_still_expose_name(self):
        for stem in ['탄동진자의 원리를 이용하는 장치의 이름은?',
                     '이 장치는 탄동 진자라고 한다. 명칭을 쓰시오.',
                     '“탄동 진자”라는 장치의 이름을 쓰시오.']:
            with self.subTest(stem=stem):
                self.assertIn('answer_in_stem', codes(word(stem, '탄동진자')))

    def test_prefixed_or_compound_term_does_not_expose_shorter_answer(self):
        self.assertNotIn('answer_in_stem', codes(word('비탄성 충돌과 달리 운동에너지가 보존되는 충돌은?', '탄성 충돌')))
        self.assertNotIn('answer_in_stem', codes(word('질량중심과 관련된 물체의 물리량을 쓰시오.', '질량')))
        self.assertNotIn('answer_in_stem', codes(word('bonding과 구별되는 금융상품의 이름을 쓰시오.', 'bond')))

    def test_number_formula_single_letter_and_multiple_required_names_are_deferred(self):
        for answer in ['2', 'x', r'\(F=ma\)', 'm/s', '〈앵그르의 바이올린〉, 《선물》']:
            with self.subTest(answer=answer):
                self.assertNotIn('answer_in_stem', codes(word(answer + '라는 표현을 검토하라.', answer)))

    def test_actual_spring_integral_answer_is_not_a_word_question(self):
        # The first paid audit's 38536b32 question asked for a full integral.
        q = word('원래 길이가 0.20m인 용수철을 0.24m에서 0.27m까지 늘인다. '
                 '용수철 상수가 k일 때 필요한 일을 나타내는 정적분을 쓰시오.',
                 r'\(\displaystyle W=\int_{0.04}^{0.07}kx\,dx\)')
        self.assertIn('word_answer_is_formula', codes(q))

    def test_word_formula_markers_are_rejected_without_requiring_other_defects(self):
        for answer in ['∫₀¹ f(x)dx', '∑ aᵢ', 'F=ma', r'\int f(x)dx',
                       r'\int_0^1 f(x)dx', r'\frac{a}{b}', r'\sum_i a_i', '$$x^2$$']:
            with self.subTest(answer=answer):
                self.assertIn('word_answer_is_formula', codes(word('답을 쓰시오.', answer)))

    def test_normal_word_terms_remain_allowed_and_essay_may_contain_a_formula(self):
        for answer in ['탄동 진자', '원통껍질법', '표준편차', 'F-검정',
                       '제1형 당뇨병', '가속도(acceleration)']:
            with self.subTest(answer=answer):
                self.assertNotIn('word_answer_is_formula', codes(word('해당 명칭을 쓰시오.', answer)))
        q = word('일을 구하는 방법을 설명하시오.', r'\(W=\int_a^bf(x)dx\)')
        q.update(type='essay', keyPoints=['위치별 힘을 적분한다.'])
        self.assertNotIn('word_answer_is_formula', codes(q))

    def test_parenthetical_definition_is_not_treated_as_answer_alias(self):
        self.assertNotIn('answer_in_stem', codes(word('일상 파편을 재구성하는 기법의 이름은?',
                                                    '메르츠(일상 파편을 재구성하는 기법)')))
        self.assertIn('answer_in_stem', codes(word('메르츠를 설명한 기법의 이름을 쓰시오.',
                                                 '메르츠(Merz)')))

    def test_actual_latex_backspace_and_tab_escape_are_rejected(self):
        q = mcq()
        q['options'][2]['text'] = '\\(2\\pi\\displaystyle\bigl(\text{상한 }2)\bigr)\\)'
        self.assertIn('invalid_control_character', codes(q))
        self.assertTrue(any('U+0008' in i['message'] for i in local_issues(q)))
        self.assertTrue(any('U+0009' in i['message'] for i in local_issues(q)))

    def test_well_escaped_latex_and_plain_indentation_are_allowed(self):
        q = mcq()
        q['options'][2]['text'] = r'\(2\pi\displaystyle\bigl(\text{상한 }2\bigr)\)'
        q['explanation'] = '풀이:\n\t첫째 줄\n\t둘째 줄\r\n'
        self.assertNotIn('invalid_control_character', codes(q))

    def test_control_characters_are_checked_in_all_visible_fields_but_not_sources(self):
        q = word('정상 지문', '정상 답')
        q['evidence'] = [{'quote': '원문\x08은 그대로 보존한다.'}]
        self.assertNotIn('invalid_control_character', codes(q))
        q['answer'] = '정상 답\x00'
        q['keyPoints'] = ['비교 요소\x1b']
        findings = [x for x in local_issues(q) if x['code'] == 'invalid_control_character']
        self.assertEqual(len(findings), 2)

    def test_normal_text_is_not_mutated(self):
        q = mcq()
        q['options'][2]['text'] = '다른\n  선지'
        saved = copy.deepcopy(q)
        local_issues(q)
        self.assertEqual(q, saved)

    def test_duplicate_options_ignore_width_and_whitespace_runs(self):
        q = mcq()
        q['options'][0]['text'] = 'Ｆ＝ｍａ  이다.'
        q['options'][1]['text'] = 'F=ma\n이다.'
        self.assertIn('duplicate_option_text', codes(q))

    def test_similar_but_different_options_are_not_called_duplicates(self):
        q = mcq()
        q['options'][0]['text'] = '운동량이 보존된다.'
        q['options'][1]['text'] = '운동량이 보존되지 않는다.'
        self.assertNotIn('duplicate_option_text', codes(q))

    def assert_integral_pair(self, left, right, equivalent):
        q = mcq()
        q['options'][0]['text'], q['options'][2]['text'] = left, right
        findings = local_issues(q)
        actual = [f for f in findings if f['code'] == 'equivalent_integral_options']
        self.assertEqual(bool(actual), equivalent)
        if equivalent:
            self.assertIn('A·C', actual[0]['message'])
        return findings

    def test_actual_alpha_equivalent_definite_integral_options_are_detected(self):
        # Paid blind review 55ad1d5e... incorrectly called C a variable error.
        self.assert_integral_pair(r'\(\displaystyle\int_0^1[(2-y)-y^2]dy\)',
                                  r'\(\displaystyle\int_0^1[(2-x)-x^2]dx\)', True)
        self.assert_integral_pair('∫₀¹[(2−y)−y²]dy', '∫₀¹[(2−x)−x²]dx', True)

    def test_latex_limits_spaces_and_simple_power_grouping_preserve_equivalence(self):
        self.assert_integral_pair(r'\[\int_{0}^{1} \left[(2-t)-t^{2}\right] \,dt\]',
                                  r'$\int_0^1 [(2-u)-u^2]du$', True)
        self.assert_integral_pair(r'\int_a^b f(x)\,dx', r'\int_a^b f(y)\,dy', True)
        self.assert_integral_pair(r'\int_0^1\sin(x)dx', r'\int_0^1\sin(y)dy', True)

    def test_different_limits_signs_coefficients_and_functions_are_not_conflated(self):
        cases = [
            (r'\int_0^1 x^2dx', r'\int_0^2 y^2dy'),
            (r'\int_0^1 x^2dx', r'\int_1^0 y^2dy'),
            (r'\int_0^1 (2-x)dx', r'\int_0^1 (3-y)dy'),
            (r'\int_0^1 (2-x)dx', r'\int_0^1 (2+y)dy'),
            (r'\int_0^1 sin(x)dx', r'\int_0^1 cos(y)dy'),
            (r'\int_0^1 exp(x)dx', r'\int_0^1 eyp(y)dy'),
        ]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assert_integral_pair(left, right, False)

    def test_free_variables_remain_exact_and_bound_variable_is_not_captured(self):
        self.assert_integral_pair(r'\int_0^1 a*x dx', r'\int_0^1 a*y dy', True)
        for left, right in [
            (r'\int_0^1 a*x dx', r'\int_0^1 b*y dy'),
            (r'\int_0^1 (x+y)dx', r'\int_0^1 (y+x)dy'),
            (r'\int_0^x x dx', r'\int_0^x y dy'),
            (r'\int_0^1 [(2-y)-y^2]dy', r'\int_0^1 [(2-y)-y^2]dx'),
        ]:
            with self.subTest(left=left, right=right):
                self.assert_integral_pair(left, right, False)

    def test_superscripts_are_not_flattened_into_ordinary_digits(self):
        findings = self.assert_integral_pair('∫₀¹y²dy', '∫₀¹y2dy', False)
        self.assertNotIn('duplicate_option_text', {f['code'] for f in findings})
        self.assert_integral_pair('∫₀¹y²dy', '∫₀¹x³dx', False)

    def test_function_names_and_english_words_are_not_alpha_replaced(self):
        self.assert_integral_pair(r'\int_0^1 syntax(x)dx', r'\int_0^1 syntay(y)dy', False)
        self.assert_integral_pair(r'\int_0^1 xylophone dx', r'\int_0^1 yylophone dy', False)
        self.assert_integral_pair(r'\int_0^1 xy dx', r'\int_0^1 xy dy', False)

    def test_only_complete_single_definite_integral_formulas_are_compared(self):
        cases = [
            (r'\int_0^1 xdx 이 식은 세로 절편이다.', r'\int_0^1 ydy 이 식은 가로 절편이다.'),
            (r'넓이는 \(\int_0^1 xdx\)이다.', r'넓이는 \(\int_0^1 ydy\)이다.'),
            (r'2\int_0^1 xdx', r'2\int_0^1 ydy'),
            (r'\int_0^1 xdx=1/2', r'\int_0^1 ydy=1/2'),
            (r'\int xdx', r'\int ydy'),
            (r'\int_0^1 xdx+\int_0^1 ydy', r'\int_0^1 ydy+\int_0^1 xdx'),
        ]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assert_integral_pair(left, right, False)

    def test_integrals_with_accidentally_equal_values_are_not_solved_by_guard(self):
        self.assert_integral_pair(r'\int_0^1 xdx', r'\int_0^1 (1-y)dy', False)
        self.assert_integral_pair(r'\int_{-1}^1 sin(x)dx', r'\int_{-1}^1 x^3dx', False)

    def test_integral_detection_does_not_touch_question_or_source_quotes(self):
        q = mcq()
        q['options'][0]['text'] = '∫₀¹y²dy'
        q['options'][1]['text'] = '∫₀¹x²dx'
        q['evidence'] = [{'quote': '∫₀¹y²dy · 原文保持\n\\int_0^1 x^2 dx'}]
        before = copy.deepcopy(q)
        self.assertIn('equivalent_integral_options', codes(q))
        self.assertEqual(q, before)

    def test_explicit_admission_of_multiple_answers_is_caught(self):
        q = mcq()
        q['explanation'] = ('다만 C도 같은 영역을 가로 띠로 나타낸 올바른 식이다. '
                            '따라서 두 식이 모두 정답이 되어 문항의 정답이 유일하지 않다.')
        self.assertIn('explanation_admits_invalid_question', codes(q))

    def test_explicit_no_answer_and_two_answers_are_caught(self):
        for explanation in ['이 문항에는 정답이 없다.', '이 문제는 정답이 두 개이다.',
                            '해당 문항은 복수정답이다.']:
            with self.subTest(explanation=explanation):
                q = mcq(); q['explanation'] = explanation
                self.assertIn('explanation_admits_invalid_question', codes(q))

    def test_conditional_warning_and_flawed_example_analysis_are_not_admissions(self):
        for explanation in ['만약 방향 조건을 생략하면 문항의 정답이 유일하지 않다. '
                            '이 문제에서는 방향을 명시해 A만 성립한다.',
                            '조건을 바꾸는 경우 문항의 정답이 유일하지 않다.',
                            '원래 학생이 만든 문항은 복수정답이지만 A는 이를 올바르게 수정했다.']:
            with self.subTest(explanation=explanation):
                q = mcq(); q['explanation'] = explanation
                self.assertNotIn('explanation_admits_invalid_question', codes(q))

    def test_a_question_can_explicitly_ask_to_diagnose_a_flawed_quoted_item(self):
        q = mcq()
        q['stem'] = '다음 문항의 오류를 검토한 설명으로 옳은 것은? [인용된 문항]'
        q['explanation'] = '인용된 문항의 정답이 유일하지 않다. 이를 지적한 A가 맞다.'
        self.assertNotIn('explanation_admits_invalid_question', codes(q))

    def test_distractor_explicitly_called_correct_is_caught(self):
        q = mcq(); q['options'][2]['explanation'] = '정답이다. 같은 영역을 올바르게 나타낸다.'
        self.assertIn('distractor_marked_correct', codes(q))

    def test_partial_truth_in_distractor_is_not_confused_with_answer(self):
        q = mcq()
        q['options'][2]['explanation'] = '첫 조건은 옳다. 다만 두 번째 조건이 틀리므로 정답이 아니다.'
        self.assertNotIn('distractor_marked_correct', codes(q))
        q['stem'] = '옳지 않은 것은?'
        q['options'][0]['explanation'] = '틀리다. 보존 조건을 충족하지 않는다.'
        self.assertFalse(codes(q))

    def test_non_string_and_partial_input_are_safe(self):
        for value in [None, [], {}, {'type': 'mcq'}, {'type': 'word', 'answer': 4},
                      {'type': 'mcq', 'options': 1, 'keyPoints': True}]:
            self.assertEqual(local_issues(value), [])
        self.assertEqual(quality_text(None), '')
        self.assertEqual(quality_text(' Ａ \n  B '), 'A B')


if __name__ == '__main__':
    unittest.main()
