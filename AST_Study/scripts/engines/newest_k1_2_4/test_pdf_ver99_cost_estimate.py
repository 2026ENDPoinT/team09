"""Offline tests for ver.99 historical cost selection and cache-aware prediction."""
import json
import tempfile
import unittest
from pathlib import Path
from pdf_ver99_cost_estimate import samples, estimate, workload


def document(count=10, chars=500):
    return {'documentId':'fixture', 'pages':[{'nativeText':'x'*chars} for _ in range(count)]}


class CostEstimateTests(unittest.TestCase):
    def sample(self):
        return {'workload':workload(document(),list(range(1,11))),
                'stageUsage':{'region_plan':{'usageBasedUsd':.002},'region_study':{'usageBasedUsd':.018,'requests':10},
                              'summary_reduce':{'usageBasedUsd':.0002}},'documentId':'other','pages':10,'charsPerPage':500,'sparseFraction':0,
                'planUsd':.002,'studyUsd':.018,'outlineUsd':.0002,'usd':.0202,
                'inputTokens':10000,'outputTokens':5000}

    def test_same_features_reproduce_cost_not_budget_floor(self):
        prediction=estimate(document(),list(range(1,11)),[self.sample()])
        self.assertAlmostEqual(prediction['usd'],.0202)
        self.assertLessEqual(prediction['lowUsd'],prediction['usd'])
        self.assertGreaterEqual(prediction['highUsd'],prediction['usd'])

    def test_partial_cache_removes_planning_and_paid_study(self):
        prediction=estimate(document(),list(range(1,11)),[self.sample()],plan_cached=True,study_remaining=.25)
        self.assertAlmostEqual(prediction['usd'],.0047)
        self.assertEqual(estimate(document(0),[],[])['usd'],0)

    def test_no_samples_is_disclosed_fallback(self):
        prediction=estimate(document(),list(range(1,11)),[])
        self.assertEqual(prediction['sampleCount'],0)
        self.assertGreater(prediction['highUsd'],prediction['usd'])
        self.assertGreater(prediction['tokens'],0)

    def test_image_geometry_changes_price_at_same_page_and_text_count(self):
        def block(box):
            return {'id':'b','page':1,'text':'definition '*50,'kind':'text',
                    'bbox':box,'visualOnly':False,'hasVisual':False}
        doc=document(1)
        small=workload(doc,[1],blocks=[block([.1,.1,.4,.2])])
        full=workload(doc,[1],blocks=[block([0,0,1,1])])
        self.assertGreater(full['details']['imageTokenProxy'],small['details']['imageTokenProxy'])
        self.assertGreater(estimate(doc,[1],[],work=full)['usd'],estimate(doc,[1],[],work=small)['usd'])

    def test_text_and_request_overhead_are_counted_without_history(self):
        sparse=estimate(document(10,20),list(range(1,11)),[])
        dense=estimate(document(10,4000),list(range(1,11)),[])
        self.assertGreater(dense['usd'],sparse['usd'])
        self.assertGreater(sparse['workload']['cropImages'],0)
        self.assertGreater(sparse['stageUsd']['region_study'],0)

    def test_pending_jobs_are_sized_individually(self):
        doc=document(2)
        blocks=[{'id':str(i),'page':i,'text':'text '*100,'kind':'text','visualOnly':False,
                 'bbox':box} for i,box in [(1,[.1,.1,.3,.2]),(2,[0,0,1,1])]]
        jobs=[{'title':'topic','blocks':[b]} for b in blocks]
        work=workload(doc,[1,2],blocks=blocks,jobs=jobs)
        small=workload(doc,[1,2],blocks=blocks,jobs=jobs[:1])
        large=workload(doc,[1,2],blocks=blocks,jobs=jobs[1:])
        psmall=estimate(doc,[1,2],[],work=work,pending_work=small,plan_cached=True)
        plarge=estimate(doc,[1,2],[],work=work,pending_work=large,plan_cached=True)
        self.assertGreater(plarge['usd'],psmall['usd'])
        empty=workload(doc,[1,2],blocks=blocks,jobs=[])
        done=estimate(doc,[1,2],[self.sample() for _ in range(3)],work=work,pending_work=empty,plan_cached=True,outline_cached=True)
        self.assertEqual(done['usd'],0)
        self.assertEqual(done['tokens'],0)

    def test_scan_still_has_vision_cost_without_text_planning(self):
        work=workload(document(2,0),[1,2])
        self.assertEqual(work['region_plan']['calls'],0)
        self.assertEqual(work['region_study']['calls'],2)
        self.assertGreater(work['details']['imageTokenProxy'],0)

    def test_completed_result_requires_no_layout_or_history(self):
        from unittest.mock import patch
        import pdf_new_concept_ver99_study as engine
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'result.json').write_text(json.dumps({'processingComplete':True}))
            with patch.object(engine,'root_path',return_value=root), patch.object(engine,'extract',side_effect=AssertionError('no extraction')):
                result=engine.reading_plan(root,document(),scope='document')
            self.assertEqual(result['costEstimateUsd'],0)
            self.assertEqual(result['estimatedTotalTokens'],0)

    def test_calibration_keeps_visual_cost_positive_with_sparse_history(self):
        from pdf_ver99_cost_estimate import fit_study
        history=[self.sample() for _ in range(3)]
        fit=fit_study(history,(.1,.5))
        self.assertTrue(all(value>=.05 for value in fit))
        self.assertIsNone(fit_study(history[:2],(.1,.5)))

    def test_reading_plan_uses_local_layout_without_remote_call(self):
        from unittest.mock import patch
        import pdf_new_concept_ver99_study as engine
        doc=document(1)
        block={'id':'b','page':1,'text':'개념 설명','kind':'text','bbox':[0,0,1,1],
               'visualOnly':False,'hasVisual':False}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(engine,'root_path',return_value=root), patch.object(engine,'extract',return_value=[block]) as extraction:
                result=engine.reading_plan(root,doc,scope='document')
            extraction.assert_called_once_with(root,doc,[1])
            self.assertEqual(result['estimateWorkload']['fragments'],1)
            self.assertEqual(result['estimateWorkload']['cropImages'],1)
            self.assertGreater(result['costEstimateUsd'],0)
            self.assertEqual(list(root.iterdir()),[])

    def test_source_density_is_not_shrunk_with_prompt_overhead(self):
        from pdf_ver99_cost_estimate import fit_study, study_components
        # Independent synthetic workloads with known, different coefficients.
        # This checks identifiability and direction, not this repository's PDFs.
        history=[]
        for index,(image,source,overhead) in enumerate([(2000,500,10000),(9000,500,5000),
                                                       (3000,8000,5000),(4000,4000,20000),
                                                       (15000,2000,5000)]):
            work={'details':{'imageTokenProxy':image,'effectiveImageTokenProxy':image,
                             'sourceTokenProxy':source},
                  'region_study':{'input':image+source+overhead,'output':source*1.1}}
            components=study_components(work,(.1,.5))
            cost=sum(a*b for a,b in zip(components,(.8,1.2,.25)))
            history.append({'documentId':str(index),'workload':work,
                            'stageUsage':{'region_study':{'usageBasedUsd':cost}}})
        coefficients=fit_study(history,(.1,.5))
        self.assertEqual(len(coefficients),3)
        self.assertGreater(coefficients[1],coefficients[2]*2)
        for sample in history:
            actual=sample['stageUsage']['region_study']['usageBasedUsd']
            predicted=sum(a*b for a,b in zip(coefficients,study_components(sample['workload'],(.1,.5))))
            self.assertLess(abs(predicted/actual-1),.15)

    def test_saturated_image_feature_preserves_uncapped_reservation_proxy(self):
        doc=document(1)
        block={'id':'a','page':1,'text':'source','bbox':[0,0,1,1],
               'kind':'text','visualOnly':False,'hasVisual':False}
        w=workload(doc,[1],blocks=[block])
        self.assertGreater(w['details']['imageTokenProxy'],w['details']['effectiveImageTokenProxy'])
        self.assertGreater(w['region_study']['input'],w['details']['imageTokenProxy'])
        self.assertGreater(w['details']['effectiveImageTokenProxy'],0)

    def test_cached_plan_uses_actual_job_calibration_not_cold_proxy(self):
        import copy
        base=workload(document(),list(range(1,11)))
        planned=copy.deepcopy(base);planned['details']['grouping']='cached_plan'
        cold=copy.deepcopy(base)
        for key in ('input','output'):cold['region_study'][key]*=4
        for key in ('imageTokenProxy','effectiveImageTokenProxy','sourceTokenProxy'):cold['details'][key]*=4
        stages={kind:{'usageBasedUsd':(base[kind]['input']*.1+base[kind]['output']*.5)/1_000_000}
                for kind in ('region_plan','region_study','summary_reduce')}
        from pdf_ver99_cost_estimate import study_components
        stages['region_study']['usageBasedUsd']=sum(study_components(planned,(.1,.5)))
        history=[{'documentId':str(i),'workload':cold,'plannedWorkload':planned,'stageUsage':stages}
                 for i in range(3)]
        prediction=estimate(document(),list(range(1,11)),history,work=base,pending_work=planned,plan_cached=True)
        expected=stages['region_study']['usageBasedUsd']+stages['summary_reduce']['usageBasedUsd']
        self.assertAlmostEqual(prediction['usd'],expected,places=7)

    def test_audit_excludes_target_document_from_all_calibration(self):
        import types
        from audit_pdf_cost_estimate import replay
        from unittest.mock import patch
        history=[{**self.sample(),'documentId':str(i)} for i in range(3)]
        seen=[]
        def predict(doc,targets,others):
            self.assertNotIn(doc['documentId'],[s['documentId'] for s in others])
            seen.append(doc['documentId'])
            return {'usd':.02,'lowUsd':.01,'highUsd':.03}
        def read_doc(path):return {**document(),'documentId':path.parent.name}
        with patch('audit_pdf_cost_estimate.current.read',side_effect=read_doc):
            replay(Path('/fixture'),history,types.SimpleNamespace(estimate=predict))
        self.assertEqual(seen,['0','1','2'])

    def test_planned_audit_excludes_target_and_scores_remaining_separately(self):
        import copy
        from unittest.mock import patch
        from audit_pdf_cost_estimate import compare_planned
        history=[]
        for i in range(3):
            sample={**self.sample(),'documentId':str(i)}
            sample['plannedWorkload']=copy.deepcopy(sample['workload'])
            sample['plannedWorkload']['details']['grouping']='cached_plan'
            history.append(sample)
        seen=[]
        def predict(doc,targets,others,**kwargs):
            self.assertNotIn(doc['documentId'],[s['documentId'] for s in others])
            confirmed=kwargs.get('plan_cached',False)
            if confirmed:
                self.assertEqual(kwargs['pending_work']['details']['grouping'],'cached_plan')
            seen.append(confirmed)
            return {'usd':.018 if confirmed else .02,
                    'stageUsd':{'region_plan':0 if confirmed else .002,'region_study':.017,'summary_reduce':.001}}
        def read_doc(path):return {**document(),'documentId':path.parent.name}
        with patch('audit_pdf_cost_estimate.current.read',side_effect=read_doc), patch('audit_pdf_cost_estimate.current.estimate',side_effect=predict):
            report=compare_planned(Path('/fixture'),history)
        self.assertEqual(report['sampleCount'],3)
        self.assertEqual(seen,[False,True]*3)
        row=report['rows'][0]
        self.assertAlmostEqual(row['actualRemainingUsd'],.0182)
        self.assertAlmostEqual(row['afterRemainingUsd'],.018)
        self.assertAlmostEqual(row['afterTotalUsd'],.020)
        self.assertNotEqual(row['afterTotalErrorPercent'],row['afterRemainingErrorPercent'])

    def test_planned_audit_rejects_missing_or_reused_paid_jobs(self):
        from audit_pdf_cost_estimate import compare_planned
        sample=self.sample()
        missing=compare_planned(Path('/fixture'),[sample])
        self.assertEqual(missing['sampleCount'],0)
        self.assertEqual(len(missing['excluded']),1)
        sample['plannedWorkload']={**sample['workload'],'region_study':{'calls':99}}
        reused=compare_planned(Path('/fixture'),[sample])
        self.assertEqual(reused['sampleCount'],0)
        self.assertEqual(len(reused['excluded']),1)

    def test_history_filters_legacy_empty_unknown_and_resumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,changes in [('good',{}),('legacy',{'strategy':'new-concept-v02'}),
                                 ('empty',{'sections':[]}),('unknown',{'runUsage':{'unknownUsageRequests':1}}),
                                 ('resumed',{'metrics':{'newStudyJobs':3}})]:
                folder=root/name;result_path=folder/'generated/new-concept-v99/hash/result.json'
                result_path.parent.mkdir(parents=True)
                (folder/'document.json').write_text(json.dumps({**document(),'documentId':name}))
                result={'strategy':'new-concept-v99','model':'model','promptVersion':'version',
                        'processingComplete':True,'scope':'document','sections':[{}],'concepts':[{}],
                        'metrics':{'newStudyJobs':4},'runUsage':{'usageBasedUsd':.02,'unknownUsageRequests':0,
                        'inputTokens':100,'outputTokens':10,'byKind':{'region_plan':{'requests':1,'usageBasedUsd':.001},
                        'region_study':{'requests':4,'usageBasedUsd':.019}}}}
                result.update(changes);result_path.write_text(json.dumps(result))
            found=samples(root,'model','version')
            self.assertEqual([s['documentId'] for s in found],['good'])
            self.assertEqual(samples(root,'model','version','good'),[])
            self.assertEqual(samples(root,'different','version'),[])

if __name__=='__main__':unittest.main()
