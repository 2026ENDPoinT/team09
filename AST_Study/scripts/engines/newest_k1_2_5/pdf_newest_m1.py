"""Newest_m1: shared unit planning, one teaching instruction, lecture-only output."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import hashlib
import json
import pdf_new_concept_ver99_study as units
from pdf_pipeline import check_cancel, emit, write_json
from pdf_semantic import generation_lock, read_json, selection

STRATEGIES = ('newest-m1',)
VERSION = 'Newest_m1-v1'
WORKERS = 20
PROMPT = '이 내용들을 요약해줘. 수식이나 개념들을 절대 놓치지 말고, 전공용어를 활용해서 대학생에게 도움되도록 설명해줘. 이 글을 읽고 쉽게 이해가 가능하고, 복습할 때 보더라도 쉽게 파악이 가능하도록.'
FORMAT = {'type':'json_schema','json_schema':{'name':'lecture','strict':True,'schema':{
    'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}}}

def root_path(folder, document, strategy, model, scope, page):
    identity = json.dumps([VERSION,PROMPT,document['fingerprint'],model,scope,page],ensure_ascii=False)
    return Path(folder)/'generated'/strategy/hashlib.sha256(identity.encode()).hexdigest()

def prepare_local_sources(folder, document, model, scope='document', page=None, strategy='newest-m1'):
    return units.prepare_local_sources(folder,document,model,scope,page,'new-concept-v99')

def prepare_group_plan(folder, document, provider, scope='document', page=None, strategy='newest-m1'):
    # The same planner/cache is shared; no teaching from the old engine is run.
    result = units.prepare_group_plan(folder,document,provider,scope,page,'new-concept-v99')
    page,_,_=selection(document,scope,page)
    source=units.root_path(folder,document,'new-concept-v99',provider.model,scope,page)
    root=root_path(folder,document,strategy,provider.model,scope,page)
    for name in ('blocks.json','plan.json','manifest.json'):
        value=read_json(source/name)
        if value is not None:write_json(root/name,value)
    estimate=reading_plan(folder,document,None,provider.model,scope,page,strategy)
    result.update(estimate)
    # Legacy teaching reservations belong to the legacy engine, not this prompt.
    result.pop('pendingOriginalUsage',None)
    return result

def reading_plan(folder,document,pages=None,model='gpt-6-luna',scope='document',page=None,strategy='newest-m1'):
    from pdf_ver99_cost_estimate import workload, estimate
    page,targets,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,model,scope,page)
    saved=read_json(root/'result.json')
    manifest=read_json(root/'manifest.json') or {}
    blocks=read_json(root/'blocks.json')
    jobs=manifest.get('jobs')
    pending=None if jobs is None else [j for j in jobs if not (root/f'response-{j["id"]}.json').exists() and not j.get('skip')]
    complete=bool(saved and saved.get('processingComplete'))
    work=workload(document,targets,blocks=blocks,jobs=jobs)
    prediction=estimate(document,targets,[],plan_cached=jobs is not None,outline_cached=True,model=model,work=work,
        pending_work=workload(document,targets,blocks=blocks,jobs=pending) if pending is not None else None)
    return {'strategy':strategy,'pages':targets,'totalPages':len(targets),
        'cachedPages':len(targets) if complete else 0,'pendingPages':0 if complete else len(targets),
        'totalCostEstimateUsd':0 if complete else prediction['usd'],
        'costEstimateUsd':0 if complete else prediction['usd'],
        'estimatedTotalTokens':0 if complete else prediction['tokens'],
        'estimateLowUsd':0 if complete else prediction['lowUsd'],
        'estimateHighUsd':0 if complete else prediction['highUsd'],
        'estimateBasis':'Newest_m1 임시 추정 · 기존 단위 작업량 기준 (실측 전)'}

def recover(folder,document,scope='document',page=None,model='gpt-6-luna',strategy='newest-m1'):
    page,_,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,model,scope,page)
    return read_json(root/'result.json') or read_json(root/'partial.json')

def summary(raw,job,document):
    answer=raw.get('answer') if isinstance(raw,dict) else None
    if not isinstance(answer,str) or not answer.strip():raise ValueError('빈 강의해설 응답')
    refs=[units.evidence(b,document) for b in job['blocks']]
    return {'summary':{'title':job['title'],'body':answer.strip(),'parts':[],
        'evidence':refs,'visualPages':sorted({b['page'] for b in job['blocks']}),
        'standardKnowledgeUsed':False},'concepts':[]}

def generate(folder,document,provider,scope='document',page=None,*,strategy='newest-m1'):
    if strategy not in STRATEGIES:raise ValueError(strategy)
    folder=Path(folder)
    page,targets,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,provider.model,scope,page)
    manifest=read_json(root/'manifest.json')
    if not manifest:prepare_group_plan(folder,document,provider,scope,page,strategy)
    manifest=read_json(root/'manifest.json')
    if not manifest or 'jobs' not in manifest:raise ValueError('단위엔진 결과가 없어요.')
    jobs=[j for j in manifest['jobs'] if not j.get('skip')]
    done={}; failures=[]
    def snapshot():
        complete=len(done)==len(jobs)
        value={'kind':'ai_generated' if complete else 'partial','model':provider.model,
            'strategy':strategy,'promptVersion':VERSION,'documentId':document['documentId'],
            'sourceFingerprint':document['fingerprint'],'scope':scope,'page':page,
            'sourcePages':targets,'contextPages':[],'sections':[done[i]['summary'] for i in sorted(done)],
            'concepts':[],'coverage':[],'coverageComplete':complete,'processingComplete':complete,
            'partialUnits':len(done),'totalUnits':len(jobs),'failedUnits':list(failures),
            'incompletePages':sorted({b['page'] for i,j in enumerate(jobs) if i not in done for b in j['blocks']}),
            'integrationPending':False,'standardKnowledgeUsed':False}
        from pdf_ai import run_usage
        value['runUsage']=run_usage(provider)
        write_json(root/('result.json' if complete else 'partial.json'),value)
        write_json(units.latest_path(folder,strategy,scope,page),value)
        return value
    def publish(i,value):
        done[i]=value
        path=root/f'unit-{i:05d}.json';write_json(path,value)
        emit('summary_unit_ready',unit=i+1,total=len(jobs),scope=scope,selectionPage=page or 0,strategy=strategy,path=str(path))
        emit('study_timeline',stage='unit_done',percent=20+int(78*len(done)/max(1,len(jobs))))
        snapshot()
    def request(i,images,crops):
        from pdf_ai import complete_study_delivery
        job=jobs[i]
        check_cancel(folder)
        provider.context={'kind':'region_study','strategy':strategy,'unitIds':[job['id']],
            'pages':sorted({b['page'] for b in job['blocks']}),'reasoningEffort':'none',
            'studyTeachingIdentity':VERSION,'studyDurable':True,'studyConnectionRepairAllowed':True}
        payload={'task':'region_teaching','unitId':job['id'],'title':job['title'],
            'blocks':job['blocks'],'images':crops}
        raw=complete_study_delivery(provider,payload,image=images,image_limit=16,max_output=18000,
            system_prompt=PROMPT,response_format=FORMAT,cache_stable_prefix=True)
        write_json(root/f'response-{job["id"]}.json',raw)
        return summary(raw,job,document)
    with generation_lock(folder):
        emit('study_timeline',stage='units_ready',percent=20,total=len(jobs))
        pending=[]
        for i,job in enumerate(jobs):
            raw=read_json(root/f'response-{job["id"]}.json')
            if raw is not None:
                try:publish(i,summary(raw,job,document));continue
                except ValueError:pass
            pending.append(i)
        # Render on the calling thread (PDFium), keep at most 20 prepared requests alive.
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            active={}; cursor=0
            while cursor<len(pending) or active:
                while cursor<len(pending) and len(active)<WORKERS:
                    check_cancel(folder)
                    i=pending[cursor];cursor+=1
                    try:
                        images,crops=units.render_crops(folder,jobs[i]['blocks'],root)
                        if len(images)>16:raise ValueError('단위 이미지 수가 전송 한도를 넘었어요.')
                        active[pool.submit(request,i,images,crops)]=i
                    except InterruptedError:raise
                    except Exception as error:
                        failures.append({'unitId':jobs[i]['id'],'error':type(error).__name__,'detail':str(error)})
                if not active:continue
                ready,_=wait(active,return_when=FIRST_COMPLETED)
                for future in ready:
                    i=active.pop(future)
                    try:publish(i,future.result())
                    except InterruptedError:raise
                    except Exception as error:
                        failures.append({'unitId':jobs[i]['id'],'error':type(error).__name__,'detail':str(error)})
        return snapshot()
