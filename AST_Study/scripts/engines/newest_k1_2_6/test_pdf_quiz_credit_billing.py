"""Offline quiz-to-wallet contracts. All transport and wallet data are fixtures."""
import copy
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pdf_ai import Provider
from pdf_credit_billing import Billing, RATE, available, balance, wallet_lock
import pdf_quiz
from test_pdf_quiz import review_passthrough


class QuizCreditBillingTests(unittest.TestCase):
    def setUp(self):
        review_patch = patch.object(pdf_quiz, 'review_candidates', side_effect=review_passthrough, create=True)
        self.review = review_patch.start()
        self.addCleanup(review_patch.stop)
        transport_patch = patch.object(pdf_quiz, 'pack_generation_jobs', side_effect=lambda assignments, *unused: assignments)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)
        wire_patch = patch.object(pdf_quiz, 'wire_generation_payload', side_effect=lambda payload: (payload, {}))
        wire_patch.start()
        self.addCleanup(wire_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'document'
        self.wallet_path = Path(self.temp.name) / 'credits-wallet.json'
        # Three concurrent 128k output ceilings need larger temporary holds;
        # settlement must still charge only the fixture's actual token usage.
        self.write_wallet(500)
        self.calls = []
        self.call_lock = threading.Lock()

    def write_wallet(self, credits):
        self.wallet_path.write_text(json.dumps({
            'version': 1, 'liveBilling': True, 'baselineCredits': '0',
            'highWaterCredits': '0', 'purchases': [{'credits': str(credits)}],
            'creditOperations': {}, 'creditCharges': {}, 'creditHolds': {},
        }), encoding='utf-8')

    def wallet(self):
        with wallet_lock(self.wallet_path) as wallet:
            return copy.deepcopy(wallet)

    @staticmethod
    def fixture():
        document = {'documentId': 'fixture-document', 'fingerprint': 'fixture-fingerprint',
                    'pages': [{'number': 1}], 'chunks': []}
        concepts = [{'name': f'개념 {index}', 'entries': [{
            'definition': f'핵심 정의 {index}', 'explanation': f'핵심 설명 {index}',
            'evidence': [{'page': 1}],
        }]} for index in range(1, 4)]
        request = {'quiz': {'theme': 'practice_set', 'totalCount': 3,
                           'difficulty': '중', 'allowedTypes': ['ox']},
                   'studyContent': {'documentId': document['documentId'],
                                    'sourceFingerprint': document['fingerprint'],
                                    'concepts': concepts},
                   'studyGroups': [{'id': 'all', 'title': '연결된 개념',
                                    'conceptIndexes': [0, 1, 2]}],
                   'startPage': 1, 'endPage': 1}
        return document, request

    @staticmethod
    def plan():
        return {'allocations': [
            {'unitId': f'unit-{index}', 'conceptIds': [f'c{index}'],
             'counts': {'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0},
             'focus': f'개념 {index}의 조건'} for index in range(1, 4)
        ], 'unallocated': 0, 'reason': ''}

    @staticmethod
    def question(index):
        return {'type': 'ox', 'conceptIds': [f'c{index}'],
                'stem': f'개념 {index}의 정의가 성립하는 조건을 판단하라.',
                'options': [], 'answer': 'O', 'explanation': '정의의 조건에 부합한다.',
                'keyPoints': [], 'evidence': [{'sourceId': f'study:c{index}:e1',
                                              'quote': f'핵심 정의 {index}'}]}

    def provider(self, *, malformed=None, missing_usage=None, parallel=False):
        barrier = threading.Barrier(3) if parallel else None

        def transport(body):
            payload = json.loads(body['messages'][1]['content'])
            with self.call_lock:
                self.calls.append(copy.deepcopy(body))
            index = 0
            if payload['task'] == 'quiz_plan':
                result = self.plan()
            else:
                index = int(payload['assignment']['conceptIds'][0][1:])
                if barrier:
                    barrier.wait(timeout=5)
                result = {'questions': [self.question(index)], 'unfilled': 0, 'reason': ''}
            content = 'malformed fixture JSON' if index == malformed else json.dumps(result)
            response = {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
            if index != missing_usage:
                response['usage'] = {'prompt_tokens': 100 + index,
                                     'completion_tokens': 30 + index}
            return response

        provider = Provider(self.folder, True, 1, transport=transport)
        provider.billing = Billing(self.wallet_path, provider.ledger['operationId'], 'quiz',
                                   ledger_path=provider.ledger_path)
        provider.ledger['category'] = 'quiz'
        return provider

    def generate(self, provider):
        document, request = self.fixture()
        with patch.object(pdf_quiz, 'emit'):
            return pdf_quiz.generate(self.folder, document, request, provider)

    def assert_settled_cost_matches_wallet(self, provider):
        wallet = self.wallet()
        settled = [entry for entry in provider.ledger['requests'] if entry['state'] == 'settled']
        expected = sum((Decimal(str(entry['estimatedUsd'])) * RATE for entry in settled), Decimal(0))
        operation = wallet['creditOperations'][provider.ledger['operationId']]
        self.assertEqual(operation['category'], 'quiz')
        self.assertAlmostEqual(Decimal(operation['credits']), expected, places=20)
        self.assertAlmostEqual(Decimal(500) - balance(wallet), expected, places=20)
        self.assertEqual(len(wallet['creditCharges']), len(settled))
        return wallet

    def test_planning_and_parallel_questions_are_debited_once_and_cache_is_free(self):
        provider = self.provider(parallel=True)
        result = self.generate(provider)
        self.assertEqual(len(result['questions']), 3)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result['runUsage']['byKind']['quiz_plan']['requests'], 1)
        self.assertEqual(result['runUsage']['byKind']['quiz_questions']['requests'], 3)
        wallet = self.assert_settled_cost_matches_wallet(provider)
        self.assertFalse(wallet['creditHolds'])
        self.assertEqual(wallet['creditOperations'][provider.ledger['operationId']]['unknownRequests'], 0)

        # Reopening a saved workbook and replaying already-paid request caches
        # must not create a second charge, even if settlement is recovered twice.
        saved = json.loads(Path(result['resultPath']).read_text(encoding='utf-8'))
        self.assertEqual(saved['questions'], result['questions'])
        for entry in provider.ledger['requests']:
            provider.settle_credits(entry)
        for body in list(self.calls):
            provider.context = {'kind': json.loads(body['messages'][1]['content'])['task'],
                                'reasoningEffort': body['reasoning_effort']}
            provider.complete(json.loads(body['messages'][1]['content']),
                              max_output=body['max_completion_tokens'],
                              system_prompt=body['messages'][0]['content'],
                              response_format=body['response_format'])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.wallet(), wallet)

    def test_unusable_paid_question_reply_still_counts_toward_debit(self):
        provider = self.provider(malformed=2, parallel=True)
        result = self.generate(provider)
        self.assertEqual(len(result['questions']), 2)
        self.assertEqual(result['unfilled'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['runUsage']['settledRequests'], 4)
        self.assertEqual(len(self.calls), 4)
        wallet = self.assert_settled_cost_matches_wallet(provider)
        self.assertFalse(wallet['creditHolds'])

    def test_unknown_question_usage_keeps_evidence_without_reserving_balance(self):
        provider = self.provider(missing_usage=2, parallel=True)
        result = self.generate(provider)
        self.assertEqual(len(result['questions']), 3)
        self.assertEqual(result['runUsage']['unknownUsageRequests'], 1)
        wallet = self.assert_settled_cost_matches_wallet(provider)
        self.assertFalse(wallet['creditHolds'])
        self.assertEqual(available(wallet), balance(wallet))
        unknown = next(entry for entry in provider.ledger['requests']
                       if entry['state'] == 'usage_unknown')
        hold = wallet['creditPendingRequests'][unknown['requestId']]
        self.assertTrue(hold['unknown'])
        self.assertAlmostEqual(Decimal(hold['credits']),
                               Decimal(str(unknown['reservedUsd'])) * RATE, places=20)
        self.assertEqual(wallet['creditOperations'][provider.ledger['operationId']]['unknownRequests'], 1)
        provider.settle_credits(unknown)
        self.assertEqual(self.wallet(), wallet)

    def test_no_credit_stops_before_planning_transport(self):
        self.write_wallet(0)
        provider = self.provider()
        result = self.generate(provider)
        self.assertTrue(result['creditStopped'])
        self.assertFalse(result['questions'])
        self.assertFalse(self.calls)
        self.assertFalse(provider.ledger['requests'])
        wallet = self.wallet()
        self.assertEqual(balance(wallet), 0)
        self.assertFalse(wallet['creditCharges'])
        self.assertFalse(wallet['creditHolds'])


if __name__ == '__main__':
    unittest.main()
