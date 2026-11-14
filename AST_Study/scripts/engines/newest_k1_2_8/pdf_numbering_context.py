"""One local, source-ordered numbering pass. No model, files, or canonical edits.

Existing source relations are anchors. Only independently supported text labels
are added; ambiguous lists retain their previous projection. State is detached
and read-only so parallel teaching jobs do not depend on completion order.
"""
from __future__ import annotations
import copy
import hashlib
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from types import MappingProxyType
from pdf_heading_signals import marker, exercise_fragments

VERSION='numbering-context-1'


@dataclass(frozen=True)
class TagState:
    scheme: str
    ordinal: int
    parent_id: str
    scope_id: str
    lane: tuple
    page: int
    body_end: str
    reasons: tuple


@dataclass(frozen=True)
class NumberingContext:
    headings: tuple
    parents: object
    closures: object
    states: object
    stats: object


def _ordinal(text):
    scheme,value,_=marker(text)
    if isinstance(value,tuple):
        if len(value)!=1:return None  # Explicit 6.1 / 6.1.1 paths remain authoritative.
        if scheme=='korean':
            letter=chr(value[0]);alphabet='가나다라마바사아자차카타파하'
            if letter not in alphabet:return None
            number=alphabet.index(letter)+1
        else:number=value[0]
    elif scheme=='circle':number=value
    elif scheme=='wrapped-letter':number=ord(value.lower())-96
    elif scheme=='roman':
        values={'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
        number=0;previous=0
        for letter in reversed(value):
            current=values[letter];number+=-current if current<previous else current;previous=max(previous,current)
    else:return None
    return (scheme,number) if 0<number<=100 else None


def _lane(block):
    zone=block.get('zoneBounds',[0,0,1,1])
    # Vertical print panels share a reading lane; independent columns do not.
    return (round(zone[0],2),round(zone[2]-zone[0],2))


def build_context(blocks,baseline_headings):
    from pdf_study_hierarchy import title_like, relative_box, title_text, heading_id
    from pdf_source_owner_index import SourceIndex
    blocks=list(blocks);baseline=list(baseline_headings)
    result=[copy.deepcopy(n) for n in baseline]
    source=SourceIndex(blocks,baseline);positions=source.positions;by_id=source.by_id
    nodes={n['id']:n for n in result};starts={n.get('startBlockId'):n for n in baseline}
    boxes=[relative_box(b) for b in blocks];lanes=[_lane(b) for b in blocks]
    skip_roles={'navigation','decoration','exercise'}
    panels=defaultdict(list)
    for b in blocks:panels[(b['page'],b.get('zone',0))].append(b)
    body_fonts={key:statistics.median(fonts) for key,items in panels.items()
        if (fonts:=[b['fontSize'] for b in items if b.get('kind')=='text' and b.get('fontSize')
                    and len(b.get('text',''))>=20 and b.get('localRole') not in skip_roles])}
    exercises=exercise_fragments(panels)
    tags=[_ordinal(b.get('text','')) for b in blocks]
    def aligned(i,j):
        return bool(boxes[i] and boxes[j] and lanes[i]==lanes[j] and abs(boxes[i][0]-boxes[j][0])<=.02)
    def significant(i):
        b=blocks[i]
        return b.get('localRole') not in ('navigation','decoration') and bool(b.get('text','').strip() or b.get('hasVisual'))
    def body_end(i):
        """At most a panel's owned body; nested lists are not sibling labels."""
        b=blocks[i];box=boxes[i];end=None;started=False
        for j in range(i+1,len(blocks)):
            other=blocks[j];ob=boxes[j]
            if other['page']!=b['page'] or lanes[j]!=lanes[i] or other['id'] in starts:break
            if not significant(j):continue
            if tags[j] and aligned(i,j):break
            if not ob:break
            inset=ob[0]>box[0]+.018
            smaller=bool(b.get('fontSize') and other.get('fontSize')
                         and other['fontSize']<b['fontSize']*.94)
            bullet=marker(other.get('text',''))[0].startswith('bullet:')
            text=other.get('text','').strip()
            paragraph=len(text)>=25 and (text.endswith(('.','。')) or '\n' in text)
            box_raw=other.get('bbox',[0,0,0,0]);visual=other.get('hasVisual') and (box_raw[2]-box_raw[0])*(box_raw[3]-box_raw[1])>.02
            if not inset and not (bullet and smaller):break
            if bullet or visual or inset and paragraph:started=True
            elif not started:break
            end=j
        return end
    def path_contains(node_id,ancestor):
        seen=set()
        while node_id and node_id not in seen:
            if node_id==ancestor:return True
            seen.add(node_id);node_id=nodes.get(node_id,{}).get('parentId','')
        return False
    # Current sequence per lane/style/indent. There is no dependency on a model
    # reply, nor any mutation of the blocks that identify paid requests.
    sequences=[];active=defaultdict(list);events=[];open_bodies=[];virtuals={}
    present_pages={b['page'] for b in blocks}
    for i,b in enumerate(blocks):
        tag=tags[i]
        if not tag or not boxes[i] or b['id'] in exercises or b.get('localRole') in skip_roles:continue
        # Expired bodies cannot frame a later nested label. Retaining just the
        # currently open intervals avoids rescanning all earlier flat labels.
        open_bodies[:]=[old for old in open_bodies if old['end']>=i]
        anchor=starts.get(b['id']);owner=source.owner(b['id'])
        if anchor:
            parent=nodes.get(anchor.get('parentId'))
            if not parent:continue
            end=min(positions.get(anchor.get('endBlockId'),i),len(blocks)-1)
        else:
            if (b.get('kind')!='text' or not title_like(b.get('text',''))
                    or len(b.get('text',''))>140):continue
            font=body_fonts.get((b['page'],b.get('zone',0)),0)
            if boxes[i][1]>.8 and font and b.get('fontSize') and b['fontSize']<font*.75:continue
            parent=nodes.get(owner['id']) if owner else None;end=body_end(i)
            if end is None:continue
            # Nested schemes are framed by the enclosing label's independently
            # owned body. Their parent is tentative until its own series passes.
            enclosing=next((old for old in reversed(open_bodies) if old['index']<i<=old['end']
                and lanes[old['index']]==lanes[i] and boxes[i][0]>boxes[old['index']][0]+.025
                and nodes[old['parent']]['level']<3),None)
            if enclosing:
                key=heading_id(blocks[enclosing['index']]['id'])
                parent=nodes.get(key)
                if parent is None:
                    parent={'id':key,'parentId':enclosing['parent'],'level':nodes[enclosing['parent']]['level']+1,
                        'startBlockId':blocks[enclosing['index']]['id'],'endBlockId':blocks[enclosing['end']]['id'],
                        'page':blocks[enclosing['index']]['page'],'sourceKind':'list'}
                    nodes[key]=parent;virtuals[key]=parent
            if parent is None:
                # A vertically printed next panel can continue a proven lane
                # even though raw zone IDs differ within the physical page.
                for stream in reversed(active[(lanes[i],tag[0])]):
                    previous=stream[-1]
                    if aligned(i,previous['index']) and tag[1]==previous['tag'][1]+1:
                        candidate=nodes[previous['parent']]
                        if positions.get(candidate.get('endBlockId'),-1)>=i:parent=candidate
                        break
        if not parent or parent['level']>=4 or parent.get('sourceKind')=='classification':continue
        item={'index':i,'tag':tag,'end':end,'parent':parent['id'],'anchor':anchor['id'] if anchor else None}
        candidates=active[(lanes[i],tag[0])]
        previous=None
        for stream in reversed(candidates):
            last=stream[-1];j=last['index'];root=nodes[last['parent']]
            if not aligned(i,j) or positions.get(root.get('endBlockId'),-1)<i:continue
            # An explicit anchor's parent wins. A soft candidate may pop only
            # through the preceding anchored item's own descendant branch.
            same_parent=item['parent']==last['parent']
            nested=not anchor and last['anchor'] and path_contains(item['parent'],last['anchor'])
            gap=b['page']-blocks[j]['page']
            gap_supported=gap<=1
            if not gap_supported and last['anchor']:
                old_anchor=nodes[last['anchor']]
                last_page=blocks[positions.get(old_anchor.get('endBlockId'),j)]['page']
                gap_supported=(last_page>=b['page']-1 and all(p in present_pages for p in range(blocks[j]['page'],b['page']+1)))
            if same_parent or nested:
                if tag[1]==last['tag'][1]+1 and gap>=0 and gap_supported:
                    item['parent']=last['parent'];previous=stream
                break  # Reset/out-of-sequence must not reopen an older stream.
        if previous is not None:previous.append(item)
        else:
            stream=[item];candidates.append(stream);sequences.append(stream)
        events.append(item);open_bodies.append(item)
    parents={};states={};closures={};approved=[];added=[]
    eligible=[stream for stream in sequences if len(stream)>=2 and stream[0]['tag'][1]==1]
    # A nested series cannot manufacture a parent from one ambiguous outer item.
    eligible_ids={heading_id(blocks[item['index']]['id']) for stream in eligible for item in stream}
    for stream in eligible:
        if stream[0]['parent'] in virtuals and stream[0]['parent'] not in eligible_ids:continue
        parent=nodes[stream[0]['parent']]
        scope=hashlib.sha256((parent['id']+'\0'+stream[0]['tag'][0]+'\0'+blocks[stream[0]['index']]['id']).encode()).hexdigest()[:16]
        approved.append(stream)
        for k,item in enumerate(stream):
            b=blocks[item['index']];end=item['end']
            if k+1<len(stream):end=min(end,stream[k+1]['index']-1)
            state=TagState(item['tag'][0],item['tag'][1],parent['id'],scope,lanes[item['index']],b['page'],blocks[end]['id'],
                           ('ordered_sequence','independent_body' if not item['anchor'] else 'existing_source_anchor','aligned_reading_lane'))
            states[b['id']]=state
            if item['anchor']:continue
            parents[b['id']]=parent['id']
            added.append({'id':heading_id(b['id']),'parentId':parent['id'],'title':title_text(b['text']),
                'level':parent['level']+1,'startBlockId':b['id'],'endBlockId':blocks[end]['id'],
                'page':b['page'],'endPage':blocks[end]['page'],'sourceHeading':True,'sourceKind':'list','bounded':True,
                'structuralRole':'numbered_heading','numberingContext':{'scopeId':scope,'scheme':state.scheme,'ordinal':state.ordinal,
                    'parentId':state.parent_id,'bodyEndBlockId':state.body_end,'version':VERSION}})
    # A new, outdented introduction with a fresh inset series is independent
    # evidence that a weak list container has ended. Protect chapter numbers
    # and every already recognized later child branch from truncation.
    for stream in approved:
        parent=nodes[stream[0]['parent']]
        if parent['id'] in virtuals:continue  # New labels already have independently bounded bodies.
        if parent.get('sourceKind') not in ('marked','title','list'):continue
        last=stream[-1];end=last['end'];last_box=boxes[last['index']]
        upper=min(len(blocks),positions.get(parent.get('endBlockId'),end)+1)
        for i in range(end+1,upper):
            intro=blocks[i];ib=boxes[i]
            if intro['id'] in starts:break
            intro_text=intro.get('text','').strip()
            intro_like=title_like(intro_text,allow_question=True) or (len(intro_text)<=160 and '\n' not in intro_text
                and not re.search(r'[=∑∫∞→]|\\(?:frac|sum)',intro_text))
            if (intro['page']-blocks[end]['page'] not in (0,1) or not ib or lanes[i]!=lanes[last['index']]
                    or intro.get('kind')!='text' or tags[i] or intro['id'] in exercises
                    or not intro_like or ib[0]>last_box[0]+.015):continue
            fresh=[]
            for j in range(i+1,len(blocks)):
                child=blocks[j];cb=boxes[j]
                if child['page']!=intro['page'] or lanes[j]!=lanes[i] or child['id'] in starts:break
                if not significant(j) or not cb:continue
                if cb[0]<=ib[0]+.018 and not (tags[j] and ib[0]<last_box[0]-.02 and cb[0]>=ib[0]-.01):break
                if tags[j]:fresh.append(j)
                if len(fresh)>=2:break
            if (len(fresh)==2 and tags[fresh[0]][1]==1 and tags[fresh[1]][1]==2
                    and tags[fresh[0]][0]==tags[fresh[1]][0] and aligned(*fresh)):
                descendants=[n for n in result if n['id']!=parent['id'] and path_contains(n['id'],parent['id'])]
                later_child=any(positions[n['startBlockId']]>end for n in descendants)
                if not later_child:
                    cap=blocks[end]['id'];closures[parent['id']]=cap
                    parent.update(endBlockId=cap,endPage=blocks[end]['page'],bounded=True,
                        numberingBoundary={'introBlockId':intro['id'],'reason':'new_inset_series_after_outdented_introduction','version':VERSION})
                    # A source child's old broad span must not escape the
                    # independently established end of its whole container.
                    # Keep every existing parent edge and all learner content.
                    for child in descendants:
                        if positions[child['endBlockId']]>end:
                            child.update(endBlockId=cap,endPage=blocks[end]['page'],bounded=True)
                break
    # A reset may have invalidated a later tentative series under the old
    # weak container. Preserve its content for the ordinary ancestor fallback.
    retained=[]
    live={n['id']:n for n in result}
    # Parents are evaluated first. A rejected outer label cannot leave behind
    # nested children pointing to a tentative node that never became a heading.
    for node in sorted(added,key=lambda n:n['level']):
        parent=live.get(node['parentId'])
        if parent is None or positions[node['startBlockId']]>positions[parent['endBlockId']]:
            parents.pop(node['startBlockId'],None);states.pop(node['startBlockId'],None);continue
        if positions[node['endBlockId']]>positions[parent['endBlockId']]:
            node['endBlockId']=parent['endBlockId'];node['endPage']=parent['endPage']
            node['numberingContext']['bodyEndBlockId']=node['endBlockId']
        retained.append(node);live[node['id']]=node
    added=retained
    result.extend(added)
    result.sort(key=lambda n:(positions.get(n.get('startBlockId'),-1),n['level']))
    for ref,state in list(states.items()):
        cap=live[state.parent_id]['endBlockId']
        if positions[state.body_end]>positions[cap]:states[ref]=replace(state,body_end=cap)
    return NumberingContext(tuple(result),MappingProxyType(parents),MappingProxyType(closures),MappingProxyType(states),
        MappingProxyType({'blocks':len(blocks),'number_labels':len(events),'accepted_sequences':len(approved),
                          'added_labels':len(added),'closed_parents':len(closures)}))
