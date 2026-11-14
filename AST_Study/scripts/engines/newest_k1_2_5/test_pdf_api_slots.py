"""Offline request-slot, cross-process rate admission and cancellation checks."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from unittest.mock import patch
import json
import multiprocessing
import os
import time
import unittest

import pdf_api_slots as slots


def _process_request(directory, arrivals):
    with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=900_000):
        arrivals.put(time.time())
        time.sleep(.01)


def _process_startup_requests(directory, ready, release, counter, peak, guard):
    with slots.startup_priority_slots(directory) as priority:
        def request(index):
            with slots.api_slot(directory=directory, priority=priority if index < 2 else None):
                with guard:
                    counter.value += 1
                    peak.value = max(peak.value, counter.value)
                ready.put(True)
                if not release.wait(8):
                    raise RuntimeError('offline startup test timed out')
                with guard:
                    counter.value -= 1
        with ThreadPoolExecutor(max_workers=9) as pool:
            list(pool.map(request, range(9)))


def _process_crashed_startup(directory, connection):
    with slots.startup_priority_slots(directory):
        connection.send(True)
        connection.close()
        os._exit(0)


def _hold(stack, manager):
    manager.__enter__()
    active = True
    def release():
        nonlocal active
        if active:
            active = False
            manager.__exit__(None, None, None)
    stack.callback(release)
    return release


def _cancel_wait():
    polls = 0
    def check():
        nonlocal polls
        polls += 1
        if polls == 2:
            raise InterruptedError('expected offline wait')
    return check


class ApiSlotsTest(unittest.TestCase):
    def test_waiting_input_estimate_refreshes_outside_rate_lock(self):
        with TemporaryDirectory() as directory, patch.object(slots, '_capacity', return_value=(100, 100)):
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=70):
                pass
            calls = []
            def estimate():
                # A provider snapshot must never run under the rate-state lock.
                guard = slots._handle(Path(directory) / 'rate-state.lock')
                try:
                    self.assertTrue(slots._try_lock(guard))
                    slots._unlock(guard)
                finally:
                    guard.close()
                calls.append(True)
                return 60 if len(calls) == 1 else 10
            with slots.api_slot(directory=directory, model='gpt-6-luna',
                                input_tokens=60, max_output=20, input_tokens_estimator=estimate):
                self.assertEqual(len(calls), 2)
                state = json.loads((Path(directory) / 'rate-state.json').read_text())
                self.assertEqual([r[1] for r in state['models']['gpt-6-luna']['requests']], [70, 20])
            self.assertEqual(len(calls), 2)  # admitted tickets are never recomputed

    def test_input_estimate_never_bypasses_output_ceiling_or_server_cap(self):
        with TemporaryDirectory() as directory, patch.object(slots, '_capacity', return_value=(100, 100)):
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=70):
                pass
            with self.assertRaises(InterruptedError):
                with slots.api_slot(check=_cancel_wait(), directory=directory, model='gpt-6-luna',
                                    input_tokens=60, max_output=40, count_parallel=False,
                                    input_tokens_estimator=lambda: 1):
                    self.fail('output ceiling must still block admission')
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual([r[1] for r in state['models']['gpt-6-luna']['requests']], [70])

    def test_invalid_or_failing_input_estimate_retains_original_bound(self):
        def broken():
            raise RuntimeError('no local estimate')
        for candidate in (lambda: -1, lambda: True, lambda: 700.0, lambda: 701, lambda: None, broken):
            with self.subTest(candidate=candidate), TemporaryDirectory() as directory:
                with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=700,
                                    max_output=100, input_tokens_estimator=candidate):
                    pass
                state = json.loads((Path(directory) / 'rate-state.json').read_text())
                self.assertEqual(state['models']['gpt-6-luna']['requests'][0][1], 700)

    def test_never_exceeds_shared_request_cap(self):
        with TemporaryDirectory() as directory, patch.object(slots, 'MAX_PARALLEL_REQUESTS', 4):
            active = peak = 0
            guard = Lock()

            def request(_):
                nonlocal active, peak
                with slots.api_slot(directory=Path(directory)):
                    with guard:
                        active += 1
                        peak = max(peak, active)
                    time.sleep(.03)
                    with guard:
                        active -= 1

            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(request, range(24)))
            self.assertEqual(peak, 4)
        self.assertEqual(slots.MAX_PARALLEL_REQUESTS, 14)

    def test_token_admission_is_shared_across_processes(self):
        # fork inherits this short test window; real operation always uses 60 s.
        if 'fork' not in multiprocessing.get_all_start_methods():
            self.skipTest('fork unavailable; pure scheduler checks still cover Windows')
        with TemporaryDirectory() as directory, patch.object(slots, 'RATE_WINDOW_SECONDS', .12), \
             patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'build'}):
            ctx = multiprocessing.get_context('fork')
            arrivals = ctx.Queue()
            processes = [ctx.Process(target=_process_request, args=(directory, arrivals)) for _ in range(3)]
            for process in processes:
                process.start()
            stamps = sorted(arrivals.get(timeout=5) for _ in processes)
            for process in processes:
                process.join(timeout=5)
                self.assertEqual(process.exitcode, 0)
            # 900k+900k cannot fit Build's 1.6M safety budget in one window.
            self.assertGreaterEqual(stamps[1] - stamps[0], .10)
            self.assertGreaterEqual(stamps[2] - stamps[1], .10)
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual(len(state['models']['gpt-6-luna']['requests']), 1)

    def test_cancel_while_waiting_does_not_admit_or_hold_slot(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'build'}):
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=1_000_000):
                pass
            attempts = 0

            def cancel():
                nonlocal attempts
                attempts += 1
                if attempts == 3:
                    raise InterruptedError('cancelled')

            with self.assertRaises(InterruptedError):
                with slots.api_slot(cancel, directory, model='gpt-6-luna', input_tokens=1_000_000):
                    self.fail('must not enter')
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual(len(state['models']['gpt-6-luna']['requests']), 1)
            # Waiting on the model budget did not occupy global network slots.
            with patch.object(slots, 'MAX_PARALLEL_REQUESTS', 1):
                with slots.api_slot(directory=directory):
                    pass

    def test_build_default_and_explicit_launch(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(slots._capacity('gpt-6-luna', {}), (1_600_000, 4000))
        with patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'launch'}):
            self.assertEqual(slots._capacity('gpt-6-luna', {}), (8_000_000, 8000))
        with patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'typo'}):
            self.assertEqual(slots._capacity('gpt-6-luna', {}), (1_600_000, 4000))

    def test_too_large_request_fails_before_network_and_without_record(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'build'}):
            with self.assertRaises(slots.RateLimitRequestTooLarge):
                with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=1_600_001):
                    self.fail('must not enter')
            self.assertFalse((Path(directory) / 'rate-state.json').exists())
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=100):
                pass

    def test_output_cap_is_reservation_max_not_sum(self):
        state = {'models': {}}
        with patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'build'}):
            state['models']['gpt-6-luna'] = {'requests': [[1000, 1_200_000]]}
            self.assertTrue(slots._allowed(state, 'gpt-6-luna', 400_000, 1000))
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 400_001, 1000))
        with TemporaryDirectory() as directory:
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=700, max_output=18000):
                pass
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual(state['models']['gpt-6-luna']['requests'][0][1], 18000)

    def test_window_expires_request_count_and_models_are_independent(self):
        state = {'models': {'gpt-6-luna': {'requests': [[1000, 5]],
                 'observed': {'limit_requests': 2}}}}
        self.assertFalse(slots._allowed(state, 'gpt-6-luna', 5, 1059.99))
        self.assertTrue(slots._allowed(state, 'gpt-6-sol', 5, 1059.99))
        self.assertTrue(slots._allowed(state, 'gpt-6-luna', 5, 1060))

    def test_headers_lower_tier_limit_and_track_other_client_pressure(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'launch'}), \
             patch.object(slots.time, 'time', return_value=1000):
            slots.observe_rate_limits('gpt-6-luna', {'X-RateLimit-Limit-Tokens': '100',
                'X-RateLimit-Limit-Requests': '20', 'X-RateLimit-Remaining-Tokens': '10',
                'X-RateLimit-Reset-Tokens': '1m2.5s', 'Authorization': 'never-store'}, directory)
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            record = state['models']['gpt-6-luna']
            self.assertEqual(slots._capacity('gpt-6-luna', record), (80, 16))
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 11, 1001))
            self.assertTrue(slots._allowed(state, 'gpt-6-luna', 10, 1001))
            record['requests'].append([1001, 7])
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 4, 1002))
            self.assertTrue(slots._allowed(state, 'gpt-6-luna', 11, 1063))
            self.assertNotIn('never-store', json.dumps(state))
            self.assertNotIn('Authorization', json.dumps(state))

    def test_project_headers_limit_independently_from_account_headers(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'SYNESIS_OPENAI_TIER': 'build'}), \
             patch.object(slots.time, 'time', return_value=1000):
            slots.observe_rate_limits('gpt-6-luna', {'x-ratelimit-limit-tokens': '2000000',
                'x-ratelimit-limit-project-tokens': '100',
                'x-ratelimit-remaining-tokens': '1900000',
                'x-ratelimit-reset-tokens': '5s',
                'x-ratelimit-remaining-project-tokens': '15',
                'x-ratelimit-reset-project-tokens': '2s'}, directory)
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            record = state['models']['gpt-6-luna']
            self.assertEqual(slots._capacity('gpt-6-luna', record)[0], 80)
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 16, 1001))
            self.assertTrue(slots._allowed(state, 'gpt-6-luna', 16, 1002))
            # Project reset must not erase still-active account pressure.
            record['observed']['remaining_tokens'] = 10
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 16, 1002))
            # A higher project cap cannot elevate a lower account cap.
            record['observed']['limit_tokens'] = 50
            self.assertEqual(slots._capacity('gpt-6-luna', record)[0], 40)

    def test_partial_observation_preserves_existing_remaining_timestamp(self):
        with TemporaryDirectory() as directory:
            with patch.object(slots.time, 'time', return_value=1000):
                slots.observe_rate_limits('gpt-6-luna', {'x-ratelimit-remaining-tokens': '10',
                    'x-ratelimit-reset-tokens': '1m'}, directory)
            with patch.object(slots.time, 'time', return_value=1002):
                slots.observe_rate_limits('gpt-6-luna', {'x-ratelimit-limit-requests': '100'}, directory)
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual(state['models']['gpt-6-luna']['observed']['at_tokens'], 1000)

    def test_corrupt_state_waits_full_window_instead_of_resetting_capacity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'rate-state.json').write_text('not-json')
            state = slots._load(root, 1000)
            self.assertFalse(slots._allowed(state, 'gpt-6-luna', 5, 1001))
            self.assertTrue(slots._allowed(state, 'gpt-6-luna', 5, 1060))
            self.assertEqual(slots._load(root, 1001)['blockedUntil'], 1060)

    def test_exception_releases_slot_but_keeps_start_in_rate_window(self):
        with TemporaryDirectory() as directory, patch.object(slots, 'MAX_PARALLEL_REQUESTS', 1):
            with self.assertRaisesRegex(RuntimeError, 'network'):
                with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=10):
                    raise RuntimeError('network')
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=10):
                pass
            state = json.loads((Path(directory) / 'rate-state.json').read_text())
            self.assertEqual(len(state['models']['gpt-6-luna']['requests']), 2)

    def test_invalid_estimates_and_headers(self):
        for estimate in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                with slots.api_slot(input_tokens=estimate):
                    pass
        with TemporaryDirectory() as directory:
            slots.observe_rate_limits('gpt-6-luna', {'x-ratelimit-limit-tokens': '-2',
                'x-ratelimit-remaining-tokens': 'invalid'}, directory)
            self.assertFalse((Path(directory) / 'rate-state.json').exists())
        self.assertEqual(slots._reset_seconds('100ms'), .1)
        self.assertIsNone(slots._reset_seconds('garbage1s'))


class StartupPrioritySlotsTest(unittest.TestCase):
    def assert_waits(self, directory, priority=None, **kwargs):
        with self.assertRaisesRegex(InterruptedError, 'expected offline wait'):
            with slots.api_slot(_cancel_wait(), directory, priority=priority, **kwargs):
                self.fail('must wait rather than exceed the allowed concurrency')

    def test_priority_can_start_first_then_fill_base_and_first_completion_drains_to_ordinary_cap(self):
        with TemporaryDirectory() as directory, patch.object(slots, 'MAX_PARALLEL_REQUESTS', 2), ExitStack() as stack:
            with slots.startup_priority_slots(directory) as priority:
                first = _hold(stack, slots.api_slot(directory=directory, priority=priority))
                second = _hold(stack, slots.api_slot(directory=directory, priority=priority))
                base_a = _hold(stack, slots.api_slot(directory=directory))
                base_b = _hold(stack, slots.api_slot(directory=directory))
                self.assert_waits(directory)
                self.assert_waits(directory, priority)
                # The first actual request has completed; an already-admitted
                # peer continues, but no base refill may keep startup capacity.
                first();priority.close();priority.close()
                base_a()
                self.assert_waits(directory)  # base_b + extra peer still at 2.
                self.assert_waits(directory, priority)  # Closed grant downgrades.
                base_b()
                with slots.api_slot(directory=directory, priority=priority):
                    self.assert_waits(directory)
                second()
            self.assertFalse(list(Path(directory).glob('startup-*.lock')))

    def test_capability_has_only_two_successful_admissions_even_if_extra_lock_becomes_free(self):
        with TemporaryDirectory() as directory, patch.object(slots, 'MAX_PARALLEL_REQUESTS', 1), ExitStack() as stack:
            with slots.startup_priority_slots(directory) as priority:
                _hold(stack, slots.api_slot(directory=directory))
                first = _hold(stack, slots.api_slot(directory=directory, priority=priority))
                _hold(stack, slots.api_slot(directory=directory, priority=priority))
                first()
                self.assert_waits(directory, priority)
                self.assertEqual(priority._remaining, 0)

    def test_waiting_cancel_and_failed_rate_write_do_not_spend_priority_admissions(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ,{'SYNESIS_OPENAI_TIER':'build'}), \
             slots.startup_priority_slots(directory) as priority:
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=1_000_000):
                pass
            self.assert_waits(directory, priority, model='gpt-6-luna', input_tokens=1_000_000)
            self.assertEqual(priority._remaining, 2)
            with patch.object(slots, '_save', side_effect=OSError('synthetic write failure')):
                with self.assertRaisesRegex(OSError, 'synthetic write failure'):
                    with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=1,
                                        priority=priority):
                        self.fail('must not admit without persisting the rate reservation')
            self.assertEqual(priority._remaining, 2)
            with slots.api_slot(directory=directory, priority=priority):
                pass
            self.assertEqual(priority._remaining, 1)

    def test_priority_keeps_tpm_rpm_accounting_and_output_reservation_unchanged(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ,{'SYNESIS_OPENAI_TIER':'build'}), \
             slots.startup_priority_slots(directory) as priority:
            with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=700,
                                max_output=18000, priority=priority) as admission:
                pass
            state = slots._load(Path(directory), time.time())
            self.assertEqual(state['models']['gpt-6-luna']['requests'],
                             [[state['models']['gpt-6-luna']['requests'][0][0],18000,admission.ticket]])
            self.assertEqual(slots._capacity('gpt-6-luna', {}), (1_600_000,4000))
            with self.assertRaises(slots.RateLimitRequestTooLarge):
                with slots.api_slot(directory=directory, model='gpt-6-luna', input_tokens=1_600_001,
                                    priority=priority):
                    self.fail('priority does not raise the model/project token limit')
            self.assertEqual(priority._remaining, 1)

    def test_priority_waiter_closed_before_admission_enters_only_after_ordinary_drain(self):
        with TemporaryDirectory() as directory, patch.object(slots,'MAX_PARALLEL_REQUESTS',1), ExitStack() as stack:
            other=stack.enter_context(slots.startup_priority_slots(directory))
            first=_hold(stack,slots.api_slot(directory=directory,priority=other))
            second=_hold(stack,slots.api_slot(directory=directory,priority=other))
            waiting=Event();entered=Event();release=Event()
            priority=stack.enter_context(slots.startup_priority_slots(directory))
            def request():
                def check():
                    waiting.set()
                    if release.is_set() and not entered.is_set():
                        raise RuntimeError('unexpected cancellation before admission')
                with slots.api_slot(check,directory,priority=priority):
                    entered.set()
                    if not release.wait(5):raise RuntimeError('offline request release timed out')
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(request)
                try:
                    self.assertTrue(waiting.wait(3))
                    priority.close();other.close()
                    first()
                    self.assertFalse(entered.wait(.08))  # One extra is still at the ordinary cap.
                    second()
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(priority._remaining,2)  # No late extra claim.
                    self.assert_waits(directory,priority)
                finally:
                    release.set()
                    first();second()
                future.result(timeout=5)

    def test_closed_unadmitted_capability_is_ordinary_and_scope_exception_closes_marker(self):
        with TemporaryDirectory() as directory, patch.object(slots, 'MAX_PARALLEL_REQUESTS', 1):
            with self.assertRaisesRegex(RuntimeError, 'operation cancelled'):
                with slots.startup_priority_slots(directory) as priority:
                    priority.close()
                    with slots.api_slot(directory=directory, priority=priority):
                        self.assert_waits(directory, priority)
                    raise RuntimeError('operation cancelled')
            self.assertFalse(list(Path(directory).glob('startup-*.lock')))
            with slots.api_slot(directory=directory):
                pass

    def test_invalid_capabilities_and_directory_mismatch_do_not_elevate_capacity(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as other:
            for invalid in (True,1,'priority',object()):
                with self.assertRaises(ValueError):
                    with slots.api_slot(directory=directory, priority=invalid):
                        self.fail('invalid capability')
            with slots.startup_priority_slots(directory) as priority:
                with self.assertRaisesRegex(ValueError, 'different slot directory'):
                    with slots.api_slot(directory=other, priority=priority):
                        self.fail('cross-directory capability')
            with slots.api_slot(directory=directory, priority=False):
                pass

    def test_three_processes_share_hard_sixteen_locks_and_ordinary_limit_remains_fourteen(self):
        if 'fork' not in multiprocessing.get_all_start_methods():
            self.skipTest('fork unavailable; thread and lock tests still cover Windows paths')
        with TemporaryDirectory() as directory:
            ctx=multiprocessing.get_context('fork');ready=ctx.Queue();release=ctx.Event()
            counter=ctx.Value('i',0);peak=ctx.Value('i',0);guard=ctx.Lock()
            processes=[ctx.Process(target=_process_startup_requests,
                args=(directory,ready,release,counter,peak,guard)) for _ in range(3)]
            try:
                for process in processes:process.start()
                for _ in range(16):ready.get(timeout=8)
                with guard:
                    self.assertEqual(counter.value,16)
                    self.assertEqual(peak.value,16)
            finally:
                release.set()
                for process in processes:
                    process.join(timeout=8)
                    if process.is_alive():process.terminate();process.join(timeout=2)
            self.assertTrue(all(process.exitcode==0 for process in processes))
            self.assertEqual(peak.value,16)
            self.assertEqual(counter.value,0)
            with ExitStack() as stack:
                for _ in range(14):_hold(stack,slots.api_slot(directory=directory))
                self.assert_waits(directory)  # No generic 16-call mode leaked.

    def test_crashed_process_marker_is_not_a_live_startup_window(self):
        if 'fork' not in multiprocessing.get_all_start_methods():
            self.skipTest('fork unavailable')
        with TemporaryDirectory() as directory, patch.object(slots,'MAX_PARALLEL_REQUESTS',1), ExitStack() as stack:
            ctx=multiprocessing.get_context('fork');parent,child=ctx.Pipe(duplex=False)
            process=ctx.Process(target=_process_crashed_startup,args=(directory,child))
            process.start();child.close()
            self.assertTrue(parent.poll(5));self.assertTrue(parent.recv());parent.close()
            process.join(timeout=5);self.assertEqual(process.exitcode,0)
            self.assertTrue(list(Path(directory).glob('startup-*.lock')))
            # A still-running extra request must drain instead of allowing an
            # ordinary refill because a dead marker file happens to exist.
            handle=slots._handle(Path(directory)/'14.lock');self.assertTrue(slots._try_lock(handle))
            stack.callback(handle.close);stack.callback(slots._unlock,handle)
            self.assert_waits(directory)
            self.assertFalse(list(Path(directory).glob('startup-*.lock')))


class RateUsageSettlementTest(unittest.TestCase):
    def state(self,directory):
        return json.loads((Path(directory)/'rate-state.json').read_text())

    def test_measured_input_reduces_only_its_bound_and_keeps_output_ceiling(self):
        with TemporaryDirectory() as directory:
            with slots.api_slot(directory=directory,model='gpt-6-luna',
                                input_tokens=600_000,max_output=18_000) as admission:
                pass
            state=self.state(directory)
            self.assertEqual(state['models']['gpt-6-luna']['requests'][0][1],600_000)
            self.assertFalse(slots._allowed(state,'gpt-6-luna',1_580_000,time.time()))
            self.assertTrue(slots.settle_rate_usage(admission,8_000,18_000))
            state=self.state(directory)
            row=state['models']['gpt-6-luna']['requests'][0]
            self.assertEqual(row[1],18_000)
            self.assertEqual(row[2],admission.ticket)
            self.assertTrue(slots._allowed(state,'gpt-6-luna',1_580_000,time.time()))
            self.assertEqual(len(state['models']['gpt-6-luna']['requests']),1)
            # Even a mistaken caller cannot substitute actual output or zero
            # for the output ceiling recorded when this request was admitted.
            self.assertTrue(slots.settle_rate_usage(admission,8_000,0))
            self.assertEqual(self.state(directory)['models']['gpt-6-luna']['requests'][0][1],18_000)

    def test_actual_input_above_estimate_increases_future_rate_accounting(self):
        with TemporaryDirectory() as directory:
            with slots.api_slot(directory=directory,model='gpt-6-luna',
                                input_tokens=10_000,max_output=18_000) as admission:
                pass
            self.assertTrue(slots.settle_rate_usage(admission,40_000,18_000))
            state=self.state(directory)
            self.assertEqual(state['models']['gpt-6-luna']['requests'][0][1],40_000)
            self.assertFalse(slots._allowed(state,'gpt-6-luna',1_580_000,time.time()))

    def test_error_or_unknown_usage_retains_estimate_for_whole_window(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                with slots.api_slot(directory=directory,model='gpt-6-luna',
                                    input_tokens=600_000,max_output=18_000):
                    raise RuntimeError('usage unknown')
            state=self.state(directory)
            row=state['models']['gpt-6-luna']['requests'][0]
            self.assertEqual(row[1],600_000)
            self.assertFalse(slots._allowed(state,'gpt-6-luna',1_580_000,row[0]+59))
            self.assertTrue(slots._allowed(state,'gpt-6-luna',1_580_000,row[0]+60))

    def test_tickets_are_independent_across_requests_and_models(self):
        with TemporaryDirectory() as directory:
            tickets=[]
            for model in ['gpt-6-luna','gpt-6-luna','gpt-6-sol']:
                with slots.api_slot(directory=directory,model=model,
                                    input_tokens=100_000,max_output=18_000) as admission:
                    tickets.append(admission)
            self.assertEqual(len({a.ticket for a in tickets}),3)
            self.assertTrue(slots.settle_rate_usage(tickets[1],10_000,18_000))
            state=self.state(directory)
            self.assertEqual([r[1] for r in state['models']['gpt-6-luna']['requests']], [100_000,18_000])
            self.assertEqual(state['models']['gpt-6-sol']['requests'][0][1],100_000)
            wrong=slots.Admission(Path(directory),'gpt-6-sol',tickets[0].ticket,18_000)
            self.assertFalse(slots.settle_rate_usage(wrong,1_000,18_000))
            self.assertEqual(self.state(directory),state)

    def test_concurrent_settlements_do_not_lose_other_admissions(self):
        with TemporaryDirectory() as directory:
            def work(index):
                with slots.api_slot(directory=directory,model='gpt-6-luna',
                                    input_tokens=20_000,max_output=1000) as admission:
                    pass
                actual=3000+index
                self.assertTrue(slots.settle_rate_usage(admission,actual,1000))
                return admission.ticket,actual
            with ThreadPoolExecutor(max_workers=12) as pool:
                expected=dict(pool.map(work,range(24)))
            rows=self.state(directory)['models']['gpt-6-luna']['requests']
            self.assertEqual({r[2]:r[1] for r in rows},expected)
            self.assertEqual(len(rows),24)

    def test_legacy_rows_are_readable_and_expired_ticket_cannot_modify_them(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);now=time.time()
            slots._save(root,{'models':{'gpt-6-luna':{'requests':[[now,50000]]}}})
            self.assertEqual(slots._load(root,now)['models']['gpt-6-luna']['requests'],[[now,50000]])
            fake=slots.Admission(root,'gpt-6-luna','unknown-ticket',18_000)
            self.assertFalse(slots.settle_rate_usage(fake,1,18_000))
            self.assertEqual(self.state(directory)['models']['gpt-6-luna']['requests'][0][1],50000)
            with slots.api_slot(directory=root,model='gpt-6-luna',input_tokens=50000,max_output=18000) as admission:
                pass
            before=self.state(directory)
            with patch.object(slots.time,'time',return_value=now+61):
                self.assertFalse(slots.settle_rate_usage(admission,1,18_000))
            self.assertEqual(self.state(directory),before)

    def test_missing_invalid_or_unwritable_settlement_keeps_original_reservation(self):
        with TemporaryDirectory() as directory:
            with slots.api_slot(directory=directory,model='gpt-6-luna',input_tokens=50000,max_output=18000) as admission:
                pass
            before=self.state(directory)
            for value in [-1,1.5,True,None]:
                self.assertFalse(slots.settle_rate_usage(admission,value,18000))
            self.assertFalse(slots.settle_rate_usage(None,1000,18000))
            with patch.object(slots,'_save',side_effect=OSError('simulated storage failure')):
                self.assertFalse(slots.settle_rate_usage(admission,1000,18000))
            self.assertEqual(self.state(directory),before)


if __name__ == '__main__':
    unittest.main()
