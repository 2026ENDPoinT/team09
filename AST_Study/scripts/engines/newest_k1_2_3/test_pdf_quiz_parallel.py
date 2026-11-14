"""Event-driven regression checks for the bounded quiz generation scheduler."""
from contextlib import contextmanager
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pdf_quiz as quiz
from pdf_ai import BudgetExceeded
from test_pdf_quiz import fixture, planned, question, review_passthrough


WAIT_SECONDS = 4


def plan_for_groups(count):
    return {'allocations': [planned(
        {'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0},
        ids=['c' + str(index + 1)], uid='unit-' + str(index))['allocations'][0]
        for index in range(count)], 'unallocated': 0, 'reason': ''}


def answer_for(payload, stem=None):
    cid = payload['assignment']['conceptIds'][0]
    return {'questions': [question(cid=cid, stem=stem or cid + '의 조건 확인')],
            'unfilled': 0, 'reason': ''}


class ConcurrentProvider:
    """A fake provider with the production thread-local context and ledger lock."""
    def __init__(self, plan, answer):
        self.plan = plan
        self.answer = answer
        self._lock = threading.RLock()
        self._thread_context = threading.local()
        self.ledger = {'requests': []}
        self.billing = None
        self.calls = []
        self.active = 0
        self.peak_active = 0
        self.started = []
        self.completion_order = []
        self.finished = {}
        self.state_changed = threading.Condition(self._lock)

    @property
    def context(self):
        return getattr(self._thread_context, 'value', {})

    @context.setter
    def context(self, value):
        self._thread_context.value = value

    def wait_started(self, count):
        with self.state_changed:
            return self.state_changed.wait_for(lambda: len(self.started) >= count, WAIT_SECONDS)

    def complete(self, payload, **options):
        context = dict(self.context)
        entry = {'state': 'reserved', 'reservedUsd': .01, 'kind': context.get('kind')}
        planning = payload.get('task') == 'quiz_plan'
        uid = None if planning else payload['assignment']['unitId']
        with self.state_changed:
            self.calls.append((copy.deepcopy(payload), copy.deepcopy(options), context))
            self.ledger['requests'].append(entry)
            if not planning:
                self.started.append(uid)
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                self.finished[uid] = threading.Event()
            self.state_changed.notify_all()
        not_sent = False
        try:
            return copy.deepcopy(self.plan) if planning else self.answer(payload)
        except BudgetExceeded:
            not_sent = True
            raise
        finally:
            with self.state_changed:
                entry.update(state='not_sent' if not_sent else 'settled',
                             estimatedUsd=0 if not_sent else .01,
                             usage={} if not_sent else {'prompt_tokens': 100, 'completion_tokens': 20})
                if not planning:
                    self.active -= 1
                    self.completion_order.append(uid)
                    self.finished[uid].set()
                self.state_changed.notify_all()


class QuizParallelTests(unittest.TestCase):
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

    @contextmanager
    def running(self, document, request, provider, release, saved=None):
        holder = {}
        real_write = quiz.write_json

        def persist(path, value):
            real_write(path, value)
            if saved is not None:
                saved(value)

        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch.object(quiz, 'write_json', side_effect=persist):
            folder = Path(directory)

            def work():
                try:
                    holder['result'] = quiz.generate(folder, document, request, provider)
                except BaseException as error:
                    holder['error'] = error

            thread = threading.Thread(target=work, name='quiz-parallel-test-run', daemon=True)
            thread.start()
            try:
                yield holder, folder
            finally:
                release()
                thread.join(WAIT_SECONDS + 2)
                self.assertFalse(thread.is_alive(), 'scheduler did not drain its workers')
            if 'error' in holder:
                raise holder['error']

    def test_ten_calls_overlap_and_eleventh_waits_for_a_slot(self):
        document, request = fixture(12, ['ox'], size=12)
        release = threading.Event()

        def answer(payload):
            if not release.wait(WAIT_SECONDS):
                raise RuntimeError('test gate timed out')
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(12), answer)
        with self.running(document, request, provider, release.set) as (holder, _):
            self.assertTrue(provider.wait_started(10), 'ten workers must enter concurrently')
            with provider._lock:
                self.assertEqual(len(provider.started), 10)
                self.assertEqual(provider.active, 10)
                self.assertEqual(provider.peak_active, 10)
            release.set()
        result = holder['result']
        self.assertEqual(len(result['questions']), 12)
        self.assertEqual(provider.peak_active, 10)
        self.assertEqual(len(provider.started), 12)
        self.assertEqual(len(provider.calls), 13)
        self.assertEqual(result['unfilled'], 0)
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .13)
        for payload, _, context in provider.calls[1:]:
            self.assertEqual(context['kind'], 'quiz_questions')
            self.assertEqual(context['quizUnitId'], payload['assignment']['unitId'])
            self.assertNotIn('totalCount', payload['request'])
        self.assertEqual(len({str(call[0]['previousTargets']) for call in provider.calls[1:]}), 1)

    def test_reverse_completion_keeps_plan_order(self):
        document, request = fixture(4, ['ox'], size=4)
        gates = [threading.Event() for _ in range(4)]

        def answer(payload):
            index = int(payload['assignment']['unitId'].split('-')[-1])
            if not gates[index].wait(WAIT_SECONDS):
                raise RuntimeError('test gate timed out')
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(4), answer)
        with self.running(document, request, provider, lambda: [gate.set() for gate in gates]) as (holder, _):
            self.assertTrue(provider.wait_started(4))
            for index in range(3, -1, -1):
                gates[index].set()
                self.assertTrue(provider.finished['unit-' + str(index)].wait(WAIT_SECONDS))
        self.assertEqual(provider.completion_order, ['unit-3', 'unit-2', 'unit-1', 'unit-0'])
        self.assertEqual([q['conceptIds'] for q in holder['result']['questions']],
                         [['c1'], ['c2'], ['c3'], ['c4']])
        self.assertEqual([a['unitId'] for a in holder['result']['executionAssignments']],
                         ['unit-0', 'unit-1', 'unit-2', 'unit-3'])

    def test_one_failed_group_does_not_discard_other_completed_questions(self):
        document, request = fixture(4, ['ox'], size=4)

        def answer(payload):
            if payload['assignment']['unitId'] == 'unit-1':
                raise RuntimeError('simulated response error')
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(4), answer)
        with self.running(document, request, provider, lambda: None) as (holder, _):
            pass
        result = holder['result']
        self.assertEqual([q['conceptIds'] for q in result['questions']], [['c1'], ['c3'], ['c4']])
        self.assertEqual(result['unfilled'], 1)
        self.assertEqual(result['errors'][0]['unitId'], 'unit-1')
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .05)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 0)

    def test_duplicates_and_surplus_are_published_across_parallel_results(self):
        document, request = fixture(4, ['ox'], size=4)

        def answer(payload):
            cid = payload['assignment']['conceptIds'][0]
            if cid == 'c1':
                return {'questions': [question(cid=cid, stem='같은 판단'),
                                      question(cid=cid, stem='초과 문항')], 'unfilled': 0, 'reason': ''}
            if cid == 'c2':
                return answer_for(payload, '같은 판단')
            if cid == 'c3':
                return {'questions': [question('mcq', cid=cid)], 'unfilled': 0, 'reason': ''}
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(4), answer)
        with self.running(document, request, provider, lambda: None) as (holder, _):
            pass
        result = holder['result']
        self.assertEqual(len(result['questions']), 5)
        self.assertEqual(sum(q['stem'] == '같은 판단' for q in result['questions']), 2)
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(len(provider.calls), 5)
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .05)

    def test_cancel_stops_new_submissions_and_drains_started_responses(self):
        document, request = fixture(12, ['ox'], size=12)
        release = threading.Event()
        first = threading.Event()
        stopped = threading.Event()

        def answer(payload):
            gate = first if payload['assignment']['unitId'] == 'unit-0' else release
            if not gate.wait(WAIT_SECONDS):
                raise RuntimeError('test gate timed out')
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(12), answer)
        def saved(value):
            if value.get('cancelled'):
                stopped.set()
        with self.running(document, request, provider, lambda: (first.set(), release.set()), saved) as (holder, folder):
            self.assertTrue(provider.wait_started(10))
            (folder / 'cancel').write_text('cancel')
            first.set()
            self.assertTrue(stopped.wait(WAIT_SECONDS), 'cancel must be persisted before in-flight calls finish')
            with provider._lock:
                self.assertEqual(len(provider.started), 10)
            release.set()
        result = holder['result']
        self.assertTrue(result['cancelled'])
        self.assertEqual(len(provider.started), 10)
        self.assertEqual(len(result['questions']), 10)
        self.assertFalse(result['candidateQuestions'])
        self.assertEqual(result['unfilled'], 2)
        self.review.assert_not_called()
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .11)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 0)

    def test_budget_stop_does_not_submit_remaining_groups(self):
        document, request = fixture(12, ['ox'], size=12)
        release = threading.Event()
        first = threading.Event()
        stopped = threading.Event()

        def answer(payload):
            if payload['assignment']['unitId'] == 'unit-0':
                if not first.wait(WAIT_SECONDS):
                    raise RuntimeError('test gate timed out')
                provider.billing = SimpleNamespace(exhausted=True)
                raise BudgetExceeded('budget reached')
            if not release.wait(WAIT_SECONDS):
                raise RuntimeError('test gate timed out')
            return answer_for(payload)

        provider = ConcurrentProvider(plan_for_groups(12), answer)
        def saved(value):
            if value.get('budgetStopped'):
                stopped.set()
        with self.running(document, request, provider, lambda: (first.set(), release.set()), saved) as (holder, _):
            self.assertTrue(provider.wait_started(10))
            first.set()
            self.assertTrue(stopped.wait(WAIT_SECONDS), 'budget stop must be persisted before drain')
            with provider._lock:
                self.assertEqual(len(provider.started), 10)
            release.set()
        result = holder['result']
        self.assertTrue(result['budgetStopped'])
        self.assertTrue(result['creditStopped'])
        self.assertEqual(len(provider.started), 10)
        self.assertEqual(len(result['questions']), 9)
        self.assertFalse(result['candidateQuestions'])
        self.assertEqual(result['unfilled'], 3)
        self.review.assert_not_called()
        self.assertAlmostEqual(result['runUsage']['usageBasedUsd'], .10)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 0)


if __name__ == '__main__':
    unittest.main()
