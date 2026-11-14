"""Offline regression checks for admission cancellation and paid-attempt accounting.

Every transport is synthetic. The network opener rejects unexpected calls and
all real limiter use is confined to a temporary directory.
"""
from contextlib import ExitStack, contextmanager
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import urllib.error

import pdf_ai as ai
import pdf_api_slots as slots


def response(answer='fixture answer'):
    return {'choices': [{'message': {'content': json.dumps({'answer': answer})},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 120, 'completion_tokens': 30,
                      'prompt_tokens_details': {'cached_tokens': 0}}}


class ProviderAdmissionTest(unittest.TestCase):
    def test_transport_timing_retains_only_numeric_processing_header(self):
        p=self.provider(None)
        stream=io.StringIO(json.dumps(response()))
        stream.headers={'openai-processing-ms':'37.5','Authorization':'never-store-this-header'}
        self.opener.side_effect=None;self.opener.return_value=stream
        p.complete(self.payload,**self.options)
        entry=p.ledger['requests'][0]
        self.assertEqual(entry['serverProcessingMs'],37.5)
        self.assertGreater(entry['requestBodyBytes'],0)
        self.assertGreaterEqual(entry['connectionAndResponseHeadersSeconds'],0)
        self.assertGreaterEqual(entry['responseBodySeconds'],0)
        self.assertNotIn('never-store-this-header',p.ledger_path.read_text())

    def test_invalid_processing_header_cannot_discard_a_paid_response(self):
        p=self.provider(None)
        stream=io.StringIO(json.dumps(response()))
        stream.headers={'openai-processing-ms':'nan'}
        self.opener.side_effect=None;self.opener.return_value=stream
        result=p.complete(self.payload,**self.options)
        self.assertEqual(result['answer'],'fixture answer')
        self.assertEqual(p.ledger['requests'][0]['state'],'settled')
        self.assertNotIn('serverProcessingMs',p.ledger['requests'][0])

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'document'
        self.key = patch.object(ai, 'api_key', return_value='test-only-no-network').start()
        self.addCleanup(patch.stopall)
        self.opener = patch.object(ai.urllib.request, 'urlopen',
                                   side_effect=AssertionError('unexpected network')).start()
        self.payload = {'task': 'region_teaching', 'source': 'synthetic fixture'}
        self.options = {'max_output': 100, 'system_prompt': 'Synthetic offline test.'}

    def provider(self, transport):
        p = ai.Provider(self.folder, True, 1, transport=transport)
        p.rate_directory = Path(self.tmp.name) / 'isolated-rate-state'
        p.context = {'kind': 'region_study'}
        p.study_recovery_reads=1  # Offline failures need one receipt lookup, not a live outage wait.
        p.billing = Mock()
        return p

    def assert_not_sent(self, p):
        entry = p.ledger['requests'][-1]
        self.assertEqual(entry['state'], 'not_sent')
        self.assertNotIn('sentAtMs', entry)
        self.assertEqual(entry['estimatedUsd'], 0)
        self.assertAlmostEqual(p.spent, 0)
        p.billing.reserve.assert_called_once_with(entry['requestId'], entry['reservedUsd'])
        p.billing.settle.assert_called_once_with(entry['requestId'], 0)
        saved = json.loads(p.ledger_path.read_text())['requests'][-1]
        self.assertEqual(saved['state'], 'not_sent')
        usage = ai.run_usage(p)
        self.assertEqual(usage['requests'], 0)
        self.assertEqual(usage['settledRequests'], 0)
        self.assertEqual(usage['unknownUsageRequests'], 0)
        self.assertEqual(usage['notSentRequests'], 1)
        self.assertEqual(usage['uncertainReservedUsd'], 0)
        self.assertEqual(usage['usageBasedUsd'], 0)
        self.assertEqual(usage['byKind']['region_study']['requests'], 0)
        return entry

    def test_cancel_during_admission_releases_hold_and_allows_same_payload_again(self):
        send = Mock(return_value=response())
        p = self.provider(send)

        @contextmanager
        def waiting(check, **kwargs):
            check()  # The initial entry check passed; this queue poll is cancelled.
            yield

        with patch.object(ai, 'check_cancel', side_effect=[None, InterruptedError('cancelled')]), \
             patch.object(ai, 'api_slot', waiting):
            with self.assertRaises(InterruptedError):
                p.complete(self.payload, **self.options)
        send.assert_not_called()
        self.opener.assert_not_called()
        self.assert_not_sent(p)

        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'fixture answer'})
        send.assert_called_once()
        self.assertEqual(len(p.ledger['requests']), 2)
        self.assertEqual(p.ledger['requests'][1]['state'], 'settled')
        self.assertNotIn('retryOfMissingResponse', p.ledger['requests'][1])
        usage = ai.run_usage(p)
        self.assertEqual((usage['requests'], usage['notSentRequests'], usage['unknownUsageRequests']),
                         (1, 1, 0))
        self.assertAlmostEqual(p.spent, usage['usageBasedUsd'])

    def test_cancelled_prior_process_does_not_trigger_missing_paid_response_guard(self):
        first = self.provider(Mock(return_value=response()))

        @contextmanager
        def cancelled(**kwargs):
            raise InterruptedError('cancelled before network')
            yield

        with patch.object(ai, 'api_slot', cancelled):
            with self.assertRaises(InterruptedError):
                first.complete(self.payload, **self.options)
        self.assert_not_sent(first)
        # A new Provider scans the old on-disk ledger, just as a later UI run does.
        send = Mock(return_value=response('second operation'))
        second = self.provider(send)
        self.assertEqual(second.complete(self.payload, **self.options), {'answer': 'second operation'})
        send.assert_called_once()
        self.assertNotIn('retryOfMissingResponse', second.ledger['requests'][0])

    def test_request_larger_than_observed_project_cap_never_sends_and_refunds_hold(self):
        p = self.provider(None)
        slots.observe_rate_limits(p.model, {'x-ratelimit-limit-project-tokens': '1000'},
                                  p.rate_directory)
        with patch.dict('os.environ', {'SYNESIS_OPENAI_TIER': 'build'}):
            with self.assertRaises(ai.AiResponseError) as caught:
                p.complete(self.payload, **self.options)
        self.assertIsInstance(caught.exception.__cause__, slots.RateLimitRequestTooLarge)
        self.opener.assert_not_called()
        self.assert_not_sent(p)
        # The refused attempt must not poison duplicate prevention for this input.
        p.transport = Mock(return_value=response())
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'fixture answer'})
        p.transport.assert_called_once()

    def test_failure_after_network_attempt_preserves_unknown_reservation_and_blocks_duplicate(self):
        p = self.provider(None)
        self.opener.side_effect = urllib.error.URLError('synthetic connection lost')
        with self.assertRaises(ai.AiResponseError):
            p.complete(self.payload, **self.options)
        # One creation attempt, followed only by read-only metadata lookups of
        # its unique stored tag. A lost acknowledgement never permits POST #2.
        calls=[call.args[0]for call in self.opener.call_args_list]
        self.assertEqual(sum(request.method=='POST'for request in calls),1)
        self.assertTrue(all(request.method=='GET'for request in calls[1:]))
        entry = p.ledger['requests'][0]
        self.assertIn('sentAtMs', entry)
        self.assertEqual(entry['state'], 'failed_or_uncertain')
        self.assertAlmostEqual(p.spent, entry['reservedUsd'])
        p.billing.settle.assert_called_once_with(entry['requestId'], None)
        usage = ai.run_usage(p)
        self.assertEqual((usage['requests'], usage['notSentRequests'], usage['unknownUsageRequests']),
                         (1, 0, 1))
        self.assertAlmostEqual(usage['uncertainReservedUsd'], entry['reservedUsd'], places=8)
        previous_calls=self.opener.call_count
        with self.assertRaises(ai.MissingPaidResponseError):
            p.complete(self.payload, **self.options)
        self.assertEqual(self.opener.call_count,previous_calls)
        self.assertEqual(len(p.ledger['requests']), 1)

    def test_partial_stream_failure_keeps_unknown_hold_instead_of_marking_not_sent(self):
        p = self.provider(None)

        class InterruptedStream:
            # Intentionally no headers attribute: absence cannot invalidate a reply.
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                yield ('data: ' + json.dumps({'choices': [{'index': 0,
                    'delta': {'content': '{"answer":"partial'}, 'finish_reason': None}]})).encode()
                raise OSError('synthetic failure after output bytes')

        self.opener.side_effect = None
        self.opener.return_value = InterruptedStream()
        with self.assertRaises(ai.AiResponseError):
            p.complete(self.payload, on_delta=Mock(), **self.options)
        entry = p.ledger['requests'][0]
        self.assertIn('sentAtMs', entry)
        self.assertNotEqual(entry['state'], 'not_sent')
        self.assertAlmostEqual(p.spent, entry['reservedUsd'])
        p.billing.settle.assert_called_once_with(entry['requestId'], None)
        usage = ai.run_usage(p)
        self.assertEqual((usage['unknownUsageRequests'], usage['notSentRequests']), (1, 0))
        self.assertFalse(list((self.folder / 'generated' / 'paid-responses').glob('*.json')))
        with self.assertRaises(ai.MissingPaidResponseError):
            p.complete(self.payload, on_delta=Mock(), **self.options)
        self.opener.assert_called_once()

    def test_transport_fixtures_only_touch_private_test_slots_and_no_account_rate_state(self):
        p = self.provider(Mock(return_value=response()))
        with patch.object(slots, 'runtime_state', side_effect=AssertionError('global state touched')), \
             patch.object(ai, 'api_slot', wraps=slots.api_slot) as admission:
            p.complete(self.payload, **self.options)
        self.key.assert_not_called()  # Fake transport does not even load credentials.
        self.opener.assert_not_called()
        kwargs = admission.call_args.kwargs
        self.assertEqual(kwargs['directory'], self.folder / '.test-api-slots')
        self.assertIsNone(kwargs['model'])
        self.assertGreater(kwargs['input_tokens'], 0)
        self.assertEqual(kwargs['max_output'], 100)
        self.assertTrue(list((self.folder / '.test-api-slots').glob('*.lock')))
        self.assertFalse((self.folder / '.test-api-slots' / 'rate-state.json').exists())
        self.assertFalse(p.rate_directory.exists())

    def test_headerless_http_fixture_preserves_paid_cache_and_does_not_repeat_request(self):
        p = self.provider(None)
        self.opener.side_effect = None
        self.opener.return_value = io.BytesIO(json.dumps(response('saved answer')).encode())
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'saved answer'})
        self.opener.assert_called_once()
        paid = self.folder / 'generated' / 'paid-responses'
        self.assertEqual(len(list(paid.glob('*.raw.json'))), 1)
        self.assertEqual(len(list(paid.glob('*.json'))), 2)
        # A second UI read must return the preserved paid response offline.
        self.opener.side_effect = AssertionError('cached request must not send again')
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'saved answer'})
        self.opener.assert_called_once()
        self.assertEqual(len(p.ledger['requests']), 1)
        usage = ai.run_usage(p)
        self.assertEqual((usage['requests'], usage['settledRequests'], usage['unknownUsageRequests']),
                         (1, 1, 0))
        self.assertTrue((p.rate_directory / 'rate-state.json').is_file())

    def test_startup_capability_reaches_only_admission_not_wire_ledger_or_cache_identity(self):
        send=Mock(return_value=response());p=self.provider(send)
        slot_directory=p.folder/'.test-api-slots'
        with slots.startup_priority_slots(slot_directory) as priority, \
             patch.object(ai,'api_slot',wraps=slots.api_slot) as admission:
            p.context['_startup_priority']=priority
            self.assertEqual(p.complete(self.payload,**self.options),{'answer':'fixture answer'})
            self.assertIs(admission.call_args.kwargs['priority'],priority)
            self.assertEqual(admission.call_args.kwargs['directory'],slot_directory)
            self.assertEqual(priority._remaining,1)
            self.assertNotIn('_startup_priority',p.ledger['requests'][0])
            saved=p.ledger_path.read_text()
            self.assertNotIn('_startup_priority',saved)
            self.assertNotIn('StartupPrioritySlots',saved)
            # Cache reads spend no startup admission and send no new request.
            p.complete(self.payload,**self.options)
            self.assertEqual(priority._remaining,1)
            self.assertEqual(admission.call_count,1)
            self.assertEqual(send.call_count,1)
        other=ai.Provider(Path(self.tmp.name)/'ordinary-document',True,1,
                          transport=Mock(return_value=response()))
        other.context={'kind':'region_study'}
        other.complete(self.payload,**self.options)
        first_body=dict(send.call_args.args[0]);second_body=dict(other.transport.call_args.args[0])
        # Each independent generation has its own bookkeeping tag. This is
        # deliberately outside the prompt and stable paid-cache identity.
        self.assertNotEqual(first_body.pop('metadata'),second_body.pop('metadata'))
        self.assertEqual(first_body,second_body)
        self.assertEqual(p.ledger['requests'][0]['payloadHash'],other.ledger['requests'][0]['payloadHash'])
        first={path.name for path in (p.folder/'generated/paid-responses').glob('*.json')}
        second={path.name for path in (other.folder/'generated/paid-responses').glob('*.json')}
        self.assertEqual(first,second)
        self.opener.assert_not_called()

    def test_provider_first_two_priority_calls_use_extra_locks_while_all_fourteen_base_locks_are_busy(self):
        observed=[]
        p=self.provider(None)
        slot_directory=p.folder/'.test-api-slots'
        def send(body):
            busy=[]
            for number in (14,15):
                handle=slots._handle(slot_directory/f'{number}.lock')
                try:
                    if slots._try_lock(handle):slots._unlock(handle)
                    else:busy.append(number)
                finally:handle.close()
            observed.append(busy)
            self.assertEqual(busy,[14])
            self.assertNotIn('_startup_priority',json.dumps(body))
            return response()
        p.transport=send
        with ExitStack() as stack:
            priority=stack.enter_context(slots.startup_priority_slots(slot_directory))
            for _ in range(14):stack.enter_context(slots.api_slot(directory=slot_directory))
            p.context['_startup_priority']=priority
            for index in range(2):
                p.complete(dict(self.payload,unit=index),**self.options)
            self.assertEqual(observed,[[14],[14]])
            self.assertEqual(priority._remaining,0)
            # The unused physical extra is not a generic 16th ordinary slot.
            polls=0
            def cancelled(*_):
                nonlocal polls
                polls+=1
                if polls==3:raise InterruptedError('third call must wait')
            with self.assertRaisesRegex(InterruptedError,'third call must wait'), \
                 patch.object(ai,'check_cancel',side_effect=cancelled):
                p.complete(dict(self.payload,unit=2),**self.options)
            self.assertEqual(p.ledger['requests'][-1]['state'],'not_sent')
        self.assertNotIn('_startup_priority',p.ledger_path.read_text())
        self.opener.assert_not_called()

    def test_closed_startup_capability_downgrades_in_real_provider_admission_path(self):
        p=self.provider(None)
        self.opener.side_effect=None
        self.opener.return_value=io.BytesIO(json.dumps(response('ordinary after startup')).encode())
        with slots.startup_priority_slots(p.rate_directory) as priority, \
             patch.object(ai,'api_slot',wraps=slots.api_slot) as admission:
            priority.close()
            p.context['_startup_priority']=priority
            result=p.complete(self.payload,**self.options)
            self.assertEqual(result,{'answer':'ordinary after startup'})
            self.assertIs(admission.call_args.kwargs['priority'],priority)
            self.assertEqual(admission.call_args.kwargs['directory'],p.rate_directory)
            self.assertEqual(priority._remaining,2)
        self.assertEqual(p.ledger['requests'][0]['state'],'settled')
        self.assertNotIn('_startup_priority',p.ledger_path.read_text())
        state=json.loads((p.rate_directory/'rate-state.json').read_text())
        self.assertEqual(len(state['models'][p.model]['requests']),1)
        self.assertEqual(self.opener.call_count,1)


if __name__ == '__main__':
    unittest.main()
