"""Offline audit of the saved citation/context recheck. No API calls or model grading."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

from pdf_ai import load_tutor_document, review_evidence


def audit(folder, cases, skip=0):
    session = json.loads((folder / 'session.json').read_text())
    turns = session['turns'][skip:]
    assert len(turns) == len(cases), (folder, len(turns), len(cases))
    document = load_tutor_document(Path(session['folder']))
    sources = {c['id']: c for c in document['chunks']}
    entries = sorted([e for p in (folder / 'usage').glob('*.json')
                      for e in json.loads(p.read_text()).get('requests', [])],
                     key=lambda e: e['createdAtMs'])
    chats = [e for e in entries if e['state'] == 'settled' and e['kind'] != 'web_search']
    raw = sorted((folder / 'generated/paid-responses').glob('*.raw.json'),
                 key=lambda p: p.stat().st_mtime_ns)
    assert len(raw) == len(chats), folder
    values = {}
    for path, entry in zip(raw, chats):
        value = json.loads(path.read_text())
        assert value['usage'] == entry['usage'], path
        values[entry['requestId']] = json.loads(value['choices'][0]['message']['content'])
    offset, rows = 0, []
    for case, turn in zip(cases, turns):
        assert case['question'] == turn['question'], case['id']
        requests = entries[offset:offset + turn['usage']['requests']]
        offset += len(requests)
        answers = [e for e in requests if 'answer' in values.get(e['requestId'], {})]
        result = turn['result']
        quotes = result.get('evidence', [])
        checked, _ = review_evidence(quotes, sources)
        assert len(checked) == len(quotes), (folder, case['id'], 'unverified displayed quote')
        rows.append({'id': case['id'], 'question': turn['question'], 'expected': case['expected'],
                     'answer': result['answer'], 'evidence': quotes,
                     'visualPages': result.get('visualPages', []),
                     'requiresPdfEvidence': result.get('requiresPdfEvidence'),
                     'evidenceIncomplete': result.get('evidenceIncomplete'),
                     'missingPdfEvidence': bool(result.get('requiresPdfEvidence') and
                                               not quotes and not result.get('visualPages')),
                     'searchDecision': result.get('searchDecision'),
                     'webSources': result.get('webSources', []), 'usage': turn['usage'],
                     'elapsedSeconds': turn['elapsedSeconds'],
                     'extraReviewRequests': max(0, len(answers) - 1),
                     'extraReviewUsd': sum(e.get('estimatedUsd', 0) for e in answers[1:]),
                     'session': str(folder / 'session.json')})
    assert offset == len(entries), folder
    return rows, {'executions': len(rows), 'requests': len(entries),
                  'costUsd': sum(e.get('estimatedUsd', 0) for e in entries if e['state'] == 'settled'),
                  'uncertainReservedUsd': sum(e.get('reservedUsd', 0) for e in entries if e['state'] != 'settled'),
                  'webSearchCalls': sum(t['usage']['webSearchCalls'] for t in turns),
                  'extraReviewRequests': sum(r['extraReviewRequests'] for r in rows),
                  'extraReviewUsd': sum(r['extraReviewUsd'] for r in rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('build/tutor-citations-20261016'))
    args = parser.parse_args()
    root = args.root
    base = json.loads(Path('scripts/tutor_qa_cases_20261016.json').read_text())
    cross = json.loads(Path('scripts/tutor_crossfield_cases_20261016.json').read_text())
    suite = {g: base[g] for g in ('finance', 'art')} | cross
    stages, history, latest = {}, [], {}
    configs = [('first', root, tuple(suite), False),
               ('second', root / 'final', tuple(suite), True),
               ('recheck', root / 'recheck', ('art', 'calculus', 'programming'), True)]
    for stage, directory, groups, exclude_external in configs:
        for group in groups:
            cases = [c for c in suite[group]['cases']
                     if not exclude_external or c['id'] not in ('F19', 'A19')]
            rows, stats = audit(directory / group, cases)
            stages[f'{stage}/{group}'] = stats
            for row in rows:
                row.update(stage=stage, group=group)
                history.append(row)
                latest[row['id']] = row
    a06 = [c for c in suite['art']['cases'] if c['id'] == 'A06']
    for stage in ('quiz-recheck', 'quiz-filter-recheck'):
        rows, stats = audit(root / stage / 'art', a06, skip=5)
        stages[stage] = stats
        for row in rows:
            row.update(stage=stage, group='art')
            history.append(row)
            latest[row['id']] = row
    rows, stats = audit(root / 'state-recheck/programming', suite['programming']['cases'])
    stages['state-recheck'] = stats
    for row in rows:
        row.update(stage='state-recheck', group='programming')
        history.append(row)
        latest[row['id']] = row
    # Human review against the stated expectations, original text and rendered
    # pages. This report never treats a model's claimVerdict as a quality grade.
    for cid, row in latest.items():
        row['review'] = {'grade': 'partial' if cid in ('F19', 'A19') else 'pass',
                         'note': '요청한 공식 외부 원문 확보가 부족해요.' if cid in ('F19', 'A19')
                         else '사전 기대사항과 대조했으며 핵심 답변과 대상·조건 연결을 충족해요.'}
    for cid, note in {
        'P02': '주소와 역참조 값은 맞게 구분하지만 틀린 사용자 전제에 “네, 맞아요”로 시작해 혼동을 줄 수 있어요.',
        'P05': 'a=25,b=10은 맞지만 정수 b를 “가리키는” 주체처럼 표현한 문장은 부정확해요.',
        'P08': '재지정 허용 여부는 맞지만 포인터가 저장한 주소와 포인터 자체의 주소를 표현에서 혼용해요.',
    }.items():
        latest[cid]['review'] = {'grade': 'partial', 'note': note}
    old_review = json.loads(Path('scripts/tutor_qa_review_20261016.json').read_text())
    prior_partial = [cid for g in ('finance', 'art') for cid, value in old_review[g].items()
                     if value['grade'] == 'partial']
    resolved = [cid for cid in prior_partial if latest[cid]['review']['grade'] == 'pass']
    assert {11, 12} <= {e['page'] for e in latest['F03']['evidence']}
    assert {4, 12} <= {e['page'] for e in latest['F15']['evidence']}
    summary = {'uniqueQuestions': len(latest), 'executions': len(history), 'stages': stages,
               'totalCostUsd': round(sum(s['costUsd'] + s['uncertainReservedUsd'] for s in stages.values()), 8),
               'unknownReservedUsd': sum(s['uncertainReservedUsd'] for s in stages.values()),
               'latestGrades': dict(Counter(r['review']['grade'] for r in latest.values())),
               'priorPartialResolved': resolved,
               'latestMissingPdfEvidence': [cid for cid, r in latest.items() if r['missingPdfEvidence']],
               'latestIncompleteEvidence': [cid for cid, r in latest.items() if r['evidenceIncomplete']],
               'knownIntermediateFailures': {
                   'first/P06': 'PDF의 a=100으로 사용자의 a=25,b=10 조건을 덮었어요.',
                   'first/C09,C11': '원시함수 여부·서로 다른 적분상수에 대한 판정과 설명이 모순됐어요.',
                   'second/C06': '3x−2x²의 인수분해와 적분 구간·결과가 틀렸어요.',
                   'second/A06,recheck/A06,quiz-recheck/A06': '미답변 OX 문장을 사실인 보충 설명으로 사용했어요.',
                   'recheck/P04': '포인터 재지정 때 변경된 a=25를 초기값 10으로 되돌렸어요.'},
               'limitations': ['고정된 개발 질문의 수동 검증이며 전체 정답률로 일반화하지 않아요.',
                               '실제 인용 원문 확인은 의미상 모든 주장에 대한 증명이 아니에요.',
                               '2건의 공식 외부 원문 확보 문제는 이번에 해결하지 않았어요.',
                               '화면 렌더링·클릭은 CLI에서 검증하지 않아요.']}
    summary['totalCostKrwAt1400'] = round(summary['totalCostUsd'] * 1400, 2)
    baseline = json.loads(Path('build/tutor-quality-cli-20261016/reviewed-summary.json').read_text())
    summary['baselineExtraReviews40'] = sum(baseline['groups'][g]['extraReviewRequests'] for g in ('finance', 'art'))
    summary['firstRecheckExtraReviews40'] = sum(stages[f'first/{g}']['extraReviewRequests'] for g in ('finance', 'art'))
    summary['latestExtraReviews40'] = sum(r['extraReviewRequests'] for r in latest.values()
                                          if r['group'] in ('finance', 'art'))
    summary['latestNonWebMeanKrwAt1400'] = round(sum(r['usage']['usageBasedUsd'] for r in latest.values()
        if not r['usage']['webSearchCalls']) * 1400 / sum(not r['usage']['webSearchCalls'] for r in latest.values()), 2)
    assert summary['totalCostUsd'] < 2
    report = {'summary': summary, 'latest': sorted(latest.values(), key=lambda r: r['id']), 'history': history}
    (root / 'validation-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    esc = html.escape
    parts = ['<!doctype html><meta charset="utf-8"><title>튜터 인용·대화 검증</title>',
             '<style>body{max-width:1050px;margin:40px auto;padding:20px;font:16px/1.65 system-ui;color:#243142}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}article{border-top:1px solid #ccc;padding:16px 0}summary{cursor:pointer}</style>',
             '<h1>튜터 인용·대화 검증 · 2026-10-16</h1>',
             f'<p>{len(latest)}개 질문을 수정 전후 {len(history)}회 실행했어요. 원문·그림·계산에 대조해 수동 검토했으며, 실패한 중간 결과도 보존해요.</p>',
             '<p>인용 탈락과 두 페이지 근거 연결의 기존 부분 충족 16개는 재검증에서 충족했어요. 공식 외부 원문 확보 2개는 부분 충족으로 남겨요.</p>',
             '<p>미적분·포인터에서 5개 꼬리질문, 새 주제 전환, 이전 주제 회상을 확인했어요. 중간 실행에서 조건 덮어쓰기·계산 오류·퀴즈 오독을 발견해 보완했어요. 모든 미래 대화에 같은 성능을 보장하지 않아요.</p>',
             '<details><summary>비용·호출·중간 실패·한계</summary><pre>' + esc(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre></details>']
    for row in report['latest']:
        parts += [f'<article><h2>{row["id"]} · {row["review"]["grade"]}</h2><p>{esc(row["question"])}</p>',
                  '<pre>' + esc(row['answer']) + '</pre>',
                  '<details><summary>기대 결과·인용·호출 기록</summary><pre>' + esc(json.dumps(row, ensure_ascii=False, indent=2)) + '</pre></details></article>']
    parts += ['<details><summary>수정 중 모든 실행 기록</summary><pre>' + esc(json.dumps(history, ensure_ascii=False, indent=2)) + '</pre></details>']
    (root / 'report.html').write_text('\n'.join(parts))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
