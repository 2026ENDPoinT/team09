"""No-network contracts for compact grouping and source-preserving splitting."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
from pdf_group_transport import request, expand
from pdf_ai import AiResponseError


def block(n, **extra):
    return {'id':f'p{n}f0','page':n+1,'text':'기관의 정의와 작용 '+('가'*400),
            'kind':'text','headingId':'heading','bbox':[.1,.2,.8,.6],
            'zone':0,'hasVisual':False,'visualOnly':False,**extra}


class GroupTransportTests(unittest.TestCase):
    def test_default_planner_sends_full_source_and_restores_exact_canonical_metadata(self):
        self.assertEqual(study.PLAN_TRANSPORT,'ranges')
        blocks=[block(i) for i in range(3)];original=copy.deepcopy(blocks);calls=[]
        def complete(payload,**options):
            calls.append(copy.deepcopy((payload,options)))
            return {'groups':[{'first':0,'last':1,'title':'정의와 조건','role':'teaching','continuesPrevious':False},
                              {'first':2,'last':2,'title':'관계와 의미','role':'teaching','continuesPrevious':False}]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=complete)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);groups,_=study.plan_groups(folder,provider,blocks,folder)
            plan=json.loads((folder/'plan.json').read_text())
        payload,options=calls[0]
        self.assertEqual(len(calls),1)
        self.assertEqual([b['text'] for b in payload['targets']],[b['text'] for b in original])
        self.assertEqual([b['index'] for b in payload['targets']],[0,1,2])
        self.assertIn('first',options['response_format']['json_schema']['schema']['properties']['groups']['items']['properties'])
        restored=[b for group in groups for b in group['blocks']]
        self.assertEqual([b['id'] for b in restored],[b['id'] for b in original])
        for before,after in zip(original,restored):
            for key,value in before.items():self.assertEqual(after[key],value)
        self.assertEqual(plan['sourcePartition']['sourceDigest'],plan['sourcePartition']['assignedSourceDigest'])
        self.assertTrue(study.usable_plan(plan,blocks=original))

    def test_verified_id_plan_is_reused_without_another_model_call_after_default_switch(self):
        blocks=[block(i) for i in range(3)];doc={'documentId':'doc','fingerprint':'fp','pages':[
            {'number':i+1,'nativeText':b['text'],'label':str(i+1)} for i,b in enumerate(blocks)]}
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);legacy=folder/'generated/new-concept-v99/legacy';legacy.mkdir(parents=True)
            groups=[{'title':'정의와 조건','blocks':copy.deepcopy(blocks)}]
            with patch.object(study,'PLAN_TRANSPORT','ids'):
                old_plan=study.plan_record(groups,[],'gpt-6-luna',blocks=blocks)
            for name,value in {'blocks.json':blocks,'plan.json':old_plan,
                               'manifest.json':{'jobs':[],'teachingIdentity':study.teaching_identity()},
                               'partial.json':{'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99','scope':'document','page':0}}.items():
                (legacy/name).write_text(json.dumps(value))
            before={p.name:p.read_bytes() for p in legacy.iterdir()}
            provider=SimpleNamespace(model='gpt-6-luna',billing=None,
                complete=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('no repeat paid planning')))
            with patch.object(study,'extract',return_value=copy.deepcopy(blocks)):
                result=study.prepare_group_plan(folder,doc,provider)
            root=study.root_path(folder,doc,'new-concept-v99',provider.model,'document',0)
            reused=json.loads((root/'plan.json').read_text())
            self.assertTrue(result['groupingConfirmed'])
            self.assertTrue(study.usable_plan(reused,blocks=blocks))
            self.assertEqual(reused['reusedFrom'],str(legacy))
            self.assertEqual({p.name:p.read_bytes() for p in legacy.iterdir()},before)

    def test_range_transport_keeps_full_text_and_expands_original_ids(self):
        blocks=[block(i) for i in range(5)]
        source=copy.deepcopy(blocks)
        payload=request(blocks[1:4],blocks[:1],blocks[4:],study.planning_fragment)
        self.assertEqual([b['index'] for b in payload['targets']],[0,1,2])
        self.assertEqual([b['text'] for b in payload['targets']],[b['text'] for b in blocks[1:4]])
        raw={'groups':[{'first':0,'last':1,'title':'정의','role':'teaching'},
                       {'first':2,'last':2,'title':'구조','role':'uncertain'}]}
        converted=expand(raw,blocks[1:4])
        self.assertEqual([g['blockIds'] for g in converted['groups']],[['p1f0','p2f0'],['p3f0']])
        self.assertEqual(blocks,source)
        self.assertIn('first',raw['groups'][0])

    def test_no_gaps_overlap_reordering_context_or_boolean_indices(self):
        for ranges in [[(0,0)],[(1,2)],[(0,1),(1,2)],[(0,3)],[(0,0),(2,2)],
                       [(0,1),(2,1)],[(False,2)],[(0,1.5)]]:
            with self.subTest(ranges=ranges),self.assertRaises(AiResponseError):
                expand({'groups':[{'first':a,'last':b} for a,b in ranges]},[block(i) for i in range(3)])

    def test_parallel_windows_merge_continuation_without_duplicate_sources(self):
        blocks=[block(i) for i in range(6)]
        def complete(payload,**kw):
            return {'groups':[{'first':0,'last':len(payload['targets'])-1,
                'title':'하나의 원리','role':'teaching','continuesPrevious':bool(payload['before'])}]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=complete)
        with tempfile.TemporaryDirectory() as d,patch.object(study,'PLAN_TRANSPORT','ranges'), \
             patch.object(study,'PLAN_WINDOW_BLOCKS',2):
            groups,_=study.plan_groups(Path(d),provider,blocks,Path(d))
        self.assertEqual(len(groups),1)
        self.assertEqual([b['id'] for g in groups for b in g['blocks']],[b['id'] for b in blocks])

    def test_transport_splits_keep_semantic_topic_and_each_source_once(self):
        blocks=[block(i) for i in range(9)]
        with patch.object(study,'JOB_CROP_LIMIT',2),patch.object(study,'JOB_WEIGHT_LIMIT',3000):
            jobs=study.jobs_for([{'title':'같은 주제','blocks':blocks}])
        self.assertGreater(len(jobs),1)
        self.assertEqual({j['topicIndex'] for j in jobs},{0})
        self.assertEqual([b['id'] for j in jobs for b in j['blocks']],[b['id'] for b in blocks])
        self.assertTrue(all(len(study.crop_runs(j['blocks']))<=4 for j in jobs))

    def test_atomic_table_and_single_panel_never_split_for_soft_size_limit(self):
        source=block(0,text='표 한 덩어리 '+('가'*12000),kind='visual',hasVisual=True)
        with patch.object(study,'JOB_CROP_LIMIT',2),patch.object(study,'JOB_WEIGHT_LIMIT',1000):
            jobs=study.jobs_for([{'title':'기관','blocks':[source]}])
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['blocks'],[source])

    def test_page_cap_only_splits_transport_and_keeps_one_semantic_topic(self):
        blocks=[block(i) for i in range(7)]
        with patch.object(study,'JOB_PAGE_LIMIT',3):
            jobs=study.jobs_for([{'title':'긴 설명','blocks':blocks}])
        self.assertEqual([len({b['page'] for b in j['blocks']}) for j in jobs],[3,3,1])
        self.assertEqual({j['topicIndex'] for j in jobs},{0})
        self.assertTrue(all(j['contextDepth']==4 for j in jobs))
        self.assertEqual([b['id'] for j in jobs for b in j['blocks']],[b['id'] for b in blocks])


if __name__=='__main__':unittest.main()
