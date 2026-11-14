"""Rebuild the local cost/time report from saved metadata. No API/UI calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
from pathlib import Path

from audit_pdf_cost_metrics import usage_metrics

DEFAULT_ROOT = Path('build/pdf-cost-20261021')
QUALITY_NOTE = ('품질 동등은 확인하지 못했어요. 완료된 출력에도 수식·조건·명칭의 누락이나 '
                '오독이 있어요. 시간·비용 개선을 품질 유지 성공으로 해석하지 않아요.')


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def public_usage(value):
    return {key: child for key, child in value.items() if key not in ('requestMetrics',)}


def ledger_rows(root):
    """Include nested probes, without ever reconciling or writing the registry."""
    rows = []; evidence = []
    for path in sorted((Path(root)/'runs').glob('**/usage/*.json')):
        raw = path.read_bytes(); data = json.loads(raw)
        if data.get('model') != 'gpt-6-luna' or not isinstance(data.get('requests'),list):
            raise ValueError('Unsupported model or malformed ledger in cost comparison.')
        rows.extend(data['requests'])
        evidence.append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest(),
                         'model':data['model'],'requests':len(data['requests'])})
    return rows,evidence


def budget_summary(root, records):
    """Read the approved boundary and SharedBudget snapshot; never call snapshot().

    The admission helper's cumulative historical registry intentionally keeps its
    original $1 limit. Only activeWindow is chargeable to the later approval.
    Ledger token totals and the immutable approval-time checkpoint stay separate
    from that authoritative money/reservation snapshot.
    """
    rows,evidence = ledger_rows(root)
    cumulative = public_usage(usage_metrics(rows))
    cumulative['actualKnownUsd'] = cumulative['usageBasedUsd']+cumulative['additionalCacheWritePremiumUsd']
    recorded = read(root/'budget.json',{})
    registry = recorded.get('requests') or {}
    if not isinstance(registry,dict):raise ValueError('Malformed budget request registry.')
    approval_path = root/'approved-window.json'
    approval = read(approval_path)
    previous = None; checkpoint = set(); active_rows = rows
    if approval is not None:
        if not isinstance(approval,dict) or approval.get('schemaVersion')!=1:
            raise ValueError('Malformed explicit approval checkpoint.')
        if (not isinstance(approval.get('authorization'),str) or not approval['authorization'].strip()
                or not isinstance(approval.get('createdAtUtc'),str) or not approval['createdAtUtc'].strip()):
            raise ValueError('The approval must preserve its explicit authorization and date.')
        for key in ('approvedLimitUsd','executionCapUsd','baseActualKnownUsd','baseCommittedUsd'):
            amount = approval.get(key)
            if type(amount) not in (int,float) or not math.isfinite(amount) or amount<0:
                raise ValueError('Invalid approval checkpoint amount.')
        if (approval['approvedLimitUsd']<=.02 or approval['executionCapUsd']<=0 or
                approval['executionCapUsd']>approval['approvedLimitUsd']-.02+1e-12):
            raise ValueError('The approval must retain its execution headroom.')
        digest = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        if recorded.get('approvedWindowSha256') not in (None,digest):
            raise ValueError('The saved approval checkpoint hash changed.')
        ids = approval.get('checkpointRequestIds')
        if (not isinstance(ids,list) or any(not isinstance(key,str) or not key for key in ids)
                or len(ids)!=len(set(ids)) or not set(ids).issubset(registry)
                or approval.get('baseRequestCount',len(ids))!=len(ids)):
            raise ValueError('Approval checkpoint IDs must match the existing registry.')
        checkpoint = set(ids)
        active_rows = [row for row in rows if row.get('requestId') in registry and row.get('requestId') not in checkpoint]
        previous = {'approvedCapUsd':recorded.get('limitUsd',1.),'checkpointRequestCount':len(ids),
            'actualKnownUsdAtApproval':approval.get('baseActualKnownUsd'),
            'committedUsdAtApproval':approval.get('baseCommittedUsd'),
            'checkpointCreatedAtUtc':approval.get('createdAtUtc'),
            'scope':'승인 시점에 고정한 이전 요청 집계예요. 신규 승인 한도에서 다시 차감하지 않아요.'}
    elif recorded.get('approvedWindowSha256'):
        raise ValueError('The bound explicit approval checkpoint is missing.')

    budget = public_usage(usage_metrics(active_rows))
    observed_actual = budget['usageBasedUsd']+budget['additionalCacheWritePremiumUsd']
    snapshot = recorded.get('activeWindow')
    if snapshot is not None and not isinstance(snapshot,dict):raise ValueError('Malformed active budget window.')
    if approval is not None:
        if not snapshot:
            raise ValueError('The approved checkpoint has no active budget snapshot.')
        if (snapshot.get('approvedLimitUsd')!=approval.get('approvedLimitUsd') or
                snapshot.get('executionCapUsd')!=approval.get('executionCapUsd') or
                snapshot.get('checkpointRequestCount')!=len(checkpoint)):
            raise ValueError('The active budget window disagrees with its approval checkpoint.')
    if snapshot:
        for key in ('approvedLimitUsd','executionCapUsd','committedUsd','actualKnownUsd',
                    'missingCacheWriteUpperBoundUsd','conservativeUnknownReservedUsd'):
            value = snapshot.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('Invalid active budget snapshot amount.')
        budget.update({key:snapshot[key] for key in ('committedUsd','actualKnownUsd',
            'missingCacheWriteUpperBoundUsd','conservativeUnknownReservedUsd')})
        cap = snapshot['approvedLimitUsd']; execution = snapshot['executionCapUsd']
        count = snapshot.get('requestCount')
        snapshot_scope = '저장된 SharedBudget.activeWindow snapshot'
    else:
        cap = recorded.get('limitUsd',1.); execution = max(0.,cap-.02)
        budget['actualKnownUsd'] = observed_actual
        count = budget['requests']+budget['notSentRequests']
        snapshot_scope = '승인 창 전환 전 원장의 읽기 전용 재계산'
    budget.update(approvedCapUsd=cap,executionCapUsd=execution,
        remainingToCapUsd=max(0.,cap-budget['committedUsd']),
        remainingToExecutionCapUsd=max(0.,execution-budget['committedUsd']),
        registeredRequestCount=count,checkpointRequestCount=len(checkpoint),
        ledgerObservedActualKnownUsd=observed_actual,
        recordedBudgetCommittedUsd=recorded.get('committedUsd'),
        snapshotScope=snapshot_scope,activeWindow=public_usage(snapshot) if snapshot else None,
        previousWindow=previous,cumulativeAllRunLedgers=cumulative,
        ledgerFiles=len(evidence),ledgerEvidence=evidence,
        approvalPath='approved-window.json' if approval is not None else None,
        approvalCheckpointValidated=approval is not None,
        unregisteredLedgerRequestCount=len({row['requestId'] for row in rows if registry and row['requestId'] not in registry}),
        snapshotMayChangeWhileRunning=(any(not row['recordComplete'] for row in records)
            or budget['unknownUsageRequests']>0 or not math.isclose(observed_actual,budget['actualKnownUsd'],abs_tol=1e-10)),
        note=('신규 승인 창의 요청만 현재 한도에서 차감해요. 이전 승인 시점 집계와 전체 누적 원장은 별도예요. '
              '금액·미확정 예약은 저장된 activeWindow snapshot, 토큰·cache-write 관측값은 해당 창 원장에서 읽어요. '
              '진행 중에는 두 snapshot의 저장 시점 차이가 있을 수 있어요.' if approval is not None else
              '현재 승인 창의 원장만 읽기 전용으로 집계해요. 사용량 추정·cache-write 보정·미확정 안전예약을 포함해요.'))
    registered_active = {key:row for key,row in registry.items() if key not in checkpoint}
    observed_ids = {row['requestId'] for row in active_rows}
    budget['registeredUnresolvedRequestCount'] = (sum(row.get('state') not in ('settled','not_sent')
        for row in registered_active.values()) if registry else budget['unknownUsageRequests'])
    budget['registeredRequestsWithoutLedger'] = len(set(registered_active)-observed_ids)
    budget['snapshotMayChangeWhileRunning'] |= bool(budget['registeredRequestsWithoutLedger'])
    return budget


def unit_coverage(rows, cache):
    """Account original unit IDs independently of their RPC batch grouping."""
    metrics = usage_metrics(rows)
    states = {row['requestId']:row['state'] for row in metrics['requestMetrics']}
    selected = {}
    for row in rows:
        if (row.get('kind')=='region_study' and row.get('state')==states.get(row.get('requestId'))
                and row.get('state')!='not_sent'):
            selected.setdefault(row['requestId'],row)
    ids = []; invalid = False; settled = set(); batches = 0
    for row in selected.values():
        targets = row.get('unitIds')
        if not isinstance(targets,list) or not targets or any(not isinstance(key,str) or not key for key in targets):
            invalid = True; continue
        ids.extend(targets)
        if len(targets)>1:batches+=1
        if row.get('state')=='settled':settled.update(targets)
    counts = Counter(ids); unique = set(counts)
    manifest_path = cache/'manifest.json' if cache else None
    manifest = read(manifest_path,{}) if manifest_path else {}
    jobs = manifest.get('jobs') if isinstance(manifest,dict) else None
    expected = None; manifest_malformed = bool(manifest_path and manifest_path.is_file())
    if isinstance(jobs,list):
        values = [job.get('id') for job in jobs if isinstance(job,dict) and not job.get('skip')]
        if (len(values)==len(jobs)-sum(isinstance(job,dict) and bool(job.get('skip')) for job in jobs)
                and all(isinstance(key,str) and key for key in values) and len(values)==len(set(values))):
            expected = set(values)
            manifest_malformed = False
    proof = {'submittedUniqueUnits':len(unique),'settledUniqueUnits':len(settled),
        'duplicateSubmittedUnits':sum(count>1 for count in counts.values()),
        'malformedUnitIds':invalid,'observedStudySubmissions':len(selected),
        'observedBatchSubmissions':batches,'plannedPaidUnits':len(expected) if expected is not None else None,
        'malformedManifest':manifest_malformed,
        'plannedUnitCoverageComplete':expected==unique if expected is not None else None,
        'submittedUnitIdsSha256':hashlib.sha256(json.dumps(sorted(unique)).encode()).hexdigest(),
        'scope':'원래 unit ID의 제출·settled 범위예요. 출처 ID별 본문 완전성이나 생성 품질의 증명은 아니에요.'}
    return proof


def request_timing(rows):
    """Client-observed network intervals, never configured thread-pool size.

    Provider latency includes pre-send admission queue time. Prefer measured
    encode/header/body phases; otherwise subtract a recorded queue before
    anchoring latency at sentAtMs. Never count that queue a second time.
    No end time is invented for a pending request. Identical request IDs are
    counted once, while a longer observed latency in a later snapshot survives.
    Half-open intervals ensure an ending call and a newly sent call at the same
    millisecond do not falsely inflate the peak.
    """
    metrics=usage_metrics(rows)
    states={row['requestId']:row['state'] for row in metrics['requestMetrics']}
    groups={}
    for row in rows:
        if row.get('state')==states.get(row.get('requestId')) and row.get('state')!='not_sent':
            groups.setdefault(row['requestId'],[]).append(row)
    def number(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
    def network_duration(row):
        if number(row.get('connectionAndResponseHeadersSeconds')) and number(row.get('responseBodySeconds')):
            encoded=row.get('requestEncodeSeconds',0)
            if not number(encoded):return None
            return (encoded+row['connectionAndResponseHeadersSeconds']+row['responseBodySeconds'],'network_phase_fields')
        if not number(row.get('latencySeconds')):return None
        if 'queueSeconds' in row:
            if not number(row['queueSeconds']) or row['queueSeconds']>row['latencySeconds']:return None
            return (row['latencySeconds']-row['queueSeconds'],'latency_minus_queue')
        return (row['latencySeconds'],'legacy_latency_without_queue_metadata')
    latencies=[];network_latencies=[];queues=[];events=[];intervals=0;sent=0;methods=Counter()
    for snapshots in groups.values():
        measured=[row for row in snapshots if number(row.get('latencySeconds'))]
        observed=[(row,network_duration(row)) for row in snapshots]
        observed=[(row,duration) for row,duration in observed if duration is not None]
        anchored=[(row,duration) for row,duration in observed if number(row.get('sentAtMs'))]
        if any(number(row.get('sentAtMs')) for row in snapshots):sent+=1
        if measured:latencies.append(max(row['latencySeconds'] for row in measured))
        if observed:network_latencies.append(max(duration[0] for _,duration in observed))
        queued=[row['queueSeconds'] for row in snapshots if number(row.get('queueSeconds'))]
        if queued:queues.append(max(queued))
        if not anchored:continue
        row,(duration,method)=max(anchored,key=lambda value:value[1][0])
        start=row['sentAtMs']/1000;end=start+duration;intervals+=1;methods[method]+=1
        if end>start:events.extend(((start,1),(end,-1)))
    active=peak=0
    for _,delta in sorted(events,key=lambda event:(event[0],event[1])):
        active+=delta;peak=max(peak,active)
    return {'maxRequestSeconds':max(latencies) if latencies else None,
        'maxNetworkRequestSeconds':max(network_latencies) if network_latencies else None,
        'maxQueueSeconds':max(queues) if queues else None,'networkTimingMethods':dict(methods),
        'peakActiveRequest':peak if intervals else None,'totalRequests':len(groups),
        'sentTimestampRequests':sent,'networkIntervalsObserved':intervals,
        'requestsWithoutCompleteTiming':len(groups)-intervals,
        'notSentRequestsExcluded':metrics['notSentRequests'],
        'scope':'중복 request ID와 not_sent를 제외해요. 최대 전체 지연에는 admission 대기와 실패 요청도 포함해요. '
                '동시 요청 수는 sentAtMs 뒤 encode/header/body 실측 합계를 우선 사용하고, 없으면 latencySeconds에서 queueSeconds를 빼 추정해요. '
                '대기 기록 없는 옛 요청만 latency를 그대로 쓰며, 이 경우 networkTimingMethods에 별도 표시해요. '
                '시각·지연이 없는 요청은 구간을 만들지 않으므로 진행 중/누락 시 peak는 관측 하한이에요. '
                '서버 내부 병렬 처리 수나 설정된 worker 수의 증명은 아니에요.'}


def first_summary(folder, run):
    path = folder/'progress.jsonl'
    cache = Path(run['cacheRoot']) if run.get('cacheRoot') else None
    if path.is_file() and cache:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # A currently appended final line can be incomplete.
            if event.get('event') != 'summary_unit_ready' or type(event.get('unit')) is not int:
                continue
            unit = read(cache/f'unit-{event["unit"]-1:05d}.json', {})
            if (unit.get('summary') or {}).get('parts'):
                return event.get('seconds'), '비어 있지 않은 요약 unit의 공개 이벤트'
    return (run.get('metrics') or {}).get('firstResultSeconds'), '엔진의 첫 결과 상대시간'


def collect_runs(root):
    records = []; private = {}; root=Path(root)
    folders = {path.parent for path in (root/'runs').glob('**/run.json')}
    folders.update(path.parent.parent for path in (root/'runs').glob('**/usage/*.json'))
    for folder in sorted(folders):
        run = read(folder/'run.json', {})
        rows = []
        for ledger in sorted((folder/'usage').glob('*.json')):
            data = read(ledger)
            if data.get('model') != 'gpt-6-luna':
                raise ValueError('Unsupported model in cost comparison.')
            rows.extend(data['requests'])
        if not run and not rows:
            continue
        usage = usage_metrics(rows)
        document = read(folder/'document.json', {})
        first, first_method = first_summary(folder, run)
        partial_pages = bool(run.get('onlyPages'))
        partial_units = bool(run.get('onlyUnitIds'))
        partial = partial_pages or partial_units or run.get('sampleOnly') is True
        finished = bool(run) and run.get('processingComplete') is True and not run.get('failedUnits') and not run.get('error')
        status = ('측정 중' if not run else '실패·일부 실패' if run.get('error') or run.get('failedUnits')
                  else '일부 페이지만 측정' if partial_pages else '일부 unit 표본' if partial_units
                  else '표본 측정' if partial else '생성 종료' if finished else '미완료')
        metrics = run.get('metrics') or {}
        cache = Path(run['cacheRoot']) if run.get('cacheRoot') else None
        coverage = unit_coverage(rows,cache)
        timing = request_timing(rows)
        variant = str(folder.relative_to(root/'runs'))
        records.append({'variant':variant,'status':status,'recordComplete':bool(run),
            'processingComplete':run.get('processingComplete'),'coverageComplete':run.get('coverageComplete'),
            'qualityEquivalent':False,'onlyPages':run.get('onlyPages'),'onlyUnitIds':run.get('onlyUnitIds'),
            'sampleOnly':partial,'partialPageProbe':partial_pages,'partialUnitProbe':partial_units,
            'fullRunEligible':finished and not partial and not usage['unknownUsageRequests'],
            'physicalPages':len(document.get('pages') or []),
            'workers':run.get('workers',metrics.get('workers')),'aliases':run.get('aliases'),
            'aliasPool':run.get('aliasPool'),'compactPrompt':run.get('compactPrompt',False),
            'compactTableSetup':run.get('compactTableSetup',False),
            'sourceSha256':run.get('sourceSha256'),'planSha256':run.get('planSha256'),
            'teachingIdentity':run.get('teachingIdentity'),'freshPlanningIncluded':False,
            'wallSeconds':run.get('wallSeconds'),'firstSummarySeconds':first,
            'firstSummaryDefinition':first_method,'studyJobs':metrics.get('studyJobs'),
            'newStudyJobs':metrics.get('newStudyJobs'),'extraReviewCalls':metrics.get('extraReviewCalls'),
            'batchUnits':run.get('batchUnits',metrics.get('transportBatchUnits',1 if run else None)),
            'batchImages':run.get('batchImages',metrics.get('transportBatchImages',4 if run else None)),
            'batchSubmissions':metrics.get('transportSubmissions',coverage['observedStudySubmissions']),
            'balancedBatches':run.get('balancedBatches',metrics.get('transportBalanced',False if run else None)),
            'batchAliases':run.get('batchAliases',False if run else None),
            'batchAliasPool':run.get('batchAliasPool',metrics.get('transportBatchAliasPool')),
            'sourceCoverageHint':run.get('sourceCoverageHint',metrics.get('sourceCoverageHint')),
            'studyInputApi':run.get('studyInputApi',metrics.get('studyInputApi','chat' if run else None)),
            'statementUncertainty':run.get('statementUncertainty',False if run else None),
            'maxRequestSeconds':timing['maxRequestSeconds'],'peakActiveRequest':timing['peakActiveRequest'],
            'maxNetworkRequestSeconds':timing['maxNetworkRequestSeconds'],'maxQueueSeconds':timing['maxQueueSeconds'],
            'totalRequests':timing['totalRequests'],'requestTiming':timing,
            'unitIdCoverage':coverage,
            'failedUnitCount':len(run.get('failedUnits') or []),'errorType':run.get('error'),
            'runPath':str((folder/'run.json').relative_to(root)),
            'cacheShare':usage['cachedInputTokens']/usage['inputTokens'] if usage['inputTokens'] else None,
            'knownUsageCostUsd':usage['usageBasedUsd']+usage['additionalCacheWritePremiumUsd'],
            'usage':public_usage(usage)})
        private[variant] = rows
    return records, private


def changes(before, after):
    keys = ('wallSeconds','firstSummarySeconds','knownUsageCostUsd')
    values = {key:(before.get(key),after.get(key)) for key in keys}
    for key in ('inputTokens','outputTokens','totalTokens','requests','normalizedNoCacheUsd'):
        values[key] = before['usage'].get(key),after['usage'].get(key)
    return {key:{'before':b,'after':a,'reductionPercent':(b-a)/b*100,
                  'afterOverBefore':a/b,'beforeOverAfter':b/a if a else None}
            for key,(b,a) in values.items() if isinstance(b,(int,float)) and isinstance(a,(int,float)) and b}


def payload_comparison(left, right, *, batch_transport=False):
    if batch_transport or any(len(row.get('unitIds') or [])>1
            for row in left+right if row.get('kind')=='region_study'):
        return {'applicable':False,'established':False,
            'reason':'배치 요청은 여러 원래 unit을 한 payload로 포장해요. 개별 payload hash의 일대일 비교는 성립하지 않아요.',
            'scope':'같은 원본·계획과 원래 unit ID coverage 동등성을 별도로 확인해요. 생성 본문 품질은 별도예요.'}
    def index(rows):
        result = {}
        for row in rows:
            if row.get('kind') != 'region_study' or row.get('state') == 'not_sent':
                continue
            key = tuple(row.get('unitIds') or [])
            if not key or key in result:
                return None
            result[key] = row.get('payloadHash')
        return result
    a,b = index(left),index(right)
    if a is None or b is None:
        return {'established':False,'reason':'요청과 unit의 일대일 연결을 확인할 수 없어요.'}
    shared = set(a)&set(b)
    return {'applicable':True,'established':bool(a) and set(a)==set(b)
            and all(isinstance(a[k],str) and bool(a[k]) and a[k]==b[k] for k in shared),
        'leftStudyRequests':len(a),'rightStudyRequests':len(b),'sharedUnits':len(shared),
        'identicalFullPayloadHashes':sum(a[k]==b[k] for k in shared),
        'scope':'system/user text + image base64 + response schema의 hash예요. 생성 본문을 입력으로 쓰는 전체 개요 호출은 제외해요.'}


def pair_runs(records, private, left, right):
    index = {row['variant']:row for row in records}
    if left not in index or right not in index:
        return None
    a,b = index[left],index[right]
    same_source = bool(a['sourceSha256']) and a['sourceSha256']==b['sourceSha256']
    same_plan = bool(a['planSha256']) and a['planSha256']==b['planSha256']
    reasons = []
    if not same_source or not same_plan:reasons.append('같은 원본·고정 묶음이 아니에요.')
    if not a['fullRunEligible'] or not b['fullRunEligible']:reasons.append('진행 중·표본(페이지/unit)·실패·미완료 실행은 전체 문서 비교에서 제외해요.')
    ca,cb = a['unitIdCoverage'],b['unitIdCoverage']
    same_units = (ca['submittedUniqueUnits']>0 and ca['submittedUniqueUnits']==cb['submittedUniqueUnits']
                  and ca['submittedUnitIdsSha256']==cb['submittedUnitIdsSha256'])
    clean = all(not row['malformedUnitIds'] and not row['duplicateSubmittedUnits'] and not row['malformedManifest']
        and row['settledUniqueUnits']==row['submittedUniqueUnits'] and row['plannedUnitCoverageComplete'] is not False
        for row in (ca,cb))
    equivalent_scope = same_source and same_plan and same_units and clean
    if not same_units or not clean:reasons.append('원래 unit ID의 동일한 전체 처리 범위를 확인하지 못했어요.')
    canonical = {'established':equivalent_scope,'sameCanonicalSourceSha256':same_source,
        'sameFrozenPlanSha256':same_plan,'sameSubmittedUnitIds':same_units,
        'leftUnitCount':ca['submittedUniqueUnits'],'rightUnitCount':cb['submittedUniqueUnits'],
        'leftPlannedCoverage':ca['plannedUnitCoverageComplete'],'rightPlannedCoverage':cb['plannedUnitCoverageComplete'],
        'allSubmittedUnitsSettledAndUnique':clean,'qualityEquivalent':False,
        'scope':'원본/계획 hash와 원래 unit ID의 제출·settled 범위만 비교해요. 원문 출처별 설명 완전성·정확성·본문 품질의 동등성은 증명하지 않아요.'}
    is_batch = any(type(row.get('batchUnits')) is int and row['batchUnits']>1 for row in (a,b))
    payload = payload_comparison(private[left],private[right],batch_transport=is_batch)
    notes = ['한 번씩 순차 실행했어요. 새 AI 응답·서버 지연과 cache 상태가 달라 병렬도만의 인과 효과를 보장하지 않아요.',QUALITY_NOTE]
    if a['cacheShare'] is not None and b['cacheShare'] is not None and abs(a['cacheShare']-b['cacheShare'])>.1:
        notes.append('입력 cache 적중률 차이가 커요. 실제 추정비용과 cache 미적용 비교비용을 함께 봐야 해요.')
    if b['aliases']:
        notes.append('출처 ID 별칭/고정 enum은 의도된 wire 차이예요. full payload hash의 차이를 원문 삭제로 단정하거나, alias 역치환 검증 없이 원문 동등이라고 단정하지 않아요.')
    if b['compactPrompt'] or b['compactTableSetup']:
        notes.append('지시문/관찰 형식도 축약한 후보예요. 입력 원본이 같다는 사실과 모델에 준 계약·출력 품질이 같다는 주장은 구분해요.')
    if is_batch:notes.append('배치는 여러 unit을 한 요청에 포장하는 설정이에요. unit 범위 동등성과 생성 본문 품질은 별도로 판단해요.')
    if a['batchAliases'] or b['batchAliases']:
        notes.append('배치 출처 별칭은 paid wire 응답을 canonical ID로 복원해요. 원래 unit ID coverage 비교는 그대로지만, 별칭 복원이나 source 범위 일치가 본문 품질을 보장하지 않아요.')
        if a['batchAliasPool']!=b['batchAliasPool']:
            notes.append('배치 별칭 schema 방식도 달라요. exact enum·고정 pool·namespace pattern의 출력 행동과 cache 적중은 별도로 관측해야 해요.')
    if a['sourceCoverageHint']!=b['sourceCoverageHint']:
        notes.append('원문 보존 hint 설정이 다르거나 한쪽 기록이 없어요. 같은 원본·unit 범위여도 입력 지시문 동일성을 확정하지 않으며, 순수한 alias/schema 효과로 해석하지 않아요.')
    if a['studyInputApi']!=b['studyInputApi']:
        notes.append('입력 API 경로도 달라요(chat/responses). 요청 형식·cache·사용량 응답 차이가 있으므로 배치나 별칭만의 효과로 해석하지 않아요.')
    if a['statementUncertainty']!=b['statementUncertainty']:
        notes.append('문장별 불확실성 보고 설정도 달라요. 운송 포장만 바뀐 실험으로 해석하지 않아요.')
    elif a['statementUncertainty']:
        notes.append('양쪽 모두 문장별 불확실성 보고를 사용해요. 읽을 수 있는 본문과 판독 불확실성은 품질 감사에서 별도로 확인해야 해요.')
    notes.append('최장 전체 요청 지연과 관측 동시 요청 수를 함께 표시해요. latency에 포함된 admission 대기를 송신 시각 뒤에 다시 더하지 않아요. pending/시각 누락 요청은 동시 구간을 추측하지 않으며, 관측 peak는 서버 내부 동시성 증명이 아니에요.')
    return {'beforeVariant':left,'afterVariant':right,'sameSource':same_source,'samePlan':same_plan,
        'fullDocumentComparisonEligible':not reasons,'exclusionReasons':reasons,
        'qualityEquivalent':False,'fullPayloadHashComparison':payload,
        'canonicalSourcePlanUnitCoverageComparison':canonical,
        'requestTimingComparison':{'before':a['requestTiming'],'after':b['requestTiming']},
        'inputContractSettings':{'before':{key:a[key] for key in ('batchAliases','batchAliasPool','sourceCoverageHint','studyInputApi','statementUncertainty')},
            'after':{key:b[key] for key in ('batchAliases','batchAliasPool','sourceCoverageHint','studyInputApi','statementUncertainty')}},
        'changes':changes(a,b) if not reasons else {},'notes':notes}


def historic_143(forensic):
    if not forensic:return None
    old = (forensic.get('historicalComparison') or {}).get('actualPreviousCompletedRuns') or []
    old = next((row for row in reversed(old) if str(row.get('generationStartedKst','')).startswith('2026-10-17')),None)
    if not old:return None
    account=forensic['accounting'];timeline=forensic['timeline'];current=account['displayedSummaryOperation']
    def side(label,usage,metrics):
        return {'label':label,'engineSeconds':metrics.get('elapsedSeconds'),
            'firstSummaryEngineSeconds':metrics.get('firstResultSeconds'),
            'costUsd':usage.get('usageBasedUsd'),'inputTokens':usage.get('inputTokens'),
            'outputTokens':usage.get('outputTokens'),'totalTokens':usage.get('totalTokens'),
            'calls':usage.get('requests'),'cachedInputTokens':usage.get('cachedInputTokens'),
            'studyJobs':metrics.get('studyJobs'),'workers':metrics.get('workers')}
    before=side('10월17일 실제 생성',old['summaryLedgerUsage'],old['metrics'])
    after=side('스크린샷의 현재 생성',current,timeline['engineMetrics'])
    return {'pages':forensic['identity']['physicalPages'],'summaryScope':{'before':before,'after':after},
        'separatePlanning':{'beforeObserved':old['additionalSeparatePlanningUsage'],
            'after':account['preplanningOperation'],
            'beforeKnownChain':old['observedLedgerChainUsage'],
            'afterKnownChain':account['freshPlanningAndSummaryCombined']},
        'currentChainWallSeconds':timeline['planningOperationThroughResultWallSeconds'],
        'currentGenerationInvocationWallSeconds':timeline['summaryInvocationThroughResultWallSeconds'],
        'earlierFailedPlanningCostUsd':account['separateEarlierFailedPlanningToday']['usageBasedUsd'],
        'sourceQualityEquivalent':False,
        'notes':['스크린샷 $0.158581은 생성 작업만의 금액이에요. 별도 묶음 판단을 포함하면 약$0.173769예요.',
            '10월17일과 현재는 fresh 묶음·job수·제외범위가 달라 통제 실험이 아니에요.',
            '과거에는 별도 planning 새 호출1개만 관측돼요. 나머지 과거 cache 생성비를 복원한 총비용이 아니므로, 두 chain 합계를 완전한 총비용 대조로 단정하지 않아요.',
            '화면의 약2분51초는 별도 planning부터 결과 저장까지 약169.9초와 맞아요. 생성 엔진140.3초에 planning 시간이 포함돼 있다고 읽으면 안 돼요.',
            '오늘 새 실행처럼 보였던 이전 결과 하나는 10월17일 결과의 cache 표시였어요. 새 유료 완료실험으로 세지 않아요.',
            '이 역사 수치는 원장의 기존 추정금액이에요. 새 비용 상한과 합산하지 않고 과거 원장을 소급 변경하지 않아요.']}


def historic_six(history):
    if not history:return None
    result=[]
    for pair in history['pairs']:
        def summary(row):
            keys=('variant','title','pages','wallSeconds','firstSummaryPublishedSeconds',
                'actualWithKnownCacheWriteUsd','normalizedNoCacheUsd','inputTokens','outputTokens',
                'totalTokens','requestCount','cachedInputTokens','unknownReservedUsd',
                'processingComplete','coverageComplete','maxRequestLatencySeconds')
            return {key:row.get(key) for key in keys}
        result.append({'case':pair['case'],'before':summary(pair['before']),'after':summary(pair['after']),
            'comparisonEligible':pair['completedSamePdfDescriptiveComparisonEligible'],
            'sourceBlocksEqual':pair['sourceBlocksEqualExceptPlanAnnotations'],
            'qualityEquivalent':False,'flags':pair['flags']})
    aggregates={k:v for k,v in history['aggregates'].items() if k!='allSixRawIncludesIncomplete'}
    v3=history['refillV3SingleFrozenCase']
    return {'pairs':result,'aggregates':aggregates,'refillV3':{
        key:v3[key] for key in ('freshSixPdfRemeasuredAfterV3','actualFrozenWallSeconds',
            'modeledEquivalentOriginalPlanningWallSeconds','postGroupingReductionPercent',
            'generationBillingExcludingPlanner','limits')},
        'note':'최종 fresh6건은 v2 측정이에요. v3 즉시 재투입은 고정 묶음 인상주의1건만 다시 측정했어요. 적분 최종 HTTP503 실패를 빠른 성공으로 합산하지 않아요. 금융 기준 최대 응답은 원장124.723초예요.'}


def build(root=DEFAULT_ROOT):
    root=Path(root);records,private=collect_runs(root)
    budget=budget_summary(root,records)
    pairs=[];seen=set()
    def append_pair(left,right):
        if (left,right) in seen:return
        value=pair_runs(records,private,left,right)
        if value:
            pairs.append(value);seen.add((left,right))
    for left,right in [('same-plan-8','same-plan-14'),('same-plan-14','alias32'),
                       ('same-plan-8','alias32'),('anatomy-control','anatomy-alias32'),
                       ('pair-exact-full','pair-namespace-full'),
                       ('pair-namespace-full','responses-full'),
                       ('same-plan-8','responses-full'),('pair-exact-full','responses-full')]:
        append_pair(left,right)
    def control_rank(row):
        name=Path(row['variant']).name
        return (name!='same-plan-14',not (name=='control' or name.endswith('-control')),
                bool(row['sampleOnly']),not row['fullRunEligible'],
                bool(row['compactPrompt'])+bool(row['compactTableSetup'])+bool(row['aliases'])+
                    bool(row['batchAliases'])+bool(row['statementUncertainty']),
                row['batchUnits'] if type(row['batchUnits']) is int else math.inf,row['variant'])
    for row in records:
        if not row['sourceSha256'] or not row['planSha256']:continue
        compatible=[candidate for candidate in records if candidate['sourceSha256']==row['sourceSha256']
                    and candidate['planSha256']==row['planSha256']]
        baseline=min(compatible,key=control_rank)
        if baseline['variant']!=row['variant']:
            append_pair(baseline['variant'],row['variant'])
    decision=read(root/'decision.json',{'status':'pending','note':'최종 채택은 아직 결정하지 않았어요.'})
    return {'schemaVersion':2,'generatedAtUtc':datetime.now(timezone.utc).isoformat(),
        'additionalApiRequests':0,'qualityEquivalent':False,'qualityNote':QUALITY_NOTE,
        'decision':decision,'budget':budget,'runs':records,'samePlanComparisons':pairs,
        'historical143':historic_143(read(root/'document11-forensics.json')),
        'historicalSix':historic_six(read(root/'historical-comparison.json')),
        'notes':['새 실험은 같은 확인된 묶음을 재사용해 새 유료 planning을 측정하지 않아요. 최초 업로드부터의 전체시간과 직접 비교하지 않아요.',
            'cachedInputTokens는 전체 inputTokens의 일부예요. 입력+출력 토큰 합계에 cached토큰을 다시 더하지 않아요.',
            'cache 미적용 비용은 입력$0.10/M·출력$0.50/M의 비교지표예요. 실제 추정비용과 달라요.',
            '새 alias32의 cache 성공을 가정하지 않아요. 관측한 적중률과 input/output·응답 실패를 그대로 표시해요.',
            '페이지/unit 표본·실패·진행 중 실행은 표에는 남기되 전체 문서 성능·비용 비교에서 제외해요.',
            '배치의 요청 payload hash는 원래 개별 unit payload와 일대일 대응하지 않아요. 동일 원본·계획·unit ID coverage와 설명 품질은 각각 구분해요.'],
        'evidence':[{'path':name,'exists':(root/name).exists()} for name in (
            'document11-forensics.json','historical-comparison.json','pricing-regression.json',
            'cjk-prose-image-potential.json')]}


def fmt(value, digits=1):
    return '—' if value is None else f'{value:,.{digits}f}'


def money(value):return '—' if value is None else f'${value:.6f}'
def integer(value):return '—' if value is None else f'{int(value):,}'
def percent(value):return '—' if value is None else f'{value*100:.1f}%'


def setting(value):
    if value is None:return '—'
    if type(value) is bool:return '켜짐' if value else '꺼짐'
    return escape(str(value))


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def decision_text(value):
    """Display external decision metadata without interpreting it as a quality proof."""
    if isinstance(value,dict):
        return ' · '.join(str(key)+': '+decision_text(item) for key,item in value.items())
    if isinstance(value,list):return ' / '.join(decision_text(item) for item in value)
    if value is None:return '—'
    if type(value) is bool:return 'true' if value else 'false'
    return str(value)


def render_decision(decision):
    pieces=['<section><h2>최종 채택</h2><p class="pending">'+escape(str(decision.get('status','pending')))+'</p><p>'+
            escape(str(decision.get('note','최종 채택은 아직 결정하지 않았어요.')))+'</p>']
    for key,label in [('selectedProfile','선택한 프로필'),('measuredResults','측정 결과'),
                      ('qualityCaveats','품질 확인 범위와 한계')]:
        value=decision.get(key)
        if value is None or value==[] or value=={} or value=='':continue
        pieces.append('<p><strong>'+label+'</strong></p>')
        if isinstance(value,list):
            pieces.append('<ul>'+''.join('<li>'+escape(decision_text(item))+'</li>' for item in value)+'</ul>')
        else:pieces.append('<p>'+escape(decision_text(value))+'</p>')
    pieces.append('</section>')
    return ''.join(pieces)


def render(report):
    pieces=['<header><span class="eyebrow">SYNESIS · PDF 분석 실험</span><h1>시간과 비용을 함께 비교해요</h1><p>실제 원장과 저장된 실행에서 다시 계산했어요. 결과는 단일 실행이며 캐시·미완료·측정 범위를 함께 표시해요.</p></header>',
        '<aside class="warning"><strong>품질 유지 성공으로 판정하지 않았어요.</strong> '+escape(report['qualityNote'])+'</aside>']
    b=report['budget']
    pieces.append('<section><h2>현재 승인 창의 비용 상한</h2><div class="cards">'+''.join(
        '<article><small>'+label+'</small><b>'+value+'</b></article>' for label,value in [
        ('새 승인 상한',money(b['approvedCapUsd'])),('확인된 사용량 기준 비용',money(b['actualKnownUsd'])),
        ('미확정·누락 상한 포함 예약',money(b['committedUsd'])),('남은 보수 여유',money(b['remainingToCapUsd']))])+'</div><p>'+escape(b['note'])+'</p>')
    pieces.append('<p class="muted">cache-write 확인 요금 '+money(b['knownCacheWritePremiumUsd'])+' · 등록된 미확정 요청 '+integer(b['registeredUnresolvedRequestCount'])+'개 / 안전예약 '+money(b['conservativeUnknownReservedUsd'])+' · write 필드 미관측 상한 '+money(b['missingCacheWriteUpperBoundUsd'])+'</p></section>')
    if b.get('previousWindow'):
        previous=b['previousWindow'];cumulative=b['cumulativeAllRunLedgers']
        pieces.append('<section><h2>승인 창을 나누어 집계해요</h2>'+table(
            ['집계 범위','승인 상한','요청수','확인된 사용량 비용','보수 예약 포함'],[
                ['이전 승인 · 새 승인 당시 고정 checkpoint',money(previous['approvedCapUsd']),
                 integer(previous['checkpointRequestCount']),money(previous['actualKnownUsdAtApproval']),money(previous['committedUsdAtApproval'])],
                ['신규 승인 · 현재 activeWindow',money(b['approvedCapUsd']),integer(b['registeredRequestCount']),
                 money(b['actualKnownUsd']),money(b['committedUsd'])],
                ['모든 run 원장 누적 · 한도 차감용 합계 아님','—',integer(cumulative['requests']),
                 money(cumulative['actualKnownUsd']),money(cumulative['committedUsd'])]])+
            '<p>'+escape(previous['scope'])+'</p><p class="muted">승인 경계는 approved-window.json의 request ID checkpoint예요. '
            '이전 금액을 신규 한도에서 이중 차감하지 않아요. 실행 여유 '+money(b['remainingToExecutionCapUsd'])+'</p></section>')
    pieces.append('<section><h2>같은 묶음으로 다시 생성한 실험</h2><p>새 planning 없이 생성만 측정했어요. 같은 원본·묶음이어도 원격 응답과 캐시 적중이 달라요.</p>')
    rows=[]
    for row in report['runs']:
        u=row['usage'];label=escape(row['variant'])
        if row['partialPageProbe']:label+=' <span class="badge">일부 페이지</span>'
        elif row['partialUnitProbe']:label+=' <span class="badge">일부 unit</span>'
        elif row['sampleOnly']:label+=' <span class="badge">표본</span>'
        rows.append([label,escape(row['status']),integer(row['physicalPages']),fmt(row['wallSeconds']),fmt(row['firstSummarySeconds']),money(row['knownUsageCostUsd']),money(u['normalizedNoCacheUsd']),
            integer(u['totalTokens']),integer(u['inputTokens'])+' / '+integer(u['outputTokens']),integer(u['requests']),
            integer(row['batchUnits']),integer(row['batchImages']),integer(row['batchSubmissions']),
            setting(row['balancedBatches']),setting(row['batchAliases']),setting(row['batchAliasPool']),
            setting(row['sourceCoverageHint']),setting(row['studyInputApi']),setting(row['statementUncertainty']),
            fmt(row['maxRequestSeconds']),fmt(row['maxNetworkRequestSeconds']),fmt(row['maxQueueSeconds']),integer(row['peakActiveRequest']),
            percent(row['cacheShare']),integer(u['unknownUsageRequests'])])
    pieces.append(table(['실행','상태','전체쪽','생성 초','첫 요약 초','추정 비용','cache 미적용 비용','총 토큰','입력 / 출력 토큰',
                        '호출','unit/요청 한도','이미지/요청 한도','study 제출','균형 포장','배치 별칭','별칭 schema',
                        '원문 보존 hint','입력 API','문장별 불확실성',
                        '최장 요청 초(대기 포함)','최장 네트워크 초','최장 admission 대기 초','관측 동시 요청','입력cache','미확정'],rows))
    pieces.append('<p class="muted">모든 실행의 품질 동등: 미확인. 전체쪽은 원본 길이이며 표본 실험의 처리량이 아니에요. '
                  'batchUnits·batchImages는 요청당 최대 포장 크기이고 study 제출수는 원래 unit 수와 달라요. 비용은 각 run 원장의 cache-write 보정 포함 추정치예요.</p>')
    pieces.append('<p class="muted">배치 별칭은 canonical 출처 ID로 복원한 뒤 unit 범위를 비교해요. 복원 성공은 본문 품질 보장이 아니에요. '
        'hint·별칭 schema·입력 API 설정 차이를 함께 표시해요. 예전 run에 없던 hint/schema 메타데이터는 —로 남겨요. '
        '관측 동시 요청은 송신부터 응답까지의 구간 추정이며 not_sent는 제외해요. 진행 중/시각 누락 호출이 있으면 peak는 하한이에요.</p>')
    pieces.append('<p class="muted">latencySeconds에는 API slot 진입 전 대기가 포함돼요. 동시 구간에는 encode/header/body 실측을 우선 쓰고, '
        '실측이 없으면 queueSeconds를 뺀 지연을 사용해 대기를 이중 계산하지 않아요. 큐 기록 없는 과거 요청은 별도 fallback으로 남겨요.</p>')
    for pair in report['samePlanComparisons']:
        c=pair['changes'];title=escape(pair['beforeVariant']+' → '+pair['afterVariant'])
        pieces.append('<details><summary>'+title+(' · 전체 범위 대조' if pair['fullDocumentComparisonEligible'] else ' · 전체 비교 제외')+'</summary>')
        values=[]
        for key,label in [('wallSeconds','시간'),('firstSummarySeconds','첫 요약'),('knownUsageCostUsd','관측 비용'),('normalizedNoCacheUsd','cache 미적용 비용'),('inputTokens','입력'),('outputTokens','출력'),('requests','호출')]:
            if key in c:
                change=c[key];reduction=change['reductionPercent']
                values.append([label,fmt(abs(reduction))+'% '+('감소' if reduction>=0 else '증가'),fmt(change['beforeOverAfter'],2)+'배'])
        pieces.append(table(['지표','이전 대비 감소율','이전 / 이후'],values))
        payload=pair['fullPayloadHashComparison']
        proof=pair['canonicalSourcePlanUnitCoverageComparison']
        pieces.append('<p>동일 원본 '+('확인' if pair['sameSource'] else '미확인')+' · 동일 묶음 '+('확인' if pair['samePlan'] else '미확인')+
            ' · 원래 unit ID 범위 '+('동등 확인' if proof['established'] else '동등 미확인')+
            ' ('+integer(proof['leftUnitCount'])+' / '+integer(proof['rightUnitCount'])+'개)</p><p class="muted">'+escape(proof['scope'])+'</p>')
        if payload.get('applicable') is False:
            pieces.append('<p>개별 payload hash 비교: 해당 없음. '+escape(payload['reason'])+'</p>')
        else:
            pieces.append('<p>동일 full payload '+integer(payload.get('identicalFullPayloadHashes'))+'/'+integer(payload.get('sharedUnits'))+'개</p>')
        timing=pair['requestTimingComparison'];before=timing['before'];after=timing['after']
        pieces.append('<p>최장 요청(대기 포함) '+fmt(before['maxRequestSeconds'])+' → '+fmt(after['maxRequestSeconds'])+
            '초 · 네트워크 '+fmt(before['maxNetworkRequestSeconds'])+' → '+fmt(after['maxNetworkRequestSeconds'])+
            '초 · 관측 동시 요청 '+integer(before['peakActiveRequest'])+' → '+integer(after['peakActiveRequest'])+
            ' · 전체 원장 요청 '+integer(before['totalRequests'])+' → '+integer(after['totalRequests'])+'개</p>')
        pieces.append('<ul>'+''.join('<li>'+escape(n)+'</li>' for n in pair['exclusionReasons']+pair['notes'])+'</ul></details>')
    pieces.append('</section>')
    h=report['historical143']
    if h:
        pieces.append('<section><h2>143쪽 자료 · 10월17일과 스크린샷 실행</h2><p>생성 작업만의 수치와 별도 묶음 판단 비용을 나누어 봐요.</p>')
        rows=[]
        for row in h['summaryScope'].values():rows.append([escape(row['label']),fmt(row['engineSeconds']),fmt(row['firstSummaryEngineSeconds']),money(row['costUsd']),integer(row['totalTokens']),integer(row['inputTokens'])+' / '+integer(row['outputTokens']),integer(row['calls']),integer(row['studyJobs'])])
        pieces.append(table(['생성 작업 범위','엔진 초','첫 결과 초','기존 원장 비용','총 토큰','입력 / 출력 토큰','호출','작업수'],rows))
        p=h['separatePlanning'];rows=[]
        for label,key in [('10월17일 관측 planning','beforeObserved'),('현재 별도 planning','after'),('10월17일 관측 chain','beforeKnownChain'),('현재 planning + 생성','afterKnownChain')]:
            u=p[key];rows.append([label,money(u['usageBasedUsd']),integer(u['inputTokens'])+' / '+integer(u['outputTokens']),integer(u['requests'])])
        pieces.append(table(['별도 집계','기존 원장 비용','입력 / 출력 토큰','호출'],rows))
        pieces.append('<ul>'+''.join('<li>'+escape(n)+'</li>' for n in h['notes'])+'</ul></section>')
    h=report['historicalSix']
    if h:
        pieces.append('<section><h2>앞선 6개 PDF 실험의 전체 기록</h2><p>'+escape(h['note'])+'</p>')
        rows=[]
        for pair in h['pairs']:
            a,b=pair['before'],pair['after'];label=escape(a['title'])
            state='완료 수치 대조' if pair['comparisonEligible'] else '최종 실패 · 집계 제외'
            if not pair['sourceBlocksEqual']:state+=' · 추출입력 변경'
            cache=lambda row: percent(row['cachedInputTokens']/row['inputTokens']) if row['inputTokens'] else '—'
            rows.append([label,escape(state),fmt(a['wallSeconds'])+' → '+fmt(b['wallSeconds']),fmt(a['firstSummaryPublishedSeconds'])+' → '+fmt(b['firstSummaryPublishedSeconds']),money(a['actualWithKnownCacheWriteUsd'])+' → '+money(b['actualWithKnownCacheWriteUsd']),money(a['normalizedNoCacheUsd'])+' → '+money(b['normalizedNoCacheUsd']),integer(a['totalTokens'])+' → '+integer(b['totalTokens']),integer(a['inputTokens'])+' / '+integer(a['outputTokens'])+' → '+integer(b['inputTokens'])+' / '+integer(b['outputTokens']),integer(a['requestCount'])+' → '+integer(b['requestCount']),cache(a)+' → '+cache(b),money(b['unknownReservedUsd'])])
        pieces.append(table(['PDF','비교 상태','전체 초','첫 요약 초','비용','cache 미적용 비용','총 토큰','입력 / 출력 토큰','호출','입력cache','최종 미확정예약'],rows))
        for key in ('completedSamePdfFive','identicalExtractedSourceWithoutFinanceOutlierThree'):
            value=h['aggregates'].get(key)
            if value:
                a,b=value['before'],value['after'];pieces.append('<p><strong>'+escape(value['label'])+'</strong>: '+fmt(a['wallSeconds'])+' → '+fmt(b['wallSeconds'])+'초 · 첫 요약 평균 '+fmt(a['meanFirstSummarySeconds'])+' → '+fmt(b['meanFirstSummarySeconds'])+'초. 품질 동등이나 순수 병렬효과의 증명은 아니에요.</p>')
        v=h['refillV3'];pieces.append('<details><summary>마지막 v3 보충 스케줄러는 인상주의 1건만 재측정했어요</summary><p>고정 묶음 실측 '+fmt(v['actualFrozenWallSeconds'])+'초 · 원래 planning을 더한 참고 계산 '+fmt(v['modeledEquivalentOriginalPlanningWallSeconds'])+'초. 새 planning을 포함한 6문서 실측으로 사용하지 않아요.</p><ul>'+''.join('<li>'+escape(n)+'</li>' for n in v['limits'])+'</ul></details></section>')
    pieces.append(render_decision(report['decision']))
    pieces.append('<section><h2>해석과 근거</h2><ul>'+''.join('<li>'+escape(n)+'</li>' for n in report['notes'])+'</ul><p>'+''.join('<a href="'+escape(item['path'],quote=True)+'">'+escape(item['path'])+'</a> ' for item in report['evidence'] if item['exists'])+'</p></section>')
    pieces.append('<footer>원장·원문은 읽기 전용으로 사용했어요. 보고서 생성으로 API를 호출하지 않아요. 갱신 '+escape(report['generatedAtUtc'])+'</footer>')
    css='''*{box-sizing:border-box}body{margin:0;background:#f4f7fc;color:#182b46;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1460px;margin:auto;padding:42px 30px}header{padding:24px 0 18px}h1{font-size:34px;line-height:1.25;margin:12px 0}h2{font-size:21px;margin:0 0 12px}.eyebrow{font-size:12px;letter-spacing:.12em;color:#637a99}section{background:white;border:1px solid #dbe4f1;border-radius:18px;padding:26px;margin:22px 0}.warning{border-left:4px solid #c37c31;background:#fff7eb;border-radius:8px;padding:16px 20px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.cards article{background:#f2f6fc;border-radius:12px;padding:16px}.cards small{display:block;color:#5b708d}.cards b{display:block;font-size:23px;margin-top:8px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap;margin:12px 0}th{text-align:left;background:#eef3fa;color:#526b8c;font-size:12px}th,td{padding:12px 13px;border-bottom:1px solid #e3eaf4}tbody tr:hover{background:#f7faff}.muted,footer{color:#637893;font-size:13px}.badge{font-size:11px;background:#fff1d8;color:#9b6419;padding:3px 7px;border-radius:6px}details{border-top:1px solid #e1e8f2;padding:14px 0}summary{cursor:pointer;font-weight:600}a{color:#245699;word-break:break-all;margin-right:12px}.pending{display:inline-block;background:#edf2f9;padding:4px 12px;border-radius:7px}footer{padding:8px 0 30px}li{margin:6px 0}@media(max-width:800px){main{padding:20px 14px}.cards{grid-template-columns:repeat(2,1fr)}section{padding:18px}h1{font-size:27px}}'''
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SYNESIS PDF 시간·비용 비교</title><style>'+css+'</style><main>'+''.join(pieces)+'</main></html>'


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    args=parser.parse_args();report=build(args.root);args.root.mkdir(parents=True,exist_ok=True)
    (args.root/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.root/'report.html').write_text(render(report),encoding='utf-8')
    print(json.dumps({'runs':len(report['runs']),'committedUsd':report['budget']['committedUsd'],'decision':report['decision'].get('status'),'additionalApiRequests':0}))


if __name__=='__main__':main()
