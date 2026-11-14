"""Sparse cache-hot history must not underquote a different cold workload."""
import copy
import unittest
from pdf_newest_k1_2_0_cost import estimate


class CostHistoryTests(unittest.TestCase):
    def setUp(self):
        self.work = {
            'region_plan': {'input': 12000, 'output': 1000},
            'region_study': {'input': 100000, 'output': 15000},
            'summary_reduce': {'input': 2000, 'output': 200},
            'details': {'pages': 10, 'fragments': 100,
                        'sourceTokenProxy': 30000, 'effectiveImageTokenProxy': 40000,
                        'imageTokenProxy': 40000}}
        self.baseline = estimate({}, [], [], work=self.work)

    def sample(self):
        return {'workload': copy.deepcopy(self.work), 'stageUsage': {
            k: {'usageBasedUsd': .00001, 'inputTokens': 1, 'outputTokens': 1}
            for k in ('region_plan', 'region_study', 'summary_reduce')}}

    def test_one_or_two_cache_hot_receipts_cannot_shrink_cold_price_or_tokens(self):
        for count in (1, 2):
            result = estimate({}, [], [self.sample() for _ in range(count)], work=self.work)
            self.assertEqual(result['usd'], self.baseline['usd'])
            self.assertEqual(result['tokens'], self.baseline['tokens'])
            self.assertEqual(result['sampleCount'], count)

    def test_unrelated_single_fragment_slides_cannot_calibrate_fragmented_source(self):
        sample = self.sample()
        sample['workload']['details']['fragments'] = 10
        result = estimate({}, [], [sample] * 4, work=self.work)
        self.assertEqual(result['sampleCount'], 0)
        self.assertEqual(result['usd'], self.baseline['usd'])


if __name__ == '__main__':
    unittest.main()
