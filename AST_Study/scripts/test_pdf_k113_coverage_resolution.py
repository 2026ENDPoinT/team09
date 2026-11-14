"""Coverage is earned by retained teaching, never by a blanket warning waiver."""
import copy
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pdf_newest_k1_1_3 as engine
from pdf_k113_coverage import complete, disposition, feedback
from pdf_k113_math import restore
from pdf_k113_saved import index, reply
from pdf_pipeline import write_json
from pdf_source_aliases import decode, SourceAliasError
from test_pdf_newest_k1_1_3 import block, response


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.a={**block(0),'id':'a'}
        self.b={**block(0),'id':'b','bbox':[.1,.78,.9,.95],
                'text':'충분히 큰 항부터 비율이 r보다 커지므로 항이 0으로 가지 않는다.',
                'hasVisual':True}
        self.job={'id':'j','title':'관계','blocks':[self.a,self.b]}
        self.doc={'documentId':'doc','pages':[{'label':'1'}]}
        self.quote='충분히 큰 항부터 비율이 일정한 수보다 커지므로 항이 0으로 가지 않아요.'
        self.raw=response('a')
        self.raw['concepts'][0]['segments'][1]['text']=self.quote
        self.raw['sourceCoverage']=[{'blockId':'a','conceptTitle':'조건의 비교','quote':'조건을 비교하는 방법이에요.'},
            {'blockId':'b','conceptTitle':'조건의 비교','quote':self.quote}]

    def validate(self,raw):return engine.validate(raw,self.job,self.doc)
    def states(self,raw):return {c['blockId']:c['state']for c in self.validate(raw)['coverage']}

    def test_source_index_requires_the_actual_retained_proof_or_condition(self):
        self.assertEqual(self.states(self.raw)['b'],'summarized')
        value=self.validate(self.raw)
        for content in (value['concepts'][0],value['summary']['parts'][0]):
            self.assertIn('b',[e['sourceId']for e in content['evidence']])
        for text in ('조건이 달라지는 경우를 비교해요.', '더하면\n이에요.'):
            changed=copy.deepcopy(self.raw);changed['concepts'][0]['segments'][1]['text']=text
            self.assertEqual(self.states(changed)['b'],'needs_review')
        wrong=copy.deepcopy(self.raw);wrong['sourceCoverage'][1]['conceptTitle']='다른 개념'
        self.assertEqual(self.states(wrong)['b'],'needs_review')

    def test_explicit_uncertainty_cannot_be_cleared_by_the_index(self):
        self.raw['uncertainBlocks']=[{'blockId':'b','reason':'핵심 조건을 판독하지 못했어요.'}]
        self.assertEqual(self.states(self.raw)['b'],'needs_review')

    def test_topic_hint_never_authorizes_omitting_an_owned_conclusion(self):
        self.raw.pop('sourceCoverage')
        self.raw['excludedBlocks']=[{'blockId':'b','reason':
            '앞선 발산 사례의 결론으로, 이 단위의 핵심인 다른 사례와 별개이므로 중복 설명하지 않아요.'}]
        self.assertEqual(self.states(self.raw)['b'],'needs_review')

    def test_index_cannot_reference_duplicate_or_foreign_sources(self):
        for key in ('a','foreign'):
            raw=copy.deepcopy(self.raw);raw['sourceCoverage'][1]['blockId']=key
            with self.assertRaises(ValueError):self.validate(raw)
        decoded=decode({'sourceCoverage':[{'blockId':'a','conceptTitle':'개념','quote':'abc'}]}, {'a':'real-source'})
        self.assertEqual(decoded['sourceCoverage'][0]['blockId'],'real-source')
        with self.assertRaises(SourceAliasError):decode({'sourceCoverage':[{'blockId':'unused'}]}, {'a':'real-source'})

    def test_short_continuation_survives_but_missing_independent_definition_does_not(self):
        self.job['blocks']=[self.a]
        raw=response('a');entry=raw['concepts'][0]
        entry['segments']=[{'kind':'explanation','text':'단, 이 경우에는 앞의 판정법을 적용할 수 없어요.','blockIds':['a']}]
        entry['sourceSetup'].update(teachingRole='continuation',sourceQuotes=['단, 판정법으로 증명할 수 없다.'])
        value=self.validate(raw)
        self.assertEqual(value['coverage'][0]['state'],'summarized')
        self.assertIn('적용할 수 없어요',value['summary']['parts'][0]['body'])
        entry['sourceSetup']['teachingRole']='independent'
        self.assertEqual(self.validate(raw)['coverage'][0]['state'],'needs_review')
        raw['concepts'].insert(0,response('a')['concepts'][0])
        self.assertEqual(self.validate(raw)['coverage'][0]['state'],'needs_review')

    def test_exclusions_must_preserve_the_concept_and_cannot_hide_a_new_condition(self):
        parts=[{'title':'기본 원리','body':'일반식과 적용 조건을 설명해요.'}]
        item={'reason':'반복 예시예요.','sourceDisposition':{'kind':'repeated_example',
            'observations':['같은 방법에 다른 숫자를 대입한 예제예요.'],
            'keptConceptTitle':'기본 원리','independentLearningPoint':''}}
        b={**self.b,'text':'예제 2. 수치를 대입해 구하라.'}
        self.assertIsNotNone(disposition(item,b,[b],parts))
        self.assertIsNone(disposition(item,b,[b],[]))
        item['sourceDisposition']['independentLearningPoint']='새로운 예외 조건'
        self.assertIsNone(disposition(item,b,[b],parts))
        item['sourceDisposition']['independentLearningPoint']=''
        self.assertIsNone(disposition(item,{**b,'text':'정의: 새로운 물리량'},[b],parts))
        item['sourceDisposition'].update(kind='structure',observations=['제목으로만 사용한 텍스트예요.'])
        self.assertIsNone(disposition(item,{**b,'text':'x = y + z'},[b],parts))
        item['sourceDisposition']['observations']=['좌표축과 그래프가 있는 장식이에요.']
        self.assertIsNone(disposition(item,{**b,'text':''},[b],parts))

    def test_missing_essential_material_is_not_an_optional_source_note(self):
        d={'kind':'unlabelled_supporting_figure','observations':['보조 그림의 차수 표기가 없어요.'],
           'keptConceptTitle':'근사 다항식','independentLearningPoint':''}
        item={'sourceDisposition':d,'reason':'원문에 차수가 없어요.'}
        parts=[{'title':'근사 다항식','body':'다항식의 근사 관계는 설명했어요.'}]
        self.assertIsNotNone(disposition(item,self.b,[self.b],parts))
        d['independentLearningPoint']='핵심 정리 전체의 수식이 판독되지 않아요.'
        self.assertIsNone(disposition(item,self.b,[self.b],parts))

    def test_math_envelopes_change_neither_symbols_nor_code(self):
        text='중력 위치 에너지는\n(U_g=mgy)\n이고 변화량을 비교해요.'
        self.assertIn(r'\(U_g=mgy\)',restore(text))
        self.assertEqual(restore(restore(text)),restore(text))
        for value in ('```cpp\nint x=2;\n```','`x=2`',r'\(x=2\)',
                      '식은\n(x=2+)\n이에요.','가격은 $12예요.'):
            self.assertEqual(restore(value),value)

    def test_bare_format_string_is_protected_from_math_and_escape_repairs(self):
        from pdf_k113_review import ReviewPolicy
        from pdf_new_concept_ver99_checks import prepare_learner_segment
        call=r'printf("%d %p\n", pooh, &pooh)'
        policy=ReviewPolicy([]);value=policy.prepare(call+'를 실행해요.',[])
        value=prepare_learner_segment(value)[0]
        self.assertIn('`'+call+'`',value)
        self.assertNotIn('%`',value)
        self.assertIn(r'\(W=F\cos\theta\)',restore(r'일은\n(W=F\cos\theta)\n예요.'))

    def test_request_completion_alone_is_never_coverage_completion(self):
        value={'processingComplete':True,'coverageComplete':False,'coverage':[{'state':'needs_review'}]}
        self.assertFalse(complete(value))
        value['coverageComplete']=True;self.assertFalse(complete(value))
        value['coverage']=[{'state':'context','sourceNote':{'kind':'source_conflict'}}]
        self.assertTrue(complete(value))
        feedback(self.job,self.raw,[{'blockId':'b','state':'needs_review','reason':'증명이 빠졌어요.'}])
        self.assertEqual(self.job['_reviewFeedback'][0]['page'],1)
        before=self.job['_reviewRevision'];changed=copy.deepcopy(self.raw);changed['concepts']=[]
        feedback(self.job,changed,[]);self.assertNotEqual(before,self.job['_reviewRevision'])


class SavedReplyTests(unittest.TestCase):
    def test_previous_reply_requires_exact_source_model_and_neighbor_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);old=folder/'generated/newest-k1-1-3/old';current=old.parent/'current'
            doc={'documentId':'d','fingerprint':'fp'};job={'id':'j','title':'주제','blocks':[block(0)],
                'unitContext':{'before':['앞 단락']},'contextDepth':1}
            value={'documentId':'d','sourceFingerprint':'fp','strategy':'newest-k1-1-3',
                'model':'gpt-6-luna','scope':'document','page':0}
            write_json(old/'partial.json',value);write_json(old/'manifest.json',{'jobs':[job]})
            write_json(old/'response-j.json',response(block(0)['id']))
            candidates=index(folder,doc,'newest-k1-1-3','gpt-6-luna','document',0,current)
            self.assertIsNotNone(reply(candidates,job)[0])
            for field,value in [('unitContext',{'before':['다른 단락']}),('blocks',[block(1)])]:
                self.assertIsNone(reply(candidates,{**job,field:value})[0])
            self.assertFalse(index(folder,{**doc,'fingerprint':'changed'},'newest-k1-1-3','gpt-6-luna','document',0,current))
            self.assertFalse(index(folder,doc,'newest-k1-1-3','other-model','document',0,current))

    def test_resume_revalidates_saved_units_and_calls_only_the_missing_unit(self):
        blocks=[block(i)for i in range(2)]
        groups=[{'title':f'주제 {i}','description':'조건 설명','blocks':[b]}for i,b in enumerate(blocks)]
        doc={'documentId':'d','fingerprint':'fp','pages':[{'number':b['page'],
             'label':str(b['page']),'nativeText':b['text']}for b in blocks]}
        calls=[]
        class Provider:
            model='gpt-6-luna';billing=None;ledger={'requests':[]};transport=object();context={}
            def complete(self,payload,**kw):
                return {'body':'조건을 살펴봐요.','topicIds':['k1','k2']}
        def completed(provider,payload,**kw):
            calls.append(payload)
            return response(payload['blocks'][0]['id'])
        with tempfile.TemporaryDirectory()as tmp,ExitStack()as s:
            s.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('offline')))
            for name,value in {'SOURCE_ID_ALIASES':False,'TRANSPORT_BATCH_UNITS':1,'TRANSPORT_BATCH_ALIASES':False}.items():
                s.enter_context(patch.object(engine,name,value))
            folder=Path(tmp);old=folder/'generated/newest-k1-1-3/previous'
            jobs=engine.jobs_for(groups)
            saved={'documentId':'d','sourceFingerprint':'fp','strategy':'newest-k1-1-3','scope':'document',
                'page':0,'model':'gpt-6-luna','processingComplete':True,'coverageComplete':False,'localOutputVersion':'old'}
            write_json(old/'result.json',saved);write_json(engine.latest_path(folder,'newest-k1-1-3','document',0),saved)
            write_json(old/'plan.json',engine.plan_record(groups,[],'gpt-6-luna',[],blocks=blocks))
            write_json(old/'blocks.json',blocks);write_json(old/'manifest.json',{'jobs':jobs})
            write_json(old/f'response-{jobs[0]["id"]}.json',response(blocks[0]['id']))
            write_json(old/f'response-{jobs[1]["id"]}.json',{'concepts':[],'excludedBlocks':[],'uncertainBlocks':[]})
            s.enter_context(patch.object(engine,'extract_layout',return_value=copy.deepcopy(blocks)))
            s.enter_context(patch.object(engine,'render_crops',return_value=([],[])))
            s.enter_context(patch.object(engine,'emit'))
            s.enter_context(patch('pdf_ai.complete_study_delivery',side_effect=completed))
            s.enter_context(patch('pdf_ai.run_usage',return_value={}))
            value=engine.generate(folder,doc,Provider())
            self.assertTrue(complete(value),value.get('failedUnits'))
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['blocks'][0]['id'],blocks[1]['id'])
            self.assertTrue(calls[0]['reviewFocus'])
            self.assertEqual(len(value['cacheReuse']['replies']),2)
            cached=engine.generate(folder,doc,Provider())
            self.assertTrue(cached['cacheHit']);self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
