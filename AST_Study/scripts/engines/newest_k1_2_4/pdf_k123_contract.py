"""Compact internal wire fields while preserving canonical source validation."""
import copy
import re

VERSION='k123-concise-internal-records-v2'


def encode(request):
    request['response_format']=copy.deepcopy(request['response_format'])
    setup=request['response_format']['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']
    setup['properties'].pop('interpretation',None)
    setup['required']=[k for k in setup['required']if k!='interpretation']
    difficulty=setup['properties']['learnerDifficulty']
    difficulty['properties'].pop('question',None)
    difficulty['required']=[k for k in difficulty['required']if k!='question']
    from pdf_k123_policy import LEAN_RULES
    request['instructions']+=LEAN_RULES
    request['_conciseInternalRecords']=VERSION
    request['context']['internalRecordsPolicy']=VERSION
    return request


def restore(raw,request):
    if not request.get('_conciseInternalRecords')or not isinstance(raw,dict):return raw
    raw=copy.deepcopy(raw)
    for concept in raw.get('concepts',[]):
        if not isinstance(concept,dict):continue
        setup=concept.get('sourceSetup')
        if not isinstance(setup,dict):continue
        # Empty compatibility fields assert no observation or completed check.
        # Actual relations, source excerpts, branch checks and learner text survive.
        setup.setdefault('interpretation','')
        if isinstance(setup.get('learnerDifficulty'),dict):
            setup['learnerDifficulty'].setdefault('question','')
    return raw


def quarantine_unused_exclusions(raw,request):
    """An unused schema-pool alias cannot exclude any real source region.

    Never repair a learner citation, real source record or uncertainty claim.
    Exact coverage validation after this function still detects actual omissions.
    """
    exact=request.get('_sourceCoverageExactFormat')
    if not exact or not isinstance(raw,dict):return raw,[]
    allowed=set(exact['json_schema']['schema']['$defs']['studySourceId']['enum'])
    if not allowed or not isinstance(raw.get('excludedBlocks'),list):return raw,[]
    removed=[x for x in raw['excludedBlocks']if isinstance(x,dict)
        and isinstance(x.get('blockId'),str)and x['blockId']not in allowed]
    if not removed:return raw,[]
    value=copy.deepcopy(raw)
    value['excludedBlocks']=[x for x in value['excludedBlocks']if not(isinstance(x,dict)
        and isinstance(x.get('blockId'),str)and x['blockId']not in allowed)]
    return value,removed


def remove_wire_annotations(raw,request):
    """Remove only an exact trailing wire-citation dump, with an audit receipt.

    Short intervals, mathematical/code spans, source-printed lists, partial alias
    lists and ordinary learner statements are never changed. Structured source
    references stay intact for the original ownership/coverage validators.
    """
    aliases=request.get('aliases')
    if not isinstance(raw,dict)or not aliases:return raw,[]
    source='\n'.join(b.get('text','')for b in request['job']['blocks'])
    compact=lambda s:re.sub(r'\s+','',s)
    source=compact(source)
    pattern=re.compile(r'(?<!\S)\[(?:[a-z]+,\s*){3,}[a-z]+\](?=[ \t]*(?:\n|$))')
    protected=re.compile(r'(`{3,}|~{3,})[\s\S]*?\1|`[^`\n]*`|'
                         r'\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$')
    value=copy.deepcopy(raw);removed=[]
    for i,concept in enumerate(value.get('concepts',[])):
        for j,segment in enumerate(concept.get('segments',[])):
            text=segment.get('text')
            if not isinstance(text,str):continue
            refs=segment.get('blockIds',[])
            spans=[m.span()for m in protected.finditer(text)]
            def replace(match):
                keys=re.findall(r'[a-z]+',match[0])
                if (keys!=list(dict.fromkeys(refs))or any(k not in aliases for k in keys)
                        or compact(match[0])in source
                        or (len(keys)<6 and not text[:match.start()].rsplit('\n',1)[-1].rstrip()
                            .endswith(('.', '!', '?', '。')))
                        or any(a<=match.start()<b for a,b in spans)):
                    return match[0]
                removed.append({'conceptIndex':i,'segmentIndex':j,'wireAliases':keys,
                    'reason':'Exact trailing structured-citation duplicate; source references retained'})
                return ''
            segment['text']=pattern.sub(replace,text).rstrip()
    return (value if removed else raw),removed
