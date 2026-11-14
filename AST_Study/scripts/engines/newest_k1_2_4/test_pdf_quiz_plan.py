"""Offline arithmetic recovery for otherwise valid quiz planner output."""
import copy
import unittest

import pdf_quiz as quiz


def row(uid, counts, concepts=None):
    return {'unitId': uid, 'conceptIds': concepts or ['c1'],
            'counts': dict(zip(quiz.TYPES, counts)), 'focus': '조건과 개념의 구별'}


def response(rows, unallocated=0):
    return {'allocations': rows, 'unallocated': unallocated, 'reason': ''}


def amount(plan):
    return sum(sum(a['counts'].values()) for a in plan['allocations'])


class QuizPlanCountTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [{'id': 'c' + str(i)} for i in range(1, 29)]
        self.config = {'totalCount': 10, 'allowedTypes': list(quiz.TYPES)}

    def normalize(self, plan, total=10, allowed=None):
        config = {**self.config, 'totalCount': total}
        if allowed is not None:
            config['allowedTypes'] = allowed
        return quiz.validate_plan(plan, self.catalog, config)

    def actual_shape(self):
        # The real settled planner allocated 3+3+3+2+2 for a ten-question request.
        # Only its numeric shape and opaque concept IDs are needed for replay.
        return response([
            row('group-a', [0, 2, 0, 1], ['c2', 'c3', 'c4']),
            row('group-b', [1, 1, 1, 0], ['c5', 'c6', 'c7']),
            row('group-c', [1, 1, 0, 1], ['c8', 'c9', 'c10']),
            row('group-d', [0, 1, 1, 0], ['c14', 'c15', 'c16', 'c17']),
            row('group-e', [0, 1, 0, 1], ['c20', 'c21', 'c22']),
        ])

    def test_real_thirteen_to_ten_preserves_five_scopes_and_input(self):
        raw = self.actual_shape()
        original = copy.deepcopy(raw)
        plan = self.normalize(raw)
        self.assertEqual(raw, original)
        self.assertEqual(amount(plan), 10)
        self.assertEqual([sum(a['counts'].values()) for a in plan['allocations']], [2] * 5)
        self.assertEqual(plan['countAdjustment'], {'allocatedBefore': 13, 'allocatedAfter': 10})
        for old, new in zip(raw['allocations'], plan['allocations']):
            self.assertEqual(new['unitId'], old['unitId'])
            self.assertEqual(new['conceptIds'], old['conceptIds'])
            self.assertEqual(new['focus'], old['focus'])
            for kind in quiz.TYPES:
                self.assertIs(type(new['counts'][kind]), int)
                self.assertGreaterEqual(new['counts'][kind], 0)
                if not old['counts'][kind]:
                    self.assertEqual(new['counts'][kind], 0)

    def test_underallocation_seven_to_ten_uses_integer_largest_remainders(self):
        raw = response([row(str(i), [0, n, 0, 0]) for i, n in enumerate([2, 2, 1, 1, 1])])
        plan = self.normalize(raw)
        self.assertEqual([a['counts']['mcq'] for a in plan['allocations']], [3, 3, 2, 1, 1])
        self.assertEqual(amount(plan), 10)
        self.assertEqual(plan['countAdjustment'], {'allocatedBefore': 7, 'allocatedAfter': 10})

    def test_fewer_questions_than_groups_does_not_create_zero_rows(self):
        plan = self.normalize(self.actual_shape(), total=2)
        self.assertEqual(amount(plan), 2)
        self.assertEqual(len(plan['allocations']), 2)
        self.assertEqual([a['unitId'] for a in plan['allocations']], ['group-a', 'group-b'])
        self.assertTrue(all(sum(a['counts'].values()) == 1 for a in plan['allocations']))

    def test_preserves_small_scope_when_enough_questions(self):
        plan = self.normalize(response([row('large', [0, 49, 0, 0]), row('small', [0, 1, 0, 0])]), total=5)
        self.assertEqual([a['counts']['mcq'] for a in plan['allocations']], [4, 1])

    def test_exact_allocation_is_unchanged_and_has_no_adjustment(self):
        raw = response([row('a', [1, 2, 1, 1]), row('b', [1, 2, 1, 1])])
        self.assertEqual(self.normalize(raw), raw)
        self.assertNotIn('countAdjustment', self.normalize(raw))

    def test_explicit_unallocated_is_preserved(self):
        raw = self.actual_shape()
        raw['unallocated'] = 2
        raw['reason'] = '일부 자료의 근거 부족'
        plan = self.normalize(raw)
        self.assertEqual(amount(plan), 8)
        self.assertEqual(plan['unallocated'], 2)
        self.assertEqual(plan['reason'], raw['reason'])
        self.assertEqual(plan['countAdjustment']['allocatedAfter'], 8)

    def test_all_explicitly_unallocated_has_no_execution_rows(self):
        raw = self.actual_shape()
        raw['unallocated'] = 10
        plan = self.normalize(raw)
        self.assertEqual(plan['allocations'], [])
        self.assertEqual(plan['unallocated'], 10)

    def test_zero_allocation_rows_are_removed_without_inventing_scopes(self):
        empty = row('empty', [0, 0, 0, 0])
        empty['focus'] = ''
        plan = self.normalize(response([empty, row('usable', [0, 10, 0, 0])]))
        self.assertEqual([a['unitId'] for a in plan['allocations']], ['usable'])
        self.assertNotIn('countAdjustment', plan)
        with self.assertRaises(ValueError):
            self.normalize(response([empty]))

    def test_disabled_format_and_unknown_concepts_are_not_repaired(self):
        with self.assertRaises(ValueError):
            self.normalize(self.actual_shape(), allowed=['mcq'])
        raw = self.actual_shape()
        raw['allocations'][0]['conceptIds'] = ['foreign']
        with self.assertRaises(ValueError):
            self.normalize(raw)
        with self.assertRaises(ValueError):
            self.normalize(response([row('empty', [0, 0, 0, 0], ['foreign'])]))

    def test_invalid_counts_and_unallocated_are_not_repaired(self):
        for invalid in (-1, True, 121, '2', 1.5):
            raw = self.actual_shape()
            raw['allocations'][0]['counts']['mcq'] = invalid
            with self.subTest(count=invalid), self.assertRaises(ValueError):
                self.normalize(raw)
        for invalid in (-1, True, 11):
            raw = self.actual_shape()
            raw['unallocated'] = invalid
            with self.subTest(unallocated=invalid), self.assertRaises(ValueError):
                self.normalize(raw)

    def test_duplicate_group_or_concept_membership_inside_group_is_not_repaired(self):
        raw = self.actual_shape()
        raw['allocations'][1]['unitId'] = raw['allocations'][0]['unitId']
        with self.assertRaises(ValueError):
            self.normalize(raw)
        raw = self.actual_shape()
        raw['allocations'][0]['conceptIds'] = ['c2', 'c2']
        with self.assertRaises(ValueError):
            self.normalize(raw)


if __name__ == '__main__':
    unittest.main()
