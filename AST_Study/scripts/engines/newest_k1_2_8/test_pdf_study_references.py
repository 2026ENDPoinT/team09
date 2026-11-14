"""Offline role decisions: reference brevity must not erase teaching or evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
from pdf_study_references import (VERSION, OVERRIDE_FILE, content_hash,
                                  project_saved_references, RULES, CACHE_IDENTITY_RULES, identity_prompt)
from pdf_source_aliases import encode, decode
from pdf_study_batch_transport import encode as batch_encode, decode as batch_decode


def block(**changes):
    return {'id':'map','page':1,'kind':'page','text':'','bbox':[0.,0.,1.,1.],
            'hasVisual':True,'geometryFallback':True,'visualOnly':True,
            'planRole':'uncertain','visualReadingRequired':True,**changes}


def record(**changes):
    return {'blockId':'map','reason':'위치 관계를 보여 주는 참고 지도예요.',
            'referenceContext':{'kind':'location_map','observations':['한반도와 일본 열도가 나란히 표시되어 있어요.'],
                                'learningSignals':[],'readable':True},**changes}


def response(item=None):
    return {'concepts':[],'tables':[],'sequences':[],'uncertainBlocks':[],
            'excludedBlocks':[record() if item is None else item]}


DOCUMENT={'documentId':'doc','fingerprint':'fp','pages':[{'number':1,'label':'i'}]}


def validate(raw=None, source=None):
    source=block() if source is None else source
    return study.validate(response() if raw is None else raw,
                          {'id':'job','title':'강의','blocks':[source]},DOCUMENT)


def taught():
    return {'title':'인과관계와 상관관계','definition':'상관관계는 두 변수의 변화가 함께 나타나는 관계예요.',
            'explanation':'상관관계는 인과관계를 입증하지 않아요. 관찰한 관계와 그 원인을 구분해요.',
            'easyExplanation':'함께 변하는 두 대상을 보더라도 다른 조건이 원인일 수 있어요.',
            'blockIds':['map'],'standardKnowledgeUsed':False}


class ReferenceRoleTests(unittest.TestCase):
    def test_only_equivalent_compression_reuses_paid_teaching_identity(self):
        current=study.teaching_identity()
        full=study.STUDY_PROMPT[:-len(RULES)]+CACHE_IDENTITY_RULES
        with patch.object(study,'STUDY_PROMPT',full):
            self.assertEqual(study.teaching_identity(),current)
        with patch.object(study,'STUDY_PROMPT','A changed teaching rule.\n'+study.STUDY_PROMPT):
            self.assertNotEqual(study.teaching_identity(),current)
        changed=RULES+'A different policy.'
        with patch('pdf_study_references.RULES',changed):
            self.assertEqual(identity_prompt('base'+changed),'base'+changed)

    def test_navigation_guard_still_reads_image_once_before_context_decision(self):
        source=block(planRole='navigation')
        class Provider:
            model='gpt-6-luna';billing=None;ledger={'requests':[]}
            def __init__(self):self.calls=[]
            def complete(self,payload,**options):
                self.calls.append((payload,options))
                assert payload['task']=='region_teaching' and options.get('image')
                assert RULES in options['system_prompt'] and CACHE_IDENTITY_RULES not in options['system_prompt']
                return response(record(blockId=payload['blocks'][0]['id']))
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);provider=Provider()
            cache=study.root_path(folder,DOCUMENT,'new-concept-v99',provider.model,'document',0)
            cache.mkdir(parents=True)
            (cache/'plan.json').write_text(json.dumps(study.plan_record(
                [{'title':'강의','blocks':[copy.deepcopy(source)]}],[],provider.model)))
            with patch.object(study,'extract',return_value=[source]),\
                 patch.object(study,'render_crops',return_value=([{'data':'fixture'}],[{'page':1,'blockIds':['map']}])):
                value=study.generate(folder,DOCUMENT,provider)
            self.assertEqual(len(provider.calls),1)
            self.assertTrue(value['processingComplete']);self.assertTrue(value['coverageComplete'])
            self.assertEqual(value['coverage'][0]['state'],'context')
            self.assertEqual(value['sections'],[]);self.assertEqual(value['concepts'],[])
            self.assertEqual(value['referenceContexts'][0]['evidence'][0]['sourceId'],'map')

    def test_read_image_can_be_context_without_manufacturing_three_paragraphs(self):
        raw=response();before=copy.deepcopy(raw);value=validate(raw)
        self.assertEqual(value['summary']['parts'],[]);self.assertEqual(value['concepts'],[])
        coverage=value['coverage'][0]
        self.assertEqual(coverage['state'],'context')
        self.assertEqual(coverage['referenceContext']['observations'],raw['excludedBlocks'][0]['referenceContext']['observations'])
        self.assertEqual(coverage['evidence'][0]['sourceId'],'map')
        self.assertEqual(coverage['evidence'][0]['bbox'],[0.,0.,1.,1.])
        self.assertEqual(coverage['evidence'][0]['pageLabel'],'i')
        self.assertEqual(raw,before)

    def test_reference_is_accounted_for_in_complete_assembled_output(self):
        job={'id':'job','title':'강의','blocks':[block()]};unit=validate()
        value=study.assemble(DOCUMENT,'new-concept-v99','document',0,[1],[job],{0:unit},[],[],headings=[],all_blocks=[block()])
        self.assertTrue(value['coverageComplete']);self.assertTrue(value['processingComplete'])
        self.assertEqual(value['referenceContexts'][0]['evidence'][0]['sourceId'],'map')
        self.assertEqual(value['sections'],[]);self.assertEqual(value['concepts'],[])

    def test_learning_signals_uncertainty_and_topic_mismatch_cannot_use_reference_channel(self):
        for signal in ('definition','mechanism','quantitative_comparison','labelled_structure',
                       'code','reported_claim','historical_event','classification','interpretation_boundary'):
            item=record();item['referenceContext']['learningSignals']=[signal]
            self.assertEqual(validate(response(item))['coverage'][0]['state'],'needs_review',signal)
        for change in ('unreadable','unsupported_kind','empty_observations','missing_assessment','topic_only'):
            item=record()
            if change=='unreadable':item['referenceContext']['readable']=False
            elif change=='unsupported_kind':item['referenceContext']['kind']='anatomical_diagram'
            elif change=='empty_observations':item['referenceContext']['observations']=[]
            elif change=='missing_assessment':del item['referenceContext']['learningSignals']
            else:item['reason']='묶음의 주제와 무관한 그림이에요.'
            self.assertEqual(validate(response(item))['coverage'][0]['state'],'needs_review',change)

    def test_quantities_code_routes_claims_and_native_teaching_fail_closed(self):
        for text in ('일본의 값은 35%이고 한국은 25%예요.','신경 경로가 표시되어 있어요.',
                     '교역 경로가 연결되어 있어요.','역사적 전선이 표시되어 있어요.',
                     r'\(y=x^2\)','```cpp\nint *p[3];\n```','도시별 인구 분포를 보여 줘요.'):
            item=record();item['referenceContext']['observations']=[text]
            self.assertEqual(validate(response(item))['coverage'][0]['state'],'needs_review',text)
        self.assertEqual(validate(source=block(text='사회는 세 가지로 분류된다.'))['coverage'][0]['state'],'needs_review')

    def test_reference_never_removes_supported_teaching_or_interpretation_boundary(self):
        raw=response();raw['concepts']=[taught()]
        value=validate(raw)
        self.assertEqual(value['coverage'][0]['state'],'summarized')
        for field in ('definition','explanation','easyExplanation'):
            self.assertEqual(value['concepts'][0][field],taught()[field])
        self.assertEqual(value['concepts'][0]['evidence'][0]['sourceId'],'map')

    def test_unknown_source_and_plain_exclusion_do_not_bypass_visual_guard(self):
        with self.assertRaises(ValueError):validate(response(record(blockId='other')))
        for context in (None,):
            item=record(referenceContext=context)
            self.assertEqual(validate(response(item))['coverage'][0]['state'],'needs_review')
        item={'blockId':'map','reason':'일반적인 개념을 설명하지 않는 그림이에요.'}
        self.assertEqual(validate(response(item))['coverage'][0]['state'],'needs_review')

    def test_aliases_and_strict_batched_transport_preserve_context_evidence(self):
        job={'id':'job','title':'강의','blocks':[block()]}
        payload=study.teaching_payload(job,[{'page':1,'blockIds':['map']}],{'pageCount':1},[])
        wire,fmt,mapping=encode(payload,study.STUDY_FORMAT,job)
        raw=response(record(blockId=next(iter(mapping))))
        self.assertEqual(decode(raw,mapping)['excludedBlocks'][0],record())
        unit={'job':job,'payload':payload,'response_format':study.STUDY_FORMAT,'images':[{'data':'fixture'}]}
        other=copy.deepcopy(unit);other['job']['id']='other-job';other['job']['blocks'][0]['id']='other'
        other['payload']['blocks'][0]['id']='other';other['payload']['crops'][0]['blockIds']=['other']
        _,_,_,contract=batch_encode([unit,other],alias_pool_size='exact')
        wire={owner['name']:response(record(blockId=next(iter(owner['aliases']))))
              for owner in contract['units']}
        decoded=batch_decode(wire,contract)
        self.assertEqual(decoded[0]['excludedBlocks'][0],record())
        self.assertEqual(decoded[1]['excludedBlocks'][0]['blockId'],'other')


class SavedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        plain={'title':'지도상 위치','definition':'그림은 한반도와 일본 열도를 함께 표시한 지도예요.',
               'explanation':'두 지역 사이에 바다가 있고 주변 도시의 이름이 적혀 있어요.',
               'easyExplanation':'지도에서 두 지역이 어디에 있는지 볼 수 있어요.',
               'blockIds':['map'],'standardKnowledgeUsed':False}
        unit=validate({'concepts':[plain],'excludedBlocks':[],'uncertainBlocks':[]})
        part=unit['summary']['parts'][0];entry=unit['concepts'][0]
        self.result={'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99',
                     'model':'gpt-6-luna','scope':'document','page':0,'sections':[copy.deepcopy(unit['summary'])],
                     'concepts':[{'name':entry['name'],'entries':[copy.deepcopy(entry)],'pages':[1]}],
                     'coverage':copy.deepcopy(unit['coverage']),'hierarchy':{'version':'old'},'processingComplete':True}
        self.item={**record(),'sourceBlock':block(),'contentHash':content_hash(part,entry)}
        self.policy={'version':VERSION,'documentId':'doc','sourceFingerprint':'fp','items':[self.item]}
        (self.folder/'generated').mkdir();self.write()

    def write(self):
        (self.folder/'generated'/OVERRIDE_FILE).write_text(json.dumps(self.policy,ensure_ascii=False))

    def test_exact_approved_projection_keeps_canonical_and_paid_data_intact(self):
        original=copy.deepcopy(self.result);paid=self.folder/'paid.json';paid.write_text('original paid response')
        result=project_saved_references(self.folder,DOCUMENT,self.result)
        self.assertEqual(result['sections'],[]);self.assertEqual(result['concepts'],[])
        self.assertEqual(result['coverage'][0]['state'],'context')
        self.assertEqual(result['coverage'][0]['evidence'],original['concepts'][0]['entries'][0]['evidence'])
        self.assertEqual(self.result,original);self.assertEqual(paid.read_text(),'original paid response')
        self.assertEqual(project_saved_references(self.folder,DOCUMENT,result),result)
        (self.folder/'generated'/OVERRIDE_FILE).unlink()
        self.assertEqual(project_saved_references(self.folder,DOCUMENT,self.result),original)

    def test_saved_display_rebuild_does_not_resurrect_the_reference_concept(self):
        with patch.object(study,'save_display_hierarchy'),\
             patch.object(study,'display_source_headings',return_value=[]):
            value=study.display_saved(self.folder,DOCUMENT,self.result)
        self.assertEqual(value['sections'],[]);self.assertEqual(value['concepts'],[])
        self.assertEqual(value['coverage'][0]['state'],'context')
        self.assertEqual(value['referenceContexts'][0]['evidence'][0]['sourceId'],'map')
        self.assertEqual(value['hierarchy']['version'],study.hierarchy.VERSION)

    def test_edited_prose_source_evidence_partial_selection_and_uncertainty_are_preserved(self):
        for change in ('prose','source','evidence','extra_concept','multi_source','uncertainty','table'):
            result=copy.deepcopy(self.result)
            if change=='prose':result['sections'][0]['parts'][0]['body']+=' 새 설명'
            elif change=='source':result['sourceFingerprint']='new'
            elif change=='evidence':result['concepts'][0]['entries'][0]['evidence'][0]['bbox']=[.1,.1,.9,.9]
            elif change=='extra_concept':result['concepts'][0]['entries'].append(copy.deepcopy(result['concepts'][0]['entries'][0]))
            elif change=='multi_source':result['sections'][0]['parts'][0]['evidence'].append({'sourceId':'other'})
            elif change=='uncertainty':result['coverage'][0]['state']='needs_review'
            else:result['sections'][0]['parts'][0]['comparisonTable']={'rows':[['important']]}
            original=copy.deepcopy(result)
            self.assertEqual(project_saved_references(self.folder,DOCUMENT,result),original,change)

    def test_other_source_claims_in_same_section_are_not_removed(self):
        result=copy.deepcopy(self.result)
        other={'title':'중요한 개념','body':'원문의 중요한 개념과 조건이에요.','evidence':[{'sourceId':'other'}]}
        result['sections'][0]['parts'].append(copy.deepcopy(other));result['sections'][0]['body']+='\n\n'+other['body']
        result['concepts'][0]['entries'].append({'name':'다른 개념','evidence':[{'sourceId':'other'}]})
        value=project_saved_references(self.folder,DOCUMENT,result)
        self.assertEqual(value['sections'][0]['parts'],[other]);self.assertEqual(value['sections'][0]['body'],other['body'])
        self.assertEqual(value['concepts'][0]['entries'],[result['concepts'][0]['entries'][1]])

    def test_even_exact_overlay_cannot_hide_quantities_code_or_source_boundaries(self):
        for text in ('관측값은 35%예요.',r'\(y=x^2\)','```cpp\nint *p[3];\n```',
                     '상관관계는 인과관계를 입증하지 않아요.','신경 경로를 설명해요.'):
            value=copy.deepcopy(self.result);part=value['sections'][0]['parts'][0];entry=value['concepts'][0]['entries'][0]
            part['body']+=' '+text;value['sections'][0]['body']=part['body'];entry['explanation']+=' '+text
            self.policy['items'][0]['contentHash']=content_hash(part,entry);self.write()
            self.assertEqual(project_saved_references(self.folder,DOCUMENT,value),value,text)


if __name__=='__main__':unittest.main()
