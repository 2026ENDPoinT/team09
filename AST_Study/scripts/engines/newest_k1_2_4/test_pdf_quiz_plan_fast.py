"""Offline checks for quiz default scope (legacy Fast regression), billing and paid-cache reuse."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

import pdf_ai as ai
from audit_pdf_cost_metrics import request_metrics


def response(tier='default'):
    result = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
              'usage': {'prompt_tokens': 1000, 'completion_tokens': 100,
                        'prompt_tokens_details': {'cached_tokens': 200, 'cache_write_tokens': 300}}}
    if tier is not None:
        result['service_tier'] = tier
    return result


class QuizPlanFastTests(unittest.TestCase):
    def test_quiz_uses_default_without_changing_other_tasks(self):
        with TemporaryDirectory() as tmp:
            for kind, task, effort in [('quiz_plan', 'quiz_plan', 'none'),
                                       ('quiz_questions', 'quiz_questions', 'low'),
                                       ('quiz_review', 'quiz_review', 'medium'),
                                       ('quiz_plan', 'quiz_questions', 'none'),
                                       ('region_study', 'fixture', 'none'),
                                       ('summary_reduce', 'fixture', 'none'),
                                       ('tutor', 'fixture', 'none')]:
                with self.subTest(kind=kind, task=task):
                    send = Mock(return_value=response())
                    provider = ai.Provider(Path(tmp)/f'{kind}-{task}', True, 1,
                                           transport=send, group_service_tier='default')
                    provider.context = {'kind': kind, 'reasoningEffort': effort}
                    provider.complete({'task': task}, max_output=100, system_prompt='fixture',
                                      cache_stable_prefix=True)
                    body = send.call_args.args[0]
                    quiz = task in ('quiz_plan','quiz_questions')
                    self.assertEqual(body.get('service_tier'), 'default' if quiz else None)
                    self.assertEqual(body['reasoning_effort'], effort)
                    entry = provider.ledger['requests'][0]
                    cost = (800*.1+200*.01+100*.5+300*.025)/1e6
                    self.assertAlmostEqual(entry['estimatedUsd'], cost)
                    self.assertAlmostEqual(request_metrics(entry)['usageBasedUsd'], cost)
                    if quiz:
                        self.assertEqual(entry['requestedServiceTier'], 'default')
                        self.assertEqual(entry['billedServiceTier'], 'default')

    def test_default_reservation_and_returned_tier_settlement(self):
        with TemporaryDirectory() as tmp:
            for tier in ('default', 'fast', None):
                with self.subTest(returned=tier):
                    send = Mock(return_value=response(tier))
                    provider = ai.Provider(Path(tmp)/str(tier), True, 1, transport=send)
                    provider.context = {'kind': 'quiz_plan'}
                    provider.complete({'task': 'quiz_plan'}, max_output=100, system_prompt='fixture')
                    entry = provider.ledger['requests'][0]
                    factor = 2 if tier == 'fast' else 1
                    self.assertAlmostEqual(entry['reservedUsd'],
                                           (entry['inputTokenBound']*.1+100*.5)/1e6)
                    self.assertAlmostEqual(entry['estimatedUsd'], (800*.1+200*.01+100*.5+300*.025)/1e6*factor)
                    self.assertEqual(entry['billedServiceTier'], 'fast' if tier == 'fast' else 'default')

    def test_default_budget_checked_before_network(self):
        with TemporaryDirectory() as tmp:
            send = Mock(side_effect=AssertionError('network must not run'))
            provider = ai.Provider(Path(tmp), True, .00001, transport=send)
            provider.context = {'kind': 'quiz_plan'}
            with self.assertRaises(ai.BudgetExceeded):
                provider.complete({'task': 'quiz_plan'}, max_output=1000, system_prompt='fixture')
            send.assert_not_called()

    def test_tier_change_does_not_charge_again_for_saved_allocation(self):
        with TemporaryDirectory() as tmp:
            send = Mock(return_value=response('default'))
            first = ai.Provider(Path(tmp), True, 1, transport=send)
            first.context = {'kind': 'fixture'}
            payload = {'task': 'quiz_plan', 'outline': [], 'catalog': []}
            expected = first.complete(payload, max_output=100, system_prompt='fixture')
            send.assert_called_once()
            no_send = Mock(side_effect=AssertionError('saved allocation must be reused'))
            second = ai.Provider(Path(tmp), True, 1, transport=no_send)
            second.context = {'kind': 'quiz_plan'}
            self.assertEqual(second.complete(payload, max_output=100, system_prompt='fixture'), expected)
            no_send.assert_not_called()
            self.assertEqual(second.ledger['requests'], [])


if __name__ == '__main__':
    unittest.main()
