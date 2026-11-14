"""Replay saved cost records locally. No provider construction or API calls."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

import pdf_ver99_cost_estimate as current
from pdf_new_concept_ver99_study import VERSION as PROMPT_VERSION


def load_module(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(root, history, estimator):
    rows=[]
    for target in history:
        document=current.read(root/target['documentId']/'document.json')
        others=[sample for sample in history if sample['documentId']!=target['documentId']]
        prediction=estimator.estimate(document,list(range(1,target['pages']+1)),others,
                                      **({'work':target['workload']} if hasattr(estimator,'workload') else {}))
        actual=target['usd']
        rows.append({'documentId':target['documentId'],'pages':target['pages'],'actualUsd':actual,
                     'estimatedUsd':prediction['usd'],'signedErrorPercent':100*(prediction['usd']/actual-1),
                     'actualStageUsd':{k:v.get('usageBasedUsd',0) for k,v in target['stageUsage'].items()
                                       if v.get('requests')},'predictedStageUsd':prediction.get('stageUsd'),
                     'localWorkload':target['workload']['details'],
                     'localStudyRequests':target['workload']['region_study']['calls'],
                     'actualStudyRequests':target['stageUsage']['region_study']['requests'],
                     'rangeContainsActual':prediction['lowUsd']<=actual<=prediction['highUsd']})
    return {'sampleCount':len(rows),'meanAbsolutePercentageError':sum(abs(r['signedErrorPercent']) for r in rows)/max(1,len(rows)),
            'maximumAbsolutePercentageError':max((abs(r['signedErrorPercent']) for r in rows),default=0),
            'rows':rows}


def compare_planned(root, history):
    """Replay the instant after planning, before any study response exists.

    Only target source fragments and the saved pre-study manifest are predictors.
    Target planning cost is already known at this instant; study usage is used
    solely as the scoring label. No completed study cache is supplied to estimate.
    """
    rows,excluded=[],[]
    for target in history:
        planned=target.get('plannedWorkload')
        actual_requests=target['stageUsage']['region_study'].get('requests',0)
        if not planned or planned['region_study']['calls']!=actual_requests:
            excluded.append({'documentId':target['documentId'],'reason':'actual manifest/paid-request counts unavailable or mismatched'})
            continue
        document=current.read(root/target['documentId']/'document.json')
        others=[sample for sample in history if sample['documentId']!=target['documentId']]
        pages=list(range(1,target['pages']+1))
        before=current.estimate(document,pages,others,work=target['workload'])
        after=current.estimate(document,pages,others,work=target['workload'],pending_work=planned,plan_cached=True)
        actual_total=target['usd']
        known_plan=target['planUsd']
        actual_remaining=actual_total-known_plan
        before_remaining=sum(before['stageUsd'][k] for k in ('region_study','summary_reduce'))
        after_total=known_plan+after['usd']
        rows.append({'documentId':target['documentId'],'pages':target['pages'],
            'beforeRequests':target['workload']['region_study']['calls'],
            'confirmedRequests':planned['region_study']['calls'],'actualRequests':actual_requests,
            'actualTotalUsd':actual_total,'knownPlanningUsd':known_plan,
            'beforeTotalUsd':before['usd'],'afterTotalUsd':after_total,
            'actualRemainingUsd':actual_remaining,'beforeRemainingUsd':before_remaining,'afterRemainingUsd':after['usd'],
            'beforeTotalErrorPercent':100*(before['usd']/actual_total-1),
            'afterTotalErrorPercent':100*(after_total/actual_total-1),
            'beforeRemainingErrorPercent':100*(before_remaining/actual_remaining-1),
            'afterRemainingErrorPercent':100*(after['usd']/actual_remaining-1),
            'beforeStageUsd':before['stageUsd'],'afterStageUsd':after['stageUsd'],
            'confirmedWorkload':planned['details']})
    metrics={}
    for key in ('beforeTotal','afterTotal','beforeRemaining','afterRemaining'):
        errors=[abs(row[key+'ErrorPercent']) for row in rows]
        metrics[key]={'meanAbsolutePercentageError':sum(errors)/max(1,len(errors)),
                      'maximumAbsolutePercentageError':max(errors,default=0)}
    return {'sampleCount':len(rows),'method':'same PDFs, leave-one-document-out; target pre-study manifest only; no target study responses/usage as predictors',
            'totalDefinition':'known paid planning cost + predicted future study/overview cost',
            'remainingDefinition':'study + overview only in both arms, with planning excluded',
            'metrics':metrics,'rows':rows,'excluded':excluded}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('.synesis/pdf'))
    parser.add_argument('--baseline-original',type=Path,required=True)
    parser.add_argument('--baseline-v2',type=Path,required=True)
    parser.add_argument('--cohort',type=Path,help='JSON array of document IDs frozen before design changes')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    old=load_module(args.baseline_original,'cost_original')
    v2=load_module(args.baseline_v2,'cost_v2')
    all_samples=current.samples(args.root,'gpt-6-luna',PROMPT_VERSION)
    cohort=set(json.loads(args.cohort.read_text())) if args.cohort else {s['documentId'] for s in all_samples}
    history=[s for s in all_samples if s['documentId'] in cohort]
    report={'method':'leave-one-document-out; target excluded from all fitted coefficients',
            'limitation':'Exploratory replay: this cohort informed model design; not independent prospective validation.',
            'paidApiCalls':0,'cohortDocumentIds':sorted(cohort),
            'original':replay(args.root,history,old),'v2':replay(args.root,history,v2),
            'v3':replay(args.root,history,current),
            'plannedComparison':compare_planned(args.root,history)}
    report['additionalRecords']=[]
    for target in all_samples:
        if target['documentId'] in cohort:continue
        document=current.read(args.root/target['documentId']/'document.json')
        prediction=current.estimate(document,list(range(1,target['pages']+1)),history,work=target['workload'])
        report['additionalRecords'].append({'documentId':target['documentId'],'pages':target['pages'],
            'actualUsd':target['usd'],'estimatedUsd':prediction['usd'],
            'signedErrorPercent':100*(prediction['usd']/target['usd']-1)})
        if target.get('plannedWorkload'):
            after=current.estimate(document,list(range(1,target['pages']+1)),history,work=target['workload'],
                                   pending_work=target['plannedWorkload'],plan_cached=True)
            total=target['planUsd']+after['usd']
            report['additionalRecords'][-1].update(afterPlanningTotalUsd=total,
                afterPlanningTotalErrorPercent=100*(total/target['usd']-1),
                afterPlanningRemainingErrorPercent=100*(after['usd']/(target['usd']-target['planUsd'])-1))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({version:{key:report[version][key] for key in ('sampleCount','meanAbsolutePercentageError','maximumAbsolutePercentageError')}
                      for version in ('original','v2','v3')},ensure_ascii=False,indent=2))
    print('Planned comparison:',json.dumps(report['plannedComparison']['metrics'],indent=2))
    print('Additional records:',report['additionalRecords'])


if __name__=='__main__':main()
