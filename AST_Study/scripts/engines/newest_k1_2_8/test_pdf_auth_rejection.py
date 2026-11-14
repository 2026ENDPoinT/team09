"""Credential-replacement recovery with synthetic responses and no network."""
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import Mock, patch

from pdf_ai import Provider, AiResponseError, MissingPaidResponseError
from pdf_auth_rejection import authentication_key_id, is_authentication_rejection
from pdf_study_batch_recovery import BatchRecoveryIndex
from pdf_study_receipts import reconcile
from test_pdf_study_batch_transport import fixture


def rejection(code='expired_secret_key', **extra):
    return {'state': 'failed_or_uncertain', 'httpStatus': 401,
            'apiError': {'type': 'invalid_request_error', 'code': code}, **extra}


def success(_):
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 5}}


class AuthenticationRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.payload = {'task': 'credential-retry-fixture'}
        self.calls = 0
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        self.network.start();self.addCleanup(self.network.stop)

    def provider(self, transport=success, key='sk-fixture-replacement'):
        provider = Provider(self.folder, True, .1, transport=transport)
        provider.key = key
        return provider

    def fail(self, body):
        self.calls += 1
        raise urllib.error.HTTPError('https://api.openai.com/v1/chat/completions', 401,
            'Unauthorized', {}, io.BytesIO(json.dumps({'error': {
                'code': 'expired_secret_key', 'message': 'Expired sk-fixture-old-key'}}).encode()))

    def first_failure(self):
        first = self.provider(self.fail, key='sk-fixture-old-key')
        with self.assertRaisesRegex(AiResponseError, '키를 변경'):
            first.complete(self.payload)
        self.assertEqual(self.calls, 1)
        entry = first.ledger['requests'][0]
        self.assertTrue(is_authentication_rejection(entry))
        self.assertEqual(entry['authenticationKeyId'], authentication_key_id(first.key))
        self.assertNotIn(first.key, first.ledger_path.read_text())
        return first

    def test_changed_key_retries_once_and_preserves_original_ledger_bytes(self):
        first = self.first_failure();original = first.ledger_path.read_bytes()
        send = Mock(side_effect=success);retry = self.provider(send)
        self.assertEqual(retry.complete(self.payload), {'ok': True})
        self.assertEqual(retry.complete(self.payload), {'ok': True})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(first.ledger_path.read_bytes(), original)
        self.assertNotIn('retryOfMissingResponse', retry.ledger['requests'][0])

    def test_unchanged_key_is_blocked_in_current_and_restarted_worker(self):
        first = self.first_failure()
        for provider in (first, self.provider(self.fail, key=first.key)):
            with self.subTest(restarted=provider is not first):
                with self.assertRaisesRegex(AiResponseError, '키가 그대로'):
                    provider.complete(self.payload)
                # A new payload must not evade same-key rejection.
                with self.assertRaisesRegex(AiResponseError, '키가 그대로'):
                    provider.complete({'task': 'another-unit'})
        self.assertEqual(self.calls, 1)

    def test_legacy_unfingerprinted_auth_failure_can_retry_without_rewriting_it(self):
        first = self.first_failure();entry = first.ledger['requests'][0]
        entry.pop('authenticationKeyId');entry.pop('authenticationRejected')
        first.ledger_path.write_text(json.dumps(first.ledger))
        original = first.ledger_path.read_bytes()
        self.assertEqual(self.provider().complete(self.payload), {'ok': True})
        self.assertEqual(first.ledger_path.read_bytes(), original)

    def test_unknown_401_and_non_auth_errors_remain_duplicate_blocked(self):
        first = self.first_failure()
        for status, code in ((401, None), (401, 'unknown_error'), (403, 'invalid_api_key'),
                             (429, 'insufficient_quota'), (500, 'server_error')):
            entry = copy.deepcopy(first.ledger['requests'][0])
            entry.update(httpStatus=status, apiError={'code': code})
            first.ledger['requests'] = [entry];first.ledger_path.write_text(json.dumps(first.ledger))
            send = Mock(side_effect=success)
            with self.subTest(status=status, code=code):
                with self.assertRaises(MissingPaidResponseError):
                    self.provider(send).complete(self.payload)
                send.assert_not_called()

    def test_another_uncertain_attempt_still_blocks_after_auth_rejection(self):
        first = self.first_failure();unknown = copy.deepcopy(first.ledger['requests'][0])
        unknown.pop('apiError');unknown.pop('httpStatus')
        unknown['requestId'] = 'different-uncertain-request'
        first.ledger['requests'].append(unknown);first.ledger_path.write_text(json.dumps(first.ledger))
        with self.assertRaises(MissingPaidResponseError):
            self.provider().complete(self.payload)

    def test_new_attempt_timeout_is_not_retryable_just_because_key_was_replaced(self):
        self.first_failure()
        send = Mock(side_effect=TimeoutError('synthetic response loss'))
        with self.assertRaises(AiResponseError):self.provider(send).complete(self.payload)
        with self.assertRaises(MissingPaidResponseError):self.provider(send).complete(self.payload)
        self.assertEqual(send.call_count, 1)

    def test_retry_still_obeys_the_new_run_budget(self):
        from pdf_ai import BudgetExceeded
        self.first_failure();provider = self.provider();provider.max_usd = .00000001
        with self.assertRaises(BudgetExceeded):provider.complete(self.payload)
        self.assertEqual(provider.ledger['requests'], [])

    def test_unconfirmed_cost_is_not_silently_rewritten_as_zero(self):
        first = self.first_failure()
        self.assertEqual(first.ledger['requests'][0]['state'], 'failed_or_uncertain')
        self.assertNotIn('estimatedUsd', first.ledger['requests'][0])


class AuthenticationEvidenceTests(unittest.TestCase):
    def test_only_known_credential_codes_without_acceptance_or_usage_are_eligible(self):
        for code in ('expired_secret_key', 'token_invalidated', 'invalid_api_key'):
            self.assertTrue(is_authentication_rejection(rejection(code)))
        for fields in ({'responseId': 'resp_accepted'}, {'chatCompletionId': 'chatcmpl-accepted'},
                       {'usage': {'prompt_tokens': 0}}, {'estimatedUsd': .001},
                       {'state': 'settled'}, {'state': 'usage_unknown'},
                       {'recoveredOriginalResponse': True}, {'httpStatus': '401'},
                       {'apiError': {'code': []}}, {'apiError': {'code': None}}):
            with self.subTest(fields=fields):
                self.assertFalse(is_authentication_rejection(rejection(**fields)))

    def test_batch_and_singleton_auth_history_does_not_block_or_rewrite_records(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory);usage = folder/'usage';usage.mkdir()
            jobs = [fixture(0, 0)['job'], fixture(1, 0)['job']]
            for ids in ([jobs[0]['id']], [job['id'] for job in jobs]):
                path = usage/'legacy.json'
                path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [
                    rejection(sentAtMs=123, kind='region_study', unitIds=ids)]}))
                before = path.read_bytes()
                index = BatchRecoveryIndex(folder, jobs, 'gpt-6-luna', 'new-concept-v99', 'same-teacher')
                self.assertFalse(index.single_history(jobs[0]))
                self.assertIsNone(index.recover(jobs[0]))
                self.assertEqual(path.read_bytes(), before)
            # An accepted response ID keeps even a superficially similar 401 protected.
            path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [
                rejection(sentAtMs=123, kind='region_study', unitIds=[job['id'] for job in jobs],
                          responseId='resp_accepted')]}))
            index = BatchRecoveryIndex(folder, jobs, 'gpt-6-luna', 'new-concept-v99', 'same-teacher')
            with self.assertRaises(MissingPaidResponseError):index.recover(jobs[0])

    def test_receipt_recovery_does_not_lookup_a_rejected_request_or_mutate_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory);usage = folder/'usage';usage.mkdir()
            path = usage/'legacy.json'
            path.write_text(json.dumps({'model': 'gpt-6-luna', 'requests': [rejection(
                sentAtMs=123, kind='region_plan', inputApi='chat', responseCacheKey='a'*64,
                recoveryRequestTag='b'*32)]}))
            before = path.read_bytes();opener = Mock(side_effect=AssertionError('No lookup'))
            provider = SimpleNamespace(folder=folder, model='gpt-6-luna', transport=None,
                                       ledger_path=usage/'new.json')
            self.assertEqual(reconcile(provider, open_url=opener), [])
            opener.assert_not_called();self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
