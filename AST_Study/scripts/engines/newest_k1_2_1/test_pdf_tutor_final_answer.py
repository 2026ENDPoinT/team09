"""Final model text is preserved; local retrieval status is context, not a canned reply."""
import copy
import unittest

from pdf_ai import tutor, BudgetExceeded
from test_pdf_tutor_intent import document, semantic


class Provider:
    model = 'test-only'
    def __init__(self, values, plan=None, web=None):
        self.values = list(values)
        self.plan = plan
        self.web = web
        self.calls, self.searches = [], []
    def plan_tutor(self, payload):
        return self.plan
    def complete(self, payload, **kwargs):
        self.calls.append((copy.deepcopy(payload), kwargs))
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        if kwargs.get('on_delta'):
            kwargs['on_delta'](value['answer'][:len(value['answer'])//2])
            kwargs['on_delta'](value['answer'])
        return copy.deepcopy(value)
    def web_search(self, question, topic_hint=''):
        self.searches.append(question)
        if isinstance(self.web, Exception):
            raise self.web
        return self.web


def reply(text, **kwargs):
    return dict(answer=text, responseKind='general', notFound=False,
                needsExternalSearch=False, evidence=[], visualPages=[], **kwargs)


class FinalAnswerTests(unittest.TestCase):
    def test_disabled_lookup_state_reaches_model_without_replacing_its_answer(self):
        text = '검색이 꺼져 있어 현재 수치는 확인할 수 없어요. 이전에 확인한 값이 있으면 기준 시각과 함께 비교해 드릴게요.'
        provider = Provider([reply(text)], semantic('현재 통계', web='explicit'))
        result = tutor(document(), '통계를 외부 검색해줘', provider, web_fallback=False)
        self.assertEqual(provider.calls[0][0]['webSearchState']['status'], 'disabled')
        self.assertEqual(result['answer'], text)
        self.assertFalse(provider.searches)

    def test_no_hits_general_question_reaches_model_and_preserves_its_answer(self):
        doc = {'documentId': 'doc', 'pages': [{}], 'chunks': []}
        text = '먼저 목표와 마감일을 정하고, 어려운 부분부터 짧게 복습해 봐요.'
        provider = Provider([reply(text)], semantic('공부 방법'))
        result = tutor(doc, '이 자료를 공부할 때 어떻게 계획하면 좋아?', provider)
        self.assertEqual(result['answer'], text)
        self.assertEqual(provider.calls[0][0]['pdfEvidence']['status'], 'no_matches')
        self.assertEqual(provider.calls[0][0]['sources'], [])
        self.assertFalse(provider.searches)

    def test_required_pdf_missing_explanation_is_written_by_model_not_app(self):
        text = '찾은 범위에서는 실험 조건을 확인할 수 없어요. 실험 방법이 있는 페이지나 표를 알려주시면 조건을 대조해 드릴게요.'
        value = reply(text)
        value.update(responseKind='document', notFound=True, requiresPdfEvidence=True)
        provider = Provider([value], semantic('실험 조건'))
        result = tutor({'documentId': 'doc', 'pages': [{}], 'chunks': []},
                       '이 PDF 실험의 온도 조건을 정확히 알려줘', provider)
        self.assertEqual(result['answer'], text)
        self.assertTrue(result['notFound'])
        self.assertEqual(len(provider.calls), 1)

    def test_general_answer_with_pdf_words_is_not_replaced_by_missing_notice(self):
        text = 'PDF에 없는 가상의 예로 설명해 볼게요. 일을 맡긴 사람과 맡은 사람의 목표가 다를 수 있어요.'
        provider = Provider([reply(text)], semantic('주인 대리인', intent='illustrate'))
        result = tutor(document(), '이 PDF에 없는 사례로 설명해줘', provider)
        self.assertEqual(result['answer'], text)

    def test_bad_citations_are_filtered_locally_without_a_second_answer_call(self):
        initial = reply('자료를 이렇게 해석할 수 있어요.')
        initial.update(responseKind='document', evidence=[{'sourceId': 'fake', 'quote': '없는 문장'}])
        provider = Provider([initial], semantic('삶의 기쁨', page=16))
        result = tutor(document(), '16페이지의 의미는?', provider)
        self.assertEqual(result['answer'], initial['answer'])
        self.assertEqual(result['evidence'], [])
        self.assertTrue(result['evidenceIncomplete'])
        self.assertEqual(len(provider.calls),1)

    def test_ambiguous_current_quote_does_not_search_or_assume_currency_pair(self):
        text = '어떤 통화 사이의 환율을 말씀하세요? 예를 들어 달러와 원화인지 알려 주세요.'
        provider = Provider([reply(text, needsClarification=True)],
                            semantic('환율', web='none', ask=True))
        shown = []
        result = tutor(document(), '환율이 얼마야 지금?', provider, progress=shown.append)
        self.assertEqual(result['answer'], text)
        self.assertFalse(provider.searches)
        self.assertEqual(shown[-1], text)
        self.assertTrue(text.startswith(shown[0]))
        self.assertTrue(callable(provider.calls[0][1].get('on_delta')))

    def test_missing_plan_cannot_escalate_a_draft_into_paid_search(self):
        initial = reply('정확한 통화를 알려 주세요.')
        initial['needsExternalSearch'] = True
        final = {'answer': '검증용 검색 결과예요. [1]', 'webSources': [
            {'number': 1, 'title': 'fixture', 'url': 'https://example.org/rate'}]}
        # Planner failure stays closed, even when the draft requests a lookup.
        provider = Provider([initial], web=final)
        shown = []
        result = tutor(document(), '환율이 얼마야 지금?', provider, progress=shown.append)
        self.assertEqual(result['answer'], initial['answer'])
        self.assertEqual(shown[-1], initial['answer'])
        self.assertTrue(initial['answer'].startswith(shown[0]))
        self.assertEqual(len(provider.searches), 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['searchDecision']['reason'], 'planner_unavailable')

    def test_model_clarification_overrides_its_search_flag(self):
        value = reply('어느 통화와 어느 통화 사이를 비교할까요?', needsClarification=True)
        value['needsExternalSearch'] = True
        provider = Provider([value])
        result = tutor(document(), '환율이 얼마야 지금?', provider)
        self.assertFalse(provider.searches)
        self.assertEqual(result['answer'], value['answer'])

    def test_prefetch_search_failure_is_given_to_answer_model_without_retry(self):
        text = '지금은 외부 확인이 완료되지 않아 최신 수치를 확정할 수 없어요. 기준 시각과 확인 가능한 자료를 알려 주시면 함께 비교해 드릴게요.'
        provider = Provider([reply(text)], semantic('공식 통계', web='explicit'), web=RuntimeError('unavailable'))
        shown = []
        result = tutor(document(), '공식 통계를 외부 검색해줘', provider, progress=shown.append)
        self.assertEqual(result['answer'], text)
        self.assertEqual(provider.calls[0][0]['webSearchState']['status'], 'failed')
        self.assertFalse(provider.calls[0][0]['externalSearchAvailable'])
        self.assertEqual(len(provider.searches), 1)
        self.assertEqual(shown[-1], text)
        self.assertTrue(text.startswith(shown[0]))

    def test_draft_flag_never_creates_a_second_lookup_or_second_answer(self):
        initial = reply('확인해 볼게요.')
        initial['needsExternalSearch'] = True
        final = reply('외부 확인에 실패해서 최신값을 확정할 수 없어요. 어떤 기준의 환율이 필요한지 알려 주세요.')
        provider = Provider([initial, final], web=RuntimeError('unavailable'))
        shown = []
        result = tutor(document(), '환율이 얼마야 지금?', provider, progress=shown.append)
        self.assertEqual(len(provider.searches), 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(shown[-1], initial['answer'])
        self.assertTrue(initial['answer'].startswith(shown[0]))
        self.assertEqual(result['answer'], initial['answer'])

    def test_budget_exhaustion_is_an_operational_error_not_a_missing_pdf_reply(self):
        provider = Provider([BudgetExceeded('test budget')], semantic('공부'))
        with self.assertRaises(BudgetExceeded):
            tutor(document(), '공부 방법을 알려줘', provider)


if __name__ == '__main__':
    unittest.main()
