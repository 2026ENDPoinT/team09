"""Recheck paid answers locally after validator changes; never calls a model."""
import contextlib
import copy
import io
import json
from pathlib import Path
from pdf_ai import map_unit
from pdf_page_analysis import hydrate, visual_notes

ROOT=Path('build/pdf-page-live-validation')
rows=[]
for prefix,number in [('b18d6db8cfbc',23),('9a295022e96e',1),('9a295022e96e',5)]:
    folder=ROOT/prefix;doc=json.loads((folder/'document.json').read_text(encoding='utf-8'));hydrate(folder,doc)
    unit=[c for c in doc['chunks'] if c['page']==number and c.get('source')!='ocr']
    ids={c['id'] for c in unit}
    responses=[]
    for p in (folder/'generated/paid-responses').glob('*.json'):
        if p.name.endswith(('.raw.json','.incomplete.json')):continue
        v=json.loads(p.read_text(encoding='utf-8'))
        if 'summary' not in v:continue
        evidence=[e for part in v['summary'].get('parts',[]) for e in part.get('evidence',[])]
        if evidence and all(e.get('sourceId') in ids for e in evidence):responses.append(v)
    assert responses
    responses.sort(key=lambda value: sum(len(p.get('evidence',[])) for p in value['summary'].get('parts',[])),reverse=True)
    class Replay:
        def complete(self,*args,**kwargs):return copy.deepcopy(responses[0])
    cache=folder/'generated/offline-revalidated-v3';cache.mkdir(exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        result=map_unit(Replay(),cache,unit,f'page-{number}',[],visual_notes(doc,[number]),document=doc)
    page=doc['pages'][number-1];summary=result['summary'];elements=page['pageAnalysis']['elements']
    row={'documentPages':len(doc['pages']),'page':number,'recoveredElements':len(summary.get('coverageRecoveredElementIds',[])),
         'summaryParts':len(summary.get('parts',[])),'formulaPreservedParts':sum(p.get('formulaPreserved',False) for p in summary.get('parts',[])),
         'nativeBackedElements':len({c['elementId'] for c in unit if c.get('nativeSupportSourceIds')}),'remoteRequests':0}
    if number==1:
        diagrams=[e['bbox'] for e in page['slideLensRegions'] if e.get('origin')=='page-vision-v1' and e['kind'] in ('diagram','table')]
        fragments=[r['bbox'] for r in page.get('imageRegions',[])]
        row['fragments']=len(fragments)
        row['fragmentsInsideSemanticLens']=sum(any(b[0]<=r[0] and b[1]<=r[1] and b[2]>=r[2] and b[3]>=r[3] for b in diagrams) for r in fragments)
    if number==23:
        formulas=' '.join(f['latex'] for e in elements for f in e['formulas'])
        row['bothMassFamiliesRead']=all(token in formulas for token in ['M','m','a','b','omega'])
        row['diagramCount']=sum(e['kind']=='diagram' for e in elements)
        row['formulaCount']=sum(len(e['formulas']) for e in elements)
    rows.append(row)
(ROOT/'revalidation.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows))
