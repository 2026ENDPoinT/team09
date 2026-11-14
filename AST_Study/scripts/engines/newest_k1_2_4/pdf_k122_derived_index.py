"""Derive a duplicate source index from model-written MAIN citations only.

No learner text, source claims or exclusions are synthesized. Missing main
citations stay blank and go through the original omission checks. The exact
schema/source ownership validator still runs after the duplicate index expands.
"""
import copy

VERSION='k122-derived-main-index-v1'
RULES='''Every supplied target must be grounded in its own source IDs. Cite each
taught source directly in the MAIN definition/explanation segment that actually
teaches its contribution. For an integrated formula or relationship cite every
constituent target ID there. Do not cite a generic sentence for a missing condition,
case or method: include that contribution in the main explanation first. Excluded
or uncertain targets must have their own supported exclusion/uncertain segment.
The application constructs the duplicate source index from these actual MAIN
segment citations. Do not output a separate sourceCoverage field. Easy explanation,
sourceSetup, a table or a sequence alone never substitutes for MAIN teaching.\n'''

def encode(format):
    value=copy.deepcopy(format);root=value['json_schema']['schema']
    del root['properties']['sourceCoverage'];root['required'].remove('sourceCoverage')
    return value

def expand(raw,exact):
    if not isinstance(raw,dict)or 'sourceCoverage'in raw:raise ValueError('Unexpected duplicate source index.')
    root=exact['json_schema']['schema'];ids=root['$defs']['studySourceId']['enum'];allowed=set(ids)
    references={}
    concepts=raw.get('concepts')
    if not isinstance(concepts,list):raise ValueError('Concepts must be a list.')
    for i,c in enumerate(concepts):
        if not isinstance(c,dict)or not isinstance(c.get('segments'),list):raise ValueError('Invalid concept segments.')
        for j,s in enumerate(c['segments']):
            if not isinstance(s,dict)or not isinstance(s.get('blockIds'),list):raise ValueError('Invalid source citations.')
            if any(not isinstance(k,str)or k not in allowed for k in s['blockIds']):raise ValueError('Foreign source citation.')
            if len(s['blockIds'])!=len(set(s['blockIds'])):raise ValueError('Duplicate source citation.')
            if s.get('kind')in ('definition','explanation')and isinstance(s.get('text'),str)and s['text'].strip():
                for key in s['blockIds']:references.setdefault(key,{'conceptIndex':i,'segmentIndex':j})
    value=copy.deepcopy(raw)
    value['sourceCoverage']=[{'blockId':key,'mainSegmentRef':references.get(key)}for key in ids]
    return value
