"""Offline fixtures for crash recovery and exactly-once credit settlement; no APIs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pdf_credit_billing import Billing, RATE, available, balance, wallet_lock


class ReservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'wallet.json'
        self.ledger = Path(self.tmp.name) / 'usage.json'
        self.path.write_text(json.dumps({'liveBilling': True, 'purchases': [{'credits': '100'}],
            'baselineCredits': '0', 'highWaterCredits': '0', 'creditHolds': {},
            'creditCharges': {}, 'creditOperations': {}}))

    def state(self):
        with wallet_lock(self.path) as wallet:
            return json.loads(json.dumps(wallet, default=str))

    def receipt(self, state, usd=None):
        entry = {'requestId': 'request', 'state': state}
        if usd is not None:
            entry['estimatedUsd'] = usd
        self.ledger.write_text(json.dumps({'operationId': 'operation', 'requests': [entry]}))

    def test_live_reservation_is_only_temporary_and_unknown_usage_does_not_block(self):
        billing = Billing(self.path, 'operation', 'quiz', ledger_path=self.ledger)
        billing.reserve('request', Decimal(20) / RATE)
        self.assertAlmostEqual(float(available(self.state())), 80)
        billing.settle('request')
        first = self.state()
        self.assertEqual(available(first), 100)
        self.assertFalse(first['creditHolds'])
        self.assertIn('request', first['creditPendingRequests'])
        self.assertEqual(first['creditOperations']['operation']['unknownRequests'], 1)
        billing.settle('request')
        self.assertEqual(self.state(), first)

    def test_late_usage_settles_original_request_exactly_once(self):
        billing = Billing(self.path, 'operation', 'quiz', ledger_path=self.ledger)
        billing.reserve('request', Decimal(20) / RATE)
        billing.settle('request')
        self.receipt('settled', .01)
        first = self.state()
        billing.settle('request', .01)
        self.assertEqual(self.state(), first)
        self.assertEqual(balance(first), 100)
        self.assertEqual(first['creditCharges']['request']['payer'], 'synesis')
        self.assertEqual(Decimal(first['creditCharges']['request']['providerUsd']), Decimal('.01'))
        self.assertEqual(Decimal(first['creditCharges']['request']['usd']), 0)
        self.assertEqual(first['creditOperations']['operation']['unknownRequests'], 0)
        self.assertFalse(first['creditPendingRequests'])
        self.assertEqual(len(first['creditCharges']), 1)

    def test_not_sent_is_confirmed_zero_cost(self):
        billing = Billing(self.path, 'operation', 'summary', ledger_path=self.ledger)
        billing.reserve('request', .02)
        self.receipt('not_sent')
        state = self.state()
        self.assertEqual(available(state), 100)
        self.assertEqual(Decimal(state['creditCharges']['request']['usd']), 0)
        self.assertFalse(state['creditHolds'])
        self.assertFalse(state.get('creditPendingRequests'))

    def test_legacy_pending_cost_is_sponsored_after_late_receipt(self):
        wallet = self.state()
        wallet['creditOperations']['operation'] = {'category': 'summary', 'createdAtMs': 1,
            'credits': '0', 'unknownRequests': 1}
        wallet['creditPendingRequests'] = {'request': {'operationId': 'operation',
            'category': 'summary', 'unknown': True, 'ledgerPath': str(self.ledger)}}
        self.path.write_text(json.dumps(wallet))
        self.receipt('settled', .01)
        state = self.state()
        self.assertEqual(balance(state), 100)
        self.assertEqual(state['creditCharges']['request']['payer'], 'synesis')
        self.assertEqual(Decimal(state['creditCharges']['request']['providerUsd']), Decimal('.01'))
        self.assertFalse(state['creditPendingRequests'])

    def test_process_death_releases_reservation_without_claiming_zero_usage(self):
        script = """
import sys
from pathlib import Path
from pdf_credit_billing import Billing
Billing(Path(sys.argv[1]), 'operation', 'summary', ledger_path=sys.argv[2]).reserve('request', .02)
print('ready', flush=True)
sys.stdin.read()
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parent.resolve()))
        child = subprocess.Popen([sys.executable, '-c', script, str(self.path), str(self.ledger)],
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertIn('request', self.state()['creditHolds'])
            child.terminate(); child.wait(timeout=10)
            state = self.state()
            self.assertEqual(available(state), 100)
            self.assertFalse(state['creditHolds'])
            self.assertNotIn('request', state['creditCharges'])
            self.assertEqual(state['creditPendingRequests']['request']['reservationReleaseReason'], 'owner_stopped')
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def test_restart_replays_settlement_even_when_hold_owner_stopped(self):
        wallet = self.state()
        wallet['creditHolds']['request'] = {'credits': '20', 'operationId': 'operation',
            'createdAtMs': 1, 'category': 'summary', 'ledgerPath': str(self.ledger)}
        self.path.write_text(json.dumps(wallet))
        self.receipt('settled', .01)
        first = self.state()
        self.assertLess(balance(first), 100)
        self.assertFalse(first['creditHolds'])
        self.assertFalse(first.get('creditPendingRequests'))
        self.assertEqual(self.state(), first)

    def test_legacy_unknown_or_lost_ledger_does_not_lock_funds_or_erase_evidence(self):
        wallet = self.state()
        wallet['creditOperations']['operation'] = {'category': 'summary', 'createdAtMs': 1,
            'credits': '0', 'unknownRequests': 1}
        wallet['creditHolds']['request'] = {'credits': '20', 'operationId': 'operation',
            'createdAtMs': 1, 'unknown': True, 'ledgerPath': str(self.ledger)}
        self.path.write_text(json.dumps(wallet))
        self.ledger.write_text('{broken')
        first = self.state()
        self.assertEqual(available(first), 100)
        self.assertFalse(first['creditCharges'])
        self.assertIn('request', first['creditPendingRequests'])
        self.assertEqual(first['creditOperations']['operation']['unknownRequests'], 1)
        self.assertEqual(self.state(), first)


if __name__ == '__main__':
    unittest.main()
