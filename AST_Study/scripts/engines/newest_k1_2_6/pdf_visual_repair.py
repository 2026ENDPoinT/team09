"""Merge an explicitly requested visual-page repair without regenerating healthy prose."""
from __future__ import annotations
import copy
import hashlib
import json

from pdf_ai import merge_concepts
from pdf_hierarchy_runtime import hierarchy
from pdf_visual_selection import VERSION


def source_pages(section):
    return {e['page'] for p in section.get('parts',[]) for e in p.get('evidence',[])}


def merge_repair(base, base_blocks, patch, patch_blocks, document):
    """Only fill previously absent pages; never replace a supported explanation.

    IDs are namespaced because an old layout may have hundreds of raster strips
    where the repaired layout has one image. Matching a positional ID is unsafe.
    """
    for key in ('documentId','sourceFingerprint','strategy','model'):
        if base.get(key)!=patch.get(key):raise ValueError('다른 문서·분석 방식의 보완 결과예요: '+key)
    if base.get('sourceFingerprint')!=document.get('fingerprint'):
        raise ValueError('원문이 바뀌어 보완 결과를 합칠 수 없어요.')
    if not base.get('processingComplete') or not patch.get('processingComplete') or patch.get('failedUnits'):
        raise ValueError('완료된 원문 분석과 보완 결과가 필요해요.')
    pages=set(patch.get('sourcePages',[]))
    if not pages or not patch.get('sections'):raise ValueError('추가할 설명이 없어요.')
    existing={n for s in base.get('sections',[]) for n in source_pages(s)}
    if pages & existing:raise ValueError('이미 설명이 있는 페이지는 자동 교체하지 않아요.')
    if not pages.issubset(set(base.get('sourcePages',[]))):raise ValueError('기존 분석 범위 밖의 보완 결과예요.')
    old=copy.deepcopy(base);added=copy.deepcopy(patch)
    digest=hashlib.sha256(json.dumps([sorted(pages),patch['sections']],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
    mapping={b['id']:f'visual-repair-{digest}:{b["id"]}' for b in patch_blocks}
    def rebind(node):
        if isinstance(node,dict):
            for key,value in node.items():
                if key in ('sourceId','blockId','id') and isinstance(value,str) and value in mapping:node[key]=mapping[value]
                elif key=='blockIds' and isinstance(value,list):node[key]=[mapping.get(v,v) for v in value]
                elif isinstance(value,(dict,list)):rebind(value)
        elif isinstance(node,list):
            for item in node:rebind(item)
    rebind(added)
    new_blocks=copy.deepcopy(patch_blocks);rebind(new_blocks)
    blocks=[copy.deepcopy(b) for b in base_blocks if b['page'] not in pages]+new_blocks
    blocks.sort(key=lambda b:(b['page'],b.get('bbox',[0,0])[1],b.get('bbox',[0])[0]))
    tagged=[(index,section) for index,section in enumerate(old['sections'])]
    tagged.extend((None,section) for section in added['sections'])
    tagged.sort(key=lambda item:min(source_pages(item[1]) or {10**9}))
    old['sections']=[section for _,section in tagged]
    # The title-only overview can retain its original prose and source links.
    indices={f's{prior}':f's{now}' for now,(prior,_) in enumerate(tagged) if prior is not None}
    if isinstance(old.get('overview'),dict) and isinstance(old['overview'].get('sourceSectionIds'),list):
        old['overview']['sourceSectionIds']=[indices[x] for x in old['overview']['sourceSectionIds'] if x in indices]
    cards=lambda result:[e for c in result.get('concepts',[]) for e in c.get('entries',[c])]
    old['concepts']=merge_concepts(cards(base)+cards(added))
    old['coverage']=[c for c in old['coverage'] if c['page'] not in pages]+added['coverage']
    old['coverage'].sort(key=lambda c:c['page'])
    pending=sorted({c['page'] for c in old['coverage'] if c['state'] in ('needs_review','pending_summary')})
    old.update(coverageComplete=not pending,evidenceIncomplete=bool(pending),
        incompleteStudyPages=pending,pageAnalysisIncompletePages=pending,
        visualSelectionVersion=VERSION,cacheHit=True)
    old['visualRepair']={'version':VERSION,'pages':sorted(pages),'namespace':digest,
        'originalRunUsage':base.get('runUsage'),'additionalRunUsage':patch.get('runUsage'),
        'originalPartsPreserved':sum(len(s.get('parts',[])) for s in base['sections'])}
    old['runUsage']=patch.get('runUsage',{})
    for key in ('partialUnits','totalUnits'):
        if key in old:old[key]+=patch.get(key,0)
    old.setdefault('metrics',{})['visualRepairGenerationSeconds']=patch.get('metrics',{}).get('elapsedSeconds')
    old['_pageLabels']={str(i+1):p.get('label',str(i+1)) for i,p in enumerate(document['pages'])}
    old=hierarchy.decorate(old,blocks,hierarchy.source_headings(blocks))
    return old,blocks
