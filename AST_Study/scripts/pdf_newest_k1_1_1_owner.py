"""Immutable local source-span ownership index; no I/O, model or source edits.

The mappings are read-only snapshots. Their record values and owner() results
refer to the original read-only source records, preserving the prior tie rule.
"""
from dataclasses import dataclass
import heapq
from types import MappingProxyType


@dataclass(frozen=True, slots=True, init=False)
class SourceIndex:
    positions: object
    by_id: object
    known: object
    structural_ids: frozenset
    promoted_ids: frozenset
    _owners: object

    def __init__(self, blocks, nodes):
        blocks = list(blocks)
        nodes = list(nodes)
        positions = {block['id']: index for index, block in enumerate(blocks)}
        by_id = {block['id']: block for block in blocks}
        known = {node['id']: node for node in nodes}
        structural_ids = frozenset(node['startBlockId'] for node in nodes
            if node.get('startBlockId') and node.get('sourceHeading') is not False)
        promoted_ids = frozenset(node['startBlockId'] for node in nodes
            if node.get('structuralRole') == 'numbered_heading' and node.get('startBlockId'))
        owners = self._sweep(blocks, nodes, positions, by_id)
        for name, value in [('positions', positions), ('by_id', by_id),
                            ('known', known), ('_owners', owners)]:
            object.__setattr__(self, name, MappingProxyType(value))
        object.__setattr__(self, 'structural_ids', structural_ids)
        object.__setattr__(self, 'promoted_ids', promoted_ids)

    def owner(self, ref):
        return self._owners.get(ref)

    @staticmethod
    def _sweep(blocks, nodes, positions, by_id):
        # A node is zone-restricted only on its own page and only when its
        # start block is present. On other pages it belongs to the unrestricted
        # foreign-page query, exactly as in the former per-reference scan.
        starts = []
        for order, node in enumerate(nodes):
            start = positions.get(node.get('startBlockId'), -1)
            end = positions.get(node.get('endBlockId'), len(blocks))
            if start <= end:
                starts.append((start, order, end))
        starts.sort()
        unrestricted = []
        by_page = {}
        by_zone = {}
        page_heads = []
        page_versions = {}
        cursor = 0
        owners = {}

        def prune(heap, at):
            while heap and heap[0][2] < at:
                heapq.heappop(heap)

        def publish(page, at):
            heap = by_page[page]
            prune(heap, at)
            version = page_versions.get(page, 0) + 1
            page_versions[page] = version
            if heap:
                priority, order, _ = heap[0]
                heapq.heappush(page_heads, (priority, order, version, page))

        def foreign_page_head(page, at):
            held = []
            try:
                while page_heads:
                    entry = page_heads[0]
                    priority, order, version, candidate_page = entry
                    if page_versions.get(candidate_page) != version:
                        heapq.heappop(page_heads)
                        continue
                    heap = by_page[candidate_page]
                    prune(heap, at)
                    if not heap or heap[0][:2] != (priority, order):
                        heapq.heappop(page_heads)
                        publish(candidate_page, at)
                        continue
                    if candidate_page == page:
                        held.append(heapq.heappop(page_heads))
                        continue
                    return (priority, order)
                return None
            finally:
                for entry in held:
                    heapq.heappush(page_heads, entry)

        for at, block in enumerate(blocks):
            while cursor < len(starts) and starts[cursor][0] <= at:
                _, order, end = starts[cursor]
                cursor += 1
                node = nodes[order]
                entry = (-node['level'], order, end)
                start_block = by_id.get(node.get('startBlockId'))
                if start_block is None or node.get('sourceKind')=='planned_topic':
                    heapq.heappush(unrestricted, entry)
                else:
                    page = node.get('page')
                    zone = start_block.get('zone', 0)
                    heapq.heappush(by_page.setdefault(page, []), entry)
                    heapq.heappush(by_zone.setdefault((page, zone), []), entry)
                    publish(page, at)
            # Duplicate source IDs retain the last block/position, just as the
            # original dictionary comprehensions did. Earlier copies have no ref.
            if positions[block['id']] != at:
                continue
            page = block['page']
            zone_heap = by_zone.get((page, block.get('zone', 0)), [])
            prune(zone_heap, at)
            prune(unrestricted, at)
            candidates = [heap[0][:2] for heap in (unrestricted, zone_heap) if heap]
            foreign = foreign_page_head(page, at)
            if foreign is not None:
                candidates.append(foreign)
            owners[block['id']] = nodes[min(candidates)[1]] if candidates else None
        return owners
