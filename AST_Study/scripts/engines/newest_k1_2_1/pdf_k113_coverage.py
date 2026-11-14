"""Evidence-backed K1.1.3 source accounting. Never waive uncertain assertions.

Source fragments are not independent concepts: join proven text/layout pieces to
their taught parent. Large images require a model-read disposition in the normal
teaching response, not a heuristic based on a sparse native caption.
"""
import re
import unicodedata
import hashlib
import json

VERSION='k113-coverage-resolution-v2'
_BULLET=re.compile(r'^[\s•●▪◦·»–—-]*(?:\d+[.)])?$')
_CLAIM=re.compile(r'[=<>∑∫]|\\[A-Za-z]+|(?:이다|한다|된다|있다|없다|않다|하라|구하라)[.!?]?$')
_LAYOUT=re.compile(r'제목|표제|표지|목차|구분선|강조선|장식|글머리|기호|서지|참고문헌|bibliograph|heading|cover|navigation',re.I)


def complete(result):
    return (isinstance(result,dict) and result.get('processingComplete') is True
            and result.get('coverageComplete') is True
            and not any(x.get('state') in ('needs_review','pending_summary') for x in result.get('coverage',[])))


def feedback(job, raw, coverage):
    by_id={b['id']:b for b in job['blocks']}
    job['_reviewFeedback']=[{'page':by_id[c['blockId']]['page'],
        'bbox':by_id[c['blockId']].get('bbox'), 'issue':c['reason']}
        for c in coverage if c.get('state')=='needs_review' and c['blockId']in by_id]
    job['_reviewRevision']=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def compact(text):
    return re.sub(r'[\s`\\{}()\[\]•●▪◦·»–—]', '',unicodedata.normalize('NFKC',str(text))).casefold()


def same_lane(a,b):
    return a.get('page')==b.get('page') and a.get('zone',0)==b.get('zone',0)


def nearby(a,b,gap=.035):
    x=a.get('bbox');y=b.get('bbox')
    return bool(x and y and same_lane(a,b) and
        min(x[3],y[3])>=max(x[1],y[1])-.01 and
        max(x[0]-y[2],y[0]-x[2],0)<=gap)


def reconcile(coverage, blocks, parts, raw=None):
    by_id={b['id']:b for b in blocks};rows={c['blockId']:c for c in coverage}
    excluded={x['blockId']:x for x in (raw or {}).get('excludedBlocks',[])}
    # Only actually retained body text can prove that an inline word is taught.
    taught={}
    for p in parts:
        if not p.get('body','').strip():continue
        for e in p.get('evidence',[]):taught.setdefault(e['sourceId'],[]).append(p)
    for c in coverage:
        if c['state']!='needs_review' or c.get('reviewKind')=='content':continue
        b=by_id.get(c['blockId']);box=b.get('bbox') if b else None
        if not box:continue
        text=b.get('text','').strip();norm=compact(text);w=box[2]-box[0];h=box[3]-box[1]
        peers=[p for p in blocks if p['id']in taught and p['id']!=b['id'] and same_lane(b,p)]
        reason=excluded.get(b['id'],{}).get('reason','')
        related=[];role=None
        # Native title plus a model's image-read structural assessment. Sparse
        # text over a whole diagram cannot satisfy the shallow-box branch.
        if (text and b.get('wordIds') and not _CLAIM.search(text) and _LAYOUT.search(reason)
                and ((h<.12 and len(text)<120) or
                     b.get('planRoleBeforeVisualGuard',b.get('planRole'))=='navigation')):
            role='source_layout';related=[p['id']for p in peers]
        # Typography-only punctuation/bullets must have a taught neighbor.
        if text and (_BULLET.fullmatch(text) or re.fullmatch(r'[,;:：(){}]+',text)):
            related=[p['id']for p in peers if nearby(b,p,.055)]
            if related:role='text_accessory'
        # A short fragment at a font boundary, including an identifier or a
        # superscript, must occur in the retained explanation of its neighbor.
        # No arbitrary prose, conditions or mathematical operators are waived.
        short=(len(norm)<=18 and h<.12 and not re.search(r'[=<>→⇒]|(?:없|않|단,|따라서)',text))
        if short and norm and b.get('wordIds'):
            for p in peers:
                if nearby(b,p,.025) and any(norm in compact(q['body']) for q in taught[p['id']]):
                    related=[p['id']];role='inline_fragment';break
        if role:
            c.update(state='context',reason='설명된 원문과 연결한 구조·문장 구성 요소예요.',
                     resolution={'version':VERSION,'kind':role,'blockIds':related,'sourceText':text})
            c.pop('reviewKind',None)
    return coverage


def disposition(item, block, blocks, parts):
    """Validate a read-and-classify record from the SAME teaching response."""
    d=item.get('sourceDisposition')
    ref=item.get('referenceContext');box=block.get('bbox',[])
    if (d is None and isinstance(ref,dict) and ref.get('kind')=='decoration'
            and ref.get('readable') is True and ref.get('learningSignals')==[]
            and ref.get('observations') and len(box)==4 and not block.get('text','').strip()
            and 0<box[3]-box[1]<.025 and box[2]-box[0]>10*(box[3]-box[1])
            and re.search(r'구분선|강조선|가로.{0,5}선|장식', ' '.join(ref['observations'])+item.get('reason',''))
            and not re.search(r'좌표|축|화살표|분수|수식|그래프|graph|axis',' '.join(ref['observations']),re.I)):
        d={'kind':'structure','observations':ref['observations'],'independentLearningPoint':'','keptConceptTitle':''}
    if not isinstance(d,dict):return None
    kind=d.get('kind');observations=d.get('observations',[])
    if not observations or not all(isinstance(x,str) and x.strip()for x in observations):return None
    if d.get('independentLearningPoint','').strip():return None
    matches=[p for p in parts if p.get('title')==d.get('keptConceptTitle') and p.get('body','').strip()]
    if not matches:
        # Only an entire concept name plus a qualifier, never arbitrary overlap.
        matches=[p for p in parts if len(p.get('title',''))>=10 and p.get('body','').strip()
                 and re.match(re.escape(p['title'])+r'\s*(?:와|과|및|·|:)',d.get('keptConceptTitle',''))]
        if len(matches)!=1:matches=[]
    if kind in ('source_conflict','unlabelled_supporting_figure'):
        if not matches:return None
        if kind=='source_conflict' and len(set(observations))<2:return None
        if kind=='unlabelled_supporting_figure' and not block.get('hasVisual'):return None
        return {'kind':kind,'observations':observations,'keptConceptTitle':d['keptConceptTitle']}
    if kind in ('repeated_example','supporting_illustration'):
        if not matches:return None
        # A real new law, branch or condition may not be excluded as illustration.
        text=block.get('text','')
        if re.search(r'정의\s*[:：]|정리\s*[:：]|\b(?:theorem|definition)\b',text,re.I):return None
        return {'kind':kind,'observations':observations,'keptConceptTitle':d['keptConceptTitle']}
    if kind=='structure':
        if not _LAYOUT.search(item.get('reason','')+' '+' '.join(observations)):return None
        if (_CLAIM.search(block.get('text','')) or re.search(
                r'정의\s*[:：]|정리\s*[:：]|\b(?:theorem|definition)\b',block.get('text',''),re.I)):
            return None
        if re.search(r'수식|방정식|축|범례|그래프|알고리즘|분기|변수|formula|graph|code',
                     ' '.join(observations),re.I):return None
        return {'kind':kind,'observations':observations}
    return None


def link_supported(raw, allowed, parts, cards, accounted, evidence):
    """Require the same-response source index to quote a RETAINED paragraph."""
    records=raw.get('sourceCoverage',[]);seen=set()
    for r in records:
        key=r.get('blockId')
        if key not in allowed or key in seen:raise ValueError('출처 처리 기록이 중복되거나 범위를 벗어났어요.')
        seen.add(key)
        quote=compact(r.get('quote',''))
        if len(quote)<8:continue
        matches=[i for i,p in enumerate(parts) if p.get('title')==r.get('conceptTitle')
                 and quote in compact(p.get('body',''))]
        if len(matches)!=1:continue
        i=matches[0];part=parts[i]
        # Never clear uncertainty sharing this source; it is processed below.
        ref=evidence(allowed[key])
        for obj in (part,cards[i]):
            if not any(e['sourceId']==key for e in obj['evidence']):obj['evidence'].append(ref)
            obj['visualPages']=sorted(set(obj['visualPages'])|{allowed[key]['page']})
        accounted[key]=('summarized','최종 본문의 대응 문장과 원문을 연결했어요.')
