"""A streamed answer never becomes a paid review/replacement. No remote calls."""
import copy
from pathlib import Path
import tempfile
import unittest

import pdf_ai as ai
from test_pdf_tutor_final_answer import Provider,reply
from test_pdf_tutor_intent import semantic


class SingleAnswerTests(unittest.TestCase):
    def document(self):
        return {'documentId':'doc','pages':[{}],'chunks':[]}

    def test_qualified_confirmation_is_one_stream_in_both_answer_modes(self):
        cases=[
            ('정부가 벽화를 의뢰한 거지?',
             '맞아요. 정부가 전시용 벽화를 의뢰했어요. 다만 소재까지 지정한 것은 아니고, 작가가 주제를 정했어요.'),
            ('외력이 없으면 운동량이 보존되는 거지?',
             '맞아요. 외력이 없는 계의 운동량은 보존돼요. 다만 모든 계가 외력이 없는 것은 아니에요.'),
            ('이 조건에서는 값이 같은 거지?',
             '맞아요. 이 조건에서는 값이 같아요. 하지만 다른 조건에서도 같다는 뜻은 아니에요.')]
        for mode in ('quick','deep'):
            for question,answer in cases:
                with self.subTest(mode=mode,question=question):
                    p=Provider([reply(answer,claimVerdict='confirmed')],semantic('현재 질문'))
                    shown=[];stages=[]
                    result=ai.tutor(self.document(),question,p,mode=mode,
                        progress=shown.append,stage=stages.append)
                    self.assertEqual(len(p.calls),1)
                    self.assertNotIn('',shown)
                    self.assertTrue(all(answer.startswith(t)for t in shown))
                    self.assertEqual(shown[-1],answer)
                    self.assertEqual(result['memory']['turns'][-1]['answer'],answer)
                    self.assertEqual(stages.count('answer_wait'),1)
                    self.assertFalse(p.searches)

    def test_former_risk_categories_do_not_create_another_answer_call(self):
        cases=[
            ('모든 조건에서 같은 거야?','아니요. 주어진 조건에서만 같아요.','rejected'),
            ('이후에 적용되는 거야?','맞아요. 이전 단계가 끝난 이후에 적용돼요.','confirmed'),
            ('계수를 바꾼 넓이를 계산해줘','3x-2x²=x(3-2x)이므로 경계는 0과 3/2이고 넓이는 9/8이에요.','none'),
            ('새 대상으로 바꾸면 이전 값도 다시 돌아가?','이전 값 10은 유지되고 대상만 달라져요.','none'),
            ('정의가 맞지?','일부만 맞아요. 조건에 따라 달라지는 부분을 구분해야 해요.','mixed')]
        for question,answer,verdict in cases:
            with self.subTest(question=question):
                p=Provider([reply(answer,claimVerdict=verdict)],semantic('현재 질문'))
                shown=[];result=ai.tutor(self.document(),question,p,progress=shown.append)
                self.assertEqual(len(p.calls),1)
                self.assertEqual(result['answer'],answer)
                self.assertNotIn('',shown)

    def test_late_empty_delta_cannot_erase_a_visible_answer(self):
        class EmptyDeltaProvider(Provider):
            def complete(self,payload,**options):
                self.calls.append((copy.deepcopy(payload),options))
                for text in ('설명','', '설명이 이어져요.'):
                    options['on_delta'](text)
                return reply('설명이 이어져요.')
        p=EmptyDeltaProvider([],semantic('개념'));shown=[]
        result=ai.tutor(self.document(),'개념을 설명해줘',p,progress=shown.append)
        self.assertEqual(shown,['설명','설명이 이어져요.'])
        self.assertEqual(len(p.calls),1);self.assertEqual(result['answer'],shown[-1])

    def test_failed_answer_is_not_resent_as_a_review_or_a_study_repair(self):
        p=Provider([ai.AiResponseError('Connection interrupted')],semantic('개념'))
        with self.assertRaises(ai.AiResponseError):ai.tutor(self.document(),'개념을 설명해줘',p)
        self.assertEqual(len(p.calls),1)

    def test_old_review_helpers_and_prompt_are_removed(self):
        for name in ('tutor_review_reason','compact_tutor_review','TUTOR_REVIEW_SYSTEM'):
            self.assertFalse(hasattr(ai,name),name)


class StaleReviewGuardTests(unittest.TestCase):
    def test_legacy_review_cannot_reserve_or_send_in_either_api_mode(self):
        for mode in ('chat','responses'):
            for cache_only in (False,True):
                with self.subTest(mode=mode,cache_only=cache_only),tempfile.TemporaryDirectory()as folder:
                    calls=[]
                    p=ai.Provider(Path(folder),True,.1,transport=lambda body:calls.append(body),study_input_api=mode)
                    with self.assertRaises(ai.AiResponseError):
                        p.complete({'taskType':'tutor','operation':'answer_review','question':'question'},
                            cache_only=cache_only)
                    self.assertEqual(calls,[])
                    self.assertEqual(p.ledger['requests'],[])
                    self.assertEqual(p.spent,0)


if __name__=='__main__':unittest.main()
