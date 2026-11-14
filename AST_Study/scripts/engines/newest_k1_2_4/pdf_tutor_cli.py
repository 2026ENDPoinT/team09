"""Headless developer client for the SAME PDF tutor used by the desktop UI."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from synesis_paths import data_root, io_path
from pathlib import Path
import sys
import time
import uuid

from pdf_ai import (AiResponseError, BudgetExceeded, Provider, RemoteDisabled,
                    TUTOR_INPUT_BOUND, load_tutor_document, run_tutor_request)
from pdf_pipeline import write_json

ROOT = Path(__file__).resolve().parent.parent


def library_items(library):
    items = []
    for folder in sorted(library.iterdir() if library.is_dir() else []):
        if not (folder / 'document.json').is_file():
            continue
        # Read the saved library title, not the potentially huge PDF index.
        props = folder / 'library.properties'
        title = folder.name
        if props.is_file():
            for line in props.read_text(encoding='utf-8').splitlines():
                if line.startswith(('title=', 'name=')):
                    title = re.sub(r'\\u([0-9a-fA-F]{4})',
                                   lambda m: chr(int(m[1], 16)), line.split('=', 1)[1])
                    break
        items.append({'id': folder.name, 'title': title, 'folder': str(folder.resolve())})
    return items


def usage_delta(provider, start):
    entries = provider.ledger['requests'][start:] if provider else []
    settled = [entry for entry in entries if entry.get('state') == 'settled']
    unknown = [entry for entry in entries if entry.get('state') != 'settled']
    return {'requests': len(entries),
            'usageBasedUsd': round(sum(entry.get('estimatedUsd', 0) for entry in settled), 8),
            'webSearchCalls': sum(entry.get('webSearchCalls', 0) for entry in settled),
            'unknownUsageRequests': len(unknown),
            'uncertainReservedUsd': round(sum(entry.get('reservedUsd', 0) for entry in unknown), 8)}


class Session:
    def __init__(self, folder, output, provider=None, resume=False):
        self.folder, self.output, self.provider = folder.resolve(), output.resolve(), provider
        self.document = load_tutor_document(self.folder)
        self.path = self.output / 'session.json'
        if self.path.exists() and not resume:
            raise ValueError('기존 세션은 --resume으로 이어가거나 새 --output 경로를 사용해 주세요.')
        self.state = {'documentId': self.document['documentId'], 'folder': str(self.folder),
                      'page': 1, 'memory': None, 'turns': [], 'budgetUsedUsd': 0}
        if resume:
            if not self.path.is_file():
                raise ValueError('이어갈 session.json이 없어요.')
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            if (self.state.get('documentId') != self.document['documentId'] or
                    self.state.get('folder') != str(self.folder)):
                raise ValueError('다른 PDF의 세션은 이어갈 수 없어요.')
        if provider:
            # The CLI cap is for the WHOLE session, including uncertain paid
            # attempts from interrupted runs; cached responses add no entries.
            prior = 0.0
            for path in (output / 'usage').glob('*.json'):
                if path == provider.ledger_path:
                    continue
                for entry in json.loads(path.read_text(encoding='utf-8')).get('requests', []):
                    prior += (entry.get('estimatedUsd', 0) if entry.get('state') == 'settled'
                              else entry.get('reservedUsd', 0))
            if prior >= provider.max_usd:
                raise BudgetExceeded('이 세션의 총 예산을 이미 사용했어요.')
            provider.max_usd -= prior
            self.prior_usd = prior
        else:
            self.prior_usd = self.state.get('budgetUsedUsd', 0)

    def set_page(self, page):
        if type(page) is not int or not 1 <= page <= len(self.document['pages']):
            raise ValueError(f"페이지는 1~{len(self.document['pages'])} 범위여야 해요.")
        self.state['page'] = page

    def ask(self, question, *, page=None, mode='quick', web=True, attachments=None,
            strategy='new-concept-v99'):
        if page is not None:
            self.set_page(page)
        request = {'question': question, 'page': self.state['page'], 'mode': mode,
                   'memory': self.state['memory'], 'webFallback': web, 'strategy': strategy}
        if attachments:
            request['attachmentPaths'] = attachments
        start = len(self.provider.ledger['requests']) if self.provider else 0
        started = time.monotonic()
        # Persist intent before calls so a failed/uncertain attempt is inspectable.
        attempt = self.output / 'requests' / (uuid.uuid4().hex + '.json')
        write_json(attempt, request)
        try:
            result = run_tutor_request(self.folder, self.document, request, self.provider)
        except Exception as error:
            write_json(attempt.with_suffix('.error.json'),
                       {'type': type(error).__name__, 'usage': usage_delta(self.provider, start)})
            raise
        usage = usage_delta(self.provider, start)
        row = {'question': question, 'page': self.state['page'], 'mode': mode,
               'elapsedSeconds': round(time.monotonic() - started, 3),
               'usage': usage, 'result': result}
        write_json(attempt.with_suffix('.result.json'), row)
        self.state['memory'] = result.get('memory', self.state['memory'])
        self.state['turns'].append(row)
        self.state['budgetUsedUsd'] = self.prior_usd + (self.provider.spent if self.provider else 0)
        write_json(self.path, self.state)
        return row


def main(argv=None):
    parser = argparse.ArgumentParser(description='시네시스 창 없이 실제 PDF AI멘토를 사용해요.')
    parser.add_argument('--list', action='store_true', help='로컬 PDF 목록만 조회해요.')
    parser.add_argument('--library', type=io_path, default=data_root() / 'library')
    parser.add_argument('--folder', type=io_path, help='document.json이 있는 PDF 폴더예요.')
    parser.add_argument('--document', help='--list에 나온 문서 ID예요.')
    parser.add_argument('--question', help='한 질문을 실행해요. 생략하면 대화형이에요.')
    parser.add_argument('--batch', type=io_path, help='질문 문자열 또는 {question,page,mode} 배열 JSON이에요.')
    parser.add_argument('--page', type=int)
    parser.add_argument('--mode', choices=['quick', 'deep'], default='quick')
    parser.add_argument('--strategy', default=os.environ.get('SYNESIS_PDF_STRATEGY', 'new-concept-v99'))
    parser.add_argument('--attachment', action='append', help='PDF 폴더 내 상대 첨부 경로예요.')
    parser.add_argument('--no-web', action='store_true')
    parser.add_argument('--allow-remote', action='store_true', help='유료 모델/API 호출을 허용해요.')
    parser.add_argument('--max-usd', type=float, default=0, help='재개를 포함한 세션 총 예산이에요.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--json', action='store_true', help='질문마다 결과 JSON 한 줄을 출력해요.')
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(library_items(args.library), ensure_ascii=False, indent=2))
        return
    if bool(args.folder) == bool(args.document):
        parser.error('--folder 또는 --document 중 하나를 지정해 주세요.')
    if args.question is not None and args.batch:
        parser.error('--question과 --batch는 함께 사용할 수 없어요.')
    if args.resume and not args.output:
        parser.error('--resume에는 --output이 필요해요.')
    if args.allow_remote and (not math.isfinite(args.max_usd) or not 0 < args.max_usd <= 1):
        parser.error('API 호출에는 $0 초과 $1 이하의 --max-usd가 필요해요.')
    folder = args.folder or args.library / args.document
    output = args.output or ROOT / 'build/tutor-cli' / uuid.uuid4().hex
    provider = (Provider(output.resolve(), True, args.max_usd, input_bound_limit=TUTOR_INPUT_BOUND)
                if args.allow_remote else None)
    if provider:
        provider.context = {'kind': 'tutor_cli'}
    session = Session(folder, output, provider, args.resume)
    if args.page is not None:
        session.set_page(args.page)

    def run(item):
        item = {'question': item} if isinstance(item, str) else item
        if not isinstance(item, dict) or not isinstance(item.get('question'), str):
            raise ValueError('배치 항목에는 question 문자열이 필요해요.')
        row = session.ask(item['question'], page=item.get('page'), mode=item.get('mode', args.mode),
                          web=not args.no_web, attachments=args.attachment, strategy=args.strategy)
        if args.json:
            print(json.dumps(row, ensure_ascii=False), flush=True)
        else:
            result, usage = row['result'], row['usage']
            print(result['answer'])
            print(f"\n[검색 판단: {result.get('searchDecision', {}).get('reason', 'local')} · "
                  f"웹 호출 {usage['webSearchCalls']}회 · ${usage['usageBasedUsd']:.8f} · "
                  f"{row['elapsedSeconds']:.1f}초]", flush=True)

    if args.question is not None:
        run(args.question)
    elif args.batch:
        cases = json.loads(args.batch.read_text(encoding='utf-8'))
        if not isinstance(cases, list):
            raise ValueError('배치는 JSON 배열이어야 해요.')
        for case in cases:
            run(case)
    else:
        print('질문을 입력해요. /page 번호, /reset, /quit을 사용할 수 있어요.')
        while True:
            try:
                question = input(f"PDF {session.state['page']}쪽 > ").strip()
            except EOFError:
                break
            if question == '/quit':
                break
            if question.startswith('/page '):
                session.set_page(int(question.split()[1]))
            elif question == '/reset':
                session.state['memory'] = None
                write_json(session.path, session.state)
            elif question:
                run(question)
    if not args.json:
        print(f'기록: {session.path}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RemoteDisabled, BudgetExceeded, AiResponseError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
