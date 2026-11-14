"""Source-preserving local repair of parsed grouping assignments, without APIs.

A complete partition certifies source accounting, not semantic correctness.
Transport/network/JSON parsing failures must be handled by the caller and never
converted into a successful model plan by this module.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json

VERSION = 'exact-source-partition-v1'
ROLES = frozenset(('teaching', 'illustration', 'exercise', 'navigation', 'uncertain'))
# These are local annotations, not source text/geometry. Other source fields
# must compare exactly when a cached partition is checked against extraction.
_ANNOTATIONS = frozenset(('planRole', 'planRoleBeforeVisualGuard', 'visualReadingRequired'))


class PartitionError(ValueError):
    pass


class PartitionFormatError(PartitionError):
    pass


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _canonical(targets):
    if not isinstance(targets, list) or any(not isinstance(b, dict) for b in targets):
        raise PartitionError('원문 조각 목록 형식이 올바르지 않아요.')
    ids = [b.get('id') for b in targets]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise PartitionError('원문 조각 ID가 비어 있거나 중복돼요.')
    return ids


def _source(block):
    return {k: v for k, v in block.items() if k not in _ANNOTATIONS}


def validate_partition(targets, groups, *, require_global_order=True):
    """Reject missing/extra/duplicate/reordered/modified sources before reuse.

    The caller supplies current canonical extraction, not a list derived from
    the cached groups themselves. The proof deliberately contains no prose.
    """
    ids = _canonical(targets)
    if not isinstance(groups, list):
        raise PartitionError('원문 묶음 목록 형식이 올바르지 않아요.')
    flattened = []
    positions = {key: index for index, key in enumerate(ids)}
    for group in groups:
        if (not isinstance(group, dict) or not isinstance(group.get('blocks'), list)
                or not group['blocks'] or any(not isinstance(b, dict) for b in group['blocks'])):
            raise PartitionError('원문 묶음에 비어 있거나 잘못된 조각 목록이 있어요.')
        group_ids = [b.get('id') for b in group['blocks']]
        if (any(not isinstance(key, str) or key not in positions for key in group_ids)
                or [positions[key] for key in group_ids] != sorted(positions[key] for key in group_ids)):
            raise PartitionError('원문 묶음 내부의 ID·순서가 원문과 일치하지 않아요.')
        flattened.extend(group['blocks'])
    actual = [b.get('id') for b in flattened]
    if (len(actual) != len(ids) or set(actual) != set(ids)
            or len(set(actual)) != len(actual) or require_global_order and actual != ids):
        raise PartitionError('원문 묶음의 ID·횟수·순서가 원문과 일치하지 않아요.')
    source_digest = _digest([_source(b) for b in targets])
    assigned_digest = _digest([_source(b) for b in sorted(flattened, key=lambda b: positions[b['id']])])
    if source_digest != assigned_digest:
        raise PartitionError('원문 묶음의 내용이나 위치가 원문과 달라요.')
    return {'complete': True, 'sourceCount': len(ids), 'assignedCount': len(actual),
            'sourceIdsDigest': _digest(ids), 'sourceDigest': source_digest,
            'assignedSourceDigest': assigned_digest, 'orderPreserved': actual == ids,
            'eachGroupSourceOrderPreserved': True}


def _groups(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('groups'), list):
        raise PartitionFormatError('묶음 응답의 groups 목록 형식이 올바르지 않아요.')
    return raw['groups']


def recover_ranges(raw, targets):
    """Expand only valid exact integer intervals; never clip or guess an index.

    Gaps/overlaps are left for repair_partition. The existing strict public
    pdf_group_transport.expand contract remains unchanged.
    """
    ids = _canonical(targets)
    converted = []
    diagnostics = []
    for index, group in enumerate(_groups(raw)):
        if not isinstance(group, dict):
            diagnostics.append({'groupIndex': index, 'reason': 'malformed_group'})
            continue
        first, last = group.get('first'), group.get('last')
        if (type(first) is not int or type(last) is not int
                or not 0 <= first <= last < len(ids)):
            diagnostics.append({'groupIndex': index, 'reason': 'invalid_exact_interval'})
            continue
        value = copy.deepcopy(group)
        value.pop('first', None)
        value.pop('last', None)
        value['blockIds'] = ids[first:last+1]
        # Dropping an invalid earlier range must not promote a later group's
        # continuation claim into a seemingly clean first-group continuation.
        value['continuesPrevious'] = (index == 0 and first == 0
                                       and group.get('continuesPrevious') is True)
        converted.append(value)
    return {'groups': converted}, {'version': VERSION, 'transport': 'ranges',
                                   'invalidRangeGroups': diagnostics,
                                   'sourceTargetCount': len(ids)}


def repair_partition(raw, targets, *, furniture_ids=()):
    """Retain unambiguous exact model owners and preserve all other sources.

    Cross-group conflicts never use first-wins ownership. Missing/conflicting
    sources form local uncertain runs on the same page/zone. Only independently
    supplied furniture IDs or actual page_number kinds may be decoration.
    Inputs and their source payloads are never mutated.
    """
    ids = _canonical(targets)
    positions = {key: index for index, key in enumerate(ids)}
    supplied = _groups(raw)
    owners = {key: set() for key in ids}
    specs = {}
    diagnostics = []
    for index, group in enumerate(supplied):
        if not isinstance(group, dict):
            diagnostics.append({'groupIndex': index, 'reason': 'malformed_group'})
            continue
        members = group.get('blockIds')
        if not isinstance(members, list):
            diagnostics.append({'groupIndex': index, 'reason': 'invalid_id_list'})
            continue
        clean = True
        unique = []
        seen = set()
        for key in members:
            if not isinstance(key, str):
                diagnostics.append({'groupIndex': index, 'reason': 'invalid_id_type'})
                clean = False
            elif key not in positions:
                diagnostics.append({'groupIndex': index, 'reason': 'unknown_id', 'blockId': key})
                clean = False
            elif key in seen:
                diagnostics.append({'groupIndex': index, 'reason': 'same_group_repeat', 'blockId': key})
                clean = False
            else:
                seen.add(key)
                unique.append(key)
                owners[key].add(index)
        if [positions[key] for key in unique] != sorted(positions[key] for key in unique):
            diagnostics.append({'groupIndex': index, 'reason': 'source_order_restored'})
            clean = False
        title = group.get('title')
        if not isinstance(title, str) or not title.strip():
            title = '학습 내용'
            diagnostics.append({'groupIndex': index, 'reason': 'invalid_title'})
            clean = False
        role = group.get('role')
        if not isinstance(role, str) or role not in ROLES:
            role = 'uncertain'
            diagnostics.append({'groupIndex': index, 'reason': 'invalid_role'})
            clean = False
        specs[index] = {'title': title, 'role': role, 'clean': clean,
                        'continuesPrevious': group.get('continuesPrevious') is True}

    furniture = {key for key in furniture_ids if isinstance(key, str) and key in positions}
    # Preserve healthy paid assignments byte-for-byte in their teaching role.
    # Legacy routing always overrode independently verified running margins,
    # but page_number kinds became decoration only when locally recovered.
    furniture.update(b['id'] for b in targets
                     if b.get('kind') == 'page_number' and len(owners[b['id']]) != 1)
    missing = [key for key in ids if not owners[key]]
    ambiguous = [key for key in ids if len(owners[key]) > 1]
    missing_set, ambiguous_set = set(missing), set(ambiguous)
    labels = [next(iter(owners[key])) if len(owners[key]) == 1 else None for key in ids]
    # A recovered page number/header may join a definite neighbor as structural
    # bookkeeping. It must not split an otherwise intact paid teaching topic.
    for at, key in enumerate(ids):
        if key not in furniture or labels[at] is not None:
            continue
        neighbor = next((labels[j] for j in range(at+1, len(ids)) if labels[j] is not None), None)
        if neighbor is None:
            neighbor = next((labels[j] for j in range(at-1, -1, -1) if labels[j] is not None), None)
        labels[at] = neighbor

    groups = []
    previous = None
    for at, original in enumerate(targets):
        key = original['id']
        owner = labels[at]
        is_furniture = key in furniture
        if owner is not None:
            label = ('ai', owner)
            spec = specs[owner]
            role = 'decoration' if is_furniture else spec['role']
            title, origin = spec['title'], 'ai'
        else:
            reason = 'local_structural' if is_furniture else (
                'local_ambiguous' if key in ambiguous_set else 'local_unassigned')
            label = (reason, _digest([original.get('page'), original.get('zone', 0)]))
            title = '구조 정보' if is_furniture else '학습 내용'
            role, origin = ('decoration' if is_furniture else 'uncertain'), reason
        # These annotations may come from an older cached plan. Recompute the
        # owner here and let protect_visual_groups rederive image routing;
        # never carry an old exclusion/guard explanation into local recovery.
        block = {k: copy.deepcopy(v) for k, v in original.items() if k not in _ANNOTATIONS}
        block['planRole'] = role
        if label != previous:
            continuation = (owner == 0 and at == 0 and specs[owner]['clean']
                            and specs[owner]['continuesPrevious']
                            and specs[owner]['role'] not in ('navigation', 'exercise')) if owner is not None else False
            groups.append({'title': title, 'blocks': [], 'assignmentOrigin': origin,
                           'role': spec['role'] if owner is not None else role,
                           'continuesPrevious': bool(continuation)})
            if owner is not None:
                groups[-1]['sourceGroupIndex'] = owner
        groups[-1]['blocks'].append(block)
        previous = label
    proof = validate_partition(targets, groups)
    metadata = {'version': VERSION, 'partitionComplete': True,
                'semanticGroupingStatus': 'locally_recovered' if missing or ambiguous or diagnostics else 'ai_assigned',
                'unassignedBlockIds': missing, 'ambiguousBlockIds': ambiguous,
                'localUncertainBlockIds': [key for key in ids if (key in missing_set or key in ambiguous_set) and key not in furniture],
                'furnitureBlockIds': [key for key in ids if key in furniture],
                'diagnostics': diagnostics,
                'diagnosticCounts': dict(Counter(item['reason'] for item in diagnostics)),
                'coverageProof': proof, 'additionalRecoveryApiRequests': 0,
                'confirmationScope': 'exact source partition only; local uncertain ownership is not AI semantic confirmation'}
    return groups, metadata
