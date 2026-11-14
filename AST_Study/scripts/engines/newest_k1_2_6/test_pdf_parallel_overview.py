import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from pdf_parallel_overview import ParallelOverview
from pdf_pipeline import write_json, read_json_cache
from pdf_study_concurrency import admission_options
from pdf_api_slots import api_slot


class ParallelOverviewTests(unittest.TestCase):
    def test_late_overview_keeps_published_units_and_future_units_keep_overview(self):
        with TemporaryDirectory()as tmp,ThreadPoolExecutor(max_workers=1)as pool:
            path=Path(tmp)/'partial.json'
            initial={'overview':{'body':'loading'},'sections':[]}
            write_json(path,initial)
            release=Event();events=[]
            overview=ParallelOverview(initial['overview'],path,emit=lambda *args,**kw:events.append(args),metadata={})
            def generate():
                if not release.wait(3):raise AssertionError('test timed out')
                return {'body':'completed flow'}
            overview.start(pool,generate)
            try:
                overview.publish({'sections':['first unit']},lambda _:None)
                self.assertEqual(read_json_cache(path)['sections'],['first unit'])
            finally:release.set()
            overview.result()
            self.assertEqual(read_json_cache(path),{'overview':{'body':'completed flow'},'sections':['first unit']})
            overview.publish({'sections':['first unit','second unit']},lambda _:None)
            self.assertEqual(read_json_cache(path)['overview'],{'body':'completed flow'})
            self.assertEqual(events,[('summary_overview_ready',)])

    def test_overview_admission_works_when_all_twenty_two_slots_are_full(self):
        from pdf_api_slots import startup_priority_slots
        with TemporaryDirectory()as tmp,ExitStack()as stack:
            priority=stack.enter_context(startup_priority_slots(tmp))
            for _ in range(2):stack.enter_context(api_slot(directory=tmp,parallel_limit=20,priority=priority))
            for _ in range(20):stack.enter_context(api_slot(directory=tmp,parallel_limit=20))
            for strategy in ('newest-k1-1','newest-k1-1-1'):
                with api_slot(directory=tmp,**admission_options(strategy,overview=True)):pass
            self.assertTrue(admission_options('newest-k1-11',overview=True)['count_parallel'])


if __name__=='__main__':unittest.main()
