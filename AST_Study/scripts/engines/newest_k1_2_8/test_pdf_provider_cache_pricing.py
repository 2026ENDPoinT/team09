"""Explicit-cache pricing and cap reservations; synthetic transports only."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pdf_ai as ai


def response(cached=200, writes=300):
    details = {'cached_tokens': cached}
    if writes is not None:
        details['cache_write_tokens'] = writes
    return {'choices': [{'message': {'content': json.dumps({'answer': 'fixture'})},
                         'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 1000, 'completion_tokens': 100,
                  'prompt_tokens_details': details}}


class ProviderCachePricingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(patch.stopall)
        self.opener = patch.object(ai.urllib.request, 'urlopen',
            side_effect=AssertionError('A pricing test must not call the network')).start()
        self.key = patch.object(ai, 'api_key',
            side_effect=AssertionError('A pricing test must not load a credential')).start()
        self.number = 0
        self.payload = {'task': 'region_teaching', 'source': 'synthetic fixture'}
        self.options = {'max_output': 100, 'system_prompt': 'Offline pricing fixture.'}

    def provider(self, result=None, max_usd=1):
        self.number += 1
        send = Mock(return_value=copy.deepcopy(result or response()))
        provider = ai.Provider(Path(self.tmp.name)/str(self.number), True, max_usd, transport=send)
        provider.context = {'kind': 'region_study'}
        provider.billing = Mock()
        return provider, send

    def test_cache_write_premium_is_included_once_in_actual_ledger_and_credit_settlement(self):
        provider, send = self.provider()
        self.assertEqual(provider.complete(self.payload, cache_stable_prefix=True, **self.options),
                         {'answer': 'fixture'})
        entry = provider.ledger['requests'][0]
        expected = (800*.1+200*.01+100*.5+300*.1*.25)/1_000_000
        self.assertAlmostEqual(entry['cacheWritePremiumUsd'], .0000075)
        self.assertAlmostEqual(entry['estimatedUsd'], expected)
        self.assertAlmostEqual(provider.spent, expected)
        self.assertAlmostEqual(ai.run_usage(provider)['usageBasedUsd'], expected)
        provider.billing.settle.assert_called_once_with(entry['requestId'], expected)
        saved = json.loads(provider.ledger_path.read_text())['requests'][0]
        self.assertEqual(saved['cacheWritePremiumUsd'], entry['cacheWritePremiumUsd'])
        self.assertEqual(send.call_args.args[0]['prompt_cache_options'], {'mode': 'explicit'})
        self.opener.assert_not_called();self.key.assert_not_called()

    def test_missing_write_usage_and_negative_count_do_not_invent_premium(self):
        for writes in [None, 0, -100]:
            with self.subTest(writes=writes):
                provider, _ = self.provider(response(writes=writes))
                provider.complete(self.payload, **self.options)
                entry = provider.ledger['requests'][0]
                self.assertEqual(entry['cacheWritePremiumUsd'], 0)
                self.assertAlmostEqual(entry['estimatedUsd'], (800*.1+200*.01+100*.5)/1e6)

    def test_write_count_is_clamped_to_uncached_input_without_charging_cached_reads_again(self):
        for cached, writes, billable in [(900, 5000, 100), (5000, 5000, 0),
                                         (-100, 5000, 1000)]:
            with self.subTest(cached=cached, writes=writes):
                provider, _ = self.provider(response(cached, writes))
                provider.complete(self.payload, **self.options)
                entry = provider.ledger['requests'][0]
                self.assertAlmostEqual(entry['cacheWritePremiumUsd'], billable*.1*.25/1e6)

    def test_long_context_write_premium_uses_the_existing_doubled_input_rate(self):
        with patch.object(ai, 'LUNA_LONG_CONTEXT_THRESHOLD', 500):
            provider, _ = self.provider()
            provider.complete(self.payload, cache_stable_prefix=True, **self.options)
            entry = provider.ledger['requests'][0]
            expected = (800*.2+200*.02+100*.75+300*.2*.25)/1e6
            self.assertAlmostEqual(entry['cacheWritePremiumUsd'], .000015)
            self.assertAlmostEqual(entry['estimatedUsd'], expected)
            self.assertAlmostEqual(entry['reservedUsd'],
                (entry['inputTokenBound']*.2*1.25+100*.75)/1e6)

    def test_explicit_write_reservation_increases_input_component_only(self):
        for enabled in [False, True]:
            with self.subTest(enabled=enabled):
                provider, _ = self.provider()
                provider.complete(self.payload, cache_stable_prefix=enabled, **self.options)
                entry = provider.ledger['requests'][0]
                expected = (entry['inputTokenBound']*.1*(1.25 if enabled else 1)+100*.5)/1e6
                self.assertAlmostEqual(entry['reservedUsd'], expected)

    def test_worst_case_cache_write_hold_blocks_over_cap_before_any_send(self):
        first, _ = self.provider()
        first.complete(self.payload, cache_stable_prefix=False, **self.options)
        entry = first.ledger['requests'][0]
        old_hold = (entry['inputTokenBound']*.1+100*.5)/1e6
        new_hold = (entry['inputTokenBound']*.1*1.25+100*.5)/1e6
        provider, send = self.provider(max_usd=(old_hold+new_hold)/2)
        with self.assertRaises(ai.BudgetExceeded):
            provider.complete(self.payload, cache_stable_prefix=True, **self.options)
        send.assert_not_called()
        self.assertEqual(provider.ledger['requests'], [])
        provider.billing.reserve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
