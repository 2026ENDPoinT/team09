"""Offline cap regressions: cache fees, incomplete sends and snapshot races."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from audit_pdf_cost_metrics import (can_reserve, ledger_metrics, request_metrics,
                                    reserve_amount, usage_metrics)


def settled(key='a', **details):
    return {'requestId': key, 'state': 'settled', 'reservedUsd': .02,
        'estimatedUsd': .0015,
        'usage': {'prompt_tokens': 10000, 'completion_tokens': 1000,
            'prompt_tokens_details': {'cached_tokens': 2000, 'cache_write_tokens': 3000, **details}}}


class CostMetricsTests(unittest.TestCase):
    def test_real_cache_write_key_token_subset_and_long_context_premium(self):
        value = settled(cache_creation_tokens=999999)
        before = copy.deepcopy(value);row = request_metrics(value)
        self.assertEqual(value, before)
        self.assertEqual(row['inputTokens'], 10000)
        self.assertEqual(row['totalTokens'], 11000)
        self.assertEqual(row['cachedInputTokens'], 2000)
        self.assertEqual(row['cacheWriteTokens'], 3000)
        self.assertAlmostEqual(row['knownCacheWritePremiumUsd'], .000075)
        self.assertAlmostEqual(row['committedUsd'], .001575)
        already_included = copy.deepcopy(value)
        already_included.update(estimatedUsd=.001575, cacheWritePremiumUsd=.000075)
        self.assertAlmostEqual(request_metrics(already_included)['committedUsd'], .001575)
        self.assertEqual(request_metrics(already_included)['additionalCacheWritePremiumUsd'], 0)
        value['usage']['prompt_tokens'] = 300000
        self.assertAlmostEqual(request_metrics(value)['knownCacheWritePremiumUsd'], .00015)
        del value['usage']['prompt_tokens_details']['cache_write_tokens']
        row = request_metrics(value)
        self.assertFalse(row['cacheWriteFieldPresent'])
        self.assertEqual(row['knownCacheWritePremiumUsd'], 0)
        self.assertGreater(row['missingCacheWriteUpperBoundUsd'], 0)

    def test_cap_reservations_unknown_and_not_sent_never_get_underpriced(self):
        self.assertEqual(reserve_amount(.008), .01)
        self.assertTrue(can_reserve(.97, .008))
        self.assertFalse(can_reserve(.97, .00800001))
        unknown = {'requestId': 'u', 'state': 'failed_or_uncertain', 'reservedUsd': .008}
        unused = {'requestId': 'n', 'state': 'not_sent', 'reservedUsd': 999}
        value = usage_metrics([settled(), unknown, unused])
        self.assertEqual(value['requests'], 2)
        self.assertEqual(value['unknownUsageRequests'], 1)
        self.assertEqual(value['notSentRequests'], 1)
        self.assertAlmostEqual(value['unknownReservedUsd'], .008)
        self.assertAlmostEqual(value['conservativeUnknownReservedUsd'], .01)
        self.assertAlmostEqual(value['committedUsd'], .001575+.01)

    def test_repeated_snapshot_settlement_wins_without_mutation_or_double_count(self):
        a = settled();reserved = {'requestId': 'a', 'state': 'reserved', 'reservedUsd': .02}
        entries = [reserved, a, copy.deepcopy(a)];before = copy.deepcopy(entries)
        value = usage_metrics(entries)
        self.assertEqual(entries, before)
        self.assertEqual(value['requests'], 1)
        self.assertEqual(value['duplicateSnapshotsIgnored'], 2)
        self.assertAlmostEqual(value['committedUsd'], .001575)
        conflict = copy.deepcopy(a);conflict['estimatedUsd'] += .001
        with self.assertRaises(ValueError):usage_metrics([a, conflict])
        with self.assertRaises(ValueError):usage_metrics([a, {**a, 'state': 'not_sent'}])

    def test_only_explicit_run_ledgers_are_read_and_invalid_money_stops_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);run = root/'runs/same-plan-8/usage';run.mkdir(parents=True)
            (run/'one.json').write_text(json.dumps({'model':'gpt-6-luna','requests':[settled()]}))
            backup = root/'before/usage';backup.mkdir(parents=True)
            (backup/'ignored.json').write_text('invalid and must never be read')
            value = ledger_metrics(root)
            self.assertEqual(value['requests'], 1)
            self.assertEqual(value['ledgerFiles'], 1)
            self.assertEqual(value['additionalApiRequests'], 0)
        for amount in [float('nan'), float('inf'), -.01, True]:
            with self.subTest(amount=amount), self.assertRaises(ValueError):reserve_amount(amount)
        bad = settled();bad['usage']['prompt_tokens_details']['cache_write_tokens'] = 20000
        with self.assertRaises(ValueError):request_metrics(bad)


if __name__ == '__main__':
    unittest.main()
