"""K1.2.0 compact coverage references; learner prose is never generated locally.

The model points to its own main segment instead of copying title/prose into an
internal index. Restore the canonical index from that exact response and enforce
the original schema before all existing ownership/source/uncertainty checks.
"""
from __future__ import annotations

import copy

VERSION = 'main-segment-ref-safe-v1'
CANONICAL_MARKER = '_sourceCoverageContract'


class CompactCoverageError(ValueError):
    pass


def encode_format(original):
    exact=copy.deepcopy(original)
    value=copy.deepcopy(original)
    row=value['json_schema']['schema']['properties']['sourceCoverage']['items']
    source_id=copy.deepcopy(row['properties']['blockId'])
    row.clear()
    row.update(type='object',additionalProperties=False,required=['blockId','mainSegmentRef'],
        properties={'blockId':source_id,'mainSegmentRef':{'anyOf':[
            {'type':'null'}, {'type':'object','additionalProperties':False,
                'required':['conceptIndex','segmentIndex'],
                'properties':{'conceptIndex':{'type':'integer','minimum':0},
                              'segmentIndex':{'type':'integer','minimum':0}}}]}})
    return value,exact


def restore(raw,exact_format):
    if exact_format is None:return raw
    if not isinstance(raw,dict):raise CompactCoverageError('Coverage response must be an object.')
    schema=exact_format['json_schema']['schema']
    expected=schema['$defs']['studySourceId']['enum']
    records=raw.get('sourceCoverage')
    # Lossless record ordering only. Missing, duplicated, foreign or malformed
    # records still fail below; never invent a source pointer or learner text.
    if (isinstance(records,list) and len(records)==len(expected)
            and all(isinstance(row,dict) and set(row)=={'blockId','mainSegmentRef'}
                    and isinstance(row.get('blockId'),str) for row in records)
            and len({row['blockId']for row in records})==len(expected)
            and {row['blockId']for row in records}==set(expected)
            and [row['blockId']for row in records]!=expected):
        by_id={row['blockId']:row for row in records}
        raw=copy.deepcopy(raw)
        records=[copy.deepcopy(by_id[key])for key in expected]
        raw['sourceCoverage']=records
    if (not isinstance(records,list) or len(records)!=len(expected)
            or any(not isinstance(row,dict) for row in records)
            or [row.get('blockId')for row in records]!=expected):
        raise CompactCoverageError('Coverage must contain every real source exactly once in input order.')
    # Keep the exact wire/source contract. A well-shaped pointer to the wrong
    # paragraph is recoverable metadata; malformed/unknown source data is not.
    from pdf_study_batch_transport import _validate
    wire,_=encode_format(exact_format)
    wire_schema=wire['json_schema']['schema']
    _validate(raw,wire_schema,wire_schema)
    concepts=raw.get('concepts')
    if not isinstance(concepts,list):raise CompactCoverageError('Concepts must remain an array.')
    restored=[]
    for row in records:
        if set(row)!= {'blockId','mainSegmentRef'}:
            raise CompactCoverageError('Unexpected coverage fields cannot be silently discarded.')
        key=row['blockId'];ref=row['mainSegmentRef']
        blank={'blockId':key,'conceptTitle':'','quote':''}
        if ref is None:
            # This is not an exclusion and proves no coverage. The unchanged
            # source validator must establish context/exclusion or flag review.
            restored.append(blank)
            continue
        if (not isinstance(ref,dict) or set(ref)!= {'conceptIndex','segmentIndex'}
                or any(type(ref[name])is not int or ref[name]<0 for name in ref)):
            raise CompactCoverageError('A main segment reference must use exact nonnegative integer indices.')
        ci,si=ref['conceptIndex'],ref['segmentIndex']
        if ci>=len(concepts) or not isinstance(concepts[ci],dict):
            restored.append(blank);continue
        concept=concepts[ci];segments=concept.get('segments')
        if not isinstance(segments,list) or si>=len(segments) or not isinstance(segments[si],dict):
            restored.append(blank);continue
        segment=segments[si]
        if segment.get('kind')not in ('definition','explanation'):
            restored.append(blank);continue
        if (not isinstance(segment.get('blockIds'),list) or key not in segment['blockIds']
                or not isinstance(segment.get('text'),str) or not segment['text'].strip()
                or not isinstance(concept.get('title'),str) or not concept['title'].strip()):
            restored.append(blank);continue
        restored.append({'blockId':key,'conceptTitle':concept['title'],'quote':segment['text']})
    value=copy.deepcopy(raw)
    value['sourceCoverage']=restored
    _validate(value,schema,schema)
    return value


def supplement_only_sources(raw):
    """Find blank records whose only supplied teaching citation is supplemental.

    No semantic inference or source-ID addition is permitted. This catches the
    pre-existing materializer's union of main and easy-explanation citations.
    """
    main=set();easy=set()
    for concept in raw.get('concepts',[]):
        for segment in concept.get('segments',[]):
            if not segment.get('text','').strip():continue
            if segment.get('kind') in ('definition','explanation'):
                main.update(segment.get('blockIds',[]))
            elif segment.get('kind')=='easyExplanation':
                easy.update(segment.get('blockIds',[]))
    blank={row['blockId']for row in raw.get('sourceCoverage',[])
           if not row.get('quote','').strip()}
    return blank & easy - main


def retain_supplement_review(result,source_ids):
    """Never count an invalid main pointer as repaired by optional prose alone.

    Existing context/exclusion and uncertainty decisions remain intact. This
    guard only downgrades summarized rows; it never promotes any row or changes
    learner prose, table, flow, citation, or exclusion records.
    """
    for row in result.get('coverage',[]):
        if row['blockId'] in source_ids and row['state']=='summarized':
            row.update(state='needs_review',reviewKind='content',
                reason='보충 설명에만 출처가 있어요. 필수 내용의 본문 반영 여부를 확인해야 해요.')
            result.setdefault('processingDiagnostics',[]).append({
                'stage':'compact_coverage_check','blockIds':[row['blockId']],
                'reason':'supplement_only_without_valid_main_reference'})
    return result
