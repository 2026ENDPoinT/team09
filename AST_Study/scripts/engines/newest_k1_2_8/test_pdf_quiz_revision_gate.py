"""Offline bounded blind rechecks; revised drafts are never implicit approvals."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
import pdf_quiz_review as review
from pdf_ai import AiResponseError, BudgetExceeded, CreditExceeded
from test_pdf_quiz import FakeProvider, fixture, question
from test_pdf_quiz_review import approve, independent_solution, revision, verdict


class QuizRevisionGateTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.document, request = fixture(3, size=2)
        self.document['pages'][0]['nativeText'] = '원문 조건과 구별해야 할 판단 근거이다.'
        self.document['pages'][1]['nativeText'] = '둘째 개념의 원문 조건이다.'
        self.config, _, _, self.concepts, self.sources = quiz.context(self.document, request)
        images = patch.object(review, '_images', return_value=([], [], []))
        images.start()
        self.addCleanup(images.stop)
        # Keep the production gate enabled. The older suite isolates pass one.
        self.assertTrue(review.VERIFY_REVISED_QUESTIONS)

    def candidates(self, kinds=('mcq',)):
        candidates, assignments = [], {}
        for index, kind in enumerate(kinds):
            assignment = {'unitId': 'unit-' + str(index), 'conceptIds': ['c1'],
                          'counts': {t: int(t == kind) for t in quiz.TYPES}, 'focus': '조건 비교'}
            raw = question(kind, stem=f'{index}번의 주어진 조건을 판단하시오.')
            candidate = quiz._question(raw, assignment, self.concepts, self.sources)
            candidate['id'] = 'candidate-' + str(index)
            candidates.append(candidate)
            assignments[candidate['id']] = assignment
        return candidates, assignments

    @staticmethod
    def replacement(candidate):
        value = revision(candidate)
        value['stem'] = '수정된 ' + candidate['id'] + ' 사례의 조건을 판단하시오.'
        value['explanation'] = '재검증 전의 교정본 해설이다.'
        return value

    def first_pass(self, candidates, revised_ids):
        by_id = {q['id']: q for q in candidates}

        def answer(payload):
            self.assertTrue(payload['editingAllowed'])
            rows = []
            for row in payload['candidates']:
                if row['id'] in revised_ids:
                    rows.append(verdict(row, decision='revise', issues=['wording'],
                                        replacement=self.replacement(by_id[row['id']])))
                else:
                    rows.append(verdict(row))
            return {'reviews': rows}

        return answer

    def run_review(self, candidates, assignments, provider, progress):
        def record(accepted, audit):
            progress.append((copy.deepcopy(accepted), copy.deepcopy(audit)))

        return review.review_candidates(self.folder, self.document, self.config, candidates,
            self.concepts, self.sources, provider, assignments, set(), on_progress=record)

    def test_unchanged_keep_requires_only_one_review_call(self):
        candidates, assignments = self.candidates()
        provider = FakeProvider([approve])
        progress = []
        accepted, audit = self.run_review(candidates, assignments, provider, progress)
        self.assertEqual([q['id'] for q in accepted], ['candidate-0'])
        self.assertEqual((audit['accepted'], audit['revised'], audit['calls']), (1, 0, 1))
        self.assertNotIn('revisionRecheck', audit)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(audit['reviews'][0]['publicationDecision'], 'accept')

    def test_revisions_stay_private_until_one_batched_blind_recheck_passes(self):
        candidates, assignments = self.candidates(('mcq', 'mcq', 'mcq'))
        original = copy.deepcopy(candidates)
        revised_ids = {'candidate-1', 'candidate-2'}
        progress = []

        def second_pass(payload):
            self.assertFalse(payload['editingAllowed'])
            self.assertEqual({row['id'] for row in payload['candidates']}, revised_ids)
            for row in payload['candidates']:
                self.assertNotIn('answer', row['question'])
                self.assertNotIn('explanation', row['question'])
                self.assertNotIn('keyPoints', row['question'])
                self.assertTrue(all(set(option) == {'id', 'text'} for option in row['question']['options']))
            return approve(payload)

        provider = FakeProvider([self.first_pass(candidates, revised_ids), second_pass])
        accepted, audit = self.run_review(candidates, assignments, provider, progress)
        first_accepted, first_audit = progress[0]
        self.assertEqual([q['id'] for q in first_accepted], ['candidate-0'])
        self.assertEqual([row['publicationDecision'] for row in first_audit['reviews']],
                         ['accept', 'pending_recheck', 'pending_recheck'])
        self.assertEqual({q['id'] for q in accepted}, {q['id'] for q in candidates})
        self.assertEqual((audit['accepted'], audit['revised'], audit['rejected'], audit['calls']), (3, 2, 0, 2))
        self.assertEqual(audit['revisionRecheck']['calls'], 1)
        self.assertTrue(all(row['publicationDecision'] == 'accept' for row in audit['reviews']))
        self.assertTrue(all(q['explanation'] == '독립 풀이로 조건과 원문을 대조한 결과이다.' for q in accepted))
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(candidates, original)
        self.assertEqual(provider.context, {})

    def test_second_pass_cannot_revise_again_or_start_a_third_call(self):
        candidates, assignments = self.candidates(('mcq', 'mcq'))
        revised_ids = {'candidate-1'}

        def needs_more_work(payload):
            self.assertFalse(payload['editingAllowed'])
            return {'reviews': [verdict(row, decision='revise', issues=['still_wrong'],
                replacement=self.replacement(candidates[1])) for row in payload['candidates']]}

        provider = FakeProvider([self.first_pass(candidates, revised_ids), needs_more_work,
                                 AssertionError('a third paid call must never start')])
        progress = []
        accepted, audit = self.run_review(candidates, assignments, provider, progress)
        self.assertEqual([q['id'] for q in accepted], ['candidate-0'])
        self.assertEqual((audit['accepted'], audit['revised'], audit['rejected'], audit['calls']), (1, 0, 1, 2))
        self.assertEqual(audit['reviews'][1]['publicationDecision'], 'reject')
        self.assertIn('새 교정', audit['revisionRecheck']['reviews'][0]['publicationReason'])
        self.assertEqual(len(provider.calls), 2)

    def test_second_pass_key_disagreement_rejects_instead_of_rekeying(self):
        candidates, assignments = self.candidates(('mcq', 'mcq'))

        def disagree(payload):
            row = payload['candidates'][0]
            return {'reviews': [verdict(row, correctOptionIds=['B'],
                solution=independent_solution(row['question'], answer='B'))]}

        provider = FakeProvider([self.first_pass(candidates, {'candidate-1'}), disagree,
                                 AssertionError('no third call')])
        progress = []
        accepted, audit = self.run_review(candidates, assignments, provider, progress)
        self.assertEqual([q['id'] for q in accepted], ['candidate-0'])
        self.assertEqual(audit['rejected'], 1)
        self.assertEqual(audit['revisionRecheck']['reviews'][0]['publicationDecision'], 'reject')
        self.assertIn('정답이 달라', audit['revisionRecheck']['reviews'][0]['publicationReason'])
        self.assertEqual(candidates[1]['answer'], 'A')
        self.assertEqual(len(provider.calls), 2)

    def test_unchanged_objective_key_conflicts_fail_closed_without_rekeying(self):
        for kind, bad_key in [('mcq', 'D'), ('ox', 'X')]:
            with self.subTest(kind=kind):
                candidates, assignments = self.candidates((kind,))
                candidates[0]['answer'] = bad_key
                provider = FakeProvider([approve, AssertionError('unexpected second call')])
                accepted, audit = self.run_review(candidates, assignments, provider, [])
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)
                self.assertEqual(audit['reviews'][0]['publicationDecision'], 'reject')
                self.assertIn('정답이 달라', audit['reviews'][0]['publicationReason'])
                self.assertEqual(candidates[0]['answer'], bad_key)
                self.assertEqual(len(provider.calls), 1)

    def test_recheck_transport_credit_or_budget_failure_preserves_safe_progress_without_retry(self):
        failures = [AiResponseError('synthetic review transport failure'),
                    RuntimeError('synthetic model failure'), BudgetExceeded('synthetic budget stop'),
                    CreditExceeded('synthetic depleted credit'), InterruptedError('synthetic cancellation')]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                candidates, assignments = self.candidates(('mcq', 'mcq'))
                provider = FakeProvider([self.first_pass(candidates, {'candidate-1'}), failure,
                                         AssertionError('a failed recheck must not retry')])
                progress = []
                with self.assertRaises(type(failure)):
                    self.run_review(candidates, assignments, provider, progress)
                self.assertEqual(len(provider.calls), 2)
                self.assertEqual(provider.context, {})
                self.assertTrue(progress)
                self.assertEqual([q['id'] for q in progress[-1][0]], ['candidate-0'])
                decisions = {row['questionId']: row['publicationDecision'] for row in progress[-1][1]['reviews']}
                self.assertEqual(decisions['candidate-0'], 'accept')
                self.assertEqual(decisions['candidate-1'], 'pending_recheck')

    def test_cancel_before_recheck_never_sends_second_request(self):
        candidates, assignments = self.candidates(('mcq', 'mcq'))
        provider = FakeProvider([self.first_pass(candidates, {'candidate-1'}),
                                 AssertionError('cancelled second call')])
        progress = []
        with patch.object(review, 'check_cancel', side_effect=[None, InterruptedError('cancel')]):
            with self.assertRaises(InterruptedError):
                self.run_review(candidates, assignments, provider, progress)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual([q['id'] for q in progress[-1][0]], ['candidate-0'])


if __name__ == '__main__':
    unittest.main()
