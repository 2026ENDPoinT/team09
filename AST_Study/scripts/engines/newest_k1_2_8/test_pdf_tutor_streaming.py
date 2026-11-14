"""Offline streaming contracts: one answer, no review reset, terminal usage."""
import json
import itertools
import unittest
from unittest.mock import patch

from pdf_ai import tutor, collect_web_stream, collect_chat_stream, partial_json_answer, AiResponseError
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import document, semantic


class StreamingTests(unittest.TestCase):
    def test_external_model_prose_is_preserved_with_numbered_web_sources(self):
        shown=[]
        provider=Provider([],{**semantic('외부 자료',web='explicit'),'scope':'external'},
            web={'answer':'확인한 내용이에요. {Q2} [Q5] 출처는 [1]이에요.',
                 'webSources':[{'number':1,'title':'공식 자료','url':'https://example.org/reference'}]})
        result=tutor(document(),'외부 자료를 검색해줘',provider,progress=shown.append)
        self.assertEqual(result['answer'],'확인한 내용이에요. {Q2} [Q5] 출처는 [1]이에요.')
        self.assertEqual(shown[-1],result['answer'])
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertEqual(result['webSources'][0]['number'],1)
        self.assertEqual(len(provider.searches),1)
        self.assertFalse(provider.calls)

    def test_every_received_character_survives_streaming_even_in_label_like_text(self):
        shown=[]
        raw='M&A는 인수와 합병이에요. {Q2} [Q5] 【Q6】 이어서 설명해요.'
        class CitationProvider(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append((payload,kwargs))
                for end in range(1,len(raw)+1):kwargs['on_delta'](raw[:end])
                return reply(raw)
        provider=CitationProvider([],semantic('인수와 합병'))
        result=tutor(document(),'M&A를 설명해줘',provider,progress=shown.append)
        self.assertTrue(shown)
        self.assertEqual(shown,[raw[:end] for end in range(1,len(raw)+1)])
        self.assertEqual(shown[-1],result['answer'])
        self.assertEqual(result['answer'],raw)
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertEqual(len(provider.calls),1)

    def test_web_and_mixed_requests_stream_only_the_final_answer_in_both_modes(self):
        from pdf_ai import Provider as NetworkProvider
        for mode in ('quick','deep'):
            for scope in ('external','mixed'):
                shown=[]
                class RoutedProvider(NetworkProvider):
                    model='test-only'
                    def __init__(self):
                        self.web_callback=None
                    def plan_tutor(self,payload):
                        return {**semantic('반복문',web='explicit'),'scope':scope}
                    def web_search(self,question,topic_hint='',on_delta=None):
                        self.web_callback=on_delta
                        if on_delta:on_delta('외부 검색으로 확인한 답변이에요.')
                        return {'answer':'외부 검색으로 확인한 답변이에요.',
                            'webSources':[{'number':1,'title':'공식 문서','url':'https://example.org/reference'}]}
                    def complete(self,payload,**options):
                        self.assert_callback=callable(options.get('on_delta'))
                        options['on_delta']('원문과 외부 자료를 함께 설명해요.')
                        return reply('원문과 외부 자료를 함께 설명해요.')
                provider=RoutedProvider()
                result=tutor(document(),'1페이지 원리와 공식 외부 자료를 검색해서 설명해줘.',
                    provider,mode=mode,progress=shown.append)
                if scope=='mixed':
                    self.assertIsNone(provider.web_callback)
                    self.assertTrue(provider.assert_callback)
                    self.assertNotIn('외부 검색으로 확인한 답변이에요.',shown)
                else:self.assertTrue(callable(provider.web_callback))
                self.assertEqual(shown[-1],result['answer'])

    def test_detailed_fields_stream_before_completion_without_json_or_metadata(self):
        from pdf_tutor_delivery import assemble_teaching
        value=reply('', teaching={'lead':'조건은 `!eof()`예요. 😀',
            'case':{'setup':'입력이 3 5라고 해요.', 'development':'먼저 읽고\n마지막 식을 평가해요.'}},
            followUpQuestion='노출하면 안 되는 후속 질문')
        raw=json.dumps(value,ensure_ascii=True)
        shown=[]
        def lines():
            for char in raw:
                yield 'data: '+json.dumps({'choices':[{'index':0,'delta':{'content':char}}]})
            self.assertTrue(any('조건은' in text for text in shown))
            yield 'data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})
            yield 'data: [DONE]'
        with patch('pdf_ai.time.monotonic',side_effect=itertools.count(0,.05)):
            collect_chat_stream(lines(),shown.append)
        self.assertEqual(shown[-1],assemble_teaching(value)['answer'])
        self.assertNotIn('followUpQuestion',''.join(shown))
        self.assertNotIn('노출하면 안 되는',''.join(shown))
        for end in range(len(raw)+1):
            partial=partial_json_answer(raw[:end])
            self.assertTrue(assemble_teaching(value)['answer'].startswith(partial))

    def test_detailed_pdf_and_general_answers_publish_before_provider_returns(self):
        from pdf_tutor_delivery import assemble_teaching
        for mode in ('quick','deep'):
            for scope in ('pdf','general','mixed'):
                shown=[]
                class LiveProvider(Provider):
                    def complete(self,payload,**options):
                        detailed=payload['learningTask']['responseContract']=='worked_example'
                        value=(reply('',teaching={'lead':'조건을 설명해요.',
                            'case':{'setup':'입력이 3 5예요.','development':'마지막 식으로 판단해요.'}})
                            if detailed else reply('조건을 설명해요. 마지막 식으로 판단해요.'))
                        options['on_delta']('조건을 설명해요.')
                        self.observed=list(shown)
                        return value
                provider=LiveProvider([], {**semantic('반복 조건'),'scope':scope})
                result=tutor(document(),'5페이지 반복 조건을 설명해줘.',provider,mode=mode,progress=shown.append)
                self.assertEqual(provider.observed,['조건을 설명해요.'])
                self.assertEqual(shown[-1],result['answer'])

    def test_explicit_affirmation_survives_stream_and_final_answer(self):
        shown = []
        class AffirmingProvider(Provider):
            def complete(self, payload, **kwargs):
                for text in ('맞아요.', '맞아요. 정답 확률이 낮을수록 손실이 커져요.'):
                    kwargs['on_delta'](text)
                return reply('맞아요. 정답 확률이 낮을수록 손실이 커져요.',
                             claimVerdict='confirmed')
        result = tutor(document(), '정답 확률이 낮으면 손실이 커지는 게 맞지?',
                       AffirmingProvider([], semantic('손실 확률')), progress=shown.append)
        self.assertEqual(shown[0], '맞아요.')
        self.assertEqual(result['answer'], shown[-1])
        self.assertEqual(result['memory']['turns'][-1]['answer'], shown[-1])

    def test_model_deltas_arrive_before_complete_returns(self):
        shown = []
        class StreamingProvider(Provider):
            def complete(self, payload, **kwargs):
                callback = kwargs['on_delta']
                callback('운동량은')
                self_before = list(shown)
                callback('운동량은 보존돼요.')
                self.observed_before_return = self_before
                return reply('운동량은 보존돼요.')
        provider = StreamingProvider([], semantic('운동량 보존'))
        result = tutor(document(), '운동량 보존을 설명해줘', provider, progress=shown.append)
        self.assertEqual(provider.observed_before_return, ['운동량은'])
        self.assertEqual(shown, ['운동량은', '운동량은 보존돼요.'])
        self.assertEqual(result['memory']['turns'][-1]['answer'], shown[-1])

    def test_qualification_does_not_reset_or_regenerate_streamed_answer(self):
        answer='맞아요. 운동량은 보존돼요. 다만 외력이 없는 계에 대한 설명이지, 모든 계에 대한 설명은 아니에요.'
        provider = Provider([reply(answer,claimVerdict='confirmed')], semantic('운동량'))
        shown = []
        result = tutor(document(), '외력이 없는 계에서 운동량이 보존되는 거지?', provider, progress=shown.append)
        self.assertNotIn('', shown)
        self.assertEqual(shown[-1], answer)
        self.assertEqual(result['memory']['turns'][-1]['answer'], answer)
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(all(callable(options['on_delta']) for _, options in provider.calls))

    def test_confirmation_opening_is_not_removed_from_partial_or_final_text(self):
        shown = []
        received=('네,','네, 초대 정부는 이승만 정부예요.')
        class CitationProvider(Provider):
            def complete(self, payload, **kwargs):
                for text in received:
                    kwargs['on_delta'](text)
                return reply(received[-1],claimVerdict='confirmed')
        result=tutor(document(), '초대정부가 이승만이지?', CitationProvider([], semantic('초대 정부')), progress=shown.append)
        self.assertEqual(shown,list(received))
        self.assertEqual(result['answer'],received[-1])

    def test_web_sse_streams_text_before_terminal_object_with_usage_and_sources(self):
        shown = []
        terminal = {'status': 'completed', 'usage': {'input_tokens': 12, 'output_tokens': 8},
                    'output': [{'type': 'web_search_call', 'status': 'completed',
                                'action': {'type': 'search', 'sources': [{'url': 'https://example.org'}]}}]}
        def lines():
            yield 'event: response.output_text.delta\n'
            for text in ('확인한 ', '내용이에요.'):
                yield 'data: ' + json.dumps({'type': 'response.output_text.delta', 'delta': text}) + '\n'
            self.assertTrue(shown)  # Text has arrived before response.completed.
            yield 'data: ' + json.dumps({'type': 'response.completed', 'response': terminal}) + '\n'
        result = collect_web_stream(lines(), shown.append)
        self.assertEqual(result, terminal)
        self.assertEqual(shown[-1], '확인한 내용이에요.')

    def test_split_emoji_escape_waits_for_complete_unicode_character(self):
        partial = '{"answer":"좋아요 \\ud83d'
        self.assertEqual(partial_json_answer(partial), '좋아요 ')
        self.assertEqual(partial_json_answer(partial+'\\ude00"}'), '좋아요 😀')

    def test_web_truncation_is_not_a_completed_answer(self):
        with self.assertRaises(AiResponseError):
            collect_web_stream(['data: {"type":"response.output_text.delta","delta":"일부"}\n'], lambda _: None)


if __name__ == '__main__':
    unittest.main()
