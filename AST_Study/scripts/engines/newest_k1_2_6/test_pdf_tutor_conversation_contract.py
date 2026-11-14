"""Offline end-to-end tutor contracts: semantic turns, both modes and real SSE decoding."""
import copy
import itertools
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
import unittest
from unittest.mock import patch

from pdf_ai import (tutor, tutor_memory, collect_chat_stream, partial_json_answer,
                    safe_social_answer, Provider as ApiProvider)
from pdf_tutor_delivery import (assemble_teaching, conversational_response, worked_format)
from test_pdf_tutor_final_answer import Provider
from test_pdf_tutor_intent import document, semantic


def response(answer='', **changes):
    value=dict(claimVerdict='none',responseKind='general',notFound=False,
               requiresPdfEvidence=False,needsClarification=False,needsExternalSearch=False,
               evidence=[],visualPages=[],answer=answer,webSearchTopic='',followUpQuestion='')
    value.update(changes)
    return value


def sse(value, callback, contract):
    raw=json.dumps(value,ensure_ascii=True)
    def lines():
        for char in raw:
            yield 'data: '+json.dumps({'choices':[{'index':0,'delta':{'content':char}}]})
        yield 'data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})
        yield 'data: [DONE]'
    with patch('pdf_ai.time.monotonic',side_effect=itertools.count(0,.05)):
        result=collect_chat_stream(lines(),callback,response_contract=contract)
    return json.loads(result['choices'][0]['message']['content'])


class StreamingProvider(Provider):
    def complete(self,payload,**options):
        self.calls.append((copy.deepcopy(payload),options))
        value=copy.deepcopy(self.values.pop(0))
        contract=payload['learningTask']['responseContract']
        return sse(value,options.get('on_delta'),contract)


class ConversationContractTests(unittest.TestCase):
    def test_both_modes_and_three_wire_shapes_preserve_conversation_and_focus(self):
        cases=[
            ('오늘은 좀 지치네','잠시 쉬어도 괜찮아요. 돌아오면 이어서 해요.'),
            ('앞으로 답을 조금 짧게 해줄래','앞으로는 핵심 위주로 짧게 답할게요.'),
            ('우리 다음 시간에 이어서 하자','좋아요. 다음 시간에 이어서 해요.'),
            ('넌 어떤 도움을 줄 수 있어?','개념 설명이나 문제 풀이를 도와드릴 수 있어요.'),
            ('나 커피 마시고 왔어','잘 다녀왔어요. 5분 더 쉬었다 시작해도 좋아요.'),
            ('PDF 얘기는 잠깐 멈추자','PDF 설명은 잠깐 멈출게요.\n편하게 이야기해요.'),
            ('ㅇㅋㅇㅋ완전히 이해했어 고맙다잉','이해됐다니 기뻐요. 😊'),
            ('오늘 공부하기가 너무 힘들어','한 번에 끝내려 하지 않아도 괜찮아요.\n'+
                '필요하면 쉬는 시간을 갖고 마음이 편해졌을 때 돌아와도 좋아요. '*7),
        ]
        doc=document()
        memory=tutor_memory(doc,{'documentId':doc['documentId'],
            'topicQuestion':'포인터와 참조의 차이',
            'focus':{'subject':'포인터와 참조','page':1,'viewerPage':1},
            'sourceTask':{'action':'explain','page':1,'item':3},
            'turns':[{'question':'포인터와 참조를 설명해줘.','answer':'이전 학습 답변'}]})
        for mode,(question,answer),shape in itertools.product(('quick','deep'),cases,
                                                              ('direct','lead','legacy_case')):
            with self.subTest(mode=mode,question=question,shape=shape):
                value=response(answer if shape=='direct' else '',responseKind='social')
                if shape!='direct':
                    value['teaching']={'lead':answer,'case':{'setup':'','development':''}}
                    if shape=='legacy_case':
                        value['teaching']['case']={'setup':'생성된 추가 안내',
                                                   'development':'생성된 후속 설명'}
                p=StreamingProvider([value],semantic('잘못 추정된 이전 학습 주제',followup=True))
                shown=[]
                result=tutor(doc,question,p,mode=mode,memory=memory,progress=shown.append)
                expected=answer+('\n\n생성된 추가 안내\n\n생성된 후속 설명' if shape=='legacy_case' else '')
                self.assertEqual(result['kind'],'social')
                self.assertEqual(result['answer'],expected)
                self.assertEqual(result['memory']['topicQuestion'],memory['topicQuestion'])
                self.assertEqual(result['memory']['focus'],memory['focus'])
                self.assertEqual(result['memory']['sourceTask'],memory['sourceTask'])
                self.assertEqual(result['memory']['turns'][-1]['answer'],expected)
                self.assertEqual(len(p.calls),1)
                self.assertFalse(p.searches)
                self.assertEqual(shown[-1],expected)
                self.assertTrue(all(expected.startswith(part) for part in shown))

    def test_direct_answer_wins_over_incidental_teaching_in_either_mode(self):
        for mode in ('quick','deep'):
            value=response('원하는 말투로 답할게요.',teaching={'lead':'불필요한 보조 내용','case':{}})
            # This confirmation task selects the direct contract even in deep mode.
            p=StreamingProvider([value],semantic('확인'))
            shown=[]
            result=tutor(document(),'이렇게 하면 맞지?',p,mode=mode,progress=shown.append)
            self.assertEqual(p.calls[0][0]['learningTask']['responseContract'],'direct')
            self.assertEqual(result['answer'],value['answer'])
            self.assertEqual(shown[-1],value['answer'])
            self.assertTrue(all(value['answer'].startswith(part) for part in shown))

    def test_direct_empty_answer_preserves_all_received_prose(self):
        value=response('',teaching={'lead':'직접 답변이에요.',
            'case':{'setup':'버릴 사례','development':'버릴 전개'}})
        shown=[]
        sse(value,shown.append,'direct')
        final=assemble_teaching(value,response_contract='direct')['answer']
        self.assertEqual(final,'직접 답변이에요.\n\n버릴 사례\n\n버릴 전개')
        self.assertEqual(shown[-1],final)
        self.assertTrue(all(final.startswith(part) for part in shown))

    def test_reordered_direct_json_never_exposes_the_discarded_lead(self):
        value={'teaching':{'lead':'잘못된 보조 내용','case':{}},'answer':'실제 답변이에요.'}
        raw=json.dumps(value,ensure_ascii=True)
        for end in range(len(raw)+1):
            self.assertTrue(value['answer'].startswith(partial_json_answer(raw[:end],response_contract='direct')))
        self.assertEqual(partial_json_answer(raw,response_contract='direct'),value['answer'])

    def test_reordered_social_and_clarification_preserve_received_sections(self):
        for fields in ({'responseKind':'social'},{'needsClarification':True},{'notFound':True}):
            value={'teaching':{'lead':'안내 답변이에요.',
                'case':{'setup':'버릴 사례','development':'버릴 전개'}},**response('',**fields)}
            raw=json.dumps(value,ensure_ascii=True)
            final=assemble_teaching(value,response_contract='worked_example')['answer']
            for end in range(len(raw)+1):
                self.assertTrue(final.startswith(partial_json_answer(raw[:end],response_contract='worked_example')))
            self.assertEqual(partial_json_answer(raw,response_contract='worked_example'),final)

    def test_clarification_and_unavailable_information_work_in_both_modes(self):
        for mode,flag in itertools.product(('quick','deep'),('needsClarification','notFound')):
            answer='비교할 대상이 무엇인지 알려 주세요.'
            value=response('',**{flag:True},teaching={'lead':answer,'case':{}})
            p=StreamingProvider([value],semantic('비교 대상'))
            result=tutor(document(),'그 두 대상이 어떻게 달라?',p,mode=mode)
            self.assertEqual(result['answer'],answer)
            self.assertEqual(len(p.calls),1)

    def test_missing_optional_case_fields_preserve_existing_explanation(self):
        for case in ({},{'setup':'초기 조건','development':''},
                     {'setup':'','development':'결과'},None):
            with self.subTest(case=case):
                final=assemble_teaching(response('',teaching={'lead':'설명','case':case}),
                                        response_contract='worked_example')['answer']
                self.assertTrue(final.startswith('설명'))
                if isinstance(case,dict):
                    for text in case.values():
                        if text:self.assertIn(text,final)
        value=response('',teaching={'lead':'운동량은 보존돼요.',
            'case':{'setup':'마찰 없는 레일의 두 운반차예요.','development':'내부 힘으로 변한 운동량의 합은 0이에요.'}})
        shown=[]
        p=StreamingProvider([value],semantic('운동량 보존'))
        result=tutor(document(),'운동량 보존을 자세히 설명해줘.',p,mode='deep',progress=shown.append)
        self.assertEqual(result['answer'],assemble_teaching(value)['answer'])
        self.assertEqual(shown[-1],result['answer'])
        self.assertTrue(all(result['answer'].startswith(part) for part in shown))

    def test_social_metadata_cannot_hide_factual_claims_or_malformed_types(self):
        invalid=[{'claimVerdict':'confirmed'},{'requiresPdfEvidence':True},
                 {'evidence':[{'sourceId':'x'}]},{'visualPages':[2]},
                 {'needsExternalSearch':True},{'notFound':0},{'requiresPdfEvidence':'false'},
                 {'evidence':''},{'visualPages':{}},{'blocked':None}]
        for fields in invalid:
            with self.subTest(fields=fields):
                self.assertFalse(conversational_response(response('답변',responseKind='social',**fields)))
        self.assertFalse(safe_social_answer(response('PDF 12페이지에 정답이 있어요.',responseKind='social')))
        for answer in ('5분만 쉬어도 괜찮아요.','PDF 설명이 도움 됐다니 기뻐요.',
                       '편하게 말해요.\n대화 이어가요.'):
            self.assertTrue(safe_social_answer(response(answer,responseKind='social')))

    def test_empty_or_malformed_direct_answers_are_not_reported_as_success(self):
        for value in (response(''),response([],teaching={'lead':[]}),
                      response('',teaching={'lead':[]}),response('',teaching={})):
            with self.subTest(value=value),self.assertRaises(ValueError):
                assemble_teaching(value,response_contract='direct')

    def test_social_words_do_not_disable_an_explicit_learning_request(self):
        for mode,question in itertools.product(('quick','deep'),
                ('고마워. 그런데 운동량 보존은 왜 성립하는지 설명해줘.',
                 '조금 피곤하지만 포인터와 참조의 차이를 설명해줘.')):
            value=response('핵심은 내부 힘의 합이에요.') if mode=='quick' else response('',
                teaching={'lead':'핵심은 내부 힘의 합이에요.',
                          'case':{'setup':'외력이 없는 두 물체를 생각해요.',
                                  'development':'두 물체의 운동량 변화가 서로 상쇄돼요.'}})
            p=StreamingProvider([value],semantic('운동량 보존'))
            result=tutor(document(),question,p,mode=mode)
            self.assertEqual(result['kind'],'ai_generated')
            self.assertEqual(p.calls[0][0]['learningTask']['responseContract'],
                             'direct')

    def test_real_provider_passes_the_contract_to_http_and_injected_streams(self):
        for contract,injected,answer in itertools.product(('direct','worked_example'),
                                                           (True,False),('','실제 답변이에요.')):
            value={'teaching':{'lead':'대화 답변이에요.',
                              'case':{'setup':'불필요한 사례','development':'불필요한 전개'}},
                   **response(answer,responseKind='social')}
            if contract=='worked_example':value['answer']=''
            expected=assemble_teaching(value,response_contract=contract)['answer']
            raw=json.dumps(value,ensure_ascii=True)
            lines=['data: '+json.dumps({'choices':[{'index':0,'delta':{'content':c}}]}) for c in raw]
            lines += ['data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}),
                      'data: [DONE]']
            wire={'choices':[{'message':{'content':raw},'finish_reason':'stop'}],
                  'usage':{'prompt_tokens':100,'completion_tokens':100}}
            with tempfile.TemporaryDirectory() as directory, patch('pdf_ai.api_key',return_value='test-only'):
                folder=Path(directory);seen=[]
                p=ApiProvider(folder,True,.05,transport=(lambda body:wire) if injected else None)
                p.rate_directory=folder/'rates'
                payload={'taskType':'tutor','question':'대화 관리 요청',
                         'learningTask':{'explanationMode':'quick' if contract=='direct' else 'deep',
                                         'responseContract':contract}}
                with patch('urllib.request.urlopen',return_value=nullcontext(lines)), \
                     patch('pdf_ai.time.monotonic',side_effect=itertools.count(0,.05)):
                    returned=p.complete(payload,max_output=512,on_delta=seen.append,
                                        response_format=worked_format() if contract=='worked_example' else None)
                self.assertEqual(assemble_teaching(returned,response_contract=contract)['answer'],expected)
                self.assertEqual(seen[-1],expected)
                self.assertTrue(all(expected.startswith(part) for part in seen))

    def test_direct_verdicts_can_be_document_grounded_in_both_modes(self):
        for mode,verdict in itertools.product(('quick','deep'),('confirmed','rejected','mixed','none')):
            answer={'confirmed':'맞아요. 제시한 답은 정답이에요.',
                    'rejected':'그 답은 맞지 않아요. 조건을 하나 놓쳤어요.',
                    'mixed':'첫 부분은 맞고, 마지막 조건은 달라요.',
                    'none':'요청한 사실은 다음과 같아요.'}[verdict]
            value=response('',responseForm='direct',responseKind='document',claimVerdict=verdict,
                           requiresPdfEvidence=True,
                           teaching={'lead':answer,'case':{'setup':'','development':''}})
            p=StreamingProvider([value],semantic('이전 답안 정오 판정',followup=True))
            shown=[]
            result=tutor(document(),'그럼 나 맞춘거야?',p,mode=mode,progress=shown.append)
            self.assertEqual(result['answer'],answer)
            self.assertEqual(result['kind'],'ai_generated')
            self.assertTrue(result['requiresPdfEvidence'])
            self.assertEqual(shown[-1],answer)
            self.assertTrue(all(answer.startswith(part) for part in shown))

    def test_verdict_and_explanation_keep_generated_body_without_regeneration(self):
        value=response('',responseForm='worked_example',claimVerdict='confirmed',
                       teaching={'lead':'맞아요. 그 이유를 설명해요.',
                                 'case':{'setup':'','development':''}})
        p=StreamingProvider([value],semantic('운동량 보존'))
        result=tutor(document(),'내 설명이 왜 맞는지 구체적인 사례로 설명해줘.',p,mode='deep')
        self.assertEqual(result['answer'],'맞아요. 그 이유를 설명해요.')
        self.assertEqual(len(p.calls),1)

    def test_malformed_optional_metadata_does_not_erase_body(self):
        for form in (None,[],{},'unexpected'):
            with self.subTest(form=form):
                self.assertEqual(assemble_teaching(response('본문',responseForm=form),
                                                 response_contract='direct')['answer'],'본문')
        self.assertEqual(assemble_teaching(response('이전 형식 본문'),response_contract='direct')['answer'],
                         '이전 형식 본문')

    def test_response_form_controls_stream_and_final_in_any_field_order(self):
        for order in ('metadata_first','teaching_first'):
            value=response('',responseForm='direct',responseKind='document',claimVerdict='confirmed',
                           requiresPdfEvidence=True,evidence=[{'sourceId':'s','quoteId':'q'}],
                           teaching={'lead':'맞아요. 그 답은 정답이에요.',
                                     'case':{'setup':'버릴 사례','development':'버릴 전개'}})
            if order=='teaching_first':value={'teaching':value['teaching'],**value}
            raw=json.dumps(value,ensure_ascii=True)
            final=assemble_teaching(value,response_contract='worked_example')['answer']
            for end in range(len(raw)+1):
                self.assertTrue(final.startswith(partial_json_answer(raw[:end],response_contract='worked_example')))
            self.assertEqual(partial_json_answer(raw,response_contract='worked_example'),final)

    def test_available_prose_is_delivered_despite_missing_or_malformed_optional_sections(self):
        shapes=[
            (response('주 답변',teaching={'lead':'보조 답변','case':{}}),'주 답변'),
            (response('',teaching={'lead':'생성된 설명'}),'생성된 설명'),
            (response('',teaching={'lead':'생성된 설명','case':None}),'생성된 설명'),
            (response('',teaching={'lead':'생성된 설명','case':[]}),'생성된 설명'),
            (response('',teaching={'case':{'setup':'조건','development':'결과'}}),'조건\n\n결과'),
            (response('',teaching={'case':{'development':'생성된 전개'}}),'생성된 전개'),
            (response([],teaching={'lead':'남아 있는 본문'}),'남아 있는 본문'),
            (response('',responseForm=[],teaching={'lead':'유효한 본문'}),'유효한 본문'),
            (response('',teaching={'lead':'같은 문장.','case':{'setup':'같은 문장.',
                       'development':'그 뒤의 결과'}}),'같은 문장.\n\n같은 문장.\n\n그 뒤의 결과'),
        ]
        for mode,(value,expected) in itertools.product(('quick','deep'),shapes):
            with self.subTest(mode=mode,value=value):
                p=StreamingProvider([value],semantic('개념'))
                shown=[]
                result=tutor(document(),'이 개념을 설명해줘.',p,mode=mode,progress=shown.append)
                self.assertEqual(result['answer'],expected)
                self.assertEqual(shown[-1],expected)
                self.assertTrue(all(expected.startswith(part) for part in shown))
                self.assertEqual(result['memory']['turns'][-1]['answer'],expected)
                self.assertEqual(len(p.calls),1)

    def test_worked_schema_decides_response_purpose_before_streaming_prose(self):
        keys=list(worked_format()['json_schema']['schema']['properties'])
        for key in ('responseForm','responseKind','requiresPdfEvidence','needsClarification','notFound','evidence','visualPages'):
            self.assertLess(keys.index(key),keys.index('teaching'))


if __name__=='__main__':unittest.main()
