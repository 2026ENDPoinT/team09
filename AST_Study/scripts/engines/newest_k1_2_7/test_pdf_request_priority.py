"""Equal-envelope scheduling, no source rewriting or additional RPC work."""
import copy
import unittest
from unittest.mock import patch
import pdf_new_concept_ver99_study as study


def block(key,text,box=(.1,.1,.9,.9)):
    return {'id':key,'page':int(key)+1,'kind':'text','text':text,'bbox':list(box),'zone':0}


class RequestPriorityTests(unittest.TestCase):
    def test_visual_work_moves_forward_without_changing_any_pair_or_source(self):
        jobs=[{'blocks':[block(str(i),text,box)]}for i,(text,box)in enumerate([
            ('첫 단위',(.1,.1,.2,.2)),('둘째 단위',(.1,.1,.2,.2)),
            ('짧은 글',(.1,.1,.2,.2)),('',(0,0,1,1)),('보통 글',(.1,.1,.3,.2))])]
        batches=[[0],[1],[2,4],[3]];before=copy.deepcopy((jobs,batches))
        with patch.object(study,'VISUAL_REQUEST_PRIORITY',True):
            result=study.request_schedule(batches,jobs,front=[0,1])
        self.assertEqual(result,[[0],[1],[3],[2,4]])
        self.assertEqual((jobs,batches),before)
        self.assertEqual(sorted(map(tuple,result)),sorted(map(tuple,batches)))

    def test_confirmed_id_list_plan_survives_range_wire_upgrade(self):
        blocks=[block('0','원리'),block('1','설명')];groups=[{'title':'원리','blocks':blocks}]
        with patch.object(study,'PLAN_TRANSPORT','ids'):
            saved=study.plan_record(groups,[],'gpt-6-luna',blocks=blocks)
        with patch.object(study,'PLAN_TRANSPORT','ranges'):
            self.assertTrue(study.usable_plan(saved,blocks=blocks))
            changed=copy.deepcopy(blocks);changed[1]['text']='다른 원문'
            self.assertFalse(study.usable_plan(saved,blocks=changed))
            self.assertFalse(study.usable_plan(saved,model='another-model',blocks=blocks))


if __name__=='__main__':unittest.main()
