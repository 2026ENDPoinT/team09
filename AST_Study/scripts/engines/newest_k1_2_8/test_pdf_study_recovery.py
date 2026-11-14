"""Source identity, visible page edges and partial teaching recovery regressions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
from pdf_new_concept_v02_regions import visible_word_box
from pdf_study_cache_reuse import repair_source_ids,constrained_format,reuse_plan,reusable_reply


def block(identity='v2p8f3', text='확실한 원리', box=None):
    return {'id':identity,'page':1,'zone':0,'kind':'text','text':text,
            'bbox':box or [.1,.2,.8,.4],'planRole':'teaching','hasVisual':False}


def reply(ids):
    return {'concepts':[{'title':'원리','definition':'확실한 정의예요.',
            'explanation':'확실한 설명이에요.','easyExplanation':'쉬운 설명이에요.',
            'blockIds':ids,'standardKnowledgeUsed':False}],
            'uncertainBlocks':[],'excludedBlocks':[],'sequences':[],'tables':[]}


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False))


class RecoveryTests(unittest.TestCase):
    def test_visible_edge_text_is_clipped_instead_of_dropped(self):
        self.assertEqual(visible_word_box([.1,.963,.2,1.0003]),[.1,.963,.2,1.])
        self.assertEqual(visible_word_box([-.001,-.001,.2,.1]),[0.,0.,.2,.1])
        for box in [[.1,1.01,.2,1.02],[.5,.2,.1,.4],[0,0,float('nan'),1],[1.1,0,1.2,.2]]:
            self.assertIsNone(visible_word_box(box))

    def test_only_unique_omitted_letter_is_recovered(self):
        raw=reply(['v2p83']);value=repair_source_ids(raw,['v2p8f3'])
        self.assertEqual(value['concepts'][0]['blockIds'],['v2p8f3'])
        self.assertEqual(raw['concepts'][0]['blockIds'],['v2p83'])
        for unknown in ['v2p8f9','v2p8f33','v2p3f8']:
            self.assertEqual(repair_source_ids(reply([unknown]),['v2p8f3'])['concepts'][0]['blockIds'],[unknown])
        ambiguous=repair_source_ids(reply(['v2p568']),['v2p56f8','v2p5f68'])
        self.assertEqual(ambiguous['concepts'][0]['blockIds'],['v2p568'])

    def test_unknown_numeric_id_still_fails_instead_of_fabricating_a_source(self):
        job={'id':'unit','title':'원리','blocks':[block()]}
        doc={'documentId':'doc','pages':[{'label':'1'}]}
        with self.assertRaisesRegex(ValueError,'v2p8f9'):
            study.validate(reply(['v2p8f9']),job,doc)

    def test_request_enum_constrains_every_reference_and_leaves_template_unchanged(self):
        fmt=constrained_format(study.STUDY_FORMAT,{'blocks':[block()]})
        paths=[]
        def walk(node):
            if isinstance(node,dict):
                for name,item in node.get('properties',{}).items():
                    if name=='blockId':paths.append(item['$ref'])
                    if name=='blockIds':paths.append(item['items']['$ref'])
                for item in node.values():walk(item)
            elif isinstance(node,list):
                for item in node:walk(item)
        walk(fmt)
        self.assertGreaterEqual(len(paths),5)
        self.assertTrue(all(x=='#/$defs/studySourceId' for x in paths))
        self.assertEqual(fmt['json_schema']['schema']['$defs']['studySourceId']['enum'],['v2p8f3'])
        self.assertNotIn('enum',study.STUDY_FORMAT['json_schema']['schema']['properties']['concepts']['items']['properties']['segments']['items']['properties']['blockIds']['items'])
        schema=fmt['json_schema']['schema']['properties']
        table=schema['tables']['items']['properties']
        self.assertEqual(table['headers']['items'],{'type':'string'})
        self.assertEqual(table['rows']['items']['items'],{'type':'string'})
        setup=schema['concepts']['items']['properties']['sourceSetup']['properties']
        self.assertEqual(setup['observedRelations']['items'],{'type':'string'})
        self.assertEqual(setup['boundaryChecks']['items'],{'type':'string'})

    def test_uncertain_paragraph_does_not_discard_supported_concept(self):
        good,bad=block('v2p8f3'),block('v2p8f4','불명확한 비교',[.1,.5,.8,.7])
        entry={'title':'원리','segments':[
            {'kind':'definition','text':'확실한 정의예요.','blockIds':[good['id']]},
            {'kind':'explanation','text':'확실한 관계를 설명해요.','blockIds':[good['id']]},
            {'kind':'explanation','text':'확인하지 못한 수치가 99배예요.','blockIds':[bad['id']]},
            {'kind':'easyExplanation','text':'쉬운 예를 생각해 봐요.','blockIds':[good['id']]}],
            'standardKnowledgeUsed':False}
        raw={'concepts':[entry],'uncertainBlocks':[{'blockId':bad['id'],'reason':'측정 조건 확인 필요'}]}
        v=study.validate(raw,{'id':'u','title':'원리','blocks':[good,bad]},
                         {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(len(v['concepts']),1)
        self.assertNotIn('99배',v['summary']['body'])
        self.assertIn('확실한 관계',v['summary']['body'])
        self.assertEqual([e['sourceId'] for e in v['summary']['evidence']],[good['id']])
        self.assertEqual({e['blockId']:e['state'] for e in v['coverage']},
                         {good['id']:'summarized',bad['id']:'needs_review'})
        self.assertEqual(len(raw['concepts'][0]['segments']),4)

    def test_invalid_numeric_paragraph_isolated_from_other_supported_paragraphs(self):
        good,bad=block(),block('v2p8f4','수치',[.1,.5,.8,.7])
        raw={'concepts':[{'title':'원리','segments':[
            {'kind':kind,'text':'확실한 설명이에요.','blockIds':[good['id']]}
            for kind in ['definition','explanation','easyExplanation']] +
            [{'kind':'explanation','text':r'\(2+2=5\)예요.','blockIds':[bad['id']]}]}]}
        value=study.validate(raw,{'id':'u','title':'원리','blocks':[good,bad]},
                             {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(len(value['concepts']),1)
        self.assertNotIn('2+2=5',value['summary']['body'])
        self.assertEqual(value['coverage'][1]['state'],'needs_review')

    def test_uncertain_claim_in_same_region_keeps_other_supported_paragraphs(self):
        b=block();entry={'title':'원리','segments':[
            {'kind':kind,'text':'확실한 설명이에요.','blockIds':[b['id']]}
            for kind in ['definition','explanation','easyExplanation']] +
            [{'kind':'uncertain','text':'그림의 마지막 수치는 읽을 수 없어요.','blockIds':[b['id']]}]}
        value=study.validate({'concepts':[entry]},{'id':'u','title':'원리','blocks':[b]},
                             {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(len(value['concepts']),1)
        self.assertNotIn('마지막 수치',value['summary']['body'])
        self.assertEqual(value['coverage'][0]['state'],'needs_review')
        entry['segments'][-1]={'kind':'explanation','text':r'\(2+2=5\)예요.','blockIds':[b['id']]}
        value=study.validate({'concepts':[entry]},{'id':'u','title':'원리','blocks':[b]},
                             {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(len(value['concepts']),1)
        self.assertNotIn('2+2=5',value['summary']['body'])
        self.assertEqual(value['coverage'][0]['state'],'needs_review')

    def seed(self,folder):
        root=folder/'generated/new-concept-v99/old';b=block()
        job={'id':'oldjob','title':'원리','blocks':[b]}
        save(root/'manifest.json',{'jobs':[job],'teachingIdentity':study.teaching_identity()})
        save(root/'blocks.json',[b])
        save(root/'plan.json',study.plan_record([{'title':'원리','blocks':[b]}],[],'gpt-6-luna'))
        save(root/'partial.json',{'documentId':'doc','sourceFingerprint':'fp','scope':'document',
                                  'page':0,'strategy':'new-concept-v99'})
        save(root/'response-oldjob.json',reply(['v2p83']))
        return root,b,job

    def test_reuse_maps_actual_regions_not_positional_ids_and_excludes_changed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,b,job=self.seed(Path(tmp));new={**b,'id':'v2p8f12'}
            value,meta=reusable_reply(root,[job],{'blocks':[new]})
            self.assertEqual(value['concepts'][0]['blockIds'],['v2p8f12'])
            self.assertEqual(len(meta['sourceIdRepairs']),1)
            self.assertIsNone(reusable_reply(root,[job],{'blocks':[{**new,'text':'다른 내용'}]})[0])
            self.assertEqual(json.loads((root/'response-oldjob.json').read_text())['concepts'][0]['blockIds'],['v2p83'])

    def test_only_new_visible_edge_text_can_reuse_a_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);root,b,_=self.seed(folder);cache=folder/'generated/new-concept-v99/new'
            doc={'documentId':'doc','fingerprint':'fp'}
            edge={**block('v2p8f4','하단 라벨',[.1,.96,.2,1.]),'pageEdgeClipped':True}
            plan,_=reuse_plan(folder,cache,doc,'new-concept-v99','document',0,[b,edge])
            self.assertEqual(plan['addedEdgeBlockIds'],[edge['id']])
            self.assertEqual(len(plan['groups'][0]['blocks']),2)
            ordinary={k:v for k,v in edge.items() if k!='pageEdgeClipped'}
            self.assertIsNone(reuse_plan(folder,cache,doc,'new-concept-v99','document',0,[b,ordinary])[0])
            self.assertIsNone(reuse_plan(folder,cache,{**doc,'fingerprint':'changed'},'new-concept-v99','document',0,[b])[0])

    def test_planner_identity_and_failure_state_control_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);root,b,_=self.seed(folder);cache=folder/'generated/new-concept-v99/new'
            doc={'documentId':'doc','fingerprint':'fp'}
            args=(folder,cache,doc,'new-concept-v99','document',0,[b])
            self.assertIsNotNone(reuse_plan(*args,planner_identity=study.planner_identity())[0])
            self.assertIsNone(reuse_plan(*args,planner_identity='different planner')[0])
            plan=json.loads((root/'plan.json').read_text())
            plan['warnings']=[{'stage':'plan','error':'AiResponseError'}];save(root/'plan.json',plan)
            self.assertIsNone(reuse_plan(*args,planner_identity=study.planner_identity())[0])

    def test_changed_teaching_prompt_does_not_reuse_old_generated_prose(self):
        class StopAfterPlan:
            model='gpt-6-luna';context={};ledger={'requests':[]}
            def complete(self,*a,**k):raise AssertionError('No network in this fixture')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);root,b,_=self.seed(folder)
            manifest=json.loads((root/'manifest.json').read_text());manifest['teachingIdentity']='old teaching rules'
            save(root/'manifest.json',manifest)
            doc={'documentId':'doc','fingerprint':'fp','pages':[{'label':'1'}],'chunks':[]}
            with patch.object(study,'extract',return_value=[b]),patch.object(study,'render_crops',side_effect=RuntimeError('stop before image transport')):
                value=study.generate(folder,doc,StopAfterPlan())
            self.assertEqual(value['kind'],'partial')
            self.assertEqual(value['cacheReuse']['replies'],[])

    def test_generation_reuses_paid_reply_and_repairs_id_without_provider_call(self):
        class NoCalls:
            model='gpt-6-luna';context={};ledger={'requests':[]}
            def complete(self,*a,**k):raise AssertionError('No new model call expected')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);_,b,_=self.seed(folder)
            doc={'documentId':'doc','fingerprint':'fp','pages':[{'label':'1'}],'chunks':[]}
            with patch.object(study,'extract',return_value=[b]),patch('pdf_outline.overview',return_value={'body':'원리'}):
                value=study.generate(folder,doc,NoCalls())
            self.assertEqual(value['kind'],'ai_generated')
            self.assertTrue(value['coverageComplete'])
            self.assertEqual(len(value['cacheReuse']['replies']),1)
            self.assertEqual(value['cacheReuse']['sourceIdRepairs'][0]['to'],'v2p8f3')

    def test_planning_admission_estimate_reuses_completed_sources_without_planner(self):
        class NoCalls:
            model='gpt-6-luna';billing=None;ledger={'requests':[]}
            def complete(self,*a,**k):raise AssertionError('No new grouping call expected')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);_,b,_=self.seed(folder)
            doc={'documentId':'doc','fingerprint':'fp','pages':[
                {'number':1,'label':'1','nativeText':'확실한 원리','width':600,'height':800}],'chunks':[]}
            with patch.object(study,'extract',return_value=[b]):
                value=study.prepare_group_plan(folder,doc,NoCalls())
            self.assertTrue(value['groupingConfirmed'])
            self.assertEqual(value['estimateStageUsd']['region_plan'],0)
            self.assertEqual(value['estimateStageUsd']['region_study'],0)

    def test_reused_outline_rebinds_current_sources_without_model_call(self):
        from pdf_outline import overview
        class NoCalls:
            calls=0
            def complete(self,*a,**k):
                self.calls+=1;raise AssertionError('No outline call expected')
        with tempfile.TemporaryDirectory() as tmp:
            old,new=Path(tmp)/'old',Path(tmp)/'new'
            old.mkdir();new.mkdir();provider=NoCalls()
            def sections(identity):
                return [{'title':'원리','parts':[{'title':'개념'}],
                         'evidence':[{'sourceId':identity,'page':1,'quote':'원리'}],'visualPages':[1]}]
            first=overview(provider,old,sections('old'),local_only=True)
            second=overview(provider,new,sections('new'),reuse_from=old)
            self.assertEqual(first['body'],second['body'])
            self.assertEqual(second['evidence'][0]['sourceId'],'new')
            self.assertEqual(second['overviewMethod'],'headings_cache_rebound')
            self.assertEqual(provider.calls,0)


if __name__=='__main__':unittest.main()
