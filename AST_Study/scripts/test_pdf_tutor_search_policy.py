"""Spending regressions: PDF verification is not paid independent verification."""
import unittest
import tempfile
from pathlib import Path

from pdf_ai import tutor, BudgetExceeded, Provider, completed_web_searches, web_search_result
from pdf_tutor_intent import refined_plan, plan_question
from test_pdf_tutor_intent import Replay, document, semantic


class SearchPolicyTests(unittest.TestCase):
    def test_pdf_wording_cannot_spend_even_if_planner_mislabels_verification(self):
        questions = ['이 PDF에서 탄생을 검색해줘', '17페이지 문장이 실제로 맞는지 확인해줘',
                     '지금 이 자료의 숫자로 계산한 결과가 맞아?',
                     '원문에서 내 해석을 뒷받침하는 근거를 찾아줘',
                     'Search this PDF for the definition and verify my calculation.']
        for question in questions:
            with self.subTest(question=question):
                provider = Replay({**semantic('탄생', web='verify'), 'scope': 'pdf'})
                result = tutor(document(), question, provider)
                self.assertEqual(provider.searches, [])
                self.assertEqual(result['searchDecision']['reason'], 'pdf_only')

    def test_stable_scope_blocks_conflicting_freshness_flag(self):
        for scope in ('pdf', 'general'):
            for web in ('fresh', 'verify', 'explicit'):
                provider = Replay({**semantic('원리', web=web), 'scope': scope})
                tutor(document(), '지금 배운 원리가 실제로 어떻게 작동하는지 확인해줘', provider)
                self.assertFalse(provider.searches)

    def test_missing_pdf_hit_and_answer_request_cannot_authorize_lookup(self):
        provider = Replay({**semantic('양자 얽힘'), 'scope': 'general'})
        result = tutor({'documentId': 'doc', 'pages': [{}], 'chunks': []},
                       '양자 얽힘을 쉬운 비유로 설명해줘', provider)
        self.assertFalse(provider.searches)
        self.assertEqual(result['kind'], 'ai_generated')
        self.assertTrue(provider.answers[0]['externalSearchAvailable'])

    def test_missing_required_conditions_override_explicit_lookup(self):
        provider = Replay({**semantic('환율', web='fresh'), 'scope': 'external',
                           'missingConditions': ['통화 쌍']})
        result = tutor(document(), '지금 환율을 외부 검색해줘', provider)
        self.assertFalse(provider.searches)
        self.assertEqual(result['searchDecision']['reason'], 'clarification_required')
        self.assertTrue(provider.answers[0]['questionPlan']['needsClarification'])

    def test_necessary_lookup_happens_before_any_draft(self):
        for web in ('fresh', 'verify'):
            provider = Replay({**semantic('기준금리', web=web), 'scope': 'external'})
            result = tutor(document(), '한국은행 기준금리 수치를 확인해줘', provider)
            self.assertEqual(len(provider.searches), 1)
            self.assertFalse(provider.answers)
            self.assertEqual(result['kind'], 'web_generated')

    def test_mentioning_pdf_does_not_block_a_needed_current_external_fact(self):
        provider = Replay({**semantic('한국은행 기준금리', web='fresh'), 'scope': 'external'})
        result = tutor(document(), '이 PDF에 나온 한국은행 기준금리는 지금 얼마야?', provider)
        self.assertEqual(len(provider.searches), 1)
        self.assertEqual(result['kind'], 'web_generated')

    def test_mixed_noncomparison_preserves_both_pdf_and_web_context(self):
        provider = Replay({**semantic('마티스', web='verify'), 'scope': 'mixed'})
        result = tutor(document(), '16페이지 내용을 설명하고 미술관 출처도 확인해줘', provider)
        self.assertEqual(len(provider.searches), 1)
        self.assertEqual(len(provider.answers), 1)
        self.assertTrue(provider.answers[0]['sources'])
        self.assertIn('savedWebResearch', provider.answers[0])
        self.assertTrue(result['evidence'])

    def test_failed_planner_does_not_spend_from_live_keywords(self):
        provider = Replay(BudgetExceeded('planner unavailable'))
        result = tutor(document(), '오늘 한국은행 기준금리는 얼마야?', provider)
        self.assertFalse(provider.searches)
        self.assertEqual(result['searchDecision']['reason'], 'planner_unavailable')

    def test_invalid_extended_plans_fall_back_without_exception(self):
        local = plan_question('뜻이 뭐야?', {}, 1, None)
        for extra in ({'scope': []}, {'missingConditions': 'country'},
                      {'missingConditions': [None]}):
            self.assertEqual(refined_plan(local, {**semantic('뜻'), **extra}, 17, None), local)

    def test_ignored_attempt_and_page_open_are_not_an_extra_paid_search(self):
        response = {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 20},
                    'output': [
                        {'type': 'web_search_call', 'status': 'completed',
                         'action': {'type': 'search', 'sources': [
                             {'url': 'https://example.org/actual', 'title': 'Actual'}]}},
                        {'type': 'web_search_call', 'status': 'completed',
                         'action': {'type': 'open_page'}},
                        {'type': 'web_search_call', 'status': 'searching',
                         'action': {'type': 'search', 'sources': [
                             {'url': 'https://example.org/ignored', 'title': 'Ignored'}]}},
                        {'type': 'message', 'content': [
                            {'type': 'output_text', 'text': '확인한 내용이에요.', 'annotations': []}]}]}
        self.assertEqual(len(completed_web_searches(response)), 1)
        with tempfile.TemporaryDirectory() as temp:
            provider = Provider(Path(temp), True, .1, transport=lambda body: response)
            result = provider.web_search('공식 자료를 확인해줘')
            self.assertEqual(provider.ledger['requests'][0]['webSearchCalls'], 1)
            self.assertAlmostEqual(provider.ledger['requests'][0]['estimatedUsd'], .01002)
            self.assertEqual([s['url'] for s in result['webSources']], ['https://example.org/actual'])

    def test_an_unprocessed_search_attempt_cannot_support_a_web_answer(self):
        response = {'status': 'completed', 'output': [
            {'type': 'web_search_call', 'status': 'searching', 'action': {'type': 'search'}}]}
        with self.assertRaises(ValueError):
            web_search_result(response)


if __name__ == '__main__':
    unittest.main()
