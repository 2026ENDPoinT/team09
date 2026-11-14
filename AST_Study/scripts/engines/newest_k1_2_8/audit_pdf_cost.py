"""Explicit, isolated paid cost experiments with one persistent aggregate cap.

No user library results, credentials, or user credits are modified. Run variants
sequentially; all workers reserve their worst-case cost before network access.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import shutil
import sys
import time


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--scripts', type=Path, required=True)
    parser.add_argument('--variant', required=True)
    parser.add_argument('--workers', type=int, choices=(8,14), required=True)
    parser.add_argument('--aliases', action='store_true')
    parser.add_argument('--alias-pool', type=int)
    parser.add_argument('--compact-table-setup', action='store_true')
    parser.add_argument('--compact-prompt', action='store_true')
    parser.add_argument('--only-pages', type=int, nargs='+')
    parser.add_argument('--only-unit-ids', nargs='+')
    parser.add_argument('--batch-units', type=int, choices=(1,2,3,4),default=1)
    parser.add_argument('--batch-images', type=int, choices=(4,8,16),default=4)
    parser.add_argument('--balanced-batches', action='store_true')
    parser.add_argument('--batch-aliases', action='store_true')
    parser.add_argument('--statement-uncertainty', action='store_true')
    parser.add_argument('--fixed-batch-pool', type=int)
    parser.add_argument('--batch-alias-mode',choices=('exact','namespace'),default='exact')
    parser.add_argument('--coverage-hints',action='store_true')
    parser.add_argument('--study-api',choices=('chat','responses'),default='chat')
    parser.add_argument('--allow-remote', action='store_true')
    args = parser.parse_args()
    if not args.allow_remote or not args.variant.replace('-','').isalnum():
        parser.error('Explicit remote approval and a simple variant name are required.')
    root = args.root.resolve()
    source = args.source.resolve()
    if root.is_relative_to(source):
        parser.error('An experiment must not live inside the user library.')
    root.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.scripts.resolve()))
    import pdf_ai
    import pdf_new_concept_ver99_study as study
    from pdf_pipeline import write_json
    from pdf_study_cache_reuse import block_key
    from audit_pdf_cost_budget import SharedBudget
    # Read the already-authorized project credential in memory only. Snapshots
    # have no .env; no credential is copied, printed or placed in CLI arguments.
    project = Path(__file__).resolve().parents[1]
    key = pdf_ai.api_key(project / '.env')
    if not key:
        raise RuntimeError('The approved API credential is unavailable.')
    pdf_ai.api_key = lambda: key
    shared_budget = SharedBudget(root, args.variant)
    budget = shared_budget.snapshot()

    class BudgetProvider(pdf_ai.Provider):
        def reserve_credits(self, entry):
            shared_budget.reserve(entry)

        def settle_credits(self, entry):
            shared_budget.settle(entry)

    folder = root/'runs'/args.variant
    if folder.exists():
        raise RuntimeError('Never resume or overwrite a paid comparison implicitly.')
    folder.mkdir(parents=True)
    shutil.copy2(source/'source.pdf', folder/'source.pdf')
    document = json.loads((source/'document.json').read_text())
    document['generated'] = {}
    write_json(folder/'document.json', document)
    study.WORKERS = args.workers
    study.SOURCE_ID_ALIASES = args.aliases
    study.COMPACT_TABLE_SETUP = args.compact_table_setup
    study.TRANSPORT_BATCH_UNITS = args.batch_units
    study.TRANSPORT_BATCH_IMAGES = args.batch_images
    study.TRANSPORT_BALANCED = args.balanced_batches
    study.TRANSPORT_BATCH_ALIASES = args.batch_aliases
    study.STATEMENT_UNCERTAINTY = args.statement_uncertainty
    study.TRANSPORT_BATCH_ALIAS_POOL = args.fixed_batch_pool or args.batch_alias_mode
    study.SOURCE_COVERAGE_HINT = args.coverage_hints
    study.STUDY_INPUT_API = args.study_api
    if args.compact_prompt:
        from pdf_compact_teaching_prompt import COMPACT_STUDY_PROMPT
        study.STUDY_PROMPT = COMPACT_STUDY_PROMPT
    if args.alias_pool is not None:
        if not args.aliases:
            raise ValueError('A pool requires source aliases.')
        study.SOURCE_ALIAS_POOL_SIZE = args.alias_pool or None
    provider = BudgetProvider(folder, True, budget['activeWindow']['executionCapUsd'],
                              max_allowed_usd=budget['activeWindow']['approvedLimitUsd'])
    provider.rate_directory = root/'api-slots'
    cache = study.root_path(folder, document, 'new-concept-v99', provider.model, 'document', 0)
    cache.mkdir(parents=True)
    plan = json.loads(args.plan.read_text())
    blocks = study.extract(folder, document, list(range(1,len(document['pages'])+1)), cache)
    expected = {b['id']:block_key(b) for g in plan['groups'] for b in g['blocks']}
    actual = {b['id']:block_key(b) for b in blocks}
    if expected != actual or not study.usable_plan(plan, provider.model, blocks):
        raise RuntimeError('The confirmed frozen plan does not match canonical source fragments.')
    if args.only_pages or args.only_unit_ids:
        if any(p<1 or p>len(document['pages']) for p in (args.only_pages or [])):
            raise ValueError('Probe pages must be inside the source document.')
        original_jobs = study.jobs_for
        selected_pages = set(args.only_pages or [])
        selected_ids = set(args.only_unit_ids or [])
        def selected_jobs(groups):
            return [job for job in original_jobs(groups)
                    if selected_pages.intersection(b['page'] for b in job['blocks']) or job['id'] in selected_ids]
        study.jobs_for = selected_jobs
    write_json(cache/'plan.json', plan)
    run = {'variant':args.variant,'workers':args.workers,'aliases':args.aliases,
           'aliasPool':study.SOURCE_ALIAS_POOL_SIZE,'compactTableSetup':args.compact_table_setup,
           'compactPrompt':args.compact_prompt,'onlyPages':args.only_pages,
           'onlyUnitIds':args.only_unit_ids,'sampleOnly':bool(args.only_pages or args.only_unit_ids),
           'batchUnits':args.batch_units,'batchImages':args.batch_images,
           'balancedBatches':args.balanced_batches,
           'batchAliases':args.batch_aliases,
           'statementUncertainty':args.statement_uncertainty,
           'batchAliasPool':study.TRANSPORT_BATCH_ALIAS_POOL,
           'sourceCoverageHint':args.coverage_hints,
           'studyInputApi':args.study_api,
           'source':str(source),'sourceSha256':hashlib.sha256((folder/'source.pdf').read_bytes()).hexdigest(),
           'planSha256':hashlib.sha256(args.plan.read_bytes()).hexdigest(),
           'scripts':str(args.scripts.resolve()),'teachingIdentity':study.teaching_identity(),
           'planning':'same confirmed plan; no paid planning call; no teaching reply reused',
           'cacheRoot':str(cache),'startedAtMs':int(time.time()*1000)}
    shared_budget.snapshot()
    started = time.monotonic()
    print(json.dumps({'event':'start','variant':args.variant}), flush=True)
    try:
        with (folder/'progress.jsonl').open('w') as progress:
            def emit(kind, **data):
                progress.write(json.dumps({'event':kind,'seconds':time.monotonic()-started,**data},
                                          ensure_ascii=False)+'\n')
                progress.flush()
            study.emit = emit
            result = study.generate(folder, document, provider)
            if args.only_pages or args.only_unit_ids:
                result['sampleOnly'] = True
                result['sampleUnitsComplete'] = result['processingComplete']
                result['processingComplete'] = False
            write_json(folder/'result.json', result)
            run.update({k:result.get(k) for k in ('processingComplete','coverageComplete','failedUnits','metrics')})
    except Exception as error:
        run.update(error=type(error).__name__, detail=str(error))
    finally:
        run.update(wallSeconds=time.monotonic()-started,usage=pdf_ai.run_usage(provider))
        write_json(folder/'run.json',run)
        budget=shared_budget.snapshot()
        print(json.dumps({'event':'finish','variant':args.variant,'wallSeconds':run['wallSeconds'],
                          'usage':run['usage'],'error':run.get('error'),
                          'committedUsd':budget['committedUsd'],
                          'activeWindow':budget['activeWindow']},ensure_ascii=False), flush=True)


if __name__=='__main__':
    main()
