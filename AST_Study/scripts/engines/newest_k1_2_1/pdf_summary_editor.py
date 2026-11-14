"""One bounded editorial pass over completed topic drafts.

Reading/coverage records and concept cards stay intact. If editing fails, the already
completed teaching drafts remain usable; an optional polish must never stop generation.
"""
import copy
import hashlib
import json

from pdf_pipeline import check_cancel, write_json
from pdf_response_schema import _object
from pdf_study_policy import study_rules
from pdf_output_language import study_issues

VERSION = 'learner-summary-v7'
MAX_INPUT_BYTES = 96000
PARALLEL_VERSION = 'parallel-reviewed-topics-v1'
PROMPT = study_rules(concepts=False, editing=True) + """
TASK: Edit completed study drafts into readable topic sections. Preserve useful explanations,
conditions, distinctions, formulas and source examples. Merge genuine repetition and improve
connections. Keep independent teaching questions separate; there is no target compression ratio
or section count. Retain a good easy explanation and adapt it only where the edited topic needs it.
Each section must explain the educational content of its assigned drafts; do not concatenate
hints mechanically or replace distinct ideas with a generic slogan.

INPUT: body and easyHints are earlier generated teaching prose, not verbatim PDF evidence.
standardKnowledgeUsed reports existing supplementation; labels in the text identify illustrations.
Retain the labels of existing added examples and analogies when keeping or adapting them.
Do not promote a prior illustration or correction into a source claim. Preserve material
uncertainty, while omitting processing commentary unrelated to the explanation being used.

OUTPUT: Return title, body, easyExplanation, addedIllustration and sourceSectionIds per section.
Use every input ID exactly once, keeping IDs in source order. Order sections by first occurrence;
a later revisit may join its earlier topic, but preserve meaningful process/argument order.
These IDs account for coverage and do not require separate prose per draft. Return no overview;
the lecture flow is generated independently from completed topic headings.
"""
S = {'type': 'string'}
FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'synesis_learner_summary_v3',
    'strict': True, 'schema': _object({'sections': {'type': 'array',
    'items': _object({'title': S, 'body': S, 'easyExplanation': S,
                     'addedIllustration': {'type': 'boolean'},
                     'sourceSectionIds': {'type': 'array', 'items': S}})}})}}


def draft_items(sections):
    # Carry the small teaching hints forward; avoid resending evidence and concept cards.
    items = []
    for i, section in enumerate(sections):
        hints = [part['easyExplanation'].strip() for part in section.get('parts', [])
                 if isinstance(part.get('easyExplanation'), str) and part['easyExplanation'].strip()]
        if not hints and isinstance(section.get('easyExplanation'), str) and section['easyExplanation'].strip():
            hints = [section['easyExplanation'].strip()]
        items.append({'id': f's{i}', 'title': section['title'], 'body': section['body'],
                      'easyHints': list(dict.fromkeys(hints)),
                      'standardKnowledgeUsed': bool(section.get('standardKnowledgeUsed')) or any(
                          part.get('standardKnowledgeUsed') for part in section.get('parts', [])),
                      'evidenceIncomplete': section.get('evidenceIncomplete', False)})
    return items


def combined_evidence(sections):
    evidence, seen = [], set()
    for section in sections:
        for entry in section.get('evidence', []):
            key = (entry.get('sourceId'), entry.get('quote'))
            if key not in seen:
                evidence.append(copy.deepcopy(entry)); seen.add(key)
    return evidence


def validate_edit(value, source):
    from pdf_ai import study_math_issues
    sections = value.get('sections') if isinstance(value, dict) else None
    if not isinstance(sections, list) or not sections or any(not isinstance(s, dict) for s in sections):
        raise ValueError('통합 요약의 설명이 비어 있어요.')
    ids = []
    for s in sections:
        if any(not isinstance(s.get(k), str) or not s[k].strip() for k in ('title', 'body', 'easyExplanation')):
            raise ValueError('통합 요약의 본문이나 쉬운 설명이 비어 있어요.')
        if not isinstance(s.get('addedIllustration'), bool):
            raise ValueError('통합 요약의 추가 예시 표시가 비어 있어요.')
        refs = s.get('sourceSectionIds')
        if not isinstance(refs, list) or not refs or any(not isinstance(i, str) for i in refs):
            raise ValueError('통합 요약의 원본 구간 연결이 비어 있어요.')
        ids.extend(refs)
    expected = [f's{i}' for i in range(len(source))]
    if len(ids) != len(expected) or set(ids) != set(expected):
        raise ValueError('통합 요약의 원본 구간이 누락·중복됐거나 외부 구간을 참조해요.')
    # Ordering metadata is deterministic; fix it locally without discarding paid prose.
    # Never infer membership or repair missing/duplicate IDs (rejected above).
    sections = [dict(s, sourceSectionIds=sorted(s['sourceSectionIds'], key=lambda i: int(i[1:])))
                for s in sections]
    sections.sort(key=lambda s: int(s['sourceSectionIds'][0][1:]))
    study = {'summary': {'title': '요약', 'body': '요약', 'parts': sections}, 'concepts': []}
    if study_issues(study) or study_math_issues(study):
        raise ValueError('통합 요약의 언어나 수식 표기를 확인해야 해요.')
    output = []
    for s in sections:
        originals = [source[int(i[1:])] for i in s['sourceSectionIds']]
        part = {k: s[k] for k in ('title', 'body', 'easyExplanation')}
        part.update(evidence=combined_evidence(originals),
                    visualPages=sorted({p for x in originals for p in x.get('visualPages', [])}),
                    coveredElementIds=list(dict.fromkeys(i for x in originals for p in x.get('parts', [])
                                                        for i in p.get('coveredElementIds', []))),
                    standardKnowledgeUsed=s['addedIllustration'] or any(x.get('standardKnowledgeUsed') for x in originals),
                    evidenceIncomplete=any(x.get('evidenceIncomplete') for x in originals))
        output.append({**part, 'easyExplanation': '', 'parts': [part],
                       'sourceSectionIds': list(s['sourceSectionIds']),
                       'semanticUnitIds': [x['semanticUnitId'] for x in originals if x.get('semanticUnitId')]})
    return output


def edit_summary(provider, cache, sections, *, local_only=False, cached_only=False):
    from pdf_outline import overview
    items = draft_items(sections)
    payload = {'task': 'edit_completed_study_topics', 'drafts': items}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256((provider.model + VERSION + PROMPT + encoded).encode()).hexdigest()
    path = cache / f'edited-summary-{key}.json'
    status = {'version': VERSION, 'sourceSectionCount': len(sections)}
    if local_only or len(encoded.encode()) > MAX_INPUT_BYTES or (cached_only and not path.is_file()):
        status.update(status='drafts_retained', reason='local_only' if local_only else
                      'no_saved_edit' if cached_only and not path.is_file() else 'input_bound')
    else:
        check_cancel(provider.folder if hasattr(provider, 'folder') else cache.parent)
        try:
            if path.is_file():
                value = json.loads(path.read_text(encoding='utf-8'))
            else:
                provider.context = {'kind': 'summary_reduce', 'strategy': VERSION, 'level': 1, 'group': 0}
                value = provider.complete(payload, max_output=24000, system_prompt=PROMPT, response_format=FORMAT)
                # Keep the paid raw response even when structural validation fails.
                write_json(path, value)
            edited = validate_edit(value, sections)
            opening = overview(provider, cache, edited, local_only=cached_only)
            return opening, edited, {**status, 'status': 'edited', 'sectionCount': len(edited)}
        except InterruptedError:
            raise
        except Exception as error:
            # CLI providers can be defined in __main__, whereas tests import pdf_ai.
            # Optional editing must also tolerate transport/IO failures, irrespective
            # of the provider's exception class identity. Cancellation still propagates.
            status.update(status='drafts_retained', reason=type(error).__name__)
    # No second paid call, and no loss of completed drafts if optional editing fails.
    return overview(provider, cache, sections, local_only=True), sections, status


PARALLEL_PROMPT = PROMPT + '''
These drafts have already been checked against original page images. Improve the connections
and grouping of adjacent explanations, retaining every distinct idea and condition. Preserve
the checked easy explanations and their examples; do not invent, replace or extend an example
or analogy. Merge genuine repetition without changing its mechanism. Do not add facts or
textbook corrections. There is no section-count or length target. Keep useful structure inside
the explanations. Return sourceSectionIds exactly as in the normal editorial contract.
'''


def parallel_edit(provider, cache, sections, workers=8):
    """Bound the slow editorial tail to small adjacent groups, with stable ordering."""
    from concurrent.futures import ThreadPoolExecutor
    from pdf_pipeline import read_json_cache
    if len(sections)<2:
        return sections, {'status':'source_retained','sourceSectionCount':len(sections),'pendingGroups':[]}
    def pages(section):
        return set(section.get('visualPages',[])) | {e.get('page') for e in section.get('evidence',[]) if e.get('page')}
    groups=[];group=[];group_pages=set()
    for section in sections:
        proposed=[*group,section]
        # Separate coherent topics need no extra rewrite. Adjacent fragments
        # sharing source pages are candidates for joining, never forced merges.
        if group and (not group_pages.intersection(pages(section)) or len(proposed)>4
                      or len(json.dumps(draft_items(proposed),ensure_ascii=False).encode())>MAX_INPUT_BYTES):
            groups.append(group);group=[];group_pages=set()
        group.append(section)
        group_pages.update(pages(section))
    if group:groups.append(group)
    if all(len(g)==1 for g in groups):
        return sections, {'status':'source_retained','sourceSectionCount':len(sections),
                          'pendingGroups':[],'reason':'separate_coherent_topics'}
    def work(item):
        index,originals=item
        if len(originals)==1:
            return originals,False
        payload={'task':'edit_completed_study_topics','drafts':draft_items(originals),
                 'editorVersion':PARALLEL_VERSION}
        encoded=json.dumps([provider.model,PARALLEL_PROMPT,payload],ensure_ascii=False,sort_keys=True)
        path=cache/f'parallel-edit-{hashlib.sha256(encoded.encode()).hexdigest()}.json'
        try:
            check_cancel(provider.folder if hasattr(provider,'folder') else cache.parent)
            value=read_json_cache(path)
            if value is None:
                provider.context={'kind':'summary_reduce','strategy':PARALLEL_VERSION,'group':index}
                value=provider.complete(payload,system_prompt=PARALLEL_PROMPT,response_format=FORMAT,
                                        max_output=24000,cache_stable_prefix=True)
            edited=validate_edit(value,originals)
            offset=sum(len(group) for group in groups[:index])
            for section in edited:
                section['sourceSectionIds']=[f's{offset+int(identity[1:])}'
                                             for identity in section['sourceSectionIds']]
            write_json(path,value)
            return edited,False
        except InterruptedError:
            raise
        except Exception:
            return originals,True
    with ThreadPoolExecutor(max_workers=min(workers,len(groups))) as pool:
        values=list(pool.map(work,enumerate(groups)))
    return [s for result,_ in values for s in result], {
        'version':PARALLEL_VERSION,'status':'parallel_edited','sourceSectionCount':len(sections),
        'groups':len(groups),'maxSectionsPerRequest':4,
        'pendingGroups':[i for i,(_,pending) in enumerate(values) if pending]}
