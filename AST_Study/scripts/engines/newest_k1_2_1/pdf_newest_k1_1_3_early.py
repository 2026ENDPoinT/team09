"""Source-verified opening units; one owner per paid task across plan handoff."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor


class EarlyUnits:
    def __init__(self,folder,document,provider,scope,page):
        import pdf_newest_k1_1_3 as e
        self.e=e;self.folder=folder;self.document=document;self.provider=provider
        self.scope=scope;self.page=e.selection(document,scope,page)[0]
        self.pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='study-opening')
        self.warm_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='study-page-warm')
        self.render_lock=threading.RLock();self.futures={};self.jobs={}
        self.previews=None;self.warmed=[];self.warm_failures=[];self.handoff=False

    def __enter__(self):return self

    def __exit__(self,*args):
        # Never close shared HTTP transport while an opening request owns it.
        self.warm_pool.shutdown(wait=True,cancel_futures=True)
        self.pool.shutdown(wait=True,cancel_futures=True)

    def start(self,cache,blocks,started):
        from pdf_study_stream import PreviewPublication
        self.cache=cache;self.blocks=blocks;self.started=started
        self.positions={b["id"]:n for n,b in enumerate(blocks)}
        self.context=self.e.document_context(self.document)
        self.previews=PreviewPublication([],[],set(),scope=self.scope,page=self.page,
            strategy=self.e.STRATEGIES[0],emit=self.e.emit,started=started)
        # Bounded page warming, unchanged resolution/pixels. Share the crop lock
        # so PDF decoding and writes cannot race the normal/early crop producer.
        pages=list(dict.fromkeys(b['page'] for b in blocks))[:4]
        self.warm_pool.submit(self._warm,pages)

    def _warm(self,pages):
        from pdf_regions import page_image
        for page in pages:
            if self.handoff:return
            try:
                with self.render_lock:
                    self.e.check_cancel(self.folder)
                    with page_image(self.folder,page,self.cache):pass
                self.warmed.append(page)
            except InterruptedError:raise
            except Exception as error:
                # Speculation cannot fail a generation; actual preparation uses
                # the established rendering/error path if warming fails.
                self.warm_failures.append(type(error).__name__)

    def offer(self,groups,*,final=False):
        e=self.e
        annotated={b['id']:b for g in groups for b in g['blocks']}
        for block in self.blocks:
            if block['id'] in annotated:
                for field in ('planRole','planRoleBeforeVisualGuard','visualReadingRequired'):
                    if field in annotated[block['id']]:block[field]=annotated[block['id']][field]
        teaching=[{**g,'blocks':[b for b in g['blocks']
            if b.get('planRole') not in ('decoration','navigation','exercise')]} for g in groups]
        teaching=[g for g in teaching if g['blocks']]
        teaching,_=e.lead_with_visual_page(teaching)
        jobs=e.jobs_for(teaching)
        eligible_topics=min(3,len(teaching) if final else max(0,len(teaching)-1))
        cover=e.plain_cover_ids(self.blocks)
        with self.previews.lock:
            self.previews.jobs=jobs
            self.previews.front=[i for i,j in enumerate(jobs)
                if not all(b['id'] in cover for b in j['blocks'])][:2]
        for i,job in enumerate(jobs):
            if job['topicIndex']>=eligible_topics:break
            if all(b['id'] in cover for b in job['blocks']):continue
            if job['id'] in self.futures:continue
            if any(old_index==i for old_index,_ in self.jobs.values()):
                raise ValueError('확정한 단락이 변경되어 중복 생성을 중단했어요.')
            # A task's index and exact context/source identity are frozen now.
            frozen=copy.deepcopy(job)
            self.jobs[job['id']]=(i,frozen)
            self.futures[job['id']]=self.pool.submit(self._work,i,frozen,copy.deepcopy(jobs))
        e.write_json(self.cache/'early-unit-contexts.json',{
            'policy':'opening-three-next-one-v1','units':[{'index':i,'job':job} for i,job in self.jobs.values()]})
        return eligible_topics>=3 or final

    def _work(self,index,job,jobs):
        e=self.e
        from pdf_study_stream import StudyPreview
        from pdf_ai import complete_study_delivery
        raw=e.read_json(self.cache/f'response-{job["id"]}.json')
        if raw is not None:
            # Retain normal source ownership and schema validation on cache hits.
            from pdf_newest_k1_1_3_guard import ensure_owned
            ensure_owned(raw,{'job':job},[{'job':other} for other in jobs if other['id']!=job['id']])
            unit=e.validate(raw,job,self.document)
            if not any(c['state']=='needs_review' for c in unit['coverage']):return unit
            from pdf_k113_coverage import feedback
            feedback(job,raw,unit['coverage'])
        with self.render_lock:
            images,crops=e.render_crops(self.folder,e.render_blocks(job['blocks']),self.cache)
            images,crops,text_only=e.select_images(job['blocks'],images,crops)
            e.write_json(self.cache/f'crops-{job["id"]}.json',crops)
            e.write_json(self.cache/f'input-{job["id"]}.json',{'policy':e.TEXT_INPUT_VERSION,
                'textOnlyBlockIds':sorted(text_only),'imageBlockIds':[b for c in crops for b in c.get('blockIds',[])]})
        # Background context uses the same complete extracted source, never a
        # truncated PDF. Only the explicit title/description window is smaller.
        request=e.build_teaching_request(self.folder,job,self.blocks,self.document,(images,crops),
            positions=self.positions,context=self.context)
        self.provider.context=request['context']
        preview=StudyPreview([((),index)],self.previews.update)
        raw=complete_study_delivery(self.provider,request['payload'],image=request['images'],
            max_output=18000,system_prompt=request['instructions'],response_format=request['response_format'],
            cache_stable_prefix=True,on_study_delta=preview.feed,on_delivery_reset=preview.reset)
        value=e.accept_teaching_reply(self.cache,self.document,jobs,job,raw,request)
        # Raw response is durable before publication; final plan decorates it
        # through the normal hierarchy/UI pipeline without another model call.
        preview.flush()
        return value

    def bind_final(self,jobs):
        self.handoff=True
        for key,(index,job) in self.jobs.items():
            if index>=len(jobs) or jobs[index]['id']!=key:
                raise ValueError('확정된 앞부분 묶음과 최종 계획이 달라요. 원문 보호를 위해 재호출하지 않았어요.')
        with self.previews.lock:self.previews.jobs=jobs

    def metrics(self):
        return {'policy':'opening-three-next-one-v1','earlyTasks':len(self.futures),
                'warmedPages':self.warmed,'warmFailures':self.warm_failures,
                'extraGenerationCallsForHandoff':0}
