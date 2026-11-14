"""Build a local, read-only PDF speed/quality experiment report. No API or UI calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import math
from pathlib import Path
from statistics import mean
from urllib.parse import quote

DEFAULT_ROOT = Path('build/pdf-speed-20261021')
CASES = [('industrialization','압축적 산업화',39), ('anatomy','시각·청각기관',16),
         ('pointers','포인터와 동적 객체',31), ('integration','적분의 응용',31),
         ('finance','금융의 이해',14), ('impressionism','인상주의와 후기 인상주의',37)]
PRICE_NOTE = '캐시 미적용 비교 비용은 입력 100만 토큰당 $0.10, 출력 $0.50로 계산한 비교 지표예요. 실제 청구액과 구분해요.'
QUALITY_NOTE = '품질은 선택한 페이지·항목을 대조했어요. 일부 자료는 전 페이지를 살폈지만 모든 주장과 세부 정보를 전수 검증한 것은 아니며, 전체 무손실을 보장하지 않아요.'


def number(value, default=None):
    return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else default


def load(path, warnings):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as error:
        warnings.append({'file':path.name,'error':type(error).__name__})
        return None


def relative(path, root):
    try:return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:return None


def usage_stats(entries):
    active=[e for e in entries if e.get('state')!='not_sent']
    settled=[e for e in active if e.get('state')=='settled' and number(e.get('estimatedUsd')) is not None]
    unknown=[e for e in active if e not in settled]
    inputs=outputs=cached=cache_write=0
    for entry in settled:
        usage=entry.get('usage') or {}
        inputs+=int(number(usage.get('prompt_tokens',usage.get('input_tokens')),0))
        outputs+=int(number(usage.get('completion_tokens',usage.get('output_tokens')),0))
        details=usage.get('prompt_tokens_details',usage.get('input_tokens_details')) or {}
        cached+=int(number(details.get('cached_tokens'),0))
        cache_write+=int(number(details.get('cache_write_tokens'),0))
    actual=sum(number(e.get('estimatedUsd'),0) for e in settled)
    reserved=sum(max(0,number(e.get('reservedUsd'),0)) for e in unknown)
    # Preserve every historical ledger estimate. The explicit standard-tier
    # cache-write premium is a separate report-only adjustment, not a reprice.
    cache_write_surcharge=cache_write*(.125-.10)/1_000_000
    queue=[number(e.get('queueSeconds')) for e in active]
    latency=[number(e.get('latencySeconds')) for e in active]
    server=[max(0,number(e.get('latencySeconds'),0)-number(e.get('queueSeconds'),0))
            for e in active if number(e.get('latencySeconds')) is not None]
    return {'requests':len(active),'notSentRequests':len(entries)-len(active),
            'settledRequests':len(settled),'unknownUsageRequests':len(unknown),
            'inputTokens':inputs,'cachedInputTokens':cached,'outputTokens':outputs,
            'totalTokens':inputs+outputs,'actualUsd':round(actual,10),
            'uncertainReservedUsd':round(reserved,10),'committedUsd':round(actual+reserved,10),
            'cacheWriteTokens':cache_write,
            'knownCacheWriteSurchargeUsd':round(cache_write_surcharge,10),
            'committedWithKnownCacheWriteUsd':round(actual+reserved+cache_write_surcharge,10),
            'normalizedUncachedUsd':round((inputs*.10+outputs*.50)/1_000_000,10),
            'maxQueueSeconds':max((v for v in queue if v is not None),default=None),
            'queueRecordedRequests':sum(v is not None for v in queue),
            'maxRequestSeconds':max((v for v in latency if v is not None),default=None),
            'maxServiceSecondsEstimate':max(server,default=None)}


def deduplicate(entries):
    seen={}; duplicates=0
    for index,entry in enumerate(entries):
        key=entry.get('requestId') or ('missing-id',index)
        if key in seen:
            duplicates+=1
            old=seen[key]
            # A settled copy is definitive; do not count a stale reservation twice.
            if entry.get('state')=='settled' and old.get('state')!='settled':seen[key]=entry
        else:seen[key]=entry
    return list(seen.values()),duplicates


def result_counts(folder,warnings):
    path=folder/'result.json'
    if not path.is_file():return None
    result=load(path,warnings)
    if not isinstance(result,dict):return None
    coverage=result.get('coverage') or []
    states=Counter(row.get('state','unknown') for row in coverage if isinstance(row,dict))
    review_pages=sorted({row['page'] for row in coverage if isinstance(row,dict)
                        and row.get('state')=='needs_review' and isinstance(row.get('page'),int)})
    pending_pages=sorted({row['page'] for row in coverage if isinstance(row,dict)
                         and row.get('state')=='pending_summary' and isinstance(row.get('page'),int)})
    return {'sections':len(result.get('sections') or []),
            'conceptEntries':sum(len(c.get('entries') or []) for c in result.get('concepts') or []),
            'coverageStates':dict(states),'needsReviewPages':review_pages,'pendingSummaryPages':pending_pages,
            'incompletePages':result.get('incompletePages') or [],
            'processingComplete':result.get('processingComplete'),
            'coverageComplete':result.get('coverageComplete')}


def quality_summary(root,warnings):
    docs=[]
    verdicts={'pass','present','preserved','partial','missing','incorrect','fail','needs_review','uncertain'}
    variants={p.name for p in (root/'runs').glob('*/*') if p.is_dir()}
    for path in sorted((root/'quality').glob('*.json')):
        data=load(path,warnings)
        if data is None:continue
        counts=Counter(); severity=Counter(); pages=set(); samples=0
        def walk(value):
            nonlocal samples
            if isinstance(value,list):
                for child in value:walk(child)
            elif isinstance(value,dict):
                if ('fact' in value or 'claim' in value) and ('page' in value or 'pages' in value):samples+=1
                page=value.get('page')
                if isinstance(page,int):pages.add(page)
                for page in value.get('pages',[]) if isinstance(value.get('pages'),list) else []:
                    if isinstance(page,int):pages.add(page)
                for key,child in value.items():
                    if key=='verdict' and isinstance(child,str) and child in verdicts:counts[child]+=1
                    elif key in variants and isinstance(child,str) and child in verdicts:counts[f'{key}:{child}']+=1
                    elif key=='severity' and isinstance(child,str) and child!='none':severity[child]+=1
                    if isinstance(child,(dict,list)):walk(child)
        walk(data)
        docs.append({'path':relative(path,root),'name':path.stem,'sampleChecks':samples,
                     'referencedPageNumbers':sorted(pages),'verdictCounts':dict(counts),
                     'issueCategories':dict(severity),
                     'additionalApiRequests':data.get('additionalApiRequests',0) if isinstance(data,dict) else None})
    return {'scopeNote':QUALITY_NOTE,'documents':docs,
            'note':'문서마다 검토 범위가 겹칠 수 있어 품질 확인 개수를 합산하지 않아요.'}


def aggregate(rows):
    keys=['requests','notSentRequests','settledRequests','unknownUsageRequests','inputTokens',
          'cachedInputTokens','outputTokens','totalTokens','actualUsd','uncertainReservedUsd',
          'committedUsd','normalizedUncachedUsd','wallSeconds','planningSeconds']
    out={key:round(sum(number(row.get(key),0) for row in rows),10) for key in keys}
    first=[row['firstResultSeconds'] for row in rows if number(row.get('firstResultSeconds')) is not None]
    out.update(runs=len(rows),pages=sum(int(row.get('pages') or 0) for row in rows),
               firstResultMeanSeconds=mean(first) if first else None,
               firstResultRecordedRuns=len(first))
    return out


def delta(before,after):
    if number(before) is None or number(after) is None or before==0:return None
    return (after-before)/before*100


def comparisons(decision,rows):
    if not isinstance(decision,dict) or not decision.get('selectedVariant'):return None
    index={(row['case'],row['variant']):row for row in rows}
    selected=decision['selectedVariant']; baseline_by=decision.get('baselineByCase') or {}
    wanted=decision.get('cases') or [case for case,_,_ in CASES]
    wanted=[item.get('case') if isinstance(item,dict) else item for item in wanted]
    pairs=[]; usable=[]
    for case in wanted:
        before=index.get((case,baseline_by.get(case,'baseline')))
        after=index.get((case,selected))
        reasons=[]
        if before is None or after is None:reasons.append('비교 실행 기록이 아직 없어요.')
        for side,row in [('baseline',before),('selected',after)]:
            if row and not row['comparisonEligible']:reasons.append(f'{side}: '+ ' / '.join(row['comparisonExclusionReasons']))
        pair={'case':case,'baselineVariant':baseline_by.get(case,'baseline'),'selectedVariant':selected,
              'usable':not reasons,'reasons':reasons,'before':before,'after':after}
        if before and after:
            pair['deltaPercent']={key:delta(before.get(key),after.get(key)) for key in (
                'wallSeconds','planningSeconds','firstResultSeconds','actualUsd','normalizedUncachedUsd',
                'inputTokens','cachedInputTokens','outputTokens','totalTokens','requests')}
        pairs.append(pair)
        if not reasons:usable.append(pair)
    def totals(eligible):
        before=aggregate([p['before'] for p in eligible]);after=aggregate([p['after'] for p in eligible])
        return {'pairCount':len(eligible),'before':before,'after':after,
                'deltaPercent':{key:delta(before.get(key),after.get(key)) for key in before if key not in ('runs','pages')}}
    return {'selectedVariant':selected,'baselineByCase':baseline_by,'requestedCases':wanted,
            'allPairsAvailable':len(usable)==len(wanted),'pairs':pairs,'totals':totals(usable),
            'withoutFlaggedServerOutliers':totals([p for p in usable if not (
                p['before']['serverOutlier'] or p['after']['serverOutlier'])]),
            'notes':[str(note) for note in decision.get('notes',[]) if isinstance(note,str)],
            'measurementNote':'각 변형은 문서별 단일 실행이에요. 합산 시간은 문서를 차례로 처리한 합계이며, 동시 사용자 처리량이나 반복 측정 평균이 아니에요.'}


def budget_summary(entries, ledger_count, duplicates, checkpoint=None):
    """Keep lifetime accounting while applying a renewed cap only to new IDs."""
    full=usage_stats(entries)
    value={**full,'ledgerFiles':ledger_count,'duplicateLedgerEntriesIgnored':duplicates,
           'normalizationNote':PRICE_NOTE,
           'note':'실패·중단·미채택 변형의 실제 비용과 미확정 예약을 모두 포함해요.'}
    active=full;approved=3.30;execution=3.25
    if checkpoint is not None:
        ids=checkpoint.get('preexistingRequestIds')
        approved=number(checkpoint.get('approvedNewCapUsd'))
        if (not isinstance(ids,list) or not all(isinstance(x,str) for x in ids)
                or approved is None or approved<=0):
            raise ValueError('새 예산 체크포인트의 요청ID 목록 또는 승인 금액이 올바르지 않아요.')
        old_ids=set(ids)
        previous=[entry for entry in entries if entry.get('requestId') in old_ids]
        current=[entry for entry in entries if entry.get('requestId') not in old_ids]
        active=usage_stats(current)
        execution=number(checkpoint.get('executionCapUsd'),approved)
        value.update(previousBudgetWindow=usage_stats(previous),currentBudgetWindow=active,
            capAppliesTo='currentBudgetWindow',
            checkpoint={'path':'budget-checkpoint-034740.json',
                        'createdAtUtc':checkpoint.get('createdAtUtc'),
                        'preexistingRequestIdsCount':len(old_ids),
                        'snapshotPreviousActualUsd':number(checkpoint.get('previousActualUsd')),
                        'snapshotPreviousUncertainReservedUsd':number(checkpoint.get('previousUncertainReservedUsd')),
                        'snapshotPreviousCommittedUsd':number(checkpoint.get('previousCommittedUsd')),
                        'classification':'체크포인트의 기존 요청ID는 이전 구간에 두고 나머지는 신규 구간에 넣어요. 기존 요청의 사용량이 뒤늦게 확정돼도 신규 비용으로 옮기지 않아요.'},
            note='누적 집계는 모든 시도를 포함해요. 새 승인 상한은 체크포인트 이후의 신규 요청에만 적용하며, 이전 요청은 제외해요. 각 구간의 미확정 요청은 보수 예약으로 포함해요.')
    else:value['capAppliesTo']='lifetime'
    adjusted=active['committedWithKnownCacheWriteUsd']
    value.update(approvedCapUsd=approved,executionCapUsd=execution,
                 approvedCapExceeded=adjusted>=approved,
                 executionCapExceeded=adjusted>execution,
                 remainingToApprovedCapUsd=round(approved-adjusted,10),
                 capCalculation='사용량 기준 원장 추정 + 미확정 보수 예약 + 확인된 표준 티어 cache-write 추가요금이에요. 원장 금액은 변경하지 않아요.',
                 cacheWritePricingSource='https://developers.openai.com/api/docs/models/gpt-6-luna')
    return value


def build_report(root):
    warnings=[];all_entries=[];by_folder={};ledger_paths=[]
    for path in sorted(root.glob('**/usage/*.json')):
        data=load(path,warnings)
        if not isinstance(data,dict):continue
        entries=[row for row in data.get('requests',[]) if isinstance(row,dict)]
        all_entries.extend(entries); by_folder.setdefault(path.parent.parent.resolve(),[]).extend(entries)
        ledger_paths.append(relative(path,root))
    unique,duplicates=deduplicate(all_entries)
    rows=[]
    folders=set(by_folder)
    folders.update(path.parent.resolve() for path in root.glob('runs/*/*/run.json'))
    for folder in sorted(folders):
        rel=relative(folder,root)
        if not rel or not rel.startswith('runs/'):continue
        path=folder/'run.json'; run=load(path,warnings) if path.is_file() else {}
        if not isinstance(run,dict):run={}
        parts=Path(rel).parts;case=run.get('case',parts[1]);variant=run.get('variant',parts[2])
        entries,_=deduplicate(by_folder.get(folder,[]));stats=usage_stats(entries)
        metrics=run.get('metrics') or {};planning=number(run.get('planningSeconds'))
        wall=number(run.get('wallSeconds'))
        frozen=run.get('frozenPlanning') if isinstance(run.get('frozenPlanning'),dict) else None
        post_group=wall-planning if wall is not None and planning is not None else None
        original_planning=number(frozen.get('originalPlanningSeconds')) if frozen else None
        modeled_equivalent=(original_planning+post_group
                            if original_planning is not None and post_group is not None else None)
        first=number(metrics.get('firstResultSeconds'))
        first=(planning+first) if planning is not None and first is not None else None
        result=result_counts(folder,warnings)
        failed=run.get('failedUnits') or []
        processing=run.get('processingComplete', result.get('processingComplete') if result else None)
        coverage=run.get('coverageComplete', result.get('coverageComplete') if result else None)
        excluded=[]
        if run.get('plannerOnly'):excluded.append('묶음 판단만 실행했어요.')
        if frozen:
            excluded.append('새 묶음 판단을 측정하지 않았어요(fresh planner not measured). 고정 묶음의 전체시간은 fresh 실행과 직접 비교하지 않아요.')
        if not path.is_file():excluded.append('실행이 진행 중이거나 종료 기록이 없어요.')
        if run.get('error') or failed or processing is not True:
            excluded.append('생성 실패·중단 또는 완료 확인이 필요해요.')
        contaminated=case=='integration' and variant=='baseline'
        if contaminated:excluded.append('기존 가짜 API 테스트의 공유 대기 약 48.4초가 섞여 정상 속도 비교에서 제외해요.')
        outlier=number(stats['maxServiceSecondsEstimate'],0)>=90
        notes=[]
        if outlier:notes.append('로컬 입장 대기를 뺀 개별 요청이 90초 이상 걸렸어요. 긴 응답으로 표시하고 원래 시간은 유지해요. 전송·서버 처리의 세부 원인은 하위 계측이 있는 요청에서만 구분해요.')
        if case=='finance' and variant=='baseline':notes.append('금융 기준 실행은 약 153.6초였고 개별 응답 약 135초가 지배했어요. 일반적인 처리 속도로 단정하지 않아요.')
        if coverage is False:notes.append('생성 완료와 별개로 일부 내용은 제외되었거나 확인이 필요해요.')
        if frozen:
            notes.append('고정 묶음 대조예요. 실제 첫 결과·전체시간은 새 planner를 포함하지 않아요. 원래 planning을 더한 등가시간은 실측이 아닌 계산 참고값이에요.')
        if metrics.get('overviewLocalFallback') is True:
            notes.append('선택 사항인 전체 개요 호출이 실패해 저장된 소제목으로 개요를 만들었어요. 이미 생성된 본문은 보존했고 추가 API 재시도는 하지 않았어요.')
        if result and result.get('pendingSummaryPages'):
            notes.append('요약 대기 페이지: '+', '.join(map(str,result['pendingSummaryPages']))+'쪽이에요.')
        if number(stats['maxQueueSeconds'],0)>1:notes.append('공유 제한에 따른 입장 대기가 포함됐어요. 다른 실행과 겹친 표본은 고립 실행과 구분해서 봐요.')
        rows.append({'case':case,'title':run.get('title',dict((c,t) for c,t,_ in CASES).get(case,case)),
                     'variant':variant,'pages':run.get('pages',dict((c,p) for c,_,p in CASES).get(case)),
                     'plannerOnly':bool(run.get('plannerOnly')),'wallSeconds':wall,
                     'planningSeconds':planning,'firstResultSeconds':first,
                     'frozenPlanning':frozen,'freshPlannerMeasured':not bool(frozen) and planning is not None,
                     'postGroupingSeconds':post_group,
                     'modeledEquivalentOriginalPlanningSeconds':modeled_equivalent,
                     'generationFirstResultSeconds':number(metrics.get('firstResultSeconds')),
                     'firstResultDefinition':'planningSeconds + metrics.firstResultSeconds',
                     'processingComplete':processing,'coverageComplete':coverage,
                     'failedUnits':len(failed),'errorType':run.get('error'),
                     'settings':run.get('settings') or {},'metrics':{k:v for k,v in metrics.items()
                         if isinstance(v,(int,float,bool)) or v is None or
                         (isinstance(v,list) and all(isinstance(x,(int,float,bool)) for x in v))},
                     'overviewLocalFallback':metrics.get('overviewLocalFallback',False),
                     'result':result,'path':relative(path,root) if path.is_file() else rel,
                     'comparisonEligible':not excluded,'comparisonExclusionReasons':excluded,
                     'queueContaminated':contaminated,'serverOutlier':outlier,
                     'longResponseOutlier':outlier,'notes':notes,**stats})
    rows.sort(key=lambda r:([c for c,_,_ in CASES].index(r['case']) if r['case'] in [c for c,_,_ in CASES] else 99,r['variant']))
    decision=load(root/'decision.json',warnings) if (root/'decision.json').is_file() else None
    backup=load(root/'baseline/manifest.json',warnings) if (root/'baseline/manifest.json').is_file() else None
    upload=load(root/'upload-performance.json',warnings) if (root/'upload-performance.json').is_file() else None
    history=load(root/'throughput/historical-analysis.json',warnings) if (root/'throughput/historical-analysis.json').is_file() else None
    observed=load(root/'throughput/observed-usage-20261021.json',warnings) if (root/'throughput/observed-usage-20261021.json').is_file() else None
    refill_path=root/'throughput/refill-v3-observation.json'
    refill=load(refill_path,warnings) if refill_path.is_file() else None
    checkpoint_path=root/'budget-checkpoint-034740.json'
    checkpoint=load(checkpoint_path,warnings) if checkpoint_path.is_file() else None
    if checkpoint_path.is_file() and not isinstance(checkpoint,dict):
        raise ValueError('새 예산 체크포인트를 읽지 못해 예산 구간을 안전하게 구분할 수 없어요.')
    return {'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
            'scope':{'plannedCases':len(CASES),'plannedPages':sum(p for _,_,p in CASES),
                     'casePages':{c:p for c,_,p in CASES},'measuredOncePerVariant':True},
            'budget':budget_summary(unique,len(ledger_paths),duplicates,checkpoint),
            'runs':rows,'comparisons':comparisons(decision,rows),'quality':quality_summary(root,warnings),
            'decision':decision,'observedThroughput':observed,'postMeasurementScheduler':refill,
            'backup':{'files':len(backup.get('files',[])),'created':backup.get('created'),
                      'credentialsIncluded':backup.get('credentialsIncluded'),'path':'baseline/manifest.json'} if isinstance(backup,dict) else None,
            'upload':upload,'throughput':{'historicalFullStudyStats':history.get('fullStudyStats'),
                                        'concurrencyAt60Pct':history.get('concurrencyAt60Pct'),
                                        'path':'throughput/README.md'} if isinstance(history,dict) else None,
            'limitations':[QUALITY_NOTE,'실제 사용자의 네트워크·서버 상태와 PDF 구성에 따라 시간이 달라져요.',
                           '첫 결과 시간은 묶음 판단 시간까지 포함해요. 묶음 판단만 실행했거나 해당 기록이 없으면 표시하지 않아요.',
                           '묶음을 재사용한 대조 실험은 새 planner를 측정하지 않았어요. 실제 측정값과 원래 planner 시간을 더한 계산 참고값을 구분하고 기본 전체시간 비교에서 제외해요.',
                           '캐시된 입력도 입력 토큰 합계에 포함해요. 캐시 절감 효과는 실제 비용과 캐시 미적용 비교 비용을 나란히 봐요.',
                           '분당 제한 계산에 쓰는 보수적인 예약량과 실제 사용 토큰은 달라요. 사용 가능한 작업이 적으면 제한의 60%를 채우기 위해 불필요한 호출을 만들지 않아요.'],
            'readWarnings':warnings}


def fmt(value,digits=1):
    return '—' if number(value) is None else f'{value:,.{digits}f}'


def money(value):return '—' if number(value) is None else f'${value:.5f}'


def change(value):return '—' if number(value) is None else f'{value:+.1f}%'


def link(path,label):
    return f'<a href="{escape(quote(path,safe="/"))}">{escape(label)}</a>' if path else escape(label)


def render_html(report):
    b=report['budget'];comp=report['comparisons'];chunks=[]
    active=b.get('currentBudgetWindow',b);renewed='checkpoint' in b
    def section(title,body):chunks.append(f'<section><h2>{escape(title)}</h2>{body}</section>')
    chunks.append('<header><p class="eyebrow">SYNESIS · PDF ENGINE AUDIT</p><h1>요약·개념 생성 속도 실험</h1>'
                  '<p class="lead">시간·토큰·비용과 내용 보존을 함께 비교해요. 실패한 시도와 남은 확인 사항도 포함했어요.</p>'
                  f'<p class="muted">6개 PDF · 예정 합계 168쪽 · {escape(report["generatedAt"][:19].replace("T"," "))} UTC</p></header>')
    chunks.append('<div class="cards">'+''.join(f'<div class="card"><span>{escape(label)}</span><strong>{value}</strong></div>' for label,value in [
        (('신규 ' if renewed else '')+'사용량 기준 추정 비용',money(active['actualUsd'])),
        (('신규 ' if renewed else '')+'미확정 보수 예약',money(active['uncertainReservedUsd'])),
        ('신규 시도 합계' if renewed else '모든 시도 합계',money(active['committedUsd'])),
        ('신규 승인 / 실행 상한' if renewed else '승인 상한 / 실행 상한',f'${b["approvedCapUsd"]:.2f} / ${b["executionCapUsd"]:.2f}')])+'</div>')
    status=('상한에 도달했거나 넘었어요. 비용 기록을 확인해 주세요.' if b['approvedCapExceeded'] else
            f'{"체크포인트 이후 신규 예산은 " if renewed else "승인된 예산은 "}${b["approvedCapUsd"]:.2f} 미만으로 관리하고 있어요.')
    body=f'<p>{escape(status)} 실패·중단·미채택 변형도 합쳤어요. 전송되지 않은 취소는 유료 요청에서 제외해요.</p>'
    if renewed:
        before=b['previousBudgetWindow'];cp=b['checkpoint']
        body+=f'<p>새 예산 기준: {escape(str(cp.get("createdAtUtc") or "—"))} · {link(cp["path"],"체크포인트 기록")}. 이전 요청 비용은 신규 ${b["approvedCapUsd"]:.2f} 한도에서 제외해요.</p>'
        body+='<div class="scroll"><table><thead><tr><th>구간</th><th>사용량 기준 추정</th><th>미확정 예약</th><th>합계</th><th>요청</th></tr></thead><tbody>'
        for label,stats in [('체크포인트 이전',before),('체크포인트 이후 신규',active),('전체 누적',b)]:
            body+=f'<tr><td>{escape(label)}</td><td>{money(stats["actualUsd"])}</td><td>{money(stats["uncertainReservedUsd"])}</td><td>{money(stats["committedUsd"])}</td><td>{stats["requests"]:,}회</td></tr>'
        body+='</tbody></table></div><p class="muted">이전 구간은 현재 원장의 확정 상태로 다시 계산해요. 체크포인트 당시 예약액과 달라질 수 있으며, 새로 확정된 이전 요청을 신규 비용으로 중복 계산하지 않아요.</p>'
    body+=f'<p>{"신규 " if renewed else ""}요청 {active["requests"]:,}회 · 미확정 {active["unknownUsageRequests"]:,}회 · 전송 전 취소 {active["notSentRequests"]:,}회 · '
    body+=f'입력 {active["inputTokens"]:,} / 캐시 입력 {active["cachedInputTokens"]:,} / 출력 {active["outputTokens"]:,} 토큰</p>'
    body+=f'<p>확인된 cache-write {active["cacheWriteTokens"]:,}토큰의 별도 추가요금 추정은 {money(active["knownCacheWriteSurchargeUsd"])}예요. '
    body+=f'원장 금액을 바꾸지 않고 상한 판단에는 이 금액을 더한 {money(active["committedWithKnownCacheWriteUsd"])}를 사용해요. '
    body+=f'<a href="{escape(b["cacheWritePricingSource"])}">공식 표준 티어 가격</a>의 입력 $0.10·cache-write $0.125 차이를 적용했어요.</p>'
    body+=f'<p class="muted">{escape(PRICE_NOTE)} 토큰을 확인하지 못한 요청의 비교 비용은 계산하지 않고, 예약액을 별도로 남겨요.</p>'
    section('비용 집계',body)
    if comp:
        rows=[]
        for p in comp['pairs']:
            before=p['before'];after=p['after'];dp=p.get('deltaPercent',{})
            name=next((t for c,t,_ in CASES if c==p['case']),p['case'])
            if before and after:
                state='비교 가능' if p['usable'] else '집계 제외'
                if before['serverOutlier'] or after['serverOutlier']:state+=' · 긴 응답 표본'
                rows.append('<tr>'+''.join(f'<td>{v}</td>' for v in [escape(name),
                    f'{fmt(before["firstResultSeconds"])} → {fmt(after["firstResultSeconds"])}',
                    f'{fmt(before["wallSeconds"])} → {fmt(after["wallSeconds"])}',change(dp.get('wallSeconds')),
                    f'{money(before["actualUsd"])} → {money(after["actualUsd"])}',
                    f'{money(before["normalizedUncachedUsd"])} → {money(after["normalizedUncachedUsd"])}',
                    escape(state)])+'</tr>')
            else:rows.append(f'<tr><td>{escape(name)}</td><td colspan="6">비교 기록이 아직 없어요.</td></tr>')
        body=f'<p>선택 변형: <strong>{escape(comp["selectedVariant"])}</strong>. {escape(comp["measurementNote"])}</p>'
        body+='<div class="scroll"><table><thead><tr>'+''.join(f'<th>{t}</th>' for t in ['PDF','첫 결과: 전 → 후 (초)','전체: 전 → 후 (초)','전체 변화','사용량 추정 비용: 전 → 후','캐시 미적용 비용: 전 → 후','비교 상태'])+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
        for label,total in [('비교 가능한 전체 표본',comp['totals']),('90초 이상 긴 응답 표본을 뺀 참고 집계',comp['withoutFlaggedServerOutliers'])]:
            before=total['before'];after=total['after'];dp=total['deltaPercent']
            body+=f'<p><strong>{escape(label)}</strong> · {total["pairCount"]}개: 합산 {fmt(before["wallSeconds"])} → {fmt(after["wallSeconds"])}초 ({change(dp.get("wallSeconds"))}), '
            body+=f'토큰 {fmt(before["totalTokens"],0)} → {fmt(after["totalTokens"],0)} ({change(dp.get("totalTokens"))}), 비용 {money(before["actualUsd"])} → {money(after["actualUsd"])}.</p>'
        if not comp['allPairsAvailable']:body+='<p class="warning">일부 실행이 빠졌거나 비교에서 제외되어 부분 집계예요. 아래 전체 실행 기록에서 이유를 확인해 주세요.</p>'
        for note in comp['notes']:body+=f'<p class="muted">{escape(note)}</p>'
        body+='<p>'+link('decision.json','기본 설정과 후보별 채택·거부 이유')+' · '+link('selected-defaults.json','원본 프롬프트 동일성 확인')+'</p>'
        section('선택한 변형과 기준 실행',body)
    else:section('실험 선택 상태','<p>아직 최종 변형을 선택하지 않았어요. 아래 기록은 실험 목록이며, 가장 빠른 시도를 자동으로 채택하지 않아요.</p>')
    def run_table(rows):
        out=[]
        for r in rows:
            status='생성 완료' if r['processingComplete'] is True else '미완료'
            if r['plannerOnly']:status='묶음 판단만'
            if r['errorType']:status+=' · '+str(r['errorType'])
            if r['failedUnits']:status+=f' · 실패 {r["failedUnits"]}'
            if r.get('overviewLocalFallback'):status+=' · 로컬 개요 대체'
            if r.get('frozenPlanning'):status+=' · 묶음 고정'
            if r['coverageComplete'] is False:status+=' · 내용 확인 필요'
            if r['queueContaminated']:status+=' · 대기 혼입'
            if r['serverOutlier']:status+=' · 긴 응답'
            if number(r['maxQueueSeconds'],0)>1:status+=' · 입장 대기 포함'
            detail=r['notes']+r['comparisonExclusionReasons']
            note='<details><summary>상태·설정</summary><p>'+escape(' '.join(detail) or '별도 주의 사항이 없어요.')+'</p><pre>'+escape(json.dumps(r['settings'],ensure_ascii=False,indent=2))+'</pre></details>'
            vals=[escape(r['title']),link(r['path'],r['variant']),fmt(r['planningSeconds']),fmt(r['firstResultSeconds']),fmt(r['wallSeconds']),
                  fmt(r['maxQueueSeconds']),fmt(r['maxServiceSecondsEstimate']),str(r['requests']),
                  f'{r["inputTokens"]:,} / {r["cachedInputTokens"]:,} / {r["outputTokens"]:,}',money(r['actualUsd']),
                  money(r['normalizedUncachedUsd']),money(r['uncertainReservedUsd']),escape(status)+note]
            out.append(f'<tr data-case="{escape(r["case"])}">'+''.join(f'<td>{v}</td>' for v in vals)+'</tr>')
        headers=['PDF','변형','묶음 (초)','첫 결과 (초)','전체 (초)','최대 대기 (초)','최장 응답 추정 (초)','호출','입력 / 캐시 / 출력 토큰','사용량 추정','캐시 미적용','미확정 예약','상태']
        return '<div class="scroll"><table><thead><tr>'+''.join(f'<th>{h}</th>' for h in headers)+'</tr></thead><tbody>'+''.join(out)+'</tbody></table></div>'
    options='<option value="">모든 PDF</option>'+''.join(f'<option value="{c}">{escape(t)}</option>' for c,t,_ in CASES)
    section('전체 생성 실험',f'<label class="filter">PDF 선택 <select id="caseFilter">{options}</select></label>'+run_table([r for r in report['runs'] if not r['plannerOnly']])+
            '<p class="muted">최대 대기는 호출 전 입장 대기예요. 최장 응답 추정은 호출 기록 시간에서 입장 대기를 뺀 값이며 순수 모델 계산 시간은 아니에요. 대기 기록이 없는 예전 요청은 0초로 단정하지 않아요.</p>')
    planners=[r for r in report['runs'] if r['plannerOnly']]
    if planners:section('묶음 판단만 한 실험',run_table(planners)+'<p class="muted">요약 생성 시간을 비교하는 표본에 포함하지 않아요. 실패한 판단 호출의 미확정 비용도 총예산에 포함했어요.</p>')
    frozen_runs=[r for r in report['runs'] if r.get('frozenPlanning')]
    if frozen_runs:
        body='<p class="warning">이 대조 실험은 이미 정한 묶음을 사용했어요. 새 묶음 판단을 재지 않았으므로 실제 전체·첫 결과 시간을 fresh 실행보다 빨라진 값으로 직접 비교하지 않아요.</p>'
        body+='<div class="scroll"><table><thead><tr>'+''.join(f'<th>{label}</th>' for label in ['PDF','변형 / 묶음 출처','실제 묶음 로드(초)','묶음 이후 실측(초)','실제 첫 결과(초)','실제 전체(초)','원래 planning+이후 계산값(초)'])+'</tr></thead><tbody>'
        for row in frozen_runs:
            source=row['frozenPlanning'].get('variant','—')
            values=[escape(row['title']),escape(f'{row["variant"]} / {source}'),fmt(row['planningSeconds']),
                    fmt(row['postGroupingSeconds']),fmt(row['firstResultSeconds']),fmt(row['wallSeconds']),
                    fmt(row['modeledEquivalentOriginalPlanningSeconds'])]
            body+='<tr>'+''.join(f'<td>{value}</td>' for value in values)+'</tr>'
        body+='</tbody></table></div><p class="muted">묶음 이후=실제 전체−이번 묶음 로드예요. 마지막 계산값은 원래 실행의 planning+이번 묶음 이후 시간이며 실제 fresh 측정값이 아니에요. 고정 묶음 사전 준비·캐시 상태도 fresh 실행과 다를 수 있어요.</p>'
        section('묶음 고정 대조 실험',body)
    qbody=f'<p class="warning">{escape(QUALITY_NOTE)}</p><p>{escape(report["quality"]["note"])}</p><ul>'
    for doc in report['quality']['documents']:
        counts=' · '.join(f'{key} {value}' for key,value in doc['verdictCounts'].items())
        issues=' · '.join(f'{key} {value}' for key,value in doc['issueCategories'].items())
        sample_label=f'대조 항목 {doc["sampleChecks"]}개' if doc['sampleChecks'] else '보조 진단 기록'
        qbody+=f'<li>{link(doc["path"],doc["name"])} — {sample_label}'
        if counts:qbody+=f'<br><span class="muted">{escape(counts)}</span>'
        if issues:qbody+=f'<br><span class="warning">{escape(issues)}</span>'
        qbody+='</li>'
    qbody+='</ul><p class="muted">이 HTML에는 PDF 원문이나 생성된 학습 본문을 싣지 않았어요. 세부 근거는 로컬 대조 파일에서 확인해 주세요.</p>'
    section('품질과 누락·중복 검토',qbody)
    backup=report['backup']; upload=report['upload'];history=report['throughput'];aux=[]
    if backup:aux.append(f'<p>기존 엔진·프롬프트·설정·화면 소스 {backup["files"]:,}개 파일을 보관했어요. {link(backup["path"],"백업 해시 목록")} · {link("baseline-restore.md","복원 안내")} · 인증정보 포함: {"예" if backup["credentialsIncluded"] else "아니요"}.</p>')
    if upload:
        aux.append(f'<p>업로드 직후 로컬 준비의 중앙값: {fmt(number(upload.get("beforeMedianSeconds"),0)*1000,1)} → {fmt(number(upload.get("afterMedianSeconds"),0)*1000,1)}ms '
                   f'({fmt(upload.get("medianReductionPercent"))}% 감소). {link("upload-performance.json","업로드 반응 측정")}.</p>')
        aux.append('<p class="muted">Mac의 합성 빈 PDF 1쪽·변형별 6회 측정이에요. 실제 Windows FPS나 복잡한 PDF 전체 처리 시간을 뜻하지 않아요. 기존 전체 화면 스모크 테스트는 바꾸지 않은 메뉴 문구 검사에서 멈춘 한계가 있어요.</p>')
    if history:
        stats=history.get('historicalFullStudyStats') or {};lat=stats.get('latencySeconds') or {};tok=stats.get('actualTotalTokens') or {}
        aux.append(f'<p>과거 전체 문서 분석 호출 {lat.get("count",0)}회: 평균 {fmt(lat.get("mean"))}초, 실제 평균 {fmt(tok.get("mean"),0)}토큰. '
                   f'{link(history["path"],"병렬도·처리량 분석")}, {link("throughput/historical-analysis.json","이력 계산 데이터")}.</p>')
    observed=report.get('observedThroughput') or {}
    observed_variant=(observed.get('variants') or {}).get((report.get('decision') or {}).get('selectedVariant'))
    if observed_variant:
        billed=(observed_variant.get('peakBilledTokensAttributedToSentAtIn60Seconds') or {}).get('amount')
        rpm=(observed_variant.get('peakSentRPM60Seconds') or {}).get('amount')
        reserved=(observed_variant.get('estimatedLiveAdmissionReservationPeak') or {}).get('tokens')
        aux.append(f'<p>이번 기본안의 60초 구간 피크는 실제 사용 토큰 {fmt(billed,0)}(전송 시각에 귀속한 지표), {fmt(rpm,0)}회 요청이었어요. 제한 예약량 피크의 재구성 근삿값은 {fmt(reserved,0)}토큰, 진행 중 요청은 최대 {fmt(observed_variant.get("estimatedPeakRequestsInFlight"),0)}개였어요. 설정한 비율은 입장 상한이며 실제 사용률 달성을 뜻하지 않아요. '+link('throughput/observed-usage-20261021.json','실측 범위·계산법·한계')+'.</p>')
        aux.append('<p>현재 운영안은 PDF당 API 14개·공유 64개 상한과 준비 작업 1개를 사용해요. '+
                   link('throughput/operational-scheduling-observations.json','실제 동시성·첫 결과·완료 대기 기록')+' · '+
                   link('throughput/observed-usage-phase1-final-20261021.json','이전 1단계 32개 상한의 별도 기록')+'.</p>')
    refill=report.get('postMeasurementScheduler')
    if isinstance(refill,dict):
        aux.append('<p>6개 PDF의 위 시간표는 사후 스케줄러 수정 전 실측을 그대로 보존해요. 이후 예산 회복 즉시 재투입을 보완하고 인상주의 1건만 고정 묶음으로 확인했어요. '
                   f'첫 정산 {fmt(refill.get("firstInitialResponseSeconds"),3)}초 뒤 {fmt(refill.get("nextRequestStartSeconds"),3)}초에 다음 요청을 시작해, '
                   f'{fmt(refill.get("lastInitialSiblingResponseSeconds"),3)}초까지 걸린 다른 요청을 기다리지 않았어요. '
                   '이 표본은 금액 예약 제한으로 실제 동시 최대가10개였고 API 상한은14개예요. 6개 PDF 전체를 다시 측정한 결과는 아니며 캐시와 원격 응답 시간도 달라졌어요. '+
                   link('throughput/refill-v3-observation.json','사후 수정·전송시각·한계')+' · '+
                   link('quality/deferred-recovery-regression.json','무과금 회귀 검사')+'.</p>')
    if (report.get('decision') or {}).get('selectedVariant'):
        aux.append('<p>'+link('quality/image-inflight-memory.json','이미지 전송 버퍼 비교')+' · '+link('quality/baseline-local-replay.json','기존 본문 오프라인 재생')+' · '+link('validation.json','개발 검사 결과')+' · '+link('selected-source/manifest.json','선택한 엔진 소스 스냅샷')+'</p>')
    aux.append('<p>공식 Luna 표준 제한은 Build 200만 TPM / 5,000 RPM, Launch 1,000만 TPM / 10,000 RPM이에요. 실제 업그레이드 전에는 Build를 적용하고 더 낮은 계정·프로젝트 제한을 우선해요. '
               '<a href="https://developers.openai.com/api/docs/models/gpt-6-luna">공식 모델 제한</a> · <a href="https://developers.openai.com/api/docs/guides/rate-limits">제한 계산 안내</a>.</p>')
    section('백업·화면 반응·병렬도', ''.join(aux))
    section('해석할 때 확인할 점','<ul>'+''.join(f'<li>{escape(note)}</li>' for note in report['limitations'])+'</ul>'+
            (f'<p class="warning">읽기 오류 {len(report["readWarnings"])}개가 있어요. '+link('report.json','상세 집계')+'에서 확인해 주세요.</p>' if report['readWarnings'] else '')+
            '<p>'+link('report.json','전체 수치 JSON')+'</p>')
    css='''*{box-sizing:border-box}body{margin:0;background:#f4f7fc;color:#192b44;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1550px;margin:auto;padding:48px 30px 70px}header{padding:12px 5px 24px}.eyebrow{letter-spacing:.15em;font-size:11px;font-weight:700;color:#52749d}h1{font-size:34px;letter-spacing:-.04em;margin:8px 0 12px}h2{font-size:21px;letter-spacing:-.025em;margin:0 0 15px}.lead{font-size:17px;color:#526985;max-width:820px}.muted{color:#71839b;font-size:13px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:12px 0 24px}.card,section{background:white;border:1px solid #dce5f2;border-radius:17px}.card{padding:20px 23px;box-shadow:0 4px 20px #0b2b5b04}.card span{display:block;color:#71839b;font-size:12px}.card strong{font-size:25px;display:block;margin-top:7px;color:#082b61}section{padding:26px;margin:18px 0;overflow:hidden}a{color:#174b8c;text-decoration:none;border-bottom:1px solid #c7d8ef}a:hover{color:#041f4d;border-bottom-color:currentColor}.scroll{overflow:auto;margin:18px -2px 10px}table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}th{background:#eef3fa;color:#4b6689;font-size:11px;font-weight:600;text-align:left;padding:12px;position:sticky;top:0}td{border-bottom:1px solid #edf1f7;padding:12px;vertical-align:top}tbody tr:hover{background:#f7faff}td:last-child{white-space:normal;min-width:190px;max-width:350px}details{margin-top:6px;color:#6a7e99;font-size:11px}summary{cursor:pointer;color:#365d8b}pre{white-space:pre-wrap;line-height:1.4}.warning{color:#a16329;background:#fff9ef;border-radius:8px;padding:10px 13px}.filter{font-size:13px;color:#5c7392}select{margin-left:10px;padding:8px 12px;border:1px solid #cddbed;border-radius:8px;background:white;color:#193f70}li{margin:10px 0}@media(max-width:800px){main{padding:22px 13px}h1{font-size:27px}.cards{grid-template-columns:repeat(2,1fr)}.card{padding:15px}.card strong{font-size:21px}section{padding:19px}}'''
    js="document.getElementById('caseFilter').addEventListener('change',e=>{document.querySelectorAll('tr[data-case]').forEach(r=>r.hidden=!!e.target.value&&r.dataset.case!==e.target.value)});"
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SYNESIS PDF 속도 실험</title><style>'+css+'</style><main>'+''.join(chunks)+'</main><script>'+js+'</script></html>'


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--root','--output',dest='root',type=Path,default=DEFAULT_ROOT)
    args=parser.parse_args();root=args.root.resolve()
    if not root.is_dir():parser.error('기존 실험 폴더가 필요해요.')
    report=build_report(root)
    # No source text, API credentials, response bodies or full ledger entries are
    # exported. This report only writes numeric summaries and local references.
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'report.html').write_text(render_html(report),encoding='utf-8')
    print(json.dumps({'runs':len(report['runs']),'actualUsd':report['budget']['actualUsd'],
                      'uncertainReservedUsd':report['budget']['uncertainReservedUsd'],
                      'committedUsd':report['budget']['committedUsd'],
                      'selectedVariant':(report['comparisons'] or {}).get('selectedVariant'),
                      'readWarnings':len(report['readWarnings'])},ensure_ascii=False))


if __name__=='__main__':main()
