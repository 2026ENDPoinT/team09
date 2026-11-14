"""Continue proven numbered source units through their subordinate headings.

Only existing, mutually corroborated source headings supply unit boundaries.
Generated job boundaries and topic words are never structural evidence.
"""
import copy
import hashlib
from collections import defaultdict

from pdf_numbering_context import _ordinal, _lane

VERSION='source-unit-continuity-1'


def continue_units(blocks,headings):
    from pdf_study_hierarchy import relative_box, span_headings
    nodes=copy.deepcopy(list(headings));known={n['id']:n for n in nodes}
    by_id={b['id']:({**b,**{k:b['nativeHeading'][k] for k in ('fontSize','bbox')}}
        if isinstance(b.get('nativeHeading'),dict) else b) for b in blocks}
    pos={b['id']:i for i,b in enumerate(blocks)}
    children=defaultdict(list)
    for node in nodes:children[node.get('parentId','')].append(node)
    streams=defaultdict(list);series=[]
    def geometry(node):return relative_box(by_id[node['startBlockId']])
    def compatible(left,right):
        a=by_id[left['startBlockId']];b=by_id[right['startBlockId']]
        x=geometry(left);y=geometry(right);fa=a.get('fontSize') or 0;fb=b.get('fontSize') or 0
        return (x and y and _lane(a)==_lane(b) and abs(x[0]-y[0])<=.02
                and fa and fb and abs(fa-fb)<=max(1,max(fa,fb)*.08)
                and left['level']==right['level'])
    for node in nodes:
        block=by_id.get(node.get('startBlockId'));parent=known.get(node.get('parentId'))
        tag=_ordinal(node.get('title',''))
        if (not block or not parent or not tag or tag[0]=='decimal' or node.get('bounded')
                or node.get('sourceKind') not in ('list','title') or node['level']>=4
                or node.get('structuralRole')=='numbered_heading'):continue
        key=(parent['id'],tag[0],_lane(block))
        previous=streams.get(key)
        if previous and compatible(previous[-1][0],node) and previous[-1][1][1]+1==tag[1]:
            previous.append((node,tag))
        else:
            previous=[(node,tag)];streams[key]=previous;series.append(previous)
    accepted=[items for items in series if len(items)>=2 and items[0][1][1]==1]
    for items in accepted:
        parent=known[items[0][0]['parentId']]
        scope=hashlib.sha256((parent['id']+'\0'+items[0][0]['id']).encode()).hexdigest()[:16]
        unit_ids={n['id'] for n,_ in items}
        peers=list(children[parent['id']])
        for index,(unit,tag) in enumerate(items):
            start=pos[unit['startBlockId']]
            end=pos[items[index+1][0]['startBlockId']]-1 if index+1<len(items) else pos[parent['endBlockId']]
            own=by_id[unit['startBlockId']];box=geometry(unit);font=own.get('fontSize') or 0
            attached=[]
            for peer in peers:
                at=pos[peer['startBlockId']]
                if not start<at<=end or peer['id'] in unit_ids:continue
                source=by_id[peer['startBlockId']];pb=geometry(peer);pf=source.get('fontSize') or 0
                descendants=[];todo=[peer]
                while todo:
                    item=todo.pop();descendants.append(item);todo.extend(children.get(item['id'],[]))
                # Never swallow a new column, outdented section, explicit
                # numbered branch, or a branch that would exceed display depth.
                suitable=(peer.get('sourceKind') in ('title','marked') and not _ordinal(peer.get('title',''))
                    and pb and box and _lane(source)==_lane(own) and pb[0]>=box[0]-.02
                    and (not pf or pf<=font*1.08)
                    and max(n['level'] for n in descendants)<4)
                if not suitable:
                    end=at-1;break
                attached.append((peer,descendants))
            unit.update(sourceKind='list',structuralRole='numbered_unit',bounded=True,
                endBlockId=blocks[end]['id'],endPage=blocks[end]['page'],
                sourceUnit={'version':VERSION,'scopeId':scope,'scheme':tag[0],'ordinal':tag[1],
                            'parentId':parent['id'],'endBlockId':blocks[end]['id']})
            for peer,descendants in attached:
                peer['parentId']=unit['id']
                for node in descendants:node['level']+=1
    return span_headings(nodes,blocks)
