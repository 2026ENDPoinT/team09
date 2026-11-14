"""Opt-in, frozen-source A/B of hidden selection context; never edits saved results.

Five question pairs per subject = ten actual answer calls. No paid planner/judge.
UI contexts are exported through PdfWorkspace/StudySelectionActions before freezing.
"""
import argparse
import copy
import json
import random
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pdf_ai as ai
from pdf_pipeline import write_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/selection-context-live-20261017'
CAP = .30  # Deliberately below the user's $1 ceiling; all reservations included.
CONTEXT_INSTRUCTION = (' selectionContext is generated study material selected in the UI, not PDF evidence. '
                       'Use it to resolve references; verify claims against sources. Do not recite its metadata.')
# Frozen before any paid requests: actual saved concept IDs and literal selections.
# Alternate summary/concept when that literal also exists in the saved summary.
SETS = [
 ('math','미분적분학','19ad2950',[
  (13,'몫의 법칙은 분모 수열의 극한이 0이 아닐 때만 적용해요.', '분모 극한이 0이 아니어야 함'),
  (19,'조임정리에 따라 가운데 수열도 0으로 수렴해요.', '절댓값 부등식과 양쪽 극한 0; 일반적인 절댓값 극한으로 확장 금지'),
  (30,'따라서 항들은 위쪽 경계에 가까워지며 수렴해요.', '단조성과 유계성을 함께 설명; 임의 상계와 극한을 동일시하지 않음'),
  (38,'두 부분합이 같은 극한으로 가까워지면 그 차이는 0으로 가까워져요.', 'a_n=s_n-s_(n-1), 필요조건이며 역은 불성립'),
  (105,'반지름이 같아도 끝점에서 수렴하는지 발산하는지는 별도로 확인해야 해요.', '항별 미분 적분에서 반지름 유지와 끝점 별도 검사')]),
 ('physics','일반물리학','7abdf2ea',[
  (1,'따라서 알짜힘이 작용하면 운동량이 변하고, 알짜힘이 0이면 운동량은 시간에 따라 변하지 않아요.', 'F_net=dp/dt; ma는 일정 질량 조건'),
  (4,'각도 발사 식은 수평 방향의 운동량을 보존한 결과예요.', '궁수 화살 계, cos 수평성분, 반동 부호; 전체 수직보존 단정 금지'),
  (7,'따라서 같은 충격량이라도 작용 시간이 길면 평균힘의 크기는 작아져요.', 'I=Favg dt와 같은 충격량 조건'),
  (11,'마지막 식은 두 물체 사이의 상대 속도가 충돌 전후에 반대 부호로 바뀐다는 뜻이에요.', '일차원 탄성충돌 상대속도, 운동량 운동에너지 보존'),
  (18,'이 결과는 총질량', 'Ptot=M vCM; 입자 질량 가중 평균, 일정질량 조건')]),
 ('finance','금융의 이해','d0042fff',[
  (9,'또 유통시장에서 형성된 가격은 발행기업이 발행시장에서 새 증권을 판매할 때 기준이 돼요.', '발행/유통 구분 및 유동성 가격발견; 발행사 직접자금 수령과 혼동 금지'),
  (33,'계약서 작성 비용을 여러 거래에 나누어 부담하므로 거래 1달러당 비용이 낮아져요.', '대출 서류 재사용과 규모의 경제'),
  (37,'대출자는 높은 이자수익을 약속하는 차입자가 있어도 상환 위험을 감당하기 어렵다고 판단해 대출을 하지 않을 수 있어요.', '계약 전 위험 유형 숨김, 역선택과 대출거절'),
  (38,'대출자는 이 위험을 우려해 대출하지 않기로 할 수 있어요.', '계약 후 숨은 행동에 따른 상환위험; 역선택과 구별'),
  (40,'신용할당은 금융기관이 역선택과 도덕적 해이를 관리하는 방법 가운데 하나예요.', '높은 이자 지불 의사에도 대출 거절/금액 제한; 실시간 금융조언 없음')]),
 ('art','현대예술의 이해','18c30d6a',[
  (8,'회화의 요소를 최소한으로 줄이는 것은 단순한 장식이 아니라, 자연의 형태를 넘어서는 새로운 회화적 실체를 만들고 현실을 초월하려는 의지와 연결돼요.', '말레비치 절대주의의 비대상 기하학; 단순 장식 아님'),
  (12,'이 형식주의적 관점에서는 예술의 발전을 사회 변화보다 형식의 변화로 이해해요.', '데 스틸 반 뒤스부르흐 대상 단순화에서 구성균형으로 전환'),
  (17,'기능을 고려한 새로운 형태를 만드는 일이 디자인의 핵심이 됐어요.', '바우하우스 예술 기술 통합, 기능 대량생산'),
  (31,'그 관점에서 화면 전체의 균질한 작동은 회화의 평면성을 부각하는 올오버 경향과 연결돼요.', '그린버그 평면성/균질성; 폴록 드리핑과 수단 결과 구별'),
  (40,'뉴먼은 지퍼를 단순한 선이 아니라 존재를 분리하고 출현시키는 사건으로 보았어요.', '바넷 뉴먼 수직 띠, 색면과 관람자 경험; 자료 해석으로 구분')]),
 ('anatomy','사람해부학','1f8a648d',[
  (3,'빛이 들어오는 방향과 신경 신호가 향하는 방향을 함께 보여 줘요.', '망막 빛수용기와 신호 방향; 실제 그림 밖 구조를 봤다고 단정 금지'),
  (6,'시각교차에서는 양쪽 눈의 신경섬유 일부가 서로 교차해요.', '망막 시신경 시각교차 후두엽, 일부교차; 모든 섬유교차 아님'),
  (11,'귀관은 가운데귀와 인두 쪽을 연결하는 관이에요.', '중이 인두 연결; 외이도 혼동 금지'),
  (13,'이 정보는 전정 신경을 통해 전달돼요.', '평형기관 정적위치 직선가속 회전 구별, 전정신경'),
  (16,'신경 신호가 되어 중추신경계통으로 전달돼요.', '고막 귓속뼈 안뜰창 달팽이관 털세포 기계진동에서 신호 전환')]),
 ('ai','컴퓨팅사고와 인공지능','53b61260',[
  (4,'이 값은 0과 1 사이에 놓이며, 입력 점수가 커질수록 1에 가까워져요.', '시그모이드 z를 확률범위로 변환; softmax 혼동 금지'),
  (9,'확률이 작아질수록 손실은 커져요.', '정답클래스 확률 -log p, 단순 임의클래스 확률 아님'),
  (18,'이 방향은 각 파라미터의 편미분을 음수로 한 성분들로 이루어져요.', '음의 그래디언트 방향, 충분히 작은 스텝 조건; 무조건 감소 단정 금지'),
  (20,'너무 크면 최솟값을 지나쳐 반대쪽으로 이동할 수 있고, 작으면 작은 단계로 이동해요.', '학습률과 업데이트 폭/오버슈트; 반복 횟수 자체와 구별'),
  (31,'따라서 전체 함수를 한 번에 미분하지 않고도 계산 그래프를 따라 역방향으로 그래디언트를 누적할 수 있어요.', '연쇄법칙 국소 미분 곱과 분기 합; 역전파와 파라미터 업데이트 구별')]),
 ('society','오늘의 한국사회','43c5af0b',[
  (1,'이 선택들은 혜택과 부담을 누구에게 배분할지 결정하므로 정치적 갈등을 수반해요.', '공공성 범위 공급주체 재정의 선택과 분배갈등'),
  (3,'따라서 공적 지원이 있다는 사실과 시설의 운영 주체가 공공이라는 사실은 구분해야 해요.', '공적재원과 민간공급은 별도 차원'),
  (9,'제공된 행위가 늘면 그에 따라 산정되는 진료비도 늘어날 수 있어요.', '행위별 수가제 가격 곱 횟수; 과잉진료는 가능성으로'),
  (27,'보험 급여 비율도 낮게 유지됐고', '저부담 저급여 저수가 구분; 급여를 임금으로 오해 금지'),
  (34,'한 분야에 대한 회피가 누적되면 해당 진료를 받을 수 있는 기관이나 인력이 부족해질 수 있어요.', '저수가 필수의료 공급 유인; 단일 확정 인과/현재통계 단정 금지')]),
 ('nursing','보건의료와 간호 데이터','e9b05677',[
  (8,'연도별 차이를 곧바로 질병이나 의료이용의 실제 변화로 해석하지 않도록 주의해야 해요.', '청구 기준 변화 코딩 편향; 실제발생 변화와 구별'),
  (10,'이를 선택 편향이라고 해요.', '레지스트리 등록 기준과 전체대상 대표성 한계'),
  (15,'측정된 값은 관찰 자료이고, 그 값이 환자에게 어떤 임상적 의미를 갖는지는 별도로 판단해야 해요.', 'PGHD 기기 정확도 측정조건 해석 구별; 진단 지시 아님'),
  (22,'그러므로 ‘기록되지 않음’을 ‘발생하지 않음’으로 해석하면 안 돼요.', '결측 이유와 관찰 미실시/입력누락; 환자 안정 추론 금지'),
  (25,'시간축을 잘못 설정하면 변화의 순서를 오해해 간호중재의 효과를 잘못 판단할 수 있어요.', '발생 수행 입력 채취 보고 시간 구별, 중재전후 순서')]),
]

def read(p): return json.loads(p.read_text())

def prepare_ui():
    cases=[]
    for key,subject,short,items in SETS:
        folder=next((ROOT/'.synesis/pdf').glob(short+'*'))
        saved=read(folder/'generated/new-concept-v99/latest-document-0.json')
        for j,(index,literal,criteria) in enumerate(items):
            block=saved['concepts'][index]; origin='개념'
            if j%2==0:
                matches=[s for s in saved['sections'] if literal in json.dumps(s,ensure_ascii=False)]
                if matches: block=matches[0];origin='요약'
            assert literal in json.dumps(block,ensure_ascii=False), (key,index,literal)
            cases.append(dict(id=f'{key}-{j+1}',subject=subject,documentPath=str(folder/'document.json'),
                origin=origin,block=block,selectionLiteral=literal,criteria=criteria))
    path=OUT/'ui-inputs.json'
    if path.exists():assert read(path)==cases,'Do not change frozen UI inputs'
    write_json(path,cases)
    print(json.dumps({'cases':len(cases),'subjects':len(SETS)},ensure_ascii=False))

def freeze():
    rng=random.Random(20261017);cases=[]
    for c in read(OUT/'ui-contexts.json'):
        folder=Path(c['documentPath']).parent
        document=ai.load_tutor_document(folder)  # Local saved page analysis, no calls.
        context=ai.tutor_selection_context(document,c['selectionContext'])
        pages=context.get('pages',[]);assert pages,(c['id'],context)
        sources,_=ai.citation_sources(ai.model_sources([x for x in document['chunks'] if x['page'] in pages],document))
        # Reuse saved PDF figure descriptions equally in both arms, not generated study prose as evidence.
        notes=ai.load_visual_notes(folder,document,pages)
        question='['+c['selectedMarkdown']+']\n\n이 부분에 대해 상세히 설명해줘.'
        payload=dict(taskType='tutor',task=ai.TUTOR_TASK+ai.TUTOR_MODE_PROMPTS['quick'],question=question,
            topicHint='',recentConversation=[],sources=sources,visualNotes=notes,externalSearchAvailable=False,
            currentPdfPage=pages[0],documentPageCount=len(document['pages']),
            pdfEvidence=dict(status='matched' if sources or notes else 'no_matches',sourceCount=len(sources),
                             visualNoteCount=len(notes),scope='local_search',entireDocumentReviewed=False),
            webSearchState={'status':'disabled'},
            questionPlan=dict(subject=question,resolvedRequest=question,intent='explain',needsClarification=False,scope='document'))
        variants=['before','after'];rng.shuffle(variants)
        cases.append({k:c[k] for k in ('id','subject','origin','criteria','selectionLiteral')} | dict(
            documentId=document['documentId'],pages=pages,payload=payload,selectionContext=context,
            arms={chr(65+i):arm for i,arm in enumerate(variants)}))
    frozen=dict(method='Fixed original PDF excerpts and saved figure notes; real answer-generation stage only. '
                       'Same system, question, sources, model, output cap; only selectionContext + its production instruction differ. '
                       'Offline UI capture uses real renderer/controller. No paid planner, web search, judge, or answer-review calls.',
        model='gpt-6-luna',reasoningEffort='low',outputCap=ai.TUTOR_MAX_OUTPUT['quick'],system=ai.TUTOR_SYSTEM,
        contextInstruction=CONTEXT_INSTRUCTION,cases=cases,capUsd=CAP,userCeilingUsd=1,
        criteria='Compare source-backed accuracy, reference resolution, relevant completeness, unnecessary clarification, '
                 'unsupported claims; do not reward length. A single pair cannot establish statistical significance.',
        rateBasis='Existing project Provider rates, not independently verified invoice pricing.',
        rates=ai.PRICES['gpt-6-luna'])
    path=OUT/'inputs.json'
    if path.exists():assert read(path)==frozen,'Frozen paid inputs changed'
    write_json(path,frozen)
    print(json.dumps({'subjects':len(SETS),'pairs':len(cases),'calls':2*len(cases),
        'origins':{s:sum(c['origin']==s for c in cases) for s in ('요약','개념')},
        'contextChars':[len(c['selectionContext'].get('context','')) for c in cases],
        'missingEvidence':[c['id'] for c in cases if not(c['payload']['sources'] or c['payload']['visualNotes'])]},ensure_ascii=False))

def provider():
    p=ai.Provider(OUT,True,CAP)
    state=OUT/'audit-state.json'
    if state.exists():
        p.ledger_path=Path(read(state)['ledger']);p.ledger=read(p.ledger_path)
        p.spent=sum(e.get('estimatedUsd',e['reservedUsd']) if e.get('state')=='settled' else e['reservedUsd'] for e in p.ledger['requests'])
    write_json(state,{'ledger':str(p.ledger_path),'capUsd':CAP})
    return p

def generate():
    frozen=read(OUT/'inputs.json');p=provider()
    def one(job):
        c,label,arm=job;path=OUT/'answers'/f'{c["id"]}-{label}.json'
        if path.exists():return
        payload=copy.deepcopy(c['payload'])
        if arm=='after':payload['selectionContext']=c['selectionContext'];payload['task']+=frozen['contextInstruction']
        write_json(OUT/'requests'/f'{c["id"]}-{label}.json',payload)
        p.context={'kind':'selection_context_ab','case':c['id'],'arm':label,'subject':c['subject']}
        answer=p.complete(payload,max_output=frozen['outputCap'],system_prompt=frozen['system'])
        write_json(path,answer)
        print(json.dumps({'case':c['id'],'arm':label,'spentUsd':round(p.spent,6)},ensure_ascii=False),flush=True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(one,[(c,k,v) for c in frozen['cases'] for k,v in c['arms'].items()]))
    finally:write_json(OUT/'run-usage.json',ai.run_usage(p))

def export_review():
    f=read(OUT/'inputs.json');text=[]
    for c in f['cases']:
        text += [f"\n## {c['id']} {c['subject']} ({c['origin']}, p.{c['pages']})",'선택: '+c['selectionLiteral'],
                 '기준: '+c['criteria'],'문맥: '+json.dumps(c['selectionContext'],ensure_ascii=False)]
        for label in c['arms']:
            p=OUT/'answers'/f'{c["id"]}-{label}.json'
            if p.exists():text += [f'### {label}',read(p).get('answer','[missing answer]')]
        text += ['### PDF 근거',json.dumps(c['payload']['sources'],ensure_ascii=False),
                 '### PDF 그림 분석',json.dumps(c['payload']['visualNotes'],ensure_ascii=False)]
    (OUT/'blind-review.md').write_text('\n\n'.join(text))
    print('Wrote blind-review.md; evaluate manually before revealing arm mapping.')

def report():
    frozen=read(OUT/'inputs.json');manual=read(OUT/'manual-review.json')
    ledger=read(Path(read(OUT/'audit-state.json')['ledger']));usage=read(OUT/'run-usage.json')
    entries={(e['case'],e['arm']):e for e in ledger['requests']}
    assert len(entries)==len(ledger['requests'])==80
    assert usage['unknownUsageRequests']==0 and usage['usageBasedUsd']<CAP<1
    assert all(e['state']=='settled' and e['finishReason']=='stop' for e in entries.values())
    assert set(manual)=={c['id'] for c in frozen['cases']}
    rows=[];subjects=defaultdict(list);token_totals=defaultdict(Counter)
    for c in frozen['cases']:
        mapping={arm:label for label,arm in c['arms'].items()}
        before=read(OUT/'requests'/f'{c["id"]}-{mapping["before"]}.json')
        after=read(OUT/'requests'/f'{c["id"]}-{mapping["after"]}.json')
        comparison=copy.deepcopy(after);comparison.pop('selectionContext')
        comparison['task']=comparison['task'].removesuffix(frozen['contextInstruction'])
        assert comparison==before,'Source/question changes confound the A/B comparison'
        assert after['selectionContext']==c['selectionContext']
        assert len(c['selectionContext'].get('context',''))<=480
        values={arm:entries[(c['id'],label)] for arm,label in mapping.items()}
        for arm,e in values.items():
            token_totals[arm].update(input=e['usage']['prompt_tokens'],output=e['usage']['completion_tokens'],
                cached=e['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0))
        preference=manual[c['id']]['preference']
        outcome='similar' if preference=='tie' else ('improved' if c['arms'][preference]=='after' else 'regressed')
        row=dict(id=c['id'],subject=c['subject'],origin=c['origin'],title=c['selectionContext']['title'],
            pages=c['pages'],outcome=outcome,review=manual[c['id']],mapping=mapping,
            extraInputTokens=values['after']['usage']['prompt_tokens']-values['before']['usage']['prompt_tokens'],
            beforeUsage=values['before']['usage'],afterUsage=values['after']['usage'])
        rows.append(row);subjects[c['subject']].append(row)
    deltas=[r['extraInputTokens'] for r in rows];totals=Counter(r['outcome'] for r in rows)
    stats=dict(mean=statistics.mean(deltas),median=statistics.median(deltas),min=min(deltas),max=max(deltas),
        inputIncreasePercent=100*(token_totals['after']['input']/token_totals['before']['input']-1),
        outputIncreasePercent=100*(token_totals['after']['output']/token_totals['before']['output']-1),
        totalIncreasePercent=100*(sum(token_totals['after'][k] for k in ('input','output'))/
                                 sum(token_totals['before'][k] for k in ('input','output'))-1))
    result=dict(method=frozen['method'],model=frozen['model'],totalPairs=len(rows),callsPerSubject=10,
        outcomes=totals,extraInputTokens=stats,tokenTotals=token_totals,usage=usage,
        subjectResults={s:dict(pairs=len(rs),calls=2*len(rs),outcomes=Counter(r['outcome'] for r in rs),
            meanExtraInputTokens=statistics.mean(r['extraInputTokens'] for r in rs)) for s,rs in subjects.items()},
        rows=rows,limitations=[
            'Five distinct question pairs per subject, one draw per arm; not statistical proof of improvement or safety.',
            'Fixed-source answer-stage test; production retrieval/planner/page-routing and answer-review were not compared.',
            'Raw model answers were assessed manually; accuracy mistakes may occur in both arms. Similar does not mean flawless.',
            'Diagrams were not uploaded anew. Both arms got identical cached text/figure notes when available; original anatomy pages 5–7 were locally rendered for manual checking.',
            'Cost is calculated from actual API usage and project-configured rates/cache pricing, not independently verified invoice pricing.',
            'Output token changes include sampling and answer-length variation; only input delta is exactly attributable to the added metadata/instruction.',
            'Subjects are eight local material areas; nursing data is the available local sample, not a claim about every course or every saved PDF.'])
    write_json(OUT/'report.json',result)
    lines=['# 선택 문맥 전후 실제 모델 비교 — 2026-10-17',
        f"8개 과목 영역 × 5개 질문 × 전후 2회 = 실제 답변 80회, 40쌍을 비교했어요. 결과는 개선 {totals['improved']}쌍, 비슷함 {totals['similar']}쌍, 후퇴 {totals['regressed']}쌍이에요.",
        '각 과목의 서로 다른 질문 5개를 양쪽에 한 번씩 보냈어요. 개선은 대체로 크지 않았고, 두 방식 모두 잘 설명하는 경우가 많았어요. 단일 생성에서 나온 오류 차이를 문맥의 인과적 효과로 단정하지 않아요.',
        '## 방법',
        '실제 저장된 v99 결과의 요약 24개·개념 16개에서 선택 영역을 정했어요. PdfWorkspace와 StudySelectionActions를 통해 제목·PDF 페이지·인접 문맥을 오프라인으로 추출했어요. 선택 문장은 사용자에게 보이는 그대로 유지했어요.',
        '동일한 PDF 원문/저장된 그림 분석, 질문, 시스템 프롬프트, gpt-6-luna(low), 출력 상한 8,000을 사용했어요. 바뀐 것은 selectionContext와 그것을 설명하는 기존 운영 지침 한 문장뿐이에요. 전후 요청을 직접 대조해 나머지 필드가 모두 같은지 확인했어요.',
        '계획·검색·재검토·별도 채점 모델은 호출하지 않았어요. 비교 답변의 A/B 표시는 고정 시드로 섞었고, 버전 매핑을 보기 전에 수동으로 선호와 근거를 기록했어요. 이 실험은 답변 생성 단계의 효과를 분리하며, 원문 위치가 검색 경로를 개선하는 효과는 포함하지 않아요.',
        '## 과목별 결과',
        '| 자료 영역 | 실제 호출 | 개선 | 비슷함 | 후퇴 | 평균 추가 입력 토큰 |',
        '|---|---:|---:|---:|---:|---:|']
    for subject,rs in subjects.items():
        counts=Counter(r['outcome'] for r in rs)
        lines.append(f"| {subject} | 10 | {counts['improved']} | {counts['similar']} | {counts['regressed']} | {statistics.mean(r['extraInputTokens'] for r in rs):.1f} |")
    lines += ['## 토큰과 비용',
        f"입력은 평균 **+{stats['mean']:.2f}토큰(+{stats['inputIncreasePercent']:.2f}%)**, 중앙값 +{stats['median']}토큰, 범위 +{stats['min']}~{stats['max']}토큰이에요. 전 40회 합계 {token_totals['before']['input']:,} → 후 40회 합계 {token_totals['after']['input']:,}토큰이에요. 지침·항목 제목·원문 위치의 직렬화 비용까지 포함해요.",
        f"출력은 {token_totals['before']['output']:,} → {token_totals['after']['output']:,}토큰(+{stats['outputIncreasePercent']:.2f}%)이고 입력+출력 전체는 +{stats['totalIncreasePercent']:.2f}%예요. 출력 길이는 샘플링에 따라 달라지므로 전부 문맥의 고정 비용으로 해석하면 안 돼요. 운영 출력 상한은 바꾸지 않았어요.",
        f"80회 API 사용량은 입력 {usage['inputTokens']:,}(캐시 {usage['cachedInputTokens']:,}), 출력 {usage['outputTokens']:,}토큰이에요. 프로젝트 단가로 계산한 비용은 **${usage['usageBasedUsd']:.8f}**예요. 내부 상한 $0.30, 사용자 상한 $1을 지켰고 불명확한 비용·자동 재시도·추가 채점 호출은 없었어요. 80회 모두 정상 종료(stop)했어요. 실제 청구서를 별도로 조회한 금액은 아니에요.",
        '토큰 비교는 API의 prompt_tokens/completion_tokens 및 cached_tokens 기록을 사용했어요. 필드 의미는 [OpenAI Docs](https://developers.openai.com/cookbook/examples/prompt_caching101)를 참고했어요.',
        '## 차이가 있었던 답변']
    for row in rows:
        if row['outcome']=='similar':continue
        c=next(c for c in frozen['cases'] if c['id']==row['id'])
        lines += [f"### {row['id']} — {'개선' if row['outcome']=='improved' else '후퇴'}: {row['title']}",
            f"선택: {c['selectionLiteral']}",row['review']['reason'],
            'A/B 매핑: '+json.dumps(c['arms'],ensure_ascii=False),
            ' / '.join(f"[{arm} 답변]({OUT/'answers'/f'{row['id']}-{label}.json'})" for arm,label in row['mapping'].items())]
    lines += ['## 해석과 남은 문제',
        '문맥은 선택한 항목의 기호와 설명을 연결하는 데 도움이 되는 사례가 있었어요. 역전파에서는 추상적인 연쇄법칙 예시 대신 현재 항목의 W·b·z 식으로 연결됐어요. 알짜힘 설명에서는 0일 때 운동량이 유지된다는 조건까지 더 충실히 설명했어요.',
        '다만 수학에서는 절댓값 수렴 정리의 역도 참인데 후 답변이 역을 사용할 수 없다고 잘못 말했고, 사회 자료에서는 보험 급여 비율의 기준을 의료비가 아닌 납부 보험료처럼 표현한 후 답변이 나왔어요. 문맥이 사실 검증을 보장하지 않으며 두 사례의 원인을 문맥 하나로 확정할 수는 없어요.',
        '비슷함으로 분류한 34쌍도 모두 무결하다는 뜻은 아니에요. 단조수열 일반 정리 대신 같은 페이지의 특정 점화수열로 좁혀 답하는 문제, 금융 답변에서 대출자/차입자 용어를 혼용하는 문제는 양쪽에서 관찰됐어요.',
        '추가 호출 없이 보완할 후보는 선택 자료와 PDF 근거의 구분을 유지하면서 인접 예제로의 범위 이탈을 줄이고, 생성 문맥 안의 ‘쉬운 설명 보기’ 같은 UI 문구를 제외하는 것이에요. 이번에는 비교 조건을 유지하기 위해 제품 프롬프트·기능을 추가 변경하지 않았어요.',
        '## 범위의 한계']
    lines += ['- '+item for item in result['limitations']]
    lines += ['## 전체 기록',
        f"[40쌍 전체 답변·PDF 근거]({OUT/'blind-review.md'}) · [질문·평가 기준·입력]({OUT/'inputs.json'}) · [쌍별 판정·토큰]({OUT/'report.json'}) · [사용량]({OUT/'run-usage.json'})"]
    (OUT/'report.md').write_text('\n\n'.join(lines).replace('|\n\n|','|\n|'))
    print(json.dumps(dict(pairs=len(rows),outcomes=totals,extraInputTokens=stats,costUsd=usage['usageBasedUsd']),ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare-ui','freeze','generate','export-review','report'])
    globals()[parser.parse_args().action.replace('-','_')]()
