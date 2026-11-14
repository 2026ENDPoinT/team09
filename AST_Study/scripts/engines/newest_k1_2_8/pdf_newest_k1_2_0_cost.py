"""Local-only workload estimates for ver.99. Never an API budget or billing guarantee."""
from __future__ import annotations
import json
import math
import statistics
from pathlib import Path

VERSION = 'newest-k1-2-8-workload-estimate-standard-v3'


def read(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def features(document, pages):
    selected = [document.get('pages', [])[p-1] for p in pages
                if isinstance(p, int) and 1 <= p <= len(document.get('pages', []))]
    chars = sum(len(str(p.get('nativeText') or p.get('markdown') or '')) for p in selected)
    count = max(1, len(selected))
    sparse = sum(len(str(p.get('nativeText') or p.get('markdown') or '')) < 80 for p in selected)
    return {'pages': len(selected), 'charsPerPage': chars/count, 'sparseFraction': sparse/count}


def samples(root, model, prompt_version, exclude_document=None):
    """Reuse derived history; recheck file revisions on every call, including new runs."""
    from pdf_local_preparation_cache import history_sample
    source_files=sorted(Path(__file__).parent.glob('*.py'))
    found=[]
    for folder in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        if not folder.is_dir() or folder.name == exclude_document:continue
        paths=[folder/'document.json']
        for result in sorted(folder.glob('generated/newest-k1-2-8/*/result.json')):
            paths.extend(result.parent/name for name in
                         ('result.json','planning-usage.json','blocks.json','manifest.json'))
        value=history_sample(folder,model,prompt_version,paths+source_files,
            lambda:_uncached_samples(root,model,prompt_version,_folders=[folder]))
        found.extend(value)
    return found


def _uncached_samples(root, model, prompt_version, exclude_document=None, *, _folders=None):
    """One latest eligible run per document; reject resumed, unknown, empty and legacy runs."""
    found = []
    for folder in (_folders if _folders is not None else sorted(Path(root).iterdir()) if Path(root).is_dir() else []):
        if not folder.is_dir() or folder.name == exclude_document:
            continue
        document = read(folder/'document.json')
        if not document:
            continue
        candidates = []
        for path in folder.glob('generated/newest-k1-2-8/*/result.json'):
            result = read(path)
            if not result or result.get('strategy') != 'newest-k1-2-8':
                continue
            if result.get('model') != model or result.get('promptVersion') != prompt_version:
                continue
            if (not result.get('processingComplete') or result.get('cacheHit')
                    or not result.get('sections') or not result.get('concepts')
                    or result.get('scope') != 'document'):
                continue
            usage = result.get('runUsage') or {}
            kinds = usage.get('byKind') or {}
            # Two-stage imports settle planning in an earlier invocation. Join its
            # exact-identity usage for cold-start historical calibration only.
            if not (kinds.get('region_plan') or {}).get('requests'):
                separate = read(path.parent/'planning-usage.json')
                if separate:
                    usage = {**usage, 'byKind':{**kinds, 'region_plan':(separate.get('byKind') or {}).get('region_plan',{})},
                             'usageBasedUsd':usage.get('usageBasedUsd',0)+separate.get('usageBasedUsd',0),
                             'unknownUsageRequests':usage.get('unknownUsageRequests',0)+separate.get('unknownUsageRequests',0),
                             'inputTokens':usage.get('inputTokens',0)+separate.get('inputTokens',0),
                             'outputTokens':usage.get('outputTokens',0)+separate.get('outputTokens',0)}
                    kinds = usage['byKind']
            planning = kinds.get('region_plan') or {}
            study = kinds.get('region_study') or {}
            metrics = result.get('metrics') or {}
            # Old Flex measurements cannot calibrate new Standard prices.
            if metrics.get('processingTierProfile')!='standard-v1':continue
            # newStudyJobs excludes skipped local blocks. Fewer paid jobs means response reuse.
            if (usage.get('unknownUsageRequests', 0) or planning.get('requests', 0) <= 0
                    or study.get('requests', 0) <= 0
                    or study.get('requests') != metrics.get('newStudyJobs')):
                continue
            cost = usage.get('usageBasedUsd', 0)
            if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0:
                continue
            pages = result.get('sourcePages') or list(range(1, len(document.get('pages', []))+1))
            f = features(document, pages)
            if not f['pages']:
                continue
            blocks = None
            try:
                blocks = json.loads((path.parent/'blocks.json').read_text(encoding='utf-8'))
                measured_work = workload(document, pages, blocks=blocks)
            except (OSError, ValueError, KeyError, TypeError):
                measured_work = workload(document, pages)
            planned_work = None
            manifest = read(path.parent/'manifest.json')
            if manifest and isinstance(manifest.get('jobs'),list):
                try:
                    planned_work = workload(document,pages,blocks=blocks,jobs=manifest['jobs'])
                except (ValueError, KeyError, TypeError):
                    pass
            candidates.append((path.stat().st_mtime_ns, {
                **f, 'workload':measured_work, 'plannedWorkload':planned_work, 'stageUsage':kinds, 'documentId': document.get('documentId', folder.name), 'usd': cost,
                'inputTokens': usage.get('inputTokens', 0), 'outputTokens': usage.get('outputTokens', 0),
                'planUsd': planning.get('usageBasedUsd', 0),
                'studyUsd': study.get('usageBasedUsd', 0),
                'outlineUsd': (kinds.get('summary_reduce') or {}).get('usageBasedUsd', 0),
            }))
        if candidates:
            found.append(max(candidates, key=lambda pair: pair[0])[1])
    return found


def text_tokens(value):
    """Local sizing proxy, not a tokenizer or a provider usage claim."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return sum(.28 if ord(c) < 128 else 1.25 for c in text)


def workload(document, targets, blocks=None, jobs=None):
    """Size the real local fragments/crop geometry without rendering or remote calls.

    Before the paid semantic plan exists, page-local grouping is a disclosed proxy.
    Use the same proxy for historical calibration, never the historical result prose.
    """
    from pdf_newest_k1_2_0 import (
        local_groups, jobs_for, planning_fragment, teaching_payload, plain_cover_ids,
        PLAN_PROMPT, PLAN_FORMAT, STUDY_PROMPT, STUDY_FORMAT, entry_label)
    from pdf_new_concept_v02_regions import crop_runs
    from pdf_study_policy import document_context
    from pdf_page_analysis import MAX_SIDE
    from pdf_newest_k1_2_0_prompts import OVERVIEW_PROMPT as OUTLINE_PROMPT
    from pdf_outline import FORMAT as OUTLINE_FORMAT
    known_jobs = jobs is not None
    pages = document.get('pages', [])
    selected = sorted(set(p for p in targets if 1 <= p <= len(pages)))
    if blocks is None:
        # Used only when local layout is unavailable; keep visual-only pages.
        blocks = [{'id':f'estimate-{n}', 'page':n, 'bbox':[0.,0.,1.,1.],
                   'text':pages[n-1].get('nativeText') or pages[n-1].get('markdown') or '',
                   'kind':'page', 'visualOnly':not bool(pages[n-1].get('nativeText')),
                   'hasVisual':bool(pages[n-1].get('imageRegions') or pages[n-1].get('tableRegions'))}
                  for n in selected]
    blocks = [b for b in blocks if b['page'] in selected]
    from pdf_visual_selection import locally_skipped
    eligible = [b for b in blocks if not locally_skipped(b)]
    windows, current, size = [], [], 0
    for b in eligible:
        amount = len(json.dumps(planning_fragment(b), ensure_ascii=False).encode())
        if current and (size+amount > 50000 or len(current) >= 220):
            windows.append(current); current, size = [], 0
        current.append(b); size += amount
    if current: windows.append(current)
    plan_input = plan_output = plan_calls = 0
    for i, window in enumerate(windows):
        if not any(b['text'].strip() for b in window): continue
        payload = {'task':'region_groups','targets':[planning_fragment(b) for b in window],
                   'before':[planning_fragment(b) for b in windows[i-1][-2:]] if i else [],
                   'after':[planning_fragment(b) for b in windows[i+1][:2]] if i+1<len(windows) else []}
        plan_input += text_tokens(PLAN_PROMPT)+text_tokens(PLAN_FORMAT)+text_tokens(payload)+100
        plan_output += min(6000, 100*len(window)+80)
        plan_calls += 1
    if jobs is None:
        jobs = jobs_for(local_groups(eligible, 'slide-v1'))
    cover = plain_cover_ids(blocks)
    jobs = [j for j in jobs if not j.get('skip') and j['blocks']
            and not all(b['id'] in cover for b in j['blocks'])]
    study_input = study_output = image_tokens = crops_count = source_tokens = effective_image_tokens = 0
    context = document_context(document)
    positions = {b['id']:i for i,b in enumerate(blocks)}
    for job in jobs:
        crops = []
        from pdf_study_text_input import render_blocks
        for run in crop_runs(render_blocks(job['blocks'])):
            n = run[0]['page']; page = pages[n-1]
            width, height = float(page.get('width') or 595), float(page.get('height') or 842)
            scale = min(4., MAX_SIDE/max(width,height))
            w, h = math.ceil(width*scale), math.ceil(height*scale)
            box = [min(b['bbox'][0] for b in run), min(b['bbox'][1] for b in run),
                   max(b['bbox'][2] for b in run), max(b['bbox'][3] for b in run)]
            px, py = max(3,math.ceil(w*.003)), max(3,math.ceil(h*.003))
            cw = min(w,math.ceil(box[2]*w)+px)-max(0,math.floor(box[0]*w)-px)
            ch = min(h,math.ceil(box[3]*h)+py)-max(0,math.floor(box[1]*h)-py)
            patches=math.ceil(cw/32)*math.ceil(ch/32)
            image_tokens += math.ceil(patches*2.46)
            # A feature for saturation observed in saved request usage, not a
            # provider pricing rule. The uncapped reservation proxy stays separate.
            effective_image_tokens += min(patches,1536)*2.46
            crops.append({'page':n,'blockIds':[b['id'] for b in run]})
        neighbors=[]
        left=min(positions[b['id']] for b in job['blocks'])
        right=max(positions[b['id']] for b in job['blocks'])
        for i,edge in ((left-1,job['blocks'][0]),(right+1,job['blocks'][-1])):
            if 0<=i<len(blocks):
                b=blocks[i]
                if b.get('headingId') and b.get('headingId')==edge.get('headingId') and b.get('kind') not in ('heading','label'):
                    neighbors.append({'page':b['page'],'text':b['text'],'backgroundOnly':True})
        study_input += (text_tokens(STUDY_PROMPT)+text_tokens(STUDY_FORMAT)
                        +text_tokens(teaching_payload(job,crops,context,neighbors))+100)
        # Output cannot be known locally. Source length and visual/definition load
        # size a prior that is subsequently calibrated against stage usage.
        source = sum(text_tokens(b['text']) for b in job['blocks'])
        source_tokens += source
        visuals = sum(bool(b.get('hasVisual') or b.get('visualOnly')) for b in job['blocks'])
        entries = sum(bool(entry_label(b)) for b in job['blocks'])
        study_output += min(18000, 500+source*1.1+visuals*350+entries*180)
        crops_count += len(crops)
    study_input += image_tokens
    outline_units={j.get('topicIndex',i):j.get('unitContext',{}).get('current',{'title':j['title']}) for i,j in enumerate(jobs)}
    outline_input = (text_tokens(OUTLINE_PROMPT)+text_tokens(OUTLINE_FORMAT)+text_tokens(list(outline_units.values()))+100) if jobs else 0
    return {'region_plan':{'input':plan_input,'output':plan_output,'calls':plan_calls},
            'region_study':{'input':study_input,'output':study_output,'calls':len(jobs)},
            'summary_reduce':{'input':outline_input,'output':250 if jobs else 0,'calls':int(bool(jobs))},
            'details':{'pages':len(selected),'textCharacters':sum(len(b['text']) for b in eligible),
                       'sourceTokenProxy':source_tokens,'effectiveImageTokenProxy':effective_image_tokens,
                       'fragments':len(eligible),'cropImages':crops_count,'imageTokenProxy':image_tokens,
                       'sourceImages':sum(len(pages[n-1].get('imageRegions') or []) for n in selected),
                       'tableRegions':sum(len(pages[n-1].get('tableRegions') or []) for n in selected),
                       'grouping':'cached_plan' if known_jobs else 'local_proxy'}}


def study_components(work, rates):
    """Separate image size, source density and repeated request overhead."""
    stage = work['region_study']
    details = work['details']
    raw_visual = details['imageTokenProxy']*rates[0]/1_000_000
    visual = details['effectiveImageTokenProxy']*rates[0]/1_000_000
    # The source prior includes its input and learner explanation expansion.
    source = details['sourceTokenProxy']*(rates[0]+1.1*rates[1])/1_000_000
    overhead = ((stage['input']*rates[0]+stage['output']*rates[1])/1_000_000
                -raw_visual-source)
    return visual, source, max(0.,overhead)


def solve(matrix, vector):
    """Small pivoted linear solve; no numerical-library runtime dependency."""
    rows=[list(row)+[value] for row,value in zip(matrix,vector)]
    n=len(rows)
    for col in range(n):
        pivot=max(range(col,n),key=lambda i:abs(rows[i][col]))
        rows[col],rows[pivot]=rows[pivot],rows[col]
        divisor=rows[col][col]
        if abs(divisor)<1e-12:return None
        rows[col]=[v/divisor for v in rows[col]]
        for i in range(n):
            if i!=col:
                factor=rows[i][col]
                rows[i]=[a-factor*b for a,b in zip(rows[i],rows[col])]
    return [row[-1] for row in rows]


def fit_study(history, rates):
    """Fit three positive workload coefficients, not one pooled cost ratio.

    Source density cannot be shrunk together with repeated prompt overhead:
    text-dense courses and slide/image courses have different cost composition.
    Relative errors weight documents equally; ridge and a positive floor handle
    tiny/collinear samples. Never use target usage or target semantic plan here.
    """
    rows=[]
    for sample in history:
        actual=sample['stageUsage'].get('region_study',{}).get('usageBasedUsd',0)
        if isinstance(actual,(int,float)) and math.isfinite(actual) and actual>0:
            rows.append(tuple(v/actual for v in study_components(sample['workload'],rates)))
    if len(rows)<3:return None
    ridge,floor=.1,.05
    best=None
    # Enumerate the eight active sets of this tiny constrained ridge problem.
    for mask in range(8):
        free=[i for i in range(3) if mask & (1<<i)]
        fixed=[i for i in range(3) if i not in free]
        coefficients=[floor]*3
        if free:
            matrix=[[sum(row[i]*row[j] for row in rows)+(ridge if i==j else 0)
                     for j in free] for i in free]
            vector=[sum(row[i]*(1-sum(row[j]*floor for j in fixed)) for row in rows)+ridge
                    for i in free]
            solution=solve(matrix,vector)
            if solution is None or any(v<floor for v in solution):continue
            for i,value in zip(free,solution):coefficients[i]=value
        loss=sum((sum(a*b for a,b in zip(row,coefficients))-1)**2 for row in rows)
        loss+=ridge*sum((v-1)**2 for v in coefficients)
        if best is None or loss<best[0]:best=(loss,coefficients)
    return best[1]


def estimate(document, targets, history, *, plan_cached=False, study_remaining=1.0,
             outline_cached=False, work=None, pending_work=None, model='gpt-6-luna'):
    from pdf_ai import PRICES
    work = work or workload(document, targets)
    pending_work = pending_work or work
    rates = PRICES[model]
    stage_costs, total_tokens, ratios = {}, 0, []
    usable = [s for s in history if s.get('workload') and s.get('stageUsage')]
    # A slide with one source per page cannot calibrate a fragmented textbook
    # merely because both use the same model. Compare source geometry/density,
    # without subject names or document IDs, before applying measured ratios.
    def densities(w):
        d=w.get('details',{});pages=max(1,d.get('pages',1))
        return (max(1,d.get('fragments',0)/pages),
                max(1,d.get('sourceTokenProxy',0)/pages),
                max(1,d.get('effectiveImageTokenProxy',0)/pages))
    target=densities(work)
    def distance(sample):
        own=densities(sample['workload'])
        return max(abs(math.log(a/b)) for a,b in zip(own,target))
    usable=sorted((s for s in usable if distance(s)<=math.log(4)),key=distance)[:8]
    # A cached paid plan makes the actual job geometry known. Calibrate this
    # regime against historical actual jobs, not the cold page-local proxy.
    study_history = usable
    if pending_work['details'].get('grouping')=='cached_plan':
        study_history=[{**s,'workload':s['plannedWorkload']} for s in usable if s.get('plannedWorkload')]
    study_fit = fit_study(study_history,rates)
    for kind in ('region_plan','region_study','summary_reduce'):
        stage = pending_work[kind] if kind == 'region_study' else work[kind]
        fraction = (0 if plan_cached else 1) if kind == 'region_plan' else (
            0 if outline_cached else 1) if kind == 'summary_reduce' else study_remaining
        observations = []
        for sample in (study_history if kind=='region_study' else usable):
            baseline = sample['workload'][kind]
            base_cost = (baseline['input']*rates[0]+baseline['output']*rates[1])/1_000_000
            actual = sample['stageUsage'].get(kind, {}).get('usageBasedUsd', 0)
            if base_cost > 0 and isinstance(actual, (float,int)) and math.isfinite(actual) and actual > 0:
                observations.append(actual/base_cost)
        correction = statistics.median(observations) if observations else 1.
        # Never let one/two cheap cache-hot runs shrink every component of a
        # cold quote. Exact-plan and sufficiently sampled fits stay separate.
        if len(observations)<3:correction=max(1.,correction)
        stage_costs[kind] = (stage['input']*rates[0]+stage['output']*rates[1])/1_000_000*correction*fraction
        if kind=='region_study' and study_fit is not None:
            components=study_components(pending_work,rates)
            stage_costs[kind]=sum(a*b for a,b in zip(components,study_fit))*fraction
            baseline=(stage['input']*rates[0]+stage['output']*rates[1])/1_000_000
            correction=stage_costs[kind]/(baseline*fraction) if baseline and fraction else 0
        # Cache discounts change price, not token count. Use token observations
        # independently instead of multiplying tokens by the dollar ratio.
        token_ratios=[]
        for sample in (study_history if kind=='region_study' else usable):
            baseline=sample['workload'][kind]
            previous=sample['stageUsage'].get(kind,{})
            actual_tokens=previous.get('inputTokens',0)+previous.get('outputTokens',0)
            if actual_tokens>0 and baseline['input']+baseline['output']>0:
                token_ratios.append(actual_tokens/(baseline['input']+baseline['output']))
        token_correction=statistics.median(token_ratios)if len(token_ratios)>=3 else 1.
        total_tokens += (stage['input']+stage['output'])*token_correction*fraction
        if kind=='region_study' and study_fit is not None:
            for sample in study_history:
                fitted=sum(a*b for a,b in zip(study_components(sample['workload'],rates),study_fit))
                actual=sample['stageUsage'].get(kind,{}).get('usageBasedUsd',0)
                if fitted>0 and actual>0:ratios.append(actual/fitted)
        elif observations and correction>0:
            ratios.extend(r/correction for r in observations)
    usd = sum(stage_costs.values())
    # A sparse calibration set is not a narrow confidence interval. Include the
    # observed spread and widen for the unknown semantic grouping/output length.
    uncertainty = 1.8 if len(usable)<3 else 1.45
    low_factor = min([1/uncertainty]+ratios)
    high_factor = max([uncertainty]+ratios)
    return {'usd':round(usd,8),'lowUsd':round(usd*low_factor,8),
            'highUsd':round(usd*high_factor,8),'tokens':round(total_tokens),
            'sampleCount':len(usable),'stageUsd':stage_costs,'workload':pending_work['details'],
            'neighborDocumentIds':[], 'basis':'local_workload', 'studyCalibration':study_fit}
