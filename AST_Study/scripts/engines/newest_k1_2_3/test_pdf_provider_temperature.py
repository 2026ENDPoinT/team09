"""Offline coverage of opt-in sampling for none-effort region teaching only."""
import hashlib
import copy
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import urllib.error

import pdf_ai as ai
import pdf_new_concept_ver99_study as study


def response(answer='synthetic answer'):
    return {'choices': [{'message': {'content': json.dumps({'answer': answer})},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 120, 'completion_tokens': 30,
                      'prompt_tokens_details': {'cached_tokens': 0}}}


class ProviderTemperatureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'document'
        for target in ((ai.urllib.request, 'urlopen'), (socket, 'create_connection'),
                       (socket.socket, 'connect')):
            guard = patch.object(*target, side_effect=AssertionError('unexpected network'))
            guard.start()
            self.addCleanup(guard.stop)
        self.credentials = patch.object(ai, 'api_key',
            side_effect=AssertionError('credentials must not be loaded')).start()
        self.addCleanup(patch.stopall)
        self.payload = {'task': 'region_teaching', 'source': 'synthetic fixture'}
        self.options = {'max_output': 100, 'system_prompt': 'Offline fixture only.'}

    def provider(self, context=None, folder=None, transport=None):
        send = transport if transport is not None else Mock(return_value=response())
        p = ai.Provider(folder or self.folder, True, 1, transport=send)
        p.context = {'kind': 'region_study', **(context or {})}
        return p, send

    def test_unspecified_and_none_keep_legacy_body_hash_and_cached_response(self):
        p, send = self.provider()
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'synthetic answer'})
        body = send.call_args.args[0]
        self.assertNotIn('temperature', body)
        self.assertNotIn('temperature', p.ledger['requests'][0])
        # Delivery-only streaming instructions do not discard already billed
        # teaching. The source/model/sampling cache identity stays unchanged.
        legacy_messages=copy.deepcopy(body['messages'])
        self.assertIn('OUTPUT DELIVERY:',legacy_messages[0]['content'][-1]['text'])
        legacy_messages[0]['content']=self.options['system_prompt']
        encoded = json.dumps(legacy_messages, ensure_ascii=False).encode('utf-8')
        payload_hash = hashlib.sha256(encoded).hexdigest()
        response_hash = hashlib.sha256(p.model.encode() + b'\0' + b'100' + b'\0' + encoded).hexdigest()
        self.assertEqual(p.ledger['requests'][0]['payloadHash'], payload_hash)
        self.assertTrue((self.folder / 'generated' / 'paid-responses' /
                         (response_hash + '.json')).is_file())
        p.context['temperature'] = None
        self.assertEqual(p.complete(self.payload, cache_only=True, **self.options),
                         {'answer': 'synthetic answer'})
        send.assert_called_once()
        self.assertEqual(len(p.ledger['requests']), 1)

    def test_zero_is_sent_and_recorded_then_reused_as_float_without_api(self):
        p, send = self.provider({'temperature': 0, 'reasoningEffort': 'none'})
        p.complete(self.payload, **self.options)
        body = send.call_args.args[0]
        self.assertEqual(body['reasoning_effort'], 'none')
        self.assertEqual(body['temperature'], 0.0)
        self.assertIsInstance(body['temperature'], float)
        entry = p.ledger['requests'][0]
        self.assertEqual(entry['temperature'], 0.0)
        saved = json.loads(p.ledger_path.read_text())['requests'][0]
        self.assertEqual(saved['temperature'], 0.0)
        second, forbidden_send = self.provider({'temperature': 0.0})
        self.assertEqual(second.complete(self.payload, cache_only=True, **self.options),
                         {'answer': 'synthetic answer'})
        forbidden_send.assert_not_called()
        self.assertEqual(second.ledger['requests'], [])
        self.credentials.assert_not_called()

    def test_settings_separate_payload_hash_paid_cache_and_missing_response_guard(self):
        p, send = self.provider()
        hashes, paths, bounds = [], [], []
        for temperature in (None, 0, 0.5, 2):
            p.context['temperature'] = temperature
            p.complete(self.payload, **self.options)
            hashes.append(p.ledger['requests'][-1]['payloadHash'])
            paths.append(set((self.folder / 'generated' / 'paid-responses').glob('*.raw.json')))
            bounds.append(p.ledger['requests'][-1]['inputTokenBound'])
        self.assertEqual(send.call_count, 4)
        self.assertEqual(len(set(hashes)), 4)
        self.assertEqual([len(s) for s in paths], [1, 2, 3, 4])
        self.assertEqual(len(set(bounds)), 1)  # Sampling adds no prompt content/tokens.
        self.assertEqual([b.args[0].get('temperature') for b in send.call_args_list],
                         [None, 0.0, 0.5, 2.0])

    def test_cache_only_cannot_reuse_unspecified_result_for_zero_temperature(self):
        p, send = self.provider()
        p.complete(self.payload, **self.options)
        p.context['temperature'] = 0
        with self.assertRaises(ai.AiResponseError):
            p.complete(self.payload, cache_only=True, **self.options)
        send.assert_called_once()
        self.assertEqual(len(p.ledger['requests']), 1)

    def test_invalid_values_fail_before_reservation_cache_or_transport(self):
        invalid = (True, False, '0', -0.01, 2.01, float('nan'), float('inf'),
                   -float('inf'), [], {}, 10 ** 400)
        for index, value in enumerate(invalid):
            with self.subTest(value=repr(value)):
                p, send = self.provider({'temperature': value},
                    folder=Path(self.tmp.name) / str(index))
                with self.assertRaisesRegex(ValueError, '온도'):
                    p.complete(self.payload, **self.options)
                send.assert_not_called()
                self.assertEqual(p.ledger['requests'], [])
                self.assertFalse(p.ledger_path.exists())

    def test_temperature_does_not_reach_other_tasks_tutor_or_low_reasoning(self):
        cases = [
            ({'task': 'region_plan'}, {}, 'none'),
            ({'task': 'review_topic_teaching'}, {}, 'low'),
            ({'taskType': 'tutor', 'question': 'fixture'}, {}, 'low'),
            ({'task': 'region_teaching'}, {'reasoningEffort': 'low'}, 'low'),
            ({'sources': [], 'requiredElements': [], 'knownConceptNames': []}, {}, 'none'),
        ]
        for index, (payload, context, effort) in enumerate(cases):
            with self.subTest(payload=payload, effort=effort):
                p, send = self.provider(context, folder=Path(self.tmp.name) / str(index))
                p.complete(payload, **self.options)
                original_hash = p.ledger['requests'][0]['payloadHash']
                # Even a stale invalid setting must not affect unrelated work.
                p.context['temperature'] = 'invalid setting from another task'
                p.complete(payload, cache_only=True, **self.options)
                send.assert_called_once()
                body = send.call_args.args[0]
                self.assertNotIn('temperature', body)
                self.assertEqual(body['reasoning_effort'], effort)
                self.assertNotIn('temperature', p.ledger['requests'][0])
                self.assertEqual(p.ledger['requests'][0]['payloadHash'], original_hash)
                # Also inspect a newly sent request, rather than only a cache hit.
                fresh = {**payload, 'fixtureVersion': 2}
                p.complete(fresh, **self.options)
                self.assertNotIn('temperature', send.call_args.args[0])
                self.assertNotIn('temperature', p.ledger['requests'][-1])

    def test_failed_attempt_blocks_same_setting_but_not_explicit_different_setting(self):
        send = Mock(side_effect=urllib.error.URLError('synthetic failure'))
        p, _ = self.provider({'temperature': 0}, transport=send)
        with self.assertRaises(ai.AiResponseError):
            p.complete(self.payload, **self.options)
        self.assertEqual(p.ledger['requests'][0]['temperature'], 0)
        with self.assertRaises(ai.MissingPaidResponseError):
            p.complete(self.payload, **self.options)
        send.assert_called_once()
        p.context['temperature'] = 1
        send.side_effect = None
        send.return_value = response('different explicit sampling setting')
        self.assertEqual(p.complete(self.payload, **self.options),
                         {'answer': 'different explicit sampling setting'})
        self.assertEqual(send.call_count, 2)
        self.assertNotEqual(*[e['payloadHash'] for e in p.ledger['requests']])

    def test_none_and_low_teaching_responses_have_separate_reusable_paid_caches(self):
        send = Mock(side_effect=lambda body: response(body['reasoning_effort']))
        p, _ = self.provider({'reasoningEffort': 'none'}, transport=send)
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'none'})
        p.context['reasoningEffort'] = 'low'
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'low'})
        self.assertEqual(send.call_count, 2)
        self.assertNotEqual(*[e['payloadHash'] for e in p.ledger['requests']])
        self.assertEqual(len(list((self.folder / 'generated' / 'paid-responses').glob('*.raw.json'))), 2)
        self.assertEqual(*[e['inputTokenBound'] for e in p.ledger['requests']])
        for effort in ('none', 'low'):
            p.context['reasoningEffort'] = effort
            self.assertEqual(p.complete(self.payload, cache_only=True, **self.options), {'answer': effort})
        self.assertEqual(send.call_count, 2)

    def test_missing_low_paid_response_does_not_block_explicit_none_request(self):
        send = Mock(side_effect=urllib.error.URLError('synthetic low failure'))
        p, _ = self.provider({'reasoningEffort': 'low'}, transport=send)
        with self.assertRaises(ai.AiResponseError):
            p.complete(self.payload, **self.options)
        with self.assertRaises(ai.MissingPaidResponseError):
            p.complete(self.payload, **self.options)
        send.assert_called_once()
        p.context['reasoningEffort'] = 'none'
        send.side_effect = None
        send.return_value = response('none answer')
        self.assertEqual(p.complete(self.payload, **self.options), {'answer': 'none answer'})
        self.assertEqual(send.call_count, 2)
        self.assertNotEqual(*[e['payloadHash'] for e in p.ledger['requests']])

    def test_effort_context_does_not_change_unrelated_task_cache_identity(self):
        for index, payload in enumerate(({'task': 'region_plan'},
                                       {'taskType': 'tutor', 'question': 'fixture'})):
            with self.subTest(payload=payload):
                p, send = self.provider({'reasoningEffort': 'none'},
                    folder=Path(self.tmp.name) / str(index))
                p.complete(payload, **self.options)
                p.context['reasoningEffort'] = 'low'
                self.assertEqual(p.complete(payload, cache_only=True, **self.options),
                                 {'answer': 'synthetic answer'})
                send.assert_called_once()

    def test_teaching_identity_versions_the_payload_and_separates_low_canonical_reuse(self):
        with patch.multiple(study, NEUTRAL_VISUAL_HINT=False, STATEMENT_UNCERTAINTY=False,
                            OWNED_TEACHING=False, STUDY_TEMPERATURE=None,
                            IMAGE_REGION_LABELS=False, IMAGE_SOURCE_LABELS=False,
                            COMPACT_TABLE_SETUP=False, SOURCE_COVERAGE_HINT=False,
                            SOURCE_FACTS=False, VISUAL_TEACHING=False,
                            PARTIAL_NATIVE_VISUAL_HINTS=False,
                            STUDY_REASONING_EFFORT='none'):
            # Production none keeps the original contract; metadata stays opt-in.
            for hints in (False, True):
                with self.subTest(partialNativeVisualHints=hints), \
                     patch.object(study, 'PARTIAL_NATIVE_VISUAL_HINTS', hints):
                    base = [study.STUDY_PROMPT, study.STUDY_FORMAT]
                    if hints:
                        base.extend([study.TEACHING_PAYLOAD_VERSION,study.PARTIAL_NATIVE_VISUAL_HINT])
                    expected = study.digest(base)
                    self.assertEqual(study.teaching_identity(), expected)
                    with patch.object(study, 'STUDY_REASONING_EFFORT', 'low'):
                        self.assertNotEqual(study.teaching_identity(), expected)
                        self.assertEqual(study.teaching_identity(), study.digest(
                            [*base, ['reasoning_effort', 'low']]))


if __name__ == '__main__':
    unittest.main()
