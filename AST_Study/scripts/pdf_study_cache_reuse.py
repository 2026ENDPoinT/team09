"""Conservative local reuse of paid study replies across source-layout/check upgrades."""
from __future__ import annotations
import copy
import json
from pathlib import Path

from pdf_group_partition import validate_partition


_PLAN_ANNOTATIONS = ('planRole', 'planRoleBeforeVisualGuard', 'visualReadingRequired')


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def repair_source_ids(raw, allowed):
    """Recover only one omitted ASCII letter, with exactly one allowed candidate.

    No edit-distance guesses, numeric substitutions, or replacement of valid IDs.
    """
    value=copy.deepcopy(raw)
    if not isinstance(value,dict):return value
    allowed=set(allowed);repairs={}
    def resolve(key):
        if not isinstance(key,str) or key in allowed or len(key)<5:return key
        candidates={candidate for candidate in allowed if len(candidate)==len(key)+1
            and any(char.isascii() and char.isalpha() and candidate[:i]+candidate[i+1:]==key
                    for i,char in enumerate(candidate))}
        if len(candidates)==1:
            repairs[key]=next(iter(candidates));return repairs[key]
        return key
    def walk(node):
        if isinstance(node,dict):
            for name,item in node.items():
                if name=='blockId':node[name]=resolve(item)
                elif name=='blockIds' and isinstance(item,list):node[name]=[resolve(x) for x in item]
                elif isinstance(item,(list,dict)):walk(item)
        elif isinstance(node,list):
            for item in node:walk(item)
    walk(value)
    if repairs:value['sourceIdRepairs']=[{'from':a,'to':b,'reason':'unique_omitted_letter'} for a,b in repairs.items()]
    return value


def constrained_format(template, job):
    """The API may select only source IDs in this request, including nested steps."""
    value=copy.deepcopy(template);ids=[b['id'] for b in job['blocks']]
    ref={'$ref':'#/$defs/studySourceId'}
    def walk(node):
        if isinstance(node,dict):
            properties=node.get('properties',{})
            if 'blockId' in properties:properties['blockId']=copy.deepcopy(ref)
            if 'blockIds' in properties:
                # Templates reuse the same string-array object for references,
                # table headers/rows and internal math checks. deepcopy retains
                # those aliases: mutating items in place constrains ALL of them
                # to source IDs. Detach the reference property first.
                source_ids=copy.deepcopy(properties['blockIds'])
                source_ids['items']=copy.deepcopy(ref)
                properties['blockIds']=source_ids
            for item in node.values():walk(item)
        elif isinstance(node,list):
            for item in node:walk(item)
    walk(value)
    value['json_schema']['schema'].setdefault('$defs',{})['studySourceId']={'type':'string','enum':ids}
    return value


def block_key(block):
    # Never reuse merely because page numbers or positional IDs match.
    return (block['page'],block.get('zone',0),block.get('kind'),block.get('text',''),
            tuple(round(float(v),7) for v in block['bbox']),
            bool(block.get('hasVisual')),tuple(block.get('visualKinds',[])))


def source_mapping(old, new):
    if (not isinstance(old,list) or not isinstance(new,list)
            or any(not isinstance(b,dict) or not isinstance(b.get('id'),str) or not b['id']
                   for b in old+new)
            or len({b['id'] for b in old})!=len(old)
            or len({b['id'] for b in new})!=len(new)):return None
    lookup={}
    try:
        for block in new:lookup.setdefault(block_key(block),[]).append(block)
        mapped={};used=set()
        for block in old:
            options=lookup.get(block_key(block),[])
            if len(options)!=1 or options[0]['id'] in used:return None
            mapped[block['id']]=options[0];used.add(options[0]['id'])
    except (KeyError,TypeError,ValueError,OverflowError):return None
    return mapped


def _mapped_recovery(recovery, mapping, old_blocks, groups):
    """Rebind source-accounting metadata, without rewriting diagnostic prose.

    Old proofs are never trusted. Each window names its exact canonical source
    IDs so its proof can be checked and recomputed after positional IDs change.
    Unknown raw response IDs in diagnostics remain historical evidence.
    """
    if not isinstance(recovery,dict):raise ValueError('Invalid assignment recovery')
    old_lookup={b['id']:b for b in old_blocks}
    value=copy.deepcopy(recovery)
    def walk(node):
        if isinstance(node,dict):
            for name,item in node.items():
                if name=='blockId' and isinstance(item,str):
                    if item in mapping:node[name]=mapping[item]['id']
                elif name=='blockIds' or name.endswith('BlockIds'):
                    if not isinstance(item,list) or any(not isinstance(key,str) or key not in mapping for key in item):
                        raise ValueError('Unknown recovery source ID')
                    node[name]=[mapping[key]['id'] for key in item]
                elif name!='coverageProof' and isinstance(item,(dict,list)):walk(item)
        elif isinstance(node,list):
            for item in node:walk(item)
    walk(value)
    windows=recovery.get('windows',[])
    if not isinstance(windows,list):raise ValueError('Invalid assignment windows')
    for original,window in zip(windows,value.get('windows',[])):
        ids=original.get('sourceBlockIds') if isinstance(original,dict) else None
        if (not isinstance(ids,list) or not ids or len(set(ids))!=len(ids)
                or any(key not in old_lookup for key in ids)):
            raise ValueError('Missing canonical recovery window sources')
        positions={b['id']:i for i,b in enumerate(old_blocks)}
        if [positions[key] for key in ids]!=sorted(positions[key] for key in ids):
            raise ValueError('Reordered recovery window sources')
        mapped_ids={mapping[key]['id'] for key in ids}
        selected=[{**group,'blocks':[b for b in group['blocks'] if b['id'] in mapped_ids]}
                  for group in groups]
        selected=[group for group in selected if group['blocks']]
        window['coverageProof']=validate_partition([mapping[key] for key in ids],selected,
                                                  require_global_order=False)
    return value


def reuse_plan(folder, cache, document, strategy, scope, page, blocks, *, planner_identity=None):
    """Retain exact old regions; attach only newly visible edge text to one owner.

    Non-edge additions, removed/changed regions, or ambiguous ownership require
    ordinary planning. The caller never mutates the historical plan/replies.
    """
    roots=sorted((Path(folder)/'generated'/strategy).glob('*/manifest.json'),
                 key=lambda p:p.stat().st_mtime_ns,reverse=True)
    for manifest_path in roots:
        root=manifest_path.parent
        if root==cache:continue
        result=read(root/'result.json') or read(root/'partial.json')
        plan=read(root/'plan.json');manifest=read(manifest_path)
        if not isinstance(result,dict) or not isinstance(plan,dict) or not isinstance(manifest,dict):continue
        if (plan.get('status')!='confirmed' or plan.get('warnings')
                or planner_identity is not None and plan.get('plannerIdentity')!=planner_identity):continue
        if any(result.get(k)!=v for k,v in {'documentId':document['documentId'],
                'sourceFingerprint':document['fingerprint'],'scope':scope,'page':page,'strategy':strategy}.items()):continue
        groups=plan.get('groups',[])
        old=read(root/'blocks.json')
        # A cached plan cannot certify itself: validate against the separately
        # saved extraction, including locally skipped source regions.
        try:validate_partition(old,groups,require_global_order=False)
        except (ValueError,KeyError,TypeError,OverflowError):continue
        mapping=source_mapping(old,blocks)
        if mapping is None:continue
        known={b['id'] for b in mapping.values()};extra=[b for b in blocks if b['id'] not in known]
        if any(not b.get('pageEdgeClipped') or not b.get('text','').strip() for b in extra):continue
        copied=[{**copy.deepcopy(g),'blocks':[{**copy.deepcopy(mapping[b['id']]),
                  **{key:copy.deepcopy(b[key]) for key in _PLAN_ANNOTATIONS if key in b}}
                  for b in g['blocks']]} for g in groups]
        owners={}
        for block in extra:
            choices=[i for i,g in enumerate(copied) if any(
                (b['page'],b.get('zone',0))==(block['page'],block.get('zone',0)) for b in g['blocks'])]
            # Only an unambiguous panel owner may absorb a newly visible caption.
            if len(choices)!=1:break
            owners[block['id']]=choices[0]
        else:
            order={b['id']:i for i,b in enumerate(blocks)}
            for block in extra:
                copied[owners[block['id']]]['blocks'].append({**copy.deepcopy(block),'planRole':'teaching'})
            for group in copied:group['blocks'].sort(key=lambda b:order[b['id']])
            try:
                proof=validate_partition(blocks,copied,require_global_order=False)
                recovery=(_mapped_recovery(plan['assignmentRecovery'],mapping,old,copied)
                          if 'assignmentRecovery' in plan else None)
            except (ValueError,KeyError,TypeError,OverflowError):continue
            try:
                headings=copy.deepcopy(plan.get('headings',[]))
                if (not isinstance(headings,list) or any(not isinstance(node,dict)
                        or not isinstance(node.get('id'),str)
                        or any(node.get(name) not in mapping for name in ('startBlockId','endBlockId'))
                        for node in headings)):continue
                heading_ids={n['id']:'h:'+mapping[n['startBlockId']]['id'] for n in headings
                             if n.get('startBlockId') in mapping}
                for node in headings:
                    node['id']=heading_ids.get(node['id'],node['id'])
                    node['parentId']=heading_ids.get(node.get('parentId'),node.get('parentId',''))
                    for name in ('startBlockId','endBlockId'):
                        if node.get(name) in mapping:node[name]=mapping[node[name]]['id']
            except (KeyError,TypeError,AttributeError):continue
            return {**{k:plan[k] for k in ('plannerIdentity','status') if k in plan},
                    'groups':copied,'warnings':plan.get('warnings',[]),
                    'headings':headings,
                    'sourcePartition':proof,
                    **({'assignmentRecovery':recovery} if recovery is not None else {}),
                    'reusedFrom':str(root),'addedEdgeBlockIds':[b['id'] for b in extra]},manifest
    return None,None


def reusable_reply(root, old_jobs, job):
    """Reuse only an identical complete source set; rebind positional IDs by region."""
    new_keys={block_key(b) for b in job['blocks']}
    for old in old_jobs:
        if old.get('skip') or len(old['blocks'])!=len(job['blocks']):continue
        if old.get('contextDepth',1)!=job.get('contextDepth',1):continue
        if {block_key(b) for b in old['blocks']}!=new_keys:continue
        raw=read(Path(root)/f'response-{old["id"]}.json')
        if raw is None:continue
        mapping=source_mapping(old['blocks'],job['blocks'])
        if mapping is None:continue
        value=repair_source_ids(raw,[b['id'] for b in old['blocks']])
        old_options={n['id']:n for n in old.get('headingOptions',[])}
        for concept in value.get('concepts',[]):
            heading=old_options.get(concept.get('headingId'))
            if heading:
                matches=[n['id'] for n in job.get('headingOptions',[])
                         if (n['title'],n['level'],n['page'])==(heading['title'],heading['level'],heading['page'])]
                concept['headingId']=matches[0] if len(matches)==1 else ''
        def walk(node):
            if isinstance(node,dict):
                for name,item in node.items():
                    if name=='blockId' and item in mapping:node[name]=mapping[item]['id']
                    elif name=='blockIds' and isinstance(item,list):
                        node[name]=[mapping[x]['id'] if x in mapping else x for x in item]
                    elif isinstance(item,(dict,list)):walk(item)
            elif isinstance(node,list):
                for item in node:walk(item)
        walk(value)
        return value,{'response':str(Path(root)/f'response-{old["id"]}.json'),
                      'sourceIdRepairs':value.get('sourceIdRepairs',[])}
    return None,None
