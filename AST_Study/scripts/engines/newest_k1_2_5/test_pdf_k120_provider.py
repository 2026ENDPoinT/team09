"""Offline end-to-end K120 wire, cap and hedging checks."""
import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pdf_ai as ai
import pdf_study_progress_attempts as progress
from pdf_study_hedge import enabled
from test_pdf_responses_provider import ResponsesProviderTests
from test_pdf_responses_transport import native


class ForegroundProviderTests(unittest.TestCase):
    setUp=ResponsesProviderTests.setUp
    provider=ResponsesProviderTests.provider
    reply=ResponsesProviderTests.reply

    def make(self):
        p=self.provider(mode='chat');p.billing=None
        p.context={'kind':'region_study','strategy':'newest-k1-2-5',
                   'studyForegroundResponses':True,'unitIds':['u1']}
        return p

    def test_foreground_wire_keeps_source_limits_and_separate_reservation(self):
        self.reply(native());p=self.make()
        self.assertEqual(p.complete(self.payload,**self.options),{'ok':True})
        body=json.loads(self.opener.call_args.args[0].data)
        self.assertTrue(body['stream']);self.assertTrue(body['store']);self.assertFalse(body['background'])
        self.assertEqual(body['max_output_tokens'],self.options['max_output'])
        self.assertEqual(json.loads(body['input'][1]['content'][0]['text']),self.payload)
        entry=p.ledger['requests'][0]
        self.assertAlmostEqual(entry['customerReservedUsd'],entry['userEstimatedUsd']*1.3)
        self.assertEqual(entry['providerUpperBoundUsd'],entry['reservedUsd'])
        self.assertEqual(entry['studyTransportVersion'],'foreground-responses-stream-v1')
        self.assertTrue(all(not c.args[0].full_url.endswith('/cancel') for c in self.opener.call_args_list))

    def test_overview_uses_foreground_responses_and_reuses_paid_result(self):
        self.reply(native());p=self.make();p.context['kind']='summary_reduce'
        payload={'task':'lecture_flow_from_planned_units','titles':['원문 제목']}
        self.assertEqual(p.complete(payload,**self.options),{'ok':True})
        self.assertEqual(p.complete(payload,**self.options),{'ok':True})
        self.assertEqual(self.opener.call_count,1)
        body=json.loads(self.opener.call_args.args[0].data)
        self.assertFalse(body['background'])
        self.assertEqual(len(body['input'][0]['content']),1)

    def test_expected_customer_hold_does_not_bypass_provider_budget(self):
        p=self.make();p.max_usd=0
        with self.assertRaises(ai.BudgetExceeded):p.complete(self.payload,**self.options)
        self.opener.assert_not_called()

    def test_desktop_hedge_uses_k120_progress_policy(self):
        p=self.make();p.study_no_id_hedge=True
        self.assertTrue(enabled(p,self.payload,{}))
        race=progress.FourAttemptRace(p,self.payload,{})
        self.assertEqual(race.backup_seconds,20)
        self.assertEqual(race.policy_metadata['hedgeDelaySeconds'],20)
        self.assertEqual(race.policy_metadata['hedgeMaxAttempts'],4)
        p.context['strategy']='newest-k1-1-3'
        self.assertEqual(progress.FourAttemptRace(p,self.payload,{}).backup_seconds,30)


class FourAttemptTests(unittest.TestCase):
    def test_eighty_real_slots_no_startup_overflow_and_hedge_keeps_rate_admission(self):
        from contextlib import ExitStack
        import pdf_api_slots as slots
        from pdf_study_concurrency import admission_options
        with TemporaryDirectory() as tmp, ExitStack() as held:
            for _ in range(80):held.enter_context(slots.api_slot(directory=tmp,parallel_limit=80))
            handle,priority=slots._slot(Path(tmp),None,80)
            self.assertIsNone(handle);self.assertFalse(priority)
            # Count-exempt repeats still traverse the account-token reservation.
            with patch.object(slots,'_allowed',wraps=slots._allowed) as rate:
                with slots.api_slot(directory=tmp,model='gpt-6-luna',input_tokens=10,
                                    **admission_options('newest-k1-2-5',hedge=True)) as admission:
                    self.assertTrue(rate.called)
                    self.assertTrue(admission.ticket)

    def test_k120_sends_at_most_four_and_healthy_output_retains_60_second_policy(self):
        with TemporaryDirectory() as tmp:
            p=SimpleNamespace(context={'strategy':'newest-k1-2-5','kind':'region_study'},
                              folder=Path(tmp),_lock=threading.RLock())
            calls=[]
            def complete(payload,**options):
                a=options['_hedge_attempt'];calls.append(a.index)
                a.update(networkPhase='uploading_request')
                while True:a.check();time.sleep(.002)
            p._complete_once=complete
            with patch.object(progress,'ATTEMPT_SECONDS',.06),patch.object(progress,'STALL_SECONDS',.03),patch.object(progress,'CHECK_SECONDS',.01):
                race=progress.FourAttemptRace(p,{'task':'region_teaching'},{});race.backup_seconds=.02
                with self.assertRaises(ai.AiResponseError) as got:race.run()
                self.assertTrue(got.exception.study_hedge_exhausted)
                self.assertEqual(calls,[0,1,2,3])
                for a in race.attempts:a.finished.wait(1)

if __name__=='__main__':unittest.main()
