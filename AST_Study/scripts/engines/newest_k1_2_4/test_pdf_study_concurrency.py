"""Offline admission checks for expanded K1 variants and their one-off hedges."""
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import pdf_api_slots as slots
from pdf_study_concurrency import admission_options
from pdf_study_hedge import copy_context
from test_pdf_api_slots import _cancel_wait, _hold


class ExpandedConcurrencyTests(unittest.TestCase):
    def assert_waits(self, directory, **kwargs):
        with self.assertRaises(InterruptedError):
            with slots.api_slot(_cancel_wait(), directory, parallel_limit=20, **kwargs):
                self.fail('unexpected admission')

    def test_twenty_normal_requests_then_hedge_bypasses_count_but_records_rate(self):
        with TemporaryDirectory()as directory, ExitStack()as stack:
            for _ in range(20):
                stack.enter_context(slots.api_slot(directory=directory,parallel_limit=20))
            self.assert_waits(directory)
            with slots.api_slot(directory=directory,parallel_limit=20,count_parallel=False,
                                model='gpt-6-luna',input_tokens=10)as admission:
                self.assertIsNotNone(admission)
                self.assertTrue(admission.ticket)
                self.assert_waits(directory)
            self.assert_waits(directory)

    def test_startup_twenty_two_then_drain_to_twenty(self):
        with TemporaryDirectory()as directory, ExitStack()as stack:
            priority=stack.enter_context(slots.startup_priority_slots(directory))
            release_priority=_hold(stack,slots.api_slot(directory=directory,parallel_limit=20,priority=priority))
            _hold(stack,slots.api_slot(directory=directory,parallel_limit=20,priority=priority))
            releases=[_hold(stack,slots.api_slot(directory=directory,parallel_limit=20))for _ in range(20)]
            self.assert_waits(directory)
            priority.close()
            release_priority();releases[0]()
            self.assert_waits(directory)  # 20 still active
            releases[1]()
            with slots.api_slot(directory=directory,parallel_limit=20):pass

    def test_uncounted_hedge_still_waits_for_tpm_rpm_admission(self):
        with TemporaryDirectory()as directory, patch.object(slots,'_allowed',return_value=False)as allowed:
            self.assert_waits(directory,count_parallel=False,model='gpt-6-luna',input_tokens=500)
            self.assertTrue(allowed.called)

    def test_engine_scope_and_shared_startup_capability(self):
        import pdf_newest_k1 as k1
        import pdf_newest_k11 as k11
        import pdf_newest_k111 as k111
        import pdf_newest_k1_1_1 as k1_1_1
        self.assertEqual((k1.MAX_STUDY_WORKERS,k1.MAX_STARTUP_WORKERS),(14,16))
        self.assertEqual(admission_options('newest-k1',hedge=True),{})
        for engine in (k11,k111):
            self.assertEqual((engine.MAX_STUDY_WORKERS,engine.MAX_STARTUP_WORKERS),(20,22))
            self.assertEqual(admission_options(engine.STRATEGIES[0]),{'parallel_limit':20,'count_parallel':True})
            self.assertEqual(admission_options(engine.STRATEGIES[0],hedge=True),{'parallel_limit':20,'count_parallel':False})
        self.assertEqual((k1_1_1.MAX_STUDY_WORKERS,k1_1_1.MAX_STARTUP_WORKERS),(60,60))
        self.assertEqual(k1_1_1.TRANSPORT_BATCH_UNITS,1)
        for flags in ({},{'hedge':True},{'overview':True}):
            self.assertEqual(admission_options(k1_1_1.STRATEGIES[0],**flags),{'parallel_limit':60,'count_parallel':not flags.get('hedge',False)})
        with TemporaryDirectory()as directory, slots.startup_priority_slots(directory)as priority:
            source={'_startup_priority':priority,'pages':[1,2]}
            copied=copy_context(source)
            self.assertIs(copied['_startup_priority'],priority)
            copied['pages'].append(3)
            self.assertEqual(source['pages'],[1,2])

    def test_sixty_cap_includes_startup_and_overview_but_exempts_retries(self):
        with TemporaryDirectory()as directory, ExitStack()as stack:
            priority=stack.enter_context(slots.startup_priority_slots(directory))
            releases=[_hold(stack,slots.api_slot(directory=directory,parallel_limit=60))for _ in range(60)]
            for flags in ({},{'overview':True}):
                with self.assertRaises(InterruptedError):
                    with slots.api_slot(_cancel_wait(),directory,priority=priority,
                                        **admission_options('newest-k1-1-1',**flags)):
                        self.fail('61st request was admitted')
            with slots.api_slot(directory=directory,**admission_options('newest-k1-1-2',hedge=True)):pass
            releases[0]()
            with slots.api_slot(directory=directory,parallel_limit=60):pass

    def test_http_pool_allows_twenty_two_plus_extra_connections(self):
        from concurrent.futures import ThreadPoolExecutor
        import json,time,urllib.request
        from pdf_study_http import StudyHttpTransport
        from test_pdf_study_pooled_http import server
        with server('control')as(url,calls,_,release):
            transport=StudyHttpTransport(max_connections=22,allow_overflow=True)
            def call():
                request=urllib.request.Request(url,data=b'{"ok":true}',method='POST')
                with transport.open(request,5)as reply:return json.load(reply)
            try:
                with ThreadPoolExecutor(max_workers=24)as pool:
                    futures=[pool.submit(call)for _ in range(24)]
                    try:
                        deadline=time.monotonic()+2.5
                        while len(calls)<24 and time.monotonic()<deadline:time.sleep(.01)
                        self.assertEqual(len(calls),24)
                    finally:release.set()
                    self.assertEqual([f.result()for f in futures],[{'ok':True}]*24)
            finally:transport.close()


if __name__=='__main__':unittest.main()
