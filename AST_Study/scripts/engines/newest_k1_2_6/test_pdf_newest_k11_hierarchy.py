"""K1.1 hierarchy isolation, exact source ownership and same-call metadata tests."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_newest_k1 as old
import pdf_newest_k11 as new
import pdf_newest_k11_hierarchy as h
from pdf_newest_k11_owner import SourceIndex
from test_pdf_newest_k1 import block


class HierarchyTests(unittest.TestCase):
    def test_generation_contract_is_identical_except_planning(self):
        for name in ('STUDY_PROMPT','STUDY_FORMAT','BATCH_RULES','OVERVIEW_PROMPT',
                     'MAX_STUDY_WORKERS','MAX_STARTUP_WORKERS','TRANSPORT_BATCH_UNITS',
                     'TRANSPORT_BATCH_IMAGES','DURABLE_STUDY_BODY','STUDY_REASONING_EFFORT',
                     'JOB_WEIGHT_LIMIT','JOB_CROP_LIMIT','JOB_PAGE_LIMIT'):
            self.assertEqual(getattr(old,name),getattr(new,name),name)
        groups=[{'title':'혈액','blocks':[block(0)],'description':'혈액의 기능'}]
        self.assertEqual(old.jobs_for(groups),new.jobs_for(groups))
        self.assertNotEqual(old.planner_identity(),new.planner_identity())
        self.assertNotIn('topicPath',old.K1_RANGE_FORMAT['json_schema']['schema']['properties']['groups']['items']['properties'])

    def test_metadata_survives_existing_single_call_repair(self):
        blocks=[block(0),block(1)]
        raw={'groups':[{'title':'혈장','description':'성분과 기능','topicPath':['혈액'],
              'first':0,'last':1,'role':'teaching','continuesPrevious':False}]}
        class Provider:model='gpt-6-luna';context={}
        with tempfile.TemporaryDirectory() as tmp, patch('pdf_ai.complete_study_delivery',return_value=raw) as call,patch.object(new,'emit'):
            groups,_=new.plan_groups(Path(tmp),Provider(),blocks,Path(tmp))
            self.assertEqual(call.call_count,1)
            self.assertEqual(groups[0]['topicPath'],['혈액'])
            self.assertEqual([b['text'] for b in groups[0]['blocks']],[b['text'] for b in blocks])

    def test_same_topic_keeps_cards_and_cross_zone_ownership(self):
        blocks=[{**block(i),'page':1,'zone':i} for i in range(4)]
        groups=[{'title':str(i),'blocks':[b],'topicPath':(['혈액'] if i<2 else ['심장'])} for i,b in enumerate(blocks)]
        saved=copy.deepcopy(blocks)
        nodes=h.planned_headings(blocks,groups,[])
        self.assertEqual([n['title'] for n in nodes],['혈액','심장'])
        owners=SourceIndex(blocks,nodes)
        self.assertEqual([owners.owner(b['id'])['title'] for b in blocks],['혈액','혈액','심장','심장'])
        result={'sections':[{'title':'수업','parts':[{'title':str(i),'body':'원문 설명 '+str(i),
                'evidence':[{'sourceId':b['id'],'page':1}]} for i,b in enumerate(blocks)]}]}
        out=h.decorate(result,blocks,nodes)
        self.assertEqual([p['body'] for p in out['sections'][0]['parts']],['원문 설명 '+str(i) for i in range(4)])
        self.assertEqual(len({p['contentId'] for p in out['sections'][0]['parts']}),4)
        self.assertEqual(blocks,saved)

    def test_furniture_does_not_split_topic(self):
        blocks=[block(i) for i in range(3)]
        blocks[1]['planRole']='decoration'
        groups=[{'blocks':[b],'topicPath':['심장']} for b in blocks]
        nodes=h.planned_headings(blocks,groups,[])
        self.assertEqual(len(nodes),1)
        self.assertEqual(nodes[0]['endBlockId'],blocks[-1]['id'])

    def test_returning_branch_is_not_globally_merged(self):
        blocks=[block(i) for i in range(3)]
        groups=[{'blocks':[b],'topicPath':[title]} for b,title in zip(blocks,['혈액','심장','혈액'])]
        nodes=h.planned_headings(blocks,groups,[])
        self.assertEqual([n['title'] for n in nodes],['혈액','심장','혈액'])
        self.assertEqual(len({n['id'] for n in nodes}),3)

    def test_explicit_numbering_overrides_inferred_parent(self):
        blocks=[block(0),block(1)]
        source=[{'id':'h0','parentId':'','title':'5. 금융','level':1,'page':1,'startBlockId':blocks[0]['id'],'endBlockId':blocks[1]['id']},
                {'id':'h1','parentId':'h0','title':'5.1. 주식','level':2,'page':1,'startBlockId':blocks[0]['id'],'endBlockId':blocks[1]['id']}]
        nodes=h.planned_headings(blocks,[{'blocks':blocks,'topicPath':['엉뚱한 상위 제목']}],source)
        self.assertEqual([n['title'] for n in nodes],['5. 금융','5.1. 주식'])
        self.assertIsNone(h.numbered_title('2025.04.02 미국의 새 관세정책'))
        self.assertFalse(h.title_like('2025.04.02 미국의 새 관세정책'))

    def test_semantic_path_continues_printed_subsection_through_example(self):
        blocks=[block(i) for i in range(3)]
        source=[{'id':'root','parentId':'','title':'2. 산업화','level':1,'page':1,
                 'startBlockId':blocks[0]['id'],'endBlockId':blocks[2]['id']},
                {'id':'sub','parentId':'root','title':'1) 농지개혁','sourceKind':'list',
                 'level':2,'page':1,'startBlockId':blocks[0]['id'],'endBlockId':blocks[0]['id']}]
        groups=[{'blocks':[b],'topicPath':['산업화','농지개혁']} for b in blocks]
        nodes=h.planned_headings(blocks,groups,source)
        self.assertEqual([n['title'] for n in nodes],['2. 산업화','1) 농지개혁'])
        self.assertEqual(nodes[1]['endBlockId'],blocks[-1]['id'])

    def test_invalid_paths_fall_back_without_changing_sources(self):
        for value in ('혈액',['혈액']*2,['구성'],['2025.04.02 관세'],[1],['A','B','C','D']):
            self.assertEqual(h.topic_path(value),[])
        blocks=[block(0)]
        source=[{'id':'h0','parentId':'','title':'혈액','level':1,'page':1,'startBlockId':blocks[0]['id'],'endBlockId':blocks[0]['id']}]
        self.assertEqual(h.planned_headings(blocks,[{'blocks':blocks,'topicPath':['구성']}],source)[0]['title'],'혈액')

if __name__=='__main__':unittest.main()
