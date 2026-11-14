"""Bounded audit recheck using saved pre-question conversation and real library PDFs."""
import argparse
import copy
import json
import time
from pathlib import Path

from audit_pdf_tutor_quality import IDS
from pdf_ai import Provider, tutor, run_usage
from pdf_pipeline import write_json

# Each variant uses the original question's preceding context, never its own answer.
VARIANTS = [
    ('finance', 7, '지분을 가진 사람이 채권을 가진 사람보다 우선 변제받는 거 맞죠? 자료 정의로 판단해줘.'),
    ('finance', 7, '주주는 채권자에게 지급하고 남은 몫을 받는다고 이해했어. 이게 잔여청구권이라는 뜻이지?'),
    ('finance', 7, '칼의 순소득은 100달러고 스티브 이자도 100달러니까, 둘의 소득 증가분은 총 200달러 맞아?'),
    ('finance', 18, '열려 있는 문서의 쪽수를 알려줘.'),
    ('finance', 18, 'How many pages does this PDF have?'),
    ('finance', 18, '지금 펼친 파일 끝까지 장수가 어떻게 되지?'),
    ('art', 17, '전체 쪽수가 얼마인지 알려줘.'),
    ('art', 17, 'What is the page count of this document?'),
    ('finance', 19, '이 자료의 주인과 대리인 관계를 학교 축제 준비 상황으로 바꿔서 설명해줘. 인물과 상황은 지어내도 돼.'),
    ('finance', 19, '이번에는 PDF 속 사례를 반복하지 말고, 역할이 드러나는 짧은 상황극을 만들어줘.'),
    ('art', 13, '이 자료에서 다룬 원리를 일상 물건 하나에 적용해 새로운 가상 작품을 제안해줘.'),
    ('art', 13, '같은 아이디어를 보여주는 장난감 작품을 네가 하나 지어내면 어떤 모습일까?'),
    ('art', 19, '다다이즘은 시험용으로 작품명만 외워도 충분하지 않아? 공부에 왜 도움이 되는지 말해줘.'),
    ('art', 19, '이 수업에서 다다이즘의 배경까지 이해하는 게 작품 감상에 어떤 도움이 돼?'),
    ('finance', 19, '주인-대리인 문제를 배워 두면 조직에서 벌어지는 일을 이해하는 데 도움이 돼?'),
    ('finance', 7, '주식은 만기가 없으므로 단기금융상품이라는 결론이 맞는지 원문으로 확인해줘.'),
    ('art', 13, '가상 예시 말고 이 PDF 안에 실제로 제시된 선물 작품의 제작 방식을 확인해줘.'),
    ('art', 17, '이 PDF는 몇 페이지고, 다다이즘이 시작되는 페이지는 어디야?'),
]


class AuditProvider(Provider):
    def complete(self, payload, **kwargs):
        value = super().complete(payload, **kwargs)
        self.observed.append({'operation': payload.get('operation', 'answer'),
                              'plan': payload.get('questionPlan'), 'value': copy.deepcopy(value)})
        return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-usd', type=float, default=.25)
    parser.add_argument('--run', default='v1')
    parser.add_argument('--only', help='Comma-separated case numbers for a targeted recheck')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = root / 'build/tutor-recheck-20261015' / args.run
    output.mkdir(parents=True, exist_ok=True)
    originals = {d: json.loads((root/f'build/tutor-quality-20261015/{d}/conversation.json').read_text()) for d in IDS}
    documents = {d: json.loads((root/'.synesis/pdf'/key/'document.json').read_text()) for d, key in IDS.items()}
    cases = [(d, n, originals[d][n-1]['question'], True)
             for d, numbers in [('finance', [7, 18, 19]), ('art', [13, 17, 19])] for n in numbers]
    cases += [(d, n, q, False) for d, n, q in VARIANTS]
    path = output/'conversation.json'
    saved = json.loads(path.read_text()) if path.exists() else []
    prior = sum(e.get('estimatedUsd', e.get('reservedUsd', 0))
                for p in (output/'usage').glob('*.json')
                for e in json.loads(p.read_text()).get('requests', []))
    provider = AuditProvider(output, True, max(.0001, args.max_usd-prior))
    provider.context = {'kind': 'tutor_quality_recheck'}
    for i, (d, n, q, original) in enumerate(cases):
        if args.only and i+1 not in {int(v) for v in args.only.split(',')}:
            continue
        if any(row['number'] == i+1 for row in saved):
            continue
        provider.observed = []
        old = originals[d]
        memory = copy.deepcopy(old[n-2]['result']['memory']) if n > 1 else None
        if memory:
            for turn in memory.get('turns', []):
                turn['timestampMs'] = int(time.time()*1000)-1000
        started = time.monotonic()
        before = len(provider.ledger['requests'])
        result = tutor(documents[d], q, provider, memory=memory,
                       folder=root/'.synesis/pdf'/IDS[d], current_page=old[n-1]['page'],
                       mode='deep', web_fallback=True)
        entries = provider.ledger['requests'][before:]
        row = {'number': i+1, 'document': d, 'baselineNumber': n, 'originalQuestion': original,
               'question': q, 'elapsedSeconds': round(time.monotonic()-started, 2),
               'costUsd': round(sum(e.get('estimatedUsd', 0) for e in entries), 8),
               'requests': len(entries), 'webCalls': sum(e.get('webSearchCalls', 0) for e in entries),
               'observed': provider.observed, 'result': result}
        saved.append(row)
        write_json(path, saved)
        write_json(output/'run-usage.json', run_usage(provider))
        print(json.dumps({k: v for k, v in row.items() if k not in ('observed', 'result')} |
                         {'kind': result['kind'], 'answer': result.get('answer')}, ensure_ascii=False), flush=True)
    print(json.dumps(run_usage(provider), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
