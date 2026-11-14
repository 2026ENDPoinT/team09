"""Unsent budget recovery uses the same bounded producer and request pool."""
from collections import Counter
import threading
import time
import unittest

import pdf_ai as ai
import test_pdf_speed_pipeline as pipeline_fixture


class DeferredSchedulingTests(unittest.TestCase):
    def setUp(self):
        # Reuse the network-blocked integration fixture without discovering its
        # inherited tests again in this module.
        self.fixture = pipeline_fixture.CropPipelineTests(
            'test_first_request_starts_before_all_local_crops_finish')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.lock = threading.Lock()

    def grow(self, count):
        f = self.fixture
        f.blocks = [{**f.blocks[0], 'id': f'source{i}', 'page': i+1,
                     'planRole': 'teaching'} for i in range(count)]
        f.groups = [{'title': f'독립 주제{i}', 'blocks': [block]}
                    for i, block in enumerate(f.blocks)]
        f.document['pages'] = [
            {'number': i+1, 'label': str(i+1), 'nativeText': block['text']}
            for i, block in enumerate(f.blocks)]

    def run_pipeline(self, complete, *, count=3, provider=None):
        self.grow(count)
        return self.fixture.run_pipeline(
            lambda source: None, complete, provider=provider, worker_limit=14,
            wire_options={'SOURCE_FACTS': False, 'VISUAL_TEACHING': False,
                          'SOURCE_COVERAGE_HINT': False, 'IMAGE_REGION_LABELS': False,
                          'COMPACT_TABLE_SETUP': False})

    def test_recovered_twenty_jobs_fill_fourteen_and_never_resend_the_first_paid_job(self):
        count = 20
        deferred_ready = threading.Event()
        all_slots = threading.Event()
        recovery = threading.Event()
        attempts = Counter()
        state = {'deferred': 0, 'active': 0, 'maximum': 0, 'paid': 0}

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            with self.lock:
                attempts[source] += 1
                first = attempts[source] == 1
            if source == 'source0' and first:
                self.assertTrue(deferred_ready.wait(3))
                recovery.set()
                with self.lock: state['paid'] += 1
                return self.fixture.reply(source)
            if first:
                with self.lock:
                    state['deferred'] += 1
                    if state['deferred'] == count-1: deferred_ready.set()
                raise ai.BudgetExceeded('Only an unsettled reservation blocks admission')
            self.assertTrue(recovery.is_set())
            with self.lock:
                state['active'] += 1
                state['maximum'] = max(state['maximum'], state['active'])
                if state['active'] == 14: all_slots.set()
            # This barrier distinguishes bounded refill from serial recovery.
            self.assertTrue(all_slots.wait(1), 'Recovery did not fill 14 available slots')
            time.sleep(.01)
            with self.lock:
                state['active'] -= 1
                state['paid'] += 1
            return self.fixture.reply(source)

        result, _ = self.run_pipeline(complete, count=count)
        self.assertTrue(result['processingComplete'])
        self.assertEqual(state['maximum'], 14)
        self.assertEqual(state['paid'], count)
        self.assertEqual(attempts['source0'], 1)
        self.assertTrue(all(attempts[f'source{i}'] == 2 for i in range(1, count)))
        self.assertEqual(sum(event == 'unit_ready' for event, _ in self.fixture.events), count)

    def test_a_round_with_no_completion_or_settlement_stops_without_spinning(self):
        attempts = Counter()

        def complete(payload, **kwargs):
            attempts[payload['blocks'][0]['id']] += 1
            raise ai.BudgetExceeded('No request can fit')

        result, _ = self.run_pipeline(complete)
        self.assertFalse(result['processingComplete'])
        self.assertEqual(attempts, Counter({'source0': 2, 'source1': 2, 'source2': 2}))
        self.assertEqual(len(result['failedUnits']), 3)
        self.assertTrue(all(row['error'] == 'BudgetExceeded' for row in result['failedUnits']))

    def test_initial_pool_refills_before_the_other_thirteen_finish(self):
        self.assert_refills_without_batch_barrier(recover=False)

    def test_recovery_pool_refills_before_the_other_thirteen_finish(self):
        self.assert_refills_without_batch_barrier(recover=True)

    def assert_refills_without_batch_barrier(self, *, recover):
        # Peak concurrency alone cannot distinguish a batch barrier.
        attempts = Counter()
        first_fourteen = threading.Event()
        release_thirteen = threading.Event()
        fifteenth_started = threading.Event()
        state = {'sent': 0, 'active': 0, 'maximum': 0,
                 'blocked': 0, 'blockedAtFifteenth': None}

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            with self.lock:
                attempts[source] += 1
                if recover and attempts[source] == 1:
                    raise ai.BudgetExceeded('Unsent; recovery is required')
                state['sent'] += 1
                ordinal = state['sent']
                state['active'] += 1
                state['maximum'] = max(state['maximum'], state['active'])
                if 2 <= ordinal <= 14:
                    state['blocked'] += 1
                if ordinal == 14:
                    first_fourteen.set()
            try:
                if ordinal == 1:
                    self.assertTrue(first_fourteen.wait(3))
                elif 2 <= ordinal <= 14:
                    self.assertTrue(release_thirteen.wait(3),
                                    'The pool waited for a whole batch')
                elif ordinal == 15:
                    with self.lock:
                        state['blockedAtFifteenth'] = state['blocked']
                    fifteenth_started.set()
                    release_thirteen.set()
                return self.fixture.reply(source)
            finally:
                with self.lock:
                    state['active'] -= 1
                    if 2 <= ordinal <= 14:
                        state['blocked'] -= 1

        result, _ = self.run_pipeline(complete, count=20)
        self.assertTrue(result['processingComplete'])
        self.assertTrue(fifteenth_started.is_set())
        self.assertEqual(state['blockedAtFifteenth'], 13)
        self.assertEqual(state['maximum'], 14)
        self.assertEqual(state['sent'], 20)

    def test_early_settlement_refills_unfunded_work_before_eleven_paid_tails_finish(self):
        attempts=Counter();paid=Counter()
        all_initial_attempts=threading.Event()
        first_settled=threading.Event()
        release_tails=threading.Event()
        resumed_before_tails=threading.Event()
        state={'initial':0,'active':0,'maximum':0,'blocked':0}

        def complete(payload, **kwargs):
            source=payload['blocks'][0]['id']
            with self.lock:
                attempts[source]+=1
                first=attempts[source]==1
                if first:
                    state['initial']+=1
                    ordinal=state['initial']
                    if ordinal==16:all_initial_attempts.set()
                else:ordinal=None
            if first and ordinal>12:
                raise ai.BudgetExceeded('The first twelve reservations fill the money cap')
            if not first:
                self.assertTrue(first_settled.is_set())
                with self.lock:
                    if state['blocked']==11 and not release_tails.is_set():
                        resumed_before_tails.set()
                # Only a newly funded, previously unsent call releases the
                # long paid tails. A drain-all barrier cannot pass this test.
                release_tails.set()
            with self.lock:
                state['active']+=1
                state['maximum']=max(state['maximum'],state['active'])
                paid[source]+=1
                if first and ordinal!=1:state['blocked']+=1
            try:
                if first and ordinal==1:
                    self.assertTrue(all_initial_attempts.wait(3))
                    first_settled.set()
                elif first:
                    self.assertTrue(release_tails.wait(3),
                                    'Unsent work waited for all paid tails')
                return self.fixture.reply(source)
            finally:
                with self.lock:
                    state['active']-=1
                    if first and ordinal!=1:state['blocked']-=1

        result,_=self.run_pipeline(complete,count=16)
        self.assertTrue(result['processingComplete'])
        self.assertTrue(resumed_before_tails.is_set())
        self.assertLessEqual(state['maximum'],14)
        self.assertEqual(len(paid),16)
        self.assertTrue(all(value==1 for value in paid.values()))
        self.assertEqual(sorted(attempts.values()),[1]*12+[2]*4)

    def test_paid_transport_failure_is_not_requeued(self):
        attempts = Counter()

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            attempts[source] += 1
            if source == 'source0': raise ai.AiResponseError('Paid response is uncertain')
            if source == 'source1' and attempts[source] == 1:
                raise ai.BudgetExceeded('Unsent')
            return self.fixture.reply(source)

        result, _ = self.run_pipeline(complete)
        self.assertFalse(result['processingComplete'])
        self.assertEqual(attempts, Counter({'source1': 2, 'source0': 1, 'source2': 1}))
        self.assertEqual([row['error'] for row in result['failedUnits']], ['AiResponseError'])

    def test_credit_exhaustion_is_final_and_is_not_treated_as_transient_budget(self):
        attempts = Counter()

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']; attempts[source] += 1
            if source == 'source0': raise ai.CreditExceeded('Credits are exhausted')
            return self.fixture.reply(source)

        result, _ = self.run_pipeline(complete)
        self.assertEqual(attempts, Counter({'source0': 1, 'source1': 1, 'source2': 1}))
        self.assertEqual([row['error'] for row in result['failedUnits']], ['CreditExceeded'])

    def test_settled_but_invalid_response_allows_one_more_unfunded_round(self):
        attempts = Counter()
        all_first = threading.Event()
        allow_invalid = threading.Event()
        invalid_settled = threading.Event()
        state = {'first': 0, 'secondDeferred': 0}
        provider = None

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']
            with self.lock:
                attempts[source] += 1
                attempt = attempts[source]
                if attempt == 1:
                    state['first'] += 1
                    if state['first'] == 3: all_first.set()
            if attempt == 1:
                self.assertTrue(all_first.wait(3))
                raise ai.BudgetExceeded('Initial reservations block all jobs')
            if source == 'source0':
                self.assertTrue(allow_invalid.wait(3))
                with self.lock:
                    provider.ledger['requests'].append({
                        'requestId': 'fake-paid-invalid', 'state': 'settled',
                        'usage': {'prompt_tokens': 0, 'completion_tokens': 0},
                        'estimatedUsd': 0})
                invalid_settled.set()
                # This is a paid response with a validation failure, not an
                # unfunded attempt and therefore must not be sent a third time.
                return {'concepts': 'invalid'}
            if not invalid_settled.is_set():
                with self.lock:
                    state['secondDeferred'] += 1
                    if state['secondDeferred'] == 2: allow_invalid.set()
                raise ai.BudgetExceeded('Still blocked before the settlement')
            return self.fixture.reply(source)

        provider = pipeline_fixture.FakeProvider(complete)
        result, _ = self.run_pipeline(complete, provider=provider)
        self.assertFalse(result['processingComplete'])
        self.assertEqual(attempts['source0'], 2)
        self.assertTrue(any(attempts[source] == 3 for source in ('source1', 'source2')))
        self.assertEqual(len(result['failedUnits']), 1)
        self.assertEqual(result['failedUnits'][0]['error'], 'ValueError')

    def test_cancellation_during_recovery_escapes_instead_of_requeueing(self):
        attempts = Counter()

        def complete(payload, **kwargs):
            source = payload['blocks'][0]['id']; attempts[source] += 1
            if attempts[source] == 1: raise ai.BudgetExceeded('Unsent')
            if source == 'source0': raise InterruptedError('Cancelled')
            return self.fixture.reply(source)

        with self.assertRaises(InterruptedError):
            self.run_pipeline(complete)
        self.assertTrue(all(value <= 2 for value in attempts.values()))


if __name__ == '__main__':
    unittest.main()
