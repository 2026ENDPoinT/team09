"""Welcome actions are explicit document tasks, with one answer and unchanged display text."""
import copy
import json
import unittest
from unittest.mock import patch

import pdf_ai as ai
from pdf_tutor_starters import STARTERS, SOURCE_BYTES, context, resolve
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import chunk, semantic


class StarterTests(unittest.TestCase):
    def document(self, count=51):
        return {'documentId': 'doc', 'fingerprint': 'v1', 'pages': [{} for _ in range(count)],
                'chunks': [chunk(f'단원 {p}의 고유한 정의예요.\n' + '실제 개념과 조건을 설명해요. '*100 +
                                 f'\n마지막 단원 {p}의 결론이에요.', p, f'p{p}')
                           for p in range(1, count+1)]}

    def test_only_known_button_with_exact_visible_text_authorizes_hidden_task(self):
        for key, (text, _) in STARTERS.items():
            self.assertEqual(resolve(key, text), key)
            self.assertIsNone(resolve(key, text+' 다른 개념은?'))
            self.assertIsNone(resolve(key, text, attachment=True))
            self.assertIsNone(resolve(key, text, selection=True))
        for value in (None, {}, [], 'arbitrary instructions'):
            self.assertIsNone(resolve(value, STARTERS['key_concepts'][0]))

    def test_balanced_context_includes_late_pages_and_quotes_are_literal(self):
        doc = self.document()
        original = ai.model_sources(doc['chunks'], doc)
        packed = context(doc, original)
        self.assertEqual(packed['coverage']['locallyInspectedPages'], list(range(1,52)))
        self.assertEqual(packed['coverage']['textPages'], list(range(1,52)))
        self.assertEqual({s['page'] for s in packed['sources']}, set(range(1,52)))
        self.assertLessEqual(len(json.dumps(packed['sources'], ensure_ascii=False).encode()), SOURCE_BYTES)
        allowed = {s['sourceId']: s['text'] for s in original}
        for source in packed['sources']:
            self.assertIn(source['text'], allowed[source['sourceId']])
        self.assertFalse(packed['coverage']['allExtractedTextIncluded'])
        self.assertTrue(any('단원 51의 고유한 정의' in s['text'] for s in packed['sources']))

    def test_full_text_is_retained_when_small_and_missing_pages_are_not_claimed_readable(self):
        doc = self.document(3)
        doc['chunks'] = [chunk('첫 정의예요.', 1, 'one'), chunk('마지막 정의예요.', 3, 'three')]
        original = ai.model_sources(doc['chunks'], doc)
        packed = context(doc, original)
        self.assertEqual(packed['sources'], original)
        self.assertEqual(packed['coverage']['unavailablePages'], [2])
        self.assertEqual(packed['coverage']['fullTextPages'], [1,3])
        self.assertFalse(packed['coverage']['originalPageImagesIncluded'])

    def test_json_escaping_is_bounded_without_dropping_the_last_page(self):
        doc = self.document(24)
        for item in doc['chunks']:
            item['text'] = r'\frac{x}{y} = "definition" ' * 100 + '\n' + item['text']
        packed = context(doc, ai.model_sources(doc['chunks'],doc))
        self.assertLessEqual(len(json.dumps(packed['sources'],ensure_ascii=False).encode()),SOURCE_BYTES)
        self.assertEqual(packed['coverage']['textPages'],list(range(1,25)))

    def test_context_omission_is_not_misreported_as_missing_original_pdf_text(self):
        doc = self.document(600)
        packed = context(doc,ai.model_sources(doc['chunks'],doc))
        self.assertTrue(packed['coverage']['omittedTextPages'])
        self.assertFalse(packed['coverage']['unavailablePages'])

    def test_all_three_buttons_skip_planner_and_web_and_preserve_stream_and_memory(self):
        doc = self.document(6)
        stale = {'documentId':'doc', 'topicQuestion':'무관한 과거 개념',
                 'focus':{'subject':'과거 개념','page':2},
                 'sourceTask':{'page':2,'item':'3','action':'solve'},
                 'turns':[{'question':'3번 문제 풀어줘','answer':'어떤 문제인지 알려 주세요.'}]}
        for key, (text, policy) in STARTERS.items():
            with self.subTest(starter=key):
                provider = Provider([reply('요청한 자료 전체를 바탕으로 답해요.')],
                                    {**semantic('잘못된 과거 개념', page=2, ask=True), 'web':'explicit'})
                provider.ledger = {'requests':[]}
                provider.plan_tutor = lambda _: self.fail('a button must not pay a planner')
                stream = []
                with patch('pdf_ai.exhaustive_tutor_sources', side_effect=AssertionError('no paid map')):
                    result = ai.run_tutor_request(None, copy.deepcopy(doc),
                        {'question':text,'starterId':key,'page':4,'memory':stale,'webFallback':True},
                        provider, progress=stream.append)
                self.assertEqual(len(provider.calls),1)
                payload, options = provider.calls[0]
                self.assertEqual(payload['question'],text)
                self.assertEqual(policy,payload['starterTask'])
                self.assertNotIn(policy,options['system_prompt'])
                self.assertLess(list(payload).index('sources'),list(payload).index('starterTask'))
                self.assertEqual(payload['task'],ai.TUTOR_TASK)
                self.assertEqual(payload['starterId'],key)
                self.assertEqual(payload['documentTarget']['requestedScope'],'entire_document')
                self.assertEqual(payload['documentCoverage']['textPages'],list(range(1,7)))
                self.assertFalse(payload['questionPlan']['needsClarification'])
                self.assertIsNone(payload['questionPlan']['page'])
                self.assertEqual(payload['recentConversation'],[])
                self.assertNotIn('priorSource',payload)
                self.assertNotIn('sourceTask',payload)
                self.assertNotIn('image',options)
                self.assertFalse(provider.searches)
                self.assertFalse(payload['externalSearchAvailable'])
                self.assertEqual(result['memory']['turns'][-1]['question'],text)
                self.assertEqual(result['memory']['turns'][-1]['answer'],stream[-1])
                self.assertNotIn('sourceTask',result['memory'])
                self.assertEqual(stale['sourceTask']['page'],2)

    def test_same_document_is_a_stable_prefix_without_warmup_or_changed_visible_question(self):
        prefixes, systems = [], []
        for key,(text,_) in STARTERS.items():
            provider = Provider([reply('바로 답해요.')])
            ai.tutor(self.document(6),text,provider,starter_id=key)
            self.assertEqual(len(provider.calls),1)
            payload,options = provider.calls[0]
            prefix = {}
            for name,value in payload.items():
                if name == 'tutorReasoningEffort':break
                prefix[name]=value
            self.assertIn('sources',prefix)
            self.assertNotIn('starterId',prefix)
            prefixes.append(json.dumps(prefix,ensure_ascii=False))
            systems.append(options['system_prompt'])
        self.assertEqual(len(set(prefixes)),1)
        self.assertEqual(len(set(systems)),1)

    def test_typed_question_or_mismatched_id_keeps_existing_routing(self):
        for key in (None,'exam_prediction','untrusted task'):
            provider = Provider([reply('일반 질문 답변이에요.')],semantic('핵심 개념'))
            result = ai.tutor(self.document(3),STARTERS['key_concepts'][0],provider,
                              web_fallback=False,starter_id=key)
            payload = provider.calls[0][0]
            self.assertNotIn('starterId',payload)
            self.assertNotIn('documentCoverage',payload)
            self.assertEqual(result['answer'],'일반 질문 답변이에요.')

    def test_all_typed_labels_keep_the_current_learning_context_without_hidden_button_policy(self):
        doc=self.document(6)
        memory={'documentId':'doc','topicQuestion':'충격량과 운동량 변화의 관계',
                'focus':{'subject':'충격량과 운동량 변화의 관계','page':5},
                'turns':[{'question':'충격량이 운동량 변화와 같다는 게 무슨 뜻이야?',
                          'answer':'알짜힘이 일정 시간 작용해 운동량을 바꾼다는 뜻이에요.'}]}
        for key,(text,_) in STARTERS.items():
            with self.subTest(starter=key):
                provider=Provider([reply('지금 이야기하던 충격량을 이해하는 데 필요한 내용이에요.')],
                    {**semantic('충격량과 운동량 변화',page=5,followup=True),'scope':'pdf'})
                provider.ledger={'requests':[]}
                with patch('pdf_ai.starter_context',side_effect=AssertionError('typed message became button')), \
                     patch('pdf_ai.whole_document_guide',side_effect=AssertionError('unrequested document overview')):
                    result=ai.run_tutor_request(None,copy.deepcopy(doc),
                        {'question':text,'page':1,'memory':copy.deepcopy(memory),'webFallback':False},provider)
                payload,options=provider.calls[0]
                self.assertNotIn('starterId',payload)
                self.assertNotIn('starterTask',payload)
                self.assertNotIn('documentTarget',payload)
                self.assertNotIn('system_prompt',options)
                self.assertEqual(payload['questionPlan']['subject'],'충격량과 운동량 변화')
                self.assertIn(memory['turns'][-1]['question'],str(payload['recentConversation']))
                self.assertEqual(result['memory']['turns'][-1]['question'],text)

    def test_a_prior_button_id_in_history_never_reactivates_for_a_typed_message(self):
        doc=self.document(3);key='background_knowledge';text=STARTERS[key][0]
        provider=Provider([reply('현재 개념에 필요한 배경을 설명해요.')],
                          semantic('충격량의 배경',followup=True))
        provider.ledger={'requests':[]}
        memory={'documentId':'doc','starterId':key,
                'turns':[{'question':text,'answer':'문서 전반에 필요한 개념을 정리했어요.','starterId':key},
                         {'question':'충격량에 대해 설명해줘','answer':'운동량의 변화예요.'}],
                'focus':{'subject':'충격량','page':None}}
        ai.run_tutor_request(None,doc,{'question':text,'memory':memory,'webFallback':False},provider)
        payload,options=provider.calls[0]
        self.assertNotIn('starterId',payload)
        self.assertNotIn('starterTask',payload)
        self.assertNotIn('documentCoverage',payload)
        self.assertNotIn('system_prompt',options)


if __name__ == '__main__':
    unittest.main()
