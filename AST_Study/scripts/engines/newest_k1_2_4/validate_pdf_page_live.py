"""Explicitly authorized live check; $1 aggregate cap, isolated copies, metadata output only."""
import contextlib
import json
from pathlib import Path
import shutil
import time
from pdf_ai import Provider, generation, run_usage
from pdf_page_analysis import analyze_page, plan
from pdf_pipeline import enrich_visual_routing, write_json

ROOT=Path('build/pdf-page-live-validation')
CAP=1.0

def used_budget():
    total=0.0
    for path in ROOT.glob('*/usage/*.json'):
        for entry in json.loads(path.read_text(encoding='utf-8')).get('requests',[]):
            total+=entry.get('estimatedUsd',entry.get('reservedUsd',0))
    return total

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    results=[]
    for prefix,number in [('b18d6db8cfbc',23),('9a295022e96e',1),('9a295022e96e',5)]:
        original=next(Path('.synesis/pdf').glob(prefix+'*/document.json'))
        folder=ROOT/prefix;folder.mkdir(exist_ok=True)
        if not (folder/'source.pdf').exists():shutil.copyfile(original.parent/'source.pdf',folder/'source.pdf')
        path=folder/'document.json'
        doc=json.loads((path if path.exists() else original).read_text(encoding='utf-8'))
        enrich_visual_routing(doc);write_json(path,doc)
        remaining=CAP-used_budget()
        if remaining<=0:break
        provider=Provider(folder,True,remaining,'gpt-6-luna')
        start=time.monotonic();row={'documentPages':len(doc['pages']),'page':number}
        with (ROOT/'progress.log').open('a',encoding='utf-8') as log, contextlib.redirect_stdout(log):
            try:
                page=analyze_page(folder,doc,number,provider)
                row.update(status=page['status'],inventory=len(page['inventory']),elements=len(page['elements']),
                    issues=page['issues'],formulas=sum(len(e['formulas']) for e in page['elements']),
                    kinds=[e['kind'] for e in page['elements']],
                    lensKinds=[e['kind'] for e in page['elements'] if e['lensReason']!='none' and e['kind']!='decoration'],
                    formulaOnlyLens=sum(e['kind']=='formula' and e['lensReason']!='none' for e in page['elements']))
                summary=generation(folder,doc,provider,'page',number,page_mode=True)
                parts=[p for s in summary['sections'] for p in s.get('parts',[])]
                row.update(summaryParts=len(parts),recoveredElements=sum(len(s.get('coverageRecoveredElementIds',[])) for s in summary['sections']),
                    summaryMathParts=sum('$$' in p.get('body','') or '\\(' in p.get('body','') for p in parts),
                    summaryLens=sum(bool(p.get('slideLens')) for p in parts),pendingAfter=plan(folder,doc,pages=[number])['pending'])
                before=len(provider.ledger['requests'])
                generation(folder,doc,provider,'page',number,page_mode=True)
                row['resumeRequests']=len(provider.ledger['requests'])-before
            except Exception as error:row['errorType']=type(error).__name__
        row['usage']=run_usage(provider);row['seconds']=round(time.monotonic()-start,2)
        row['aggregateReservedOrSettledUsd']=round(used_budget(),8)
        results.append(row);write_json(ROOT/'report.json',{'capUsd':CAP,'aggregateReservedOrSettledUsd':used_budget(),'results':results})
        print(json.dumps(row,ensure_ascii=True),flush=True)
        if row.get('errorType'):break

if __name__=='__main__':main()
