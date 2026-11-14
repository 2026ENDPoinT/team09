"""No paid reviewer; durable publication and single-pass generation from valid sources."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
from pdf_ai import BudgetExceeded
from test_pdf_quiz import fixture, planned, question
from test_pdf_quiz_parallel import ConcurrentProvider


def answers(payload, limit=None):
    assignment = payload['assignment']
    items = []
    for unit in assignment.get('units', [assignment]):
        cid = unit['conceptIds'][0]
        for kind, amount in unit['counts'].items():
            for index in range(amount):
                item = question(kind, cid=cid, stem=f"{unit['unitId']} · {kind} · 판단 {index}")
                item['unitId'] = unit['unitId'];items.append(item)
    return {'questions': items if limit is None else items[:limit], 'unfilled': 0, 'reason': ''}


class DirectCompletionTests(unittest.TestCase):
    def run_quiz(self, count, answer, *, groups=1, allowed=None, snapshots=None,
                 transform_plan=None, provider_class=ConcurrentProvider):
        document, request = fixture(count, allowed or ['ox'], size=max(2, groups))
        allocations = []
        for index in range(groups):
            amount = count//groups + (index < count % groups)
            allocations += planned({'ox': amount, 'mcq': 0, 'word': 0, 'essay': 0},
                                   ids=['c'+str(index+1)], uid='u'+str(index+1))['allocations']
        plan = {'allocations': allocations, 'unallocated': 0, 'reason': ''}
        if transform_plan:
            plan = transform_plan(plan)
        provider = provider_class(plan, answer)
        real_write = quiz.write_json
        def persist(path, value):
            real_write(path, value)
            if snapshots is not None:
                snapshots.append(copy.deepcopy(value))
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch.object(quiz, 'write_json', side_effect=persist):
            result = quiz.generate(Path(directory), document, request, provider)
            saved = json.loads((Path(directory)/'generated/quiz-v2/latest.json').read_text())
        self.assertEqual(saved['questions'], result['questions'])
        self.assertFalse(any(c[0].get('task') == 'quiz_review' for c in provider.calls))
        self.assertEqual(result['quality']['status'], 'disabled')
        self.assertEqual(result['runUsage']['byKind']['quiz_review']['requests'], 0)
        return result, provider

    def test_100_requested_79_returned_are_published_without_topups(self):
        state = {'initial': 0}
        def answer(payload):
            full = answers(payload)
            if 'completion' not in payload:
                # Return 79 across the configured initial batches, never a refill.
                with lock:
                    keep = min(len(full['questions']), max(0, 79-state['initial']))
                    state['initial'] += keep
                return {**full, 'questions': full['questions'][:keep]}
            return full
        import threading
        lock = threading.Lock();snapshots = []
        result, provider = self.run_quiz(100, answer, snapshots=snapshots)
        self.assertEqual((len(result['questions']), result['unfilled']), (79, 21))
        self.assertEqual(result['refillRounds'], 0)
        self.assertFalse(result['processingComplete'])
        self.assertTrue(any(0 < len(s['questions']) < 100 for s in snapshots))
        self.assertTrue(all(not s['candidateQuestions'] for s in snapshots))
        initial = [r for r in result['generationAudit'] if r['round'] == 0]
        self.assertEqual(sum(r['accepted'] for r in initial), 79)
        refill = [c[0] for c in provider.calls if c[0].get('completion')]
        self.assertFalse(refill)
        self.assertEqual(len(provider.calls), 1 + (100 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS)

    def test_unproductive_scope_does_not_trigger_reallocation(self):
        def answer(payload):
            a = payload['assignment']
            if 'units' in a:
                # Initial second logical scope refuses, despite a zero unfilled claim.
                good = copy.deepcopy(payload);good['assignment'] = a['units'][0]
                return answers(good)
            if a['conceptIds'] == ['c2']:
                return {'questions': [], 'unfilled': sum(a['counts'].values()), 'reason': '자료 부족'}
            return answers(payload)
        result, provider = self.run_quiz(8, answer, groups=2)
        self.assertEqual((len(result['questions']), result['unfilled']), (4, 4))
        self.assertEqual(result['refillRounds'], 0)
        final_calls = [p for p, _, _ in provider.calls if p.get('completion', {}).get('round') == 2]
        self.assertFalse(final_calls)
        self.assertEqual(len(provider.calls), 1 + (8 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS)

    def test_duplicate_is_published_and_invalid_source_is_not_retried(self):
        def answer(payload):
            value = answers(payload)
            if 'completion' not in payload:
                value['questions'][1]['stem'] = value['questions'][0]['stem']
                value['questions'][2]['evidence'][0]['quote'] = '자료에 없는 문장'
            return value
        result, _ = self.run_quiz(4, answer)
        self.assertEqual(len(result['questions']), 4)
        self.assertEqual(len({q['stem'] for q in result['questions']}), 3)
        self.assertEqual(len(result['generationAudit'][0]['issues']), 1)

    def test_uneven_option_length_no_longer_excludes_a_generated_question(self):
        def mcq_plan(plan):
            plan['allocations'][0]['counts'] = {'ox': 0, 'mcq': 1, 'word': 0, 'essay': 0}
            return plan
        def answer(payload):
            value = answers(payload)
            value['questions'][0]['options'][0]['text'] = '자료에 명시된 여러 조건을 길게 설명한 선택지이다. ' * 5
            return value
        result, provider = self.run_quiz(1, answer, allowed=['mcq'], transform_plan=mcq_plan)
        self.assertEqual((len(result['questions']), result['unfilled']), (1, 0))
        self.assertEqual((len(provider.calls), result['quality']['rejected']), (2, 0))

    def test_missing_question_does_not_start_a_paid_topup(self):
        def answer(payload):
            if 'completion' in payload:
                raise BudgetExceeded('test limit')
            return answers(payload, 3)
        result, _ = self.run_quiz(4, answer)
        self.assertEqual((len(result['questions']), result['unfilled']), (3, 1))
        self.assertFalse(result.get('budgetStopped', False))
        self.assertFalse(result['processingComplete'])

    def test_empty_response_stops_immediately_with_explicit_reason(self):
        result, provider = self.run_quiz(1, lambda p: {'questions': [], 'unfilled': 1, 'reason': '자료 부족'})
        self.assertEqual(result['refillRounds'], 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result['completionStatus'], 'partial')
        self.assertTrue(result['completionStopReason'])

    def test_uncertain_usage_stops_paid_topups_without_hiding_finished_questions(self):
        class UnknownUsageProvider(ConcurrentProvider):
            def complete(self, payload, **options):
                result = super().complete(payload, **options)
                if payload['task'] == 'quiz_questions':
                    with self._lock:
                        self.ledger['requests'][-1].update(state='usage_unknown', usage={}, estimatedUsd=None)
                return result
        result, provider = self.run_quiz(4, lambda p: answers(p, 3), provider_class=UnknownUsageProvider)
        self.assertEqual((len(result['questions']), result['unfilled']), (3, 1))
        self.assertEqual((len(provider.calls), result['refillRounds']), (2, 0))
        self.assertIn('추가 호출 없이', result['completionStopReason'])
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 1)

    def test_no_cancellation_is_invented_for_an_unsent_topup(self):
        def answer(payload):
            if 'completion' in payload:
                raise InterruptedError('cancelled')
            return answers(payload, 3)
        result, _ = self.run_quiz(4, answer)
        self.assertEqual((len(result['questions']), result['unfilled']), (3, 1))
        self.assertFalse(result.get('cancelled', False))

    def test_fully_unallocated_plan_does_not_make_a_second_planner_or_topup_call(self):
        def empty_plan(plan):
            return {'allocations': [], 'unallocated': 8, 'reason': '초기 배분 부족'}
        result, provider = self.run_quiz(8, answers, transform_plan=empty_plan)
        self.assertEqual((len(result['questions']), result['unfilled']), (0, 8))
        self.assertEqual(len(provider.calls), 1)

    def test_split_batches_have_unique_payloads_and_do_not_refill_short_responses(self):
        def mixed(plan):
            plan['allocations'][0]['counts'] = dict.fromkeys(quiz.TYPES, 30)
            return plan
        def short(payload):
            value = answers(payload)
            if 'completion' not in payload:
                value['questions'] = value['questions'][:-1]
            return value
        result, provider = self.run_quiz(120, short, allowed=list(quiz.TYPES), transform_plan=mixed)
        from collections import Counter
        batch_count = (120 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS
        self.assertEqual(Counter(q['type'] for q in result['questions']),
                         Counter({'ox': 30, 'mcq': 30, 'word': 30, 'essay': 30 - batch_count}))
        self.assertEqual(result['refillRounds'], 0)
        self.assertEqual(len(provider.calls), 1 + batch_count)
        initial = [p['assignment']['unitId'] for p, _, _ in provider.calls if p['task'] == 'quiz_questions' and not p.get('completion')]
        self.assertEqual(len(initial), len(set(initial)))
        payloads = [json.dumps(p, sort_keys=True) for p, _, _ in provider.calls if p['task'] == 'quiz_questions']
        self.assertEqual(len(payloads), len(set(payloads)))

    def test_saved_choice_order_stays_fixed_when_an_earlier_batch_arrives_later(self):
        import threading
        first_saved = threading.Event()
        class Snapshots(list):
            def append(self, value):
                super().append(value)
                if value['questions'] and all(q['conceptIds'] == ['c2'] for q in value['questions']):
                    first_saved.set()
        def mcq_plan(plan):
            for unit in plan['allocations']:
                unit['counts'] = {'ox': 0, 'mcq': 10, 'word': 0, 'essay': 0}
            return plan
        def answer(payload):
            if payload['assignment']['conceptIds'] == ['c1']:
                if not first_saved.wait(4):
                    raise RuntimeError('test publication gate timed out')
            return answers(payload)
        snapshots = Snapshots()
        result, _ = self.run_quiz(20, answer, groups=2, allowed=['mcq'], snapshots=snapshots,
                                  transform_plan=mcq_plan)
        self.assertEqual(len(result['questions']), 20)
        self.assertTrue(first_saved.is_set())
        orders = {}
        for snapshot in snapshots:
            for item in snapshot['questions']:
                order = [o['id'] for o in item['options']]
                self.assertEqual(orders.setdefault(item['id'], order), order)

    def test_same_unit_source_owner_tag_can_be_repaired_but_other_units_cannot(self):
        doc, request = fixture(1)
        _, _, _, concepts, sources = quiz.context(doc, request)
        original = question()
        original['evidence'].append({'sourceId': 'study:c2:e1', 'quote': '핵심 정의 2'})
        fixed = quiz._question(original, planned(ids=['c1', 'c2'])['allocations'][0], concepts, sources)
        self.assertEqual(fixed['conceptIds'], ['c1', 'c2'])
        self.assertEqual(original['conceptIds'], ['c1'])
        with self.assertRaises(ValueError):
            quiz._question(original, planned(ids=['c1'])['allocations'][0], concepts, sources)


if __name__ == '__main__':
    unittest.main()
