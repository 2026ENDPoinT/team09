"""Slow acknowledged requests, native completion and winner publication safety."""
import threading
import time
import unittest
import io
import json
from unittest.mock import patch

import pdf_study_tail as tail
import pdf_study_hedge as hedge
from pdf_study_connection import GuardedStudyResponse
from test_pdf_study_hedge import HedgeTests
from test_pdf_responses_transport import native
from test_pdf_study_idle_watch import IdleWatchTests


class SlowRaceTests(HedgeTests):
    def test_confirmed_server_failure_gets_one_identical_retry(self):
        for fail_twice in (False,True):
            p=self.setup_race('newest-k1-1-1')
            def call(req,**kw):
                index=len(self.calls);self.calls.append(req.data)
                kw['update'](networkPhase='uploading_request',responseId='resp_failure_'+str(index))
                v=native();v['id']='resp_failure_'+str(index)
                if index==0 or fail_twice:
                    v['status']='failed';v['error']={'code':'server_error'};v['output']=[];v['usage']=None
                self.done[index].set()
                return v
            with patch('pdf_study_connection.request_once',side_effect=call):
                if fail_twice:
                    import pdf_ai as ai
                    with self.assertRaises(ai.AiResponseError) as caught:
                        ai.complete_study_delivery(p,{**self.payload,'fail_twice':fail_twice},**self.options)
                    self.assertTrue(caught.exception.study_hedge_exhausted)
                else:
                    self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
                self.wait_workers()
            self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[0],self.calls[1])
            self.assertTrue(all(e.get('hedgeReason')=='confirmed_server_failure' for e in p.ledger['requests']))

    def slow_fixture(self, provider, *, terminal=False, known=True, invalid_extra=False, budget=False):
        self.addCleanup(patch.stopall)
        patch.object(tail, 'AFTER_SECONDS', .06).start()
        patch.object(tail, 'STATUS_FRESH_SECONDS', .10).start()
        patch.object(hedge, 'DELAY', 1).start()
        original_done=threading.Event()
        def call(req, **kw):
            with self.call_lock:
                index=len(self.calls);self.calls.append(req.data)
            try:
                kw['update'](networkPhase='uploading_request', responseId='resp_slow_'+str(index))
                if index==0:
                    kw['on_delta']('old-prefix')
                    time.sleep(.075)
                    if known:
                        kw['update'](slowResponsePending=not terminal, idleStatus='completed' if terminal else 'in_progress')
                    time.sleep(.17)
                    kw['on_delta']('old-suffix')
                else:
                    time.sleep(.015)
                    kw['on_delta']('new-complete')
                value=native();value['id']='resp_slow_'+str(index)
                value['created_at']=100;value['completed_at']=291 if index==0 else 111
                if invalid_extra and index==1:value['output'][0]['content'][0]['text']='{"wrong":true}'
                try:kw['check']()
                except InterruptedError:
                    value['status']='cancelled'
                    return GuardedStudyResponse(value,None,'user_cancelled')
                return value
            finally:
                self.done[index].set()
                if index==0:original_done.set()
        if budget:
            reserve=provider.reserve_credits
            def limit(entry):
                reserve(entry);provider.max_usd=entry['reservedUsd']*1.01
            provider.reserve_credits=limit
        return patch('pdf_study_connection.request_once',side_effect=call)

    def test_confirmed_slow_extra_wins_resets_preview_and_accounts_for_original(self):
        p=self.setup_race('newest-k1-1-1');seen=[]
        def reset():seen.clear()
        with self.slow_fixture(p):
            result=p.complete(self.payload,**self.options,on_study_delta=seen.append,on_delivery_reset=reset)
            self.wait_workers()
        self.assertEqual(result,{'ok':True});self.assertEqual(seen,['new-complete'])
        self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[0],self.calls[1])
        self.assertTrue(p.ledger['requests'][1]['hedgeWinner'])
        self.assertEqual(p.ledger['requests'][0]['clientStopReason'],'hedge_superseded')
        self.assertTrue(all(e['hedgeReason']=='confirmed_slow_response' for e in p.ledger['requests']))
        self.assertEqual(p.ledger['requests'][1]['serverLifecycleSeconds'],11)
        self.assertAlmostEqual(p.spent,sum(e['estimatedUsd'] for e in p.ledger['requests']))
        self.assertTrue(all(a.get('parallel_limit')==40 and a.get('count_parallel') for a in self.admissions))

    def test_invalid_extra_keeps_original_preview_and_result(self):
        p=self.setup_race('newest-k1-1-1');seen=[];resets=[]
        with self.slow_fixture(p,invalid_extra=True):
            p.complete(self.payload,**self.options,on_study_delta=seen.append,on_delivery_reset=lambda:resets.append(1))
            self.wait_workers()
        self.assertEqual(seen,['old-prefix','old-suffix']);self.assertEqual(resets,[])
        self.assertTrue(p.ledger['requests'][0]['hedgeWinner'])

    def test_completed_or_unconfirmed_status_does_not_repost(self):
        for kwargs in ({'terminal':True},{'known':False}):
            p=self.setup_race('newest-k1-1-1')
            with self.slow_fixture(p,**kwargs):
                p.complete({**self.payload,'case':str(kwargs)},**self.options)
            self.assertEqual(len(self.calls),1)

    def test_slow_extra_still_respects_budget(self):
        p=self.setup_race('newest-k1-1-1')
        with self.slow_fixture(p,budget=True):
            self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
        self.assertEqual(len(self.calls),1)

    def test_no_preview_reset_no_acknowledged_hedge(self):
        p=self.setup_race('newest-k1-1-1')
        with self.slow_fixture(p):p.complete(self.payload,**self.options,on_study_delta=lambda text:None)
        self.assertEqual(len(self.calls),1)

    def test_old_engines_and_grouping_do_not_enable_tail_policy(self):
        for strategy in ('newest-k1','newest-k1-1','newest-k1-11'):
            self.assertFalse(tail.enabled({'strategy':strategy,'kind':'region_study'},self.payload,{}))
        self.assertFalse(tail.enabled({'strategy':'newest-k1-1-1','kind':'region_plan'},{'task':'region_groups'},{}))

    def test_stale_status_cannot_authorize_extra(self):
        p=self.setup_race('newest-k1-1-1');race=hedge.Race(p,self.payload,self.options)
        a=race.attempts[0];a.sent=time.monotonic()-100;a.response_id='resp_known'
        a.slow_pending=True;a.status_checked=time.monotonic()-11
        self.assertIsNone(race.extra_reason())


class SlowStatusTests(IdleWatchTests):
    def test_fast_control_loop_is_not_mistaken_for_useful_progress(self):
        import pdf_study_idle_watch as idle
        from pdf_study_connection import request_once
        from test_pdf_stream_resume import request
        def send():
            for _ in range(30):
                time.sleep(.02)
                if self.stream.closed:return
                try:self.stream.send({'type':'response.output_text.delta','delta':r'\\u001b[0m'*4})
                except OSError:return
        self.send_later(send)
        self.get=lambda:{**native(),'status':'in_progress' if len(self.get_times)==1 else 'completed'}
        with patch.object(idle,'OUTPUT_LOOP_AFTER_SECONDS',.10):
            request_once(request(),open_url=self.opener,update=lambda **x:self.updates.append(x),
                         resume_stream=True,tail_status_after=45)
        slow=next(u for u in self.updates if u.get('slowResponsePending'))
        self.assertEqual(slow['slowResponseCause'],'repeated_terminal_controls')
        self.assertLess(slow['slowResponseAgeSeconds'],1)

    def test_active_trickle_is_checked_and_completed_original_is_recovered(self):
        # Never idle for INTERVAL, but slower than the useful-progress threshold.
        from pdf_study_connection import request_once
        from test_pdf_stream_resume import request
        def send():
            for _ in range(20):
                time.sleep(.025)
                if self.stream.closed:return
                try:self.stream.send({'type':'response.output_text.delta','delta':'x'})
                except OSError:return
        self.send_later(send)
        reads=[]
        def get():
            reads.append(1)
            return {**native(),'status':'in_progress' if len(reads)==1 else 'completed'}
        self.get=get
        value=request_once(request(),open_url=self.opener,update=lambda **x:self.updates.append(x),
                           resume_stream=True,tail_status_after=.10)
        self.assertEqual(value['status'],'completed')
        self.assertTrue(any(u.get('slowResponsePending') for u in self.updates))
        self.assertEqual(sum(r.method=='POST' for r in self.calls),1)
        self.assertEqual(len(reads),2)

    def test_fast_progress_checks_status_without_requesting_replacement(self):
        from pdf_study_connection import request_once
        from test_pdf_stream_resume import request
        def send():
            for _ in range(20):
                time.sleep(.025)
                if self.stream.closed:return
                try:self.stream.send({'type':'response.output_text.delta','delta':'x'*100})
                except OSError:return
        self.send_later(send)
        self.get=lambda:{**native(),'status':'in_progress' if len(self.get_times)==1 else 'completed'}
        request_once(request(),open_url=self.opener,update=lambda **x:self.updates.append(x),
                     resume_stream=True,tail_status_after=.10)
        self.assertFalse(any(u.get('slowResponsePending') for u in self.updates))


class ControlLoopTests(unittest.TestCase):
    def test_split_escaped_terminal_sequence_is_detected_without_mutating_text(self):
        for sequence in (r'\u001b[0m',r'\\u001b[0m','\x1b[31m'):
            meter=tail.ControlSequenceLoop()
            for c in sequence*15:self.assertFalse(meter.feed(c))
            for c in sequence:meter.feed(c)
            self.assertTrue(meter.detected)

    def test_real_prose_math_code_and_separated_colors_remain_valid(self):
        for text in ('같은 말을 반복해요. '*1000,r'\begin{matrix}0&0&0\\0&0&0\end{matrix}'*100,
                     (r'\u001b[31m'+'red'+r'\u001b[0m'+' text')*100):
            self.assertFalse(tail.ControlSequenceLoop().feed(text))


class CancelReceiptTests(unittest.TestCase):
    def test_fallback_cancel_receipt_is_terminal_but_unknown_cost_is_retained(self):
        from test_pdf_responses_provider import ResponsesProviderTests
        fixture=ResponsesProviderTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        p=fixture.provider();p.context={'kind':'region_study','studyDurable':True}
        v={**native(),'status':'cancelled','usage':None}
        def request(req,**kw):
            kw['update'](responseId=v['id'])
            raise InterruptedError('Synthetic cancelled stream')
        fixture.opener.side_effect=lambda req,timeout:io.StringIO(json.dumps(v))
        with patch('pdf_study_connection.request_once',side_effect=request):
            with self.assertRaises(InterruptedError):p.complete(fixture.payload,**fixture.options)
        e=p.ledger['requests'][0]
        self.assertEqual(e['serverTerminalStatus'],'cancelled')
        self.assertEqual(e['state'],'usage_unknown')
        self.assertTrue(e['cancelReceiptConfirmed'])
        self.assertAlmostEqual(p.spent,e['reservedUsd'])
