"""Pre-generation question slots; no review, duplicate filtering or extra calls."""
from __future__ import annotations

from collections import Counter, deque
import copy


def balanced_counts(amount, allowed, theme=''):
    # Remainders favour the theme, rather than always starting with OX.
    preferred = {'recall': ('word', 'ox', 'mcq', 'essay'),
                 'concept_completion': ('mcq', 'word', 'ox', 'essay'),
                 'understanding': ('mcq', 'essay', 'ox', 'word'),
                 'practice_set': ('mcq', 'essay', 'word', 'ox')}.get(theme, tuple(allowed))
    order = [kind for kind in preferred if kind in allowed]
    return {kind: amount // len(order) + (order.index(kind) < amount % len(order))
            if kind in order else 0 for kind in ('ox', 'mcq', 'word', 'essay')}


def valid_goal(goal):
    # Data contract only: no semantic judge, filtering or repair call.
    if isinstance(goal, str):
        return bool(goal.strip())  # Existing saved plans remain readable.
    if isinstance(goal, dict) and set(goal) in ({'judgment','confusion'}, {'given','judgment','confusion'}):
        return all(isinstance(v,str) for v in goal.values()) and bool(goal['judgment'].strip())
    return (isinstance(goal, dict) and set(goal) == {'given', 'derive', 'ask'}
            and all(isinstance(value, str) for value in goal.values())
            and bool(goal['given'].strip()) and bool(goal['ask'].strip()))


def wire_goal(goal):
    # Shared once per request; omit repeated object keys on every slot.
    if isinstance(goal, dict) and 'judgment' in goal:
        return copy.deepcopy(goal)  # Same criterion in own and shared task inputs.
    return [goal[key] for key in ('given', 'derive', 'ask')] if isinstance(goal, dict) else goal


def target_plan(value, catalog, config):
    """Validate only the planner's data contract and assign cheap local IDs.

    Counts are derived from slots, never sent twice by the planner. A short plan
    stays short: duplicating goals or making another call would defeat its point.
    Legacy count-only plans are handled by the original parser in pdf_quiz.
    """
    from pdf_quiz import TYPES, _number, _text
    known = {c['id'] for c in catalog}
    unallocated = _number(value.get('unallocated'))
    if unallocated > config['totalCount']:
        raise ValueError('미배분 문항 수가 요청한 총문항 수보다 많아요.')
    slots, units, seen = [], [], set()
    for row in value['allocations']:
        if not isinstance(row, dict):
            raise ValueError('출제 묶음의 형식이 올바르지 않아요.')
        uid, ids = row.get('unitId'), row.get('conceptIds')
        if (not _text(uid) or uid in seen or not isinstance(ids, list) or not ids
                or any(not isinstance(cid, str) or cid not in known for cid in ids)
                or len(set(ids)) != len(ids) or not isinstance(row.get('targets'), list)):
            raise ValueError('출제 묶음의 ID·개념·문항 목표 형식이 올바르지 않아요.')
        seen.add(uid)
        unit = {'unitId': uid, 'conceptIds': list(ids), 'targets': [], 'focus': '문항별 목표를 따른다.'}
        for item in row['targets']:
            members = item.get('conceptIds') if isinstance(item, dict) else None
            if (not isinstance(item, dict) or item.get('type') not in config['allowedTypes']
                    or not valid_goal(item.get('goal')) or not isinstance(members, list) or not members
                    or any(not isinstance(cid, str) or cid not in known for cid in members)
                    or len(set(members)) != len(members)):
                raise ValueError('문항 목표의 개념·유형·판단 대상이 올바르지 않아요.')
            # Slot scope is explicit and catalog-backed. Parent summaries can omit a
            # required concept; derive the actual unit scope from the slots below.
            target = copy.deepcopy(item)
            unit['targets'].append(target)
            slots.append(target)
        units.append(unit)
    # Never invent additional objectives to repair a model's count arithmetic.
    target_count = config['totalCount'] - unallocated
    custom_ratio = bool(config.get('instructions')) and value.get('customTypeRatio') is True
    quota = (dict(Counter(s['type'] for s in slots)) if custom_ratio else
             balanced_counts(config['totalCount'], config['allowedTypes'], config.get('theme', '')))
    # Maximum bipartite flow selects whole original targets, never changes their
    # type/profile/goal. Residual edges allow replacing an early greedy choice.
    from pdf_quiz_profiles import policy
    profiles = {**policy(config['totalCount'],config['theme'])['targetCounts'],
                'unspecified':target_count}
    buckets = {}
    for index, slot in enumerate(slots):
        profile = slot.get('profile','unspecified')
        if profile not in profiles:
            raise ValueError('문항 목표의 프로필이 올바르지 않아요.')
        buckets.setdefault((slot['type'],profile), []).append(index)
    graph = {}
    def edge(a,b,n):
        graph.setdefault(a,{})[b]=n
        graph.setdefault(b,{})[a]=0
    edge('start','budget',target_count)
    for kind,n in quota.items(): edge('budget','type:'+kind,n)
    for (kind,profile),indices in buckets.items(): edge('type:'+kind,'profile:'+profile,len(indices))
    for profile,n in profiles.items(): edge('profile:'+profile,'end',n)
    while True:
        parents={'start':None};queue=deque(['start'])
        while queue and 'end' not in parents:
            a=queue.popleft()
            for b,n in graph[a].items():
                if n>0 and b not in parents: parents[b]=a;queue.append(b)
        if 'end' not in parents: break
        b='end'
        while parents[b] is not None:
            a=parents[b];graph[a][b]-=1;graph[b][a]+=1;b=a
    chosen=set()
    for (kind,profile),indices in buckets.items():
        chosen.update(indices[:graph['profile:'+profile]['type:'+kind]])
    selection = {'originalCount':len(slots),'retainedOriginalIndices':sorted(chosen),
                 'excludedTargets':[{'originalIndex':i,'target':copy.deepcopy(t),
                    'reason':'요청 수·유형·프로필 할당 안에서 목표를 변경하지 않고 수용할 수 없어요.'}
                    for i,t in enumerate(slots) if i not in chosen],
                 'typeQuota':quota, 'profileQuota':profiles, 'semanticValidation':False}
    slots = [slot for i,slot in enumerate(slots) if i in chosen]
    retained = {id(slot) for slot in slots}
    for index, slot in enumerate(slots, 1):
        slot['id'] = f't{index}'
    allocations = []
    for unit in units:
        unit['targets'] = [s for s in unit['targets'] if id(s) in retained]
        if not unit['targets']:
            continue
        unit['conceptIds'] = list(dict.fromkeys(c for s in unit['targets'] for c in s['conceptIds']))
        counts = Counter(s['type'] for s in unit['targets'])
        unit['counts'] = {kind: counts[kind] for kind in TYPES}
        allocations.append(unit)
    remaining = config['totalCount'] - len(slots)
    return {'allocations': allocations, 'unallocated': remaining, 'customTypeRatio': custom_ratio,
            'targetSelection': selection,
            'reason': (_text(value['reason']) + (' 목표·유형·프로필을 변경하지 않고 배정할 수 없는 부족분이 있어요.' if remaining else '')).strip()}


def scoped_targets(assignment, targets, unit_id=None):
    from pdf_quiz import TYPES
    result = {**assignment, 'targets': targets}
    if unit_id is not None:
        result['unitId'] = unit_id
    result['conceptIds'] = list(dict.fromkeys(c for target in targets for c in target['conceptIds']))
    counts = Counter(target['type'] for target in targets)
    result['counts'] = {kind: counts[kind] for kind in TYPES}
    return result


def target_index(plan):
    # Column order is documented once in common.md; no repeated object keys.
    return [[s['id'], s['type'], s['conceptIds'], wire_goal(s['goal'])]
            for unit in plan['allocations'] for s in unit.get('targets', [])]


def wire_assignment(assignment):
    # A model should not have to join units[].targetIds to a separate target
    # table. Flatten only the wire contract; source validation still receives
    # the unchanged logical units and plan, never this transport projection.
    units = assignment.get('units', [assignment])
    if units and all('targets' in unit for unit in units):
        tasks = [{'targetId': slot['id'], 'unitId': unit['unitId'],
                  'type': slot['type'], 'conceptIds': copy.deepcopy(slot['conceptIds']),
                  'goal': wire_goal(copy.deepcopy(slot['goal'])),
                  **{k:copy.deepcopy(slot[k]) for k in ('profile','profileStatus','additionalJudgment','profileEvidenceSourceIds') if k in slot}}
                 for unit in units for slot in unit['targets']]
        return {'unitId': assignment['unitId'], 'questionCount': len(tasks), 'tasks': tasks}
    result = {k: copy.deepcopy(v) for k, v in assignment.items() if k not in ('targets', 'units')}
    if 'targets' in assignment:
        result.pop('focus', None)
        result['targetIds'] = [s['id'] for s in assignment['targets']]
    if 'units' in assignment:
        result.pop('focus', None)
        result['units'] = [wire_assignment(u) for u in assignment['units']]
    return result


def interleave_questions(questions, allowed):
    """Mix display order without dropping questions, changing IDs or reviewing."""
    queues = {kind: deque(q for q in questions if q['type'] == kind) for kind in allowed}
    for question in questions:
        if question['type'] not in queues:
            queues[question['type']] = deque(q for q in questions if q['type'] == question['type'])
    result = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                result.append(queue.popleft())
    return result
