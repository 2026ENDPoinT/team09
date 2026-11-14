"""Run a bounded learner conversation against real library PDFs; preserve every turn."""
import argparse
import json
import time
from pathlib import Path
from pdf_ai import Provider, tutor, run_usage
from pdf_pipeline import write_json

FINANCE = [
 ('concept',2,'2페이지에서 금융시장이 경제의 효율성을 높인다는 게 무슨 뜻이야? 스티브와 칼의 예로 쉽게 설명해줘.'),
 ('concept',3,'직접금융과 간접금융을 돈이 이동하는 경로 중심으로 설명해줘.'),
 ('concept',7,'유로본드와 외국채가 헷갈려. 이 자료의 예로 차이를 설명해줘.'),
 ('concept',9,'역선택과 도덕적 해이를 돈을 빌리는 시점을 기준으로 설명해줘.'),
 ('verification',2,'2페이지 예시에서 칼의 추가 소득이 200달러고 이자가 100달러니까, 순소득은 100달러 맞지? 스티브 몫까지 더하면 새로 생긴 소득은 300달러야? 원문과 계산으로 확인해줘.'),
 ('verification',5,'5페이지 설명대로라면 주식은 만기가 없으니까 단기금융시장에 속한다고 봐도 돼? 이 PDF 기준으로 판단해줘.'),
 ('verification',4,'주식 보유자는 채권자보다 먼저 돈을 받는 사람이어서 잔여청구권자라는 거지? 4페이지와 대조해서 맞는지 봐줘.'),
 ('verification',7,'영국 런던에서 파는 달러 표시 채권은 유로화 표시가 아니니까 유로본드가 아닌 거 아니야? 7페이지 정의에 적용해줘.'),
 ('followup',9,'9페이지 역선택으로 돌아가자. 돈을 잘 갚겠다고 높은 이자를 약속하는 사람에게도 은행이 대출을 거절하는 이유는 뭐야?'),
 ('followup',9,'그럼 이자율을 더 올려 받으면 그 위험을 보상할 수 있지 않아?'),
 ('followup',9,'돈을 빌리기 전부터 숨겨진 정보 때문에 문제가 생긴다는 거네?'),
 ('followup',9,'빌린 뒤에 원래 하려던 안전한 사업 대신 도박을 한다면 그건 앞의 경우와 뭐가 달라?'),
 ('followup',9,'둘 다 은행이 상대를 잘 몰라서 생기는 건데 왜 이름을 따로 붙이는 거야?'),
 ('followup',9,'은행은 앞의 문제에는 심사를, 뒤의 문제에는 감시를 하는 거라고 정리하면 돼?'),
 ('followup',10,'이제 10페이지로 넘겼어. 여기 경영자가 주주 돈으로 자기 편의만 챙기는 것도 방금 말한 뒤의 문제에 해당해?'),
 ('followup',10,'그럼 스톡옵션을 주면 그 문제가 완전히 없어지는 거야? 이 페이지에 나온 한계까지 같이 말해줘.'),
 ('other',10,'지금 공부한 역선택과 도덕적 해이로 OX 문제 두 개만 내줘. 답은 맨 아래 따로 적어줘.'),
 ('other',10,'이 PDF는 총 몇 페이지야?'),
 ('other',10,'주인-대리인 문제를 PDF에 없는 동아리 회장 사례로 설명해줘. 실제 사건 말고 네가 만든 예시로.'),
 ('other',10,'시험 직전이라 시간이 없어. 이 자료에서 서로 혼동하기 쉬운 구분 세 쌍만 골라 한 줄씩 정리해줘.'),
]
ART = [
 ('concept',8,'8페이지의 다다이즘은 어떤 운동이야? 전쟁과 연결해서 쉽게 설명해줘.'),
 ('concept',9,'위고 발의 음성시는 보통 시와 어떻게 달라? 9페이지 기준으로 알려줘.'),
 ('concept',27,'27페이지 레디메이드는 그냥 기성품이랑 뭐가 달라?'),
 ('concept',22,'22페이지 솔라리제이션이 뭔지, 사진에서 어떤 효과를 내려는 건지 설명해줘.'),
 ('verification',10,'10페이지 우연에 따른 구성은 작가가 아무 선택도 하지 않고 모든 걸 완전히 무작위에 맡겼다는 뜻이야? 원문의 제작 절차로 확인해줘.'),
 ('verification',21,'21페이지 만 레이의 선물은 다리미를 더 편리하게 쓰도록 개량한 작품이 맞아? 원문과 반대되는 부분이 있으면 짚어줘.'),
 ('verification',27,'27페이지 샘은 뒤샹이 직접 소변기를 조각해서 만든 작품이라고 외워도 돼? 자료에 근거해서 판단해줘.'),
 ('verification',31,'31페이지 큰 유리는 마지막에 신부와 독신자들의 욕망이 충족되는 구조를 보여주는 거지? 이 페이지 설명이랑 비교해줘.'),
 ('followup',21,'다시 21페이지 선물 얘기로 돌아가자. 익숙한 다리미를 못 쓰게 만들어서 뭘 보여주려는 거야?'),
 ('followup',21,'의의는뭐지?'),
 ('followup',21,'그럼 실제로 쓸 수 없어졌다는 점 자체가 작품의 핵심인 거네?'),
 ('followup',21,'제목도 왜 하필 선물이야? 앞에서 말한 의미와 이어서 설명해줘.'),
 ('followup',21,'비슷한 원리로, 이 PDF에는 없는 가상의 작품을 하나만 예로 들어줘.'),
 ('followup',21,'그렇게 원래 기능을 바꿔 놓으면 전부 레디메이드라고 불러도 돼?'),
 ('followup',27,'이제 27페이지 샘으로 넘겼어. 이쪽은 방금 다리미 작품과 어떤 점이 같고 달라?'),
 ('followup',27,'그럼 작가가 직접 물건을 만들지 않아도 선택하고 제시한 행위 때문에 작품이 될 수 있다는 거야?'),
 ('other',27,'이 PDF 전체는 몇 페이지야?'),
 ('other',27,'다다이즘과 레디메이드 내용을 확인할 OX 문제 두 개만 내줘. 정답은 마지막에 따로.'),
 ('other',27,'이 자료 공부할 때 다다이즘을 꼭 이해해야 해? 작품 이름만 외우면 부족한 이유를 설명해줘.'),
 ('other',21,'만 레이의 선물 작품을 공식 미술관 자료로 외부 검색해서 확인해줘. 작가의 출생이 아니라 지금 이야기한 다리미 작품이 대상이야.'),
]
IDS = {'finance':'d0042fffa2b446780854f493bdbcf2c50713b815810c29b0169b03b9f910c2c5',
       'art':'57ebaa9745f02a68d662f6d84ea19768139c85a725b751b7ab7c9d779275f09f'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('document',choices=IDS)
    parser.add_argument('--max-usd',type=float,default=.2)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    folder=root/'.synesis/pdf'/IDS[args.document]
    output=root/'build/tutor-quality-20261015'/args.document
    output.mkdir(parents=True,exist_ok=True)
    document=json.loads((folder/'document.json').read_text())
    document['_studyStrategy']='new-concept-v99'
    # Use the app's actual evidence/visual caches, but isolate QA history/charges.
    provider=Provider(output,True,args.max_usd)
    provider.context={'kind':'tutor_quality_audit','documentId':document['documentId']}
    results_path=output/'conversation.json'
    saved=json.loads(results_path.read_text()) if results_path.exists() else []
    memory=saved[-1]['result']['memory'] if saved else None
    questions=FINANCE if args.document=='finance' else ART
    prior=sum(entry.get('estimatedUsd',entry.get('reservedUsd',0))
              for path in (output/'usage').glob('*.json') if path!=provider.ledger_path
              for entry in json.loads(path.read_text()).get('requests',[]))
    provider.max_usd=max(.0001,args.max_usd-prior)
    for i,(category,page,question) in enumerate(questions):
        if i<len(saved):continue
        started=time.monotonic();before=len(provider.ledger['requests'])
        result=tutor(document,question,provider,memory=memory,folder=folder,
                     current_page=page,mode='deep',web_fallback=True)
        memory=result.get('memory',memory)
        entries=provider.ledger['requests'][before:]
        item={'number':i+1,'category':category,'page':page,'question':question,
              'elapsedSeconds':round(time.monotonic()-started,2),
              'costUsd':round(sum(e.get('estimatedUsd',0) for e in entries),8),
              'webCalls':sum(e.get('webSearchCalls',0) for e in entries),
              'requests':len(entries),'result':result}
        saved.append(item);write_json(results_path,saved)
        print(json.dumps({k:v for k,v in item.items() if k!='result'}|{
            'kind':result['kind'],'answer':result.get('answer',''),
            'pages':[e.get('page') for e in result.get('evidence',[])],
            'webSources':result.get('webSources',[])},ensure_ascii=False),flush=True)
    write_json(output/'run-usage.json',run_usage(provider))
    print(json.dumps({'document':args.document,'usage':run_usage(provider)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
