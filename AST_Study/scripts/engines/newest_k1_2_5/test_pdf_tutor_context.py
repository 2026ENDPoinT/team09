"""Offline regressions for numbered exercise continuation and bounded history."""
import json
import time
import unittest
from unittest.mock import patch

from pdf_ai import tutor, tutor_memory, selected_conversation, TUTOR_CONTEXT_BYTES
from pdf_tutor_context import numbered_request
from pdf_tutor_page_image import image_request
from pdf_tutor_intent import planning_context, plan_question
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import semantic


def doc(text='int main() { int n=12; cout << n; }'):
    return {'documentId':'doc','pages':[{'nativeText':text, 'words':[
        {'text':'4.','bbox':[.1,.3,.13,.32]}, {'text':'8.','bbox':[.55,.3,.58,.32]}]}],
        'chunks':[{'id':'s','documentId':'doc','page':1,'source':'native','field':'nativeText',
                   'start':0,'end':len(text),'text':text}]}


def memory():
    return {'documentId':'doc','topicQuestion':'前の型の概念',
            'focus':{'subject':'前の型の概念','page':1,'viewerPage':1},
            'sourceTask':{'page':1,'item':6,'action':'solve'},
            'turns':[{'question':'1페이지 6번 해설해줘','answer':'앞 문항 해설'},
                     {'question':'그 타입은 밖에서도 써?','answer':'선언된 범위를 확인해요.'}]}


class TutorContextTests(unittest.TestCase):
    def test_new_item_replaces_stale_semantic_topic_and_streams_one_answer(self):
        for question in ['1페이지 8번','1페이지 8번 문제 풀이해줘','8번도 ㄱㄱ']:
            with self.subTest(question=question):
                provider=Provider([reply('현재 문항의 해설이에요.')],
                                  {**semantic('앞 문항 타입',page=1,followup=True),'scope':'pdf'})
                seen=[]
                with patch('pdf_tutor_page_image.prepare',return_value=(
                        [{'data':'test'}],[{'page':1,'reason':'numbered_code_layout'}])) as prepare:
                    result=tutor(doc(),question,provider,memory=memory(),current_page=1,
                                 web_fallback=False,progress=seen.append)
                payload,options=provider.calls[0]
                self.assertIn('8번',payload['questionPlan']['subject'])
                self.assertNotIn('타입',payload['topicHint'])
                self.assertEqual(payload['learningTask']['kind'],'worked_solution')
                self.assertEqual(payload['learningTask']['responseContract'],'direct')
                self.assertEqual(options['image'],[{'data':'test'}])
                self.assertTrue(prepare.call_args.kwargs['page_bound'])
                self.assertIsNotNone(image_request(doc(),prepare.call_args.args[2],1,page_bound=True))
                self.assertEqual(result['memory']['sourceTask']['item'],8)
                self.assertEqual(len(provider.calls),1)
                self.assertEqual(seen[-1],result['answer'])
                self.assertFalse(provider.searches)

    def test_plain_text_item_avoids_image_and_concept_opt_out_is_preserved(self):
        text='8. 다음 설명이 참인지 판단하세요. 참조 변수는 선언할 때 초기화해야 한다.'
        document=doc(text)
        document['pages'][0]['words']=[]
        resolved=numbered_request('1페이지 8번',memory(),1,1,1)
        self.assertIsNone(image_request(document,resolved['request'],1,page_bound=True))
        for question in ['1페이지 8번 풀지 말고 개념만', '1페이지에 새 문제 만들어줘',
                         '1페이지 8번과 9번', '8번은 왜 const야?', '1페이지 8번 삭제해줘']:
            self.assertIsNone(numbered_request(question,memory(),1,1,1))
        self.assertIsNone(image_request(doc(),'1페이지 원리만, 이미지는 보지 말고 설명해줘',1,page_bound=True))

    def test_item_number_is_never_used_as_page_and_document_memory_is_isolated(self):
        r=numbered_request('27번',memory(),None,1,1)
        self.assertEqual((r['page'],r['item'],r['candidate']),(1,27,True))
        self.assertIsNone(numbered_request('99페이지 8번',memory(),0,1,1))
        self.assertNotIn('sourceTask',tutor_memory({**doc(),'documentId':'other'},memory()))

    def test_planner_receives_six_bounded_exchanges_and_user_task_hint(self):
        state=memory();state['turns']=[{'question':f'{i}번 해설','answer':'상세한 설명'} for i in range(10)]
        value=planning_context('1페이지 8번',state,plan_question('1페이지 8번',state,1,1),1)
        self.assertEqual(len(value['recent']),6)
        self.assertEqual(value['sourceTask']['item'],6)
        self.assertNotIn('sources',value)
        huge={**state,'turns':[{'question':'질문'*5000,'answer':'답변'*20000}]*20}
        bounded=planning_context('해설',huge,plan_question('해설',huge,1,None),1)
        self.assertLessEqual(len(json.dumps(bounded['recent'],ensure_ascii=False).encode()),10000)

    def test_longer_history_keeps_twenty_turns_after_pause_and_full_recent_answer(self):
        now=int(time.time()*1000)
        state=tutor_memory(doc(),{'documentId':'doc','turns':[
            {'question':f'{i}번 설명','answer':'x'*8000 if i==24 else '설명',
             'timestampMs':now-1_000_000} for i in range(25)]})
        self.assertEqual(len(state['turns'][-1]['answer']),8000)
        selected=selected_conversation(state,now,[])
        self.assertEqual(len(selected),20)
        self.assertEqual(selected[0]['question'],'5번 설명')
        self.assertLessEqual(len(json.dumps(selected,ensure_ascii=False).encode()),TUTOR_CONTEXT_BYTES)


if __name__=='__main__':unittest.main()
