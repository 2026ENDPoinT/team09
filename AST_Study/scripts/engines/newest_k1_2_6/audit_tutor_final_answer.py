"""Check missing-PDF and single-final-answer behavior with bounded real model calls."""
import copy
import argparse
import json
import time
from pathlib import Path

from audit_pdf_tutor_quality import IDS
from pdf_ai import Provider, tutor, run_usage
from pdf_pipeline import write_json


class AuditProvider(Provider):
    simulate_unavailable = False
    def complete(self, payload, **kwargs):
        value = super().complete(payload, **kwargs)
        self.observed.append({'operation': payload.get('operation', 'answer'),
                              'pdfEvidence': payload.get('pdfEvidence'),
                              'webSearchState': payload.get('webSearchState'),
                              'value': copy.deepcopy(value)})
        return value
    def web_search(self, *args, **kwargs):
        self.searches += 1
        if self.simulate_unavailable:
            raise RuntimeError('QA simulated unavailable search')
        return super().web_search(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run')
    parser.add_argument('--only')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    folder = root/'.synesis/pdf'/IDS['finance']
    document = json.loads((folder/'document.json').read_text())
    output = root/'build/tutor-final-answer-20261015'
    if args.run:
        output = output/args.run
    output.mkdir(parents=True, exist_ok=True)
    provider = AuditProvider(output, True, .12)
    provider.context = {'kind': 'tutor_final_answer_audit'}
    cases = [
        ('required_missing', '이 PDF에서 다룬 양자 얽힘 실험의 측정 온도는 몇 켈빈이야?'),
        ('illustration', '주인-대리인 문제를 PDF에 없는 동아리 회장 사례로 설명해줘. 실제 사건 말고 네가 만든 예시로.'),
        ('learning_reason', '이 자료 공부할 때 주인-대리인 문제를 꼭 이해해야 해? 용어만 외우면 부족한 이유가 뭐야?'),
        ('ambiguous_live_fact', '환율이 얼마야 지금?'),
        ('local_metadata', '이 PDF는 총 몇 페이지야?'),
        ('disabled_search', '외부 검색하지 말고 오늘 달러-원화 환율이 얼마인지 알려줘.'),
        ('general_without_evidence', '집중이 잘 안돼. 30분 정도 공부하고 쉬는 계획을 짜줄래?'),
        ('simulated_search_failure', '서울의 오늘 기온을 외부 검색해서 확인해줘.'),
    ]
    saved = []
    for category, question in cases:
        if args.only and category not in args.only.split(','):
            continue
        provider.simulate_unavailable = category == 'simulated_search_failure'
        provider.observed, provider.searches = [], 0
        shown = []
        before = len(provider.ledger['requests'])
        result = tutor(document, question, provider, folder=folder, current_page=10,
                       progress=shown.append, mode='quick')
        entries = provider.ledger['requests'][before:]
        row = {'category': category, 'question': question, 'result': result,
               'observed': provider.observed, 'displayedAnswers': shown,
               'searchAttempts': provider.searches,
               'costUsd': round(sum(e.get('estimatedUsd', 0) for e in entries), 8),
               'requests': len(entries)}
        saved.append(row)
        write_json(output/'conversation.json', saved)
        write_json(output/'run-usage.json', run_usage(provider))
        print(json.dumps({k: v for k, v in row.items() if k not in ('result', 'observed')} |
                         {'answer': result['answer']}, ensure_ascii=False), flush=True)
    print(json.dumps(run_usage(provider), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
