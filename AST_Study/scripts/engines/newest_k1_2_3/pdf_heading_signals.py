"""Document-layout evidence for headings; no subject terms, model, or I/O.

Combine sibling repetition, relative typography, indentation and owned body
blocks inside each page/column. Font size alone never creates a local parent.
"""
import re
import unicodedata

BULLETS = '■▪▫◆◇❖▶▷►▸▹•‣∙●○◦⚫☐□'
MARKER = re.compile(r'^\s*(['+re.escape(BULLETS)+r'])\s*')
PREFIX = re.compile(r'^\s*(?:(\d+(?:\.\d+)*)([.):])|\((\d+)\)|([A-Za-z])([.)])|([가-하])[.)])\s*(?=\S)')


def marker(text):
    raw=text.strip()
    if raw and '①' <= raw[0] <= '⑳':
        return ('circle', ord(raw[0])-ord('①')+1, raw[1:].strip())
    text=unicodedata.normalize('NFKC',raw)
    match=MARKER.match(text)
    if match:return ('bullet:'+match[1],None,text[match.end():].strip())
    roman=re.match(r'^([IVXLCDM]{1,8})[.)]\s+(?=\S)',text)
    if roman:return ('roman',roman[1],text[roman.end():].strip())
    wrapped_letter=re.match(r'^\(([A-Za-z])\)\s*(?=\S)',text)
    if wrapped_letter:return ('wrapped-letter',wrapped_letter[1],text[wrapped_letter.end():].strip())
    match=PREFIX.match(text)
    if not match:return ('',None,text)
    number,ending,wrapped,letter,letter_end,korean=match.groups()
    if number:
        scheme='decimal' if '.' in number or ending=='.' else 'number'+ending
        ordinal=tuple(int(n) for n in number.split('.'))
    elif wrapped:scheme='wrapped';ordinal=(int(wrapped),)
    elif letter:scheme='letter:'+letter_end;ordinal=(ord(letter.lower())-96,)
    else:scheme='korean';ordinal=(ord(korean),)
    return scheme,ordinal,text[match.end():].strip()


def strip_prefix(text):
    return marker(text)[2]


def same_font(a,b):
    x=a.get('fontSize') or 0;y=b.get('fontSize') or 0
    return bool(x and y and abs(x-y)<=max(.75,max(x,y)*.035))


def body_after(block,panels):
    """A short label needs its own body, before the next source heading."""
    items=panels.get((block['page'],block.get('zone',0)),[])
    try:index=next(i for i,b in enumerate(items) if b['id']==block['id'])
    except StopIteration:return []
    body=[]
    for item in items[index+1:]:
        if item.get('kind')=='heading':break
        if (item.get('localRole') in ('decoration','navigation','exercise')
                or item.get('kind') in ('page_number','caption')
                or not item.get('text','').strip() and not item.get('hasVisual')):continue
        body.append(item)
    return body


def nested_heading_after(block,panels,box):
    """A parent may introduce only children, without an introductory paragraph."""
    items=panels.get((block['page'],block.get('zone',0)),[])
    try:index=next(i for i,b in enumerate(items) if b['id']==block['id'])
    except StopIteration:return False
    parent_box=box(block)
    if not parent_box:return False
    child=next((b for b in items[index+1:] if b.get('kind')=='heading'),None)
    if not child or not body_after(child,panels):return False
    child_box=box(child)
    if not child_box:return False
    parent_font=block.get('fontSize') or 0;child_font=child.get('fontSize') or 0
    distinct_size=bool(parent_font>child_font>0 and not same_font(block,child))
    indent=child_box[0]>parent_box[0]+.025
    parent_marker=marker(block.get('text',''))[0];child_marker=marker(child.get('text',''))[0]
    family=bool(parent_marker and not parent_marker.startswith('bullet:') and child_marker
                and child_marker!=parent_marker)
    return distinct_size or indent or family


def exercise_fragments(panels):
    """Exclude explicit multiple-choice regions, not rhetorical lecture titles."""
    excluded=set()
    for items in panels.values():
        for index,prompt in enumerate(items):
            text=prompt.get('text','').strip()
            explicit=bool(re.match(r'^(?:Q[.：:)\s]|Question\b|문제\s*\d|연습문제|예제\s*\d)',text,re.I))
            if not explicit and not re.search(r'[?？]|(?:고르시오|선택하시오)',text):continue
            region=[];choices=[]
            for child in items[index+1:]:
                scheme,ordinal,_=marker(child.get('text',''))
                choice=bool(ordinal and scheme in ('number)','wrapped','circle','letter:)','letter:.','wrapped-letter'))
                if child.get('kind')=='heading' and not choice:break
                region.append(child)
                if choice:choices.append(ordinal)
            if len(choices)>=2 and len(set(choices))==len(choices):
                excluded.add(prompt['id']);excluded.update(b['id'] for b in region)
    return excluded


def question_title_supported(block,blocks,panels,box,body_size):
    """Require independently corroborated heading style or a local parent."""
    if block.get('kind')!='heading' or not block.get('fontSize'):return False
    own_box=box(block);scheme=marker(block.get('text',''))[0]
    if not own_box or not (body_after(block,panels) or nested_heading_after(block,panels,box)):return False
    def local_support(child):
        if not marker(child.get('text',''))[0]:return False
        for parent in panels.get((child['page'],child.get('zone',0)),[]):
            if parent['id']==child['id']:break
            if (parent.get('kind')=='heading' and (parent.get('fontSize') or 0)>(child.get('fontSize') or 0)
                    and not same_font(parent,child)
                    and parent.get('localRole') not in ('decoration','navigation','exercise')):return True
        return False
    if local_support(block):return True
    for peer in blocks:
        if (peer['id']==block['id'] or peer.get('kind')!='heading' or not same_font(peer,block)
                or peer.get('localRole') in ('decoration','navigation','exercise')):continue
        if (re.search(r'[?？]|(?:구하시오|증명하여라|고르시오)',peer.get('text',''))
                and not local_support(peer)):continue
        peer_box=box(peer)
        if not peer_box or abs(peer_box[0]-own_box[0])>.04:continue
        peer_scheme=marker(peer.get('text',''))[0]
        if scheme and peer_scheme==scheme:return True
        if own_box[1]<.2 and peer_box[1]<.2:return True
    return False


def local_parents(candidates,panels,box,*,peers=None):
    """Return supported local edges; an explicit empty parent starts a column."""
    grouped={}
    for item in candidates:
        b=item[0];grouped.setdefault((b['page'],b.get('zone',0)),[]).append(item)
    result={}
    for panel,items in grouped.items():
        active=[];seen=[]
        # A repeated marker at the same indentation/size is a peer signal,
        # not a universal ranking of diamonds, squares, circles or numbers.
        def peer(a,b):
            ma=marker(a.get('text',''))[0];mb=marker(b.get('text',''))[0]
            ba=box(a);bb=box(b)
            return (ma==mb and ba and bb and abs(ba[0]-bb[0])<.025
                    and (same_font(a,b) or not a.get('fontSize') and not b.get('fontSize')))
        for item in items:
            child=item[0];cb=box(child);cm=marker(child.get('text',''))[0]
            bodies=body_after(child,panels)
            if not cb:seen.append(child);continue
            active_ids={b['id'] for b in active}
            sibling=next((old for old in reversed(seen) if peer(old,child)
                and (old['id'] in active_ids or result.get(old['id']) in active_ids)),None)
            # An absent local edge does not mean the first peer has no global
            # chapter parent. Let the source walk inherit that resolved parent.
            if sibling is not None and peers is not None:peers[child['id']]=sibling['id']
            if sibling is not None and sibling['id'] in result:
                result[child['id']]=result[sibling['id']]
            else:
                parent=None
                for old in reversed(active):
                    ob=box(old);om=marker(old.get('text',''))[0]
                    if not ob or peer(old,child):continue
                    cf=child.get('fontSize') or 0;of=old.get('fontSize') or 0
                    smaller=bool(cf and of and of>cf and not same_font(old,child))
                    indented=cb[0]>ob[0]+.025
                    repeated=bool(cm and sum(peer(other[0],child) for other in items)>=2)
                    # Body indentation/typography corroborates a candidate;
                    # an isolated large quantity or ordinary bullet is not a title.
                    owned=bool(bodies and any((box(b) and box(b)[0]>=cb[0]-.015)
                        and (not cf or not b.get('fontSize') or b['fontSize']<=cf) for b in bodies))
                    family=bool(repeated and cm!=om and not om.startswith('bullet:'))
                    if owned and (smaller or indented and (not of or not cf or cf<=of) or family):
                        parent=old;break
                if parent is not None:result[child['id']]=parent['id']
                elif not seen and panel[1]!=0:result[child['id']]=''
                elif sibling is not None:result[child['id']]=''
            parent_id=result.get(child['id'])
            if parent_id is not None:
                if not parent_id:active=[]
                else:
                    while active and active[-1]['id']!=parent_id:active.pop()
            active.append(child);seen.append(child)
    return result
