"""Small bounded same-request generation probe for course-independent flow selection."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import copy, json, sys, time
import pdf_ai
import pdf_new_concept_ver99_study as study
from pdf_study_cache_reuse import constrained_format

CASES=[
 ('signal-process',True,'신호 전달 과정: 감지 단계는 외부 자극을 전기 신호로 변환한다. 감지 결과인 전기 신호를 증폭 단계의 입력으로 사용한다. 증폭 결과가 표시 단계로 전달되어 사용자가 읽을 수 있는 표시로 변환된다.'),
 ('manufacturing-process',True,'성형 공정: 가열로 원료를 액상으로 변환한다. 가열 결과인 액상 원료를 주형에 주입한다. 주입 결과를 냉각하면 주형의 모양을 가진 고체 제품으로 변환된다. 순서를 바꾸면 주형 모양의 제품을 얻을 수 없다.'),
 ('nominal-causal',True,'원인과 결과의 연쇄: 비타민 A 부족으로 인해 레티닌 생성이 감소한다. 레티닌 생성 감소 때문에 로돕신 재생이 감소한다. 로돕신 재생 감소로 인해 어두운 곳에서의 시각이 저하된다.'),
 ('feedback-cycle',True,'제어 주기: 측정에서 얻은 현재 상태를 오차 계산의 입력으로 사용한다. 오차 계산의 결과를 조절 입력으로 전달한다. 조절로 인해 실제 상태가 바뀌고, 조절 후 상태를 다시 측정한다. 측정, 오차 계산, 조절이 반복되는 닫힌 순환이다.'),
 ('data-procedure',True,'자료 처리 절차: 수집 결과인 원자료를 정제의 입력으로 사용한다. 정제를 완료한 후 정제 결과를 집계 입력으로 전달한다. 집계 결과를 보고서 작성의 입력으로 사용해 최종 보고서를 만든다. 수집, 정제, 집계, 보고서 작성은 앞 단계 결과를 다음 단계가 사용한다.'),
 ('parallel-types',False,'자료의 유형은 수치형, 범주형, 텍스트형이다. 수치형은 수량을, 범주형은 종류를, 텍스트형은 자유로운 문장을 표현한다. 세 유형은 서로 다른 자료의 종류이며 같은 자료가 세 유형을 차례로 통과하는 과정이 아니다.'),
 ('parallel-principles',False,'좋은 요청의 다섯 원칙: 1. 간단하고 명확하게 쓴다. 2. 구체적인 행동 동사를 쓴다. 3. 필요한 맥락을 준다. 4. 원하는 출력 형식을 정한다. 5. 금지사항만 나열하기보다 원하는 행동을 직접 말한다. 이 원칙들은 병렬적인 작성 기준이다.'),
 ('maturity-levels',False,'상호운용성의 네 수준: 물리적 수준은 시스템 간 연결과 전송, 구조적 수준은 데이터 형식과 구문, 의미적 수준은 데이터 뜻의 공통 이해, 조직적 수준은 정책과 책임의 일치를 뜻한다. 연결 → 구조 → 의미 → 조직적 활용로 확장되는 성숙도 위계이며 실행할 때 차례로 수행하는 절차는 아니다.'),
 ('spatial-layers',False,'그림의 공간적 층위: 위쪽에는 소수의 선구자, 가운데에는 변화하는 집단, 아래쪽에는 다수의 대중이 배치된다. 위·중간·아래는 같은 시점에 존재하는 공간적 구분으로, 시간에 따라 한 사람이 차례로 이동하는 과정은 아니다.'),
 ('chronology',False,'발전 연대: 1980년에는 첫 문서 표준이 발표되었다. 1995년에는 다른 조직이 메시지 표준을 발표했다. 2010년에는 새로운 교환 규격이 발표되었다. 이는 서로 다른 발표 사건을 정리한 연대표다.'),
 ('true-two-stage',False,'동적 이차원 배열 해제는 두 작업 사이 순서가 중요하다. 먼저 각 행 배열을 delete[]로 해제한다. 행 해제를 완료한 후 바깥 포인터 배열을 delete[]로 해제한다. 바깥 배열을 먼저 지우면 각 행을 가리키는 포인터를 잃는다. 실제 단계는 이 두 개뿐이다.'),
 ('parallel-mappings',False,'연구 자료별 정보와 주의: 설문자료는 개인의 응답을 제공하며 응답 편향을 고려한다. 행정자료는 제도 운영 기록을 제공하며 집계 단위를 확인한다. 면담자료는 구체적인 경험을 제공하며 일반화 범위를 제한한다. 이들은 서로 다른 자료와 유의점의 대응표이며 자료원이 차례로 바뀌는 과정은 아니다.')]


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    # The previous $2 window includes $1.823236565 committed, with uncertain
    # reservations and cache-write surcharge retained. This run can add <=.02.
    prior=json.loads(Path('build/pdf-speed-20261021/report.json').read_text())['budget']['currentBudgetWindow']['committedWithKnownCacheWriteUsd']
    assert prior+.02<2
    provider=pdf_ai.Provider(out,True,.02,model='gpt-6-luna')
    started=time.monotonic()
    batches=[CASES[i:i+3] for i in range(0,len(CASES),3)]
    def work(pair):
        n,batch=pair
        blocks=[{'id':name,'page':i+1,'kind':'text','text':text,'bbox':[0,0,1,1],
                 'hasVisual':False,'visualOnly':False,'planRole':'teaching'} for i,(name,_,text) in enumerate(batch)]
        job={'id':f'probe{n}','title':'독립된 학습 항목','blocks':blocks}
        doc={'documentId':f'step-flow-probe-{n}','pages':[{'number':i+1,'label':str(i+1),'nativeText':text}
               for i,(_,_,text) in enumerate(batch)]}
        provider.context={'kind':'region_study','audit':'step_flow_admission','probeBatch':n,'reasoningEffort':'none'}
        raw=provider.complete(study.teaching_payload(job,[],{},[]),max_output=6500,
              system_prompt=study.STUDY_PROMPT,response_format=constrained_format(study.STUDY_FORMAT,job),
              cache_stable_prefix=True)
        result=study.validate(raw,job,doc)
        (out/f'batch-{n}-validated.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        rows=[]
        for name,expected,_ in batch:
            cards=[part for part in result['summary']['parts'] if part.get('stepFlow')
                   and any(e.get('sourceId')==name for e in part.get('evidence',[]))]
            draft=[seq for seq in raw.get('sequences',[]) if any(name in step.get('blockIds',[]) for step in seq.get('steps',[]))]
            rows.append({'id':name,'expectedCard':expected,'actualCard':bool(cards),'rawSequences':len(draft),
                         'passed':expected==bool(cards),'titles':[p['stepFlow']['title'] for p in cards],
                         'rawStepCounts':[len(seq.get('steps',[])) for seq in draft]})
        return rows
    error=None;rows=[]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for row in pool.map(work,enumerate(batches)):rows.extend(row)
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
    usage=pdf_ai.run_usage(provider)
    record={'cases':rows,'passed':not error and all(row['passed'] for row in rows) and len(rows)==len(CASES),
            'seconds':round(time.monotonic()-started,3),'usage':usage,'error':error,
            'newCapUsd':.02,'previousWindowCommittedUsd':prior,
            'windowMaxWithThisRunUsd':prior+.02,'productionExtraReviewCalls':0,
            'method':'Full production teaching prompt/schema and normal validation; four batches of three deliberately constructed source snippets, no independent model judge.',
            'note':'Selection probe, not a whole-document quality/cost benchmark.'}
    (out/'generation-probe.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(json.dumps(record,ensure_ascii=False))
    return record

if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'build/pdf-step-flow-20261021/generation-probe')
