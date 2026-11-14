import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audit_pdf_cost_report import build, collect_runs, pair_runs, render, request_timing


def entry(key='request', kind='region_study', payload='same'):
    return {'requestId':key,'state':'settled','kind':kind,'unitIds':['unit'] if kind=='region_study' else [],
        'payloadHash':payload,'reservedUsd':.02,'estimatedUsd':.0015,
        'usage':{'prompt_tokens':10000,'completion_tokens':1000,
                 'prompt_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}}}


def save(root,name,*,only_pages=None,complete=True,rows=None,run_record=True):
    folder=root/'runs'/name;folder.mkdir(parents=True)
    (folder/'usage').mkdir();(folder/'usage/ledger.json').write_text(json.dumps(
        {'model':'gpt-6-luna','requests':rows or [entry(name)]}))
    (folder/'document.json').write_text(json.dumps({'pages':[{},{}],'nativeText':'NEVER EXPOSE RAW SOURCE'}))
    cache=folder/'cache';cache.mkdir()
    if run_record:
        run={'variant':name,'workers':14,'sourceSha256':'same-source','planSha256':'same-plan',
            'processingComplete':complete,'coverageComplete':False,'onlyPages':only_pages,
            'cacheRoot':str(cache),'wallSeconds':20,'metrics':{'firstResultSeconds':8,'studyJobs':1},
            'detail':'NEVER EXPOSE RAW SOURCE'}
        (folder/'run.json').write_text(json.dumps(run))
    return folder,cache


def update_run(folder, **values):
    path=folder/'run.json';data=json.loads(path.read_text());data.update(values)
    path.write_text(json.dumps(data));return data


def approve_new_window(root):
    ids=[f'old-{i}' for i in range(554)]
    approval={'schemaVersion':1,'createdAtUtc':'2026-10-21T04:04:38+00:00',
        'authorization':'Explicit additional $2 for new calls.',
        'approvedLimitUsd':2.,'executionCapUsd':1.98,'checkpointRequestIds':ids,
        'baseRequestCount':554,'baseActualKnownUsd':.58614423,'baseCommittedUsd':.662439105}
    path=root/'approved-window.json';path.write_text(json.dumps(approval))
    registry={key:{'state':'settled','amountUsd':0.} for key in ids}
    registry.update({'new-known':{'state':'settled','amountUsd':.0015},
                     'new-pending':{'state':'reserved','amountUsd':.025}})
    budget={'limitUsd':1.,'requests':registry,'committedUsd':.688939105,
        'approvedWindowSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'activeWindow':{'approvedLimitUsd':2.,'executionCapUsd':1.98,'committedUsd':.0265,
            'actualKnownUsd':.0015,'missingCacheWriteUpperBoundUsd':0.,
            'conservativeUnknownReservedUsd':.025,'requestCount':2,'checkpointRequestCount':554}}
    (root/'budget.json').write_text(json.dumps(budget))
    return approval,budget


class CostReportTests(unittest.TestCase):
    def test_partial_page_probe_and_incomplete_arm_never_qualify_as_full_comparison(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);save(root,'same-plan-14');save(root,'alias32',only_pages=[2])
            report=build(root);pair=next(p for p in report['samePlanComparisons'] if p['afterVariant']=='alias32')
            self.assertFalse(pair['fullDocumentComparisonEligible'])
            self.assertFalse(report['qualityEquivalent'])
            self.assertEqual(report['decision']['status'],'pending')

    def test_first_summary_skips_empty_local_unit_and_uses_publication_clock(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder,cache=save(root,'same-plan-8')
            (cache/'unit-00000.json').write_text(json.dumps({'summary':{'parts':[]}}))
            (cache/'unit-00001.json').write_text(json.dumps({'summary':{'parts':[{'body':'private prose'}]}}))
            (folder/'progress.jsonl').write_text('\n'.join(json.dumps(e) for e in [
                {'event':'summary_unit_ready','unit':1,'seconds':2},
                {'event':'summary_unit_ready','unit':2,'seconds':9.5}]))
            records,_=collect_runs(root)
            self.assertEqual(records[0]['firstSummarySeconds'],9.5)

    def test_same_payload_proof_excludes_generated_overview_input(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            save(root,'same-plan-8',rows=[entry('a'),entry('b','summary_reduce','generated-one')])
            save(root,'same-plan-14',rows=[entry('c'),entry('d','summary_reduce','generated-two')])
            records,private=collect_runs(root);pair=pair_runs(records,private,'same-plan-8','same-plan-14')
            self.assertTrue(pair['fullPayloadHashComparison']['established'])
            self.assertEqual(pair['fullPayloadHashComparison']['identicalFullPayloadHashes'],1)

    def test_running_arm_reservations_and_write_fee_are_counted_without_history(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);unknown={'requestId':'u','state':'reserved','reservedUsd':.02}
            a=entry('a');a['usage']['prompt_tokens_details']['cache_write_tokens']=1000
            save(root,'active',rows=[a,unknown],run_record=False)
            report=build(root)
            self.assertAlmostEqual(report['budget']['actualKnownUsd'],.001525)
            self.assertAlmostEqual(report['budget']['conservativeUnknownReservedUsd'],.025)
            self.assertAlmostEqual(report['budget']['committedUsd'],.026525)
            self.assertTrue(report['budget']['snapshotMayChangeWhileRunning'])

    def test_public_html_escapes_metadata_and_contains_no_original_prose_or_remote_assets(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);save(root,'<script>')
            report=build(root);html=render(report)
            self.assertNotIn('NEVER EXPOSE RAW SOURCE',html)
            self.assertIn('&lt;script&gt;',html)
            self.assertNotIn('<script>',html)
            self.assertNotIn('src="http',html)
            self.assertNotIn('href="http',html)
            self.assertNotIn('requestMetrics',json.dumps(report))

    def test_prior_554_request_checkpoint_and_new_two_dollar_window_are_independent(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=entry('old-0');old['estimatedUsd']=.58614423
            save(root,'earlier-window',rows=[old])
            save(root,'new-window',rows=[entry('new-known'),
                {'requestId':'new-pending','state':'reserved','reservedUsd':.02}],run_record=False)
            approve_new_window(root)
            tracked=list(root.rglob('*.json'));before={path:path.read_bytes() for path in tracked}
            report=build(root);b=report['budget']
            self.assertEqual(b['approvedCapUsd'],2.)
            self.assertEqual(b['executionCapUsd'],1.98)
            self.assertAlmostEqual(b['actualKnownUsd'],.0015)
            self.assertAlmostEqual(b['committedUsd'],.0265)
            self.assertAlmostEqual(b['remainingToCapUsd'],1.9735)
            self.assertAlmostEqual(b['remainingToExecutionCapUsd'],1.9535)
            self.assertEqual(b['registeredRequestCount'],2)
            self.assertEqual(b['checkpointRequestCount'],554)
            previous=b['previousWindow']
            self.assertEqual(previous['approvedCapUsd'],1.)
            self.assertEqual(previous['checkpointRequestCount'],554)
            self.assertEqual(previous['actualKnownUsdAtApproval'],.58614423)
            self.assertEqual(previous['committedUsdAtApproval'],.662439105)
            self.assertAlmostEqual(b['cumulativeAllRunLedgers']['actualKnownUsd'],.58764423)
            self.assertEqual(b['inputTokens'],10000)
            self.assertTrue(b['approvalCheckpointValidated'])
            self.assertEqual({path:path.read_bytes() for path in tracked},before)
            html=render(report)
            self.assertIn('554',html);self.assertIn('$2.000000',html)
            self.assertIn('$0.586144',html);self.assertIn('$0.662439',html)

    def test_active_snapshot_keeps_registered_hold_not_yet_present_in_run_ledger(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);save(root,'new',rows=[entry('new-known')])
            approve_new_window(root)
            report=build(root);b=report['budget']
            self.assertAlmostEqual(b['committedUsd'],.0265)
            self.assertAlmostEqual(b['conservativeUnknownReservedUsd'],.025)
            self.assertEqual(b['registeredRequestCount'],2)
            self.assertEqual(b['usageBasedUsd'],.0015)
            self.assertEqual(b['registeredUnresolvedRequestCount'],1)
            self.assertEqual(b['registeredRequestsWithoutLedger'],1)
            self.assertTrue(b['snapshotMayChangeWhileRunning'])

    def test_changed_or_missing_bound_approval_checkpoint_is_not_silently_ignored(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);approve_new_window(root)
            path=root/'approved-window.json';original=path.read_text()
            changed=json.loads(original);changed['approvedLimitUsd']=3.
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):build(root)
            path.unlink()
            with self.assertRaises(ValueError):build(root)

    def test_nested_probe_usage_is_counted_once_and_labeled_as_its_own_scope(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=save(root,'batch-probes/case-a',rows=[entry('nested')])
            update_run(folder,sampleOnly=True,onlyUnitIds=['unit'])
            report=build(root)
            self.assertEqual(len(report['runs']),1)
            self.assertEqual(report['runs'][0]['variant'],'batch-probes/case-a')
            self.assertFalse(report['runs'][0]['fullRunEligible'])
            self.assertEqual(report['budget']['requests'],1)
            self.assertAlmostEqual(report['budget']['actualKnownUsd'],.0015)

    def test_unit_filter_generic_sample_failed_and_running_never_show_full_reductions(self):
        for scope in ('onlyUnitIds','sampleOnly','failed','running'):
            with self.subTest(scope=scope),TemporaryDirectory() as tmp:
                root=Path(tmp);save(root,'same-plan-14')
                folder,_=save(root,'candidate',run_record=scope!='running')
                if scope=='onlyUnitIds':update_run(folder,onlyUnitIds=['unit'])
                if scope=='sampleOnly':update_run(folder,sampleOnly=True)
                if scope=='failed':update_run(folder,failedUnits=[{'unitId':'unit','error':'AiResponseError'}])
                report=build(root)
                row=next(row for row in report['runs'] if row['variant']=='candidate')
                self.assertFalse(row['fullRunEligible'])
                records,private=collect_runs(root)
                pair=pair_runs(records,private,'same-plan-14','candidate')
                self.assertFalse(pair['fullDocumentComparisonEligible'])
                self.assertEqual(pair['changes'],{})

    def test_batch_compares_original_unit_coverage_instead_of_per_unit_payload_hashes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ids=['original-a','original-b','original-c']
            singles=[]
            for index,key in enumerate(ids):
                row=entry(f'single-{index}',payload=f'individual-payload-{index}');row['unitIds']=[key];singles.append(row)
            batch=entry('batched',payload='new-batch-payload');batch['unitIds']=ids
            save(root,'same-plan-14',rows=singles)
            folder,_=save(root,'batch4',rows=[batch])
            update_run(folder,batchUnits=4,batchImages=16,balancedBatches=True,
                       metrics={'studyJobs':3,'transportSubmissions':1,'transportBalanced':True})
            report=build(root);pair=next(pair for pair in report['samePlanComparisons'] if pair['afterVariant']=='batch4')
            self.assertTrue(pair['fullDocumentComparisonEligible'])
            self.assertFalse(pair['fullPayloadHashComparison']['applicable'])
            self.assertFalse(pair['fullPayloadHashComparison']['established'])
            self.assertTrue(pair['canonicalSourcePlanUnitCoverageComparison']['established'])
            self.assertFalse(pair['canonicalSourcePlanUnitCoverageComparison']['qualityEquivalent'])
            row=next(row for row in report['runs'] if row['variant']=='batch4')
            self.assertEqual((row['batchUnits'],row['batchImages'],row['batchSubmissions']),(4,16,1))
            self.assertTrue(row['balancedBatches'])
            self.assertEqual(row['unitIdCoverage']['observedBatchSubmissions'],1)
            html=render(report)
            self.assertIn('개별 payload hash 비교: 해당 없음',html)
            self.assertIn('원래 unit ID 범위 동등 확인',html)
            self.assertIn('균형 포장',html)

    def test_batch_with_changed_or_duplicate_unit_coverage_cannot_claim_equal_full_work(self):
        for mode in ('changed','duplicate','unsettled','manifest-mismatch','malformed-manifest'):
            with self.subTest(mode=mode),TemporaryDirectory() as tmp:
                root=Path(tmp);left=entry('left');left['unitIds']=['a','b']
                right=entry('right');right['unitIds']=['a','b']
                if mode=='changed':right['unitIds']=['a','c']
                if mode=='duplicate':right['unitIds']=['a','b','b']
                if mode=='unsettled':right={'requestId':'right','state':'reserved','reservedUsd':.02,
                                          'kind':'region_study','unitIds':['a','b']}
                save(root,'same-plan-14',rows=[left])
                folder,cache=save(root,'batch-candidate',rows=[right]);update_run(folder,batchUnits=2)
                if mode=='manifest-mismatch':(cache/'manifest.json').write_text(json.dumps({'jobs':[{'id':'a'},{'id':'b'},{'id':'c'}]}))
                if mode=='malformed-manifest':(cache/'manifest.json').write_text(json.dumps({'jobs':[{'id':['a']},{'id':'b'}]}))
                report=build(root);pair=next(pair for pair in report['samePlanComparisons'] if pair['afterVariant']=='batch-candidate')
                self.assertFalse(pair['canonicalSourcePlanUnitCoverageComparison']['established'])
                self.assertFalse(pair['fullDocumentComparisonEligible'])
                self.assertEqual(pair['changes'],{})

    def test_balanced_batch_metrics_fallback_and_running_unknown_options(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=save(root,'completed')
            update_run(folder,metrics={'transportBatchUnits':4,'transportBatchImages':16,
                                     'transportSubmissions':1,'transportBalanced':True})
            save(root,'running',run_record=False)
            records,_=collect_runs(root);index={row['variant']:row for row in records}
            self.assertEqual((index['completed']['batchUnits'],index['completed']['batchImages']),(4,16))
            self.assertTrue(index['completed']['balancedBatches'])
            self.assertIsNone(index['running']['batchUnits'])
            self.assertIsNone(index['running']['batchImages'])
            self.assertIsNone(index['running']['balancedBatches'])
            self.assertIsNone(index['running']['batchAliases'])
            self.assertIsNone(index['running']['statementUncertainty'])

    def test_same_source_plan_controls_are_found_for_industry_and_pointers(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for family in ('industry','pointers'):
                control,_=save(root,family+'-control',rows=[entry(family+'-single')])
                update_run(control,sourceSha256=family+'-source',planSha256=family+'-plan')
                balanced,_=save(root,family+'-balanced',rows=[entry(family+'-batch')])
                update_run(balanced,sourceSha256=family+'-source',planSha256=family+'-plan',
                           batchUnits=4,batchImages=16,batchAliases=True,statementUncertainty=True)
            wrong,_=save(root,'industry-wrong-plan');update_run(wrong,sourceSha256='industry-source',planSha256='other-plan')
            report=build(root)
            pairs={(pair['beforeVariant'],pair['afterVariant']):pair for pair in report['samePlanComparisons']}
            self.assertIn(('industry-control','industry-balanced'),pairs)
            self.assertIn(('pointers-control','pointers-balanced'),pairs)
            self.assertNotIn(('industry-control','industry-wrong-plan'),pairs)
            self.assertNotIn(('industry-balanced','industry-control'),pairs)
            for pair in pairs.values():
                self.assertTrue(pair['canonicalSourcePlanUnitCoverageComparison']['established'])
                self.assertFalse(pair['canonicalSourcePlanUnitCoverageComparison']['qualityEquivalent'])
                self.assertFalse(pair['fullPayloadHashComparison']['applicable'])
                self.assertTrue(any('canonical ID' in note for note in pair['notes']))
                self.assertTrue(any('불확실성 보고 설정도 달라요' in note for note in pair['notes']))
            for row in report['runs']:
                if row['variant'].endswith('-balanced'):
                    self.assertTrue(row['batchAliases']);self.assertTrue(row['statementUncertainty'])
            html=render(report)
            self.assertIn('배치 별칭',html);self.assertIn('문장별 불확실성',html)

    def test_actual_network_peak_deduplicates_requests_preserves_failed_tail_and_excludes_not_sent(self):
        a=entry('a');a.update(sentAtMs=0,latencySeconds=10)
        b=entry('b');b.update(sentAtMs=10000,latencySeconds=5)
        c=entry('c');c.update(sentAtMs=5000,latencySeconds=20)
        stale=dict(c,latencySeconds=1)
        failed={'requestId':'failed','state':'failed_or_uncertain','reservedUsd':.02,
                'sentAtMs':6000,'latencySeconds':40}
        pending={'requestId':'pending','state':'reserved','reservedUsd':.02}
        not_sent={'requestId':'cancelled','state':'not_sent','reservedUsd':.02,
                  'sentAtMs':0,'latencySeconds':999}
        timing=request_timing([a,b,stale,c,failed,pending,not_sent])
        self.assertEqual(timing['totalRequests'],5)
        self.assertEqual(timing['maxRequestSeconds'],40)
        self.assertEqual(timing['peakActiveRequest'],3)
        self.assertEqual(timing['networkIntervalsObserved'],4)
        self.assertEqual(timing['requestsWithoutCompleteTiming'],1)
        self.assertEqual(timing['notSentRequestsExcluded'],1)
        # Half-open intervals: the boundary at t=10 never counts a and b together.
        self.assertEqual(request_timing([a,b])['peakActiveRequest'],1)

    def test_latency_without_a_send_timestamp_is_preserved_but_no_peak_is_invented(self):
        row=entry('long');row['latencySeconds']=121.5
        timing=request_timing([row])
        self.assertEqual(timing['maxRequestSeconds'],121.5)
        self.assertIsNone(timing['peakActiveRequest'])
        self.assertEqual(timing['requestsWithoutCompleteTiming'],1)
        for invalid in (None,True,-1,float('inf')):
            row=entry('invalid');row.update(sentAtMs=0,latencySeconds=invalid)
            timing=request_timing([row])
            self.assertIsNone(timing['maxRequestSeconds'])
            self.assertIsNone(timing['peakActiveRequest'])
        row=entry('zero');row.update(sentAtMs=0,latencySeconds=0.)
        self.assertEqual(request_timing([row])['peakActiveRequest'],0)

    def test_request_timing_and_external_decision_are_reported_without_changing_the_decision(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            row=entry('network');row.update(sentAtMs=1000,latencySeconds=135.)
            save(root,'same-plan-14',rows=[row])
            candidate=entry('candidate');candidate.update(sentAtMs=1000,latencySeconds=150.)
            folder,_=save(root,'batch4',rows=[candidate]);update_run(folder,batchUnits=4,batchImages=16)
            decision={'status':'deferred-quality-counterexample','note':'본문 반례가 있어 보류해요.'}
            path=root/'decision.json';path.write_text(json.dumps(decision));before=path.read_bytes()
            report=build(root)
            self.assertEqual(report['decision'],decision)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(report['runs'][0]['totalRequests'],1)
            self.assertEqual(report['runs'][0]['peakActiveRequest'],1)
            self.assertEqual(report['runs'][0]['maxRequestSeconds'],150.)
            pair=next(pair for pair in report['samePlanComparisons'] if pair['afterVariant']=='batch4')
            self.assertEqual(pair['requestTimingComparison']['before']['maxRequestSeconds'],135.)
            self.assertEqual(pair['requestTimingComparison']['after']['maxRequestSeconds'],150.)
            html=render(report)
            self.assertIn('최장 요청 초',html);self.assertIn('관측 동시 요청',html)
            self.assertIn('deferred-quality-counterexample',html)

    def test_exact_and_namespace_full_pair_displays_changed_hint_schema_and_api_contract(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            exact,_=save(root,'pair-exact-full',rows=[entry('exact')])
            update_run(exact,batchUnits=2,batchImages=8,batchAliases=True,batchAliasPool='exact',
                       sourceCoverageHint=False,studyInputApi='chat')
            namespace,_=save(root,'pair-namespace-full',rows=[entry('namespace')])
            update_run(namespace,batchUnits=2,batchImages=8,batchAliases=True,batchAliasPool='namespace',
                       sourceCoverageHint=True,studyInputApi='responses')
            report=build(root)
            direct=[pair for pair in report['samePlanComparisons'] if pair['beforeVariant']=='pair-exact-full'
                    and pair['afterVariant']=='pair-namespace-full']
            self.assertEqual(len(direct),1)
            pair=direct[0]
            self.assertTrue(pair['fullDocumentComparisonEligible'])
            self.assertTrue(pair['canonicalSourcePlanUnitCoverageComparison']['established'])
            self.assertFalse(pair['qualityEquivalent'])
            self.assertFalse(pair['fullPayloadHashComparison']['applicable'])
            self.assertEqual(pair['inputContractSettings']['after']['batchAliasPool'],'namespace')
            self.assertIs(pair['inputContractSettings']['after']['sourceCoverageHint'],True)
            self.assertEqual(pair['inputContractSettings']['after']['studyInputApi'],'responses')
            self.assertTrue(any('별칭 schema 방식도 달라요' in note for note in pair['notes']))
            self.assertTrue(any('원문 보존 hint 설정' in note for note in pair['notes']))
            self.assertTrue(any('입력 API 경로도 달라요' in note for note in pair['notes']))
            html=render(report)
            self.assertIn('별칭 schema',html);self.assertIn('원문 보존 hint',html);self.assertIn('입력 API',html)
            self.assertIn('namespace',html);self.assertIn('responses',html)

    def test_responses_full_has_each_direct_profile_comparison_once_with_cache_and_contracts(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,api,pool,hint,cached in [
                    ('same-plan-8','chat',None,False,0),
                    ('pair-exact-full','chat','exact',False,1000),
                    ('pair-namespace-full','chat','namespace',True,2000),
                    ('responses-full','responses','namespace',True,4000)]:
                row=entry(name);row['usage']['prompt_tokens_details']['cached_tokens']=cached
                folder,_=save(root,name,rows=[row])
                update_run(folder,batchUnits=1 if name=='same-plan-8' else 2,
                           batchImages=4 if name=='same-plan-8' else 8,
                           batchAliases=pool is not None,batchAliasPool=pool,
                           studyInputApi=api,sourceCoverageHint=hint)
            report=build(root)
            for before in ('same-plan-8','pair-exact-full','pair-namespace-full'):
                pairs=[pair for pair in report['samePlanComparisons']
                       if (pair['beforeVariant'],pair['afterVariant'])==(before,'responses-full')]
                self.assertEqual(len(pairs),1)
                pair=pairs[0]
                self.assertTrue(pair['fullDocumentComparisonEligible'])
                self.assertTrue(pair['canonicalSourcePlanUnitCoverageComparison']['established'])
                self.assertFalse(pair['qualityEquivalent'])
                self.assertEqual(pair['inputContractSettings']['after']['studyInputApi'],'responses')
                self.assertTrue(any('입력 API 경로도 달라요' in note for note in pair['notes']))
                self.assertTrue(any('cache' in note for note in pair['notes']))
            indexed={row['variant']:row for row in report['runs']}
            self.assertEqual(indexed['responses-full']['usage']['cachedInputTokens'],4000)
            html=render(report)
            for before in ('same-plan-8','pair-exact-full','pair-namespace-full'):
                self.assertIn(before+' → responses-full',html)

    def test_external_final_decision_details_are_optional_escaped_and_read_only(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);save(root,'responses-full')
            decision={'status':'selected-with-caveats','note':'추가 원문 확인은 진행 중이에요.',
                'selectedProfile':{'variant':'responses-full','api':'responses','settings':['pair2','<svg>']},
                'measuredResults':[{'seconds':104.859,'costUsd':.10676654,'cacheTokens':321684},
                                   '<script>not executable</script>'],
                'qualityCaveats':['표본 원문 대조만 완료했어요.',{'pending':['3PDF','<img>']} ]}
            path=root/'decision.json';path.write_text(json.dumps(decision));before=path.read_bytes()
            report=build(root);html=render(report)
            self.assertEqual(report['decision'],decision)
            self.assertEqual(path.read_bytes(),before)
            for label in ('선택한 프로필','측정 결과','품질 확인 범위와 한계'):
                self.assertIn(label,html)
            for value in ('104.859','0.10676654','321684','표본 원문 대조만 완료했어요.'):
                self.assertIn(value,html)
            self.assertIn('&lt;svg&gt;',html);self.assertIn('&lt;script&gt;',html);self.assertIn('&lt;img&gt;',html)
            self.assertNotIn('<svg>',html);self.assertNotIn('<script>',html);self.assertNotIn('<img>',html)
            # The fields may be plain notes or arrays, rather than a fixed decision schema.
            report['decision']={'status':'pending','selectedProfile':['responses-full'],
                                'measuredResults':'재측정 대기','qualityCaveats':{}}
            html=render(report)
            self.assertIn('<li>responses-full</li>',html)
            self.assertIn('재측정 대기',html)
            self.assertNotIn('<strong>품질 확인 범위와 한계</strong>',html)

    def test_legacy_missing_hint_pool_are_unknown_and_setting_metadata_is_escaped(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);legacy,_=save(root,'legacy')
            candidate,_=save(root,'candidate')
            update_run(candidate,batchAliasPool='<script>',sourceCoverageHint=True,studyInputApi='<svg>')
            records,private=collect_runs(root);index={row['variant']:row for row in records}
            self.assertIsNone(index['legacy']['sourceCoverageHint'])
            self.assertIsNone(index['legacy']['batchAliasPool'])
            self.assertEqual(index['legacy']['studyInputApi'],'chat')
            pair=pair_runs(records,private,'legacy','candidate')
            self.assertTrue(any('한쪽 기록이 없어요' in note for note in pair['notes']))
            html=render(build(root))
            self.assertIn('&lt;script&gt;',html);self.assertIn('&lt;svg&gt;',html)
            self.assertNotIn('<script>',html);self.assertNotIn('<svg>',html)

    def test_admission_queue_is_not_counted_again_after_the_send_timestamp(self):
        a=entry('a');a.update(sentAtMs=0,latencySeconds=20.,queueSeconds=10.)
        b=entry('b');b.update(sentAtMs=10000,latencySeconds=20.,queueSeconds=10.)
        timing=request_timing([a,b])
        self.assertEqual(timing['maxRequestSeconds'],20.)
        self.assertEqual(timing['maxNetworkRequestSeconds'],10.)
        self.assertEqual(timing['maxQueueSeconds'],10.)
        self.assertEqual(timing['peakActiveRequest'],1)
        self.assertEqual(timing['networkTimingMethods'],{'latency_minus_queue':2})
        a.update(queueSeconds=5.,connectionAndResponseHeadersSeconds=3.2,responseBodySeconds=.5,requestEncodeSeconds=.1)
        b.update(sentAtMs=4000,connectionAndResponseHeadersSeconds=1.,responseBodySeconds=.2)
        timing=request_timing([a,b])
        self.assertAlmostEqual(timing['maxNetworkRequestSeconds'],3.8)
        self.assertEqual(timing['peakActiveRequest'],1)
        self.assertEqual(timing['networkTimingMethods'],{'network_phase_fields':2})


if __name__=='__main__':unittest.main()
