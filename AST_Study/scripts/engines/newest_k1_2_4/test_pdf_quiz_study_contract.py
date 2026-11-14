import copy
import itertools
import unittest
from unittest.mock import patch
from pdf_quiz_response import assemble_answers
from pdf_quiz_review import shuffle_display_options
from pdf_quiz_profiles import apply_profile_plan

class StudyContractTests(unittest.TestCase):
    def test_all_24_permutations_keep_answer_explanation_and_source_ids(self):
        opts=[{'optionId':f'O0{i}','text':f'보기{i}','explanation':f'해설{i}'} for i in range(1,5)]
        for order in itertools.permutations(opts):
            raw={'questions':[{'type':'mcq','options':list(order),'correctOptionId':'O03'}]}
            before=copy.deepcopy(raw)
            q=assemble_answers(raw)['questions'][0]
            shuffle_display_options([q],'fixed')
            correct=next(o for o in q['options'] if o['id']==q['answer'])
            self.assertEqual((correct['text'],correct['explanation'],correct['optionId']),('보기3','해설3','O03'))
            self.assertEqual(raw,before)
            self.assertEqual(q['rawAnswerContract'],before['questions'][0])
    def test_example_does_not_become_common_and_condition_is_preserved(self):
        raw={'type':'essay','exampleAnswer':'예시 하나','commonRequirements':['공통 판단'],
             'conditionalRequirements':[{'condition':'방법 B를 택한 경우','requirement':'B의 전제'}],'acceptedAliases':['다른 유효 답안']}
        q=assemble_answers({'questions':[raw]})['questions'][0]
        self.assertEqual(q['answer'],'예시 하나')
        self.assertEqual(q['keyPoints'],['공통 판단','조건: 방법 B를 택한 경우 → 요구: B의 전제','허용 대안(필수 아님): 다른 유효 답안'])
        self.assertEqual(q['rawAnswerContract'],raw)
    def test_malformed_identity_stays_failed_not_repaired(self):
        q=assemble_answers({'questions':[{'type':'mcq','options':[],'correctOptionId':'O99'}]})['questions'][0]
        self.assertTrue(q['answerContractError']);self.assertEqual(q['rawAnswerContract']['correctOptionId'],'O99')
    def test_profile_shortage_keeps_target_not_relabels_or_refills(self):
        target={'id':'t1','type':'essay','profile':'advanced','additionalJudgment':'추가 판단','profileEvidenceSourceIds':['absent']}
        plan={'allocations':[{'unitId':'u','targets':[target]}],'unallocated':0}
        out=apply_profile_plan(plan,{'sources':[]},{'totalCount':2,'theme':'understanding'})
        self.assertEqual(out['heldTargets'][0]['profile'],'advanced')
        self.assertFalse(out['allocations']);self.assertIsNone(out['profileAllocation']['suitableCounts']['advanced'])
        self.assertEqual(plan['allocations'][0]['targets'],[target])

if __name__=='__main__':unittest.main()
