"""Read-only compatibility for already saved v3/v4 paid replies.
No generation prompt/schema/admission policy, reviewer or user-data writes.
"""
from __future__ import annotations
import copy,json
SUPPORTED_VERSIONS=('source-teaching-content-v3','source-teaching-content-v4')

def active(value):
    return isinstance(value,dict) and value.get('contentContract')in SUPPORTED_VERSIONS


def materialize(value, prepare_text, math_issues):
    """Route explicit processing records; never guess a channel from wording."""
    result=[];mentions=[]
    diagnostics=value.setdefault('processingDiagnostics',[])
    records=value.get('diagnostics',[])
    if not isinstance(records,list):records=[records]
    for item in records:
        if not isinstance(item,dict):continue
        ids=item.get('blockIds',[])
        if not isinstance(ids,list) or any(not isinstance(i,str)for i in ids):
            raise ValueError('처리 기록의 원문 ID 형식이 올바르지 않아요.')
        diagnostics.append({'stage':'content_contract',**copy.deepcopy(item)})
        if item.get('kind')in ('reading_gap','unsupported_inference'):
            value['uncertainBlocks'].extend({'blockId':i,'reason':str(item.get('reason',''))}for i in ids)
    for entry in value['concepts']:
        if not isinstance(entry,dict) or entry.get('presentation')not in ('concept','mention'):
            raise ValueError('학습 내용의 표현 단위가 올바르지 않아요.')
        fields={'definition':[],'explanation':[],'easyExplanation':[]};ids=[];mention_text=[]
        for segment in entry.get('segments',[]):
            if not isinstance(segment,dict):raise ValueError('학습 문단 형식이 올바르지 않아요.')
            kind=segment.get('kind');refs=segment.get('blockIds');text=segment.get('text')
            if (not isinstance(text,str) or not isinstance(refs,list) or not refs
                    or any(not isinstance(i,str)for i in refs)):
                raise ValueError('학습 문단의 내용·근거 형식이 올바르지 않아요.')
            if kind not in (*fields,'source_condition','mention'):
                diagnostics.append({'stage':'content_contract','kind':'invalid_learner_channel','blockIds':refs})
                value['uncertainBlocks'].extend({'blockId':i,'reason':'invalid_learner_channel'}for i in refs)
                continue
            text=prepare_text(text)
            if not text.strip() or math_issues(text):
                diagnostics.append({'stage':'content_contract','kind':'invalid_supported_text','blockIds':refs})
                value['uncertainBlocks'].extend({'blockId':i,'reason':'invalid_supported_text'}for i in refs)
                continue
            if entry['presentation']=='mention':mention_text.append(text)
            elif kind=='mention':fields['explanation'].append(text)
            else:fields['explanation'if kind=='source_condition'else kind].append(text)
            ids.extend(refs)
        shared={k:copy.deepcopy(v)for k,v in entry.items()if k!='segments'}
        shared.update(blockIds=list(dict.fromkeys(ids)),_paragraphScoped=True,_contentContract=value['contentContract'])
        if entry['presentation']=='mention':
            if mention_text:mentions.append({**shared,'text':'\n\n'.join(mention_text)})
        elif fields['definition'] or fields['explanation']:
            result.append({**shared,**{k:'\n\n'.join(v)for k,v in fields.items()}})
    value['concepts']=result;value['mentions']=mentions
    return value


def processing_records(value,allowed):
    """Keep orphan processing references internal; never remap learner evidence."""
    if not active(value):return copy.deepcopy(value),[]
    value=copy.deepcopy(value);valid=[];rejected=[];allowed=set(allowed)
    records=value.get('diagnostics',[])
    if not isinstance(records,list):records=[records]
    for item in records:
        if (not isinstance(item,dict)or set(item)!={'kind','blockIds','reason'}
                or item.get('kind')not in ('reading_gap','unsupported_inference','selection_note')
                or not isinstance(item.get('reason'),str)):
            rejected.append({'stage':'processing_contract','kind':'invalid_internal_record','original':item});continue
        refs=item.get('blockIds')if isinstance(item,dict)else None
        if not isinstance(refs,list)or any(not isinstance(i,str)for i in refs):
            rejected.append({'stage':'processing_contract','kind':'invalid_internal_record','original':item});continue
        orphan=[i for i in refs if i not in allowed]
        if orphan:
            rejected.append({'stage':'processing_contract','kind':'foreign_internal_reference',
                'originalBlockIds':orphan,'reason':item.get('reason','')})
            item['blockIds']=[i for i in refs if i in allowed]
            if not item['blockIds']:continue
        valid.append(item)
    valid.extend({'kind':'selection_note','blockIds':[],
                  'reason':'processing_contract: '+json.dumps(note,ensure_ascii=False,separators=(',',':'))}
                 for note in rejected)
    value['diagnostics']=valid
    return value,rejected


def compose(raw, parts, cards, allowed, evidence):
    """Compose existing fact text; empty/bad optional links do not erase facts."""
    by_title={};all_titles=[]
    for i,part in enumerate(parts):
        title=part['title'];by_title.setdefault(title,[]).append(('concept',i));all_titles.append(title)
    mentions=[]
    for mention in raw.get('mentions',[]):
        refs=mention.get('blockIds',[])
        if not refs or any(i not in allowed for i in refs):raise ValueError('언급에 원문 영역 밖의 근거가 있어요.')
        refs=list(dict.fromkeys(refs));node={'title':mention['title'],'body':mention['text'],
            'easyExplanation':'','evidence':[evidence(allowed[i])for i in refs],
            'visualPages':sorted({allowed[i]['page']for i in refs}),
            'standardKnowledgeUsed':mention.get('standardKnowledgeUsed')is True,'presentation':'mention'}
        by_title.setdefault(mention['title'],[]).append(('mention',len(mentions)));mentions.append(node)
        parent=mention.get('parentTitle','');matches=by_title.get(parent,[])
        if len(matches)==1 and matches[0][0]=='concept':
            card=cards[matches[0][1]];card['explanation']='\n\n'.join(x for x in (card['explanation'],node['body'])if x)
            card['evidence'].extend(x for x in node['evidence']if x not in card['evidence'])
            card['visualPages']=sorted(set(card['visualPages']+node['visualPages']))
    def merged(title,nodes,bridge=None):
        body=[];refs=[];pages=set();easy=[]
        if bridge:body.append(bridge['text']);refs.extend(evidence(allowed[i])for i in bridge['blockIds'])
        for n in nodes:
            if n['body'].strip() and n['body']not in body:body.append(n['body'])
            if n.get('easyExplanation')and n['easyExplanation']not in easy:easy.append(n['easyExplanation'])
            refs.extend(e for e in n['evidence']if e not in refs);pages.update(n['visualPages'])
        value={'title':title,'body':'\n\n'.join(body),'easyExplanation':'\n\n'.join(easy),
            'evidence':refs,'visualPages':sorted(pages),'standardKnowledgeUsed':any(n['standardKnowledgeUsed']for n in nodes),
            'contentContract':raw['contentContract'],'lectureConceptTitles':[n['title']for n in nodes]}
        if nodes:
            for key in ('headingId','headingPath','sourceUnit','structuralRole','numberingContext'):
                if key in nodes[0]:value[key]=copy.deepcopy(nodes[0][key])
        if len(nodes)==1 and nodes[0].get('stepFlow'):value['stepFlow']=copy.deepcopy(nodes[0]['stepFlow'])
        elif any(n.get('stepFlow')for n in nodes):
            # A flow's actual taught steps remain in ordinary prose in a grouped
            # unit; do not drop a process when the legacy slot holds only one.
            from pdf_step_flow import append_sequence_fallback
            for n in nodes:
                if n.get('stepFlow'):append_sequence_fallback(value,n['stepFlow'])
        return value
    output=[];used=set()
    for group in raw.get('lectureUnits',[]):
        if not isinstance(group,dict):continue
        names=group.get('conceptTitles',[])
        if (not isinstance(names,list) or not names or len(set(names))!=len(names)
                or any(n in used or len(by_title.get(n,[]))!=1 for n in names)):
            raw.setdefault('processingDiagnostics',[]).append({'stage':'lecture_composition','kind':'invalid_optional_group'})
            continue
        nodes=[]
        for name in names:
            kind,i=by_title[name][0];nodes.append(parts[i]if kind=='concept'else mentions[i])
        bridge=group.get('bridge',{});text=bridge.get('text','')if isinstance(bridge,dict)else''
        if text:
            ids=bridge.get('blockIds',[])
            from pdf_new_concept_ver99_checks import prepare_learner_segment,math_semantics
            from pdf_ai import study_math_issues
            text=prepare_learner_segment(text,structured=True)[0]
            quote=bridge.get('sourceQuote','')
            native_support=(raw['contentContract']!='source-teaching-content-v4' or
                isinstance(quote,str)and quote.strip()and isinstance(ids,list)and any(
                    i in allowed and allowed[i].get('kind')in ('text','heading')
                    and not allowed[i].get('hasVisual')and quote in allowed[i].get('text','')for i in ids))
            if (not isinstance(ids,list)or not ids or any(i not in allowed for i in ids)
                    or not text.strip()or study_math_issues({'body':text})or math_semantics(text)or not native_support):
                raw.setdefault('processingDiagnostics',[]).append({'stage':'lecture_composition',
                    'kind':'unused_optional_bridge','reason':'invalid_source_or_text','original':copy.deepcopy(bridge)})
                bridge=None
            else:bridge={'text':text,'blockIds':list(dict.fromkeys(ids))}
        else:bridge=None
        output.append(merged(group.get('title')or nodes[0]['title'],nodes,bridge));used.update(names)
    for name,matches in by_title.items():
        if name in used:continue
        for kind,i in matches:
            node=parts[i]if kind=='concept'else mentions[i]
            if kind=='mention':
                parent=next((p for p in output if name in p.get('lectureConceptTitles',[])),None)
                if parent is None and output:
                    # An explicit parent can attach only inside the same unit.
                    original=raw.get('mentions',[{}])[i]
                    parent=next((p for p in output if original.get('parentTitle')in p.get('lectureConceptTitles',[])),None)
                if parent is not None:
                    parent['body']+='\n\n'+node['body'];parent['evidence'].extend(e for e in node['evidence']if e not in parent['evidence'])
                    parent['visualPages']=sorted(set(parent['visualPages']+node['visualPages']));continue
            output.append(merged(node['title']if kind=='concept'else'',[node]))
    return output,mentions

