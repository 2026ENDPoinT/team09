"""Local source bundles; preserve every original fragment and pixel envelope.

Bundle formula rules contained by their native expression and adjacent paragraph
pieces. This never crosses a page, panel, heading or explicit list boundary and
never invents source words. Child records are retained for exact audit expansion.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from collections import Counter

VERSION='k122-source-bundles-v2'

def union(items):
    boxes=[b['bbox'] for b in items]
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]

def contains(a,b,tol=.003):
    return a[0]-tol<=b[0] and a[1]-tol<=b[1] and a[2]+tol>=b[2] and a[3]+tol>=b[3]

def bundle(items):
    if len(items)==1:return copy.deepcopy(items[0])
    value=copy.deepcopy(items[0]);children=[]
    for b in items:children.extend(copy.deepcopy(b.get('sourceChildren') or [b]))
    value.update(id='sb'+hashlib.sha256(json.dumps([b['id']for b in children]).encode()).hexdigest()[:20],
        bbox=union(items),text='\n'.join(b['text']for b in items if b['text']),
        wordIds=[w for b in items for w in b.get('wordIds',[])],sourceChildren=children,
        sourceBundleVersion=VERSION,hasVisual=any(b.get('hasVisual')for b in items),
        visualKinds=sorted({k for b in items for k in b.get('visualKinds',[])}))
    value['visualOnly']=not bool(value['text'].strip())
    if value['hasVisual']:value['kind']='visual' if all(b['kind']=='visual'for b in items)else 'text'
    if (value['hasVisual'] or not all(b.get('nativeTextProof')==value.get('nativeTextProof')for b in items)):
        value.pop('nativeTextProof',None)
    for key in ('geometryFallback','pageEdgeClipped'):
        if any(b.get(key)for b in items):value[key]=True
    return value

def flatten(blocks):
    return [c for b in blocks for c in b.get('sourceChildren',[b])]

def verify(original,result):
    old={b['id']:b for b in original};children=flatten(result)
    if len(old)!=len(original) or Counter(b['id']for b in children)!=Counter(old.keys()):
        raise ValueError('Source bundles must retain each original exactly once.')
    for b in children:
        if b!=old[b['id']]:raise ValueError('Source child metadata/text/geometry changed.')
    for b in result:
        parts=b.get('sourceChildren',[b])
        if len({(p['page'],p.get('zone',0),p.get('headingId'))for p in parts})!=1:
            raise ValueError('A bundle crossed its original source scope.')
        if any(not contains(b['bbox'],p['bbox'],0)for p in parts):
            raise ValueError('A source pixel envelope was lost.')
        if 'sourceBundleVersion'in b:
            if b['text']!='\n'.join(p['text']for p in parts if p['text']):
                raise ValueError('A bundle changed its original source text.')
            if Counter(b.get('wordIds',[]))!=Counter(w for p in parts for w in p.get('wordIds',[])):
                raise ValueError('A bundle lost or duplicated native word ownership.')
            if any(p.get('hasVisual')for p in parts)and not b.get('hasVisual'):
                raise ValueError('A source-bearing visual lost its image requirement.')

def coalesce(original):
    blocks=copy.deepcopy(original);attached={};taken=set()
    # Fractions exported as independent vector rules are parts of the expression.
    # Only unique containing native text can establish the owner; no nearest guess.
    for i,b in enumerate(blocks):
        if not (b.get('kind')=='visual' and not b['text'].strip() and b.get('visualKinds')==['vector']):continue
        matches=[j for j,a in enumerate(blocks)if j!=i and a.get('kind')=='text'and a['text'].strip()
            and (a['page'],a.get('zone'),a.get('headingId'))==(b['page'],b.get('zone'),b.get('headingId'))
            and contains(a['bbox'],b['bbox'])]
        if len(matches)==1:attached.setdefault(matches[0],[]).append(i);taken.add(i)
    merged=[]
    for i,b in enumerate(blocks):
        if i not in taken:merged.append(bundle([b]+[blocks[j]for j in attached.get(i,[])]))
    result=[]
    for b in merged:
        # Already typed page numbers are metadata; source bytes stay auditable.
        box=b['bbox']
        footer=(box[1]>.85 and .35<(box[0]+box[2])/2<.65 and box[3]-box[1]<.04)
        if footer and b.get('kind')=='page_number' and re.fullmatch(r'(?:[-–]\s*)?\d{1,4}(?:\s*[-–])?',b['text'].strip()):
            b['localRole']='decoration';b['sourceMetadataRole']='page_number'
            result.append(b);continue
        if result and may_join(result[-1],b):result[-1]=bundle([result[-1],b])
        else:result.append(b)
    # Annotation of a page number is not a change to its original audit child.
    for b in result:
        if b.get('sourceMetadataRole')=='page_number' and 'sourceChildren'not in b:
            b['sourceChildren']=[copy.deepcopy(next(x for x in original if x['id']==b['id']))]
    verify(original,result)
    return result

def may_join(a,b):
    if (a['page'],a.get('zone'),a.get('headingId'))!=(b['page'],b.get('zone'),b.get('headingId')):return False
    if any(x.get('localRole')for x in [a,b])or a['kind']not in ('text','caption')or b['kind']not in ('text','caption'):return False
    if a.get('geometryFallback')or b.get('geometryFallback'):return False
    if len(a['text'])+len(b['text'])>1800:return False
    # A short labelled subsection/list starts a new unit; attach its following
    # definition/formula but never absorb it into the preceding paragraph.
    if re.match(r'^(?:[①-⑳•●▪❖▶※]|[-–]\s|\(?\d+[.)]\s|(?:예제|문제)\s*\d*)',b['text'].strip()):return False
    if len(b['text'].strip())<90 and b['text'].rstrip().endswith((':','：')):return False
    x,y=a['bbox'],b['bbox'];gap=y[1]-x[3]
    overlap=min(x[2],y[2])-max(x[0],y[0]);min_width=min(x[2]-x[0],y[2]-y[0])
    continuation=(not re.search(r'[.!?。]$',a['text'].rstrip()) and gap<=min(.040,max(.012,(y[3]-y[1])*.95)))
    if not (-.004<=gap and (gap<=.026 or continuation) and overlap>=.65*min_width):return False
    if union([a,b])[3]-union([a,b])[1]>.30:return False
    # Preserve multiple text columns; centering a narrow displayed equation in
    # a broad paragraph is safe, drifting across two narrow columns is not.
    if abs(x[0]-y[0])>.045 and max(x[2]-x[0],y[2]-y[0])<.55:return False
    sa,sb=a.get('fontSize'),b.get('fontSize')
    if sa and sb and abs(sa-sb)>max(1.1,min(sa,sb)*.18):return False
    return True
