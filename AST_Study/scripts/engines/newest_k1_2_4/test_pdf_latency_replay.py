"""Offline scheduling bounds, independent of provider responses or credentials."""
import unittest

from pdf_latency_replay import replay


def task(identity,prep=1,service=10,body=True,lag=0):
    return {'id':identity,'prepareSeconds':prep,'serviceSeconds':service,
            'hasLearnerBody':body,'uiLagSeconds':lag}


class LatencyReplayTests(unittest.TestCase):
    def test_one_worker_holds_its_slot_during_preparation_and_response(self):
        result=replay([task(str(i)) for i in range(3)],1)
        self.assertEqual(result['lastResponseSeconds'],33)
        self.assertEqual([r['sendSeconds'] for r in result['requests']],[1,12,23])

    def test_serial_preparation_and_parallel_responses_overlap(self):
        result=replay([task(str(i)) for i in range(3)],3)
        self.assertEqual(result['lastResponseSeconds'],13)
        self.assertEqual(result['firstLearnerUiSeconds'],11)

    def test_prefetch_all_finishes_before_network_starts(self):
        result=replay([task(str(i)) for i in range(3)],2,pipeline=False)
        self.assertEqual([r['sendSeconds'] for r in result['requests']],[3,3,13])
        self.assertEqual(result['lastResponseSeconds'],23)

    def test_ui_lag_is_separate_from_network_worker_occupancy(self):
        result=replay([task('first',lag=20),task('second')],1)
        self.assertEqual(result['lastResponseSeconds'],22)
        self.assertEqual(result['lastUiSeconds'],31)

    def test_navigation_does_not_count_as_first_learner_result(self):
        result=replay([task('cover',service=1,body=False),task('teaching',service=3)],2)
        self.assertEqual(result['firstLearnerUiSeconds'],5)
        self.assertIsNone(replay([task('cover',body=False)],2)['firstLearnerUiSeconds'])

    def test_more_workers_do_not_shorten_one_fixed_long_response(self):
        tasks=[task('tail',prep=.1,service=70)]+[task(str(i),prep=.1,service=2) for i in range(6)]
        self.assertEqual(replay(tasks,8)['lastResponseSeconds'],70.1)
        self.assertEqual(replay(tasks,32)['lastResponseSeconds'],70.1)

    def test_zero_duration_and_empty_input_are_bounded(self):
        self.assertEqual(replay([task(str(i),prep=0,service=0) for i in range(5)],2)['lastResponseSeconds'],0)
        self.assertEqual(replay([],2,start=5)['lastUiSeconds'],5)

    def test_invalid_duration_or_worker_count_is_rejected(self):
        for value in [-1,float('nan'),float('inf')]:
            with self.subTest(value=value),self.assertRaises(ValueError):replay([task('x',prep=value)],2)
        with self.assertRaises(ValueError):replay([task('x')],0)


if __name__=='__main__':unittest.main()
