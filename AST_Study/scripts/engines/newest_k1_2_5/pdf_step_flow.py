"""Source-grounded ordered study cards and lossless ordinary-prose fallback."""
import copy
import secrets

ORDER_KINDS = ('process', 'procedure', 'derivation', 'cycle')
ORDER_POLICY = """Use a step card only for a source-taught process with at least THREE distinct
substantive stages whose order is essential: an earlier output/state/operation is needed
by a later stage, or the source explicitly teaches a causal mechanism, derivation or cycle.
Swapping adjacent stages must change the process/result, not merely the presentation.
Types, categories, properties, principles, parallel tips, comparison rows, maturity levels,
a ranked hierarchy or a chronology alone are NOT a process. Numbering, arrows, action verbs,
'first/next', or a title saying 'process' do not establish stage dependence.
A valid two-stage process stays in ordinary explanation; never split, pad or invent stages
just to reach three. Preserve the source's actual stages, conditions, branches and feedback.
Do not serialize mutually exclusive branches or parallel paths as successive stages.
Default to no sequence when uncertain. Keep the explanation understandable without a card.
For each proposed card give orderKind=process/procedure/derivation/cycle and exactly one
transition for each adjacent pair (zero-based fromStep=i,toStep=i+1). Each transition needs
a concise, specific relation describing what passes/changes/depends on the previous stage,
its actual source blockIds, and a short literal sourceQuote showing that relationship.
Use the source's stage labels; relation names both actual stages and their connection,
not 'step 1 precedes step 2'. A property/rank/type is not a changing state merely because
it can be numbered or drawn with an arrow. Do not turn parallel advice into a workflow.
For an image-only source set sourceQuote="" and describe the visible labels/arrows and
what moves/changes in relation; never invent a verbatim quote for an image.
A broad paragraph reused as every transition's evidence is not sufficient by itself.
Do not manufacture a causal relationship between independent facts to justify a card.
"""
POLICY = "Optional sequence module: default sequence to null. " + ORDER_POLICY + """
Each step has title/body, optional context/insight, and this task's source evidence.
Transition blockIds are the supplied sourceId values. Ordinary explanation still preserves
all teaching when no card is appropriate. The app controls presentation; never executable markup.
"""


def plain_sequence(flow, existing=''):
    """Keep every supported stage detail as unordered prose, without implying order."""
    rows=[]
    steps=flow.get('steps',[])
    if not isinstance(steps,list):return ''
    for step in steps:
        if not isinstance(step,dict):continue
        title=step.get('title','');body=step.get('body','')
        if not isinstance(title,str) or not isinstance(body,str) or not title.strip() or not body.strip():continue
        details=[body]
        for field in ('context','insight'):
            value=step.get(field,'')
            if isinstance(value,str) and value.strip() and value not in details:
                details.append(value)
        detail='\n\n'.join(details)
        # Indent continuation lines so formulas, code and paragraphs stay in
        # their own list item; do not flatten a multi-paragraph source reading.
        rows.append('- **'+title.strip()+'**\n\n  '+detail.replace('\n','\n  '))
    title=flow.get('title','')
    if rows and isinstance(title,str) and title.strip():rows.insert(0,'**'+title.strip()+'**')
    return '\n\n'.join(rows)


def append_sequence_fallback(block, flow):
    field='body' if 'body' in block else 'explanation'
    current=block.get(field,'')
    if not isinstance(current,str):current=''
    addition=plain_sequence(flow,current)
    if addition:block[field]='\n\n'.join(v for v in (current,addition) if v)
    evidence=block.setdefault('evidence',[])
    if isinstance(evidence,list):
        for step in flow.get('steps',[]) if isinstance(flow.get('steps'),list) else []:
            if not isinstance(step,dict):continue
            refs=step.get('evidence',[])
            for item in refs if isinstance(refs,list) else []:
                if not isinstance(item,dict):continue
                if item not in evidence:evidence.append(copy.deepcopy(item))
    return addition


def normalize_existing_flows(result):
    """Upgrade saved/partial/map output locally; never delete its stage teaching.

    Historical modules have no independent transition witnesses. They become
    ordinary prose rather than being retrospectively called certified processes.
    A model's new card is admitted only by assess_sequence during validation.
    """
    from pdf_step_flow_policy import VERSION, is_eligible_module
    def walk(node):
        additions=[]
        if isinstance(node,dict):
            for name,child in list(node.items()):
                if name not in ('evidence','stepFlow','sourceSetup') and isinstance(child,(dict,list)):
                    additions.extend(walk(child))
            if additions and isinstance(node.get('parts'),list) and isinstance(node.get('body'),str):
                # Keep an aggregate's existing introduction, equations and
                # headings, rather than reconstructing it from just its parts.
                node['body']='\n\n'.join([node['body']]+additions)
            flow=node.get('stepFlow')
            if isinstance(flow,dict) and not is_eligible_module(flow):
                addition=append_sequence_fallback(node,flow);node.pop('stepFlow',None)
                if addition:additions.append(addition)
        elif isinstance(node,list):
            for child in node:additions.extend(walk(child))
        return additions
    walk(result)
    result['stepFlowPolicyVersion']=VERSION
    return result


def validate_sequence(value, allowed, review_evidence, *, allow_plain=False):
    from pdf_step_flow_policy import assess_sequence
    if not isinstance(value, dict) or not isinstance(value.get('title'), str) or not value['title'].strip():
        return None
    steps=value.get('steps')
    if not isinstance(steps,list) or not steps:return None
    result=[]
    for step in steps:
        if not isinstance(step,dict) or any(not isinstance(step.get(k),str) or not step[k].strip() for k in ('title','body')):
            return None
        if any(not isinstance(step.get(k,''),str) for k in ('context','insight')):return None
        requested=step.get('evidence')
        if not isinstance(requested,list) or not requested:return None
        exact_items=[]
        for item in requested:
            if not isinstance(item,dict):return None
            source=allowed.get(item.get('sourceId'));quote=item.get('quote')
            if source is None or not isinstance(quote,str) or not quote.strip():return None
            source_text=source.get('text','')
            if quote not in source_text:
                position=source_text.casefold().find(quote.casefold())
                if position<0:return None
                item={**item,'quote':source_text[position:position+len(quote)]}
            exact_items.append(item)
        evidence,incomplete=review_evidence(exact_items,allowed)
        if not evidence or incomplete or any(e.get('quoteAdjusted') for e in evidence):return None
        result.append({'title':step['title'],'body':step['body'],'context':step.get('context',''),
                       'insight':step.get('insight',''),'evidence':evidence})
    eligibility=assess_sequence(value,result,allowed)
    if eligibility is None and not allow_plain:return None
    flow={'moduleId':'synesis.step-flow','schemaVersion':1,'variant':secrets.choice(('a','d')),
          'title':value['title'],'steps':result}
    if eligibility is not None:flow['eligibility']=eligibility
    return flow
