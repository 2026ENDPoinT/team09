"""Local context for explicit whole-document summaries. No model calls or writes."""
from __future__ import annotations

import json
from pathlib import Path
import re

GUIDE_BYTES = 24_000
SOURCE_BYTES = 18_000
SOURCE_PAGES = 12
_DOCUMENT = r'(?:pdf|피디에프|문서|자료|강의(?:자료)?)'
_WHOLE = r'(?:전체|전반|전부|모든\s*내용|처음부터\s*끝까지|통틀어)'
_SUMMARY = re.compile(r'요약|정리|핵심|개요|흐름|주제|중요|summari[sz]|overview|key\s*points', re.I)
_DIALOGUE = re.compile(r'대화|채팅|주고받|질문\s*(?:과|이랑|및)\s*답변|'
                       r'(?:지금까지|여태|앞서).{0,12}(?:얘기|이야기|말한|한\s*말)|conversation|chat\s*history', re.I)
_PAGE = re.compile(r'\d+\s*(?:페이지|쪽)|\b(?:page|p)\.?\s*\d+', re.I)


def summary_request(question, plan, *, attachment=False, selection=False, explicit_page=None):
    """Expand only a document-level task, never an ordinary topic or a current attachment."""
    if attachment or selection or explicit_page is not None or _PAGE.search(question):
        return False
    if _DIALOGUE.search(question) or not (_SUMMARY.search(question) or full_review_request(question)):
        return False
    if re.search(r'첨부|선택한|선택된|붙여넣|스크린샷|사진|이미지|attachment|selection', question, re.I):
        return False
    if plan.get('scope') == 'external' or plan.get('toolRequest'):
        return False
    if re.search(r'(?:다른|새로운|여러|두|2개(?:의)?)\s*' + _DOCUMENT, question, re.I):
        return False
    text = question.strip()
    named_whole = re.search(_DOCUMENT + r'\s*(?:안에서|안의|에서|의|를|는|에\s*담긴|에\s*있는)?\s*'
                            r'(?:내용\s*)?' + _WHOLE + r'|' + _WHOLE + r'\s*' + _DOCUMENT, text, re.I)
    # "전체 내용을 3가지로 요약" defaults to the connected PDF. A named subject
    # such as "DNA 복제 전체 과정" does not match this omitted-object form.
    omitted_whole = re.match(r'^(?:(?:그럼|그러면|이제|일단|좀)\s*)*'
                             r'(?:(?:이|그|현재|지금)\s*)?' + _WHOLE +
                             r'\s*(?:내용|자료|흐름|주제|핵심|적(?:으로|인))', text, re.I)
    document_overview = re.match(r'^(?:(?:이|그|현재|지금|연결된|열린|열려\s*있는|업로드한)\s*)?'
                                 + _DOCUMENT + r'\s*(?:안에서|에서|의|를|는)?\s*'
                                 r'(?:(?:가장|제일)\s*)?(?:핵심|중요|개요|주요\s*내용|흐름|요약)', text, re.I)
    return bool(named_whole or omitted_whole or document_overview)


def full_review_request(question):
    """An explicit page-by-page inspection must keep the existing full-reading path."""
    return bool(re.search(r'모든\s*(?:페이지|문장)|전\s*페이지|빠짐없이|전수|정독|'
                          r'(?:전체|전부|처음부터\s*끝까지).{0,18}(?:읽|검토|대조|확인)|'
                          r'(?:읽|검토|대조|확인).{0,18}(?:전체|전부|처음부터\s*끝까지)|'
                          r'(?:전체|전부|처음부터\s*끝까지)\s*'
                          r'(?:(?:문서|자료|PDF|원문)(?:의)?\s*)?(?:내용|페이지)?\s*'
                          r'(?:을|를|도)?\s*(?:좀\s*|한\s*번\s*)?(?:봐|보아|살펴)', question,re.I))


def dialogue_summary_request(question):
    return bool(_DIALOGUE.search(question) and _SUMMARY.search(question))


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))


def _text(value, limit):
    return str(value or '').encode('utf-8')[:limit].decode('utf-8', errors='ignore').strip()


def _excerpt(text, limit):
    part = _text(text, limit)
    if len(text.encode('utf-8')) > limit:
        boundary = max(part.rfind('\n'), part.rfind('. '))
        if boundary >= len(part) // 2:
            part = part[:boundary+1].rstrip()
    return part


def _pages(block, count):
    if not isinstance(block, dict):
        return []
    values = list(block.get('pages', [])) if isinstance(block.get('pages'), list) else []
    values += [block.get('page')]
    for key in ('evidence', 'visualPages', 'parts', 'entries'):
        for item in block.get(key, []) if isinstance(block.get(key), list) else []:
            values.extend(_pages(item, count) if isinstance(item, dict) else [item])
    return sorted({n for n in values if type(n) is int and 1 <= n <= count})


def load_guide(folder, document, strategy=None):
    """Read only the active strategy's complete result for this exact document revision."""
    if folder is None or document.get('comparisonTextOnly'):
        return None
    fingerprint = document.get('fingerprint')
    if not fingerprint or not document.get('documentId'):
        return None
    root = Path(folder) / 'generated'
    strategy = strategy or document.get('_studyStrategy')
    if strategy == 'semantic-v1':
        root /= 'semantic'
    elif strategy and strategy != 'page-v1':
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,63}', strategy):
            return None
        root /= strategy
    path = root / 'latest-document-0.json'
    try:
        if path.stat().st_size > 20_000_000:
            return None
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, RecursionError):
        return None
    if (not isinstance(saved, dict) or saved.get('kind') != 'ai_generated'
            or saved.get('documentId') != document['documentId']
            or saved.get('sourceFingerprint') != fingerprint
            or saved.get('scope', 'document') != 'document'
            or strategy and saved.get('strategy', strategy) != strategy):
        return None
    count = len(document.get('pages', []))
    groups = [c for c in saved.get('concepts', []) if isinstance(c, dict) and c.get('name')] if isinstance(saved.get('concepts'), list) else []
    if not isinstance(saved.get('sections', []), list):
        return None
    sections = [s for s in saved.get('sections', []) if isinstance(s, dict) and s.get('title')
                and not s.get('studyContentSkipped')]
    overview = saved.get('overview') if isinstance(saved.get('overview'), dict) else {}
    if not groups and not sections and not overview.get('body'):
        return None
    guide = {'scope': 'document', 'overview': _text(overview.get('body'), 2000),
             'conceptNames': [_text(c['name'], 160) for c in groups], 'concepts': [],
             'sections': [{'title': _text(s['title'], 240), 'pages': _pages(s, count)} for s in sections]}
    for group in groups:
        entries = [e for e in group.get('entries', []) if isinstance(e, dict)] if isinstance(group.get('entries'), list) else []
        entry = entries[0] if entries else {}
        guide['concepts'].append({'name': _text(group['name'], 160),
                                 'definition': _text(entry.get('definition') or entry.get('explanation'), 420),
                                 'pages': _pages(group, count)})
    guide['coverage'] = {'concepts': len(groups), 'sections': len(sections),
                         'allSavedTopicsIncluded': True, 'basis': 'saved_study_index'}
    # Reduce detail uniformly before discarding any topic. If the entire index
    # cannot fit, let the caller use the established full-document reading path.
    for limit in (160, 0):
        if _bytes(guide) <= GUIDE_BYTES:
            break
        for concept in guide['concepts']:
            concept['definition'] = _text(concept['definition'], limit)
    return guide if _bytes(guide) <= GUIDE_BYTES else None


def representative_sources(sources, guide):
    """Sample actual indexed PDF text across the index, never promote study notes to evidence."""
    linked = {p for block in guide['sections'] + guide['concepts'] for p in block['pages']}
    pages = {}
    for source in sources:
        page = source.get('page')
        if type(page) is not int or not source.get('text', '').strip():
            continue
        if linked and page not in linked:
            continue
        previous = pages.get(page)
        rank = lambda s: (s.get('source') == 'native', len(s['text']))
        if previous is None or rank(source) > rank(previous):
            pages[page] = source
    ordered = sorted(pages)
    if len(ordered) > SOURCE_PAGES:
        ordered = [ordered[round(i * (len(ordered)-1) / (SOURCE_PAGES-1))] for i in range(SOURCE_PAGES)]
    selected = [{**pages[p], 'text': _excerpt(pages[p]['text'], 1800)} for p in ordered]
    for limit in (1000, 500, 200):
        if _bytes(selected) <= SOURCE_BYTES:
            break
        selected = [{**s, 'text': _excerpt(s['text'], limit)} for s in selected]
    return selected if _bytes(selected) <= SOURCE_BYTES else []
