"""Conservative local evidence checks; no provider call and no subject vocabulary."""
import json
import re
import unicodedata

POLICY = 'unit-envelopes-source-quotes-v1'
RULES = '''
Source ownership: finish each task using ONLY the source blocks and images inside
that task's envelope. Nearby unit titles are context, not source evidence. Before
writing each concept, put up to two short, distinctive VERBATIM excerpts from the
actual source you used into sourceSetup.sourceQuotes (a heading, code expression,
or clause). Do not quote titleHint, context titles, or another unit's material.
Use [] when the source is purely visual or has no readable text; never invent an
excerpt. Keep these internal excerpts out of learner prose. Each concept's prose
must explain the source you just checked, not a companion task. Resolve a mismatch
before returning. Do not add defensive ownership commentary to learner prose.
'''

class SourceOwnershipError(ValueError):
    pass

def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value))).casefold()

def source_text(request):
    blocks=request.get('payload',{}).get('blocks',request.get('job',{}).get('blocks',[]))
    return normalize('\n'.join(str(b.get('text',''))+'\n'+str(b.get('nativeText','')) for b in blocks))

def crossed_evidence(raw, own, peers):
    """Require two independent rival-only literal quotes in the same concept.

    Missing/OCR-only evidence is inconclusive, not an error. Shared vocabulary,
    legitimate comparison within the source and nested duplicates cannot trigger.
    This is evidence of cross ownership, not a general semantic correctness score.
    """
    own_text=source_text(own)
    if not own_text:return []
    from pdf_study_review import partial_visual_source
    # Text extraction is not a transcript of a chart/image. Keep ID ownership
    # strict in validate(), but do not claim rival-only quotes from missing OCR.
    if partial_visual_source(own):return []
    result=[]
    for concept in raw.get('concepts',[]):
        quotes=concept.get('sourceSetup',{}).get('sourceQuotes',[])
        normalized=[]
        for quote in quotes:
            q=normalize(quote)
            if len(q)<12 or q in own_text:continue
            if any(q in other or other in q for other in normalized):continue
            normalized.append(q)
        for peer in peers:
            peer_text=source_text(peer)
            matches=[q for q in normalized if q in peer_text]
            if len(matches)>=2:
                result.append({'concept':concept.get('title',''), 'peerJobId':peer.get('job',{}).get('id'),
                               'quotes':matches})
    return result

def ensure_owned(raw,own,peers):
    evidence=crossed_evidence(raw,own,peers)
    if evidence:
        raise SourceOwnershipError('다른 단위의 원문 인용이 확인됐어요: '+json.dumps(evidence,ensure_ascii=False))
