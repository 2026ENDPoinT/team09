"""Local-only aggregate measurements and source-preservation checks for raster A/B."""
from collections import Counter
import argparse
import hashlib
import html
import json
from pathlib import Path

from audit_pdf_raster_benchmark import CASES, budget_used
from pdf_pipeline import write_json
from pdf_new_concept_v02_regions import contains


def change(a,b):return round(100*(b/a-1),2) if a else None


def measure(root,case,arm):
    folder=root/case/arm
    run=json.loads((folder/'run.json').read_text())
    result=json.loads((folder/'result.json').read_text())
    cache=Path(run['cacheRoot'])
    blocks=json.loads((cache/'blocks.json').read_text())
    layout=json.loads((cache/'local-layout.json').read_text())
    coverage={c['blockId']:c['state'] for c in result['coverage']}
    word_states=Counter()
    for block in blocks:
        word_states.update({coverage.get(block['id'],'unaccounted'):len(block.get('wordIds',[]))})
    usage=run['usage']
    return {'wallSeconds':round(run['wallSeconds'],3),'planningSeconds':round(run['planningSeconds'],3),
            'generationSeconds':run['metrics']['elapsedSeconds'],
            'firstResultSeconds':(run['planningSeconds']+run['metrics']['firstResultSeconds']) if run['metrics'].get('firstResultSeconds') is not None else None,
            'usd':usage['usageBasedUsd'],'krwAt1400':round(usage['usageBasedUsd']*1400,2),
            'inputTokens':usage['inputTokens'],'cachedInputTokens':usage['cachedInputTokens'],
            'outputTokens':usage['outputTokens'],'totalTokens':usage['inputTokens']+usage['outputTokens'],
            'requests':usage['requests'],'unknownUsageRequests':usage['unknownUsageRequests'],
            'byKind':usage['byKind'],'sourceBlocks':len(blocks),
            'concepts':sum(len(c.get('entries',[])) for c in result.get('concepts',[])),
            'sections':len(result['sections']),'processingComplete':result['processingComplete'],
            'coverageComplete':result['coverageComplete'],'incompleteStudyPages':result['incompleteStudyPages'],
            'wordCoverage':dict(word_states),'cacheHit':bool(result.get('cacheHit')),
            'responseReuseCount':len(result.get('cacheReuse',{}).get('replies',[])),
            'learnerTextCharacters':sum(len(p.get('body',''))+len(p.get('easyExplanation','')) for s in result['sections'] for p in s.get('parts',[])),
            'failedUnits':result['failedUnits']},blocks,layout


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=args.output.resolve();rows=[]
    manifest=json.loads((root/'manifest.json').read_text())
    for case,_,title,pages in CASES:
        if not all((root/case/arm/'result.json').exists() for arm in ('before','after')):continue
        before,old,old_layout=measure(root,case,'before');after,new,new_layout=measure(root,case,'after')
        old_words=[w for p in old_layout['pages'] for w in p['words']]
        new_words=[w for p in new_layout['pages'] for w in p['words']]
        by_page={}
        for b in new:by_page.setdefault(b['page'],[]).append(b)
        lost_visuals=[b['id'] for b in old if b.get('hasVisual') and not any(
            n.get('hasVisual') and contains(n['bbox'],b['bbox']) for n in by_page.get(b['page'],[]))]
        owned=[w for b in new for w in b.get('wordIds',[])]
        source=next(x for x in manifest['cases'] if x['case']==case)
        source_unchanged=hashlib.sha256(Path(source['source']).read_bytes()).hexdigest()==source['sha256']
        row={'case':case,'title':title,'pages':pages,'before':before,'after':after,
             'changesPercent':{key:change(before[key],after[key]) for key in
                 ('wallSeconds','usd','inputTokens','outputTokens','totalTokens','requests')},
             'preservation':{'identicalPreplanBlocks':old==new,
                 'identicalNativeWordsAndGeometry':old_words==new_words,
                 'nativeWords':len(new_words),'everyWordOwnedExactlyOnce':Counter(owned)==Counter(w['id'] for w in new_words),
                 'lostVisualBboxes':lost_visuals,'originalSourceUnchanged':source_unchanged}}
        review_path=root/'quality'/case/'review.json'
        if review_path.exists():
            review=json.loads(review_path.read_text());mapping=json.loads(review_path.with_name('mapping.json').read_text())
            counts={arm:Counter() for arm in ('before','after')}
            for check in review.get('checks',[]):
                for label,arm in mapping.items():counts[arm][check[label]['verdict']]+=1
            row['sampleQuality']={'mapping':mapping,'verdictCounts':{k:dict(v) for k,v in counts.items()},
                'checks':review.get('checks',[]),'issues':review.get('issues',[]),
                'textCoverage':review.get('textCoverage'),
                'comparison':review.get('comparison'),'limitations':review.get('limitations')}
        rows.append(row)
    totals={arm:{key:sum(r[arm][key] for r in rows) for key in
                ('wallSeconds','usd','inputTokens','cachedInputTokens','outputTokens','totalTokens','requests')}
            for arm in ('before','after')}
    report={'method':'Paired cold local-cache A/B; same current model, prompts, 8 workers; only raster coalescing differs.',
            'limitations':['One generation per variant per document; elapsed time and generated text are stochastic.',
                           'Blind AI review uses all native text and learner explanations; visual inspection samples 4 pages per document, not whole-document proof.',
                           'Existing native-text indexes are identical in both variants; initial PDF import/indexing time is outside the analysis timer.',
                           'Server-side prompt cache is not disabled; cached input is recorded separately.',
                           'Quality inputs apply the same local long-table repair to both arms. Original measured results remain archived; no model prose is replaced.',
                           'Automated whole-text missing-topic flags can be false positives; manual review findings are authoritative within their stated scope.',
                           'KRW uses the application\'s fixed illustrative 1,400 KRW/USD conversion, not a live exchange quote.'],
            'cases':rows,'totals':totals,'totalChangesPercent':{key:change(totals['before'][key],totals['after'][key])
                for key in totals['before']},'budget':{'limitUsd':2,**budget_used(root)}}
    for key,name in [('manualReview','manual-review.json'),('localTableRepair','local-table-repair.json')]:
        path=root/name
        if path.exists():report[key]=json.loads(path.read_text())
    write_json(root/'comparison.json',report)
    table=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [r['title'],r['pages'],
       f"{r['before']['wallSeconds']:.1f} → {r['after']['wallSeconds']:.1f}",
       f"${r['before']['usd']:.5f} → ${r['after']['usd']:.5f} ({r['before']['krwAt1400']:.1f} → {r['after']['krwAt1400']:.1f}원)",
       f"{r['before']['inputTokens']:,} → {r['after']['inputTokens']:,}",
       f"{r['before']['outputTokens']:,} → {r['after']['outputTokens']:,}"])+ '</tr>' for r in rows)
    summary=(f'<p><strong>5개 합계:</strong> 시간 {totals["before"]["wallSeconds"]:.1f} → {totals["after"]["wallSeconds"]:.1f}초, '
             f'비용 ${totals["before"]["usd"]:.5f} → ${totals["after"]["usd"]:.5f}, '
             f'전체 토큰 {totals["before"]["totalTokens"]:,} → {totals["after"]["totalTokens"]:,}.</p>'
             f'<p><strong>테스트·검수 총비용 ${report["budget"]["actualUsd"]:.6f} / 상한 $2.</strong> '
             f'미확정 사용량 예약 ${report["budget"]["uncertainReservedUsd"]:.6f}.</p>')
    review=report.get('manualReview',{})
    summary+='<p>'+html.escape(review.get('conclusion','품질 검수를 진행 중이에요.'))+'</p>'
    if review.get('confirmedRemainingIssues'):
        summary+='<p><strong>남은 한계:</strong> '+ ' '.join(html.escape(x['finding']) for x in review['confirmedRemainingIssues'])+'</p>'
    if review.get('fixedIssue'):
        summary+='<p><strong>추가 수정:</strong> '+html.escape(review['fixedIssue']['finding'])+' 기존 유료 응답으로 표 복구를 확인했고, 추가 API 호출은 없어요.</p>'
    source_links=' '.join(f'<a href="{html.escape(x["source"],quote=True)}">{html.escape(x["title"])} ({x["pages"]}쪽)</a>' for x in manifest['cases'])
    doc='''<!doctype html><meta charset="utf-8"><title>SYNESIS PDF A/B 검사</title>
<style>body{font:16px -apple-system,sans-serif;color:#10294b;background:#f6f8fc;margin:40px;line-height:1.65}main{max-width:1200px;margin:auto}table{border-collapse:collapse;background:white;width:100%}td,th{border:1px solid #d6dfed;padding:12px;text-align:left}h1{font-size:28px}pre{white-space:pre-wrap;background:white;border:1px solid #d6dfed;padding:20px;border-radius:12px}details{margin-top:20px}</style><main>
<h1>PDF 이미지 조각 병합 · 수정 전/후 비교</h1><p>5개 PDF · 총 150쪽 · 양쪽 모두 새 분석. 원본·기존 결과 보존. 모델·설명 지침·동시 처리 수(8개) 동일.</p>
<table><tr><th>자료</th><th>쪽</th><th>전체 시간(초)</th><th>비용(USD)</th><th>입력 토큰</th><th>출력 토큰</th></tr>'''+table+'</table>'+summary+'''
<p>모든 수치에는 묶음 판단·요약/개념 생성·개요가 포함돼요. 원화는 앱과 같은 1달러=1,400원 환산 예시예요. 품질 검수 비용은 비교 비용과 별도로 전체 예산에 포함돼요.</p>
<p>효과는 이미지 조각이 많았던 39쪽 자료에 집중돼요. 나머지 네 자료는 추출 조각이 동일했고, 원격 AI의 묶음 판단·설명 분량·캐시·서버 속도에 따른 변동이 있어요. 각 변형 1회씩의 측정으로 모든 파일의 향상을 보장하지 않아요.</p>
<p>원문 이미지 20쪽을 직접 확인하고, 익명 AI 보조 검수 58항목을 실제 생성 설명과 대조했어요. 전체 본문 누락을 판단한 자동 검수에는 오탐이 있어 실제 내용으로 교정했어요.</p>
<p>검수 원문: '''+source_links+'''</p>
<details><summary>측정 원본 · 보존 검사 · 표본 품질 검수 상세</summary><pre>'''+html.escape(json.dumps(report,ensure_ascii=False,indent=2))+'''</pre></details></main>'''
    (root/'report.html').write_text(doc)
    print(json.dumps({'cases':len(rows),'totals':totals,'changes':report['totalChangesPercent'],'budget':report['budget']},ensure_ascii=False))


if __name__=='__main__':main()
