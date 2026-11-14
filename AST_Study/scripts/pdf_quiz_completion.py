"""Build only missing quiz slots, using smaller batches and productive source scopes."""
from collections import Counter
import copy

MAX_REFILL_ROUNDS = 4
REFILL_BATCH_SIZE = 4


def origin(unit_id):
    return unit_id.split('/refill-', 1)[0].split('/context-', 1)[0].split('/batch-', 1)[0]


def refill_assignments(plan, questions, catalog, config, round_number):
    from pdf_quiz import TYPES

    missing = config['totalCount'] - len(questions)
    if missing <= 0:
        return []
    bases = copy.deepcopy(plan['allocations'])
    if not bases:
        bases = [{'unitId': 'fallback-' + c['id'], 'conceptIds': [c['id']],
                  'counts': dict.fromkeys(TYPES, 0), 'focus': c['title']} for c in catalog]
    if not bases:
        return []
    expected = Counter({t: sum(a['counts'][t] for a in bases) for t in TYPES})
    # Unallocated planner slots are filled from the selected source scope too.
    extra = config['totalCount'] - sum(expected.values())
    allowed = [t for t in config['allowedTypes']
               if not (t == 'word' and config['difficulty'] in ('상', '최상'))] or config['allowedTypes']
    for i in range(max(0, extra)):
        expected[allowed[i % len(allowed)]] += 1
    actual = Counter(q['type'] for q in questions)
    remaining = Counter({t: max(0, expected[t]-actual[t]) for t in TYPES})
    productive = Counter(origin(q.get('unitId', '')) for q in questions)
    jobs = []

    def add(base, counts):
        while sum(counts.values()) and sum(sum(j['counts'].values()) for j in jobs) < missing:
            take = dict.fromkeys(TYPES, 0)
            for _ in range(min(REFILL_BATCH_SIZE, missing - sum(sum(j['counts'].values()) for j in jobs))):
                kind = next((t for t in TYPES if counts[t] and remaining[t]), None)
                if kind is None:
                    break
                take[kind] += 1;counts[kind] -= 1;remaining[kind] -= 1
            if not sum(take.values()):
                break
            jobs.append({**base, 'unitId': base['unitId'] + f'/refill-{round_number}-{len(jobs)}',
                         'counts': take,
                         'focus': base['focus'] + ' 자료에 명시된 내용으로 기존 문항과 다른 조건·초점의 문항을 작성한다.'})

    if round_number == 1:
        # First retry preserves the original allocation and source boundaries.
        for base in bases:
            done = Counter(q['type'] for q in questions if origin(q.get('unitId', '')) == base['unitId'])
            add(base, Counter({t: max(0, base['counts'][t]-done[t]) for t in TYPES}))
    # Later rounds redistribute shortages to scopes which actually yielded usable material.
    donors = [a for a in bases if productive[a['unitId']]] or bases
    index = round_number - 1
    while sum(remaining.values()):
        before = sum(remaining.values())
        take = Counter()
        for kind in TYPES:
            take[kind] = min(remaining[kind], max(0, REFILL_BATCH_SIZE-sum(take.values())))
        add(donors[index % len(donors)], take)
        if sum(remaining.values()) == before:
            break
        index += 1
    return jobs
