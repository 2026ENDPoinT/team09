"""Only trusted unsent study batches defer a sticky low-credit stop."""
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pdf_ai as ai
from pdf_credit_billing import (Billing, RATE, CreditReservationPending,
                               InsufficientCredits, available, wallet_lock)


class BatchCreditTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wallet = self.root/'wallet.json'
        self.wallet.write_text(json.dumps({'version': 1, 'liveBilling': True,
            'baselineCredits': 0, 'highWaterCredits': 0, 'purchases': [{'credits': '10'}],
            'creditOperations': {}, 'creditCharges': {}, 'creditHolds': {}}))
        self.key = patch.object(ai, 'api_key', side_effect=AssertionError('No credential read')).start()
        self.network = patch.object(ai.urllib.request, 'urlopen', side_effect=AssertionError('No network')).start()
        self.addCleanup(patch.stopall)

    def test_unfunded_batch_does_not_change_wallet_or_stick_stop_and_smaller_fits(self):
        billing = Billing(self.wallet, 'run', 'summary')
        before = self.wallet.read_bytes()
        with self.assertRaises(CreditReservationPending):
            billing.reserve('large', Decimal(20)/RATE, split_before_stop=True)
        self.assertFalse(billing.exhausted)
        self.assertEqual(self.wallet.read_bytes(), before)
        billing.reserve('small', Decimal(4)/RATE)
        with wallet_lock(self.wallet) as wallet:
            self.assertAlmostEqual(float(available(wallet)), 6)
            self.assertEqual(set(wallet['creditHolds']), {'small'})

    def test_default_insufficiency_keeps_existing_sticky_stop(self):
        billing = Billing(self.wallet, 'run', 'summary')
        with self.assertRaises(InsufficientCredits) as caught:
            billing.reserve('large', Decimal(20)/RATE)
        self.assertNotIsInstance(caught.exception, CreditReservationPending)
        self.assertTrue(billing.exhausted)
        with self.assertRaises(InsufficientCredits):
            billing.reserve('small', Decimal(4)/RATE, split_before_stop=True)

    def test_only_exact_trusted_two_to_four_unit_marker_adds_keyword(self):
        for marker in [None, True, False, 1, 5, 2., '2']:
            with self.subTest(marker=marker):
                # This fixture deliberately has no **kwargs support.
                calls = []
                class OrdinaryBilling:
                    def reserve(self, request_id, usd): calls.append((request_id, usd))
                provider = ai.Provider(self.root/'ordinary', True, 1, transport=Mock())
                provider.billing = OrdinaryBilling()
                provider.reserve_credits({'requestId': 'r', 'reservedUsd': .01, 'studyBatchUnits': marker})
                self.assertEqual(calls, [('r', .01)])
        for marker in [2, 3, 4]:
            provider = ai.Provider(self.root/'batch', True, 1, transport=Mock())
            provider.billing = Mock()
            provider.reserve_credits({'requestId': 'r', 'reservedUsd': .01, 'studyBatchUnits': marker})
            provider.billing.reserve.assert_called_once_with('r', .01, split_before_stop=True)

    def test_batch_rejected_before_transport_can_split_then_single_sends_once(self):
        reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 100}}
        send = Mock(return_value=reply)
        provider = ai.Provider(self.root/'doc', True, 1, transport=send)
        provider.billing = Billing(self.wallet, provider.ledger['operationId'], 'summary')
        provider.context = {'kind': 'region_study', 'studyBatchUnits': 4}
        before = self.wallet.read_bytes()
        with self.assertRaises(ai.BudgetExceeded) as caught:
            provider.complete({'task': 'large batch'}, max_output=72000)
        self.assertNotIsInstance(caught.exception, ai.CreditExceeded)
        self.assertFalse(provider.billing.exhausted)
        self.assertEqual(provider.ledger['requests'], [])
        self.assertEqual(provider.spent, 0)
        self.assertEqual(self.wallet.read_bytes(), before)
        send.assert_not_called()
        provider.context = {'kind': 'region_study'}
        self.assertEqual(provider.complete({'task': 'single'}, max_output=18000), {'ok': True})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(provider.ledger['requests']), 1)
        self.assertEqual(provider.ledger['requests'][0]['state'], 'settled')
        self.key.assert_not_called();self.network.assert_not_called()

    def test_explicit_two_dollar_window_can_construct_offline_provider(self):
        from audit_pdf_cost_budget import SharedBudget
        approval = {'schemaVersion': 1, 'createdAtUtc': '2026-10-21T04:04:38Z',
            'authorization': 'Explicit user approval of additional $2.',
            'approvedLimitUsd': 2., 'executionCapUsd': 1.98,
            'checkpointRequestIds': [], 'baseActualKnownUsd': 0, 'baseCommittedUsd': 0}
        (self.root/'approved-window.json').write_text(json.dumps(approval))
        value = SharedBudget(self.root, 'offline').snapshot()['activeWindow']
        provider = ai.Provider(self.root/'two-dollar', True, value['executionCapUsd'],
                               max_allowed_usd=value['approvedLimitUsd'], transport=Mock())
        self.assertEqual(provider.max_usd, 1.98)
        self.assertEqual(provider.ledger['requests'], [])
        self.key.assert_not_called();self.network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
