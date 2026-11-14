"""Offline effort/cache isolation for paid quiz generation and review calls."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pdf_ai as ai
from pdf_credit_billing import Billing, RATE, balance, wallet_lock


class QuizEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'document'
        self.calls = []
        for target in ((ai.urllib.request, 'urlopen'), (socket, 'create_connection'),
                       (socket.socket, 'connect')):
            guard = patch.object(*target, side_effect=AssertionError('unexpected network'))
            guard.start()
            self.addCleanup(guard.stop)
        credentials = patch.object(ai, 'api_key',
                                   side_effect=AssertionError('credentials must not be loaded'))
        credentials.start()
        self.addCleanup(credentials.stop)
        self.provider = ai.Provider(self.folder, True, 1, transport=self.transport)
        self.options = {'max_output': 200, 'system_prompt': '고정된 오프라인 검증 지침이다.'}

    def transport(self, body):
        self.calls.append(copy.deepcopy(body))
        return {'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps({'effort': body['reasoning_effort']})}}],
                'usage': {'prompt_tokens': 137, 'completion_tokens': 23,
                          'prompt_tokens_details': {'cached_tokens': 0}}}

    @staticmethod
    def payload(task):
        return {'task': task, 'requestId': 'offline-quiz-effort', 'source': '고정 시험 자료'}

    def test_none_and_low_quiz_calls_have_distinct_paid_caches(self):
        for task in ('quiz_plan', 'quiz_questions', 'quiz_review'):
            with self.subTest(task=task):
                payload = self.payload(task)
                self.provider.context = {'kind': task, 'reasoningEffort': 'none'}
                self.assertEqual(self.provider.complete(payload, **self.options), {'effort': 'none'})
                none_entry = copy.deepcopy(self.provider.ledger['requests'][-1])
                call_count = len(self.calls)
                self.provider.context['reasoningEffort'] = 'low'
                # A paid none response cannot satisfy a low cache-only lookup.
                with self.assertRaises(ai.AiResponseError):
                    self.provider.complete(payload, cache_only=True, **self.options)
                self.assertEqual(len(self.calls), call_count)
                self.assertEqual(self.provider.complete(payload, **self.options), {'effort': 'low'})
                low_entry = self.provider.ledger['requests'][-1]
                self.assertNotEqual(none_entry['payloadHash'], low_entry['payloadHash'])
                self.assertNotEqual(none_entry['responseCacheKey'], low_entry['responseCacheKey'])
                self.assertEqual(none_entry['inputTokenBound'], low_entry['inputTokenBound'])
                self.assertEqual(self.calls[-2]['reasoning_effort'], 'none')
                self.assertEqual(self.calls[-1]['reasoning_effort'], 'low')
                self.assertEqual(low_entry['reasoningEffort'], 'low')
                settled_count = len(self.provider.ledger['requests'])
                for effort in ('low', 'none', 'low'):
                    self.provider.context['reasoningEffort'] = effort
                    self.assertEqual(self.provider.complete(payload, cache_only=True, **self.options),
                                     {'effort': effort})
                self.assertEqual(len(self.calls), call_count + 1)
                self.assertEqual(len(self.provider.ledger['requests']), settled_count)

    def test_low_cache_is_reused_by_a_new_provider_without_a_charge(self):
        payload = self.payload('quiz_review')
        self.provider.context = {'kind': 'quiz_review', 'reasoningEffort': 'low'}
        self.provider.complete(payload, **self.options)
        second = ai.Provider(self.folder, True, 1, transport=lambda _: self.fail('paid cache was resent'))
        second.context = {'kind': 'quiz_review', 'reasoningEffort': 'low'}
        self.assertEqual(second.complete(payload, cache_only=True, **self.options), {'effort': 'low'})
        self.assertEqual(second.ledger['requests'], [])
        self.assertEqual(ai.run_usage(second)['usageBasedUsd'], 0)
        self.assertEqual(len(self.calls), 1)

    def test_medium_review_effort_has_its_own_cache_and_is_quiz_scoped(self):
        payload = self.payload('quiz_review')
        self.provider.context = {'kind': 'quiz_review'}
        for effort in ('none', 'low', 'medium'):
            self.provider.context['reasoningEffort'] = effort
            self.assertEqual(self.provider.complete(payload, **self.options), {'effort': effort})
        self.assertEqual([body['reasoning_effort'] for body in self.calls], ['none', 'low', 'medium'])
        self.assertEqual(len({entry['payloadHash'] for entry in self.provider.ledger['requests']}), 3)
        self.assertEqual(self.provider.complete(payload, cache_only=True, **self.options),
                         {'effort': 'medium'})
        self.assertEqual(len(self.calls), 3)
        for other in (self.payload('region_teaching'), self.payload('region_plan'),
                      self.payload('page_study'), {'taskType': 'tutor', 'question': '오프라인 질문'},
                      {'taskType': 'tutor', 'task': 'quiz_plan'}):
            with self.subTest(payload=other):
                with self.assertRaisesRegex(ValueError, '추론 설정'):
                    self.provider.complete(other, **self.options)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.provider.ledger['requests']), 3)

    def test_medium_plan_and_questions_wire_cache_reservation_and_usage(self):
        for task in ('quiz_plan', 'quiz_questions'):
            with self.subTest(task=task):
                payload = self.payload(task)
                self.provider.context = {'kind': task, 'reasoningEffort': 'low'}
                self.provider.complete(payload, **self.options)
                low = copy.deepcopy(self.provider.ledger['requests'][-1])
                count = len(self.calls)
                self.provider.context['reasoningEffort'] = 'medium'
                with self.assertRaises(ai.AiResponseError):
                    self.provider.complete(payload, cache_only=True, **self.options)
                self.assertEqual(len(self.calls), count)
                self.assertEqual(self.provider.complete(payload, **self.options), {'effort': 'medium'})
                entry = self.provider.ledger['requests'][-1]
                body = self.calls[-1]
                self.assertEqual(body['model'], 'gpt-6-luna')
                self.assertEqual(body['reasoning_effort'], 'medium')
                self.assertEqual(body['max_completion_tokens'], self.options['max_output'])
                self.assertEqual(body.get('service_tier'), 'default')
                self.assertEqual(entry['reasoningEffort'], 'medium')
                self.assertEqual(entry['state'], 'settled')
                self.assertEqual(entry['usage']['completion_tokens'], 23)
                self.assertEqual(entry['reservedUsd'], low['reservedUsd'])
                self.assertNotEqual(entry['payloadHash'], low['payloadHash'])
                self.assertNotEqual(entry['responseCacheKey'], low['responseCacheKey'])
                self.assertEqual(self.provider.complete(payload, cache_only=True, **self.options),
                                 {'effort': 'medium'})
                self.assertEqual(len(self.calls), count + 1)

    def test_high_is_plan_only_and_default_tier_is_charged(self):
        payload=self.payload('quiz_plan')
        self.provider.context={'kind':'quiz_plan','reasoningEffort':'high'}
        self.provider.complete(payload,**self.options)
        entry=self.provider.ledger['requests'][-1]
        self.assertEqual(self.calls[-1]['service_tier'],'default')
        self.assertEqual(self.calls[-1]['reasoning_effort'],'high')
        self.assertEqual(entry['requestedServiceTier'],'default')
        self.assertEqual(entry['state'],'settled')
        for task in ('quiz_questions','quiz_review','region_plan','region_teaching','region_groups','page_study'):
            self.provider.context={'kind':task,'reasoningEffort':'high'}
            with self.assertRaisesRegex(ValueError,'추론 설정'):
                self.provider.complete(self.payload(task),**self.options)
        self.provider.context={'kind':'quiz_plan','reasoningEffort':'high'}
        with self.assertRaisesRegex(ValueError,'추론 설정'):
            self.provider.complete({'taskType':'tutor','task':'quiz_plan'},**self.options)
        self.assertEqual(len(self.calls),1)

    def test_high_plan_cache_does_not_reuse_medium_and_group_keeps_fast(self):
        payload=self.payload('quiz_plan')
        self.provider.context={'kind':'quiz_plan','reasoningEffort':'medium'}
        self.provider.complete(payload,**self.options)
        old=copy.deepcopy(self.provider.ledger['requests'][-1])
        self.provider.context['reasoningEffort']='high'
        with self.assertRaises(ai.AiResponseError):
            self.provider.complete(payload,cache_only=True,**self.options)
        self.provider.complete(payload,**self.options)
        new=self.provider.ledger['requests'][-1]
        self.assertNotEqual(old['responseCacheKey'],new['responseCacheKey'])
        self.assertEqual(old['reservedUsd'],new['reservedUsd'])
        self.assertEqual(new['billedServiceTier'],'default')
        self.provider.context={'kind':'region_plan','reasoningEffort':'low'}
        self.provider.complete(self.payload('region_plan'),**self.options)
        self.assertEqual(self.calls[-1]['service_tier'],'fast')

    def test_unspecified_quiz_effort_keeps_explicit_none_cache(self):
        payload = self.payload('quiz_questions')
        self.provider.context = {'kind': 'quiz_questions'}
        self.assertEqual(self.provider.complete(payload, **self.options), {'effort': 'none'})
        self.provider.context['reasoningEffort'] = 'none'
        self.assertEqual(self.provider.complete(payload, cache_only=True, **self.options), {'effort': 'none'})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.provider.ledger['requests']), 1)

    def test_stale_quiz_effort_does_not_change_other_tasks_or_their_cache(self):
        cases = [({'task': 'region_plan'}, 'none'),
                 ({'task': 'page_study'}, 'none'),
                 ({'task': 'review_topic_teaching'}, 'low'),
                 ({'taskType': 'tutor', 'question': '오프라인 질문'}, 'low')]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.provider.context = {'kind': payload.get('task', 'tutor'), 'reasoningEffort': 'none'}
                self.assertEqual(self.provider.complete(payload, **self.options), {'effort': expected})
                first_hash = self.provider.ledger['requests'][-1]['payloadHash']
                call_count = len(self.calls)
                self.provider.context['reasoningEffort'] = 'low'
                self.provider.context['temperature'] = 'stale quiz setting'
                self.assertEqual(self.provider.complete(payload, cache_only=True, **self.options),
                                 {'effort': expected})
                self.assertEqual(len(self.calls), call_count)
                self.assertEqual(self.provider.ledger['requests'][-1]['payloadHash'], first_hash)
                fresh = {**payload, 'fixtureVersion': 2}
                self.provider.complete(fresh, **self.options)
                self.assertEqual(self.calls[-1]['reasoning_effort'], expected)
                self.assertNotIn('temperature', self.calls[-1])

    def test_existing_region_teaching_low_effort_remains_supported(self):
        self.provider.context = {'kind': 'region_study', 'reasoningEffort': 'low'}
        self.assertEqual(self.provider.complete(self.payload('region_teaching'), **self.options),
                         {'effort': 'low'})
        self.assertEqual(self.calls[-1]['reasoning_effort'], 'low')

    def test_quiz_review_usage_and_wallet_include_only_new_paid_calls(self):
        wallet_path = Path(self.tmp.name) / 'credits-wallet.json'
        wallet_path.write_text(json.dumps({'version': 1, 'liveBilling': True,
            'baselineCredits': 0, 'highWaterCredits': 0, 'purchases': [{'credits': '100'}],
            'creditOperations': {}, 'creditCharges': {}, 'creditHolds': {}}))
        billing = Billing(wallet_path, self.provider.ledger['operationId'], 'quiz',
                          ledger_path=self.provider.ledger_path)
        self.provider.billing = billing
        self.provider.ledger['category'] = 'quiz'
        for task in ('quiz_questions', 'quiz_review'):
            self.provider.context = {'kind': task, 'reasoningEffort': 'low'}
            payload = self.payload(task)
            self.provider.complete(payload, **self.options)
            self.provider.complete(payload, cache_only=True, **self.options)
        usage = ai.run_usage(self.provider)
        self.assertEqual(usage['requests'], 2)
        self.assertEqual(usage['settledRequests'], 2)
        self.assertEqual(usage['byKind']['quiz_questions']['requests'], 1)
        self.assertEqual(usage['byKind']['quiz_review']['requests'], 1)
        self.assertGreater(usage['byKind']['quiz_review']['usageBasedUsd'], 0)
        self.assertAlmostEqual(usage['usageBasedUsd'],
            usage['byKind']['quiz_questions']['usageBasedUsd'] +
            usage['byKind']['quiz_review']['usageBasedUsd'], places=8)
        expected_credits = sum((Decimal(str(e['estimatedUsd'])) * RATE
                               for e in self.provider.ledger['requests']), Decimal(0))
        with wallet_lock(wallet_path) as wallet:
            self.assertEqual(len(wallet['creditCharges']), 2)
            self.assertFalse(wallet['creditHolds'])
            operation = wallet['creditOperations'][self.provider.ledger['operationId']]
            self.assertEqual(operation['category'], 'quiz')
            self.assertAlmostEqual(Decimal(operation['credits']), expected_credits, places=20)
            self.assertAlmostEqual(Decimal(100) - balance(wallet), expected_credits, places=20)
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
