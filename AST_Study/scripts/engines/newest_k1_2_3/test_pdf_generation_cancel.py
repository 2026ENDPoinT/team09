"""Desktop close must not leave an unresumable paid-request guard."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_ai import Provider, AiResponseError, MissingPaidResponseError
from pdf_generation_cancel import enable, prepare, retryable
from pdf_pipeline import write_json


def answer(body):
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


class CancelledGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.payload = {'task': 'cancel fixture'}
        self.first = Provider(self.folder, True, .1, transport=lambda _: (_ for _ in ()).throw(OSError('closed')))
        self.first.context = {'kind': 'region_plan', 'strategy': 'newest-k1-1'}
        with self.assertRaises(AiResponseError):
            self.first.complete(self.payload)
        self.entry = self.first.ledger['requests'][0]
        self.cache = self.folder / 'generated/paid-responses' / (self.entry['responseCacheKey'] + '.json')

    def save(self):
        write_json(self.first.ledger_path, self.first.ledger)

    def cancelled_receipt(self, status='cancelled', usage=None):
        self.entry.update(clientStopReason='user_cancelled', inputApi='responses', responseId='resp_fixture')
        self.save()
        write_json(self.cache.with_suffix('.cancel.receipt.json'),
                   {'id': 'resp_fixture', 'status': status, 'output': [], 'usage': usage})

    def provider(self):
        return Provider(self.folder, True, .1, transport=answer)

    def test_cancel_receipt_unblocks_next_run_and_preserves_unknown_cost(self):
        self.cancelled_receipt()
        before = self.entry['reservedUsd']
        p = self.provider()
        self.assertEqual(p.complete(self.payload), {'ok': True})
        old = json.loads(self.first.ledger_path.read_text())['requests'][0]
        self.assertEqual(old['reservedUsd'], before)
        self.assertEqual(old['state'], 'failed_or_uncertain')
        self.assertEqual(old['serverTerminalStatus'], 'cancelled')
        self.assertTrue(retryable(old))
        archive = self.cache.parent / 'cancelled' / self.entry['requestId']
        self.assertTrue((archive / self.cache.with_suffix('.cancel.receipt.json').name).is_file())
        self.assertEqual(len(p.ledger['requests']), 1)

    def test_uncancelled_timeout_keeps_duplicate_guard(self):
        with self.assertRaises(MissingPaidResponseError):
            self.provider().complete(self.payload)

    def test_foreground_close_applies_to_every_engine_without_repeating_same_run(self):
        for strategy in ('page-v1', 'semantic-v1', 'new-concept-v99', 'newest-k1', 'newest-k1-1', 'newest-k1-11', 'newest-k1-1-1', 'newest-m1'):
            with self.subTest(strategy=strategy):
                self.entry['strategy'] = strategy
                self.first.ledger['desktopCancelledAtMs'] = 1
                self.save()
                p = self.provider(); prepare(p)
                self.assertFalse(p._previous_uncached_request(self.entry['payloadHash']))
        # Cancelling a previous session cannot authorize a duplicate of the current one.
        p.ledger['requests'] = [dict(self.entry)]
        p.ledger['requests'][0]['cancellationDisposition'] = 'server_stopped'
        self.assertTrue(p._previous_uncached_request(self.entry['payloadHash'], current_only=True))

    def test_cancelled_partial_native_is_archived_not_reused_as_error(self):
        self.cancelled_receipt()
        write_json(self.cache.with_suffix('.responses.raw.json'), {'id': 'resp_fixture', 'status': 'cancelled', 'output': []})
        write_json(self.cache.with_suffix('.incomplete.json'), {'finishReason': 'unknown'})
        self.assertEqual(self.provider().complete(self.payload), {'ok': True})

    def test_completed_value_is_reused_without_new_request(self):
        self.cancelled_receipt()
        write_json(self.cache, {'ok': 'already finished'})
        p = self.provider()
        self.assertEqual(p.complete(self.payload), {'ok': 'already finished'})
        self.assertEqual(p.ledger['requests'], [])

    def test_completed_raw_is_recovered_without_new_request(self):
        self.cancelled_receipt()
        write_json(self.cache.with_suffix('.raw.json'), answer(None))
        p = self.provider()
        self.assertEqual(p.complete(self.payload), {'ok': True})
        self.assertEqual(p.ledger['requests'], [])

    def test_unconfirmed_remote_cancellation_stays_blocked(self):
        self.cancelled_receipt(status='in_progress')
        p = self.provider(); p.transport = None
        with patch('urllib.request.urlopen', side_effect=TimeoutError('offline')) as network:
            prepare(p)
        self.assertEqual(network.call_args.args[0].method, 'POST')
        self.assertTrue(network.call_args.args[0].full_url.endswith('/cancel'))
        self.assertTrue(p._previous_uncached_request(self.entry['payloadHash']))

    def test_known_cancellation_usage_is_settled_not_falsely_zeroed(self):
        self.cancelled_receipt(usage={'input_tokens': 100, 'output_tokens': 50})
        prepare(self.provider())
        old = json.loads(self.first.ledger_path.read_text())['requests'][0]
        self.assertEqual(old['state'], 'settled')
        self.assertGreater(old['estimatedUsd'], 0)

    def test_desktop_intent_persists_before_network_cleanup(self):
        import pdf_worker_control as control
        with patch.object(control, '_CANCEL', threading.Event()), patch.dict(control._INTENTS, {}, clear=True), patch.dict(control._JOBS, {}, clear=True):
            enable(self.first)
            control.cancel()
            saved = json.loads(self.first.ledger_path.read_text())
            self.assertGreater(saved['desktopCancelledAtMs'], 0)
            self.assertEqual(saved['requests'][0]['reservedUsd'], self.entry['reservedUsd'])


if __name__ == '__main__':
    unittest.main()
