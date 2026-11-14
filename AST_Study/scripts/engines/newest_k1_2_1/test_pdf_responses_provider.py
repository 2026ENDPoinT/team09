"""Synthetic HTTP integration for the opt-in single-study Responses route."""
from contextlib import contextmanager
import copy
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pdf_ai as ai
import pdf_api_slots as slots
from test_pdf_responses_transport import FORMAT, native


class ResponsesProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/'document'
        self.key = patch.object(ai, 'api_key', return_value='test-only-no-network').start()
        self.opener = patch.object(ai.urllib.request, 'urlopen', side_effect=AssertionError('No real network')).start()
        patch.object(socket.socket, 'connect', side_effect=AssertionError('No socket network')).start()
        self.observed = patch.object(slots, 'observe_rate_limits').start()
        self.settled = patch.object(slots, 'settle_rate_usage').start()
        self.admissions = []
        @contextmanager
        def admission(**kwargs):
            self.admissions.append(kwargs)
            self.assertEqual(Path(kwargs['directory']), Path(self.temp.name)/'isolated-rates')
            yield None
        patch.object(ai, 'api_slot', admission).start()
        self.addCleanup(patch.stopall)
        self.payload = {'task': 'region_teaching', 'blocks': [{'id': 'v2p1f0', 'text': r'원문 \(x-1\)'}]}
        self.options = {'max_output': 100, 'system_prompt': '고정 학습 지침 그대로예요.',
                        'response_format': copy.deepcopy(FORMAT), 'cache_stable_prefix': True}

    def provider(self, *, mode=None, retry=False):
        options = {} if mode is None else {'study_input_api': mode}
        provider = ai.Provider(self.folder, True, 1, retry_missing_responses=retry, **options)
        provider.rate_directory = Path(self.temp.name)/'isolated-rates'
        provider.context = {'kind': 'region_study'}
        provider.billing = Mock()
        return provider

    def reply(self, value):
        def open_fixture(*args, **kwargs):
            stream = io.StringIO(json.dumps(value, ensure_ascii=False))
            stream.headers = {}
            return stream
        self.opener.side_effect = open_fixture

    def test_durable_body_context_uses_retrievable_background_without_changing_source(self):
        self.reply(native());provider=self.provider(mode='chat')
        provider.context={'kind':'region_study','studyDurable':True}
        self.assertEqual(provider.complete(self.payload,**self.options),{'ok':True})
        body=json.loads(self.opener.call_args.args[0].data)
        self.assertTrue(body['background']);self.assertTrue(body['stream'])
        self.assertEqual(json.loads(body['input'][1]['content'][0]['text']),self.payload)
        self.assertEqual(provider.ledger['requests'][0]['inputApi'],'responses')

    def paths(self, entry):
        cache = self.folder/'generated'/'paid-responses'/(entry['responseCacheKey']+'.json')
        return cache, cache.with_suffix('.raw.json'), cache.with_suffix('.responses.raw.json')

    def test_chat_study_stream_keeps_source_schema_and_cache_prefix(self):
        value = {'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 1000, 'completion_tokens': 100}}
        self.reply(value);provider = self.provider()
        self.assertEqual(provider.complete(self.payload, **self.options), {'ok': True})
        request = self.opener.call_args.args[0];body = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertEqual(body['messages'][0]['role'], 'system')
        self.assertEqual(body['messages'][0]['content'][0], {'type': 'text', 'text': self.options['system_prompt'],
            'prompt_cache_breakpoint': {'mode': 'explicit'}})
        self.assertTrue(body['stream']);self.assertTrue(body['stream_options']['include_usage'])
        self.assertIn('never copy',body['messages'][0]['content'][1]['text'])
        self.assertEqual(json.loads(body['messages'][1]['content']), self.payload)
        self.assertEqual(body['response_format'], FORMAT)
        self.assertEqual(body['max_completion_tokens'], 100)
        self.assertNotIn('input', body)
        self.assertEqual(provider.ledger['requests'][0]['inputApi'],'chat')

    def test_study_opt_in_uses_responses_url_preserves_images_and_bills_native_usage(self):
        value = native();self.reply(value);provider = self.provider(mode='responses')
        image = {'width': 64, 'height': 64, 'data': 'data:image/webp;base64,EXACT-ORIGINAL'}
        before = copy.deepcopy((self.payload, image, self.options))
        self.assertEqual(provider.complete(self.payload, image=image, **self.options), {'ok': True})
        request = self.opener.call_args.args[0];body = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(body['input'][0]['role'], 'developer')
        self.assertEqual(body['input'][0]['content'][0]['prompt_cache_breakpoint'], {'mode': 'explicit'})
        self.assertEqual(json.loads(body['input'][1]['content'][0]['text']), self.payload)
        self.assertEqual(body['input'][1]['content'][1], {'type': 'input_image', 'image_url': image['data'], 'detail': 'high'})
        self.assertEqual(body['text']['format'], {'type': 'json_schema', **FORMAT['json_schema']})
        self.assertEqual(body['reasoning'], {'effort': 'none'})
        self.assertNotIn('messages', body)
        self.assertEqual((self.payload, image, self.options), before)
        self.assert_settled_native(provider, value)

    def assert_settled_native(self, provider, value):
        entry = provider.ledger['requests'][0]
        expected = (800*.1+200*.01+100*.5+300*.1*.25)/1e6
        self.assertEqual(entry['inputApi'], 'responses')
        self.assertEqual(entry['state'], 'settled')
        self.assertEqual(entry['usage']['prompt_tokens'], value['usage']['input_tokens'])
        self.assertEqual(entry['usage']['prompt_tokens_details'], value['usage']['input_tokens_details'])
        self.assertEqual(entry['usage']['completion_tokens_details'], value['usage']['output_tokens_details'])
        self.assertAlmostEqual(entry['estimatedUsd'], expected)
        provider.billing.settle.assert_called_once_with(entry['requestId'], expected)
        self.assertEqual(json.loads(self.paths(entry)[2].read_text()), value)
        return entry

    def test_nonstudy_tutor_stays_on_existing_chat_route_even_with_pilot_enabled(self):
        self.reply({'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 10}})
        provider = self.provider(mode='responses')
        self.assertEqual(provider.complete({'taskType': 'tutor', 'question': 'fixture'}, **self.options), {'ok': True})
        self.assertEqual(self.opener.call_args.args[0].full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertNotIn('inputApi',provider.ledger['requests'][0])

    def test_native_write_ttl_breakdown_is_kept_in_both_ledger_and_raw_with_normal_fee(self):
        value = native()
        value['usage']['input_tokens_details']['cache_write_tokens_details'] = {
            'ttl_12h_tokens': 0, 'ttl_30m_tokens': 300}
        self.reply(value);provider = self.provider(mode='responses')
        self.assertEqual(provider.complete(self.payload, **self.options), {'ok': True})
        entry = self.assert_settled_native(provider, value)
        saved = json.loads(provider.ledger_path.read_text())['requests'][0]
        self.assertEqual(saved['usage']['prompt_tokens_details'], value['usage']['input_tokens_details'])
        self.assertEqual(saved['usage']['completion_tokens_details'], value['usage']['output_tokens_details'])
        self.assertAlmostEqual(entry['cacheWritePremiumUsd'], 300*.1*.25/1e6)

    def test_commentary_then_final_json_uses_only_final_and_retains_full_paid_native(self):
        value = native();final = copy.deepcopy(value['output'][1]);final['phase'] = 'final_answer'
        value['output'] = [{'type': 'message', 'role': 'assistant', 'status': 'completed',
            'phase': 'commentary', 'content': [{'type': 'output_text', 'text': '{"unfinished":'}]}, final]
        self.reply(value);provider = self.provider(mode='responses')
        self.assertEqual(provider.complete(self.payload, **self.options), {'ok': True})
        self.assert_settled_native(provider, value)
        self.assertEqual(self.opener.call_count, 1)

    def test_multiple_explicit_finals_keep_usage_but_do_not_choose_any_paid_object(self):
        value = native();final = copy.deepcopy(value['output'][1]);final['phase'] = 'final_answer'
        value['output'] = [final, copy.deepcopy(final)]
        self.reply(value);provider = self.provider(mode='responses')
        with self.assertRaises(ai.AiResponseError):provider.complete(self.payload, **self.options)
        entry = self.assert_settled_native(provider, value)
        self.assertEqual(entry['finishReason'], 'unknown')
        self.assertEqual(self.opener.call_count, 1)

    def test_incomplete_and_malformed_output_still_settle_usage_and_keep_native(self):
        for mode in ('length', 'malformed'):
            with self.subTest(mode=mode):
                self.folder = Path(self.temp.name)/mode
                value = native()
                if mode == 'length':
                    value.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
                else:
                    value['output'] = []
                self.reply(value);provider = self.provider(mode='responses')
                with self.assertRaises(ai.AiResponseError):provider.complete(self.payload, **self.options)
                entry = self.assert_settled_native(provider, value)
                self.assertEqual(entry['finishReason'], 'length' if mode == 'length' else 'unknown')
                self.assertEqual(ai.run_usage(provider)['settledRequests'], 1)
                self.assertGreater(ai.run_usage(provider)['usageBasedUsd'], 0)

    def test_valid_paid_cache_reuse_never_sends_or_charges_twice(self):
        self.reply(native());first = self.provider(mode='responses')
        self.assertEqual(first.complete(self.payload, **self.options), {'ok': True})
        second = self.provider(mode='responses')
        self.opener.side_effect = AssertionError('Paid cache must avoid a second request')
        self.assertEqual(second.complete(self.payload, **self.options), {'ok': True})
        self.assertEqual(self.opener.call_count, 1)
        second.billing.reserve.assert_not_called();second.billing.settle.assert_not_called()
        self.assertEqual(second.ledger['requests'], [])

    def test_native_only_completed_crash_cache_recovers_without_resending(self):
        value = native();self.reply(value);first = self.provider(mode='responses')
        first.complete(self.payload, **self.options)
        entry = first.ledger['requests'][0];decoded, raw, native_path = self.paths(entry)
        decoded.unlink();raw.unlink()
        original = native_path.read_bytes()
        second = self.provider(mode='responses')
        self.opener.side_effect = AssertionError('Native durable answer must avoid second send')
        self.assertEqual(second.complete(self.payload, **self.options), {'ok': True})
        self.assertEqual(native_path.read_bytes(), original)
        self.assertEqual(self.opener.call_count, 1)
        second.billing.reserve.assert_not_called()

    def test_native_phased_final_overrides_old_bad_normalized_and_parsed_caches_without_send(self):
        value = native();final = copy.deepcopy(value['output'][1]);final['phase'] = 'final_answer'
        value['output'] = [{'type': 'message', 'role': 'assistant', 'phase': 'commentary',
            'content': [{'type': 'output_text', 'text': '{"unfinished":'}]}, final]
        self.reply(value);first = self.provider(mode='responses')
        self.assertEqual(first.complete(self.payload, **self.options), {'ok': True})
        decoded, raw, native_path = self.paths(first.ledger['requests'][0])
        original_native = native_path.read_bytes()
        decoded.write_text(json.dumps({'oldIncorrect': True}))
        raw.write_text(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"unfinished":{"ok":true}'}}], 'usage': {}}))
        second = self.provider(mode='responses')
        self.opener.side_effect = AssertionError('Correct final phase is already paid and durable')
        self.assertEqual(second.complete(self.payload, **self.options), {'ok': True})
        self.assertEqual(json.loads(decoded.read_text()), {'ok': True})
        self.assertEqual(json.loads(raw.read_text())['choices'][0]['message']['content'], '{"ok":true}')
        self.assertEqual(native_path.read_bytes(), original_native)
        self.assertEqual(self.opener.call_count, 1)
        second.billing.reserve.assert_not_called()

    def test_native_only_malformed_crash_cache_blocks_even_explicit_missing_retry(self):
        value = native();value['output'] = []
        self.reply(value);first = self.provider(mode='responses')
        with self.assertRaises(ai.AiResponseError):first.complete(self.payload, **self.options)
        decoded, raw, native_path = self.paths(first.ledger['requests'][0])
        for path in (decoded, raw, decoded.with_suffix('.incomplete.json')):
            path.unlink(missing_ok=True)
        original = native_path.read_bytes();second = self.provider(mode='responses', retry=True)
        self.opener.side_effect = AssertionError('Malformed paid native response must never auto-retry')
        with self.assertRaises(ai.AiResponseError):second.complete(self.payload, **self.options)
        self.assertEqual(native_path.read_bytes(), original)
        self.assertEqual(self.opener.call_count, 1)
        second.billing.reserve.assert_not_called()

    def test_stream_rejects_before_admission_reservation_or_send(self):
        provider = self.provider(mode='responses')
        with self.assertRaises(ValueError):provider.complete(self.payload, on_delta=Mock(), **self.options)
        self.opener.assert_not_called();provider.billing.reserve.assert_not_called()
        self.assertEqual(self.admissions, [])
        self.assertEqual(provider.ledger['requests'], [])


if __name__ == '__main__':
    unittest.main()
