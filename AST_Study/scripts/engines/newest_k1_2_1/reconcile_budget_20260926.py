"""One-time OFFLINE reconciliation of 12 verified legacy requests. No API calls.

Exact report/model/chunk mapping, with duration, usage, and original budget-event
checks. Ambiguous/missing evidence aborts the entire migration. Keeps audit history.
"""
import json
from pathlib import Path
from live_compare import Budget, ROOT, MODELS, usage_cost

MAPPING = [
    ('replay-balanced-01', 'mini', 1), ('replay-balanced-01', 'full', 1),
    ('replay-balanced-01', 'full', 2), ('replay-balanced-01', 'mini', 2),
    ('replay-mini-short-01', 'mini', 1), ('replay-mini-short-01', 'mini', 2),
    ('replay-mini-short-01', 'mini', 3), ('replay-mini-short-01', 'mini', 4),
    ('20260926-172913-984', 'full', 1), ('20260926-172913-984', 'mini', 1),
    ('20260926-172913-984', 'full', 2), ('20260926-172913-984', 'mini', 2),
]


def main():
    budget = Budget(ROOT/'recordings/live-budget')
    try:
        path = budget.directory/'2026-09-26-v2.json'
        original = path.read_bytes()
        data = json.loads(original)
        if len(data['requests']) < 12 or data['prior_allowance_usd'] != .015:
            raise ValueError('Unexpected ledger; no changes made')
        changes = 0
        for index, (folder, model, chunk) in enumerate(MAPPING):
            entry = data['requests'][index]
            source = ROOT/'recordings/live-comparisons'/folder/'events.jsonl'
            events = [json.loads(line) for line in source.read_text('utf-8').splitlines()]
            matches = [e for e in events if e['kind']=='RESULT' and e['model']==model and e['chunk']==chunk]
            if len(matches) != 1:
                raise ValueError('Ambiguous result; no changes made')
            result = matches[0]
            expected_hold = f'${.015+(index+1)*.0025:.4f}'
            evidence = [e for e in events if e['kind']=='BUDGET' and e['model']==model
                        and e['end_ms']==result['end_ms'] and expected_hold in e['text']]
            cost = usage_cost(entry['model'], result['usage'])
            if (entry['model'] != MODELS[model] or entry['reserved_usd'] != .0025
                    or not entry['time'].startswith('2026-09-26T') or len(evidence) != 1
                    or abs(entry['seconds']-(result['end']-result['start'])/16000) > 1e-8
                    or cost is None or abs(cost-result['estimated_cost_usd']) > 1e-10):
                raise ValueError('Evidence does not match reservation; no changes made')
            if budget.settle_entry(data, entry, result['usage']):
                entry['settlement_evidence'] = str(source.relative_to(ROOT))
                entry['settlement_chunk'] = chunk
                changes += 1
        if changes:
            backup = path.with_suffix('.before-settlement.json')
            with backup.open('xb') as target:
                target.write(original)
            budget.save(path, data)
        print(json.dumps({'settled_requests': changes, 'accounted_usd': data['reserved_usd'],
                          'prior_allowance_usd': data['prior_allowance_usd'], 'limit_usd': .045}))
    finally:
        budget.close()


if __name__ == '__main__':
    main()
