"""K120 repetition protection through SSE, usage settlement and max-four race."""
import io
import json
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_study_connection as connection
import test_pdf_k120_provider as fixtures
from test_pdf_responses_transport import native
from test_pdf_study_connection import sse


class K120RepetitionProviderTests(unittest.TestCase):
    setUp = fixtures.ForegroundProviderTests.setUp
    provider = fixtures.ForegroundProviderTests.provider
    make = fixtures.ForegroundProviderTests.make

    def install(self, fail_count):
        self.posts = []
        self.gets = []
        def opener(req, timeout):
            if req.method == 'GET':
                self.gets.append(req)
                value = native()
                value['id'] = req.full_url.rsplit('/', 1)[1]
                # Deliberately schema-valid, completed receipt: a stream which
                # already looped still must not silently become the winner.
                return io.StringIO(json.dumps(value))
            self.assertEqual(req.method, 'POST')
            self.assertFalse(req.full_url.endswith('/cancel'))
            number = len(self.posts)
            self.posts.append(req)
            ident = 'resp_loop_' + str(number)
            start = {'type': 'response.created', 'response': {'id': ident, 'status': 'in_progress'}}
            if number < fail_count:
                return sse([start, {'type': 'response.output_text.delta', 'item_id': 'msg',
                    'delta': '{"concepts":[{"title":"' + r'\u000a0' * 300}])
            value = native(); value['id'] = ident
            return sse([start, {'type': 'response.output_text.delta', 'item_id': 'msg',
                               'delta': '{"ok":true}'},
                        {'type': 'response.completed', 'response': value}])
        self.opener.side_effect = opener

    def assert_costs_preserved(self, provider, count):
        entries = provider.ledger['requests']
        self.assertEqual(len(entries), count)
        self.assertTrue(all(entry['state'] == 'settled' for entry in entries))
        self.assertTrue(all(entry['usage']['prompt_tokens'] == 1000 for entry in entries))
        self.assertTrue(all(entry['usage']['completion_tokens'] == 100 for entry in entries))
        self.assertAlmostEqual(provider.spent, sum(entry['estimatedUsd'] for entry in entries))
        for entry in entries:
            path = provider.folder / 'generated/paid-responses' / (entry['responseCacheKey'] + '.responses.raw.json')
            self.assertEqual(json.loads(path.read_text())['usage'], native()['usage'])

    def test_bad_first_attempt_is_rejected_then_success_published_with_both_costs(self):
        provider = self.make(); provider.study_no_id_hedge = True
        self.install(1)
        result = ai.complete_study_delivery(provider, self.payload, **self.options)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(len(self.gets), 1)
        self.assert_costs_preserved(provider, 2)
        bad, good = provider.ledger['requests']
        self.assertEqual(bad['deliveryViolation'], 'repeated_short_field')
        self.assertFalse(bad.get('hedgeWinner'))
        self.assertTrue(good['hedgeWinner'])
        self.assertNotIn('clientCompletedJson', bad)

    def test_four_loops_exhaust_existing_race_without_fifth_fallback(self):
        provider = self.make(); provider.study_no_id_hedge = True
        self.install(4)
        with self.assertRaises(ai.AiResponseError) as failure:
            ai.complete_study_delivery(provider, self.payload, **self.options)
        self.assertTrue(failure.exception.study_hedge_exhausted)
        self.assertEqual(len(self.posts), 4)
        self.assertEqual(len(self.gets), 4)
        self.assert_costs_preserved(provider, 4)
        self.assertTrue(all(entry.get('deliveryViolation') == 'repeated_short_field'
                            for entry in provider.ledger['requests']))
        self.assertFalse(any(entry.get('hedgeWinner') for entry in provider.ledger['requests']))

    def test_other_engines_and_overview_do_not_opt_in(self):
        for strategy in ('newest-k1', 'newest-k1-1', 'newest-k1-11',
                         'newest-k1-1-1', 'newest-k1-1-2', 'newest-k1-1-3'):
            provider = self.provider()
            provider.context = {'kind': 'region_study', 'strategy': strategy, 'studyDurable': True}
            with patch.object(connection, 'request_once', return_value=native()) as once:
                provider.complete({**self.payload, 'case': strategy}, **self.options)
                self.assertIs(once.call_args.kwargs['reject_title_repetition'], False)
        provider = self.make(); provider.context['kind'] = 'summary_reduce'
        with patch.object(connection, 'request_once', return_value=native()) as once:
            provider.complete({'task': 'lecture_flow_from_planned_units', 'titles': ['원문 제목']},
                              **self.options)
            self.assertIs(once.call_args.kwargs['reject_title_repetition'], False)

    def test_source_exact_long_title_uses_single_request_without_discarding_text(self):
        source = '반복' * 750
        result = {'title': source}
        text = json.dumps(result, ensure_ascii=False)
        schema = {'type': 'object', 'properties': {'title': {'type': 'string'}},
                  'required': ['title'], 'additionalProperties': False}
        options = {**self.options, 'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'source_title_fixture', 'strict': True, 'schema': schema}}}
        def opener(req, timeout):
            self.assertEqual(req.method, 'POST')
            value = native()
            value['output'][1]['content'] = [{'type': 'output_text', 'text': text}]
            return sse([
                {'type': 'response.created', 'response': {'id': value['id'], 'status': 'in_progress'}},
                {'type': 'response.output_text.delta', 'item_id': 'msg', 'delta': text},
                {'type': 'response.completed', 'response': value}])
        self.opener.side_effect = opener
        provider = self.make(); provider.study_no_id_hedge = True
        payload = {**self.payload, 'blocks': [{'id': 'v2p1f0', 'text': source}]}
        self.assertEqual(ai.complete_study_delivery(provider, payload, **options), result)
        self.assertEqual(self.opener.call_count, 1)
        self.assert_costs_preserved(provider, 1)


if __name__ == '__main__':
    unittest.main()
