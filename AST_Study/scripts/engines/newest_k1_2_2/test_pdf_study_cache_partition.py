"""Offline reuse must prove source accounting from independent extraction."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pdf_group_partition import repair_partition, validate_partition
from pdf_study_cache_reuse import reuse_plan, source_mapping


def block(key, text, page=1, box=None, **extra):
    return {'id':key,'page':page,'zone':0,'kind':'text','text':text,
            'bbox':box or [.1,.1,.9,.2], 'hasVisual':False, **extra}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class CachePartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.old=self.folder/'generated/new-concept-v99/old'
        self.cache=self.old.parent/'new'
        self.document={'documentId':'doc','fingerprint':'fp'}
        self.blocks=[block('old-a','원리 A'),
                     block('old-b','원리 B',box=[.1,.3,.9,.4]),
                     block('old-c','원리 C',page=2)]
        self.groups=[{'title':'첫 주제','blocks':copy.deepcopy(self.blocks[:2])},
                     {'title':'둘째 주제','blocks':copy.deepcopy(self.blocks[2:])}]
        for group in self.groups:
            for item in group['blocks']:item['planRole']='teaching'
        self.plan={'plannerIdentity':'planner','status':'confirmed','warnings':[],
                   'groups':self.groups,'headings':[]}
        self.seed()

    def seed(self):
        save(self.old/'blocks.json',self.blocks)
        save(self.old/'plan.json',self.plan)
        save(self.old/'manifest.json',{'jobs':[]})
        save(self.old/'partial.json',{'documentId':'doc','sourceFingerprint':'fp',
            'scope':'document','page':0,'strategy':'new-concept-v99'})

    def reuse(self, blocks=None):
        return reuse_plan(self.folder,self.cache,self.document,'new-concept-v99',
                          'document',0,self.blocks if blocks is None else blocks,
                          planner_identity='planner')

    def test_valid_legacy_plan_without_proof_is_validated_and_rebound(self):
        current=[{**item,'id':item['id'].replace('old-','new-')} for item in self.blocks]
        old_before={p.name:p.read_bytes() for p in self.old.iterdir()}
        current_before=copy.deepcopy(current)
        plan,manifest=self.reuse(current)
        self.assertEqual([b['id'] for g in plan['groups'] for b in g['blocks']],
                         ['new-a','new-b','new-c'])
        self.assertEqual(plan['sourcePartition'],validate_partition(current,plan['groups'],
                                                                  require_global_order=False))
        self.assertEqual(manifest,{'jobs':[]})
        self.assertEqual(current,current_before)
        self.assertEqual({p.name:p.read_bytes() for p in self.old.iterdir()},old_before)
        self.assertNotIn('assignmentRecovery',plan)

    def test_plan_cannot_use_its_own_flattened_groups_as_canonical_source(self):
        for change in ('missing','duplicate','unknown','text','bbox','source_metadata'):
            with self.subTest(change=change):
                plan=copy.deepcopy(self.plan)
                if change=='missing':plan['groups'][0]['blocks'].pop()
                elif change=='duplicate':plan['groups'][1]['blocks'].append(copy.deepcopy(self.blocks[0]))
                elif change=='unknown':plan['groups'][0]['blocks'][0]['id']='unknown'
                elif change=='text':plan['groups'][0]['blocks'][0]['text']='바뀐 원문'
                elif change=='bbox':plan['groups'][0]['blocks'][0]['bbox'][0]=.11
                else:plan['groups'][0]['blocks'][0]['nativeTableRows']=[['변조']]
                save(self.old/'plan.json',plan)
                self.assertEqual(self.reuse(),(None,None))

    def test_missing_independent_extraction_is_not_certified_by_old_proof(self):
        self.plan['sourcePartition']=validate_partition(self.blocks,self.groups)
        self.seed()
        (self.old/'blocks.json').unlink()
        self.assertEqual(self.reuse(),(None,None))

    def test_stale_proof_is_recomputed_instead_of_trusted(self):
        self.plan['sourcePartition']={'complete':True,'sourceCount':999,'sourceDigest':'forged'}
        self.seed()
        plan,_=self.reuse()
        self.assertEqual(plan['sourcePartition']['sourceCount'],3)
        self.assertNotEqual(plan['sourcePartition']['sourceDigest'],'forged')

    def test_interleaved_semantic_groups_keep_internal_source_order(self):
        self.plan['groups']=[{'title':'연속 개념','blocks':[self.blocks[0],self.blocks[2]]},
                             {'title':'사이 주제','blocks':[self.blocks[1]]}]
        self.seed()
        plan,_=self.reuse()
        self.assertIsNotNone(plan)
        self.assertFalse(plan['sourcePartition']['orderPreserved'])
        self.assertTrue(plan['sourcePartition']['eachGroupSourceOrderPreserved'])

    def test_bad_internal_order_is_rejected(self):
        self.plan['groups'][0]['blocks'].reverse()
        self.seed()
        self.assertEqual(self.reuse(),(None,None))

    def test_headings_rebind_only_to_current_canonical_sources(self):
        self.plan['headings']=[{'id':'h:old-a','parentId':'','title':'old-a도 원문 제목이에요.',
                               'startBlockId':'old-a','endBlockId':'old-c','level':1,'page':1}]
        self.seed()
        current=[{**b,'id':b['id'].replace('old-','new-')} for b in self.blocks]
        plan,_=self.reuse(current)
        self.assertEqual(plan['headings'][0],{**self.plan['headings'][0],
            'id':'h:new-a','startBlockId':'new-a','endBlockId':'new-c'})
        self.plan['headings'][0]['endBlockId']='unknown'
        self.seed()
        self.assertEqual(self.reuse(current),(None,None))

    def test_edge_addition_is_in_new_proof_and_old_proof_is_unchanged(self):
        old_proof=validate_partition(self.blocks,self.groups)
        self.plan['sourcePartition']=old_proof
        self.seed()
        edge=block('edge','잘린 하단 설명',page=2,box=[.1,.96,.9,1.],pageEdgeClipped=True)
        plan,_=self.reuse(self.blocks+[edge])
        self.assertEqual(plan['addedEdgeBlockIds'],['edge'])
        self.assertEqual(plan['sourcePartition']['sourceCount'],4)
        self.assertEqual(json.loads((self.old/'plan.json').read_text())['sourcePartition'],old_proof)

    def test_recovery_ids_and_window_proofs_rebind_without_changing_prose_or_roles(self):
        raw={'groups':[{'title':'AI 주제','role':'teaching','blockIds':['old-a'],
                        'continuesPrevious':False},
                       {'title':'다음 주제','role':'teaching','blockIds':['old-c','raw-unknown'],
                        'continuesPrevious':False}]}
        groups,metadata=repair_partition(raw,self.blocks)
        metadata.update(windowIndex=0,sourceBlockIds=[b['id'] for b in self.blocks])
        metadata['diagnostics'].append({'reason':'note','blockId':'old-b',
                                        'text':'old-b는 원문 표기예요.'})
        self.plan['groups']=groups
        self.plan['assignmentRecovery']={'version':metadata['version'],'windows':[metadata],
            'localUncertainBlockIds':['old-b'],'semanticGroupingStatus':'locally_recovered',
            'additionalRecoveryApiRequests':0,
            'confirmationScope':'exact source partition only; local uncertain ownership is not AI semantic confirmation'}
        self.seed()
        current=[{**b,'id':b['id'].replace('old-','new-')} for b in self.blocks]
        plan,_=self.reuse(current)
        recovery=plan['assignmentRecovery'];window=recovery['windows'][0]
        self.assertEqual(recovery['localUncertainBlockIds'],['new-b'])
        self.assertEqual(recovery['semanticGroupingStatus'],'locally_recovered')
        self.assertEqual(window['sourceBlockIds'],['new-a','new-b','new-c'])
        self.assertEqual(window['unassignedBlockIds'],['new-b'])
        self.assertEqual(window['coverageProof'],validate_partition(current,plan['groups'],
                                                                  require_global_order=False))
        self.assertEqual(window['diagnostics'][-1],{'reason':'note','blockId':'new-b',
                                                   'text':'old-b는 원문 표기예요.'})
        self.assertIn('raw-unknown',[d.get('blockId') for d in window['diagnostics']])
        self.assertEqual(next(b for g in plan['groups'] for b in g['blocks']
                              if b['id']=='new-b')['planRole'],'uncertain')
        self.assertEqual(json.loads((self.old/'plan.json').read_text()),self.plan)

    def test_unknown_recovery_ownership_or_missing_window_sources_declines_reuse(self):
        for recovery in ({'windows':[{'coverageProof':{'complete':True}}]},
                         {'windows':[],'localUncertainBlockIds':['unknown']}):
            with self.subTest(recovery=recovery):
                self.plan['assignmentRecovery']=recovery
                self.seed()
                self.assertEqual(self.reuse(),(None,None))

    def test_duplicate_current_id_or_ambiguous_region_mapping_is_rejected(self):
        self.assertIsNone(source_mapping(self.blocks,[*self.blocks,self.blocks[0]]))
        self.assertIsNone(source_mapping([self.blocks[0]],
                                        [self.blocks[0],{**self.blocks[0],'id':'ambiguous'}]))
        self.assertEqual(self.reuse([*self.blocks,self.blocks[0]]),(None,None))


if __name__=='__main__':unittest.main()
