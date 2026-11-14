import copy
from dataclasses import FrozenInstanceError
import random
import unittest

from pdf_source_owner_index import SourceIndex


def brute_owner(ref, blocks, nodes):
    positions = {block['id']: i for i, block in enumerate(blocks)}
    by_id = {block['id']: block for block in blocks}
    if ref not in positions:
        return None
    at = positions[ref]
    block = by_id[ref]
    candidates = [node for node in nodes
        if positions.get(node.get('startBlockId'), -1) <= at
        <= positions.get(node.get('endBlockId'), len(blocks))
        and (node.get('page') != block['page'] or node.get('startBlockId') not in by_id
             or by_id[node['startBlockId']].get('zone', 0) == block.get('zone', 0))]
    return max(candidates, key=lambda node: node['level']) if candidates else None


def block(i, page=1, zone=0):
    return {'id': 'b'+str(i), 'page': page, 'zone': zone, 'kind': 'text'}


def node(i, start, end, level=1, page=1, **extra):
    return {'id': 'h'+str(i), 'startBlockId': start, 'endBlockId': end,
            'level': level, 'page': page, 'sourceHeading': True, **extra}


class SourceIndexTests(unittest.TestCase):
    def compare(self, blocks, nodes):
        before_blocks = copy.deepcopy(blocks)
        before_nodes = copy.deepcopy(nodes)
        index = SourceIndex(blocks, nodes)
        for ref in [b['id'] for b in blocks] + ['not-in-this-job']:
            self.assertIs(index.owner(ref), brute_owner(ref, blocks, nodes), ref)
        self.assertEqual(blocks, before_blocks)
        self.assertEqual(nodes, before_nodes)
        self.assertEqual(dict(index.positions), {b['id']: i for i, b in enumerate(blocks)})
        self.assertEqual(dict(index.by_id), {b['id']: b for b in blocks})
        self.assertEqual(dict(index.known), {n['id']: n for n in nodes})
        return index

    def test_nested_spans_gaps_and_first_node_wins_level_ties(self):
        blocks = [block(i) for i in range(12)]
        nodes = [node('root', 'b0', 'b10'), node('first', 'b2', 'b5', 3),
                 node('tie', 'b3', 'b8', 3), node('deep', 'b4', 'b4', 4),
                 node('single', 'b10', 'b10', 2)]
        index = self.compare(blocks, nodes)
        self.assertIs(index.owner('b3'), nodes[1])
        self.assertIs(index.owner('b6'), nodes[2])
        self.assertIsNone(index.owner('b11'))

    def test_same_page_zone_filter_and_cross_page_unrestricted_continuation(self):
        blocks = [block(0, 1, 0), block(1, 1, 1), block(2, 1, 0),
                  block(3, 2, 1), block(4, 2, 0), block(5, 3, 0)]
        nodes = [node('left', 'b0', 'b5', 4, 1),
                 node('right', 'b1', 'b5', 3, 1),
                 node('next', 'b3', 'b5', 2, 2)]
        index = self.compare(blocks, nodes)
        self.assertIs(index.owner('b1'), nodes[1])
        self.assertIs(index.owner('b2'), nodes[0])
        self.assertIs(index.owner('b3'), nodes[0])

    def test_job_subset_missing_boundaries_preserves_fallbacks(self):
        blocks = [block(i, 3, i % 2) for i in range(3, 8)]
        nodes = [node('ancestor', 'outside-before', 'outside-after', 1, 1),
                 node('left', 'b3', 'outside-after', 3, 3),
                 node('early-end', 'outside-before', 'b4', 4, 3),
                 node('reversed', 'b7', 'b3', 10, 3)]
        index = self.compare(blocks, nodes)
        self.assertIs(index.owner('b4'), nodes[2])
        self.assertIn('outside-before', index.structural_ids)

    def test_duplicate_ids_and_omitted_zone_keep_old_dictionary_behavior(self):
        blocks = [block(0, 1, 0), block(1, 1, 1), block(0, 2, 1)]
        blocks[1].pop('zone')
        nodes = [node('same', 'b0', 'missing', 2, 1),
                 node('same', 'b1', 'missing', 2, 2),
                 node('unknown-start', None, None, 1, None)]
        self.compare(blocks, nodes)

    def test_mappings_and_structure_membership_are_read_only(self):
        blocks = [block(0)]
        nodes = [node('source', 'b0', 'b0'),
                 node('generated', 'not-source', 'b0', sourceHeading=False),
                 {'id': 'option', 'startBlockId': 'outside', 'level': 1, 'page': 1}]
        index = self.compare(blocks, nodes)
        for mapping in [index.positions, index.by_id, index.known]:
            with self.assertRaises(TypeError):
                mapping['new'] = 1
        with self.assertRaises(FrozenInstanceError):
            index.positions = {}
        self.assertEqual(index.structural_ids, frozenset({'b0', 'outside'}))

    def test_empty_document_and_empty_nodes(self):
        self.compare([], [])
        self.compare([block(0)], [])
        self.compare([], [node(0, 'missing', 'missing')])

    def test_randomized_intervals_match_prior_scan_exactly(self):
        randomizer = random.Random(20261028)
        for case in range(200):
            size = randomizer.randrange(1, 90)
            blocks = [block(i, randomizer.randrange(1, 6), randomizer.randrange(3))
                      for i in range(size)]
            nodes = []
            choices = [b['id'] for b in blocks] + ['missing-start', 'missing-end', None]
            for i in range(randomizer.randrange(0, 100)):
                nodes.append(node(i, randomizer.choice(choices), randomizer.choice(choices),
                                  randomizer.randrange(1, 8), randomizer.randrange(1, 6)))
            with self.subTest(case=case):
                self.compare(blocks, nodes)


if __name__ == '__main__':
    unittest.main()
