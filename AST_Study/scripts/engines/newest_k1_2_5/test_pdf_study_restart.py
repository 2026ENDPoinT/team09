"""Offline lost-planner restart fixtures. Every HTTP operation is mocked."""
import copy
import io
import json
import time
import unittest
import urllib.error

import pdf_ai as ai
from pdf_study_restart import planner_restart
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_responses_transport import native


class PlannerRestartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ResponsesProviderTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.payload = {'task': 'region_groups', 'targets': [{'id': 'source', 'text': 'Original source'}]}
        self.options = self.fixture.options
        self.fixture.reply({'id': 'chatcmpl_old', 'choices': [{'message': {'content': '{"ok":true}'},
            'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
        old = self.provider()
        self.assertEqual(old.complete(self.payload, **self.options), {'ok': True})
        self.path = old.ledger_path
        self.original = copy.deepcopy(old.ledger)
        self.entry = self.original['requests'][0]
        self.entry.update(state='reserved', chatCompletionId='chatcmpl_old')
        self.entry.pop('usage', None); self.entry.pop('estimatedUsd', None)
        self.path.write_text(json.dumps(self.original))
        for path in (old.folder / 'generated/paid-responses').glob('*'):
            path.unlink()
        self.calls = []

    def provider(self, retry=True):
        provider = self.fixture.provider(mode='chat', retry=retry)
        provider.context = {'kind': 'region_plan', 'studyConnectionRepairAllowed': True}
        return provider

    def install(self, failed=False):
        def opener(request, timeout):
            self.calls.append(request)
            if request.method == 'GET' or failed:
                raise urllib.error.HTTPError(request.full_url, 404 if request.method == 'GET' else 400,
                    'fixture error', {}, io.BytesIO(b'{}'))
            self.assertTrue(request.full_url.endswith('/responses'))
            stream = io.StringIO(json.dumps(native())); stream.headers = {}
            return stream
        self.fixture.opener.side_effect = opener

    def test_fresh_not_found_receipt_allows_exact_approved_planner_once(self):
        self.install(); provider = self.provider()
        self.assertEqual(provider.recover_pending_study(), [])
        self.assertEqual(ai.complete_study_delivery(provider, self.payload, **self.options), {'ok': True})
        self.assertEqual([r.method for r in self.calls], ['GET', 'POST'])
        request = json.loads(self.calls[-1].data)
        self.assertEqual(json.loads(request['input'][1]['content'][0]['text']), self.payload)
        self.assertTrue(request['background'])
        updated = json.loads(self.path.read_text())['requests'][0]
        self.assertEqual(updated['state'], 'reserved')
        self.assertTrue(updated['durableRecoveryConsumed'])
        self.assertEqual(provider.ledger['requests'][0]['durableRecoveryOf'], self.entry['requestId'])
        self.assertAlmostEqual(provider.spent, self.entry['reservedUsd'] + provider.ledger['requests'][0]['estimatedUsd'])
        calls = len(self.calls)
        self.assertEqual(ai.complete_study_delivery(self.provider(), self.payload, **self.options), {'ok': True})
        self.assertEqual(len(self.calls), calls)

    def test_failed_alternate_never_repeats_after_restart(self):
        self.install(failed=True); provider = self.provider(); provider.recover_pending_study()
        with self.assertRaises(ai.AiResponseError):
            ai.complete_study_delivery(provider, self.payload, **self.options)
        retry = self.provider(); retry.recover_pending_study()
        with self.assertRaises(ai.MissingPaidResponseError):
            ai.complete_study_delivery(retry, self.payload, **self.options)
        self.assertEqual(sum(r.method == 'POST' for r in self.calls), 1)

    def test_available_original_is_reused_without_any_generation(self):
        provider = self.provider(); provider.billing = None
        def opener(request, timeout):
            self.calls.append(request)
            self.assertEqual(request.method, 'GET')
            return io.StringIO(json.dumps({'id': self.entry['chatCompletionId'],
                'metadata': {'synesis_request_id': self.entry['recoveryRequestTag']},
                'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}))
        self.fixture.opener.side_effect = opener
        self.assertEqual(len(provider.recover_pending_study()), 1)
        self.assertEqual(ai.complete_study_delivery(provider, self.payload, **self.options), {'ok': True})
        self.assertEqual([r.method for r in self.calls], ['GET'])
        self.assertEqual(provider.ledger['requests'], [])

    def test_invalid_receipt_cannot_authorize_an_alternate(self):
        provider = self.provider()
        def opener(request, timeout):
            self.calls.append(request)
            self.assertEqual(request.method, 'GET')
            return io.StringIO(json.dumps({'id': 'chatcmpl_wrong', 'usage': {}}))
        self.fixture.opener.side_effect = opener
        self.assertEqual(provider.recover_pending_study(), [])
        with self.assertRaises(ai.MissingPaidResponseError):
            ai.complete_study_delivery(provider, self.payload, **self.options)
        self.assertEqual([r.method for r in self.calls], ['GET'])

    def test_no_retry_approval_or_fresh_lookup_never_sends(self):
        self.install(); provider = self.provider()
        with self.assertRaises(ai.MissingPaidResponseError):
            ai.complete_study_delivery(provider, self.payload, **self.options)
        self.assertFalse(self.calls)
        blocked = self.provider(retry=False); blocked.recover_pending_study()
        with self.assertRaises(ai.MissingPaidResponseError):
            ai.complete_study_delivery(blocked, self.payload, **self.options)
        self.assertEqual([r.method for r in self.calls], ['GET'])

    def test_original_unknown_cost_still_counts_toward_cap(self):
        self.entry['reservedUsd'] = 1.0
        self.path.write_text(json.dumps(self.original))
        self.install(); provider = self.provider(); provider.recover_pending_study()
        with self.assertRaises(ai.BudgetExceeded):
            ai.complete_study_delivery(provider, self.payload, **self.options)
        self.assertEqual([r.method for r in self.calls], ['GET'])
        self.assertFalse(json.loads(self.path.read_text())['requests'][0].get('durableRecoveryConsumed'))

    def test_wrong_identity_or_lookup_failure_or_teaching_never_authorizes(self):
        provider = self.provider()
        self.entry.update(receiptLookupHttpStatus=404, receiptLookupAtMs=int(time.time()*1000))
        self.path.write_text(json.dumps(self.original))
        identities = {self.entry['payloadHash']}
        self.assertIsNotNone(planner_restart(provider, identities, self.options['max_output']))
        for field, value in [('receiptLookupHttpStatus', 500), ('maxOutputTokens', 1),
                             ('kind', 'region_study'), ('state', 'settled'), ('inputApi', 'responses')]:
            ledger = copy.deepcopy(self.original); ledger['requests'][0][field] = value
            self.path.write_text(json.dumps(ledger))
            self.assertIsNone(planner_restart(provider, identities, self.options['max_output']))
        self.path.write_text(json.dumps(self.original))
        self.assertIsNone(planner_restart(provider, {'different'}, self.options['max_output']))


if __name__ == '__main__':
    unittest.main()
