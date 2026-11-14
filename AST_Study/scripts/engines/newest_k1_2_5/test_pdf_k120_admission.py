"""Offline K1.2.0 reservation waits, hard limits and honest timing regressions."""
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pdf_ai import BudgetExceeded, CreditExceeded
from pdf_credit_billing import Billing, CreditReservationPending, InsufficientCredits, RATE
from pdf_k120_admission import complete
from pdf_k120_timings import unit_timings


class AdmissionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name); self.path = self.folder / 'wallet.json'
        self.path.write_text(json.dumps({'liveBilling': True, 'baselineCredits': 0,
            'highWaterCredits': 0, 'purchases': [{'credits': 10}],
            'creditHolds': {}, 'creditCharges': {}, 'creditOperations': {}}))
        self.billing = Billing(self.path, 'test', 'summary')
        self.provider = SimpleNamespace(folder=self.folder, billing=self.billing,
            context={'strategy': 'newest-k1-2-5', 'kind': 'region_study', 'unitIds': ['j']},
            _lock=threading.RLock(), ledger={'requests': []}, spent=0., max_usd=1.)
        self.poll = patch('pdf_k120_admission.POLL_SECONDS', .005)
        self.poll.start(); self.addCleanup(self.poll.stop)
        self.sent = []

    def attempt(self, token='attempt'):
        return SimpleNamespace(token=token, entry=None, sent=None, check=lambda: None)

    def reserve(self, name, credits):
        usd = float(Decimal(str(credits)) / RATE)
        try: self.billing.reserve(name, usd)
        except CreditReservationPending as original:
            error = BudgetExceeded(str(original)); error.reservation_wait_usd = usd
            raise error from original
        except InsufficientCredits as original:
            error = CreditExceeded(str(original)); error.reservation_required_usd = usd
            raise error from original

    def fake_request(self, payload, **options):
        a = options['_hedge_attempt']
        self.reserve(a.token, 6)
        a.entry = {'requestId': a.token}; a.sent = time.monotonic()
        self.sent.append(a.token)
        self.billing.settle(a.token, float(Decimal('.1') / RATE))
        return {'ok': True}

    def release_later(self, credits):
        t = threading.Timer(.025, lambda: self.billing.settle('other', float(Decimal(str(credits)) / RATE)))
        t.start(); self.addCleanup(t.join)

    def test_wait_resumes_same_attempt_and_records_success(self):
        self.reserve('other', 6); self.release_later(.1)
        self.provider._complete_once = self.fake_request; a = self.attempt()
        self.assertEqual(complete(self.provider, {}, {'_hedge_attempt': a}), {'ok': True})
        self.assertEqual(self.sent, ['attempt'])
        self.assertGreater(a.entry['reservationWaitSeconds'], .015)
        self.assertGreater(a.entry['reservationWaitChecks'], 0)
        record = self.provider._admission_timings['j']['attempt']
        self.assertEqual(record['state'], 'completed')
        self.assertEqual(len(record['waitIntervals']), 1)

    def test_real_shortfall_records_unsent_wait_and_required_amount(self):
        self.reserve('other', 6); self.release_later(6)
        self.provider._complete_once = self.fake_request; a = self.attempt()
        with self.assertRaises(CreditExceeded) as found:
            complete(self.provider, {}, {'_hedge_attempt': a})
        self.assertIn('남은 잔고 9.20원', str(found.exception))
        self.assertIn('예약 필요액 13.80원', str(found.exception))
        self.assertFalse(self.sent); self.assertIsNone(a.entry)
        record = self.provider._admission_timings['j']['attempt']
        self.assertEqual(record['state'], 'failed')
        self.assertGreater(record['reservationWaitSeconds'], .015)

    def test_larger_rejection_does_not_poison_fundable_smaller_request(self):
        with self.assertRaises(CreditExceeded): self.reserve('too-large', 12)
        self.assertTrue(self.billing.exhausted)
        self.provider._complete_once = self.fake_request
        self.assertEqual(complete(self.provider, {}, {'_hedge_attempt': self.attempt()}), {'ok': True})
        self.assertEqual(self.sent, ['attempt'])

    def test_zero_balance_and_operation_cap_are_not_bypassed(self):
        self.reserve('used', 10); self.billing.settle('used', float(Decimal(10) / RATE))
        self.provider._complete_once = self.fake_request
        with self.assertRaises(CreditExceeded):
            complete(self.provider, {}, {'_hedge_attempt': self.attempt()})
        self.assertFalse(self.sent)
        def capped(payload, **options):
            error = BudgetExceeded('operation cap'); error.operation_wait_usd = .2
            raise error
        self.provider._complete_once = capped; self.provider.spent = .9
        self.provider.ledger['requests'] = [{'state': 'usage_unknown', 'reservedUsd': .9}]
        with self.assertRaisesRegex(BudgetExceeded, 'operation cap'):
            complete(self.provider, {}, {'_hedge_attempt': self.attempt('cap')})
        self.assertEqual(self.provider.spent, .9)

    def test_sent_request_is_never_repeated_by_admission(self):
        a = self.attempt(); calls = []
        def sent(payload, **options):
            calls.append(1); a.entry = {'requestId': 'already-sent'}
            raise BudgetExceeded('after send')
        self.provider._complete_once = sent
        with self.assertRaisesRegex(BudgetExceeded, 'after send'):
            complete(self.provider, {}, {'_hedge_attempt': a})
        self.assertEqual(calls, [1])

    def test_parallel_attempt_records_do_not_overwrite_each_other(self):
        self.provider._complete_once = self.fake_request
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: complete(self.provider, {}, {'_hedge_attempt': self.attempt(str(i))}), range(8)))
        self.assertEqual(len(results), 8)
        self.assertEqual(len(self.provider._admission_timings['j']), 8)
        self.assertEqual(len(self.sent), 8)


class TimingsTest(unittest.TestCase):
    jobs = [{'id': 'j', 'title': '단락', 'blocks': [{'page': 13}]}]

    def test_reported_seven_minutes_separates_412_second_wait_from_22_second_api(self):
        entry = {'requestId': 'r', 'kind': 'region_study', 'unitIds': ['j'],
                 'hedgeGroup': 'h', 'hedgeWinner': True, 'hedgeResultSeconds': 434.638,
                 'reservationWaitSeconds': 412.484, 'latencySeconds': 21.783,
                 'queueSeconds': .002, 'sentAtMs': 1000000}
        row = unit_timings(self.jobs, {0: {}}, [], {'requests': [entry]})[0]
        self.assertEqual(row['totalSeconds'], 434.638)
        self.assertEqual(row['reservationWaitSeconds'], 412.484)
        self.assertEqual(row['apiSeconds'], 21.781)
        self.assertEqual(row['localQueueSeconds'], .002)

    def test_overlapping_hedge_api_and_wallet_wait_are_not_added_twice(self):
        common = {'kind': 'region_study', 'unitIds': ['j'], 'hedgeGroup': 'h'}
        entries = [{**common, 'requestId': 'a', 'sentAtMs': 100000, 'latencySeconds': 55},
                   {**common, 'requestId': 'b', 'sentAtMs': 120000, 'latencySeconds': 15,
                    'hedgeWinner': True, 'hedgeResultSeconds': 45, 'hedgeNetworkSeconds': 35}]
        records = {'j': {'a': {'startedAtMs': 90000, 'endedAtMs': 135000,
                              'waitIntervals': [[90000, 100000]]},
                         'b': {'startedAtMs': 110000, 'endedAtMs': 135000,
                              'waitIntervals': [[110000, 120000]]}}}
        row = unit_timings(self.jobs, {0: {}}, [], {'requests': entries}, admission_timings=records)[0]
        self.assertEqual(row['apiSeconds'], 35)
        self.assertEqual(row['reservationWaitSeconds'], 10)
        self.assertEqual(row['totalSeconds'], 45)

    def test_failed_unsent_wait_has_reason_and_zero_api_instead_of_missing_record(self):
        records = {'j': {'a': {'startedAtMs': 1000, 'endedAtMs': 414000,
                              'waitIntervals': [[1000, 414000]], 'error': 'CreditExceeded',
                              'failureReason': '남은 잔고 20.25원 · 최대 예약액 21원'}}}
        row = unit_timings(self.jobs, {}, [{'unitId': 'j', 'error': 'CreditExceeded'}],
                           {'requests': []}, admission_timings=records)[0]
        self.assertEqual(row['apiSeconds'], 0)
        self.assertEqual(row['reservationWaitSeconds'], 413)
        self.assertEqual(row['totalSeconds'], 413)
        self.assertIn('20.25원', row['failureReason'])

    def test_reused_unit_does_not_invent_missing_times(self):
        row = unit_timings(self.jobs, {0: {}}, [], {'requests': []})[0]
        self.assertEqual(row['status'], 'reused')
        self.assertNotIn('apiSeconds', row)
        self.assertNotIn('totalSeconds', row)

    def test_missing_loser_latency_remains_unknown_instead_of_understating_api_time(self):
        common = {'kind': 'region_study', 'unitIds': ['j'], 'hedgeGroup': 'h'}
        entries = [{**common, 'requestId': 'a', 'sentAtMs': 100000},
                   {**common, 'requestId': 'b', 'sentAtMs': 120000, 'latencySeconds': 15,
                    'hedgeWinner': True, 'hedgeResultSeconds': 35}]
        row = unit_timings(self.jobs, {0: {}}, [], {'requests': entries})[0]
        self.assertNotIn('apiSeconds', row)
        self.assertEqual(row['totalSeconds'], 35)


if __name__ == '__main__': unittest.main()
