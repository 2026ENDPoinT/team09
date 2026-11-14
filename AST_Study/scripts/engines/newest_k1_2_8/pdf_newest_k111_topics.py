"""Document-local topic anchors for the existing grouping call; no remote I/O.

Names are presentation, source heading IDs are identity. An inferred topic stays
unanchored unless the planner explicitly selects an eligible, in-scope heading.
This module never guesses synonyms or merges concepts by lexical similarity.
"""
from __future__ import annotations

import re
import copy

VERSION = 'source-topic-anchors-4'



def response_format(base, options):
    """Each path label and its ID are one schema item, never parallel arrays."""
    result=copy.deepcopy(base)
    item=result['json_schema']['schema']['properties']['groups']['items']['properties']['topicPath']['items']
    # _object schemas reuse string descriptors. Replace this property rather
    # than mutating it: deepcopy preserves aliasing with the title descriptor.
    item['properties']['sourceHeadingId']={'type':'string','enum':['']+[n['id'] for n in options]}
    return result


def model_path(value):
    if not isinstance(value,list):return [],[]
    if all(isinstance(item,dict) for item in value):
        return [item.get('title','') for item in value],[item.get('sourceHeadingId','') for item in value]
    # Unanchored strings support offline/older local fixtures, never infer IDs.
    if all(isinstance(item,str) for item in value):return value,['']*len(value)
    return [],[]

def source_catalog(blocks, headings):
    from pdf_newest_k111_hierarchy import title_like, NAVIGATION
    positions = {b['id']:i for i,b in enumerate(blocks)}
    by_id = {b['id']:b for b in blocks}
    known = {n['id']:n for n in headings}
    result = {}
    for node in headings:
        start, end = node.get('startBlockId'), node.get('endBlockId')
        title = node.get('title', '')
        block = by_id.get(start, {})
        if (start not in positions or end not in positions or positions[start]>positions[end]
                or node.get('sourceKind') not in ('numbered','title','running','list')
                or block.get('localRole') in ('decoration','navigation','exercise')
                or not title_like(title) or NAVIGATION.search(title)
                or re.fullmatch(r'\([^)]*\)',title)
                or re.search(r'\d{4}\s*년\s*\d\s*학기|\b(?:semester|copyright)\b',title,re.I)):
            continue
        result[node['id']] = {'id':node['id'], 'title':title, 'parentId':node.get('parentId',''),
            'level':node['level'], 'page':node['page'], 'endPage':by_id[end]['page'],
            '_first':positions[start], '_last':positions[end]}
    # A rejected cover/attribute cannot silently become an anchor through a child.
    # Retain the nearest eligible ancestor, with cycle protection for saved input.
    for node in result.values():
        parent=node['parentId'];seen={node['id']}
        while parent and parent not in result and parent not in seen:
            seen.add(parent);parent=known.get(parent,{}).get('parentId','')
        node['parentId']=parent if parent in result and parent not in seen else ''
    return result


def window_context(targets, blocks, catalog, *, has_before=None, has_after=None):
    """Only intersecting source scopes, including ancestors outside this window.

    IDs are document-local heading IDs, not compact target IDs. Scope indices are
    relative to this window and cannot assign out-of-window teaching content.
    """
    positions={b['id']:i for i,b in enumerate(blocks)}
    selected=[positions[b['id']] for b in targets]
    if not selected:return []
    options=[]
    for node in catalog.values():
        # Only transport boundaries need additional ancestry context. Inline
        # titles are already in targets; presenting all of them as candidates
        # biases the planner toward typography instead of semantic families.
        if has_before is not None or has_after is not None:
            if not ((has_before and node['_first']<min(selected)<=node['_last'])
                    or (has_after and node['_first']<=max(selected)<node['_last'])):continue
        hits=[i for i,pos in enumerate(selected) if node['_first']<=pos<=node['_last']]
        if not hits:continue
        options.append({k:node[k] for k in ('id','title','parentId','level','page','endPage')}
                       | {'firstTarget':hits[0],'lastTarget':hits[-1]})
    available={n['id'] for n in options}
    for node in options:
        if node['parentId'] not in available:node['parentId']=''
    return options


def validated_ids(path, requested, group_blocks, blocks, catalog):
    """Reject foreign/out-of-scope IDs, repeated IDs and contradictory ancestry.

    Shared scope alone never merges labels: an explicit selection is required.
    A group crossing a source boundary falls back instead of being majority-voted
    into either section. Inferred entries keep an empty ID.
    """
    empty=['']*len(path)
    if not isinstance(requested,list) or len(requested)!=len(path):return empty
    positions={b['id']:i for i,b in enumerate(blocks)}
    # A heading may travel with its next body during partition normalization.
    # All assigned sources must still fit the chosen source scope.
    owned=[positions[b['id']] for b in group_blocks if b.get('id') in positions]
    if not owned or len(owned)!=len(group_blocks):return empty
    accepted=[];previous='';seen=set()
    for key in requested:
        if not isinstance(key,str):return accepted+['']*(len(path)-len(accepted))
        if not key:
            accepted.append('');continue
        node=catalog.get(key)
        if (not node or key in seen or not node['_first']<=min(owned)<=max(owned)<=node['_last']):
            return accepted+['']*(len(path)-len(accepted))
        ancestors=set();parent=node.get('parentId','')
        while parent in catalog and parent not in ancestors:
            ancestors.add(parent);parent=catalog[parent].get('parentId','')
        if previous and previous not in ancestors:return accepted+['']*(len(path)-len(accepted))
        accepted.append(key);seen.add(key);previous=key
    return accepted


def bind_groups(groups, blocks, catalog):
    """Change metadata only after all existing partition guards have run."""
    for group in groups:
        path=group.get('topicPath') or []
        group['topicSourceIds']=validated_ids(path,group.get('topicSourceIds'),
                                              group['blocks'],blocks,catalog)
    return groups
