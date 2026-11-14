"""Offline source, wire, cache and delivery safeguards for the isolated engine."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_newest_k1_2_0 as engine
from pdf_k123_planning_packets import pack,recover,members
from pdf_k123_shared_images import write_shared
from pdf_k123_native_prose import normalized
from test_pdf_k120_compact_coverage import fixture


class PlanningPackets(unittest.TestCase):
    def blocks(self):
        return [{'id':key,'page':1,'zone':0,'headingId':'h','kind':'text',
            'text':'문장의 이어지는 내용 '+key,'bbox':[.1,.1+i*.08,.8,.16+i*.08]}
            for i,key in enumerate(['a','b','c'])]

    def test_coarser_input_retains_exact_original_order_metadata_and_text(self):
        source=self.blocks();before=copy.deepcopy(source);packets=pack(source)
        self.assertEqual(len(packets),1)
        self.assertEqual([b for p in packets for b in members(p)],before)
        raw={'groups':[{'title':'관계','first':0,'last':0,'role':'teaching','continuesPrevious':False}]}
        value,audit=recover(raw,packets,source)
        self.assertEqual(value['groups'][0]['blockIds'],['a','b','c'])
        self.assertEqual(source,before)
        self.assertEqual((audit['planningTargetCount'],audit['sourceTargetCount']),(1,3))

    def test_page_heading_panel_exercise_and_unknown_geometry_stay_separate(self):
        for change in ({'page':2},{'zone':1},{'headingId':'other'},
                       {'kind':'heading'},{'text':'문제 1. 구하라'},
                       {'geometryFallback':True},{'pageEdgeClipped':True}):
            with self.subTest(change=change):
                blocks=self.blocks()[:2];blocks[1].update(change)
                self.assertEqual(len(pack(blocks)),2)

    def test_invalid_range_stays_a_gap_for_original_partition_guard(self):
        from pdf_group_partition import repair_partition,validate_partition
        source=self.blocks();source[1]['page']=2;source[2]['page']=3
        value,audit=recover({'groups':[{'title':'첫','first':0,'last':0,'role':'teaching'},
            {'title':'오류','first':1,'last':100,'role':'teaching'}]},pack(source),source)
        self.assertEqual(len(audit['invalidRangeGroups']),1)
        groups,proof=repair_partition(value,source)
        self.assertEqual(set(proof['localUncertainBlockIds']),{'b','c'})
        self.assertTrue(validate_partition(source,groups)['complete'])


class TeachingContract(unittest.TestCase):
    def request(self,tmp,job):
        return engine.build_teaching_request(Path(tmp),job,job['blocks'],
            {'documentId':'doc','pages':[{'label':'1'}]},([],[]))

    def test_practice_hint_preserves_mixed_teaching_and_keeps_the_wire_contract(self):
        job,_,_,_=fixture()
        job['unitContext']={'current':{'index':1,'title':'계획 제목','description':'계획 설명'}}
        for block in job['blocks']:
            block.update(text='',planRole='uncertain',planRoleBeforeVisualGuard='exercise')
        with tempfile.TemporaryDirectory() as tmp:
            image_only=self.request(tmp,job)
            job['blocks'][0]['text']='풀이 과정과 원리를 읽을 수 있는 연습 자료'
            practice=self.request(tmp,job)
            mixed_job=copy.deepcopy(job)
            mixed_job['blocks'][0].pop('planRoleBeforeVisualGuard')
            mixed_job['blocks'][0]['planRole']='teaching'
            mixed=self.request(tmp,mixed_job)
        original=practice['instructions']
        for default,brief in engine.PRACTICE_COMPRESSION:
            self.assertIn(brief,original)
            original=original.replace(brief,default,1)
        self.assertEqual(original,mixed['instructions'])
        self.assertEqual(practice['response_format'],mixed['response_format'])
        self.assertEqual(practice['payload']['unitContext']['current'],{'index':1})
        self.assertEqual(mixed['payload']['unitContext']['current'],job['unitContext']['current'])
        self.assertEqual(image_only['payload']['unitContext']['current'],job['unitContext']['current'])
        self.assertTrue(all(brief not in image_only['instructions'] for _,brief in engine.PRACTICE_COMPRESSION))

    def test_only_duplicate_internal_fields_leave_the_wire(self):
        job,_,_,_=fixture()
        with tempfile.TemporaryDirectory()as tmp:r=self.request(tmp,job)
        setup=r['response_format']['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']
        self.assertNotIn('interpretation',setup['properties'])
        self.assertNotIn('question',setup['properties']['learnerDifficulty']['properties'])
        for field in ('teachingRole','observedRelations','boundaryChecks','sourceQuotes'):
            self.assertIn(field,setup['properties'])
        self.assertEqual(r['job']['blocks'],job['blocks'])

    def test_unused_exclusion_alias_does_not_hide_a_real_missing_source(self):
        job,_,_,raw=fixture();raw.pop('sourceCoverage')
        raw['excludedBlocks']=[{'blockId':'unused-alias','reason':'not evidence'}]
        for s in raw['concepts'][0]['segments']:s['blockIds']=['a']
        raw['concepts'][0]['sourceSetup'].pop('interpretation')
        raw['concepts'][0]['sourceSetup']['learnerDifficulty'].pop('question')
        before=copy.deepcopy(raw)
        with tempfile.TemporaryDirectory()as tmp:
            request=self.request(tmp,job)
            unit=engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                [job],job,raw,request)
            self.assertEqual(next(c for c in unit['coverage']if c['blockId']=='b')['state'],'needs_review')
            self.assertTrue((Path(tmp)/'rejected-dispositions-unit.json').is_file())
        self.assertEqual(raw,before)

    def test_foreign_main_source_and_duplicate_citation_are_rejected(self):
        for ids in (['a','foreign-main'],['a','a']):
            with self.subTest(ids=ids),tempfile.TemporaryDirectory()as tmp:
                job,_,_,raw=fixture();raw.pop('sourceCoverage')
                raw['concepts'][0]['segments'][0]['blockIds']=ids
                with self.assertRaises(ValueError):
                    engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                        [job],job,raw,self.request(tmp,job))

    def test_optional_easy_never_replaces_required_main(self):
        job,_,_,raw=fixture();raw.pop('sourceCoverage')
        for s in raw['concepts'][0]['segments']:s['blockIds']=['a']
        raw['concepts'][0]['sourceSetup']['learnerDifficulty']={'kind':'mechanism'}
        raw['concepts'][0]['segments'].append({'kind':'easyExplanation','text':'시간에 따라 달라지는 위치를 비교해요.','blockIds':['b']})
        with tempfile.TemporaryDirectory()as tmp:
            result=engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                [job],job,raw,self.request(tmp,job))
        self.assertEqual(next(c for c in result['coverage']if c['blockId']=='b')['state'],'needs_review')

    def test_concrete_sourced_case_needs_no_invented_definition(self):
        job,_,_,raw=fixture();raw.pop('sourceCoverage')
        for block in job['blocks']:block['text']='1961년 정부는 은행을 국유화해 자원 배분을 통제했다.'
        raw['concepts'][0]['segments']=raw['concepts'][0]['segments'][1:]
        raw['concepts'][0]['segments'][0]['text']='정부가 은행을 소유하면서 금융자원의 배분을 통제하고 기업 투자에 영향을 주었어요.'
        setup=raw['concepts'][0]['sourceSetup'];setup['teachingRole']='source_case'
        setup['sourceQuotes']=['정부는 은행을 국유화해 자원 배분을 통제했다.']
        original=copy.deepcopy(raw['concepts'][0]['segments'])
        with tempfile.TemporaryDirectory()as tmp:
            result=engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                [job],job,raw,self.request(tmp,job))
        self.assertTrue(all(c['state']=='summarized'for c in result['coverage']))
        self.assertEqual(raw['concepts'][0]['segments'],original)
        self.assertEqual(result['concepts'][0]['definition'],'')

    def test_case_role_without_source_proof_does_not_hide_missing_meaning(self):
        job,_,_,raw=fixture();raw.pop('sourceCoverage')
        raw['concepts'][0]['segments']=raw['concepts'][0]['segments'][1:]
        raw['concepts'][0]['sourceSetup']['teachingRole']='source_case'
        with tempfile.TemporaryDirectory()as tmp:
            result=engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                [job],job,raw,self.request(tmp,job))
        self.assertTrue(all(c['state']=='needs_review'for c in result['coverage']))

    def test_technical_method_cannot_bypass_definition_with_case_role(self):
        from pdf_k113_review import ReviewPolicy
        blocks=[{'id':'a','text':'일반식 ∫ x dx = x²/2 + C'}]
        entry={'sourceSetup':{'teachingRole':'source_case','sourceQuotes':['∫ x dx']},
               'segments':[{'kind':'explanation','text':'적분의 새 방법이에요.','blockIds':['a']}]}
        self.assertFalse(ReviewPolicy(blocks).permits_supplement(entry))

    def test_native_worked_application_can_explain_without_a_second_definition(self):
        from pdf_k113_review import ReviewPolicy
        blocks=[{'id':'a','text':'예제 ∫ x dx','kind':'text'},
                {'id':'b','text':'(풀이) x²/2 + C','kind':'text'}]
        entry={'sourceSetup':{'teachingRole':'source_case','sourceQuotes':['예제 ∫ x dx']},
            'segments':[{'kind':'explanation','text':'이미 배운 거듭제곱 적분을 적용해요.','blockIds':['a','b']}]}
        self.assertTrue(ReviewPolicy(blocks).permits_supplement(entry))
        blocks.insert(1,{'id':'part','text':'(a) 첫 번째 방법','kind':'heading'})
        self.assertTrue(ReviewPolicy(blocks).permits_supplement(entry))
        blocks.insert(1,{'id':'wrap','text':'구하시오.','kind':'heading'})
        self.assertTrue(ReviewPolicy(blocks).permits_supplement(entry))
        blocks.insert(1,{'id':'h','text':'새 일반식','kind':'heading'})
        blocks=[b for b in blocks if b['id']!='part']
        self.assertFalse(ReviewPolicy(blocks).permits_supplement(entry))
        blocks=[{'id':'a','text':'예제 new int[3]; delete[] p;','kind':'text'}]
        entry['segments'][0]['blockIds']=['a']
        self.assertFalse(ReviewPolicy(blocks).permits_supplement(entry))

    def test_a_previous_complete_concept_does_not_bypass_rejected_case_proof(self):
        from pdf_new_concept_ver99_checks import prepare_response
        from pdf_k113_review import ReviewPolicy
        job,_,_,raw=fixture()
        for block in job['blocks']:block['text']='일반식 ∫ x dx = x²/2+C'
        incomplete=copy.deepcopy(raw['concepts'][0]);incomplete['segments']=incomplete['segments'][1:]
        incomplete['sourceSetup']['teachingRole']='source_case'
        incomplete['sourceSetup']['sourceQuotes']=['일반식']
        raw['concepts'].append(incomplete)
        result=prepare_response(raw,preserve_boundaries=True,distinguish_supplements=True,
            review_policy=ReviewPolicy(job['blocks']))
        self.assertTrue(any(x.get('reason')=='local_output_check: incomplete_supported_concept'
            for x in result['uncertainBlocks']))

    def test_only_exact_trailing_wire_dump_is_removed_without_touching_source_refs(self):
        from pdf_k123_contract import remove_wire_annotations
        keys=list('abcdef');tail='['+','.join(keys)+']'
        request={'aliases':{k:'source-'+k for k in keys},'job':{'blocks':[{'text':'실제 원문'}]}}
        def reply(text,refs=keys):return {'concepts':[{'segments':[{'text':text,'blockIds':refs}]}]}
        original=reply('실제 설명이에요. '+tail)
        value,audit=remove_wire_annotations(original,request)
        self.assertEqual(value['concepts'][0]['segments'][0]['text'],'실제 설명이에요.')
        self.assertEqual(value['concepts'][0]['segments'][0]['blockIds'],keys)
        self.assertEqual(original['concepts'][0]['segments'][0]['text'],'실제 설명이에요. '+tail)
        self.assertEqual(len(audit),1)
        for text,refs in [('구간 [a,b]',list('ab')),('수식 \\('+tail+'\\)',keys),
                          ('```\n'+tail+'\n```',keys),('목록 '+tail,list('abcde'))]:
            before=reply(text,refs);value,audit=remove_wire_annotations(before,request)
            self.assertEqual(value,before);self.assertEqual(audit,[])
        request['job']['blocks'][0]['text']='원문에도 '+tail
        self.assertEqual(remove_wire_annotations(original,request),(original,[]))

    def test_context_budget_and_concurrency_do_not_change_transport_packing(self):
        self.assertEqual(engine.STRATEGIES,('newest-k1-2-6',))
        self.assertEqual(engine.MAX_STUDY_WORKERS,80)
        self.assertEqual(engine.TRANSPORT_BATCH_UNITS,1)
        self.assertEqual(engine.SINGLE_REQUEST_IMAGES,16)
        self.assertEqual(len(engine.compact_description('한글 설명 '*30)),40)
        jobs=[{'blocks':[{'id':str(i)}]}for i in range(3)]
        with patch.object(engine,'WORKERS',1):one=engine.transport_batches([0,1,2],jobs)
        with patch.object(engine,'WORKERS',80):many=engine.transport_batches([0,1,2],jobs)
        self.assertEqual(one,many)


class ImageStorage(unittest.TestCase):
    def test_equal_png_and_transport_bytes_use_one_inode_without_changing_bytes(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp)/'generated/newest-k1-2-6/run'
            data=b'exact reusable image bytes'
            paths=[root/'crops/x.png',root/'crop-encoding-cache/y.png',root/'transport-cache/.encoded-blobs/z.bin']
            for p in paths:write_shared(p,data)
            self.assertTrue(all(p.read_bytes()==data for p in paths))
            self.assertEqual(len({(p.stat().st_dev,p.stat().st_ino)for p in paths}),1)
            write_shared(paths[0],b'new encoding')
            self.assertEqual(paths[1].read_bytes(),data)
            self.assertEqual(paths[0].read_bytes(),b'new encoding')

    def test_hardlink_unavailable_still_writes_exact_original_bytes(self):
        with tempfile.TemporaryDirectory()as tmp,patch('pdf_k123_shared_images.os.link',side_effect=OSError('unsupported')):
            p=Path(tmp)/'crop-encoding-cache/x.png';write_shared(p,b'unchanged')
            self.assertEqual(p.read_bytes(),b'unchanged')

    def test_raised_or_subscripted_math_is_not_flattened_to_plain_prose(self):
        self.assertEqual(normalized('통화 𝑴 와 𝟏 억'),'통화 M 와 1 억')
        self.assertIsNone(normalized('x²'))
        self.assertIsNone(normalized('x₁'))


if __name__=='__main__':unittest.main()
