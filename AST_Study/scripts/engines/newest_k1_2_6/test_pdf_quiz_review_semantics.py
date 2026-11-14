"""Offline publication gates for difficulty, explicit premises and review budgets."""
import copy
import unittest
from unittest.mock import patch

import pdf_quiz_review as review
import test_pdf_quiz_review as fixtures


class QuizReviewSemanticTests(unittest.TestCase):
    setUp = fixtures.QuizReviewTests.setUp
    candidates = fixtures.QuizReviewTests.candidates
    run_review = fixtures.QuizReviewTests.run_review

    def test_direct_application_is_blocked_for_high_levels_despite_approval(self):
        for level in ('상', '최상'):
            with self.subTest(level=level):
                self.config['difficulty'] = level
                def reply(payload):
                    return {'reviews': [fixtures.verdict(payload['candidates'][0],
                        directApplicationOnly=True, difficultyAdequate=True,
                        reasoningTask='두 공식에 각각 수치를 대입한다.')]}
                accepted, audit, provider = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual((audit['rejected'], len(provider.calls)), (1, 1))
                self.assertIn('직접 적용', audit['reviews'][0]['publicationReason'])

    def test_direct_application_is_allowed_for_middle_levels(self):
        for level in ('중', '중상'):
            with self.subTest(level=level):
                self.config['difficulty'] = level
                def reply(payload):
                    return {'reviews': [fixtures.verdict(payload['candidates'][0],
                        directApplicationOnly=True)]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(len(accepted), 1)
                self.assertEqual(audit['rejected'], 0)

    def test_unstated_assumptions_block_every_level_despite_approval(self):
        for level in ('중', '중상', '상', '최상'):
            with self.subTest(level=level):
                self.config['difficulty'] = level
                def reply(payload):
                    return {'reviews': [fixtures.verdict(payload['candidates'][0],
                        unstatedAssumptions=['나무토막이 매달려 최고점에서 정지한다고 가정한다.'])]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertIn('필수 가정', audit['reviews'][0]['publicationReason'])

    def test_new_fields_must_have_explicit_types(self):
        for field, value in [('directApplicationOnly', None), ('directApplicationOnly', 'false'),
                             ('unstatedAssumptions', None), ('unstatedAssumptions', ''),
                             ('unstatedAssumptions', {}), ('unstatedAssumptions', [''])]:
            with self.subTest(field=field, value=value):
                def reply(payload):
                    return {'reviews': [fixtures.verdict(payload['candidates'][0], **{field: value})]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)
        for field in ('directApplicationOnly', 'unstatedAssumptions'):
            with self.subTest(missing=field):
                def missing(payload):
                    verdict = fixtures.verdict(payload['candidates'][0]); verdict.pop(field)
                    return {'reviews': [verdict]}
                accepted, _, _ = self.run_review([missing])
                self.assertEqual(accepted, [])

    def test_revision_flags_describe_replacement_after_conditions_are_added(self):
        candidates, assignments = self.candidates()
        candidates[0]['stem'] = '총알이 나무토막에 박힌 뒤 상승 높이로 입사 속력을 구하시오.'
        replacement = fixtures.revision(candidates[0])
        replacement['stem'] = ('가벼운 줄에 매단 나무토막이 최저점에 있을 때 총알이 수평으로 박힌다. '
            '충돌 중 수평 외부 충격량은 무시하며, 두 물체는 최고 높이 h에서 순간 정지한다. '
            '입사 속력을 구하시오.')
        def corrected(payload):
            return {'reviews': [fixtures.verdict(payload['candidates'][0], decision='revise',
                issues=['unstated_assumptions'], replacement=replacement,
                directApplicationOnly=False, unstatedAssumptions=[])]}
        with patch.object(review, 'VERIFY_REVISED_QUESTIONS', True):
            accepted, audit, provider = self.run_review([corrected, fixtures.approve], candidates, assignments)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['stem'], replacement['stem'])
        self.assertEqual(accepted[0]['id'], candidates[0]['id'])
        self.assertEqual((audit['revised'], len(provider.calls)), (1, 2))
        self.assertEqual(audit['revisionRecheck']['reviews'][0]['unstatedAssumptions'], [])

    def test_revision_with_remaining_assumption_or_direct_high_shortcut_is_blocked(self):
        candidates, assignments = self.candidates()
        replacement = fixtures.revision(candidates[0])
        changes = [{'unstatedAssumptions': ['최고점이라고 가정한다.']},
                   {'directApplicationOnly': True}]
        self.config['difficulty'] = '상'
        for change in changes:
            with self.subTest(change=change):
                def reply(payload):
                    return {'reviews': [fixtures.verdict(payload['candidates'][0], decision='revise',
                        issues=['draft_error'], replacement=copy.deepcopy(replacement), **change)]}
                accepted, audit, provider = self.run_review([reply], candidates, assignments)
                self.assertEqual(accepted, [])
                self.assertEqual((audit['rejected'], len(provider.calls)), (1, 1))

    def test_effort_and_output_allowance_use_math_or_high_difficulty(self):
        for level, math, effort, allowance in [
                ('중', False, 'low', 2100), ('중상', False, 'low', 2100),
                ('중', True, 'medium', 6000), ('중상', True, 'medium', 6000),
                ('상', False, 'medium', 6000), ('최상', False, 'medium', 6000)]:
            with self.subTest(level=level, mathematical=math):
                self.config['difficulty'] = level
                candidates, assignments = self.candidates()
                if math:
                    candidates[0]['stem'] = r'정적분 \(\int_0^1 x\,dx\)를 구하시오.'
                _, _, provider = self.run_review([fixtures.approve], candidates, assignments)
                self.assertEqual(provider.calls[0][2]['reasoningEffort'], effort)
                self.assertEqual(provider.calls[0][1]['max_output'], allowance)
                self.assertEqual(provider.context, {})

    def test_deep_output_allowance_caps_at_25000_and_low_budget_stays_unchanged(self):
        for level, math, expected, effort in [('최상', False, 25000, 'medium'),
                ('중', True, 25000, 'medium'), ('중', False, 19700, 'low')]:
            with self.subTest(level=level, mathematical=math):
                self.config['difficulty'] = level
                candidates, assignments = self.candidates(tuple(['mcq'] * 12))
                if math:
                    for i, candidate in enumerate(candidates):
                        candidate['stem'] = f'{i}번 정적분의 값을 구하시오.'
                accepted, _, provider = self.run_review([fixtures.approve], candidates, assignments)
                self.assertEqual(len(accepted), 12)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(provider.calls[0][1]['max_output'], expected)
                self.assertEqual(provider.calls[0][2]['reasoningEffort'], effort)


if __name__ == '__main__':
    unittest.main()
