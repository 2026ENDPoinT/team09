"""No-network shared-budget regressions, including actual admission races."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from audit_pdf_cost_budget import SharedBudget


class FakeBudgetExceeded(Exception):
    pass


def reserved(key, amount=.02):
    return {'requestId': key, 'state': 'reserved', 'reservedUsd': amount}


def settled(key, amount=.02, included=False, missing=False):
    details = {'cached_tokens': 2000}
    if not missing:
        details['cache_write_tokens'] = 3000
    value = {**reserved(key, amount), 'state': 'settled', 'estimatedUsd': .0015,
        'usage': {'prompt_tokens': 10000, 'completion_tokens': 1000,
                  'prompt_tokens_details': details}}
    if included:
        value.update(estimatedUsd=.001575, cacheWritePremiumUsd=.000075)
    return value


def ledger(root, name, entries):
    path = root / 'runs' / name / 'usage' / 'one.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': entries}))
    return path


def approval(root, ids, limit=2., cap=1.98):
    value = {'schemaVersion': 1, 'createdAtUtc': '2026-10-21T04:04:38Z',
        'authorization': 'Explicit user approval: an additional $2 from this checkpoint.',
        'approvedLimitUsd': limit, 'executionCapUsd': cap,
        'checkpointRequestIds': ids, 'baseRequestCount': len(ids),
        'baseActualKnownUsd': .5, 'baseCommittedUsd': .6}
    path = root / 'approved-window.json'
    path.write_text(json.dumps(value))
    return path


class SharedBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.modules = patch.dict(sys.modules, {'pdf_ai': types.SimpleNamespace(BudgetExceeded=FakeBudgetExceeded)})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_two_providers_compete_before_send_under_one_cap(self):
        budgets = [SharedBudget(self.root, 'a'), SharedBudget(self.root, 'b')]
        barrier = threading.Barrier(2)
        admitted = []; rejected = []; failures = []

        def worker(index):
            try:
                barrier.wait(timeout=2)
                budgets[index].reserve(reserved(str(index), .4))  # Each holds $0.50.
                admitted.append(index)
            except FakeBudgetExceeded:
                rejected.append(index)
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual((len(admitted), len(rejected)), (1, 1))
        value = budgets[0].snapshot()
        self.assertEqual(value['committedUsd'], .5)
        self.assertEqual(value['activeWindow']['executionCapUsd'], .98)
        self.assertEqual(value['requestCount'], 1)
        self.assertEqual(value['requests'][str(admitted[0])]['variant'], ('a', 'b')[admitted[0]])

    def test_unknown_preserves_hold_not_sent_releases_and_duplicates_reject(self):
        budget = SharedBudget(self.root, 'a')
        budget.reserve(reserved('unknown', .1))
        value = budget.settle({**reserved('unknown', .01), 'state': 'failed_or_uncertain'})
        self.assertEqual(value['committedUsd'], .125)
        self.assertEqual(value['activeWindow']['conservativeUnknownReservedUsd'], .125)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            budget.reserve(reserved('unknown'))
        budget.reserve(reserved('unused', .1))
        budget.settle({'requestId': 'unused', 'state': 'not_sent', 'estimatedUsd': 0})
        self.assertEqual(budget.snapshot()['committedUsd'], .125)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            budget.reserve(reserved('unused'))
        with self.assertRaisesRegex(ValueError, 'before settlement'):
            budget.settle(settled('never-reserved'))
        with self.assertRaisesRegex(ValueError, 'another variant'):
            SharedBudget(self.root, 'other').settle(settled('unknown'))
        with self.assertRaisesRegex(ValueError, 'transmitted'):
            budget.settle({'requestId': 'unknown', 'state': 'not_sent', 'sentAtMs': 1})
        self.assertEqual(budget.snapshot()['requests']['unknown']['amountUsd'], .125)

    def test_real_fee_marker_and_missing_field_upper_bound_never_underprice(self):
        budget = SharedBudget(self.root, 'a')
        for key in ('old', 'new', 'missing'):
            budget.reserve(reserved(key))
        budget.settle(settled('old'))
        budget.settle(settled('new', included=True))
        value = budget.settle(settled('missing', missing=True))
        self.assertAlmostEqual(value['requests']['old']['amountUsd'], .001575)
        self.assertAlmostEqual(value['requests']['new']['amountUsd'], .001575)
        self.assertAlmostEqual(value['requests']['missing']['amountUsd'], .0017)
        self.assertAlmostEqual(value['activeWindow']['missingCacheWriteUpperBoundUsd'], .0002)
        self.assertAlmostEqual(value['activeWindow']['actualKnownUsd'], .00465)
        self.assertAlmostEqual(value['committedUsd'], .00485)
        before = copy.deepcopy(value)
        self.assertEqual(budget.snapshot(), before)
        invalid = settled('old');invalid['estimatedUsd'] = 0
        with self.assertRaisesRegex(ValueError, 'Conflicting settled'):
            budget.settle(invalid)

    def test_old_554_row_registry_migrates_without_editing_source_ledgers(self):
        requests = {str(index): {'variant': 'old', 'state': 'settled',
                    'amountUsd': .0015, 'estimatedUsd': .0015} for index in range(554)}
        (self.root/'budget.json').write_text(json.dumps({'limitUsd': 1., 'requests': requests,
                                                      'scope': 'new calls for this request only'}))
        path = ledger(self.root, 'old', [settled(str(index), missing=True) for index in range(554)])
        original = path.read_bytes()
        budget = SharedBudget(self.root, 'new')
        value = budget.snapshot()
        self.assertEqual(value['requestCount'], 554)
        self.assertAlmostEqual(value['committedUsd'], 554 * .0017)
        self.assertEqual(path.read_bytes(), original)
        # Repeated reads and stale reservations must not undo known settlement.
        ledger(self.root, 'stale', [reserved('0', .5)])
        self.assertEqual(budget.snapshot(), value)

    def test_new_explicit_window_excludes_checkpoint_and_shares_all_variants(self):
        old = SharedBudget(self.root, 'old')
        old.reserve(reserved('old', .6))  # Existing $0.75 stays in cumulative view.
        approval_path = approval(self.root, ['old'])
        original = approval_path.read_bytes()
        a = SharedBudget(self.root, 'a'); b = SharedBudget(self.root, 'b')
        value = a.snapshot()
        self.assertEqual(value['activeWindow']['committedUsd'], 0)
        self.assertEqual(value['activeWindow']['executionCapUsd'], 1.98)
        a.reserve(reserved('a', .8))  # $1.00 from the NEW $2 window.
        b.reserve(reserved('b', .78))  # $0.975 more; combined $1.975.
        with self.assertRaises(FakeBudgetExceeded): b.reserve(reserved('overflow', .008))
        value = b.snapshot()
        self.assertAlmostEqual(value['committedUsd'], 2.725)
        self.assertAlmostEqual(value['activeWindow']['committedUsd'], 1.975)
        self.assertAlmostEqual(value['activeWindow']['executionRemainingUsd'], .005)
        self.assertEqual(value['limitUsd'], 1.)
        self.assertEqual(value['requests']['old']['amountUsd'], .75)
        self.assertEqual(approval_path.read_bytes(), original)
        # Old pending operations settling later still belong to the old window.
        old.settle(settled('old', amount=.6))
        self.assertAlmostEqual(a.snapshot()['activeWindow']['committedUsd'], 1.975)

    def test_checkpoint_cannot_be_silently_expanded_changed_or_removed(self):
        budget = SharedBudget(self.root, 'a')
        budget.reserve(reserved('one'))
        path = approval(self.root, ['one'])
        budget.snapshot()
        value = json.loads(path.read_text());value['approvedLimitUsd'] = 3.
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'cannot be changed'): budget.snapshot()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'): budget.snapshot()

    def test_invalid_approval_or_accounting_fails_closed_without_rewriting(self):
        budget = SharedBudget(self.root, 'a')
        path = approval(self.root, ['unregistered'])
        with self.assertRaisesRegex(ValueError, 'existing'): budget.snapshot()
        self.assertFalse((self.root/'budget.json').exists())
        path.unlink();budget.reserve(reserved('one'))
        before = (self.root/'budget.json').read_bytes()
        invalid = settled('one');invalid['cacheWritePremiumUsd'] = 10
        with self.assertRaises(ValueError): budget.settle(invalid)
        self.assertEqual((self.root/'budget.json').read_bytes(), before)
        approval(self.root, ['one'], limit=2., cap=2.)
        with self.assertRaisesRegex(ValueError, 'headroom'): budget.snapshot()


if __name__ == '__main__':
    unittest.main()
