"""Opt-in $0.50 aggregate audit: repair two missed pages and sample four other PDFs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import traceback

from audit_pdf_raster_benchmark import budget_used
from pdf_ai import Provider, run_usage
from pdf_pipeline import write_json
import pdf_new_concept_ver99_study as study

CASES=[('pointers','8da05ec5ee76','포인터와 동적 객체',10),
       ('industrialization','0fc36f1be587','압축적 산업화',33),
       ('vectors','90e5c6b25e35','벡터와 공간기하학',None),
       ('finance','d0042fffa2b4','금융의 이해',None),
       ('impressionism','db915f557e05','인상주의와 후기 인상주의',None),
       ('anatomy','41509b420bf7','사람해부학',None)]


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--library',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--allow-remote',action='store_true')
    parser.add_argument('--max-usd',default=0,type=float)
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--variant',default='new',choices=['new','verified'])
    args=parser.parse_args()
    if not args.allow_remote or not 0<args.max_usd<=.5:parser.error('Approval and total cap <= $0.50 required.')
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    for case,prefix,title,page in CASES:
        if args.cases and case not in args.cases:continue
        source=next(args.library.glob(prefix+'*'));folder=root/case/args.variant
        if (folder/'run.json').exists():continue
        if any((folder/'usage').glob('*.json')):raise RuntimeError('Inspect existing paid attempt; no automatic retry.')
        used=budget_used(root);cap=min(.16,args.max_usd-used['committedUsd']-.03)
        if cap<=.015:raise RuntimeError('Audit aggregate cap reached.')
        folder.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'source.pdf',folder/'source.pdf')
        doc=json.loads((source/'document.json').read_text());doc['generated']={};write_json(folder/'document.json',doc)
        run={'case':case,'title':title,'source':str(source/'source.pdf'),
             'sourceSha256':hashlib.sha256((source/'source.pdf').read_bytes()).hexdigest(),
             'documentPages':len(doc['pages']),'scope':'page' if page else 'document','page':page,
             'analyzedPages':1 if page else len(doc['pages']),'maxUsd':cap,
             'teachingIdentity':study.teaching_identity(),'plannerIdentity':study.planner_identity()}
        # The text-selection rules did not change between the first and final
        # semantic check. Reuse only its exact-source confirmed grouping plan;
        # regenerate explanations under the corrected teaching instructions.
        previous=root/case/'new'/'run.json'
        if args.variant=='verified' and previous.exists():
            prior=json.loads(previous.read_text());prior_cache=Path(prior['cacheRoot'])
            plan=json.loads((prior_cache/'plan.json').read_text())
            if study.usable_plan(plan):
                cache=study.root_path(folder,doc,'new-concept-v99','gpt-6-luna',run['scope'],page or 0)
                cache.mkdir(parents=True,exist_ok=True)
                for name in ['plan.json','blocks.json','local-layout.json']:
                    if (prior_cache/name).exists():shutil.copy2(prior_cache/name,cache/name)
                run['reusedGrouping']=True
        print(json.dumps({'event':'start',**run,'aggregateBudget':used},ensure_ascii=False),flush=True)
        provider=Provider(folder,True,cap);start=time.monotonic();emit=study.emit
        try:
            with (folder/'progress.jsonl').open('a') as progress:
                def record(kind,**data):
                    progress.write(json.dumps({'event':kind,**data},ensure_ascii=False)+'\n');progress.flush()
                study.emit=record
                study.prepare_group_plan(folder,doc,provider,run['scope'],page)
                planning=run_usage(provider);write_json(folder/'planning-usage.json',planning)
                result=study.generate(folder,doc,provider,run['scope'],page)
                write_json(folder/'result.json',result)
                run.update(processingComplete=result['processingComplete'],coverageComplete=result['coverageComplete'],
                    failedUnits=result['failedUnits'],cacheRoot=str(study.root_path(folder,doc,'new-concept-v99',provider.model,run['scope'],page or 0)))
        except Exception as error:run.update(error=type(error).__name__,detail=str(error),traceback=traceback.format_exc())
        finally:
            study.emit=emit;run['wallSeconds']=time.monotonic()-start;run['usage']=run_usage(provider)
            write_json(folder/'run.json',run);used=budget_used(root)
            write_json(root/'budget.json',{'limitUsd':args.max_usd,**used})
            assert used['committedUsd']<=args.max_usd+1e-8
            print(json.dumps({'event':'finish',**run,'aggregateBudget':used},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
