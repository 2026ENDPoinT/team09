"""Offline timing and terminal-recovery regressions for K1.1.2."""
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pdf_study_progress_attempts as policy
from pdf_study_idle_watch import IdleStatusWatch
from test_pdf_stream_resume import request
from test_pdf_responses_transport import native


class ProgressAttemptsTest(unittest.TestCase):
    def setUp(self):
        self.race=SimpleNamespace(lock=threading.RLock(),winner=None)
        self.a=policy.TimedAttempt(self.race,0)
        self.a.sent=0
        self.a._interrupt_read=Mock()
        self.a.bind_status_probe(Mock(return_value=False))
        self.clock=patch.object(policy.time,'monotonic',return_value=60).start()
        self.addCleanup(patch.stopall)

    def wait_probe(self):
        for _ in range(100):
            with self.race.lock:
                if not self.a.probing:return
            time.sleep(.002)
        self.fail('probe did not finish')

    def test_ongoing_output_survives_and_is_checked_again_every_ten_seconds(self):
        self.clock.return_value=59
        self.a.update(finalTextChars=10)
        self.clock.return_value=60
        self.a.check()  # no old unconditional deadline
        self.assertTrue(self.a.check_stall(60))
        self.assertFalse(self.a.check_stall(61))
        self.clock.return_value=61
        self.a.update(finalTextChars=11)
        for now in (70,80,90):
            self.clock.return_value=now
            self.assertTrue(self.a.check_stall(now))
            self.assertIsNone(self.a.stop_reason)
        self.a.status_probe.assert_not_called()
        self.clock.return_value=100
        self.assertTrue(self.a.check_stall(100))
        self.wait_probe()
        self.assertTrue(self.a.expired)
        self.a.status_probe.assert_called_once()

    def test_heartbeats_and_unchanged_counts_do_not_extend_request(self):
        self.a.update(networkPhase='receiving_events',lastEventType='keepalive',finalTextChars=0)
        self.a.check_stall(60);self.wait_probe()
        self.assertTrue(self.a.expired)

    def test_completed_lookup_preserves_request_for_normal_validation(self):
        self.a.status_probe.return_value=True
        self.a.check_stall(60);self.wait_probe()
        self.assertTrue(self.a.terminal_pending)
        self.assertFalse(self.a.expired)

    def test_output_resuming_during_lookup_prevents_cancellation(self):
        def probe():
            self.a.update(finalTextChars=12)
            return False
        self.a.bind_status_probe(probe)
        self.a.check_stall(60);self.wait_probe()
        self.assertIsNone(self.a.stop_reason)
        self.clock.return_value=100
        self.a.check_stall(100);self.wait_probe()
        self.assertTrue(self.a.expired)  # same count is not new output

    def test_missing_id_or_failed_status_read_still_replaces_stall(self):
        self.a.bind_status_probe(None)
        self.a.check_stall(60);self.wait_probe()
        self.assertTrue(self.a.expired)

    def test_elapsed_time_is_per_attempt_and_starts_after_admission(self):
        self.a.sent=None
        self.assertFalse(self.a.check_stall(1000))
        self.a.sent=1000
        self.assertFalse(self.a.check_stall(1059))


class RaceLimitTest(unittest.TestCase):
    def test_four_attempt_limit_and_no_fifth_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=SimpleNamespace(context={'strategy':'newest-k1-1-2','kind':'region_study'},
                              folder=Path(tmp),_lock=threading.RLock())
            calls=[]
            def complete(payload,**options):
                a=options['_hedge_attempt'];calls.append(a.index)
                a.update(networkPhase='uploading_request')
                while True:
                    a.check();time.sleep(.002)
            p._complete_once=complete
            with patch.object(policy,'BACKUP_SECONDS',.02),patch.object(policy,'ATTEMPT_SECONDS',.05), \
                    patch.object(policy,'STALL_SECONDS',.025),patch.object(policy,'CHECK_SECONDS',.01):
                race=policy.FourAttemptRace(p,{'task':'region_teaching'}, {})
                with self.assertRaises(Exception) as got:race.run()
                self.assertTrue(got.exception.study_hedge_exhausted)
                self.assertEqual(calls,[0,1,2,3])
                for a in race.attempts:a.finished.wait(1)

    def test_legacy_keeps_original_deadline_and_new_version_keeps_race_contract(self):
        import pdf_study_attempts as old
        import pdf_newest_k1_1_1 as k111
        import pdf_newest_k1_1_2 as k112
        from pdf_study_concurrency import admission_options
        self.assertNotEqual(old.FourAttemptRace.policy_metadata,policy.FourAttemptRace.policy_metadata)
        self.assertIn('SOURCE ACCOUNTING AND SEMANTIC CHECK',k112.STUDY_PROMPT)
        self.assertEqual(k111.PLAN_PROMPT,k112.PLAN_PROMPT)
        self.assertEqual(k112.TRANSPORT_BATCH_UNITS,1)
        self.assertEqual(k112.MAX_STUDY_WORKERS,60)
        self.assertEqual(admission_options('newest-k1-1-2',hedge=True),
                         {'parallel_limit':60,'count_parallel':False})


class StatusProbeTest(unittest.TestCase):
    def test_completed_receipt_interrupts_stream_for_existing_validation_path(self):
        opener=Mock(return_value=io.StringIO(json.dumps(native())))
        watch=IdleStatusWatch(request(),SimpleNamespace(),open_url=opener,
            update=Mock(),check=lambda:None,clock=time.monotonic,timeout=15)
        watch.response_id=native()['id'];watch._interrupt_read=Mock()
        self.assertTrue(watch.recover_now())
        self.assertEqual(watch.native,native())
        self.assertEqual(opener.call_args.kwargs['timeout'],6)
        self.assertEqual(opener.call_args.args[0].method,'GET')
        watch._interrupt_read.assert_called_once()

    def test_wrong_response_id_is_not_accepted(self):
        watch=IdleStatusWatch(request(),SimpleNamespace(),
            open_url=lambda *a,**kw:io.StringIO(json.dumps({**native(),'id':'resp_wrong'})),
            update=Mock(),check=lambda:None,clock=time.monotonic,timeout=6)
        watch.response_id=native()['id']
        self.assertFalse(watch.recover_now())
        self.assertIsNone(watch.native)

if __name__=='__main__':unittest.main()
