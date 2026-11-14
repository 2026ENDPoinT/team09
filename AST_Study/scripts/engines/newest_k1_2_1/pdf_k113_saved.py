"""Revalidate exactly matching paid units after a K1.1.3 check/prompt upgrade."""
import copy
from pathlib import Path
from pdf_semantic import read_json


def index(folder, document, strategy, model, scope, page, current):
    candidates=[]
    for path in (Path(folder)/'generated'/strategy).glob('*/manifest.json'):
        if path.parent==current:continue
        value=read_json(path.parent/'result.json') or read_json(path.parent/'partial.json')
        if not isinstance(value,dict) or any(value.get(k)!=v for k,v in {
            'documentId':document['documentId'],'sourceFingerprint':document['fingerprint'],
            'strategy':strategy,'model':model,'scope':scope,'page':page}.items()):continue
        manifest=read_json(path)
        if isinstance(manifest,dict) and isinstance(manifest.get('jobs'),list):
            try:candidates.append((path.stat().st_mtime_ns,path.parent,manifest))
            except OSError:continue
    result={}
    for _,root,manifest in sorted(candidates,reverse=True):
        for job in manifest['jobs']:
            if isinstance(job,dict) and isinstance(job.get('id'),str):
                result.setdefault(job['id'],[]).append((root,job))
    return result


def reply(candidates, job):
    for root,old in candidates.get(job['id'],[]):
        if not all(old.get(k)==job.get(k) for k in ('title','blocks','unitContext','contextDepth')):continue
        value=read_json(root/f'response-{job["id"]}.json')
        if isinstance(value,dict):return copy.deepcopy(value),str(root)
    return None,None
