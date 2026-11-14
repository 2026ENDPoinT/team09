"""Hidden selection context stays bounded, source-scoped, and within existing calls."""
import copy
import json
import unittest
from unittest.mock import patch

from pdf_ai import tutor, tutor_selection_context, run_tutor_request, TUTOR_MAX_OUTPUT
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import document, semantic


class PlanningProvider(Provider):
    def __init__(self, *args):
        super().__init__(*args)
        self.plans = []

    def plan_tutor(self, payload):
        self.plans.append(copy.deepcopy(payload))
        return super().plan_tutor(payload)


class SelectionContextTests(unittest.TestCase):
    def context(self):
        return {'documentId': 'doc', 'origin': '요약', 'title': '마티스의 삶의 기쁨',
                'pages': [16], 'context': '앞에서 설명한 관계는 $F=dp/dt$예요.'}

    def test_hidden_context_reaches_existing_call_but_not_question_memory_or_answer(self):
        for mode in ('quick', 'deep'):
            provider = PlanningProvider([reply('관계를 원문과 함께 설명해요.')], semantic('마티스'))
            question = '[이 관계를 말해요.]\n\n이 부분에 대해 상세히 설명해줘.'
            context = self.context()
            result = tutor(document(), question, provider, current_page=1, mode=mode,
                               selection_context=context)
            payload = provider.calls[0][0]
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(len(provider.plans), 1)
            self.assertNotIn('context', provider.plans[0]['selectionLocation'])
            self.assertEqual(provider.calls[0][1]['max_output'], TUTOR_MAX_OUTPUT[mode])
            self.assertEqual(provider.searches, [])
            self.assertEqual(payload['question'], question)
            self.assertEqual(payload['selectionContext']['context'], context['context'])
            self.assertEqual(payload['requestedPdfPage'], 16)
            self.assertNotIn('currentPdfPage',payload)
            self.assertNotIn('documentId', payload['selectionContext'])
            self.assertEqual(result['memory']['turns'][-1]['question'], question)
            self.assertNotIn('selectionContext', json.dumps(result['memory'], ensure_ascii=False))
            self.assertEqual(result['answer'], '관계를 원문과 함께 설명해요.')
            self.assertEqual(context, self.context())

    def test_existing_requests_do_not_get_context_or_extra_prompt(self):
        provider = Provider([reply('설명해요.')], semantic('마티스'))
        tutor(document(), '마티스 설명해줘', provider)
        self.assertNotIn('selectionContext', provider.calls[0][0])
        self.assertNotIn('selectionContext is', provider.calls[0][0]['task'])

    def test_untrusted_or_stale_input_is_bounded_and_pages_are_validated(self):
        for invalid in (None, [], 'text', {}, {'origin': '요약', 'title': []},
                        {**self.context(), 'documentId': 'another-doc'}):
            self.assertEqual(tutor_selection_context(document(), invalid), {})
        context = {**self.context(), 'title': '가'*200,
                   'context': '$'+('x'*500)+'$', 'pages': [True, 16, 16, -1, 999, '2', 17]}
        value = tutor_selection_context(document(), context)
        self.assertEqual(len(value['title']), 80)
        self.assertEqual(value['pages'], [16, 17])
        self.assertNotIn('context', value)
        self.assertLess(len(json.dumps(value, ensure_ascii=False)), 200)

    def test_explicit_question_page_keeps_priority(self):
        provider = Provider([reply('요청한 페이지를 살펴봐요.')], semantic('작품', page=15))
        tutor(document(), '15페이지 내용을 설명해줘', provider, selection_context=self.context())
        self.assertEqual(provider.calls[0][0]['requestedPdfPage'], 15)

    def test_hidden_context_stays_in_the_single_answer_request(self):
        provider=Provider([reply('설명해요.')],semantic('마티스'))
        tutor(document(),'마티스 설명해줘',provider,selection_context=self.context())
        self.assertEqual(provider.calls[0][0]['selectionContext']['context'],self.context()['context'])
        self.assertEqual(len(provider.calls),1)

    def test_desktop_adapter_forwards_context(self):
        request = {'question': '선택한 내용을 설명해줘', 'strategy': 'new-concept-v99',
                   'selectionContext': self.context()}
        with patch('pdf_ai.tutor', return_value={'kind': 'no_evidence'}) as call:
            run_tutor_request(None, document(), request)
        self.assertEqual(call.call_args.args[-1], self.context())
        self.assertEqual(call.call_args.args[1], request['question'])


if __name__ == '__main__':
    unittest.main()
