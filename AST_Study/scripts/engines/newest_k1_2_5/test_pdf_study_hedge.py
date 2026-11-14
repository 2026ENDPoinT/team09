"""Offline race/ledger regressions; never calls a paid endpoint."""
import json
import threading
import time
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_study_hedge as hedge
from pdf_study_connection import GuardedStudyResponse
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_responses_transport import native


class HedgeTests(unittest.TestCase):
    setUp = ResponsesProviderTests.setUp
    provider = ResponsesProviderTests.provider

    def setup_race(self, strategy='newest-k1'):
        provider = self.provider()
        provider.study_no_id_hedge = True
        provider.context = {'kind':'region_study', 'strategy':strategy, 'studyDurable':True}
        self.provider_instance = provider
        self.done = [threading.Event(), threading.Event()]
        self.calls = []
        self.call_lock = threading.Lock()
        self.addCleanup(self.wait_workers)
        self.delay = patch.object(hedge, 'DELAY', .04).start()
        # Newer strategies use their own 30s four-attempt policy, not DELAY.
        # Keep this transport test's clock consistently accelerated for both.
        patch('pdf_study_attempts.BACKUP_SECONDS', .04).start()
        patch('pdf_study_progress_attempts.BACKUP_SECONDS', .04).start()
        return provider

    def wait_workers(self):
        for event in self.done[:len(self.calls)]:
            event.wait(2)
        time.sleep(.03)

    def fixture(self, delays, *, acknowledge=None, invalid=None, fail=False):
        def request(req, **kwargs):
            with self.call_lock:
                index=len(self.calls);self.calls.append(json.loads(req.data))
            kwargs['update'](networkPhase='uploading_request')
            if acknowledge == index:
                kwargs['update'](responseId='resp_test_'+str(index))
            try:
                time.sleep(delays[index])
                kwargs['update'](responseId='resp_test_'+str(index))
                result=native()
                result['id']='resp_test_'+str(index)
                try:kwargs['check']()
                except InterruptedError:
                    result['status']='cancelled'
                    return GuardedStudyResponse(result,None,'user_cancelled')
                if fail:raise OSError('synthetic connection failure')
                if invalid == index:
                    result['output'][0]['content'][0]['text']='{"wrong": true}'
                kwargs['on_delta']('original' if index==0 else 'extra')
                return result
            finally:self.done[index].set()
        return patch('pdf_study_connection.request_once', side_effect=request)

    def test_extra_wins_all_three_versions_and_both_costs_survive(self):
        for strategy in sorted(hedge.STRATEGIES):
            # Distinct payloads avoid intentionally reused paid caches.
            provider=self.setup_race(strategy)
            payload={**self.payload,'variant':strategy}
            preview=[]
            with self.fixture([.24,.015]):
                start=time.monotonic()
                result=provider.complete(payload,**self.options,on_study_delta=preview.append)
                self.assertLess(time.monotonic()-start,.20)
                self.assertEqual(result,{'ok':True})
                self.wait_workers()
            self.assertEqual(len(self.calls),2)
            self.assertEqual(self.calls[0],self.calls[1])
            self.assertEqual(preview,['extra'])
            entries=provider.ledger['requests']
            self.assertEqual(len(entries),2)
            self.assertEqual(len({e['responseCacheKey']for e in entries}),2)
            self.assertTrue(entries[1]['hedgeWinner'])
            self.assertEqual(entries[0]['clientStopReason'],'hedge_superseded')
            self.assertTrue(all(e['state']=='settled'for e in entries))
            self.assertAlmostEqual(provider.spent,sum(e['estimatedUsd']for e in entries))
            with patch('pdf_study_connection.request_once',side_effect=AssertionError('cache must win')):
                self.assertEqual(provider.complete(payload,**self.options),result)

    def test_id_before_threshold_prevents_extra_even_if_result_is_slow(self):
        provider=self.setup_race()
        with self.fixture([.14],acknowledge=0):
            self.assertEqual(provider.complete(self.payload,**self.options),{'ok':True})
        self.assertEqual(len(self.calls),1)

    def test_original_can_still_win_after_extra_launch(self):
        provider=self.setup_race()
        with self.fixture([.09,.16]):
            provider.complete(self.payload,**self.options)
            self.wait_workers()
        self.assertTrue(provider.ledger['requests'][0]['hedgeWinner'])
        self.assertEqual(len(self.calls),2)

    def test_invalid_first_completion_does_not_defeat_valid_other(self):
        provider=self.setup_race()
        with self.fixture([.15,.01],invalid=1):
            self.assertEqual(provider.complete(self.payload,**self.options),{'ok':True})
        self.assertTrue(provider.ledger['requests'][0]['hedgeWinner'])

    def test_both_fail_without_third_post_and_reservations_remain(self):
        provider=self.setup_race()
        with self.fixture([.11,.12],fail=True):
            with self.assertRaises(ai.AiResponseError)as caught:
                ai.complete_study_delivery(provider,self.payload,**self.options)
        self.assertTrue(caught.exception.study_hedge_exhausted)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(e['state']=='failed_or_uncertain'for e in provider.ledger['requests']))
        self.assertAlmostEqual(provider.spent,sum(e['reservedUsd']for e in provider.ledger['requests']))

    def test_standalone_comparison_and_legacy_opt_out(self):
        provider=self.provider()
        provider.context={'strategy':'newest-k1','studyDurable':True}
        self.assertFalse(hedge.enabled(provider,self.payload,self.options))
        provider.study_no_id_hedge=True
        provider.context['strategy']='new-concept-v99'
        self.assertFalse(hedge.enabled(provider,self.payload,self.options))

    def test_budget_cannot_be_bypassed_by_extra(self):
        provider=self.setup_race()
        original_reserve=[]
        reserve=provider.reserve_credits
        def limit_after_first(entry):
            reserve(entry)
            original_reserve.append(entry['reservedUsd'])
            provider.max_usd=entry['reservedUsd']*1.01
        provider.reserve_credits=limit_after_first
        with self.fixture([.15]):
            self.assertEqual(provider.complete(self.payload,**self.options),{'ok':True})
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(original_reserve),1)

    def test_local_wait_does_not_start_ten_second_timer(self):
        provider=self.setup_race()
        def request(req, **kwargs):
            self.calls.append({})
            kwargs['update'](networkPhase='waiting_upload_slot')
            time.sleep(.12)
            kwargs['update'](networkPhase='uploading_request')
            kwargs['update'](responseId='resp_normal')
            self.done[0].set()
            return native()
        with patch('pdf_study_connection.request_once',side_effect=request):
            provider.complete(self.payload,**self.options)
        self.assertEqual(len(self.calls),1)

    def test_private_paid_cache_recovers_without_repaying(self):
        provider=self.setup_race()
        with self.fixture([.01],acknowledge=0):
            provider.complete(self.payload,**self.options)
        entry=provider.ledger['requests'][0]
        canonical=provider.folder/'generated/paid-responses'/(entry['logicalResponseCacheKey']+'.json')
        canonical.unlink()
        restarted=self.provider()
        restarted.study_no_id_hedge=True
        restarted.context=provider.context.copy()
        with patch('pdf_study_connection.request_once',side_effect=AssertionError('no paid retry')):
            self.assertEqual(restarted.complete(self.payload,**self.options),{'ok':True})
        self.assertTrue(canonical.exists())

    def test_parallel_elapsed_time_not_sum_of_loser_and_winner(self):
        from pdf_study_timings import unit_timings
        job={'id':'unit','title':'unit','blocks':[{'page':1}]}
        requests=[{'kind':'region_study','unitIds':['unit'],'hedgeGroup':'g',
                   'hedgeWinner':False,'latencySeconds':79},
                  {'kind':'region_study','unitIds':['unit'],'hedgeGroup':'g',
                   'hedgeWinner':True,'hedgeResultSeconds':26,'latencySeconds':16}]
        row=unit_timings([job],{0:{}},[],{'requests':requests})[0]
        self.assertEqual(row['requestSeconds'],26)
        self.assertEqual(row['requestCount'],2)

    def test_unfunded_optional_hedge_does_not_stop_ordinary_work(self):
        from pdf_credit_billing import Billing
        provider=self.setup_race()
        wallet=provider.folder.parent/'wallet.json'
        wallet.write_text(json.dumps({'version':1,'liveBilling':True,'baselineCredits':0,
            'highWaterCredits':0,'purchases':[{'credits':'1'}],
            'creditOperations':{},'creditCharges':{},'creditHolds':{}}))
        provider.billing=Billing(wallet,provider.ledger['operationId'],'summary')
        with self.assertRaises(ai.BudgetExceeded):
            provider.reserve_credits({'requestId':'optional','reservedUsd':1,'hedgeAttempt':1})
        self.assertFalse(provider.billing.exhausted)
        self.assertFalse(json.loads(wallet.read_text())['creditHolds'])

    def test_loser_waiting_for_admission_stops_but_sent_no_id_stays_connected(self):
        provider=self.setup_race()
        race=hedge.Race(provider,self.payload,self.options)
        original=race.attempts[0]
        race.winner=hedge.Attempt(race,1)
        with self.assertRaises(InterruptedError):original.check()
        original.update(networkPhase='uploading_request')
        original.check()  # no ID yet; keep receipt channel alive
        original.update(responseId='resp_late')
        with self.assertRaises(InterruptedError):original.check()

    def test_delivery_fallback_cannot_add_third_attempt(self):
        provider=self.setup_race()
        failure=ai.StudyDeliveryFallback('original')
        failure.study_hedge_exhausted=True
        with patch.object(provider,'complete',side_effect=failure)as complete:
            with self.assertRaises(ai.StudyDeliveryFallback):
                ai.complete_study_delivery(provider,self.payload,**self.options)
        self.assertEqual(complete.call_count,1)


if __name__=='__main__':unittest.main()
