"""Contextual fast routing preserves dialogue and falls back without another guess."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from pdf_ai import Provider, tutor
from pdf_tutor_fast_context import fast_followup_plan
from pdf_tutor_intent import MENTOR_PLAN_SYSTEM
from test_pdf_tutor_final_answer import reply


def payload(question='그럼 왜 그런 거야?'):
    return {'taskType':'tutor','operation':'query_plan','mentorContext':True,
        'question':question,'focus':{'subject':'정지한 두 물체의 운동량 보존','page':None},
        'recent':[{'question':'정지한 두 물체가 서로 밀면 운동량이 어떻게 돼?',
                   'answer':'전체 운동량은 0이에요. 질량이 두 배인 쪽의 속력은 절반이고 방향은 반대예요.'}],
        'userTopicHistory':[{'question':'정지한 두 물체가 서로 밀면 운동량이 어떻게 돼?',
                             'subject':'정지한 두 물체의 운동량 보존'}]}


class ContextPlanTests(unittest.TestCase):
    def test_generic_explanation_operations_and_omitted_arguments(self):
        for question in ['다시 설명해줘.','그걸 좀 더 쉽게 설명해줘.','왜 그런 거야?',
                         '그럼 왜 그런 거야?','예를 들어 설명해줘.','그걸 비유로 보여줘.',
                         '좀 더 자세히 알려줘.','한쪽 질량이 두 배면 그쪽 속력은 절반이야?',
                         '그럼 반대로 하면?','그게 꼭 필요한 거야?']:
            with self.subTest(question=question):
                p=payload(question);before=copy.deepcopy(p);plan=fast_followup_plan(p)
                self.assertIsNotNone(plan);self.assertTrue(plan['followup'])
                self.assertEqual(plan['web'],'none');self.assertEqual(p,before)
                self.assertIn('운동량',plan['query']);self.assertIsNone(plan['page'])

    def test_subject_cannot_be_promoted_from_an_incidental_answer(self):
        p=payload('그럼 군사정부는 군대가 다 하는 거야?')
        p['recent'][-1]['answer']+=' 군사정부에서는 군 당국이 통치해요.'
        for question in ['그럼 군사정부는 군대가 다 하는 거야?',
                         '그럼 군사정부가 뭐야?','군사정부 설명해줘.']:
            p['question']=question
            self.assertIsNone(fast_followup_plan(p))

    def test_new_topics_older_references_locations_and_lookup_stay_remote(self):
        for question in ['군사정부는 그러면 내가 점령하면 내 군대가 통치하는 체제야?',
                         '그럼 광합성은 어떻게 돼?','아까 두 배였던 경우로 돌아가면?',
                         '해왕성은 뭐야?','하수도는 뭐야?','하반신이 뭐야?',
                         '그럼 해왕성은?', '???', '123',
                         '내가 물어본 뜻을 다시 설명해줘.','이전 질문 다시 설명해줘.',
                         '17페이지를 설명해줘.','그럼 2번도 풀어줘.',
                         '그 그림은 왜 그래?','그 표에서 두 번째는?',
                         '그럼 현재 가격은?','그러면 인터넷에서 확인해줘.',
                         '실제로도 맞는지 검증해줘.','그럼 출처는?',
                         '그거 말고 새 주제 설명해줘.','그럼 a로 바꿔도 돼?',
                         '아니 질량 말고 힘을 물어본 거야.']:
            with self.subTest(question=question):self.assertIsNone(fast_followup_plan(payload(question)))

    def test_stale_or_missing_or_unanswered_focus_stays_remote(self):
        cases=[]
        p=payload();p['focus']['subject']='스탈린 점령 사회체제';cases.append(p)
        p=payload();p['focus']={};cases.append(p)
        p=payload();p['focus']['page']=8;cases.append(p)
        p=payload();p['recent'][-1]['answer']='';cases.append(p)
        p=payload();p['recent'][-1]['answer']='어느 조건을 말하는지 알려 주세요.';cases.append(p)
        p=payload();p['recent']=[];cases.append(p)
        p=payload();p['recent'][-1]['question']='오늘 날씨를 인터넷에서 검색해줘.';cases.append(p)
        for p in cases:self.assertIsNone(fast_followup_plan(p))

    def test_strict_opt_in_source_keys_and_malformed_inputs(self):
        for key,value in [('mentorContext',False),('mentorContext','true'),
                          ('operation','home_assistant_chat'),('sourceTask',{}),
                          ('selectionLocation',{}),('focus',None),('recent',{}),
                          ('recent',[None]),('recent',[{'question':3,'answer':'yes'}]),
                          ('question',None),('question','x'*161)]:
            with self.subTest(key=key):self.assertIsNone(fast_followup_plan({**payload(),key:value}))

    def test_changed_conditions_stay_in_original_question_not_a_machine_rewrite(self):
        p=payload('한쪽 질량이 두 배면 그쪽 속력은 절반이야?')
        plan=fast_followup_plan(p)
        self.assertNotIn('answerFocus',plan);self.assertFalse(plan['ask'])
        p['question']='한쪽 질량이 세 배면?'
        self.assertIsNotNone(fast_followup_plan(p))
        p['question']='그럼 마찰이 새로 생기면?'
        self.assertIsNone(fast_followup_plan(p))  # A new physical condition needs the existing planner.

    def test_guarded_provider_fallback_uses_the_exact_original_payload_and_policy(self):
        for question in ['그럼 광합성은?','아까 그걸로 돌아가면?']:
            p=payload(question);stub=SimpleNamespace(complete=Mock(return_value={'remote':True}))
            self.assertEqual(Provider.plan_tutor(stub,p),{'remote':True})
            args,kwargs=stub.complete.call_args
            self.assertIs(args[0],p)
            self.assertEqual(kwargs,{'max_output':512,'system_prompt':MENTOR_PLAN_SYSTEM})

    def test_case_sensitive_identifiers_and_oversized_words_are_not_context_aliases(self):
        p=payload('그 상태에서 b[0][0]=7 하면 a도 변해?')
        p['focus']['subject']='a의 얕은 복사'
        p['recent']=[{'question':'a=[[2],[4]]; b=a.copy()를 했어.',
                      'answer':'b는 새 바깥 리스트이고 내부 객체는 a와 공유해요.'}]
        self.assertIsNotNone(fast_followup_plan(p))
        p['question']='그 상태에서 b[0][0]=7 하면 A도 변해?'
        self.assertIsNone(fast_followup_plan(p))
        p['question']='그럼 하'+'이면'*50+'각?'
        self.assertIsNone(fast_followup_plan(p))

    def test_both_modes_efforts_and_full_dialogue_are_preserved_with_one_call(self):
        doc={'documentId':'d','pages':[{}],'chunks':[]}
        p=payload();memory={'documentId':'d','topicQuestion':p['focus']['subject'],
            'focus':p['focus'],'turns':[{**t,'subject':p['focus']['subject']} for t in p['recent']]}
        for mode in ('quick','deep'):
            for effort in ('low','medium'):
                with self.subTest(mode=mode,effort=effort), tempfile.TemporaryDirectory() as temp:
                    bodies=[]
                    def transport(body):
                        bodies.append(copy.deepcopy(body))
                        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reply(
                            '기존 조건을 유지하며 설명해요.',resolvedTopic=p['focus']['subject']))}}],
                            'usage':{'prompt_tokens':50,'completion_tokens':30}}
                    provider=Provider(Path(temp),True,.02,transport=transport)
                    result=tutor(doc,p['question'],provider,memory=memory,mode=mode,
                                 reasoning_effort=effort,web_fallback=False)
                    self.assertTrue(result['answer']);self.assertEqual(len(bodies),1)
                    self.assertEqual(bodies[0]['reasoning_effort'],effort)
                    messages=bodies[0]['messages']
                    self.assertEqual(messages[-1]['content'],p['question'])
                    self.assertEqual(messages[1]['content'],p['recent'][0]['question'])
                    self.assertEqual(json.loads(messages[2]['content'])['answer'],p['recent'][0]['answer'])
                    self.assertEqual(len(provider.ledger['requests']),1)


if __name__=='__main__':unittest.main()
