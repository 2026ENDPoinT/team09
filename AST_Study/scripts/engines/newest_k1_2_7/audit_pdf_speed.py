"""Opt-in isolated latency experiments; all attempts share a reservation-aware cap."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import time
import re

from audit_pdf_raster_benchmark import budget_used, CASES
from pdf_ai import Provider, run_usage
from pdf_pipeline import write_json

CASES = CASES + [('finance','d0042fffa2b4','금융의 이해',14),
                 ('impressionism','db915f557e05','인상주의와 후기 인상주의',37)]


def current_budget(root, checkpoint=None):
    if checkpoint is None:return budget_used(root)
    prior=set(json.loads(checkpoint.read_text())['preexistingRequestIds'])
    entries={}
    for path in root.glob('**/usage/*.json'):
        for i,entry in enumerate(json.loads(path.read_text()).get('requests',[])):
            key=entry.get('requestId') or 'legacy:'+path.relative_to(root).as_posix()+':'+str(i)
            if key in prior or entry.get('state')=='not_sent':continue
            if key not in entries or entry.get('state')=='settled':entries[key]=entry
    actual=sum(e.get('estimatedUsd',0) for e in entries.values() if e.get('state')=='settled')
    unknown=sum(e.get('reservedUsd',0) for e in entries.values() if e.get('state')!='settled')
    return {'actualUsd':actual,'uncertainReservedUsd':unknown,
            'committedUsd':actual+unknown,'requests':len(entries)}


def load_engine(path):
    spec = importlib.util.spec_from_file_location('speed_engine', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--library', type=Path, required=True)
    p.add_argument('--variant', required=True)
    p.add_argument('--cases', nargs='+', required=True)
    p.add_argument('--allow-remote', action='store_true')
    p.add_argument('--max-usd', type=float, default=0)
    p.add_argument('--budget-checkpoint', type=Path)
    p.add_argument('--planner-only', action='store_true')
    p.add_argument('--transport', choices=['ids','ranges'])
    p.add_argument('--window-bytes', type=int)
    p.add_argument('--window-blocks', type=int)
    p.add_argument('--workers', type=int)
    p.add_argument('--job-weight', type=int)
    p.add_argument('--job-crops', type=int)
    p.add_argument('--job-pages', type=int)
    p.add_argument('--compact-table-setup', action='store_true')
    p.add_argument('--pipeline-crops', action='store_true')
    p.add_argument('--rate-utilization', type=float, default=.70)
    p.add_argument('--study-reasoning', choices=['none','low'],default='none')
    p.add_argument('--neutral-visual-hint', action='store_true')
    p.add_argument('--source-aliases', action='store_true')
    p.add_argument('--statement-uncertainty', action='store_true')
    p.add_argument('--owned-teaching', action='store_true')
    p.add_argument('--unlabeled-images', action='store_true')
    p.add_argument('--lossless-webp', action='store_true')
    p.add_argument('--study-temperature', type=float)
    p.add_argument('--image-region-labels', action='store_true')
    p.add_argument('--experimental-source-prompt', action='store_true')
    p.add_argument('--frozen-plan-variant', help='Reuse only a confirmed plan from an isolated prior variant; never reuse its teaching replies.')
    p.add_argument('--source-coverage', action='store_true')
    p.add_argument('--webp-method', type=int, choices=[0,1], default=1)
    p.add_argument('--source-facts', action='store_true')
    p.add_argument('--visual-teaching', action='store_true')
    p.add_argument('--partial-native-visual-hints', action='store_true')
    args = p.parse_args()
    if not args.allow_remote or not 0 < args.max_usd <= 3.3:
        p.error('Explicit transmission approval and aggregate cap at most $3.30 required.')
    root = args.output.resolve()
    if args.budget_checkpoint:
        checkpoint=json.loads(args.budget_checkpoint.read_text())
        if (not isinstance(checkpoint.get('preexistingRequestIds'),list)
                or not 0<args.max_usd<=checkpoint['approvedNewCapUsd']):
            p.error('The new-call budget cannot exceed the approved checkpoint cap.')
    if args.frozen_plan_variant and not re.fullmatch(r'[A-Za-z0-9_-]+', args.frozen_plan_variant):
        p.error('A frozen-plan variant must be a simple experiment name.')
    if root.is_relative_to(args.library.resolve()):
        p.error('Experiments must not alter the user library.')
    study = load_engine(args.engine)
    if args.experimental_source_prompt:study.STUDY_PROMPT=study.EXPERIMENTAL_SOURCE_PROMPT
    if not .6<=args.rate_utilization<=.8:p.error('Rate utilization must stay between 60% and 80%.')
    import pdf_api_slots
    pdf_api_slots.RATE_UTILIZATION=args.rate_utilization
    for name, value in [('PLAN_TRANSPORT',args.transport),('PLAN_WINDOW_BYTES',args.window_bytes),
                        ('PLAN_WINDOW_BLOCKS',args.window_blocks),('WORKERS',args.workers),
                        ('JOB_WEIGHT_LIMIT',args.job_weight),('JOB_CROP_LIMIT',args.job_crops)]:
        if value is not None:setattr(study,name,value)
    if args.job_pages is not None:study.JOB_PAGE_LIMIT=args.job_pages
    study.COMPACT_TABLE_SETUP=args.compact_table_setup
    study.PIPELINE_CROPS=args.pipeline_crops
    study.NEUTRAL_VISUAL_HINT=args.neutral_visual_hint
    study.SOURCE_ID_ALIASES=args.source_aliases
    study.STATEMENT_UNCERTAINTY=args.statement_uncertainty
    study.OWNED_TEACHING=args.owned_teaching
    study.STUDY_REASONING_EFFORT=args.study_reasoning
    if args.study_temperature is not None and not (args.study_reasoning=='none' and 0<=args.study_temperature<=2):
        p.error('Temperature experiments require reasoning none and a finite value from 0 to 2.')
    study.STUDY_TEMPERATURE=args.study_temperature
    study.IMAGE_REGION_LABELS=args.image_region_labels
    study.SOURCE_COVERAGE_HINT=args.source_coverage
    study.SOURCE_FACTS=args.source_facts
    study.VISUAL_TEACHING=args.visual_teaching
    if args.partial_native_visual_hints and not hasattr(study,'PARTIAL_NATIVE_VISUAL_HINTS'):
        p.error('The selected engine does not support partial native visual hints.')
    if hasattr(study,'PARTIAL_NATIVE_VISUAL_HINTS'):
        study.PARTIAL_NATIVE_VISUAL_HINTS=args.partial_native_visual_hints
    if hasattr(study,'IMAGE_SOURCE_LABELS'):study.IMAGE_SOURCE_LABELS=not args.unlabeled_images
    import pdf_image_transport
    pdf_image_transport.LOSSLESS_WEBP=args.lossless_webp
    pdf_image_transport.WEBP_METHOD=args.webp_method
    for case, prefix, title, pages in CASES:
        if case not in args.cases:
            continue
        folder = root/'runs'/case/args.variant
        if (folder/'run.json').exists():
            continue
        if any((folder/'usage').glob('*.json')):
            raise RuntimeError('Unfinished paid attempt: inspect before resuming.')
        used = current_budget(root,args.budget_checkpoint)
        allowance = min(.95, args.max_usd-used['committedUsd']-.04)
        if allowance < .04:
            raise RuntimeError('Aggregate experiment budget reached.')
        source = next(args.library.glob(prefix+'*'))
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/'source.pdf', folder/'source.pdf')
        document = json.loads((source/'document.json').read_text())
        document['generated'] = {}
        write_json(folder/'document.json', document)
        provider = Provider(folder, True, allowance)
        provider.study_reasoning_effort=args.study_reasoning
        provider.rate_directory=root/'api-slots'
        frozen_run=None
        if args.frozen_plan_variant:
            frozen_folder=root/'runs'/case/args.frozen_plan_variant
            frozen_run=json.loads((frozen_folder/'run.json').read_text())
            prior=Path(frozen_run['cacheRoot']).resolve()
            if not prior.is_relative_to(frozen_folder.resolve()):
                raise ValueError('Frozen plan must remain inside its isolated run folder.')
            old_document=json.loads((frozen_folder/'document.json').read_text())
            if any(old_document.get(k)!=document.get(k) for k in ('documentId','fingerprint')):
                raise ValueError('Frozen plan source identity changed.')
            plan=json.loads((prior/'plan.json').read_text())
            if not study.usable_plan(plan,provider.model) or plan.get('reusedFrom'):
                raise ValueError('Only a directly confirmed compatible plan can be frozen.')
            target=study.root_path(folder,document,'new-concept-v99',provider.model,'document',0)
            target.mkdir(parents=True,exist_ok=True)
            # Check source geometry/text before any paid call. This copies no
            # responses, results or usage, so generation remains a fresh trial.
            blocks=study.extract(folder,document,list(range(1,pages+1)),target)
            from pdf_study_cache_reuse import block_key
            expected={b['id']:block_key(b) for g in plan['groups'] for b in g['blocks']}
            actual={b['id']:block_key(b) for b in blocks}
            if expected!=actual:raise ValueError('Frozen plan source fragments changed.')
            write_json(target/'plan.json',plan)
        run = {'case':case, 'title':title, 'pages':pages, 'variant':args.variant,
               'source':str(source), 'plannerOnly':args.planner_only,
               'engine':str(args.engine), 'plannerIdentity':study.planner_identity(),
               'teachingIdentity':study.teaching_identity(), 'startedAtMs':int(time.time()*1000)}
        run['settings']={k:getattr(study,k,None) for k in ('PLAN_TRANSPORT','PLAN_WINDOW_BYTES',
            'PLAN_WINDOW_BLOCKS','WORKERS','JOB_WEIGHT_LIMIT','JOB_CROP_LIMIT')}
        run['settings'].update(rateUtilization=args.rate_utilization,studyReasoning=args.study_reasoning,
                               pipelineCrops=args.pipeline_crops,neutralVisualHint=args.neutral_visual_hint)
        run['settings']['sourceAliases']=args.source_aliases
        run['settings']['statementUncertainty']=args.statement_uncertainty
        run['settings']['ownedTeaching']=args.owned_teaching
        run['settings']['jobPageLimit']=getattr(study,'JOB_PAGE_LIMIT',None)
        run['settings']['compactTableSetup']=args.compact_table_setup
        run['settings']['imageSourceLabels']=getattr(study,'IMAGE_SOURCE_LABELS',False)
        run['settings']['losslessWebp']=args.lossless_webp
        run['settings']['webpMethod']=args.webp_method
        run['settings']['studyTemperature']=args.study_temperature
        run['settings']['imageRegionLabels']=args.image_region_labels
        run['settings']['sourcePromptProfile']='experimental' if args.experimental_source_prompt else 'original'
        run['settings']['sourceCoverageHint']=args.source_coverage
        run['settings']['sourceFacts']=args.source_facts
        run['settings']['visualTeaching']=args.visual_teaching
        run['settings']['partialNativeVisualHints']=getattr(study,'PARTIAL_NATIVE_VISUAL_HINTS',False)
        if args.source_coverage:run['settings']['sourceCoverageRulesDigest']=study.digest(study.SOURCE_COVERAGE_RULES)
        run['settings']['schedulingProfile']=getattr(study,'SCHEDULING_PROFILE','inline-render-legacy-preview')
        if frozen_run:
            run['frozenPlanning']={'variant':args.frozen_plan_variant,
                'originalPlanningSeconds':frozen_run['planningSeconds'],
                'teachingRepliesReused':False,
                'note':'Measured time excludes a fresh grouping call. Compare post-group generation separately, or add the original grouping time as a modeled equivalent.'}
        start = time.monotonic()
        print(json.dumps({'event':'start','case':case,'variant':args.variant,'budget':used}), flush=True)
        try:
            with (folder/'progress.jsonl').open('a') as progress:
                def record(kind, **data):
                    progress.write(json.dumps({'event':kind,'seconds':time.monotonic()-start,**data},ensure_ascii=False)+'\n')
                    progress.flush()
                study.emit = record
                study.prepare_group_plan(folder, document, provider)
                run['planningSeconds'] = time.monotonic()-start
                write_json(folder/'planning-usage.json', run_usage(provider))
                if not args.planner_only:
                    result = study.generate(folder, document, provider)
                    write_json(folder/'result.json', result)
                    run.update(processingComplete=result['processingComplete'],
                        coverageComplete=result['coverageComplete'],failedUnits=result['failedUnits'],
                        metrics=result.get('metrics'))
                run['cacheRoot'] = str(study.root_path(folder,document,'new-concept-v99',provider.model,'document',0))
        except Exception as error:
            run.update(error=type(error).__name__,detail=str(error))
        finally:
            run.update(wallSeconds=time.monotonic()-start,usage=run_usage(provider))
            write_json(folder/'run.json',run)
            used = current_budget(root,args.budget_checkpoint)
            write_json(root/'budget.json',{'limitUsd':args.max_usd,
                'checkpoint':str(args.budget_checkpoint) if args.budget_checkpoint else None,**used})
            assert used['committedUsd'] < args.max_usd + 1e-9
            print(json.dumps({'event':'finish',**run,'budget':used},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
