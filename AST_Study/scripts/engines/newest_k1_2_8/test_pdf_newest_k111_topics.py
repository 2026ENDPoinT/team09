"""Same-call stable source anchors, without synonym dictionaries or source edits."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_newest_k11 as old
import pdf_newest_k111 as engine
import pdf_newest_k111_hierarchy as h
from pdf_newest_k111_topics import source_catalog, window_context, validated_ids
from test_pdf_newest_k1 import block


def fixture():
    blocks=[block(i) for i in range(6)]
    blocks[0].update(text='운반 체계',kind='heading',fontSize=24)
    heads=[{'id':'h:'+blocks[0]['id'],'parentId':'','title':'운반 체계','level':1,
            'page':1,'startBlockId':blocks[0]['id'],'endBlockId':blocks[4]['id'],
            'sourceKind':'title','sourceHeading':True},
           {'id':'h:'+blocks[5]['id'],'parentId':'','title':'운반 체계','level':1,
            'page':6,'startBlockId':blocks[5]['id'],'endBlockId':blocks[5]['id'],
            'sourceKind':'title','sourceHeading':True}]
    return blocks,heads


class SourceTopicTests(unittest.TestCase):
    def test_missing_window_ancestor_is_supplied_with_document_stable_id(self):
        blocks,heads=fixture();catalog=source_catalog(blocks,heads)
        earlier=window_context(blocks[:3],blocks,catalog)
        later=window_context(blocks[3:5],blocks,catalog)
        self.assertEqual(earlier[0]['id'],later[0]['id'])
        self.assertEqual(later[0]['title'],'운반 체계')
        self.assertEqual((later[0]['firstTarget'],later[0]['lastTarget']),(0,1))
        self.assertEqual(len(later),1)  # No whole-document topic map.
        self.assertEqual(window_context(blocks,blocks,catalog,has_before=False,has_after=False),[])
        self.assertEqual(window_context(blocks[3:5],blocks,catalog,has_before=True,has_after=False)[0]['id'],later[0]['id'])

    def test_different_aliases_share_anchor_but_identical_names_with_other_ids_do_not(self):
        blocks,heads=fixture();saved=copy.deepcopy(blocks)
        groups=[{'blocks':blocks[:2],'topicPath':['운반 체계'],'topicSourceIds':['h:kp0f0']},
                {'blocks':blocks[2:5],'topicPath':['수송 시스템'],'topicSourceIds':['h:kp0f0']},
                {'blocks':blocks[5:],'topicPath':['운반 체계'],'topicSourceIds':['h:kp5f0']}]
        nodes=h.planned_headings(blocks,groups,heads)
        self.assertEqual([n['title'] for n in nodes],['운반 체계','운반 체계'])
        self.assertEqual([n['sourceTopicId'] for n in nodes],['h:kp0f0','h:kp5f0'])
        self.assertEqual(nodes[0]['endBlockId'],blocks[4]['id'])
        self.assertEqual(blocks,saved)

    def test_unknown_out_of_scope_and_inverted_parent_ids_fall_back(self):
        blocks,heads=fixture()
        heads.append({'id':'child','parentId':'h:kp0f0','title':'하위 체계','level':2,
            'page':2,'startBlockId':blocks[1]['id'],'endBlockId':blocks[3]['id'], 'sourceKind':'title'})
        catalog=source_catalog(blocks,heads)
        for ids in (['missing'],['h:kp5f0'],[2]):
            path=['주제']*len(ids)
            self.assertEqual(validated_ids(path,ids,blocks[1:3],blocks,catalog),['']*len(path))
        self.assertEqual(validated_ids(['상위','하위'],['h:kp0f0','missing'],blocks[1:3],blocks,catalog),['h:kp0f0',''])
        self.assertEqual(validated_ids(['상위','하위'],['h:kp0f0','h:kp0f0'],blocks[1:3],blocks,catalog),['h:kp0f0',''])
        self.assertEqual(validated_ids(['상위','하위'],['h:kp0f0','child'],blocks[1:3],blocks,catalog),['h:kp0f0','child'])
        self.assertEqual(validated_ids(['상위'],['h:kp0f0'],blocks[3:6],blocks,catalog),[''])

    def test_common_ancestor_is_not_a_synonym_rule(self):
        blocks,heads=fixture()
        groups=[{'blocks':blocks[:2],'topicPath':['수송']},
                {'blocks':blocks[2:4],'topicPath':['수송의 제어']}]
        nodes=h.planned_headings(blocks[:4],groups,[{**heads[0],'endBlockId':blocks[3]['id']}])
        self.assertEqual([n['title'] for n in nodes],['수송','수송의 제어'])
        self.assertTrue(all(not n['sourceTopicId'] for n in nodes))

    def test_source_catalog_excludes_cover_and_date(self):
        blocks,heads=fixture()
        for title in ('2026년 2학기 예시대학교','(Course Name)','2025.04.02 사건','목차'):
            self.assertEqual(source_catalog(blocks,[{**heads[0],'title':title}]),{})

    def test_partition_normalization_keeps_anchor_metadata_in_one_existing_call(self):
        blocks,heads=fixture();blocks=blocks[:4];heads=[{**heads[0],'endBlockId':blocks[-1]['id']}]
        class Provider:model='gpt-6-luna';context={}
        raw={'groups':[{'title':'내용','description':'정의와 원리','topicPath':[{'title':'수송 시스템','sourceHeadingId':''}],
                       'first':0,'last':3,'role':'teaching','continuesPrevious':False}]}
        before=copy.deepcopy(blocks)
        def complete(provider,payload,**kw):
            self.assertEqual(payload['sourceTopics'],[])
            self.assertEqual([b['text'] for b in payload['targets']],[b['text'] for b in before])
            return raw
        with tempfile.TemporaryDirectory() as tmp,patch('pdf_ai.complete_study_delivery',side_effect=complete) as call,patch.object(engine.hierarchy,'source_headings',return_value=heads),patch.object(engine,'emit'):
            groups,_=engine.plan_groups(Path(tmp),Provider(),blocks,Path(tmp))
            self.assertEqual(call.call_count,1)
            self.assertEqual(groups[0]['topicSourceIds'],[''])
            self.assertEqual([b['id'] for b in groups[0]['blocks']],[b['id'] for b in before])
            loaded=engine.read_json(Path(tmp)/'plan.json')
            self.assertEqual(loaded['groups'][0]['topicSourceIds'],[''])

    def test_alias_join_preserves_every_card_in_original_order(self):
        blocks,heads=fixture();groups=[{'blocks':[b],'topicPath':['체계' if i%2 else '시스템'],
             'topicSourceIds':['h:kp0f0' if i<5 else 'h:kp5f0']} for i,b in enumerate(blocks)]
        nodes=h.planned_headings(blocks,groups,heads)
        original={'sections':[{'title':'학습 내용','parts':[{'title':f'개념 {i}','body':f'설명 {i}',
            'evidence':[{'sourceId':b['id'],'page':b['page']}]} for i,b in enumerate(blocks)]}]}
        result=h.decorate(original,blocks,nodes)
        self.assertEqual([p['body'] for p in result['sections'][0]['parts']],[f'설명 {i}' for i in range(6)])
        self.assertEqual(len({p['contentId'] for p in result['sections'][0]['parts']}),6)
        self.assertEqual(len([n for n in result['hierarchy']['nodes'] if n.get('sourceTopicId')]),2)

    def test_two_parallel_windows_use_same_anchor_without_another_call(self):
        blocks,heads=fixture();blocks=blocks[:4];heads=[{**heads[0],'endBlockId':blocks[-1]['id']}]
        class Provider:model='gpt-6-luna';context={}
        def complete(provider,payload,**kw):
            schema=kw['response_format']['json_schema']['schema']['properties']['groups']['items']['properties']['topicPath']
            self.assertEqual(schema['items']['properties']['sourceHeadingId']['enum'],['','h:kp0f0'])
            self.assertNotIn('enum',schema['items']['properties']['title'])
            self.assertEqual(h.topic_path(['h:kp0f0']),[])
            self.assertEqual(payload['sourceTopics'][0]['id'],'h:kp0f0')
            return {'groups':[{'title':'운반','description':'운반의 원리',
                'topicPath':[{'title':'체계' if payload['before'] else '시스템','sourceHeadingId':'h:kp0f0'}],
                'first':0,'last':len(payload['targets'])-1,'role':'teaching','continuesPrevious':False}]}
        with tempfile.TemporaryDirectory() as tmp,patch('pdf_ai.complete_study_delivery',side_effect=complete) as call,patch.object(engine.hierarchy,'source_headings',return_value=heads),patch.object(engine,'PLAN_WINDOW_BLOCKS',2),patch.object(engine,'emit'):
            groups,_=engine.plan_groups(Path(tmp),Provider(),blocks,Path(tmp))
            self.assertEqual(call.call_count,2)
            self.assertEqual(len(groups),2)
            nodes=h.planned_headings(blocks,groups,heads)
            self.assertEqual(len(nodes),1)
            self.assertEqual(nodes[0]['sourceTopicId'],'h:kp0f0')
        self.assertNotIn('enum',engine.K1_RANGE_FORMAT['json_schema']['schema']['properties']['groups']['items']['properties']['topicPath']['items']['properties']['sourceHeadingId'])

    def test_source_fallback_keeps_known_heading_identity(self):
        blocks,heads=fixture();blocks=blocks[:5];heads=heads[:1]
        groups=[{'blocks':blocks[:3],'topicPath':['체계'],'topicSourceIds':['h:kp0f0']},
                {'blocks':blocks[3:],'topicPath':[]}]
        nodes=h.planned_headings(blocks,groups,heads)
        self.assertEqual(len(nodes),1)
        self.assertEqual(nodes[0]['sourceTopicId'],'h:kp0f0')
        self.assertEqual(nodes[0]['endBlockId'],blocks[-1]['id'])

    def test_old_engine_and_teaching_contract_unchanged(self):
        for key in ('STUDY_PROMPT','STUDY_FORMAT','OVERVIEW_PROMPT','BATCH_RULES',
                    'DURABLE_STUDY_BODY','TRANSPORT_BATCH_UNITS','MAX_STUDY_WORKERS','STUDY_REASONING_EFFORT'):
            self.assertEqual(getattr(old,key),getattr(engine,key),key)
        self.assertNotEqual(old.VERSION,engine.VERSION)
        self.assertNotEqual(old.planner_identity(),engine.planner_identity())
        self.assertNotIn('topicSourceIds',old.K1_RANGE_FORMAT['json_schema']['schema']['properties']['groups']['items']['properties'])
        blocks,_=fixture();groups=[{'title':'내용','description':'설명','blocks':blocks}]
        self.assertEqual(old.jobs_for(groups),engine.jobs_for(groups))

if __name__=='__main__':unittest.main()
