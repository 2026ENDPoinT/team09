"""Rebuild display results from saved replies only; no provider/network is constructed."""
import argparse
from pathlib import Path
import json
import time

from pdf_pipeline import write_json
import pdf_new_concept_ver99_study as study


def rebuild(folder):
    run=json.loads((folder/'run.json').read_text());cache=Path(run['cacheRoot'])
    doc=json.loads((folder/'document.json').read_text());old=json.loads((folder/'result.json').read_text())
    manifest=json.loads((cache/'manifest.json').read_text());blocks=json.loads((cache/'blocks.json').read_text())
    plan=json.loads((cache/'plan.json').read_text());done={};start=time.monotonic()
    for i,job in enumerate(manifest['jobs']):
        path=cache/f'response-{job["id"]}.json'
        if path.exists():raw=json.loads(path.read_text())
        else:
            assert job.get('skip') or all(b['id'] in study.plain_cover_ids(blocks) for b in job['blocks'])
            raw={'concepts':[],'uncertainBlocks':[],'excludedBlocks':[
                {'blockId':b['id'],'reason':b.get('planRole','navigation')} for b in job['blocks']]}
        done[i]=study.validate(raw,job,doc)
    value=study.assemble(doc,'new-concept-v99',run['scope'],run['page'] or 0,
        manifest['targets'],manifest['jobs'],done,[],old['processingNotes'],
        headings=plan.get('headings'),all_blocks=blocks)
    for key in ['overview','metrics','runUsage','cacheReuse','visualSelectionVersion']:
        if key in old:value[key]=old[key]
    value['localOutputVersion']=study.CHECKS_VERSION
    write_json(folder/'final-result.json',value)
    return {'case':run['case'],'variant':folder.name,'seconds':time.monotonic()-start,
        'oldEntries':sum(len(c.get('entries',[])) for c in old['concepts']),
        'finalEntries':sum(len(c.get('entries',[])) for c in value['concepts']),
        'oldPendingPages':old['incompleteStudyPages'],'finalPendingPages':value['incompleteStudyPages'],
        'additionalPaidCalls':0}


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();rows=[]
    for path in args.output.glob('*/*/run.json'):
        run=json.loads(path.read_text())
        if run.get('processingComplete'):rows.append(rebuild(path.parent))
    write_json(args.output/'local-revalidation.json',rows)
    print(json.dumps(rows,ensure_ascii=False))


if __name__=='__main__':main()
