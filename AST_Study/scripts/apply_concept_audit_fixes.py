"""Apply a reviewed, source-ID-bound patch plan to saved concepts and summaries.

No model calls. Refuse concurrent result/source changes, retain backups and all
untouched cards, and keep the summary and concept representations in agreement.
"""
import argparse,copy,json
from pathlib import Path
from audit_pdf_concepts import ROOT,read,sha
from pdf_pipeline import write_json
from pdf_ai import merge_concepts,study_math_issues
from pdf_new_concept_ver99_study import evidence
from pdf_new_concept_ver99_checks import math_semantics

def union(a,b):
 return a+[copy.deepcopy(x) for x in b if x not in a]

def source_order_insert(items,item,pages):
 first=min(pages)
 at=next((i for i,x in enumerate(items) if x.get('pages',x.get('visualPages',[]))
  and min(x.get('pages',x.get('visualPages',[])))>first),len(items))
 items.insert(at,item)

def rebuild(result):
 sections=[]
 for section in result['sections']:
  if not section['parts']:continue
  section['body']='\n\n'.join(p['body'] for p in section['parts'])
  section['evidence']=[]
  for p in section['parts']:section['evidence']=union(section['evidence'],p['evidence'])
  section['visualPages']=sorted(set(section.get('visualPages',[]))|{n for p in section['parts'] for n in p['visualPages']})
  section['standardKnowledgeUsed']=any(p.get('standardKnowledgeUsed') for p in section['parts'])
  sections.append(section)
 result['sections']=sections
 for c in result['concepts']:
  c['pages']=sorted({p for e in c['entries'] for p in e.get('visualPages',[])}|
   {r['page'] for e in c['entries'] for r in e.get('evidence',[])})
 unresolved=sorted({r['page'] for r in result['coverage'] if r['state'] in ('needs_review','pending_summary')})
 result.update(incompleteStudyPages=unresolved,pageAnalysisIncompletePages=unresolved,
  coverageComplete=not unresolved,evidenceIncomplete=bool(unresolved),
  standardKnowledgeUsed=any(s.get('standardKnowledgeUsed') for s in sections))

def apply(apply=False):
 plan=read(ROOT/'patch-plan.json');logs=[]
 selected={x['id'][:10]:x for x in read(ROOT/'selection.json')}
 for prefix,operations in plan.items():
  item=selected[prefix];latest=Path(item['path']);folder=latest.parents[2]
  snapshot=ROOT/'api-baseline'/f'{prefix}.json';before=read(latest)
  if before!=read(snapshot):raise ValueError('Saved result changed after audit: '+prefix)
  for path in (folder/'source.pdf',folder/'document.json'):
   if sha(path)!=item['hashes'][str(path)]:raise ValueError('Original source changed')
  doc=read(folder/'document.json');after=copy.deepcopy(before)
  by_id={f'C{i+1}':c for i,c in enumerate(after['concepts'])}
  cache=Path(next(x['cache'] for x in read(ROOT/'local-revalidation.json') if x['id']==item['id']))
  blocks={b['id']:b for j in read(cache/'manifest.json')['jobs'] for b in j['blocks']}
  touched=set();applied=[]
  def parts_for(c,entry):
   combined=entry['definition']+'\n\n'+entry['explanation']
   parts=[p for s in after['sections'] for p in s['parts'] if p['title']==c['name'] and p['body']==combined]
   if len(parts)!=1:raise ValueError('Ambiguous summary/card correspondence: '+c['name'])
   return parts
  for op in operations:
   kind=op['type'];refs=[evidence(blocks[key],doc) for key in op.get('sourceBlockIds',[])]
   pages=sorted({e['page'] for e in refs})
   if kind=='merge':
    source=by_id[op['fromId']];target=by_id[op['conceptId']]
    if len(source['entries'])!=1 or len(target['entries'])!=1:raise ValueError('Only reviewed single-entry merge supported')
    e=target['entries'][0];part=parts_for(target,e)[0]
    for s in after['sections']:
     s['parts']=[p for p in s['parts'] if not (p['title']==source['name'] and p['body']==source['entries'][0]['definition']+'\n\n'+source['entries'][0]['explanation'])]
    for field in ('evidence','visualPages'):
     e[field]=union(e.get(field,[]),source['entries'][0].get(field,[]));part[field]=copy.deepcopy(e[field])
    e.setdefault('aliases',[]).append(source['name'])
    e.setdefault('sourceCorrections',[]).extend(op.get('sourceCorrections',[]))
    after['concepts'].remove(source);touched.update((op['fromId'],op['conceptId']))
   elif kind=='update':
    c=by_id[op['conceptId']];e=c['entries'][op.get('entryIndex',0)];part=parts_for(c,e)[0]
    old_name=c['name'];new_name=op.get('title') or old_name
    for field in ('definition','explanation','easyExplanation'):
     if op.get(field) is not None:e[field]=op[field]
    if new_name!=old_name:
     e.setdefault('aliases',[]).append(old_name);e['name']=new_name;c['name']=new_name
     for s in after['sections']:
      if s['title']==old_name:s['title']=new_name
    e['evidence']=union(e.get('evidence',[]),refs);e['visualPages']=sorted(set(e.get('visualPages',[]))|set(pages))
    if op.get('standardKnowledgeUsed'):e['standardKnowledgeUsed']=True
    if op.get('externalChecks'):e.setdefault('externalChecks',[]).extend(op['externalChecks'])
    if op.get('sourceCorrections'):e.setdefault('sourceCorrections',[]).extend(op['sourceCorrections'])
    part.update(title=new_name,body=e['definition']+'\n\n'+e['explanation'],
     **{k:copy.deepcopy(e[k]) for k in ('easyExplanation','evidence','visualPages','standardKnowledgeUsed')})
    touched.add(op['conceptId'])
   elif kind=='add':
    entry={'name':op['title'],'aliases':[],'definition':op['definition'],'explanation':op['explanation'],
     'easyExplanation':op['easyExplanation'],'example':'','confusion':'','evidence':refs,
     'visualPages':pages,'standardKnowledgeUsed':op.get('standardKnowledgeUsed',False)}
    c=merge_concepts([entry])[0]
    if any(old['name']==c['name'] for old in after['concepts']):raise ValueError('Added card already exists')
    part={'title':c['name'],'body':entry['definition']+'\n\n'+entry['explanation'],
     **{k:copy.deepcopy(entry[k]) for k in ('easyExplanation','evidence','visualPages','standardKnowledgeUsed')}}
    section={'title':c['name'],'parts':[part],'body':part['body'],'easyExplanation':'',
     **{k:copy.deepcopy(entry[k]) for k in ('evidence','visualPages','standardKnowledgeUsed')}}
    source_order_insert(after['concepts'],c,pages);source_order_insert(after['sections'],section,pages)
   else:raise ValueError('Unknown operation')
   for row in after['coverage']:
    if row['blockId'] in op.get('sourceBlockIds',[]):
     row.update(state='summarized',reason='원문 대조 후 확인한 개념 설명에 반영했어요.')
   applied.append(op)
  rebuild(after)
  for i,c in enumerate(before['concepts']):
   if f'C{i+1}' not in touched:assert c in after['concepts'],'Untouched card changed'
  for c in after['concepts']:
   for e in c['entries']:
    assert not study_math_issues(e),(c['name'],study_math_issues(e))
    for field in ('definition','explanation','easyExplanation'):
     assert e[field].strip() and not math_semantics(e[field]),(c['name'],field)
  after.setdefault('qualityAuditRepairs',[]).append({'date':'2026-10-16','originalSha256':sha(latest),
   'planPath':str(ROOT/'patch-plan.json'),'operationCount':len(operations)})
  output=ROOT/'fixed-results'/f'{prefix}.json';write_json(output,after)
  if apply:
   backup=ROOT/'backups'/f'{prefix}-pre-quality-fixes.json'
   if backup.exists():raise ValueError('Backup already exists')
   backup.parent.mkdir(exist_ok=True);backup.write_bytes(latest.read_bytes());write_json(latest,after)
  logs.append({'id':item['id'],'name':item['name'],'applied':apply,'beforeConcepts':len(before['concepts']),
   'afterConcepts':len(after['concepts']),'operations':applied,'preview':str(output),
   'beforeSha256':sha(snapshot),'afterSha256':sha(output),'unresolvedSourcePages':after['incompleteStudyPages']})
 write_json(ROOT/'applied-fixes.json',logs)
 print(json.dumps([{k:x[k] for k in ('name','applied','beforeConcepts','afterConcepts')} for x in logs],ensure_ascii=False,indent=2))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args();apply(args.apply)
