"""Only fully named glossary requests skip semantic planning; no network calls."""
import copy,json,tempfile,unittest
from pathlib import Path
from pdf_tutor_intent import fast_definition_plan
from pdf_ai import Provider,tutor
from test_pdf_tutor_intent import semantic
from test_pdf_tutor_final_answer import reply

def payload(q):return {'taskType':'tutor','operation':'query_plan','mentorContext':True,'question':q,'recent':[], 'focus':{}}

class FastPlanTests(unittest.TestCase):
    def test_named_glossary_targets_keep_literal_terms(self):
        for q,term in [('형무소가 뭐야?','형무소'),('군정 뜻 알려줘.','군정'),('운동량은 뭐야?','운동량'),
                       ('재귀 뜻을 알려줘','재귀'),('도강파랑 잔류파가 뭔데?','도강파랑 잔류파'),
                       ('평균의 의미가 뭐예요?','평균'),('API의 정의를 설명해줘요','API'),
                       ('그리스 뜻이 뭐야?','그리스'),('민주주의 뜻이 뭐야?','민주주의'),
                       ('고양이 뭐야?','고양이'),('전문가가 뭐야?','전문가')]:
            with self.subTest(q=q):
                value=fast_definition_plan(payload(q));self.assertIsNotNone(value)
                self.assertTrue(value['subject'].startswith(term));self.assertEqual(value['query'],value['subject'])
                self.assertEqual(value['web'],'none');self.assertIsNone(value['page'])

    def test_references_conditions_pages_lookup_and_ambiguous_requests_stay_remote(self):
        for q in ['그 뜻이 뭐야?','이 말의 의미가 뭐야?','그 개념이 뭐야?', '아까 내가 물어본 뜻을 다시 설명해줘.',
                  '다시 설명해줘.','그럼 부호만 바꾸면 돼?','한쪽 질량이 두 배면?',
                  '군대가 통치한다는 뜻이 뭐야?','군사정부는 그러면 내 군대가 통치하는 거야?',
                  'A가 100이면 무슨 뜻이야?','17페이지 의미가 뭐야?','오늘 환율이 뭐야?',
                  '군정 뜻 인터넷에서 검색해줘.','선택한 부분의 뜻이 뭐야?', '이 PDF의 정의가 뭐야?',
                  '왜 그래?','반대로 하면?','무슨 뜻이야?','거기는 뭐야?','전자가 뭐야?',
                  '그 사람의 뜻이 뭐야?','각각 뜻이 뭐야?','그 경우가 뭐야?',
                  '물체가 움직일 때 운동량 뜻이 뭐야?','다른 조건. 군정 뜻이 뭐야?','중력이 없는 공간의 뜻이 뭐야?',
                  '그런 형무소가 뭐야?','내가 뭐야?','내일이 뭐야?','이 글의 뜻이 뭐야?']:
            with self.subTest(q=q):self.assertIsNone(fast_definition_plan(payload(q)))

    def test_strict_mentor_opt_in_and_source_selection_are_preserved(self):
        for field,value in [('mentorContext',False),('mentorContext','true'),('operation','home_assistant_chat'),
                            ('sourceTask',{'page':3,'item':2}),('selectionLocation',{'pages':[3]}),('selectionLocation',{})]:
            with self.subTest(field=field):self.assertIsNone(fast_definition_plan({**payload('군정 뜻이 뭐야?'),field:value}))

    def test_context_and_original_payload_remain_intact(self):
        p={**payload('군정 뜻이 뭐야?'),'recent':[{'question':'이전 질문','answer':'이전 답변'}],
           'focus':{'subject':'군정의 정의','page':9},'userTopicHistory':[{'question':'이전 질문','subject':'군정'}]}
        before=copy.deepcopy(p);self.assertTrue(fast_definition_plan(p)['followup']);self.assertEqual(p,before)
        p['focus']['subject']='무관한 이전 주제';self.assertFalse(fast_definition_plan(p)['followup'])
        p['focus']=None;self.assertFalse(fast_definition_plan(p)['followup'])

    def test_both_modes_keep_answer_effort_and_one_answer_call(self):
        for mode in ('quick','deep'):
            for effort in ('low','medium'):
                with self.subTest(mode=mode,effort=effort),tempfile.TemporaryDirectory() as temp:
                    calls=[]
                    def transport(body):
                        calls.append(body)
                        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(reply('군정은 군 당국이 통치권을 행사하는 방식이에요.',resolvedTopic='군정'))}}],
                                'usage':{'prompt_tokens':50,'completion_tokens':30}}
                    provider=Provider(Path(temp),True,.02,transport=transport)
                    result=tutor({'documentId':'d','pages':[{}],'chunks':[]},'군정 뜻이 뭐야?',provider,
                                 mode=mode,reasoning_effort=effort,web_fallback=False)
                    self.assertTrue(result['answer']);self.assertEqual(len(calls),1)
                    self.assertEqual(calls[0]['reasoning_effort'],effort)
                    self.assertEqual(len(provider.ledger['requests']),1)

if __name__=='__main__':unittest.main()
