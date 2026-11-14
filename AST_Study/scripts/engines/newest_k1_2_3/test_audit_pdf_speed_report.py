"""Offline budget-window accounting; no network, production ledger or UI access."""
import json
from pathlib import Path
import tempfile
import unittest

import audit_pdf_speed_report as report


def entry(request_id, state='settled', cost=.25, reserved=.5):
    return {'requestId':request_id,'state':state,'estimatedUsd':cost,
            'reservedUsd':reserved,'usage':{'prompt_tokens':100,
                                          'completion_tokens':20}}


class BudgetCheckpointTests(unittest.TestCase):
    def checkpoint(self):
        return {'schemaVersion':1,'createdAtUtc':'2026-10-20T18:47:40Z',
                'approvedNewCapUsd':2.0,'preexistingRequestIds':['old','old-unknown'],
                'previousActualUsd':1.5,'previousUncertainReservedUsd':.7,
                'previousCommittedUsd':2.2}

    def test_new_cap_ignores_previous_paid_and_unknown_attempts(self):
        entries=[entry('old',cost=4),entry('old-unknown','reserved',reserved=.7),
                 entry('new',cost=.25),entry('new-unknown','unknown',reserved=.5),
                 entry('new-not-sent','not_sent',cost=0,reserved=.9)]
        value=report.budget_summary(entries,1,0,self.checkpoint())
        self.assertAlmostEqual(value['committedUsd'],5.45)
        self.assertAlmostEqual(value['previousBudgetWindow']['committedUsd'],4.7)
        self.assertAlmostEqual(value['currentBudgetWindow']['committedUsd'],.75)
        self.assertEqual(value['currentBudgetWindow']['notSentRequests'],1)
        self.assertEqual(value['approvedCapUsd'],2)
        self.assertFalse(value['approvedCapExceeded'])
        self.assertAlmostEqual(value['remainingToApprovedCapUsd'],1.25)
        self.assertEqual(value['checkpoint']['snapshotPreviousCommittedUsd'],2.2)

    def test_prior_unknown_settling_later_stays_in_previous_window(self):
        checkpoint=self.checkpoint()
        before=report.budget_summary([entry('old-unknown','reserved',reserved=.7),
                                     entry('new')],1,0,checkpoint)
        after=report.budget_summary([entry('old-unknown',cost=.2),entry('new')],1,0,checkpoint)
        self.assertEqual(before['currentBudgetWindow'],after['currentBudgetWindow'])
        self.assertAlmostEqual(after['previousBudgetWindow']['actualUsd'],.2)
        self.assertEqual(after['previousBudgetWindow']['uncertainReservedUsd'],0)
        self.assertEqual(after['capAppliesTo'],'currentBudgetWindow')

    def test_new_unknown_reservation_counts_toward_two_dollar_boundary(self):
        value=report.budget_summary([entry('old',cost=9),entry('new',cost=1.5),
                                    entry('new-unknown','unknown',reserved=.5)],1,0,self.checkpoint())
        self.assertTrue(value['approvedCapExceeded'])
        self.assertEqual(value['remainingToApprovedCapUsd'],0)
        with self.assertRaises(ValueError):
            report.budget_summary([],0,0,{'approvedNewCapUsd':2})

    def test_cache_write_premium_is_separate_and_counts_in_current_cap(self):
        old=entry('old',cost=4)
        old['usage']['prompt_tokens_details']={'cache_write_tokens':2_000_000}
        new=entry('new',cost=1.98)
        new['usage']['prompt_tokens_details']={'cache_write_tokens':1_000_000}
        before=json.dumps([old,new],sort_keys=True)
        value=report.budget_summary([old,new],1,0,self.checkpoint())
        current=value['currentBudgetWindow']
        self.assertEqual(current['actualUsd'],1.98)
        self.assertEqual(current['committedUsd'],1.98)
        self.assertEqual(current['cacheWriteTokens'],1_000_000)
        self.assertAlmostEqual(current['knownCacheWriteSurchargeUsd'],.025)
        self.assertAlmostEqual(current['committedWithKnownCacheWriteUsd'],2.005)
        self.assertTrue(value['approvedCapExceeded'])
        self.assertAlmostEqual(value['remainingToApprovedCapUsd'],-.005)
        self.assertAlmostEqual(value['knownCacheWriteSurchargeUsd'],.075)
        self.assertEqual(json.dumps([old,new],sort_keys=True),before)

    def test_unknown_or_unsent_cache_usage_does_not_add_a_second_charge(self):
        unknown=entry('new-unknown','reserved',reserved=.5)
        unsent=entry('new-unsent','not_sent',cost=0,reserved=.9)
        for row in (unknown,unsent):
            row['usage']['prompt_tokens_details']={'cache_write_tokens':1_000_000}
        stats=report.usage_stats([unknown,unsent])
        self.assertEqual(stats['cacheWriteTokens'],0)
        self.assertEqual(stats['knownCacheWriteSurchargeUsd'],0)
        self.assertEqual(stats['committedWithKnownCacheWriteUsd'],.5)

    def test_html_displays_separate_windows_and_deduplicated_lifetime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);usage=root/'runs/finance/stable-none/usage'
            usage.mkdir(parents=True)
            old=entry('old',cost=4);new=entry('new',cost=.25)
            (usage/'first.json').write_text(json.dumps({'requests':[old,new]}))
            (usage/'copy.json').write_text(json.dumps({'requests':[new]}))
            (root/'budget-checkpoint-034740.json').write_text(json.dumps(self.checkpoint()))
            value=report.build_report(root);html=report.render_html(value)
            self.assertEqual(value['budget']['duplicateLedgerEntriesIgnored'],1)
            self.assertAlmostEqual(value['budget']['committedUsd'],4.25)
            self.assertAlmostEqual(value['budget']['currentBudgetWindow']['committedUsd'],.25)
            self.assertIn('체크포인트 이전',html)
            self.assertIn('체크포인트 이후 신규',html)
            self.assertIn('전체 누적',html)
            self.assertIn('$2.00 / $2.00',html)
            self.assertNotIn('$3.30 / $3.25',html)
            self.assertFalse((root/'report.html').exists())


class FrozenPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def write_run(self,variant,**extra):
        folder=self.root/'runs/pointers'/variant;folder.mkdir(parents=True)
        value={'case':'pointers','variant':variant,'pages':31,'processingComplete':True,
               'coverageComplete':True,'planningSeconds':.2,'wallSeconds':20,
               'metrics':{'firstResultSeconds':5},**extra}
        (folder/'run.json').write_text(json.dumps(value))

    def frozen(self):
        return {'variant':'conservative-none','originalPlanningSeconds':10,
                'teachingRepliesReused':False}

    def test_measured_values_stay_measured_and_equivalent_is_separate(self):
        self.write_run('control',frozenPlanning=self.frozen())
        row=report.build_report(self.root)['runs'][0]
        self.assertEqual(row['wallSeconds'],20)
        self.assertEqual(row['firstResultSeconds'],5.2)
        self.assertAlmostEqual(row['postGroupingSeconds'],19.8)
        self.assertAlmostEqual(row['modeledEquivalentOriginalPlanningSeconds'],29.8)
        self.assertEqual(row['frozenPlanning']['originalPlanningSeconds'],10)
        self.assertFalse(row['freshPlannerMeasured'])

    def test_frozen_run_is_not_a_fresh_speedup_in_default_comparison(self):
        self.write_run('baseline',planningSeconds=10,wallSeconds=40)
        self.write_run('control',frozenPlanning=self.frozen())
        (self.root/'decision.json').write_text(json.dumps(
            {'selectedVariant':'control','cases':['pointers']}))
        value=report.build_report(self.root);comparison=value['comparisons']
        self.assertFalse(comparison['allPairsAvailable'])
        self.assertEqual(comparison['totals']['pairCount'],0)
        self.assertIn('fresh planner not measured',' '.join(comparison['pairs'][0]['reasons']))
        html=report.render_html(value)
        self.assertIn('묶음 고정 대조 실험',html)
        self.assertIn('실제 fresh 측정값이 아니에요',html)

    def test_missing_source_or_wall_time_does_not_become_zero(self):
        self.write_run('control',wallSeconds=None,frozenPlanning={'variant':'prior'})
        row=report.build_report(self.root)['runs'][0]
        self.assertIsNone(row['postGroupingSeconds'])
        self.assertIsNone(row['modeledEquivalentOriginalPlanningSeconds'])

    def test_ordinary_fresh_run_remains_eligible(self):
        self.write_run('fresh')
        row=report.build_report(self.root)['runs'][0]
        self.assertTrue(row['freshPlannerMeasured'])
        self.assertTrue(row['comparisonEligible'])
        self.assertIsNone(row['modeledEquivalentOriginalPlanningSeconds'])

    def test_post_measurement_trace_does_not_replace_fresh_comparison(self):
        self.write_run('baseline',planningSeconds=10,wallSeconds=50)
        self.write_run('operational14-original',planningSeconds=10,wallSeconds=40)
        (self.root/'decision.json').write_text(json.dumps(
            {'selectedVariant':'operational14-original','cases':['pointers']}))
        traces=self.root/'throughput';traces.mkdir()
        (traces/'refill-v3-observation.json').write_text(json.dumps({
            'variant':'operational14-refill-v3','freshSixPdfRemeasured':False,
            'firstInitialResponseSeconds':11.956,'nextRequestStartSeconds':12.066,
            'lastInitialSiblingResponseSeconds':55.858}))
        value=report.build_report(self.root)
        self.assertEqual(value['comparisons']['totals']['after']['wallSeconds'],40)
        self.assertFalse(value['postMeasurementScheduler']['freshSixPdfRemeasured'])
        html=report.render_html(value)
        self.assertIn('6개 PDF 전체를 다시 측정한 결과는 아니며',html)
        self.assertIn('refill-v3-observation.json',html)


if __name__=='__main__':
    unittest.main()
