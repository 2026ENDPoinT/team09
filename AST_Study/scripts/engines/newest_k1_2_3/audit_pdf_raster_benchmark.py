"""Opt-in cold A/B audit of raster coalescing, preserving the user's library.

No remote calls without --allow-remote. All variants run sequentially, with
independent paid-response caches and one aggregate reservation-aware USD cap.
The baseline changes only merge_visuals to its pre-coalescing implementation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import time
import traceback

import pdf_ai
import pdf_new_concept_v02_regions as layout
import pdf_new_concept_ver99_study as study
from pdf_pipeline import write_json


CASES = [
    ('industrialization', '0fc36f1be587', '압축적 산업화', 39),
    ('integration', 'aa295c705cdf', '적분의 응용', 31),
    ('anatomy', '1f8a648d2e07', '시각기관', 16),
    ('dada', '57ebaa9745f0', '반예술 다다이즘', 33),
    ('pointers', '8da05ec5ee76', '포인터와 동적 객체', 31),
]


def old_merge(regions):
    result = []
    for region in regions:
        box, kinds = region['bbox'], {region['kind']}
        again = True
        while again:
            again = False
            for old in list(result):
                if layout.overlap(box, old['bbox']):
                    box = layout.union([box, old['bbox']])
                    kinds.update(old['kinds'])
                    result.remove(old)
                    again = True
        result.append({'bbox': box, 'kinds': sorted(kinds)})
    return result


@contextmanager
def variant(name):
    merge, version, imported_version = layout.merge_visuals, layout.VERSION, study.LAYOUT_VERSION
    if name == 'before':
        layout.merge_visuals = old_merge
        layout.VERSION = study.LAYOUT_VERSION = 'new-concept-layout-ver.02-page-edge-1'
    try:
        yield
    finally:
        layout.merge_visuals, layout.VERSION, study.LAYOUT_VERSION = merge, version, imported_version


def budget_used(root):
    """Unsettled/unknown attempts retain their full conservative reservation."""
    actual = reserved = 0.0
    requests = 0
    for path in root.glob('*/**/usage/*.json'):
        ledger = json.loads(path.read_text())
        for entry in ledger.get('requests', []):
            if entry.get('state')=='not_sent':continue
            requests += 1
            if entry.get('state') == 'settled':
                actual += entry['estimatedUsd']
            else:
                reserved += entry['reservedUsd']
    return {'actualUsd': actual, 'uncertainReservedUsd': reserved,
            'committedUsd': actual + reserved, 'requests': requests}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--max-usd', type=float, default=0)
    args = parser.parse_args()
    if not args.allow_remote or not 0 < args.max_usd <= 2:
        parser.error('Explicit transmission approval and a total cap <= $2 are required.')
    root = args.output.resolve()
    if root.is_relative_to(args.library.resolve()):
        parser.error('Audit output must be separate from the original library.')
    root.mkdir(parents=True, exist_ok=True)
    log = root / 'events.jsonl'

    def event(**row):
        row['timeMs'] = int(time.time()*1000)
        with log.open('a') as handle:
            handle.write(json.dumps(row, ensure_ascii=False)+'\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)

    # Suppress verbose production UI events, retaining them in each run's log.
    original_emit = study.emit
    manifest = {'totalBudgetUsd': args.max_usd, 'model': 'gpt-6-luna',
                'coldCaches': True, 'workers': study.WORKERS, 'cases': []}
    for case, prefix, title, pages in CASES:
        source = next(args.library.glob(prefix+'*'))
        document = json.loads((source/'document.json').read_text())
        assert len(document['pages']) == pages
        manifest['cases'].append({'case':case, 'title':title, 'pages':pages,
                                  'source':str(source/'source.pdf'),
                                  'sha256':hashlib.sha256((source/'source.pdf').read_bytes()).hexdigest()})
    write_json(root/'manifest.json', manifest)
    # Alternate A/B order to make server-side prefix-cache warming less one-sided.
    for index, (case, prefix, title, pages) in enumerate(CASES):
        source = next(args.library.glob(prefix+'*'))
        order = ('before','after') if index % 2 == 0 else ('after','before')
        for arm in order:
            folder = root / case / arm
            if (folder/'run.json').exists():
                event(event='preserved_existing_run', case=case, variant=arm)
                continue
            if any((folder/'usage').glob('*.json')):
                raise RuntimeError('Unfinished paid run exists; inspect it before resuming.')
            used = budget_used(root)
            # Leave $0.25 for source-grounded quality checks, also under the $2 cap.
            allowance = min(.8, args.max_usd - used['committedUsd'] - .25)
            if allowance <= .02:
                event(event='budget_stop', **used)
                return
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/'source.pdf', folder/'source.pdf')
            document = json.loads((source/'document.json').read_text())
            document['generated'] = {}
            write_json(folder/'document.json', document)
            provider = pdf_ai.Provider(folder, True, allowance)
            event(event='start', case=case, title=title, variant=arm, capUsd=allowance, **used)
            started = time.monotonic()
            run = {'case':case, 'title':title, 'pages':pages, 'variant':arm,
                   'startedAtMs':int(time.time()*1000), 'maxUsd':allowance}
            try:
                with (folder/'progress.jsonl').open('a') as progress:
                    def emit(kind, **data):
                        progress.write(json.dumps({'event':kind, **data},ensure_ascii=False)+'\n')
                        progress.flush()
                    study.emit = emit
                    with variant(arm):
                        plan_started = time.monotonic()
                        study.prepare_group_plan(folder, document, provider)
                        run['planningSeconds'] = time.monotonic()-plan_started
                        write_json(folder/'planning-usage.json', pdf_ai.run_usage(provider))
                        result = study.generate(folder, document, provider)
                        cache = study.root_path(folder, document, 'new-concept-v99', provider.model, 'document', 0)
                        run['cacheRoot'] = str(cache)
                        write_json(folder/'result.json', result)
                        run.update(processingComplete=result.get('processingComplete'),
                                   failedUnits=result.get('failedUnits'), metrics=result.get('metrics'))
            except Exception as error:
                run.update(error=type(error).__name__, detail=str(error), traceback=traceback.format_exc())
            finally:
                study.emit = original_emit
                run['wallSeconds'] = time.monotonic()-started
                run['finishedAtMs'] = int(time.time()*1000)
                run['usage'] = pdf_ai.run_usage(provider)
                write_json(folder/'run.json', run)
                used = budget_used(root)
                write_json(root/'budget.json', {'limitUsd':args.max_usd, **used})
                assert used['committedUsd'] <= args.max_usd + 1e-8
                event(event='finish', case=case, variant=arm, seconds=round(run['wallSeconds'],3),
                      complete=run.get('processingComplete',False), error=run.get('error'),
                      usage=run['usage'], aggregateBudget=used)


if __name__ == '__main__':
    main()
