"""Local source hierarchy and ordered display metadata. Never calls a model.

Presentation is independent of generation grouping. Saved prose is copied, never
rewritten. Ambiguous layout falls back to the existing generated section.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

VERSION = 'study-hierarchy-5'
NUMBER = re.compile(r'^(\d+(?:\.\d+)*)(?:\.)?\s+\S')
NAVIGATION = re.compile(r'(?:^|\n)\s*(?:Contents\b|Table of Contents\b|Learning Objectives?\b|목차|차례|학습\s*목표)',re.I)
NON_TITLE = re.compile(r'^(?:예제|예시|보기|문제|연습문제|풀이|해설|참고|예[.\s:]|Example\b|Exercise\b|Problem\b|Solution\b|Proof\b|Let\b|따라서|그러므로|즉\s)',re.I)
QUESTIONS = re.compile(r'[?？]|(?:구하여라|구하시오|구하라|계산하라|증명하여라|하여라)[.\s]*$')
LABELS = {'정의','정리','증명','참고','주의','definition','theorem','proof','remark','contents','학습목표'}
COUNTS = {'두':2,'세':3,'네':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}


def heading_id(block_id):return 'h:'+block_id

def normalized(text):return unicodedata.normalize('NFKC',text).strip()

def title_text(text):
    # An unmapped PDF glyph is not literal learner text. Keep readable words,
    # separated rather than joined across the missing glyph; never guess it.
    text=re.sub(r'\(cid:\d+\)|\ufffd',' ',text)
    return re.sub(r'^[■▪◆◇❖▶•⚫●]\s*','',re.sub(r'[ \t]+',' ',normalized(text))).strip()


def numbered_title(text):
    match=NUMBER.match(normalized(text))
    # A bare quantity ("3000 억 토큰") is not a chapter number.
    return match if match and '.' in normalized(text).split()[0] else None

def title_like(text, *, allow_math_names=False, allow_question=False):
    value=title_text(text)
    return bool(value and len(value)<=140 and '\n' not in value
        and value.casefold() not in LABELS and not NON_TITLE.match(value)
        and (allow_question or not QUESTIONS.search(value)) and not re.search(r'[=∑∫∞→]|\\(?:frac|lim)',value)
        and (allow_math_names or not re.search(r'\b(?:lim|sin|cos)\b',value))
        and not re.fullmatch(r'[\d\W]+',value) and not re.search(r'[.!。]$',value))


def panel_key(block):return (block['page'],block.get('zone',0))

def relative_box(block):
    box=block.get('bbox');zone=block.get('zoneBounds',[0,0,1,1])
    if not box:return None
    return ((box[0]-zone[0])/max(.001,zone[2]-zone[0]),
            (box[1]-zone[1])/max(.001,zone[3]-zone[1]))


def running_titles(panels,nav_panels):
    """Recover a changing section label from a repeated top-left header track.

    Constant author/course furniture and isolated short strings never qualify.
    This uses layout tracks and consecutive repetition, not subject vocabulary.
    """
    tracks=defaultdict(dict)
    for key,items in panels.items():
        for block in items:
            box=relative_box(block)
            if block.get('localRole')!='decoration' or not box or not (box[0]<.4 and 0<=box[1]<.075):continue
            text=title_text(block.get('text','').split('\n')[0])
            if not title_like(text) or len(text)>80:continue
            track=(round(box[0]/.05),round(box[1]/.03),round(block.get('fontSize') or 0))
            tracks[track].setdefault(key,(block,text))
    eligible=[]
    for track,items in tracks.items():
        counts=Counter(text for _,text in items.values())
        if len(items)<3 or sum(count>=2 for count in counts.values())<2:continue
        eligible.append((len(items),-track[0],items))
    if not eligible:return {}
    selected=max(eligible,key=lambda item:item[:2])[2]
    result={};previous=None;keys=list(panels)
    for index,key in enumerate(keys):
        if key not in selected:continue
        block,text=selected[key]
        if key in nav_panels:
            # An objectives slide may introduce the next section. Retain only
            # its independently corroborated running header, never its list.
            # Contents pages and isolated objectives must not create chapters.
            navigation=[m.group(0).strip().casefold() for b in panels[key]
                        for m in NAVIGATION.finditer(b.get('text',''))]
            following=keys[index+1] if index+1<len(keys) else None
            objectives=bool(navigation) and all(re.match(r'(?:learning objectives?\b|학습\s*목표)',n) for n in navigation)
            if (not objectives or following not in selected or following in nav_panels
                    or following[0]-key[0]>1 or selected[following][1]!=text):continue
        if text==previous:continue
        previous=text;result[block['id']]=text
    return result


def source_headings(blocks):
    """Use numbering, real title typography and changing running section labels.

    Navigation panels and learning questions cannot own subsequent teaching.
    Numberless title levels use relative font tiers, with a shallow fallback.
    """
    blocks=list(blocks)
    if not blocks:return []
    panels={}
    for block in blocks:panels.setdefault(panel_key(block),[]).append(block)
    nav_panels={key for key,items in panels.items() if NAVIGATION.search('\n'.join(b.get('text','') for b in items))}
    running=running_titles(panels,nav_panels)
    fonts=[b['fontSize'] for b in blocks if b.get('fontSize') and b.get('kind')=='text'
           and not b.get('localRole') and len(b.get('text',''))>=15]
    body_size=statistics.median(fonts) if fonts else 0
    candidates=[]
    numbered=[(b,numbered_title(b.get('text',''))) for b in blocks if b.get('kind')=='heading']
    # Repeated slide-title geometry can distinguish a teaching question title
    # from an exercise/question embedded in the body. No subject vocabulary.
    tracks=Counter()
    for b in blocks:
        box=relative_box(b)
        if b.get('kind')=='heading' and box and box[0]<.4 and 0<=box[1]<.12:
            tracks[(round(box[0]/.05),round(box[1]/.05))]+=1
    for block in blocks:
        text=block.get('text','');number=numbered_title(text)
        if block['id'] in running:
            candidates.append((block,running[block['id']],'running',None));continue
        if panel_key(block) in nav_panels or block.get('localRole') in ('decoration','exercise'):continue
        if re.match(r'^\s*[①-⑳]',text):continue
        box=relative_box(block);font=block.get('fontSize') or 0
        prominent=bool(font and body_size and font>body_size*1.12)
        question_title=bool(not number and block.get('kind')=='heading' and prominent and box
            and box[0]<.4 and 0<=box[1]<.12 and tracks[(round(box[0]/.05),round(box[1]/.05))]>=3)
        if not title_like(text,allow_question=question_title):continue
        if block.get('localRole')=='navigation':
            # A standalone chapter is structural only when actual numbered
            # child headings corroborate it; a contents/objective panel is not.
            if not number or not any(m and m[1].startswith(number[1]+'.')
                and panel_key(b) not in nav_panels for b,m in numbered):continue
        if number and block.get('kind')=='heading':
            candidates.append((block,title_text(text),'numbered',tuple(number[1].split('.'))));continue
        marked=bool(re.match(r'^\s*[■▪◆◇▶]',text))
        at_top=bool(box and box[0]<.4 and box[1]<.26)
        if (marked and block.get('kind')=='heading') or (at_top and prominent):
            candidates.append((block,title_text(text),'marked' if marked else 'title',None))
        elif block.get('kind')=='heading' and not font and not box:
            candidates.append((block,title_text(text),'title',None))
    # Some formula-heavy slides are extracted as one whole-page visual. When
    # its first line exactly repeats an adjacent, independently detected slide
    # title, retain that title boundary too. No OCR or guessed topic name.
    detected=list(candidates);candidate_ids={b['id'] for b,_,_,_ in detected}
    for block in blocks:
        box=block.get('bbox',[]);zone=block.get('zoneBounds',[0,0,1,1])
        if (block['id'] in candidate_ids or block.get('kind')!='visual' or len(box)!=4
                or panel_key(block) in nav_panels or block.get('localRole') in ('decoration','exercise')):continue
        area=(box[2]-box[0])*(box[3]-box[1])/max(.001,(zone[2]-zone[0])*(zone[3]-zone[1]))
        lines=block.get('text','').splitlines()
        if area<.65 or len(lines)<2:continue
        first=title_text(lines[0])
        match=next((item for item in detected if item[2]=='title' and abs(item[0]['page']-block['page'])==1
                    and first.casefold()==item[1].casefold()),None)
        if match:candidates.append(({**block,'fontSize':match[0].get('fontSize')},first,'title',None))
    positions={b['id']:i for i,b in enumerate(blocks)}
    candidates.sort(key=lambda item:positions[item[0]['id']])
    top_fonts=[b.get('fontSize') or 0 for b,_,kind,_ in candidates if kind in ('title','marked')
               and relative_box(b) and 0<=relative_box(b)[1]<.12]
    # A single oversize chapter slide should not define every other slide's
    # font tier. Use the upper quartile of actual top-position title sizes.
    top_font=sorted(top_fonts)[(len(top_fonts)-1)*3//4] if top_fonts else 0
    nodes=[];stack=[];running_node=None;last_candidate=None
    for block,text,kind,number in candidates:
        if kind=='running':
            level=1;running_node=None
        elif kind=='numbered':
            parents=[n for n in stack if n.get('_number') and len(n['_number'])<len(number)
                     and number[:len(n['_number'])]==n['_number']]
            parent=parents[-1] if parents else None
            level=parent['level']+1 if parent else 1
            if parent:stack=stack[:stack.index(parent)+1]
            else:running_node=None
        else:
            font=block.get('fontSize') or 0
            # Nearby font sizes at the same slide-title position are peers.
            # Otherwise a 32pt "heart" heading can become a child of 36pt "blood".
            box=relative_box(block)
            if (len(top_fonts)>=3 and box and 0<=box[1]<.12 and font>=top_font*.85
                    and not re.match(r'^\d+[):]',text)):font=max(font,top_font)
            numeric=next((n for n in reversed(stack) if n.get('_number')),None)
            base=running_node['level'] if running_node else numeric['level'] if numeric else 0
            # Compare actual active ancestors, not a global tier number. With
            # a missing font tier, clamping the first sibling's depth previously
            # made the next same-size sibling a child of the first one.
            parent=next((n for n in reversed(stack) if n['level']>base and font
                         and n.get('_font',0)*.85>font),None)
            level=parent['level']+1 if parent else base+1
            item=re.match(r'^(\d{1,2})[)]\s+',text)
            previous=next((n for n in reversed(stack) if item and n.get('_list')==int(item[1])-1),None)
            if previous:level=previous['level']
        level=min(4,level)
        while stack and stack[-1]['level']>=level:stack.pop()
        level=min(level,len(stack)+1)
        parent=stack[-1] if stack else None
        if parent and same_title(text,parent['title']):continue
        parent_id=parent['id'] if parent else ''
        # Consecutive slide continuations share a source heading. A later
        # return after a different heading remains a distinct occurrence.
        if (last_candidate and kind in ('title','marked','running')
                and last_candidate[0]['parentId']==parent_id
                and last_candidate[0]['level']==level
                and title_text(text).casefold()==title_text(last_candidate[0]['title']).casefold()
                and block['page']-last_candidate[1]<=1):
            last_candidate[0]['lastHeadingPage']=block['page']
            stack.append(last_candidate[0]);last_candidate=(last_candidate[0],block['page'])
            continue
        node={'id':heading_id(block['id']),'parentId':parent['id'] if parent else '',
            'title':text,'level':level,'startBlockId':block['id'],'page':block['page'],
            'sourceHeading':True,'sourceKind':kind,'_number':number,
            '_font':font if kind in ('title','marked') else 0,
            '_list':int(re.match(r'^(\d{1,2})[)]\s+',text)[1]) if re.match(r'^(\d{1,2})[)]\s+',text) else None}
        nodes.append(node);stack.append(node);last_candidate=(node,block['page'])
        if kind=='running':running_node=node
    for node in nodes:node.pop('_number',None);node.pop('_font',None);node.pop('_list',None)
    nodes=span_headings(nodes,blocks)
    positions={b['id']:i for i,b in enumerate(blocks)}
    structural_starts={n['startBlockId'] for n in nodes}
    # A complete, explicitly named classification is a bounded source parent.
    # Numbering alone does not join unrelated chapters or unfinished lists.
    for i,block in enumerate(blocks):
        text=normalized(block.get('text',''))
        count=re.search(r'(?<![\w])([2-9]|1\d|20|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:가지|종류|유형)',text)
        if (not count or len(text)>100 or '\n' in text or panel_key(block) in nav_panels
                or any(n['startBlockId']==block['id'] for n in nodes)):continue
        size=int(count[1]) if count[1].isdigit() else COUNTS[count[1]];expected=1;end=None
        for item in blocks[i+1:]:
            if item['id'] in structural_starts:break
            if item.get('kind')=='page_number' or item.get('localRole')=='decoration':continue
            raw=item.get('text','').strip();number=ord(raw[0])-ord('①')+1 if raw and '①'<=raw[0]<='⑳' else None
            numbered_item=re.match(r'^(?:\((\d{1,2})\)|(\d{1,2})[.):])\s+',normalized(raw))
            if number is None and numbered_item:number=int(next(x for x in numbered_item.groups() if x))
            if number!=expected or item.get('hasVisual'):break
            expected+=1
            if number==size:end=item;break
        if end is None:continue
        owners=[n for n in nodes if positions[n['startBlockId']]<=i<=positions[n['endBlockId']]]
        parent=max(owners,key=lambda n:n['level']) if owners else None
        level=parent['level']+1 if parent else 1
        if level>4:continue
        nodes.append({'id':heading_id(block['id']),'parentId':parent['id'] if parent else '',
            'title':text,'level':level,'startBlockId':block['id'],'page':block['page'],
            'sourceHeading':True,'sourceKind':'classification','bounded':True,'endBlockId':end['id']})
    return span_headings(nodes,blocks)


def span_headings(nodes,blocks):
    positions={b['id']:i for i,b in enumerate(blocks)}
    copied=[copy.deepcopy(n) for n in nodes if n.get('startBlockId') in positions]
    copied.sort(key=lambda n:(positions[n['startBlockId']],n['level']))
    for i,node in enumerate(copied):
        end=next((positions[n['startBlockId']]-1 for n in copied[i+1:] if n['level']<=node['level']),len(blocks)-1)
        end=max(positions[node['startBlockId']],end)
        if node.get('bounded'):end=min(end,positions[node['endBlockId']])
        node['endBlockId']=blocks[end]['id'];node['endPage']=blocks[end]['page']
    return copied


def options_for(job,nodes,blocks):
    positions={b['id']:i for i,b in enumerate(blocks)}
    selected=[positions[b['id']] for b in job['blocks'] if b['id'] in positions]
    if not selected:return []
    low,high=min(selected),max(selected)
    return [{k:n[k] for k in ('id','parentId','title','level','startBlockId','endBlockId','page')}
            for n in nodes if positions.get(n.get('startBlockId'),-1)<=high and positions.get(n.get('endBlockId'),-1)>=low]


def placement(concept,job):
    options=job.get('headingOptions',[]);known={n['id']:n for n in options}
    order={b['id']:i for i,b in enumerate(job['blocks'])}
    first=min((order[r] for r in concept.get('blockIds',[]) if r in order),default=0)
    candidates=[n for n in options if order.get(n['startBlockId'],-1)<=first<=order.get(n['endBlockId'],len(order))]
    key=max(candidates,key=lambda n:n['level'])['id'] if candidates else ''
    return {'headingId':key,'headingMode':'body' if key and (same_title(concept.get('title',''),known[key]['title']) or known[key]['level']>=4) else 'child'}


def same_title(a,b):
    def clean(text):
        text=re.sub(r'\([^)]*\)|（[^）]*）','',title_text(text))
        # Equivalent count/list wording is typography, not a second topic.
        # Preserve quantity: "3가지" and "4가지" are not chapter prefixes.
        text=re.sub(r'^(?:\d+(?:\.\d+)*\.?)\s+(?!가지|종류|유형)','',text)
        text=re.sub(r'(두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*가지',lambda m:str(COUNTS[m[1]])+'가지',text)
        text=re.sub(r'가지\s*(?:종류|유형)의?\s*','가지',text)
        return re.sub(r'\s+','',text).casefold()
    return clean(a)==clean(b)


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]


def decorate(result,blocks=(),headings=()):
    """Construct an ordered outline while walking the unchanged prose once.

    A closed branch is a separate occurrence if cited again. Equal concept
    titles never globally coalesce. This construction preserves reading order
    without a reviewer, repair pass, or model-based quality pipeline.
    """
    value=copy.deepcopy(result);blocks=list(blocks);positions={b['id']:i for i,b in enumerate(blocks)}
    source=copy.deepcopy(list(headings) or source_headings(blocks));base={n['id']:n for n in source}
    nodes=[];known={};open_base=[];open_nodes=[];children=Counter();content_seen=Counter();leaf_seen=Counter()
    def add(node):
        node['contentIds']=[];nodes.append(node);known[node['id']]=node
        if node['parentId']:children[node['parentId']]+=1
        return node
    for section_index,section in enumerate(value.get('sections',[])):
        entries=section.get('parts') or [section]
        if section.get('parts'):
            # Separate repeated references to the same in-memory dict too;
            # each saved/rendered occurrence needs its own display identity.
            entries=[dict(part) for part in entries];section['parts']=entries
        section_anchor=next((e.get('sourceId') for e in section.get('evidence',[]) if e.get('sourceId')),None)
        section_pages=section.get('visualPages') or [e['page'] for e in section.get('evidence',[]) if e.get('page')]
        section_start=min(section_pages) if section_pages else None
        fallback=None
        for part in entries:
            refs=[e['sourceId'] for e in part.get('evidence',[]) if e.get('sourceId')]
            at=min((positions[r] for r in refs if r in positions),default=None)
            pages=part.get('visualPages') or [e['page'] for e in part.get('evidence',[]) if e.get('page')]
            pages=pages or [1];anchor=blocks[at]['id'] if at is not None else refs[0] if refs else section_anchor or digest([section.get('title'),part.get('title'),part.get('body')])
            owners=[n for n in source if at is not None and positions.get(n.get('startBlockId'),-1)<=at<=positions.get(n.get('endBlockId'),-1)]
            owner=max(owners,key=lambda n:n['level']) if owners else None
            # Typography alone is weak evidence for extending a subsection
            # into a *different* generated topic on a later page. Keep that
            # already-known topic under the nearest strong ancestor instead.
            demoted=False
            while (owner and owner.get('sourceKind')=='title' and owner.get('parentId')
                   and section_start is not None and section_start>owner.get('lastHeadingPage',owner['page'])
                   and not same_title(section.get('title',''),owner['title'])):
                owner=base.get(owner['parentId']);demoted=True
            path=[]
            while owner:
                path.append(owner);owner=base.get(owner.get('parentId'))
            path.reverse()
            # Generated section names can be raw equation/example fragments.
            # They are not structural evidence. Keep the existing concept
            # leaves under the source ancestor instead of adding that wrapper.
            section_title=section.get('title','')
            usable_section=title_like(section_title,allow_math_names=True)
            if demoted and path and path[-1]['level']<4 and usable_section:
                path.append({'id':'section:'+digest([path[-1]['id'],section.get('title'),section_anchor or anchor]),
                    'parentId':path[-1]['id'],'title':section['title'],'level':path[-1]['level']+1,
                    'page':section_start or min(pages),'endPage':max(section_pages or pages),'sourceHeading':False})
            if not path:
                # With no source ancestor, a meaningful existing concept is
                # safer than inventing a replacement for an unusable section.
                # Give each occurrence its own root; never merge its prose.
                concept_root=not usable_section and title_like(part.get('title',''),allow_math_names=True)
                if concept_root:
                    path=[{'id':'concept-root:'+digest([section_index,anchor,part.get('title')]),
                        'parentId':'','title':part['title'],'level':1,'page':min(pages),
                        'endPage':max(pages),'sourceHeading':False}]
                elif fallback is None:
                    key='legacy:'+digest([section.get('title'),section_anchor or anchor])
                    fallback={'id':key,'parentId':'','title':section.get('title') or '학습 내용','level':1,
                              'page':min(pages),'endPage':max(pages),'sourceHeading':False}
                if not path:path=[fallback]
            common=0
            while common<min(len(path),len(open_base)) and path[common]['id']==open_base[common]:common+=1
            open_base=open_base[:common];open_nodes=open_nodes[:common]
            for item in path[common:]:
                parent=open_nodes[-1] if open_nodes else None;key=item['id']
                if key in known:
                    stem=key+':'+digest([anchor,parent['id'] if parent else '',part.get('title')]);key=stem;occurrence=1
                    while key in known:key=stem+':'+str(occurrence);occurrence+=1
                node=copy.deepcopy(item);node.update(id=key,parentId=parent['id'] if parent else '',level=(parent['level']+1 if parent else 1))
                add(node);open_base.append(item['id']);open_nodes.append(node)
            parent=open_nodes[-1];key=parent['id']
            # Body can directly define a source heading at its start. A later
            # occurrence after child topics is a new leaf, not text pulled up.
            direct=same_title(part.get('title',''),parent['title']) and not children[key]
            if parent['level']<4 and not direct:
                token=[key,normalized(part.get('title','')),anchor]
                leaf='c:'+digest(token);occurrence=leaf_seen[leaf];leaf_seen[leaf]+=1
                if occurrence:leaf+=':'+digest([refs,part.get('body'),occurrence])
                node=add({'id':leaf,'parentId':key,'title':part.get('title') or parent['title'],
                    'level':parent['level']+1,'page':min(pages),'endPage':max(pages),'sourceHeading':False})
                key=node['id']
            content='content:'+digest([key,part.get('title'),refs,part.get('body')])
            duplicate=content_seen[content];content_seen[content]+=1
            if duplicate:content+=':'+str(duplicate)
            part.update(nodeId=key,contentId=content)
            known[key]['contentIds'].append(content)
            known[key]['endPage']=max(known[key].get('endPage',known[key]['page']),max(pages))
    for node in reversed(nodes):
        node['endPage']=max(node.get('endPage',node['page']),node['page'])
        parent=known.get(node.get('parentId'))
        if parent:parent['endPage']=max(parent.get('endPage',parent['page']),node['endPage'])
        for field in ('page','endPage'):
            node['pageLabel' if field=='page' else 'endPageLabel']=value.get('_pageLabels',{}).get(str(node[field]),str(node[field]))
    value['hierarchy']={'version':VERSION,'documentId':value.get('documentId'),'sourceFingerprint':value.get('sourceFingerprint'),
        'scope':value.get('scope'),'page':value.get('page',0),'nodes':nodes}
    value.pop('_pageLabels',None)
    return value


def export(folder,result):
    (Path(folder)/'hierarchy.json').write_text(json.dumps(result.get('hierarchy',{}),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
