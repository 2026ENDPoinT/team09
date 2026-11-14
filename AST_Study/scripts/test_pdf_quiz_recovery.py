"""Quiz recovery checks across planning, generation, diagnostics and billing."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
from test_pdf_quiz import FakeProvider, fixture, planned, question, review_passthrough


class QuizRecoveryTests(unittest.TestCase):
    def setUp(self):
        review_patch = patch.object(quiz, 'review_candidates', side_effect=review_passthrough, create=True)
        self.review = review_patch.start()
        self.addCleanup(review_patch.stop)
        transport_patch = patch.object(quiz, 'pack_generation_jobs', side_effect=lambda assignments, *unused: assignments)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)
        wire_patch = patch.object(quiz, 'wire_generation_payload', side_effect=lambda payload: (payload, {}))
        wire_patch.start()
        self.addCleanup(wire_patch.stop)

    def test_miscalculated_plan_continues_without_another_planner_call(self):
        document, request = fixture(10, size=5)
        plan = {'allocations': [planned(
            {'ox': weight, 'mcq': 0, 'word': 0, 'essay': 0},
            ids=['c' + str(i + 1)], uid='related-' + str(i))['allocations'][0]
            for i, weight in enumerate([3, 3, 3, 2, 2])],
            'unallocated': 0, 'reason': ''}
        original = copy.deepcopy(plan)

        def answers(payload):
            assignment = payload['assignment']
            cid = assignment['conceptIds'][0]
            count = sum(assignment['counts'].values())
            return {'questions': [question(cid=cid, stem=cid + '의 조건 확인 ' + str(i))
                                  for i in range(count)], 'unfilled': 0, 'reason': ''}

        provider = FakeProvider([plan] + [answers] * 5)
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(result['rawPlan'], original)
        self.assertEqual(plan, original)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(len(result['questions']), 10)
        self.assertEqual(len(result['executionAssignments']), 5)
        self.assertEqual([call[2]['kind'] for call in provider.calls].count('quiz_plan'), 1)
        self.assertEqual(len(provider.calls), 6)
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .06)
        self.assertEqual(result['planAdjustment'], {'allocatedBefore': 13, 'allocatedAfter': 10})
        self.assertEqual(result['errors'], [])

    def test_invalid_scope_preserves_raw_plan_and_explains_failure(self):
        document, request = fixture(2)
        raw = planned(ids=['not-provided'])
        provider = FakeProvider([raw])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(result['rawPlan'], raw)
        self.assertEqual(result['unfilled'], 2)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['errors'][0]['stage'], 'planning')
        self.assertEqual(result['errors'][0]['errorType'], 'ValueError')
        self.assertIn('개념 범위', result['reason'])
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .01)

    def test_arbitrary_transport_exception_text_is_not_exposed(self):
        document, request = fixture(1)
        provider = FakeProvider([RuntimeError('sk-private-credential response body')])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertNotIn('sk-private', str(result['errors']))
        self.assertNotIn('response body', result['reason'])
        self.assertIn('RuntimeError', result['reason'])

    def test_generation_miscount_keeps_valid_items_without_retry(self):
        document, request = fixture(3, ['ox'])
        provider = FakeProvider([
            planned({'ox': 3, 'mcq': 0, 'word': 0, 'essay': 0}),
            {'questions': [question(stem='조건 확인 1'), question(stem='조건 확인 2')],
             'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual(len(result['questions']), 2)
        self.assertEqual(result['unfilled'], 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn('응답 수량', result['reason'])

    def test_generation_keeps_readable_surplus_without_quota_filtering(self):
        document, request = fixture(1, ['ox'])
        provider = FakeProvider([
            planned({'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}),
            {'questions': [question(stem='조건 확인 1'), question('mcq'), question(stem='조건 확인 2')],
             'unfilled': 0, 'reason': ''}])
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'):
            result = quiz.generate(Path(directory), document, request, provider)
        self.assertEqual([q['type'] for q in result['questions']], ['ox', 'mcq', 'ox'])
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(len(provider.calls), 2)


if __name__ == '__main__':
    unittest.main()
