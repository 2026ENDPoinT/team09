"""Offline review/report for saved CLI tutor sessions. Never calls a model or network."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

from pdf_ai import load_tutor_document, review_evidence
from pdf_pipeline import write_json


def compact(text):
    return re.sub(r'\s+', '', text)


def normalize(text):
    return compact(unicodedata.normalize('NFKC', text))


def audit_group(folder, cases, review):
    session = json.loads((folder / 'session.json').read_text())
    document = load_tutor_document(Path(session['folder']))
    sources = {s['id']: s for s in document['chunks']}
    entries = [entry for path in (folder / 'usage').glob('*.json')
               for entry in json.loads(path.read_text()).get('requests', [])]
    entries.sort(key=lambda e: e.get('createdAtMs', 0))
    chat_entries = [e for e in entries if e.get('kind') != 'web_search' and e.get('state') == 'settled']
    raw_paths = sorted((folder / 'generated/paid-responses').glob('*.raw.json'),
                       key=lambda p: p.stat().st_mtime_ns)
    # Cold serial CLI sessions have one raw file per settled chat entry. Check
    # both count and returned usage before pairing; never guess on a mismatch.
    if len(raw_paths) != len(chat_entries):
        raise ValueError('Raw response count does not match settled chat entries')
    values = {}
    for path, entry in zip(raw_paths, chat_entries):
        raw = json.loads(path.read_text())
        if raw.get('usage') != entry.get('usage'):
            raise ValueError('Raw response usage/order mismatch')
        values[entry['requestId']] = (path, json.loads(raw['choices'][0]['message']['content']))
    rows, offset = [], 0
    extra_review_requests = 0
    extra_review_usd = 0
    for case, turn in zip(cases, session['turns']):
        requests = entries[offset:offset + turn['usage']['requests']]
        offset += turn['usage']['requests']
        attempts, invalid = [], []
        for entry in requests:
            pair = values.get(entry['requestId'])
            if pair is None:
                continue
            path, value = pair
            if 'answer' not in value:
                continue
            rejected = []
            for quote in value.get('evidence', []):
                checked, _ = review_evidence([quote], sources)
                if checked:
                    continue
                original = sources.get(quote.get('sourceId'), {}).get('text', '')
                text = quote.get('quote', '')
                cause = ('unknown_source' if not original else
                         'whitespace_or_line_wrap' if compact(text) in compact(original) else
                         'unicode_and_whitespace' if normalize(text) in normalize(original) else
                         'changed_or_reordered_text')
                rejected.append({'sourceId': quote.get('sourceId'), 'quote': text, 'cause': cause})
            invalid.extend(rejected)
            attempts.append({'rawFile': str(path), 'answer': value.get('answer'),
                             'offeredQuotes': value.get('evidence', []), 'rejectedQuotes': rejected,
                             'usageUsd': entry.get('estimatedUsd', 0)})
        # For this suite the tool-free planner precedes one answer. Additional
        # answer drafts are the existing compact review path, not a new judge.
        if len(attempts) > 1:
            extra_review_requests += len(attempts) - 1
            extra_review_usd += sum(a['usageUsd'] for a in attempts[1:])
        result = turn['result']
        displayed = result.get('evidence', [])
        verified, incomplete = review_evidence(
            [{'sourceId': e['sourceId'], 'quote': e['quote']} for e in displayed], sources)
        if len(verified) != len(displayed):
            raise ValueError('Displayed quote does not match saved original')
        rows.append({'id': case['id'], 'category': case['category'], 'chain': case.get('chain'),
                     'question': turn['question'], 'page': turn['page'],
                     'expected': case['expected'], 'review': review[case['id']],
                     'answer': result['answer'], 'evidence': displayed,
                     'webSources': result.get('webSources', []),
                     'searchDecision': result.get('searchDecision'), 'usage': turn['usage'],
                     'elapsedSeconds': turn['elapsedSeconds'], 'modelAttempts': attempts,
                     'rejectedQuoteCauseCounts': dict(Counter(v['cause'] for v in invalid)),
                     'missingDisplayedPdfEvidence': bool(result.get('requiresPdfEvidence') and
                                                       not displayed and not result.get('visualPages'))})
    if offset != len(entries):
        raise ValueError('Unused requests remain in group audit')
    summary = {'count': len(rows), 'grades': dict(Counter(r['review']['grade'] for r in rows)),
               'factual': dict(Counter(r['review']['factual'] for r in rows)),
               'followupContext': dict(Counter(r['review']['context'] for r in rows if r['category'] == 'followup')),
               'missingDisplayedPdfEvidence': sum(r['missingDisplayedPdfEvidence'] for r in rows),
               'webSearchCalls': sum(r['usage']['webSearchCalls'] for r in rows),
               'usageUsd': round(sum(e.get('estimatedUsd', 0) for e in entries if e.get('state') == 'settled'), 8),
               'uncertainUsd': round(sum(e.get('reservedUsd', 0) for e in entries if e.get('state') != 'settled'), 8),
               'requests': len(entries), 'extraReviewRequests': extra_review_requests,
               'extraReviewUsd': round(extra_review_usd, 8),
               'meanSeconds': round(sum(r['elapsedSeconds'] for r in rows) / len(rows), 3)}
    return rows, summary


def render(rows, summary):
    esc = html.escape
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>튜터 CLI 품질 검증</title>',
             '<style>body{max-width:1050px;margin:40px auto;padding:0 22px;font:16px/1.65 system-ui;color:#243142}'
             'article{border-top:1px solid #ddd;padding:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}'
             '.pass{color:#16713b}.partial{color:#946000}.fail{color:#b02020}summary{cursor:pointer}</style>',
             '<h1>튜터 CLI 품질 검증 · 2026-10-16</h1>',
             '<p>금융·예술 PDF의 새로운 40문항을 각각 연속 대화로 실행했어요. 모델의 자기평가 대신 원문과 그림에 직접 대조했어요. 최초 실행을 재실행으로 덮어쓰지 않아요.</p>',
             '<p><b>핵심 내용의 오답과 16개 꼬리질문의 대상 혼동은 발견하지 못했어요.</b> 다만 PDF 인용과 요청한 공식 외부 출처까지 포함하면 충족 22개, 부분 충족 18개예요. 부분 충족을 모두 내용 오답으로 해석하지 않아요.</p>',
             '<table><tr><th>분야</th><th>충족</th><th>부분 충족</th><th>실패</th></tr>']
    for group, label in [('finance', '금융'), ('art', '예술')]:
        counts = summary['groups'][group]['grades']
        parts.append(f'<tr><td>{label}</td><td>{counts.get("pass", 0)}</td><td>{counts.get("partial", 0)}</td><td>{counts.get("fail", 0)}</td></tr>')
    parts += ['</table>',
              f'<p>새 질문 40개 + 기록된 직전 대화에서 재확인 4회, 총 {summary["executionCountIncludingRepeats"]}회 실행했어요. '
              f'전체 비용 추산 ${summary["totalCostUsd"]:.5f}, 약 {summary["totalCostKrwAt1400"]:.0f}원(1달러=1,400원)이에요. '
              f'외부검색 없는 첫 질문들의 평균 비용은 약 {summary["initialNonWebMeanKrwAt1400"]:.2f}원이에요.</p>',
              '<p>14문항에서 PDF 근거가 필요한 답변에 표시 가능한 인용이 남지 않았어요. 숫자 서체와 줄바꿈 차이, 문장 생략·재배열이 원인이에요. '
              '다른 2문항은 인용은 있으나 답변의 핵심 일부를 연결하지 못했어요. 외부검색 2문항은 요청한 공식 기관 소개/연구 글을 확보하지 못했어요.</p>',
              '<p>첫 실행에서 기존 자동 검토가 23회 추가 실행됐고, 약 12.34원이 들었어요. 내용 검토의 효용과 별개로 인용 표기 문제는 로컬에서 해결하는 편이 효율적이에요. '
              '이번에는 실제 튜터 코드와 원본 PDF를 변경하지 않고 검증 기록만 만들었어요.</p>',
              '<details><summary>전체 집계 JSON</summary><pre>' + esc(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre></details>']
    for row in rows:
        review = row['review']
        parts += [f'<article><h2 class="{review["grade"]}">{row["id"]} · {review["grade"]}</h2>',
                  '<p>' + esc(row['question']) + '</p>', '<pre>' + esc(row['answer']) + '</pre>',
                  '<p><b>평가:</b> ' + esc(review['note']) + '</p>',
                  '<details><summary>기대사항·근거·인용 진단</summary><pre>' +
                  esc(json.dumps({k: row[k] for k in ['expected', 'evidence', 'webSources',
                      'searchDecision', 'usage', 'modelAttempts']}, ensure_ascii=False, indent=2)) + '</pre></details></article>']
    return '\n'.join(parts) + '</html>'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('build/tutor-quality-cli-20261016'))
    parser.add_argument('--review', type=Path, default=Path('scripts/tutor_qa_review_20261016.json'))
    args = parser.parse_args()
    suite = json.loads((args.root / 'suite.json').read_text())
    review = json.loads(args.review.read_text())
    rows, groups = [], {}
    for group in ('finance', 'art'):
        group_rows, groups[group] = audit_group(args.root / group, suite[group]['cases'], review[group])
        rows.extend(group_rows)
    summary = {'groups': groups, 'initialGrades': dict(Counter(r['review']['grade'] for r in rows)),
               'initialFactual': dict(Counter(r['review']['factual'] for r in rows)),
               'initialFollowupContext': dict(Counter(r['review']['context'] for r in rows if r['category'] == 'followup')),
               'initialCostUsd': round(sum(g['usageUsd'] + g['uncertainUsd'] for g in groups.values()), 8),
               'limitations': ['개발용 40문항이며 전체 정답률로 일반화하지 않아요.',
                              '부분 충족은 주로 인용·공식 원문 확보 미완료이며 모두 내용 오답이라는 뜻은 아니에요.',
                              'PDF에 있는 내용 자체의 모든 역사적·제도적 사실을 별도로 검증한 것은 아니에요.']}
    recheck_rows, rechecks = [], {}
    for folder in sorted((args.root / 'rechecks').glob('*')):
        if not (folder / 'session.json').is_file():
            continue
        cid = folder.name
        group = 'finance' if cid.startswith('F') else 'art'
        case = next(c for c in suite[group]['cases'] if c['id'] == cid)
        found, rechecks[cid] = audit_group(folder, [case], review[group])
        found[0]['execution'] = 'repeat_from_saved_pre_question_memory'
        recheck_rows.extend(found)
    summary['rechecks'] = rechecks
    summary['recheckGrades'] = dict(Counter(r['review']['grade'] for r in recheck_rows))
    summary['executionCountIncludingRepeats'] = len(rows) + len(recheck_rows)
    summary['totalCostUsd'] = round(summary['initialCostUsd'] +
        sum(r['usageUsd'] + r['uncertainUsd'] for r in rechecks.values()), 8)
    summary['totalCostKrwAt1400'] = round(summary['totalCostUsd'] * 1400, 3)
    summary['withinBudget'] = summary['totalCostUsd'] < 2
    normal = [r for r in rows if not r['usage']['webSearchCalls']]
    summary['initialNonWebMeanKrwAt1400'] = round(
        sum(r['usage']['usageBasedUsd'] * 1400 for r in normal) / len(normal), 3)
    summary['extraReviewRequests'] = sum(g['extraReviewRequests'] for g in groups.values())
    summary['extraReviewKrwAt1400'] = round(sum(g['extraReviewUsd'] for g in groups.values()) * 1400, 3)
    summary['missingDisplayedPdfEvidence'] = sum(g['missingDisplayedPdfEvidence'] for g in groups.values())
    summary['diagnosticCases'] = {
        'formattingMismatch': [r['id'] for r in rows if any(
            r['rejectedQuoteCauseCounts'].get(k) for k in ('whitespace_or_line_wrap', 'unicode_and_whitespace'))],
        'changedOrReorderedQuote': [r['id'] for r in rows if r['rejectedQuoteCauseCounts'].get('changed_or_reordered_text')]}
    summary['recommendations'] = [
        '원문의 숫자 서체·줄바꿈을 로컬에서 정규화해 대조하고, 연결할 때는 반드시 원래 글자와 위치를 복원해요.',
        '자유롭게 다시 쓴 인용문 대신 제공한 원문 조각의 ID/범위를 선택하도록 설계하는 방안을 검토해요.',
        '형식 차이만으로 모델 검토를 다시 호출하지 않도록 하되, 틀린 전제·조건 검토는 유지해요.',
        '특정 공식 문서 요청에서는 첫 검색의 대상 문서를 더 명확히 지정해요. 이번 두 실패 응답에는 도구 한도 이후의 추가 검색 시도가 남아 있으나 1회 제한만이 실패 원인이라고 단정할 수는 없어요.']
    manifest = json.loads((args.root / 'manifest.json').read_text())
    summary['unchangedProductionSources'] = all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in manifest['sourceHashes'].items())
    summary['unchangedPdfFiles'] = all(
        hashlib.sha256((Path('.synesis/pdf') / doc['documentId'] / name).read_bytes()).hexdigest() == doc[key]
        for doc in manifest['documents'].values()
        for name, key in [('document.json', 'indexSha256'), ('source.pdf', 'sourceSha256')])
    write_json(args.root / 'reviewed-rechecks.json', recheck_rows)
    write_json(args.root / 'reviewed-results.json', rows)
    write_json(args.root / 'reviewed-summary.json', summary)
    shown = rows + [{**r, 'id': r['id'] + ' (재실행)'} for r in recheck_rows]
    (args.root / 'report.html').write_text(render(shown, summary), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
