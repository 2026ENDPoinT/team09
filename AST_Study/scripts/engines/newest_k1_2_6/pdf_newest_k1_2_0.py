"""Ver.99 teaching with source-preserving transport and bounded parallel work."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
import threading
import unicodedata
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from collections import deque
from pathlib import Path

from pdf_pipeline import check_cancel, emit, write_json
from pdf_regions import digest
from pdf_new_concept_v02_regions import VERSION as LAYOUT_VERSION, extract, render_crops, crop_runs
from pdf_study_layout_cache import extract_layout
from pdf_study_reading_policy import ENABLED as READING_V2, EXERCISE_RULES
from pdf_response_schema import _object, sequence_order_fields
from pdf_step_flow import ORDER_POLICY, append_sequence_fallback, normalize_existing_flows
from pdf_semantic import generation_lock, read_json, selection
from pdf_study_policy import document_context
from pdf_newest_k1_2_0_prompts import (PLAN_PROMPT, STUDY_PROMPT, CANONICAL_STUDY_PROMPT,
                                    OVERVIEW_PROMPT, BATCH_RULES, PRACTICE_COMPRESSION)
from pdf_k120_compact_coverage import VERSION as COMPACT_COVERAGE_VERSION, CANONICAL_MARKER
from pdf_new_concept_ver99_checks import VERSION as CHECKS_VERSION
from pdf_study_review import VERSION as REVIEW_VERSION, reading_effort
CHECKS_VERSION += ":"+REVIEW_VERSION
from pdf_k113_review import VERSION as SELECTIVE_VERSION, ReviewPolicy, exercise_exclusion
CHECKS_VERSION += ":"+SELECTIVE_VERSION
from pdf_k113_coverage import VERSION as COVERAGE_VERSION
CHECKS_VERSION += ":"+COVERAGE_VERSION
from pdf_study_cache_reuse import repair_source_ids, constrained_format, reuse_plan, reusable_reply
from pdf_group_partition import (VERSION as PARTITION_VERSION, PartitionError,
    repair_partition, recover_ranges, validate_partition)
import pdf_newest_k1_2_0_hierarchy as hierarchy
from pdf_saved_teaching_compat import active as content_contract_active
from pdf_study_text_input import (VERSION as TEXT_INPUT_VERSION, POLICY as TEXT_INPUT_POLICY,
    COMPACT_SETUP, select_images, render_blocks)
from pdf_visual_selection import (VERSION as VISUAL_SELECTION_VERSION, substantive_visual,
    locally_skipped, protect_visual_groups, unjustified_visual_exclusion, verified_non_teaching_reason)
from pdf_study_references import (VERSION as REFERENCE_VERSION, REFERENCE_SCHEMA,
    RULES as REFERENCE_RULES, identity_prompt as reference_identity_prompt,
    reference_context, project_saved_references)
from pdf_k126_profile import PROFILE as SAVINGS_PROFILE

STRATEGIES = ('newest-k1-2-6',)
VERSION = f'Newest_K1.2.6-v1-{SAVINGS_PROFILE}'
from pdf_study_concurrency import worker_limits
MAX_STUDY_WORKERS, MAX_STARTUP_WORKERS = worker_limits(STRATEGIES[0])
WORKERS = MAX_STUDY_WORKERS
SCHEDULING_PROFILE = 'source-front-2-single-startup-80-steady-80-v8'
PLAN_TRANSPORT = 'ranges'
PLAN_WINDOW_BYTES = 50000
PLAN_WINDOW_BLOCKS = 220
JOB_WEIGHT_LIMIT = 10000
JOB_CROP_LIMIT = 8
# Eight owned crops and the existing bounded labelled continuation context. The same limit
# is passed through normal, early, cache-recovery and hedged single deliveries.
SINGLE_REQUEST_IMAGES = 16
JOB_PAGE_LIMIT = 4
PIPELINE_CROPS = True
NEUTRAL_VISUAL_HINT = False
# Wire-only aliases keep canonical text, pixels, prose and stored citations intact.
# Singles enumerate only real sources; pairs use disjoint namespaces and the
# exact source map is enforced again before canonical validation.
SOURCE_ID_ALIASES = True
SOURCE_ALIAS_POOL_SIZE = None
TRANSPORT_BATCH_UNITS = 1
TRANSPORT_BATCH_IMAGES = 8
TRANSPORT_BALANCED = True
VISUAL_REQUEST_PRIORITY = False  # Enabled only after equal-envelope timing validation.
TRANSPORT_BATCH_ALIASES = True
TRANSPORT_BATCH_ALIAS_POOL = 'exact'
# K1.2.0 uses stored foreground Responses without changing source or teaching.
# Response IDs still allow retrieval of already completed results; a live
# foreground connection is cancelled by closing it rather than /cancel.
STUDY_INPUT_API = 'responses'
DURABLE_STUDY_BODY = False
FOREGROUND_STUDY_BODY = True
STATEMENT_UNCERTAINTY = True
OWNED_TEACHING = False
# Summary/concept generation stays at none; low is only an explicit audit option.
STUDY_REASONING_EFFORT = 'none'
STUDY_TEMPERATURE = None
COMPACT_TABLE_SETUP = False
IMAGE_SOURCE_LABELS = False
IMAGE_REGION_LABELS = False
SOURCE_COVERAGE_HINT = False
SOURCE_FACTS = False
VISUAL_TEACHING = False
PARTIAL_NATIVE_VISUAL_HINTS = False
TEACHING_PAYLOAD_VERSION = 'partial-native-visual-v1'
PARTIAL_NATIVE_VISUAL_HINT = '''For visualContentRequiresReading targets, read the
owned image region as well as text. nativeTextIsPartialVisualExtraction means text
contains only locally extracted native text, not a transcript of the whole figure.
It may omit image labels, connections, branches and destinations. Preserve that
text, but do not treat a short extracted word as the entire figure or as proof
that the figure has no teaching content. Ground figure teaching in its owning ID.'''
SOURCE_COVERAGE_RULES = '''
The titleHint is provisional grouping context, not a limit on target content.
Read each substantial target figure as its own evidence. A diagram is not redundant
merely because a table names the same organs: teach its visible connections,
branches and named destinations. Preserve readable dates, actors, stated purposes,
material context, units and
interpretation limits that qualify a source claim in the learner explanation or
table, not only in sourceSetup. Retain complete source classifications and named
examples that explain a stated relationship. Keep the full meaning of table column
headings, including parenthetical factors; a composite measure must not become
only one of its listed components. Do not infer unreadable details or
add outside facts. Preserve the direction of source relations when paraphrasing:
an actor, recipient, buyer and seller must not swap roles. If a source clause has
no explicit actor, use neutral attributed wording instead of borrowing an actor
from a neighboring clause. Do not turn independent source lists into row-by-row
pairings that the source does not establish.
'''
PACKING_VERSION = 'complete-classification-boundary-v3-packed-runs'
from pdf_study_review import PRINTABLE_STRING
S = PRINTABLE_STRING.copy()
SS = {'type':'array', 'items':S}


def fmt(name, fields):
    return {'type':'json_schema', 'json_schema':{'name':name, 'strict':True, 'schema':_object(fields)}}


PLAN_FORMAT = fmt('new_concept_grouping_v1', {'groups':{'type':'array', 'items':_object({
    'title':S, 'description':S, 'topicPath':SS, 'blockIds':SS, 'role':{'type':'string','enum':['teaching','illustration','exercise','navigation','uncertain']}, 'continuesPrevious':{'type':'boolean'}})}})

STUDY_FORMAT = fmt('new_concept_teaching_v2', {
    'concepts':{'type':'array', 'items':_object({'title':S, 'sourceSetup':_object({
        'teachingRole':{'type':'string','enum':['independent','continuation','source_case']},
        'observedRelations':SS,'boundaryChecks':SS,'interpretation':S,'sourceQuotes':SS,
        'learnerDifficulty':_object({'kind':{'type':'string','enum':[
            'none','symbol_meaning','intermediate_step','mechanism','distinction']},'question':S})}),
        'segments':{'type':'array','items':_object({
            'kind':{'type':'string','enum':['definition','explanation','easyExplanation','uncertain']},
            'text':S,'blockIds':SS})},
        'standardKnowledgeUsed':{'type':'boolean'}})},
    'sequences':{'type':'array','items':_object({'conceptTitle':S,'title':S,**sequence_order_fields(),
        'steps':{'type':'array','items':_object({'title':S,'body':S,'blockIds':SS})}})},
    'tables':{'type':'array','items':_object({'conceptTitle':S,'headers':SS,
        'rows':{'type':'array','items':SS},'blockIds':SS})},
    'sourceCoverage':{'type':'array','items':_object({'blockId':S,'conceptTitle':S,'quote':S})},
    'excludedBlocks':{'type':'array', 'items':_object({'blockId':S, 'reason':S,
        'referenceContext':REFERENCE_SCHEMA,
        'sourceDisposition':{'anyOf':[{'type':'null'},_object({
            'kind':{'type':'string','enum':['structure','repeated_example','supporting_illustration',
                                          'source_conflict','unlabelled_supporting_figure']},
            'observations':SS,'independentLearningPoint':S,'keptConceptTitle':S})]},
        'exerciseSelection':{'anyOf':[{'type':'null'},_object({
            'kind':{'type':'string','enum':['practice','worked_example']},
            'sourceQuote':S,'keptConceptTitle':S})]}})},
    'uncertainBlocks':{'type':'array', 'items':_object({'blockId':S, 'reason':S})}})


from pdf_group_transport import RANGE_FORMAT as _LEGACY_RANGE_FORMAT
K1_RANGE_FORMAT = copy.deepcopy(_LEGACY_RANGE_FORMAT)
_group_schema = K1_RANGE_FORMAT['json_schema']['schema']['properties']['groups']['items']
_group_schema['properties']['description'] = {'type':'string'}
_group_schema['required'].append('description')
_group_schema['properties']['topicPath'] = {'type':'array','items':{'type':'string'},'maxItems':3}
_group_schema['required'].append('topicPath')
K1_RANGE_FORMAT['json_schema']['name'] = 'newest_k1_topic_ranges_v1'



def compact_description(value):
    """A short context hint, not forty words or a second learner summary."""
    value=' '.join(str(value or '').split())
    return value if len(value)<=40 else value[:40].rstrip()


def attach_unit_context(jobs, groups):
    units=[{'index':i+1,'title':g['title'],'description':compact_description(g.get('description',''))}
           for i,g in enumerate(groups)]
    for job in jobs:
        i=job['topicIndex']
        job['unitContext']={'current':({**units[i]} if i<3 else {**units[i],'total':len(units)}),
            'before':copy.deepcopy(units[max(0,i-10):i]),
            'after':copy.deepcopy(units[i+1:i+2] if i<3 else units[i+1:i+6])}
        if i<3:job['unitContext']['policy']='opening-three-next-one-v1'


def planned_overview(provider, cache, groups, document, on_preview=None):
    """A roadmap of planned units, available before teaching; no generated prose input."""
    from pdf_outline import FORMAT, valid_flow, local_flow_body, MAX_OUTLINE_BYTES
    from pdf_output_language import foreign_prose
    items=[{'id':f'k{i+1}','title':g['title'],'description':compact_description(g.get('description',''))}
           for i,g in enumerate(groups)]
    originals={item['id']:group for item,group in zip(items,groups)}
    key=digest([OVERVIEW_PROMPT,items,provider.model])
    path=Path(cache)/f'planned-overview-{key}.json'
    saved=read_json(path)
    if (isinstance(saved,dict) and saved.get('planIdentity')==key
            and (not items or valid_flow({'body':saved.get('body'),'topicIds':saved.get('sourceSectionIds')},originals))):
        return saved
    check_cancel(provider.folder if hasattr(provider,'folder') else Path(cache).parent)
    local=not items or len(json.dumps(items,ensure_ascii=False).encode())>MAX_OUTLINE_BYTES
    diagnostic=None
    if not local:
        from pdf_overview_stream import OverviewPreview
        preview=OverviewPreview(on_preview or (lambda *a,**k:None))
        provider.context={'kind':'summary_reduce','strategy':'newest-k1-2-6','level':1,'group':0,
                          'studyForegroundResponses':FOREGROUND_STUDY_BODY}
        try:
            value=provider.complete({'task':'lecture_flow_from_planned_units','topics':items},
                max_output=500,system_prompt=OVERVIEW_PROMPT,response_format=FORMAT,
                on_study_delta=preview.feed,on_delivery_reset=preview.reset)
            local=not valid_flow(value,originals) or foreign_prose(value.get('body',''))
        except InterruptedError:
            raise
        except Exception as error:
            local=True;diagnostic=type(error).__name__
    if local:value={'body':local_flow_body(items),'topicIds':list(originals)}
    selected=[originals[key] for key in dict.fromkeys(value['topicIds'])]
    result={'title':'이 강의의 흐름','body':value['body'],'easyExplanation':'',
        'evidence':[evidence(g['blocks'][0],document) for g in selected if g['blocks']],
        'visualPages':sorted({b['page'] for g in selected for b in g['blocks']}),
        'standardKnowledgeUsed':False,'sourceSectionIds':value['topicIds'],
        'overviewMethod':'planned_local_fallback' if local else 'planned_units_once',
        'planIdentity':key,'planned':True}
    if diagnostic:result['localFallbackDiagnostic']={'error':diagnostic,'additionalApiRequests':0}
    write_json(path,result)
    return result


def latest_path(folder, strategy, scope, page):
    return Path(folder)/'generated'/strategy/f'latest-{scope}-{page or 0}.json'


def identity(document, strategy, model, scope, page):
    key=[VERSION, LAYOUT_VERSION, CHECKS_VERSION, PACKING_VERSION, PLAN_PROMPT, CANONICAL_STUDY_PROMPT, BATCH_RULES, OVERVIEW_PROMPT, STUDY_FORMAT, PRACTICE_COMPRESSION,
         document['documentId'], document['fingerprint'], strategy, model, scope, page]
    key.append(['nativeTextInput',TEXT_INPUT_VERSION])
    if (PLAN_TRANSPORT!='ids' or NEUTRAL_VISUAL_HINT or STATEMENT_UNCERTAINTY or SOURCE_ID_ALIASES or OWNED_TEACHING
            or COMPACT_TABLE_SETUP or JOB_PAGE_LIMIT!=4 or STUDY_TEMPERATURE is not None or IMAGE_SOURCE_LABELS or IMAGE_REGION_LABELS or SOURCE_COVERAGE_HINT or SOURCE_FACTS or VISUAL_TEACHING
            or (PLAN_WINDOW_BYTES,PLAN_WINDOW_BLOCKS,JOB_WEIGHT_LIMIT,JOB_CROP_LIMIT)!=(50000,220,10000,4)):
        key.extend([planner_identity(model),JOB_WEIGHT_LIMIT,JOB_CROP_LIMIT,
                    NEUTRAL_VISUAL_HINT,STATEMENT_UNCERTAINTY,SOURCE_ID_ALIASES,OWNED_TEACHING,
                    STUDY_REASONING_EFFORT,JOB_PAGE_LIMIT,COMPACT_TABLE_SETUP,IMAGE_SOURCE_LABELS,STUDY_TEMPERATURE,IMAGE_REGION_LABELS,SOURCE_COVERAGE_HINT])
    if PARTIAL_NATIVE_VISUAL_HINTS:key.extend([TEACHING_PAYLOAD_VERSION,PARTIAL_NATIVE_VISUAL_HINT])
    if SOURCE_COVERAGE_HINT:key.append(SOURCE_COVERAGE_RULES)
    if SOURCE_FACTS or VISUAL_TEACHING:key.append(teaching_identity())
    if SOURCE_ID_ALIASES and SOURCE_ALIAS_POOL_SIZE is not None:
        key.append(['sourceAliasPool',SOURCE_ALIAS_POOL_SIZE])
    if TRANSPORT_BATCH_UNITS != 1:
        key.append(['independentTransportBatch',TRANSPORT_BATCH_UNITS,TRANSPORT_BATCH_IMAGES])
        if TRANSPORT_BALANCED:key.append(['balancedTransport','worker-independent-long-short-v2'])
        if TRANSPORT_BATCH_ALIASES:key.append(['batchSourceAliases',TRANSPORT_BATCH_ALIAS_POOL])
    if STUDY_INPUT_API!='chat':key.append(['studyInputApi',STUDY_INPUT_API])
    return digest(key)


def root_path(folder, document, strategy, model, scope, page):
    return Path(folder)/'generated'/strategy/identity(document, strategy, model, scope, page)


def saved_complete(folder,document,strategy,model,scope,page):
    """Presentation upgrades never trigger paid regeneration of saved prose."""
    root=root_path(folder,document,strategy,model,scope,page)
    for path in (root/'result.json',latest_path(folder,strategy,scope,page)):
        saved=read_json(path)
        if path==root/'result.json' and saved and saved.get('processingComplete'):return saved
        if (saved and saved.get('processingComplete') and all(saved.get(k)==v for k,v in {
                'documentId':document['documentId'],'sourceFingerprint':document['fingerprint'],
                'strategy':strategy,'model':model,'scope':scope,'page':page,'promptVersion':VERSION}.items())):return saved
    # A local revalidation may finish an already paid run without overwriting
    # its raw latest/partial. Reuse only while that exact raw latest is current.
    pointer=read_json(latest_path(folder,strategy,scope,page).with_name(f'local-complete-{scope}-{page or 0}.json'))
    if isinstance(pointer,dict):
        try:
            import hashlib
            name=pointer['rootName']
            if not isinstance(name,str)or re.fullmatch('[0-9a-f]{64}',name)is None:return None
            latest=latest_path(folder,strategy,scope,page)
            if hashlib.sha256(latest.read_bytes()).hexdigest()!=pointer['originalLatestSha256']:return None
            data=(root.parent/name/'result.json').read_bytes()
            if hashlib.sha256(data).hexdigest()!=pointer['resultSha256']:return None
            value=json.loads(data)
            if (value.get('processingComplete')is True and value.get('localRecovery',{}).get('newPaidCalls')==0
                    and all(value.get(k)==v for k,v in {'documentId':document['documentId'],
                        'sourceFingerprint':document['fingerprint'],'strategy':strategy,
                        'model':model,'scope':scope,'page':page,'promptVersion':VERSION}.items())):return value
        except (OSError,ValueError,KeyError,TypeError):pass
    return None



def display_saved(folder,document,result,cache=None):
    result=normalize_existing_flows(copy.deepcopy(result))
    from pdf_saved_tables import restore_saved_tables
    result=restore_saved_tables(folder,document,result,attach_comparison_tables)
    from pdf_saved_boundaries import restore_saved_boundaries
    result=restore_saved_boundaries(folder,document,result,validate,attach_comparison_tables)
    result=project_saved_references(folder,document,result)
    from pdf_symbol_bullets import clean_titles
    result=clean_titles(folder,result)
    local_upgrade=hierarchy.VERSION=='study-hierarchy-7'
    if (result.get('hierarchy',{}).get('version')==hierarchy.VERSION
            and result.get('hierarchy',{}).get('displayRevision')==hierarchy.DISPLAY_REVISION):
        value=copy.deepcopy(result)
        save_display_hierarchy(cache,value)
        return value
    if local_upgrade:
        from pdf_hierarchy_projection_cache import lookup, store, stamp, layout_stamp
        cached=lookup(folder,cache,result,document)
        if cached is not None:
            save_display_hierarchy(cache,cached)
            return cached
        pdf_stamp=stamp(Path(folder)/'source.pdf')
        layout_before=layout_stamp(folder,cache,result)
    blocks=[]
    blocks_path=None;blocks_stamp=None
    if local_upgrade:
        candidates=[]
        for path in (Path(folder)/'generated'/result['strategy']).glob('*/blocks.json'):
            try:candidates.append((path.stat().st_mtime_ns,path.as_posix(),path))
            except OSError:continue  # A concurrently removed cache is disposable.
        roots=[item[2] for item in sorted(candidates,reverse=True)]
    else:
        roots=sorted((Path(folder)/'generated'/result['strategy']).glob('*/blocks.json'),
                     key=lambda p:p.stat().st_mtime_ns,reverse=True)
    if cache and (Path(cache)/'blocks.json').is_file():
        preferred=Path(cache)/'blocks.json';roots=[preferred]+[p for p in roots if p!=preferred]
    refs={e['sourceId'] for s in result.get('sections',[])
          for part in ([s]+s.get('parts',[]))
          for e in part.get('evidence',[]) if e.get('sourceId')}
    for path in roots:
        before=stamp(path) if local_upgrade else None
        candidate=read_json(path) or []
        if refs.issubset({b['id'] for b in candidate}):
            blocks=candidate;blocks_path=path
            if local_upgrade and before==stamp(path):blocks_stamp=before
            break
    # Missing local source data is not permission to flatten a saved outline.
    # Leave its previous projection intact and retry the upgrade on next load.
    if refs and not blocks:return result
    value=copy.deepcopy(result)
    value['_pageLabels']={str(i+1):p.get('label') or str(i+1) for i,p in enumerate(document['pages'])}
    native_status={}
    saved_groups=(read_json(blocks_path.parent/'plan.json') or {}).get('groups',[]) if blocks_path else []
    headings=display_source_headings(folder,blocks,status=native_status,groups=saved_groups)
    value=hierarchy.decorate(value,blocks,headings)
    value=clean_titles(folder,value)
    save_display_hierarchy(cache,value)
    if local_upgrade and pdf_stamp is not None and blocks_stamp is not None and native_status.get('complete'):
        store(folder,cache,result,document,blocks_path,value,
              expected_pdf_stamp=pdf_stamp,expected_blocks_stamp=blocks_stamp,
              expected_layout_stamp=layout_before)
    return value


def save_display_hierarchy(cache,result):
    if not cache:return
    try:save_hierarchy(cache,result)
    except OSError:pass  # Disposable display metadata cannot hide saved prose.


def display_source_headings(folder,blocks,*,status=None,groups=None):
    """K1.1 projection shares the existing plan across both study views."""
    from pdf_newest_k1_2_0_native import supplement
    source=hierarchy.source_headings(supplement(folder,blocks,status=status))
    return hierarchy.planned_headings(blocks,groups or [],source)


def save_hierarchy(cache,result):
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    hierarchy.export(cache,result)
    suffix=f'{result.get("scope","document")}-{result.get("page") or 0}'
    target=cache.parent/f'hierarchy-{suffix}.json'
    data=(cache/'hierarchy.json').read_bytes()
    if not target.exists() or target.read_bytes()!=data:target.write_bytes(data)


def planner_identity(model='gpt-6-luna', transport=None):
    transport=PLAN_TRANSPORT if transport is None else transport
    if transport == 'ids' and PLAN_WINDOW_BYTES == 50000 and PLAN_WINDOW_BLOCKS == 220:
        return digest([LAYOUT_VERSION, PLAN_PROMPT, PLAN_FORMAT, model])
    from pdf_group_transport import VERSION, prompt, RANGE_FORMAT
    from pdf_k123_planning_packets import VERSION as PACKET_VERSION
    return digest([LAYOUT_VERSION, prompt(PLAN_PROMPT), K1_RANGE_FORMAT, model,
                   VERSION, PACKET_VERSION, PLAN_WINDOW_BYTES, PLAN_WINDOW_BLOCKS])


def compatible_planner_identities(model='gpt-6-luna'):
    # Range encoding changes wire metadata only. Confirmed old ID-list plans
    # still require the same full independent source-partition proof and model.
    # Never make existing users pay again just to migrate that representation.
    return tuple(dict.fromkeys([planner_identity(model)]+(
        [planner_identity(model,'ids')]if PLAN_TRANSPORT=='ranges'else [])))


def teaching_identity():
    from pdf_newest_k1_2_0_guard import POLICY, RULES
    # Only the wire source index changes. Keep previously paid teaching and
    # pending receipts addressable under the same source/learning identity.
    key=[REVIEW_VERSION,POLICY,RULES,CANONICAL_STUDY_PROMPT,BATCH_RULES,STUDY_FORMAT,TEXT_INPUT_VERSION,'k113-first-three-next-one-then-10-5-v1',PRACTICE_COMPRESSION]
    key.append(['savingsProfile',SAVINGS_PROFILE])
    if PARTIAL_NATIVE_VISUAL_HINTS:key.extend([TEACHING_PAYLOAD_VERSION,PARTIAL_NATIVE_VISUAL_HINT])
    if NEUTRAL_VISUAL_HINT or STATEMENT_UNCERTAINTY or OWNED_TEACHING or COMPACT_TABLE_SETUP:
        key.extend([NEUTRAL_VISUAL_HINT,STATEMENT_UNCERTAINTY,OWNED_TEACHING,COMPACT_TABLE_SETUP])
    if STUDY_TEMPERATURE is not None:key.append(['temperature',STUDY_TEMPERATURE])
    if IMAGE_REGION_LABELS:key.append(['imageRegions',True])
    if IMAGE_SOURCE_LABELS:key.append(['imageSourceLabels',True])
    if STUDY_REASONING_EFFORT != 'none':key.append(['reasoning_effort',STUDY_REASONING_EFFORT])
    if SOURCE_COVERAGE_HINT:key.append(['sourceCoverage',SOURCE_COVERAGE_RULES])
    if SOURCE_FACTS:
        from pdf_source_facts import VERSION as FACTS_VERSION
        key.append(['sourceFacts',FACTS_VERSION])
    if VISUAL_TEACHING:
        from pdf_visual_teaching import VERSION as VISUAL_WIRE_VERSION
        key.append(['visualTeaching',VISUAL_WIRE_VERSION])
    return digest(key)


def study_workers():
    """Changing request admission must never change the semantic teaching jobs."""
    if os.environ.get('SYNESIS_SUMMARY_SERIAL') == '1':
        return 1
    return min(MAX_STUDY_WORKERS, max(1, int(WORKERS)))


def generation_schedule(ready, jobs, *, front=None):
    schedule=sorted(ready,key=lambda i:(-work_weight(jobs[i]['blocks']),i))
    # Keep the original front even on resume: cached opening units must not
    # promote arbitrary later pages into two new priority requests.
    if front is None:front=[i for i,job in enumerate(jobs) if not job.get('skip')][:2]
    priority=[i for i in front if i in ready]
    return priority+[i for i in schedule if i not in priority]


def transport_batches(indices, jobs, *, preview=True, preview_indices=None):
    """Pack original units, never their teaching or source ownership.

    A batch occupies one available request worker. It is not a pair of
    waiting workers, which would accidentally halve network concurrency.
    """
    count=TRANSPORT_BATCH_UNITS;limit=TRANSPORT_BATCH_IMAGES
    if type(count) is not int or not 1<=count<=4 or type(limit) is not int or limit not in (4,8,16):
        raise ValueError('지원하지 않는 독립 묶음 전송 설정이에요.')
    pending=list(indices);result=[]
    if count==1:return [[i] for i in pending]
    if preview_indices is not None:
        for i in preview_indices:
            if i in pending:result.append([i]);pending.remove(i)
    elif preview and pending:result.append([pending.pop(0)])
    if TRANSPORT_BALANCED:
        # Pairing is a source/image packaging decision, independent of worker
        # capacity. More workers only dispatch these same requests sooner.
        # Keep the opening preview requests separate as before.
        target=(len(pending)+count-1)//count
        while pending:
            slots=min(count,(len(pending)+max(1,target)-1)//max(1,target))
            first=pending.pop(0);batch=[first];images=len(crop_runs(jobs[first]['blocks']))
            # Pair a long job with shorter independent jobs instead of putting
            # the four longest replies behind one serial output stream.
            for i in reversed(pending):
                if len(batch)>=slots:break
                size=len(crop_runs(jobs[i]['blocks']))
                if images+size<=limit:
                    batch.append(i);images+=size
            chosen=set(batch);pending=[i for i in pending if i not in chosen]
            result.append(batch);target=max(0,target-1)
        return result
    while pending:
        batch=[];images=0
        for i in list(pending):
            size=len(crop_runs(jobs[i]['blocks']))
            if batch and images+size>limit:continue
            batch.append(i);images+=size;pending.remove(i)
            if len(batch)==count:break
        result.append(batch)
    return result


def transport_subset(frozen_batches, indices):
    """Keep original partners, including after unordered budget deferrals.

    An already accepted partner is not regenerated: a remaining child can be
    isolated, but it can never acquire an unrelated new partner.
    """
    pending=set(indices)
    if len(pending)!=len(indices):raise ValueError('Duplicate deferred units')
    batches=[]
    for original in frozen_batches:
        batch=[i for i in original if i in pending]
        if batch:batches.append(batch);pending.difference_update(batch)
    if pending:raise ValueError('Unit missing from frozen transport plan')
    return batches


def request_schedule(batches, jobs, *, front=()):
    """Reorder already packed requests, never change their units/images/pairing.

    Native-text length alone underrates image-heavy charts and tables. Area is
    a cheap source-geometry proxy, requiring neither decoding nor another call.
    The original two opening units always retain their initial priority.
    """
    if not VISUAL_REQUEST_PRIORITY:return batches
    def cost(batch):
        weight=0.0
        for i in batch:
            blocks=jobs[i]['blocks'];weight+=work_weight(blocks)
            for run in crop_runs(blocks):
                boxes=[b['bbox']for b in run]
                width=max(b[2]for b in boxes)-min(b[0]for b in boxes)
                height=max(b[3]for b in boxes)-min(b[1]for b in boxes)
                weight+=3500*max(0,min(1,width*height))
        return weight
    opening=[b for b in batches if any(i in front for i in b)]
    pending=[b for b in batches if not any(i in front for i in b)]
    return opening+sorted(pending,key=cost,reverse=True)


def usable_plan(plan, model='gpt-6-luna', blocks=None):
    if not (isinstance(plan,dict) and plan.get('plannerIdentity')in compatible_planner_identities(model)
            and plan.get('status')=='confirmed' and not plan.get('warnings')):
        return False
    try:
        # Internal callers supply independent canonical extraction. Historical
        # valid plans need no paid migration merely to acquire a local proof.
        canonical=blocks if blocks is not None else [b for g in plan['groups'] for b in g['blocks']]
        proof=validate_partition(canonical,plan['groups'],require_global_order=False)
        stored=plan.get('sourcePartition')
        return stored is None or stored==proof
    except (PartitionError,KeyError,TypeError,ValueError):
        return False


def plan_record(groups, warnings, model, headings=None, *, blocks=None, recovery=None):
    canonical=blocks if blocks is not None else [b for g in groups for b in g['blocks']]
    proof=validate_partition(canonical,groups,require_global_order=False)
    value={'groups':groups,'warnings':warnings,'plannerIdentity':planner_identity(model),
           'status':'confirmed','headings':headings or [],'sourcePartition':proof}
    if recovery is not None:value['assignmentRecovery']=recovery
    return value


def local_groups(blocks, strategy):
    groups = []
    for b in blocks:
        # Whole-page direct mode, and visual-only neighbors, remain together.
        if groups and groups[-1]['blocks'][-1]['page'] == b['page'] and (
                strategy == 'slide-v1' or b['visualOnly'] or groups[-1]['blocks'][-1]['visualOnly']
                or len(b['text'].strip()) < 80 or len(groups[-1]['blocks'][-1]['text'].strip()) < 80):
            groups[-1]['blocks'].append(b)
        else:
            title = next((s.strip() for s in b['text'].splitlines() if s.strip()), '학습 내용')[:100]
            groups.append({'title':title, 'blocks':[b]})
    return groups


def planning_fragment(block):
    value={k:block[k] for k in ('id','page','text','kind','headingId','zone','localRole') if k in block}
    if block.get('hasVisual') and block.get('kind')!='visual':value['hasVisual']=True
    if substantive_visual(block):value['visualContentRequiresReading']=True
    return value


def normalize_groups(blocks, groups):
    """Preserve source order and attach heading chains to their following content.

    This local guard prevents the observed page-end heading from being consumed by
    an earlier topic even when the model assigns it there. No review API call.
    """
    labels={b['id']:i for i,g in enumerate(groups) for b in g['blocks']}
    titles={i:g['title'] for i,g in enumerate(groups)}
    descriptions={i:compact_description(g.get('description','')) for i,g in enumerate(groups)}
    paths={i:hierarchy.topic_path(g.get('topicPath')) for i,g in enumerate(groups)}
    for i,b in enumerate(blocks):
        if b['id'] not in labels:labels[b['id']]=len(groups)+i
    for i in range(len(blocks)-2,-1,-1):
        if (blocks[i].get('kind') in ('heading','label')
                and blocks[i].get('planRole') not in ('navigation','exercise')
                and blocks[i+1].get('planRole') not in ('navigation','exercise')):labels[blocks[i]['id']]=labels[blocks[i+1]['id']]
    result=[];last_label=None
    for b in blocks:
        label=labels[b['id']]
        starts_heading=False  # The planner owns semantic boundaries; typography alone is not a new job.
        if not result or label!=last_label or starts_heading:
            result.append({'title':titles.get(label,b['text'] if b.get('kind')=='heading' else '학습 내용'),'description':descriptions.get(label,''),'topicPath':paths.get(label,[]),'blocks':[]})
        result[-1]['blocks'].append(b);last_label=label
    return result


def repeated_margin_ids(blocks):
    """Recognize short, identical page furniture from independent layout evidence.

    Exact text and position must recur on >=60% of at least three pages. Never
    infer missing prose, normalize numbers, or classify visual/heading regions.
    This runs after the paid response so existing request/cache keys stay intact.
    """
    pages={b['page'] for b in blocks}
    if len(pages)<3:return set()
    tracks={}
    for block in blocks:
        if (block.get('kind') not in ('text','label') or block.get('hasVisual')
                or block.get('visualOnly') or block.get('visualKinds')):continue
        text=' '.join(unicodedata.normalize('NFC',block.get('text','')).split())
        box=block.get('bbox',[])
        if not text or len(text)>160 or len(box)!=4:continue
        try:
            x0,y0,x1,y1=map(float,box)
            if not (0<=x0<x1<=1 and 0<=y0<y1<=1 and y1-y0<=.035
                    and (y1<=.10 or y0>=.94)):continue
        except (TypeError,ValueError):continue
        key=(text,tuple(round(v,3) for v in (x0,y0,x1,y1)))
        tracks.setdefault(key,[]).append(block)
    return {b['id'] for members in tracks.values()
            if len({b['page'] for b in members})>=max(3,(len(pages)*3+4)//5)
            for b in members}


def normalized_plan(blocks, results):
    order = {b['id']:i for i,b in enumerate(blocks)}
    for group in results:
        group['blocks'].sort(key=lambda b:order[b['id']])
    results.sort(key=lambda g:order[g['blocks'][0]['id']])
    validate_partition(blocks,results,require_global_order=False)
    # normalize_groups uses the canonical source objects; transfer only local
    # annotations, never model-provided source text, pixels, geometry or IDs.
    assigned={b['id']:b for g in results for b in g['blocks']}
    for block in blocks:
        for field in ('planRole','planRoleBeforeVisualGuard','visualReadingRequired'):
            if field in assigned[block['id']]:block[field]=assigned[block['id']][field]
            else:block.pop(field,None)
    results = protect_visual_groups(normalize_groups(blocks, results))
    validate_partition(blocks,results)
    return results


def plan_groups(folder, provider, blocks, cache, *, on_prefix=None):
    """Group once; lost-ID planners may use an explicitly local source partition."""
    check_cancel(folder)
    validate_partition(blocks,[{'blocks':blocks}] if blocks else [])
    all_blocks=read_json(cache/'blocks.json') or blocks
    margin_ids=repeated_margin_ids(all_blocks)
    source_headings=hierarchy.source_headings(all_blocks)
    windows, current, used = [], [], 0
    for b in blocks:
        amount = len(json.dumps(planning_fragment(b), ensure_ascii=False).encode())
        if current and (used+amount > PLAN_WINDOW_BYTES or len(current) >= PLAN_WINDOW_BLOCKS):
            windows.append(current); current, used = [], 0
        current.append(b); used += amount
    if current:
        windows.append(current)
    results, warnings = [], []
    def work(index):
        check_cancel(folder)
        targets = windows[index]
        # Scans have no useful text for a text-only planner: go directly to vision.
        if not any(b['text'].strip() for b in targets):
            return None, {'textlessScanBypass':True}
        before = windows[index-1][-2:] if index else []
        after = windows[index+1][:2] if index+1 < len(windows) else []
        provider.context = {'kind':'region_plan', 'strategy':'newest-k1-2-6',
                            'pages':sorted({b['page'] for b in targets}),
                            'studyGroupTransport':PLAN_TRANSPORT,
                            'studyConnectionRepairAllowed':True}
        if DURABLE_STUDY_BODY:provider.context['studyDurable']=True
        if FOREGROUND_STUDY_BODY:provider.context['studyForegroundResponses']=True
        if PLAN_TRANSPORT == 'ranges':
            from pdf_group_transport import request, prompt, RANGE_FORMAT
            from pdf_k123_planning_packets import pack,fragment,recover
            from pdf_ai import complete_study_delivery
            from pdf_ai import MissingPaidResponseError
            packets=pack(targets)
            packet_fragment=lambda b:fragment(b,planning_fragment)
            try:
                raw = complete_study_delivery(provider,request(packets,before,after,packet_fragment),
                    max_output=6000,system_prompt=prompt(PLAN_PROMPT),response_format=K1_RANGE_FORMAT,
                    cache_stable_prefix=True)
            except MissingPaidResponseError as error:
                originals=getattr(error,'local_planner_originals',None)
                if not originals:raise
                # No semantic answer was received. Reuse the existing exact-ID
                # uncertain-run repair only for this blocked window; all sources
                # remain teaching candidates and original charges stay unknown.
                return {'groups':[]},{'lostIdPlannerOriginals':originals,
                    'reason':'fully_uploaded_responses_planner_without_response_id',
                    'additionalRecoveryApiRequests':0}
            return recover(raw,packets,targets)
        from pdf_ai import complete_study_delivery
        raw = complete_study_delivery(provider,{'task':'region_groups', 'targets':[planning_fragment(b) for b in targets],
            'before':[planning_fragment(b) for b in before], 'after':[planning_fragment(b) for b in after]}, max_output=6000, system_prompt=PLAN_PROMPT,
            response_format=PLAN_FORMAT, cache_stable_prefix=True)
        return raw, {}
    pending = {};recoveries=[];scan_windows=[];next_window=0;prefix_ready=False
    def consume(i):
        targets=windows[i]
        check_cancel(folder)
        raw, transport = pending[i]
        if transport.get('textlessScanBypass'):
            # A scan intentionally bypasses a text-only request; transport and
            # invalid top-level JSON errors must still propagate, never land here.
            for block in targets:
                for field in ('planRole','planRoleBeforeVisualGuard','visualReadingRequired'):
                    block.pop(field,None)
            results.extend(local_groups(targets, 'slide-v1'))
            scan_windows.append({'windowIndex':i,'sourceBlockIds':[b['id'] for b in targets],
                                 'reason':'textless_source_read_directly_by_vision'})
            return
        repaired, recovery = repair_partition(raw,targets,furniture_ids=margin_ids)
        for group in repaired:
            source_index=group.get('sourceGroupIndex')
            source=(raw.get('groups') or [])[source_index] if isinstance(source_index,int) and 0<=source_index<len(raw.get('groups') or []) else {}
            group['description']=compact_description(source.get('description',''))
            group['topicPath']=hierarchy.topic_path(source.get('topicPath'))
        recovery.update(windowIndex=i,sourceBlockIds=[b['id'] for b in targets])
        if transport:recovery['transportRecovery']=transport
        recoveries.append(recovery)
        # Keep the model's owner labels until normalize_groups applies source
        # order and heading guards. Local uncertain runs remain separate owners.
        owners={};window_groups=[]
        for group in repaired:
            key=group.get('sourceGroupIndex') if group['assignmentOrigin']=='ai' else None
            if key is not None and key in owners:
                owners[key]['blocks'].extend(group['blocks'])
            else:
                window_groups.append(group)
                if key is not None:owners[key]=group
        for group in window_groups:
            if (group.get('continuesPrevious') and results
                    and group.get('assignmentOrigin')=='ai'
                    and results[-1].get('assignmentOrigin')=='ai'
                    and results[-1].get('role')==group.get('role')):
                results[-1]['blocks'].extend(group['blocks'])
                results[-1]['description']=compact_description(' '.join(dict.fromkeys(filter(None,[results[-1].get('description',''),group.get('description','')]))))
            else:results.append(group)

    emit('study_timeline',stage='group_progress',percent=11,completedWindows=0,totalWindows=len(windows))
    with ThreadPoolExecutor(max_workers=min(study_workers(),max(1,len(windows)))) as pool:
        futures={pool.submit(work,i):i for i in range(len(windows))}
        for future in as_completed(futures):
            pending[futures[future]]=future.result()
            while next_window in pending:
                consume(next_window);next_window+=1
                if on_prefix is not None and not prefix_ready:
                    consumed=[b for window in windows[:next_window] for b in window]
                    # A future continuesPrevious can only extend the last owner.
                    # Exclude every normalized fragment of that owner, including
                    # any heading chain reassigned to it by the source guard.
                    prefix=normalized_plan(copy.deepcopy(consumed),copy.deepcopy(results))
                    pos={b['id']:n for n,b in enumerate(consumed)}
                    final=next_window==len(windows)
                    edge=min(pos[b['id']] for b in results[-1]['blocks']) if results else 0
                    stable=[]
                    for group in prefix:
                        if not final and max(pos[b['id']] for b in group['blocks'])>=edge:break
                        stable.append(group)
                    prefix_ready=on_prefix(stable,final=final) is True
            emit('study_timeline',stage='group_progress',percent=11+8*len(pending)//max(1,len(windows)),
                 completedWindows=len(pending),totalWindows=len(windows))
    results = normalized_plan(blocks,results)
    local_ids=[key for r in recoveries for key in r['localUncertainBlockIds']]
    recovered=any(r['semanticGroupingStatus']=='locally_recovered'
                  or r.get('transportRecovery',{}).get('invalidRangeGroups') for r in recoveries)
    audit={'version':PARTITION_VERSION,'windows':recoveries,
           'directVisualWindows':scan_windows,
           'localUncertainBlockIds':local_ids,'additionalRecoveryApiRequests':0,
           'semanticGroupingStatus':('locally_recovered' if recovered else
               'direct_visual' if not recoveries and scan_windows else
               'ai_assigned_with_direct_visual' if scan_windows else 'ai_assigned'),
           'confirmationScope':'exact source partition; uncertain ownership is not AI semantic confirmation'}
    write_json(cache/'plan.json', plan_record(results,warnings,provider.model,source_headings,
                                             blocks=blocks,recovery=audit))
    margin_recovered=[key for r in recoveries for key in r['unassignedBlockIds'] if key in margin_ids]
    if recovered:
        write_json(cache/'plan-local-recovery.json',{
            **audit,'reason':'source_partition_recovery' if local_ids else 'repeated_page_furniture',
            'blockIds':local_ids or margin_recovered})
    return results, warnings



def entry_label(block):
    """Hints from explicit definition/list labels, never guessed from sentences."""
    if block.get('kind') in ('heading','label','caption','visual','page'):
        return None
    text=block['text'].strip()
    match=re.match(r'^(?:[①-⑳]\s*|\d+[.)]\s+)?([^:\n：]{1,85})[:：]\s*\S',text)
    if match and not match[1].startswith(('출처','자료','예시','예제','(예','참고','비유')):
        return match[1].strip()
    if len(text)<60 and re.match(r'^[①-⑳]\s*',text) and not re.search(r'[.!?。]$',text):
        return re.sub(r'^[①-⑳]\s*','',text)
    return None


def work_weight(blocks):
    return sum(len(b['text'].encode()) for b in blocks)+200*sum(bool(entry_label(b)) for b in blocks)


def generation_cuts(group):
    """One transport cut after a complete explicit classification, never within it.

    This narrow optimization does not infer topics from consecutive numbering.
    Incomplete lists, intervening visuals, derivations and small jobs keep the
    existing packing; semantic groups, prompts and UI topic indices stay intact.
    """
    blocks=group['blocks'];total=work_weight(blocks)
    if total<3200 or (total<7000 and sum(bool(entry_label(b)) for b in blocks)<6):return set()
    counts={'두':2,'세':3,'네':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}
    def number(block):
        text=block['text'].lstrip()
        if text and '①'<=text[0]<='⑳':return ord(text[0])-ord('①')+1
        match=re.match(r'^(?:\((\d{1,2})\)|(\d{1,2})[.):])\s+',unicodedata.normalize('NFKC',text))
        return int(next(v for v in match.groups() if v)) if match else None
    def footer(block):
        return block.get('kind')=='page_number' or bool(re.fullmatch(r'\d{1,4}',block['text'].strip()))
    candidates=[]
    for index,parent in enumerate(blocks):
        text=unicodedata.normalize('NFKC',parent['text']).strip()
        if len(text)>180 or re.search(r'변수|기호|조건|단계|과정|유도|증명',text):continue
        count=re.search(r'(?<![\w])([2-9]|1\d|20|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:가지|종류|유형)',text)
        if not count:continue
        token=count[1];size=int(token) if token.isdigit() else counts[token];expected=1
        for end in range(index+1,len(blocks)):
            block=blocks[end]
            if footer(block):continue
            if block.get('hasVisual') or block.get('kind') in ('visual','caption'):break
            item=number(block)
            if item!=expected:break
            expected+=1
            if item!=size:continue
            following=end+1
            while following<len(blocks) and footer(blocks[following]):following+=1
            # A following table, caption or continued explanation still belongs
            # to the completed list. Only a fresh explicit definition is safe.
            if following<len(blocks) and entry_label(blocks[following]) and number(blocks[following]) is None:
                left=work_weight(blocks[:end+1])
                if left>=800 and total-left>=800:candidates.append((abs(left-total/2),block['id']))
            break
    return {min(candidates)[1]} if candidates else set()


def jobs_for(groups):
    """Pack teaching panels, splitting dense groups only at complete classifications.

    Multiple concept entries can share one generation request. Four crops remain
    the transport cap; split requests retain the same semantic/UI topic.
    """
    jobs=[]
    for topic,group in enumerate(groups):
        start=len(jobs);spans=[];cuts=generation_cuts(group)
        for block in group['blocks']:
            panel=(block['page'],block.get('zone',0))
            if (not spans or spans[-1][-1]['id'] in cuts
                    or (spans[-1][0]['page'],spans[-1][0].get('zone',0))!=panel):
                spans.append([])
            spans[-1].append(block)
        batch=[]
        for span in spans:
            if batch and batch[-1]['id'] in cuts:
                jobs.append({'title':group['title'],'topicIndex':topic,'blocks':batch});batch=[]
            if len(crop_runs(span))>4:
                if batch:jobs.append({'title':group['title'],'topicIndex':topic,'blocks':batch});batch=[]
                from pdf_study_review import pack_crop_runs
                for run in pack_crop_runs(crop_runs(span),crop_runs,work_weight,JOB_CROP_LIMIT,JOB_WEIGHT_LIMIT):
                    jobs.append({'title':group['title'],'topicIndex':topic,'blocks':run})
                continue
            combined=batch+span
            if batch and (len(crop_runs(combined))>JOB_CROP_LIMIT or work_weight(combined)>JOB_WEIGHT_LIMIT
                    or len({b['page'] for b in combined})>JOB_PAGE_LIMIT):
                jobs.append({'title':group['title'],'topicIndex':topic,'blocks':batch});batch=[]
            batch.extend(span)
        if batch:jobs.append({'title':group['title'],'topicIndex':topic,'blocks':batch})
        if cuts or (len(jobs)>start+1 and (JOB_WEIGHT_LIMIT,JOB_CROP_LIMIT,JOB_PAGE_LIMIT)!=(10000,4,4)):
            for job in jobs[start:]:job['contextDepth']=4
    attach_unit_context(jobs,groups)
    for job in jobs:
        key=[job['title'],job['blocks'],job['unitContext']]
        if 'contextDepth' in job:key.append(job['contextDepth'])
        job['id']=digest(key)[:24]
    return jobs


def lead_with_visual_page(groups):
    """Place an image-only slide before the next related teaching passage.

    This changes transport order, not the number of model reviews or concepts.
    The caller retains the old grouping if the study-job count would rise.
    """
    result=copy.deepcopy(groups);moved=[]
    def heading(text):
        return re.sub(r'[^a-z0-9가-힣]','',(text or '').casefold())
    for i in range(len(result)-1):
        before,after=result[i]['blocks'],result[i+1]['blocks']
        if len(before)<2 or not after:continue
        visual=before[-1]
        if not (visual.get('kind')=='page' and visual.get('hasVisual')
                and visual.get('visualOnly') and not visual.get('text','').strip()
                and visual.get('planRole')=='teaching'
                and after[0].get('planRole')=='teaching'
                and visual['page']==after[0]['page']-1
                and all(b['page']!=visual['page'] for b in before[:-1])
                and heading(visual.get('headingTitle'))
                and heading(visual.get('headingTitle'))==heading(after[0].get('headingTitle'))
                and len(crop_runs([visual]+after))<=4):continue
        old_count=len(jobs_for(result[i:i+2]))
        before.pop();after.insert(0,visual)
        if len(jobs_for(result[i:i+2]))>old_count:
            after.pop(0);before.append(visual)
        else:moved.append(visual['page'])
    return result,moved


def teaching_payload(job, crops, context, neighbors):
    # Pixel geometry/font metadata stays in the local manifest. The model needs
    # full source text and image-to-ID mapping, not repeated extraction metadata.
    hint={} if NEUTRAL_VISUAL_HINT and any(substantive_visual(b) for b in job['blocks']) else {'titleHint':job['title']}
    targets=[];partial_visual_text=False
    image_ids={i for crop in crops for i in crop.get('blockIds',[])}
    for block in job['blocks']:
        target={k:block[k] for k in ('id','page','kind','text','planRole') if k in block}
        if block.get('nativeTextProof')==TEXT_INPUT_VERSION and block['id'] not in image_ids:
            target['nativeTextOnly']=True
        if block.get('visualOnly') and block.get('hasVisual'):
            target.update(kind='visual',hasVisual=True)
        if PARTIAL_NATIVE_VISUAL_HINTS and substantive_visual(block):
            target.update(hasVisual=True,visualContentRequiresReading=True)
            if block.get('text','').strip():
                target['nativeTextIsPartialVisualExtraction']=True
                partial_visual_text=True
        targets.append(target)
    return {'task':'region_teaching',**hint,'unitContext':copy.deepcopy(job.get('unitContext',{})),
        **({'visualReadingHint':PARTIAL_NATIVE_VISUAL_HINT} if partial_visual_text else {}),
        'blocks':targets,
        'entryHints':[{'title':entry_label(b),'startsAt':b['id']} for b in job['blocks'] if entry_label(b)],
        'crops':[{'page':c['page'],'blockIds':c.get('blockIds',[])} for c in crops],
        'documentContext':{'pageCount':context.get('pageCount')},'neighboringContext':neighbors}


def image_source_label_metadata(job, payload, crops):
    """Locate substantial target visuals inside unchanged crop pixels.

    Crop geometry stays canonical and local. Only the small wire label receives
    crop-relative boxes, with source IDs paired to their wire aliases by order.
    """
    labels=copy.deepcopy(payload['crops'])
    if not IMAGE_REGION_LABELS:return labels
    def valid_box(box):
        return (isinstance(box,(list,tuple)) and len(box)==4
                and all(isinstance(v,(int,float)) and not isinstance(v,bool)
                        and math.isfinite(v) for v in box)
                and box[2]>box[0] and box[3]>box[1])
    wire_ids={original['id']:wire['id'] for original,wire in zip(job['blocks'],payload['blocks'])}
    for crop,label in zip(crops,labels):
        box=crop.get('bbox')
        if not valid_box(box):continue
        width,height=box[2]-box[0],box[3]-box[1]
        selected=set(crop.get('blockIds',[]));regions=[]
        for block in job['blocks']:
            source=block['id'];region=block.get('bbox')
            if (source not in selected or block.get('page')!=crop.get('page')
                    or not valid_box(region) or not substantive_visual(block)):
                continue
            if (min(region[2],box[2])<=max(region[0],box[0])
                    or min(region[3],box[3])<=max(region[1],box[1])):
                continue
            relative=[(region[0]-box[0])/width,(region[1]-box[1])/height,
                      (region[2]-box[0])/width,(region[3]-box[1])/height]
            regions.append({'blockId':wire_ids[source],
                'box':[round(max(0.,min(1.,v)),4) for v in relative]})
        if regions:label['visualRegions']=regions
    return labels


def job_neighbors(blocks, job, positions):
    """Small source context, skipping page furniture; never a second model pass."""
    left=min(positions[b['id']] for b in job['blocks'])
    right=max(positions[b['id']] for b in job['blocks'])
    neighbors=[];seen=set();limit=job.get('contextDepth',1)
    # A caption may follow its large raster and be detected as a heading. It is
    # still useful local context for that image even when a planner put the two
    # in adjacent topics; it is never assigned/cited as a target here.
    visual_panels={(b['page'],b.get('zone',0)) for b in job['blocks'] if substantive_visual(b)}
    for index in (left-1,right+1):
        if not 0<=index<len(blocks):continue
        b=blocks[index];text=b.get('text','').strip()
        if ((b['page'],b.get('zone',0)) in visual_panels and b.get('kind') in ('heading','caption','label')
                and text and len(text)<=180):
            neighbors.append({'page':b['page'],'text':text,'backgroundOnly':True})
            seen.add(b['id'])
    for start,step,edge in ((left-1,-1,job['blocks'][0]),(right+1,1,job['blocks'][-1])):
        found=0
        for index in range(start,start+step*6,step):
            if not 0<=index<len(blocks):break
            b=blocks[index]
            if not edge.get('headingId') or b.get('headingId')!=edge['headingId']:break
            if b.get('kind') in ('heading','label'):break
            text=b.get('text','').strip()
            if (not text or b.get('kind')=='page_number'
                    or b.get('localRole') in ('decoration','navigation','exercise')
                    or b.get('planRole') in ('decoration','navigation','exercise')):continue
            parent=(step==-1 and len(text)<=120 and re.search(
                r'종류|유형|분류|\b(?:types?|kinds?|categories)\b',text,re.I))
            if (found<limit or parent) and b['id'] not in seen:
                neighbors.append({'page':b['page'],'text':text[:600],'backgroundOnly':True})
                seen.add(b['id'])
            found+=1
            if (step==1 and found>=limit) or parent:break
    from pdf_study_review import section_source_context
    return section_source_context(blocks,job,neighbors)


def plain_cover_ids(blocks):
    """Conservative metadata-only lecture cover; diagrams/teaching stay remote."""
    first=[b for b in blocks if b['page']==1]
    text=' '.join(b['text'].strip() for b in first)
    if (first and len(text)<160 and '강의노트' in text
            and re.search(r'\d{4}년\s*\d학기',text)
            and not any(b.get('hasVisual') or b.get('geometryFallback') for b in first)
            and not re.search(r'[:：=.!?→]|[①-⑳]',text)):
        return {b['id'] for b in first}
    return set()


def evidence(block, document):
    return {'sourceId':block['id'], 'documentId':document['documentId'], 'page':block['page'],
            'pageLabel':document['pages'][block['page']-1].get('label'), 'source':'region_image',
            'field':'none', 'quote':'', 'start':0, 'end':0, 'bbox':block['bbox']}


def validate(raw, job, document, *, preserve_boundaries=True):
    from pdf_k120_compact_coverage import supplement_only_sources,retain_supplement_review
    supplemental_sources=(supplement_only_sources(raw)
        if isinstance(raw,dict) and raw.get(CANONICAL_MARKER)==COMPACT_COVERAGE_VERSION else set())
    structured=content_contract_active(raw)
    if structured:
        from pdf_saved_teaching_compat import processing_records
        raw,_=processing_records(raw,[b['id']for b in job['blocks']])
    from pdf_new_concept_ver99_checks import prepare_response
    raw = prepare_response(repair_source_ids(raw,[b['id'] for b in job['blocks']]),
                           preserve_boundaries=preserve_boundaries, distinguish_supplements=True,
                           review_policy=ReviewPolicy(job['blocks']))

    allowed = {b['id']:b for b in job['blocks']}
    parts, cards, accounted, references, resolutions, source_notes = [], [], {}, {}, {}, {}
    concepts = raw.get('concepts') if isinstance(raw,dict) else None
    if not isinstance(concepts,list):
        raise ValueError('개념 응답 형식이 올바르지 않아요.')
    for c in concepts:
        partial=isinstance(c,dict) and c.get('_partialSupported') is True
        if not isinstance(c,dict) or any(not isinstance(c.get(k),str) or
                (not c[k].strip() and (k=='title' or k!='easyExplanation' and not partial and not structured))
                for k in ('title','definition','explanation','easyExplanation')):
            raise ValueError('개념의 제목·정의·설명이 비어 있어요.')
        if structured and not (c['definition'].strip()or c['explanation'].strip()):
            raise ValueError('독립 개념의 본문이 비어 있어요.')
        ids = c.get('blockIds',[])
        if not ids or any(x not in allowed for x in ids):
            raise ValueError('개념에 원문 영역 밖의 출처가 있어요: '+repr([x for x in ids if x not in allowed]))
        # A short qualification/continuation can be substantive. Its checked
        # explanation must not be discarded by a character-count/verb whitelist.
        refs = [evidence(allowed[x],document) for x in dict.fromkeys(ids)]
        pages = sorted({e['page'] for e in refs})
        common = {'easyExplanation':c['easyExplanation'], 'evidence':refs, 'visualPages':pages,
                  **({'partialSupported':True} if partial else {}),
                  **hierarchy.placement(c,job),
                  'standardKnowledgeUsed':c.get('standardKnowledgeUsed') is True
                      or bool(re.search(r'(?:비유|추가 예시)\s*[:：*]',c['easyExplanation']))}
        parts.append({'title':c['title'], 'body':'\n\n'.join(v for v in
            (c['definition'],c['explanation']) if v.strip()), **common})
        cards.append({'name':c['title'], 'aliases':[], 'definition':c['definition'],
                      'explanation':c['explanation'], 'example':'', 'confusion':'', **common})
        accounted.update({x:('summarized','개념 설명에 반영했어요.') for x in ids})
    attach_step_flows(raw.get('sequences',[]),concepts,parts,allowed,document,cards=cards)
    attach_comparison_tables(raw.get('tables',[]),concepts,parts,cards,allowed)
    from pdf_k113_coverage import link_supported
    link_supported(raw,allowed,parts,cards,accounted,lambda b:evidence(b,document))
    if structured:
        from pdf_saved_teaching_compat import compose
        for item in raw.get('diagnostics',[]):
            if any(i not in allowed for i in item.get('blockIds',[])):
                raise ValueError('처리 기록에 원문 영역 밖의 ID가 있어요.')
        parts,mentions=compose(raw,parts,cards,allowed,lambda b:evidence(b,document))
        for part in parts:
            accounted.update({ref['sourceId']:('summarized','근거가 있는 설명 전개에 반영했어요.')
                              for ref in part['evidence']})
        for mention in raw.get('mentions',[]):
            accounted.update({i:('summarized','기존 주제의 짧은 원문 언급에 반영했어요.')for i in mention['blockIds']})
    def formula_stroke(visual):
        box=visual.get('bbox')
        return bool(visual.get('kind')=='visual' and box
            and 'vector' in visual.get('visualKinds',[]) and any(
                other['id']!=visual['id'] and accounted.get(other['id'],('',))[0]=='summarized'
                and other.get('kind')=='text' and other.get('bbox')
                and re.search(r'[=∑∫/]',other.get('text',''))
                and all(other['bbox'][p]-0.005<=box[p] if p<2 else
                        box[p]<=other['bbox'][p]+0.005 for p in range(4))
                for other in job['blocks']))
    for field, state in (('excludedBlocks','excluded'), ('uncertainBlocks','needs_review')):
        for item in raw.get(field,[]):
            key = item.get('blockId')
            if key not in allowed:
                raise ValueError('처리 내역에 원문 영역 밖의 ID가 있어요.')
            reason=str(item.get('reason') or '원문 확인이 필요해요.')
            if field=='excludedBlocks':
                from pdf_k113_coverage import disposition
                decision=disposition(item,allowed[key],job['blocks'],parts)
                if decision is not None:
                    if decision['kind'] in ('source_conflict','unlabelled_supporting_figure'):
                        source_notes[key]={**decision,'reason':reason}
                    else:resolutions[key]=decision
                    if key not in accounted:accounted[key]=('context',reason)
                    continue
            context=reference_context(item,allowed[key]) if field=='excludedBlocks' else None
            if context is not None:
                if key not in accounted:
                    accounted[key]=('context',reason)
                    references[key]=context
                # A reference assessment never removes supported teaching sharing
                # that image, including its tables, routes and source conditions.
                continue
            # Exclusion is not uncertainty: an already supported source stays taught.
            if field=='excludedBlocks' and accounted.get(key,('',))[0]=='summarized':continue
            from pdf_study_review import structural_context
            accessory=structural_context(allowed[key],job['blocks'],accounted,reason) if field=='excludedBlocks' else None
            if accessory:
                accounted[key]=('context',accessory);continue
            if field=='excludedBlocks' and exercise_exclusion(item,allowed[key],job['blocks'],parts):
                accounted[key]=('excluded',reason);continue
            invalid_reference=(field=='excludedBlocks' and item.get('referenceContext') is not None
                and not verified_non_teaching_reason(reason))
            unsupported_exclusion=(field=='excludedBlocks' and
                unjustified_visual_exclusion(allowed[key],reason))
            # A page image may contain a whole diagram even when its native text is empty.
            # Never accept a model's "empty page" claim as proof that it teaches nothing.
            visual_empty=(field=='excludedBlocks' and allowed[key].get('hasVisual')
                and not verified_non_teaching_reason(reason)
                and allowed[key].get('planRole') not in ('navigation','exercise','decoration')
                and re.search(r'(?:내용|정보|텍스트|글자).{0,12}(?:없|비어|않|못)|(?:빈|공백)\s*페이지',reason))
            scope_exclusion=(field=='excludedBlocks' and re.search(
                r'(?:이|현재)\s*(?:단위|단락|주제).{0,60}(?:별개|범위\s*밖|포함되지|무관)|'
                r'(?:다른|앞선)\s*(?:단위|단락).{0,40}(?:속하|다루므로|내용이므로)',reason))
            if scope_exclusion:
                state_for_item='needs_review'
                reason='단락 제목과 달라도 현재 원문에 속한 조건·결론은 반영해야 해요: '+reason
            elif invalid_reference:
                state_for_item='needs_review'
                reason='참고 그림으로 생략할 근거가 충분하지 않아요: '+reason
            elif unsupported_exclusion:
                state_for_item='needs_review'
                reason='기사·사례·도식의 중요한 내용이 빠졌는지 확인이 필요해요: '+reason
            elif visual_empty:
                visual=allowed[key]
                # A vector stroke wholly inside a cited formula is part of that
                # formula (typically its fraction bar), not another diagram.
                if formula_stroke(visual):
                    state_for_item='context'
                    reason='이미 설명한 수식 안의 도형 요소예요.'
                else:
                    state_for_item='needs_review'
                    reason='그림 원문에 학습 내용이 있는지 확인이 필요해요: '+reason
            else:state_for_item=state
            if state_for_item=='needs_review' and '제목만' in reason:
                position=job['blocks'].index(allowed[key])
                following=job['blocks'][position+1:position+2]
                if (len(allowed[key].get('text',''))<80 and following
                        and accounted.get(following[0]['id'],('',))[0]=='excluded'):
                    state_for_item='excluded'
                    reason='제외된 예시의 제목이에요.'
            if state_for_item == 'needs_review' or key not in accounted:
                accounted[key] = (state_for_item,reason)
    # A standalone heading organizes the following content; it is not a missing
    # concept when that following content has already been taught. Keep explicit
    # uncertainty and all missing body/visual fragments visible.
    for i, b in enumerate(job['blocks']):
        if b.get('kind') in ('heading','label') and b['id'] not in accounted:
            following=job['blocks'][i+1:]
            # A chain of section/subsection labels all owns the same next body.
            while following and following[0].get('kind') in ('heading','label'):
                following=following[1:]
            next_boundary=next((n for n,x in enumerate(following) if x.get('kind') in ('heading','label')),len(following))
            if any(accounted.get(x['id'],('',))[0]=='summarized' for x in following[:next_boundary]):
                accounted[b['id']]=('context','뒤따르는 학습 내용의 문단 제목으로 연결했어요.')
    from pdf_study_review import structural_context
    for b in job['blocks']:
        if b['id'] not in accounted:
            accessory=structural_context(b,job['blocks'],accounted)
            if accessory:accounted[b['id']]=('context',accessory)
    coverage = []
    explicit_uncertain={x.get('blockId') for x in raw.get('uncertainBlocks',[])}
    for b in job['blocks']:
        state, reason = accounted.get(b['id'], ('needs_review','응답에 이 영역의 처리 여부가 빠졌어요.'))
        if state=='needs_review' and b['id'] not in accounted and formula_stroke(b):
            state,reason='context','이미 설명한 수식 안의 도형 요소예요.'
        coverage.append({'blockId':b['id'], 'page':b['page'], 'state':state, 'reason':reason,
            **({'resolution':{'version':COVERAGE_VERSION,**resolutions[b['id']]}} if b['id'] in resolutions else {}),
            **({'sourceNote':source_notes[b['id']]} if b['id'] in source_notes else {}),
            **({'reviewKind':'content' if b['id'] in explicit_uncertain else 'source_accounting'} if state=='needs_review' else {}),
            **({'referenceContext':references[b['id']], 'evidence':[evidence(b,document)]}
               if state=='context' and b['id'] in references else {})})
    from pdf_study_review import reconcile_coverage
    reconcile_coverage(coverage,job['blocks'])
    from pdf_k113_coverage import reconcile
    reconcile(coverage,job['blocks'],parts,raw)
    title = parts[0]['title'] if len(parts)==1 else job['title']
    summary = {'title':title, 'parts':parts, 'body':'\n\n'.join(p['body'] for p in parts),
               'easyExplanation':'', 'evidence':[e for p in parts for e in p['evidence']],
               'visualPages':sorted({b['page'] for b in job['blocks']}),
               'standardKnowledgeUsed':any(p['standardKnowledgeUsed'] for p in parts),
               'studyContentSkipped':not parts}
    result={'unitId':job['id'],'summary':summary,'concepts':cards,'coverage':coverage,
            'sourceIdRepairs':raw.get('sourceIdRepairs',[]),
            'processingDiagnostics':raw.get('processingDiagnostics',[])}
    if structured:result['contentContract']=raw['contentContract']
    return retain_supplement_review(result,supplemental_sources)



def attach_step_flows(sequences, concepts, parts, allowed, document, *, cards=None):
    """Admit dependent processes; preserve rejected supported details as prose."""
    from pdf_ai import study_math_issues
    from pdf_new_concept_v02_checks import learner_text
    from pdf_new_concept_v02_math import format_math
    from pdf_step_flow_policy import assess_sequence
    if not isinstance(sequences,list):return
    def key(value):return re.sub(r'\s+','',value).casefold()
    for item in sequences:
        if not isinstance(item,dict) or not isinstance(item.get('conceptTitle'),str):continue
        candidates=[(c,i) for c in concepts if isinstance(c,dict)
            and key(c.get('title',''))==key(item['conceptTitle'])
            for i,part in enumerate(parts) if key(part.get('title',''))==key(item['conceptTitle'])]
        if len(candidates)!=1:continue
        concept,index=candidates[0]
        if parts[index].get('stepFlow'):continue
        if not isinstance(item.get('title'),str) or not item['title'].strip():continue
        steps=item.get('steps')
        if not isinstance(steps,list) or not steps:continue
        generated=[];valid=True
        for step in steps:
            if not isinstance(step,dict) or any(not isinstance(step.get(k),str) or not step[k].strip()
                    for k in ('title','body')):valid=False;break
            ids=step.get('blockIds')
            if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or x not in allowed
                    or x not in concept['blockIds'] for x in ids):valid=False;break
            cited=[allowed[x] for x in dict.fromkeys(ids) if allowed[x].get('text','').strip()
                   or substantive_visual(allowed[x])]
            if len(cited)!=len(set(ids)):valid=False;break
            structured=content_contract_active({'contentContract':concept.get('_contentContract')})
            title,removed_title=(step['title'],[])if structured else learner_text(step['title'])
            body,removed_body=(step['body'],[])if structured else learner_text(step['body'])
            if (removed_title or removed_body or not title.strip() or not body.strip()
                    or study_math_issues({'title':title,'body':body})):valid=False;break
            sources=[]
            for block in cited:
                source=evidence(block,document)
                source['quote']=block.get('text','').strip()[:160]
                if not source['quote']:source['sourceMode']='visual'
                sources.append(source)
            generated.append({'title':title,'body':format_math(body),'context':'','insight':'',
                              'evidence':sources})
        if not valid:continue
        flow={'moduleId':'synesis.step-flow','schemaVersion':1,
              'variant':'a' if int(digest([item['title']])[:2],16)%2==0 else 'd',
              'title':item['title'],'steps':generated}
        eligibility=assess_sequence(item,generated,{x:allowed[x] for x in concept['blockIds']})
        if eligibility is not None:
            flow['eligibility']=eligibility;parts[index]['stepFlow']=flow
        else:
            append_sequence_fallback(parts[index],flow)
            if cards is not None:
                matches=[card for card in cards if key(card.get('name',''))==key(item['conceptTitle'])]
                if len(matches)==1:append_sequence_fallback(matches[0],flow)



def attach_comparison_tables(tables, concepts, parts, cards, allowed):
    """Render only source-cited, rectangular comparisons from the same model response."""
    if not isinstance(tables,list):return
    from pdf_table_cells import valid_cell as cell, markdown_cell
    used=set()
    def key(value):return re.sub(r'\s+','',value).casefold()
    for item in tables:
        if not isinstance(item,dict) or not isinstance(item.get('conceptTitle'),str):continue
        matches=[i for i,c in enumerate(concepts) if i<len(parts)
            and key(c.get('title',''))==key(item['conceptTitle'])]
        if len(matches)!=1:continue
        index=matches[0];ids=item.get('blockIds')
        if not isinstance(ids,list) or not ids or any(x not in allowed or x not in concepts[index]['blockIds'] for x in ids):continue
        headers=item.get('headers');rows=item.get('rows')
        if not isinstance(headers,list) or len(headers)<2 or not all(cell(x) for x in headers):continue
        # Responses are already output-token bounded. A row-count display limit
        # used to silently erase valid source tables (e.g. 14 anatomy organs).
        # Keep every rectangular, cited row rather than dropping the whole table.
        if not isinstance(rows,list) or len(rows)<2 or any(
                not isinstance(row,list) or len(row)!=len(headers) or not all(cell(x) for x in row)
                for row in rows):continue
        # Hierarchical comparisons legitimately repeat a parent category
        # (e.g. numeric -> discrete and numeric -> continuous).
        if len({tuple(key(value) for value in row) for row in rows})!=len(rows):continue
        markdown='| '+' | '.join(markdown_cell(x) for x in headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'
        markdown+='\n'.join('| '+' | '.join(markdown_cell(x) for x in row)+' |' for row in rows)
        signature=(index,markdown)
        if signature in used:continue
        # A concept may own several distinct source tables. Do not silently
        # discard every table after the first, or duplicate one on display repair.
        if markdown not in {p.strip() for p in parts[index]['body'].split('\n\n')}:
            parts[index]['body']+='\n\n'+markdown
        if markdown not in {p.strip() for p in cards[index]['explanation'].split('\n\n')}:
            cards[index]['explanation']+='\n\n'+markdown
        used.add(signature)


def assemble(document, strategy, scope, page, targets, jobs, done, failures, warnings, *, headings=None, all_blocks=None):
    from pdf_ai import merge_concepts
    done = consolidate_entries(done)
    ordered = [done[i] for i in sorted(done)]
    sections=[];previous_topic=None
    for i in sorted(done):
        summary=done[i]['summary']
        if not summary['parts']:continue
        topic=jobs[i].get('topicIndex',i)
        if sections and topic==previous_topic:
            section=sections[-1]
            section['title']=jobs[i]['title']
            section['parts'].extend(copy.deepcopy(summary['parts']))
            section['body']+='\n\n'+summary['body']
            section['evidence'].extend(copy.deepcopy(summary['evidence']))
            section['visualPages']=sorted(set(section['visualPages']+summary['visualPages']))
            section['standardKnowledgeUsed']|=summary['standardKnowledgeUsed']
        else:sections.append(copy.deepcopy(summary))
        previous_topic=topic
    coverage = [entry for x in ordered for entry in x['coverage']]
    for i, job in enumerate(jobs):
        if i not in done:
            coverage.extend({'blockId':b['id'],'page':b['page'],'state':'pending_summary',
                             'reason':'이 영역만 다시 생성하면 돼요.'} for b in job['blocks'])
    from pdf_study_review import reconcile_coverage
    reconcile_coverage(coverage,[b for j in jobs for b in j['blocks']])
    from pdf_k113_coverage import reconcile
    reconcile(coverage,[b for j in jobs for b in j['blocks']],
              [p for s in sections for p in s.get('parts',[])])
    unresolved = sorted({e['page'] for e in coverage if e['state'] in ('needs_review','pending_summary')})
    complete = len(done)==len(jobs) and not failures
    result={'kind':'ai_generated' if complete else 'partial', 'model':'gpt-6-luna',
        'strategy':strategy,'promptVersion':VERSION,'documentId':document['documentId'],
        'sourceFingerprint':document['fingerprint'],'scope':scope,'page':page,'sourcePages':targets,
        'contextPages':[],'sections':sections,'concepts':merge_concepts([c for x in ordered for c in x['concepts']]),
        'overview':{'title':'이 강의의 흐름','body':'개념별 설명을 준비하고 있어요.',
                    'easyExplanation':'','evidence':[],'visualPages':[],'standardKnowledgeUsed':False},
        'coverage':coverage,'coverageComplete':not unresolved,'processingComplete':complete,
        'referenceContexts':[copy.deepcopy(e) for e in coverage if 'referenceContext' in e],
        'referenceContextVersion':REFERENCE_VERSION,
        'pageAnalysisIncompletePages':unresolved,'incompleteStudyPages':unresolved,
        'incompletePages':document.get('incompletePages',[]),'visualNotePages':[],
        'partialUnits':len(done),'totalUnits':len(jobs),'integrationPending':False,
        'evidenceIncomplete':bool(unresolved),'processingNotes':warnings,'failedUnits':failures,
        'reviewStatus':'needs_review' if unresolved else 'complete',
        'sourceNotes':[copy.deepcopy(e) for e in coverage if 'sourceNote' in e],
        'coverageReviewVersion':COVERAGE_VERSION,
        'standardKnowledgeUsed':any(s['standardKnowledgeUsed'] for s in sections)}
    contracts={x['contentContract']for x in ordered if content_contract_active(x)}
    if contracts:
        if len(contracts)==1:result['contentContract']=next(iter(contracts))
        else:result['contentContracts']=sorted(contracts)
        result['processingDiagnostics']=[d for x in ordered for d in x.get('processingDiagnostics',[])]
    blocks=[];seen=set()
    for job in jobs:
        for block in job['blocks']:
            if block['id'] not in seen:blocks.append(block);seen.add(block['id'])
    # Layout order, including structural-only chapter headings, comes from plan.
    all_blocks=all_blocks if all_blocks is not None else blocks
    result['_pageLabels']={str(p['number'] if 'number' in p else i+1):p.get('label',str(i+1))
                           for i,p in enumerate(document['pages'])}
    return hierarchy.decorate(result,all_blocks,headings or [])



def consolidate_entries(done):
    """Join repeated exact titles in neighboring source ranges, without erasing
    differing explanations, conditions or citations. Homonyms far apart stay separate.
    This is presentation assembly, never an extra generation/review request.
    """
    result=copy.deepcopy(done);known={}
    def paragraphs(*values):
        kept=[];seen=set()
        for value in values:
            for text in value.split('\n\n'):
                key=re.sub(r'\s+',' ',text).strip()
                if key and key not in seen:kept.append(text);seen.add(key)
        return '\n\n'.join(kept)
    def easy_without_repeated_sentences(previous,addition):
        # Similar wording can carry a different sign, number or condition.
        # Only an identical sentence is safe to omit without another source review.
        old={s.strip() for s in re.split(r'(?<=[.!?])\s+',previous) if s.strip()}
        kept=[]
        for sentence in re.split(r'(?<=[.!?])\s+',addition):
            sentence=sentence.strip()
            if not sentence:continue
            if sentence in old or sentence in kept:continue
            kept.append(sentence)
        return ' '.join(kept)
    for i in sorted(result):
        unit=result[i];parts=[];cards=[]
        if content_contract_active(unit):continue  # Saved structured replies only.
        for part,card in zip(unit['summary']['parts'],unit['concepts']):
            key=(part.get('headingId',''),re.sub(r'\s+','',part['title']).casefold())
            previous=known.get(key)
            pages=set(card['visualPages'])
            if previous and pages and min(abs(a-b) for a in pages for b in previous[1]['visualPages'])<=1:
                old_part,old_card=previous
                old_card['explanation']=paragraphs(old_card['explanation'],
                    '' if old_card['definition']==card['definition'] else card['definition'],card['explanation'])
                old_card['easyExplanation']=paragraphs(old_card['easyExplanation'],
                    easy_without_repeated_sentences(old_card['easyExplanation'],card['easyExplanation']))
                for name in ('evidence','visualPages'):
                    for item in card[name]:
                        if item not in old_card[name]:old_card[name].append(item)
                old_card['visualPages'].sort()
                old_card['standardKnowledgeUsed']|=card['standardKnowledgeUsed']
                old_part.update(body=old_card['definition']+'\n\n'+old_card['explanation'],
                    **{k:copy.deepcopy(old_card[k]) for k in ('easyExplanation','evidence','visualPages','standardKnowledgeUsed')})
                if not old_part.get('stepFlow') and part.get('stepFlow'):
                    old_part['stepFlow']=copy.deepcopy(part['stepFlow'])
            else:
                parts.append(part);cards.append(card);known[key]=(part,card)
        unit['summary']['parts']=parts;unit['concepts']=cards
    for unit in result.values():
        summary=unit['summary'];ps=summary['parts']
        summary['body']='\n\n'.join(p['body'] for p in ps)
        summary['evidence']=[e for p in ps for e in p['evidence']]
        summary['visualPages']=sorted({page for p in ps for page in p['visualPages']})
        summary['standardKnowledgeUsed']=any(p['standardKnowledgeUsed'] for p in ps)
        summary['studyContentSkipped']=not ps
    return result


def build_teaching_request(folder, job, blocks, document, prepared, *, canonical=False,
                           positions=None, context=None, legacy_coverage=False):
    check_cancel(folder)
    images,crops=prepared
    strategy=STRATEGIES[0]
    if positions is None:positions={b["id"]:n for n,b in enumerate(blocks)}
    if context is None:context=document_context(document)
    pages = {b['page'] for b in job['blocks']}
    neighbors=job_neighbors(blocks,job,positions)
    request_context={'kind':'region_study','strategy':strategy,'unitIds':[job['id']],
                     'pages':sorted(pages),'reasoningEffort':reading_effort(job['blocks'],STUDY_REASONING_EFFORT),
                     'studyTeachingIdentity':teaching_identity(),'studyConnectionRepairAllowed':True}
    if DURABLE_STUDY_BODY:request_context['studyDurable']=True
    if FOREGROUND_STUDY_BODY:request_context['studyForegroundResponses']=True
    if STUDY_TEMPERATURE is not None:request_context['temperature']=STUDY_TEMPERATURE
    payload=teaching_payload(job,crops,context,neighbors)
    if job.get('_reviewFeedback'):
        payload['reviewFocus']=job['_reviewFeedback']
        payload['revisionOf']=job.get('_reviewRevision','')
    wire_format=constrained_format(STUDY_FORMAT,job)
    wire_format['json_schema']['schema']['properties']['sourceCoverage'].update(
        minItems=len(job['blocks']),maxItems=len(job['blocks']))
    from pdf_study_review import numerical_guards, require_semantic_checks
    guards=numerical_guards(job['blocks'])
    from pdf_study_geometry import connection_hints
    connections=connection_hints(folder,job['blocks'])
    if connections:payload['sourceConnectionChecks']=connections
    if guards:payload['sourceConditionChecks']=guards
    require_semantic_checks(wire_format,job['blocks'],guards)
    from pdf_newest_k1_2_0_guard import RULES
    compact_coverage=not canonical and not legacy_coverage
    instructions=(STUDY_PROMPT if compact_coverage else CANONICAL_STUDY_PROMPT)+RULES
    if job.get('_reviewFeedback'):
        instructions+='''\nREPAIR THE SPECIFIED SOURCE COVERAGE IN THIS RESPONSE.
reviewFocus identifies original source regions the previous response did not handle.
Read those regions again. A different topic than the title is still owned teaching.
Do not omit it as outside the current unit. Retain the rest of the supported lesson,
and either teach the contribution or provide an accurate, linked source disposition.
Do not merely quote a generic existing sentence to mark a missing case covered.\n'''
        if compact_coverage:
            instructions=instructions.replace('Do not merely quote a generic existing sentence',
                                                'Do not merely reference a generic existing main segment')
    if SOURCE_COVERAGE_HINT:
        instructions+=SOURCE_COVERAGE_RULES
    if COMPACT_TABLE_SETUP:
        instructions+='''\nFor a source table, sourceSetup records column meanings, actors, units and any
essential interpretation constraint; do not transcribe its cells there a second
time. Preserve every readable row/value once in the learner table. Keep the normal
sourceSetup observations/checks for equations, code declarations, reported claims
and diagram relations. This compresses internal duplication, not source teaching.\n'''
    if STATEMENT_UNCERTAINTY:
        # Unsupported statements have their own segment, so one unreadable
        # row cannot silently erase an otherwise readable image/table.
        wire_format['json_schema']['schema']['properties']['uncertainBlocks']['maxItems']=0
    aliases=None
    if SOURCE_ID_ALIASES and not canonical:
        from pdf_source_aliases import encode, bucket_pool_size
        alias_pool=(bucket_pool_size(len(job['blocks']),SOURCE_ALIAS_POOL_SIZE)
                    if SOURCE_ALIAS_POOL_SIZE is not None else None)
        payload,wire_format,aliases=encode(payload,wire_format,job,
                                         stable_pool_size=alias_pool)
    if OWNED_TEACHING:
        from pdf_owned_teaching import encode_format, OWNED_OUTPUT
        wire_format=encode_format(wire_format)
        instructions+=OWNED_OUTPUT
    if SOURCE_FACTS:
        from pdf_source_facts import encode_format as facts_format, SOURCE_FACTS_OUTPUT
        wire_format=facts_format(wire_format)
        instructions+=SOURCE_FACTS_OUTPUT
    visual_ownership=None
    if VISUAL_TEACHING:
        if SOURCE_ID_ALIASES or OWNED_TEACHING:
            raise ValueError('Visual ownership experiment requires canonical source IDs and teaching format.')
        from pdf_visual_teaching import encode_format as visual_format, RULES as VISUAL_OUTPUT
        wire_format,visual_ownership=visual_format(wire_format,job)
        if visual_ownership is not None:instructions+=VISUAL_OUTPUT
    if IMAGE_SOURCE_LABELS:
        image_labels=image_source_label_metadata(job,payload,crops)
        request_images=[{**img,'sourceLabel':'Target image '+str(n+1)+' · '+json.dumps(
            image_labels[n],ensure_ascii=False)} for n,img in enumerate(images)]
        instructions+='\nEach image is immediately preceded by its own page and source-ID label. Ground each visual paragraph, table and flow step in that image\'s IDs, never a neighboring image\'s IDs.\n'
        if IMAGE_REGION_LABELS:
            instructions+='visualRegions boxes are normalized [left, top, right, bottom] coordinates inside that image; each blockId owns that visual even when nearby body text shares the crop.\n'
    else:request_images=images
    from pdf_study_review import continuation_context_images
    background_images=continuation_context_images(folder,blocks,job,
        available_images=max(0,4-len(request_images)))
    if background_images:
        request_images=request_images+background_images
        instructions+="\nAn explicitly labelled BACKGROUND SOURCE CONTEXT image supplies premises for an owned continuation. It is not an additional target. Preserve the diagram's actual initial conditions instead of inferring them from a trailing equation or title.\n"
    exact_format=None
    if compact_coverage:
        from pdf_k120_compact_coverage import encode_format
        wire_format,exact_format=encode_format(wire_format)
        request_context['studySourceCoverageContract']=COMPACT_COVERAGE_VERSION
    return {'job':job,'payload':payload,'images':request_images,
            'response_format':wire_format,'instructions':instructions,
            'aliases':aliases,'visualOwnership':visual_ownership,'context':request_context,
            '_sourceCoverageExactFormat':exact_format}

def accept_teaching_reply(cache, document, jobs, job, raw, request):
    from pdf_k120_compact_coverage import restore
    exact=request.get('_sourceCoverageExactFormat')
    raw=restore(raw,exact)
    aliases=request['aliases'];visual_ownership=request['visualOwnership']
    if SOURCE_FACTS or visual_ownership is not None:
        write_json(cache/f'wire-response-{job["id"]}.json',raw)
    if visual_ownership is not None:
        from pdf_visual_teaching import decode as decode_visual
        raw=decode_visual(raw,visual_ownership)
    if SOURCE_FACTS:
        from pdf_source_facts import decode as decode_facts
        raw=decode_facts(raw)
    if OWNED_TEACHING:
        from pdf_owned_teaching import decode as decode_owned
        raw=decode_owned(raw)
    if aliases is not None:
        from pdf_source_aliases import decode
        raw=decode(raw,aliases)
    from pdf_newest_k1_2_0_guard import ensure_owned
    ensure_owned(raw,request,[{'job':other} for other in jobs if other['id']!=job['id']])
    if exact is not None:
        # Local metadata, added only after exact wire/schema/ownership checks.
        # It survives saved-response reuse without changing the model schema.
        raw[CANONICAL_MARKER]=COMPACT_COVERAGE_VERSION
    write_json(cache/f'response-{job["id"]}.json',raw)
    return validate(raw,job,document)


def cached_teaching_reply(provider, request_builder):
    """Recover either exact singleton wire format without any new API request."""
    from pdf_ai import AiResponseError
    for legacy in (False,True):
        request=request_builder(legacy_coverage=legacy)
        provider.context=request['context']
        try:
            raw=provider.complete(request['payload'],image=request['images'],
                max_output=18000,system_prompt=request['instructions'],
                response_format=request['response_format'],cache_stable_prefix=True,cache_only=True,
                image_limit=SINGLE_REQUEST_IMAGES)
            return raw,request
        except AiResponseError:
            if legacy:raise


def generate(folder, document, provider, scope='document', page=None, *, strategy='newest-k1-2-6'):
    if strategy not in STRATEGIES:
        raise ValueError('지원하지 않는 영역 처리 방식이에요.')
    with generation_lock(folder):
        try:
            from pdf_newest_k1_2_0_early import EarlyUnits
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='study-overview') as overview_pool, EarlyUnits(
                    Path(folder),document,provider,scope,page) as early:
                return _generate(Path(folder),document,provider,scope,page,strategy,overview_pool,early)
        finally:
            transport=getattr(provider,'study_http_transport',None)
            if transport is not None:transport.close()


def _generate(folder, document, provider, scope, page, strategy, overview_pool, early):
    started = time.monotonic()
    provider.study_input_api=STUDY_INPUT_API
    if getattr(provider,'transport',None)is None:
        from pdf_study_http import StudyHttpTransport
        if getattr(provider,'study_http_transport',None)is None:
            provider.study_http_transport=StudyHttpTransport(max_unsent_attempts=4,
                max_connections=MAX_STARTUP_WORKERS,allow_overflow=True)
    page, targets, _ = selection(document,scope,page)
    cache = root_path(folder,document,strategy,provider.model,scope,page)
    cache.mkdir(parents=True,exist_ok=True)
    saved = saved_complete(folder,document,strategy,provider.model,scope,page)
    from pdf_k113_coverage import complete as review_complete, feedback as review_feedback
    if review_complete(saved) and saved.get('localOutputVersion')==CHECKS_VERSION:
        from pdf_ai import run_usage
        saved = {**display_saved(folder,document,saved,cache), 'runUsage':run_usage(provider), 'cacheHit':True}
        emit('study_timeline',stage='saved',percent=100)
        return saved
    # Reopening an incomplete document retrieves original paid answers before
    # the missing-response guard or changed batch packing can block a unit.
    # A complete local result above remains instant and performs no GET.
    if callable(getattr(provider,'recover_pending_study',None)):
        provider.recover_pending_study()
    emit('study_timeline',stage='split_start',percent=3)
    blocks = extract_layout(folder,document,targets,cache,extractor=extract,layout_version=LAYOUT_VERSION)
    write_json(cache/'blocks.json',blocks)
    early.start(cache,blocks,started)
    emit('study_timeline',stage='split_done',percent=10)
    local_seconds = time.monotonic()-started
    emit('study_timeline',stage='group_start',percent=11)
    plan = read_json(cache/'plan.json')
    if not usable_plan(plan,provider.model,blocks):plan=None
    reused_manifest=None
    if plan is None:
        for planner_key in compatible_planner_identities(provider.model):
            plan,reused_manifest=reuse_plan(folder,cache,document,strategy,scope,page,blocks,
                                           planner_identity=planner_key)
            if plan is not None:break
        if plan is not None:write_json(cache/'plan.json',plan)
    elif plan.get('reusedFrom'):
        reused_manifest=read_json(Path(plan['reusedFrom'])/'manifest.json')
    if plan is not None:
        groups, warnings = plan['groups'],plan['warnings']
    elif strategy == 'newest-k1-2-6':
        emit('progress',page=0,total=1,stage='Newest_K1.2.6 · 조각 묶음 판단')
        from pdf_tiled_margins import mark_tiled_margins
        tiled_ids=set(mark_tiled_margins(folder,blocks))
        write_json(cache/'blocks.json',blocks)
        eligible=[b for b in blocks if not locally_skipped(b) and b['id'] not in tiled_ids]
        groups,warnings = plan_groups(folder,provider,eligible,cache,on_prefix=early.offer) if eligible else ([],[])
        for b in blocks:
            if b not in eligible:
                b['planRole']='decoration' if b['id'] in tiled_ids else b['localRole']
        skipped=[b for b in blocks if b not in eligible]
        groups += [{'title':'구조 정보','blocks':skipped}] if skipped else []
        written=read_json(cache/'plan.json') or {}
        write_json(cache/'plan.json',plan_record(groups,warnings,provider.model,
            written.get('headings') or hierarchy.source_headings(blocks),blocks=blocks,
            recovery=written.get('assignmentRecovery')))
    else:
        groups,warnings = local_groups(blocks,strategy),[]
        write_json(cache/'plan.json',{'groups':groups,'warnings':warnings})
    plan=read_json(cache/'plan.json') or {'groups':groups,'warnings':warnings}
    groups=protect_visual_groups(groups)
    validate_partition(blocks,groups,require_global_order=False)
    emit('study_timeline',stage='group_done',percent=20)
    planning_seconds = time.monotonic()-started-local_seconds
    skipped=[b for g in groups for b in g['blocks'] if b.get('planRole') in ('decoration','navigation','exercise')]
    teaching=[{**g,'blocks':[b for b in g['blocks'] if b.get('planRole') not in ('decoration','navigation','exercise')]} for g in groups]
    teaching=[g for g in teaching if g['blocks']]
    shifted,visual_rebalances=lead_with_visual_page(teaching)
    base_jobs=jobs_for(teaching)
    jobs=jobs_for(shifted) if visual_rebalances else base_jobs
    if len(jobs)>len(base_jobs):
        jobs=base_jobs;visual_rebalances=[]
    early.bind_final(jobs)
    if skipped:jobs.append({'id':digest(skipped)[:24],'title':'구조 정보','topicIndex':-1,'blocks':skipped,'skip':True})
    # Display metadata is rebuilt locally after display-rule upgrades. The
    # paid semantic plan, response caches and parallel jobs stay unchanged.
    headings=display_source_headings(folder,blocks,groups=groups)
    for job in jobs:job['headingOptions']=hierarchy.options_for(job,headings,blocks)
    write_json(cache/'manifest.json',{'jobs':jobs,'targets':targets,'strategy':strategy,
                                    'teachingIdentity':teaching_identity()})
    context = document_context(document)
    early_path=cache/'partial.json'
    initial=assemble(document,strategy,scope,page,targets,jobs,{},[],warnings,headings=headings,all_blocks=blocks)
    write_json(early_path,initial)
    from pdf_parallel_overview import ParallelOverview
    overview=ParallelOverview(initial['overview'],early_path,emit=emit,
        metadata=dict(strategy=strategy,scope=scope,selectionPage=page))
    overview.start(overview_pool,lambda:planned_overview(provider,cache,
        shifted if visual_rebalances else teaching,document,on_preview=overview.preview))
    ready, done, failures = {}, {}, []
    cover_ids=plain_cover_ids(blocks)
    teaching_indices={i for i,job in enumerate(jobs)
                      if not job.get('skip') and not all(b['id'] in cover_ids for b in job['blocks'])}
    positions = {b['id']:n for n,b in enumerate(blocks)}
    source_order=lambda i:min(positions[b['id']] for b in jobs[i]['blocks'])
    front_indices=sorted(teaching_indices,key=source_order)[:2]
    frozen_batches=transport_batches(generation_schedule(teaching_indices,jobs,front=front_indices),
        jobs,preview=False,preview_indices=front_indices)
    write_json(cache/'transport-plan.json',{'version':'worker-independent-long-short-v2',
        'batches':[[jobs[i]['id'] for i in batch] for batch in frozen_batches]})
    emit('study_timeline',stage='units_ready',percent=20,totalUnits=len(teaching_indices))
    crop_started = time.monotonic()
    crop_gate=early.render_lock
    crop_elapsed=0.0
    reused_replies=[]
    from pdf_k113_saved import index as saved_index, reply as saved_reply
    previous_replies=saved_index(folder,document,strategy,provider.model,scope,page,cache,prompt_version=VERSION)
    review_retry_indices=set()
    for i, job in enumerate(jobs):
        check_cancel(folder)
        if job.get('skip') or all(b['id'] in cover_ids for b in job['blocks']):
            done[i]=validate({'concepts':[],'uncertainBlocks':[],
                'excludedBlocks':[{'blockId':b['id'],'reason':b.get('planRole','navigation')}
                                  for b in job['blocks']]},job,document)
            continue
        raw = read_json(cache/f'response-{job["id"]}.json')
        reused=None
        if raw is None:
            raw,reused=saved_reply(previous_replies,job)
            if raw is not None:write_json(cache/f'response-{job["id"]}.json',raw)
        if raw is not None:
            try:
                from pdf_newest_k1_2_0_guard import ensure_owned
                ensure_owned(raw,{'job':job},[{'job':other} for other in jobs if other['id']!=job['id']])
                done[i]=validate(raw,job,document)
                if reused:
                    reused_replies.append({'unitId':job['id'],'source':reused,
                                           'additionalApiRequests':0,'revalidated':True})
                if any(c['state']=='needs_review' for c in done[i]['coverage']):
                    review_retry_indices.add(i)
                    review_feedback(job,raw,done[i]['coverage'])
                    ready[i]=None
                continue
            except ValueError as error:
                warnings.append({'stage':'cached_response_validation','unitId':job['id'],
                                 'error':type(error).__name__,'detail':str(error)})
        if PIPELINE_CROPS:
            ready[i]=None
            continue
        try:
            images, crops = render_crops(folder,job['blocks'],cache)
            write_json(cache/f'crops-{job["id"]}.json',crops)
            ready[i]=(images,crops)
        except InterruptedError:
            raise
        except Exception as error:
            failures.append({'unitId':job['id'],'stage':'render','error':type(error).__name__})
    crop_seconds = time.monotonic()-crop_started
    first_result = None
    # Paid replies and validated units are durable immediately. Publication is
    # separate: until the opening units settle, no tail-only partial/export or
    # event may reach either the summary or concept view.
    published={};pending_publications=set();terminal=set(done)
    terminal.update(i for i,job in enumerate(jobs)
                    if any(f.get('unitId')==job['id'] for f in failures))
    from pdf_study_stream import StudyPreview, PreviewPublication
    stream_previews=early.previews
    with stream_previews.lock:
        stream_previews.jobs=jobs
        stream_previews.front=front_indices
        stream_previews.terminal.update(terminal)
    def write_published():
        partial=assemble(document,strategy,scope,page,targets,jobs,published,failures,warnings,
                         headings=headings,all_blocks=blocks)
        overview.publish(partial,lambda value:hierarchy.export(cache,value))
    def flush_publications():
        nonlocal first_result
        check_cancel(folder)
        allowed=[]
        for i in front_indices:
            if i not in terminal:break
            if i in pending_publications:allowed.append(i)
        if all(i in terminal for i in front_indices):
            allowed.extend(sorted(pending_publications.difference(front_indices),key=source_order))
        for index in allowed:
            check_cancel(folder)
            pending_publications.remove(index);published[index]=done[index]
            if first_result is None and done[index]['summary']['parts']:
                first_result = time.monotonic()-started
            write_published()
            emit('summary_unit_ready',unit=index+1,total=len(jobs),scope=scope,
                 selectionPage=page,strategy=strategy,path=str(cache/f'unit-{index:05d}.json'))
            completed=len(teaching_indices.intersection(done))
            emit('study_timeline',stage='unit_done',percent=min(99,20+80*completed//max(1,len(teaching_indices))),
                 completedUnits=completed,totalUnits=len(teaching_indices))
            emit('progress',page=len(done),total=len(jobs),stage='Newest_K1.2.6 · 요약과 개념 생성')

    def finish_without_reply(indices):
        for index in indices:stream_previews.settle(index,False)
        terminal.update(indices)
        flush_publications()

    def persist(index, *, flush=True):
        unit=copy.deepcopy(done[index])
        view=hierarchy.decorate({'sections':[unit['summary']],'documentId':document['documentId'],
            'sourceFingerprint':document['fingerprint'],'scope':scope,'page':page},blocks,headings)
        unit['summary']=view['sections'][0];unit['summary']['hierarchy']=view['hierarchy']
        write_json(cache/f'unit-{index:05d}.json',unit)
        stream_previews.settle(index,True)
        terminal.add(index);pending_publications.add(index)
        if flush:flush_publications()
    for i in sorted(done):
        persist(i,flush=False)
    # Replace a previous scheduler's tail-only partial before cancellation or
    # an error can make the app recover that stale presentation. Raw paid
    # responses and per-unit files remain available for free resume.
    write_published()
    flush_publications()
    def prepare(i):
        nonlocal crop_elapsed
        if jobs[i]['id'] in early.futures:return ([],[])
        check_cancel(folder)
        job=jobs[i]
        if ready[i] is None:
            # Serialize local decoding to bound CPU/RAM, while earlier API calls
            # already run. Never keep all encoded crop images alive together.
            with crop_gate:
                check_cancel(folder)
                crop_start=time.monotonic()
                images,crops=render_crops(folder,render_blocks(job['blocks']),cache)
                images,crops,text_only=select_images(job['blocks'],images,crops)
                write_json(cache/f'crops-{job["id"]}.json',crops)
                crop_elapsed+=time.monotonic()-crop_start
        else:
            images,crops=ready[i]
            images,crops,text_only=select_images(job['blocks'],images,crops)
        write_json(cache/f'input-{job["id"]}.json',{'policy':TEXT_INPUT_VERSION,
            'textOnlyBlockIds':sorted(text_only),
            'imageBlockIds':[b for crop in crops for b in crop.get('blockIds',[])]})
        return images,crops
    def build_request(i, prepared=None, *, canonical=False, legacy_coverage=False):
        return build_teaching_request(folder,jobs[i],blocks,document,
            prepare(i) if prepared is None else prepared,canonical=canonical,positions=positions,context=context,
            legacy_coverage=legacy_coverage)

    def accept_reply(i, raw, request):
        return accept_teaching_reply(cache,document,jobs,jobs[i],raw,request)

    def work(i, prepared=None, *, priority=None, checked_preview=False):
        if jobs[i]['id'] in early.futures:
            return early.futures[jobs[i]['id']].result()
        request=build_request(i,prepared)
        if priority is not None:request['context']['_startup_priority']=priority
        provider.context=request['context']
        preview=StudyPreview([((),i)],stream_previews.update)
        raw=complete_study(request['payload'],image=request['images'],
            max_output=18000,system_prompt=request['instructions'],
            response_format=request['response_format'],cache_stable_prefix=True,
            image_limit=SINGLE_REQUEST_IMAGES,
            on_study_delta=None if checked_preview else preview.feed,
            on_delivery_reset=None if checked_preview else preview.reset)
        value=accept_reply(i,raw,request)
        if checked_preview:preview.feed(json.dumps(raw,ensure_ascii=False))
        preview.flush()
        return value

    def complete_study(payload,**options):
        from pdf_ai import complete_study_delivery
        return complete_study_delivery(provider,payload,**options)

    if ready:
        from pdf_study_batch_recovery import BatchRecoveryIndex, BatchRecoveryError
        from pdf_ai import MissingPaidResponseError
        # Index once before repacking unfinished work. Otherwise a paid pair
        # could silently become a new singleton with a different payload hash.
        sample=next(iter(ready))
        recovery_format=build_request(sample,([],[]),canonical=True)['response_format']
        try:
            paid_batches=BatchRecoveryIndex(folder,jobs,provider.model,strategy,teaching_identity(),
                                            response_format=recovery_format)
        except BatchRecoveryError:
            # Keep already saved units visible even if a damaged ledger cannot
            # establish whether the remaining units have previously been paid.
            failures.extend({'unitId':jobs[i]['id'],'stage':'paid_batch_recovery',
                'error':'MissingPaidResponseError',
                'detail':'이전 유료 사용 기록을 확인하지 못해 중복 전송을 막았어요.'}
                for i in ready)
            blocked=list(ready);ready.clear();paid_batches=None
            finish_without_reply(blocked)
        for i in list(ready):
            if i in review_retry_indices:continue  # This paid answer exists; its content needs a revision.
            if jobs[i]['id'] in early.futures:continue
            try:
                recovered=paid_batches.recover(jobs[i],
                    retry_missing_responses=getattr(provider,'retry_missing_responses',False),
                    retry_unresolved_request_ids=(getattr(provider,'unavailable_study_request_ids',())
                        if getattr(provider,'retry_unresolved_responses',False) is True else ()))
                if recovered is None:
                    if not paid_batches.single_history(jobs[i]):continue
                    # A legacy single paid attempt must not become a different
                    # paid pair just because the new scheduler packs work. Try
                    # its exact current single-request cache without networking.
                    from pdf_ai import AiResponseError
                    try:
                        prepared=prepare(i)
                        raw,request=cached_teaching_reply(provider,
                            lambda **kw:build_request(i,prepared,**kw))
                        value=accept_reply(i,raw,request)
                    except InterruptedError:raise
                    except (AiResponseError,ValueError,TypeError,KeyError,OSError) as error:
                        if (getattr(provider,'retry_missing_responses',False) is True
                                and not paid_batches.single_unresolved(jobs[i],retry_unresolved_request_ids=(
                                    getattr(provider,'unavailable_study_request_ids',())
                                    if getattr(provider,'retry_unresolved_responses',False) is True else ()))):continue
                        raise MissingPaidResponseError('이전 단독 유료 요청의 응답을 복구하지 못했어요. 새 묶음으로 중복 전송하는 것을 막았어요.') from error
                    diagnostic={'kind':'paid_single_local_recovery','additionalApiRequests':0}
                else:
                    raw,diagnostic=recovered
                    request=build_request(i,([],[]),canonical=True)
                    try:value=accept_reply(i,raw,request)
                    except (ValueError,TypeError,KeyError) as error:
                        raise MissingPaidResponseError('이전 유료 묶음의 응답을 정상 학습 결과로 복구하지 못했어요. 중복 전송을 막았어요.') from error
                done[i]=value;ready.pop(i);persist(i)
                reused_replies.append({'unitId':jobs[i]['id'],'paidBatchRecovery':diagnostic})
            except MissingPaidResponseError as error:
                ready.pop(i)
                failures.append({'unitId':jobs[i]['id'],'stage':'paid_batch_recovery',
                                 'error':type(error).__name__,'detail':str(error)})
                finish_without_reply([i])

    transport_calls=[]
    from pdf_performance import measure, record
    def prepare_batch_raw(indices):
        prepared={};errors=[]
        for i in indices:
            try:prepared[i]=prepare(i)
            except InterruptedError:raise
            except Exception as error:
                errors.append({'unitId':jobs[i]['id'],'stage':'render','error':type(error).__name__})
        return prepared,errors

    def prepare_batch(indices):
        with measure(folder,"batch_image_preparation",unitIds=[jobs[i]["id"] for i in indices]):
            return prepare_batch_raw(indices)

    def work_batch(indices, prepared, *, priority=None):
        if len(indices)==1:
            i=indices[0]
            return {i:work(i,prepared[i],priority=priority)},[]
        from pdf_study_batch_transport import encode, decode_each
        # Canonical references remain exact inside each namespaced unit schema.
        # Job-local aliases would overlap between units, so only this combined
        # envelope bypasses aliasing. Stored replies still use canonical IDs.
        requests=[build_request(i,prepared[i],canonical=True) for i in indices]
        if len({r['instructions'] for r in requests})!=1:
            raise ValueError('서로 다른 학습 지침을 한 요청으로 합칠 수 없어요.')
        alias_options={}
        if TRANSPORT_BATCH_ALIASES:
            from pdf_source_aliases import bucket_pool_size
            alias_options['alias_pool_size']=(TRANSPORT_BATCH_ALIAS_POOL if TRANSPORT_BATCH_ALIAS_POOL in ('exact','namespace') else
                bucket_pool_size(max(len(r['job']['blocks']) for r in requests),TRANSPORT_BATCH_ALIAS_POOL))
        payload,format,images,contract=encode(requests,max_units=TRANSPORT_BATCH_UNITS,
            max_images=TRANSPORT_BATCH_IMAGES,flat_defs=True,
            **alias_options)
        payload['unitEnvelopeVersion']='k1.1.1-v1'
        contract_path=cache/('transport-contract-'+digest(contract)[:24]+'.json')
        write_json(contract_path,contract)
        provider.context={'kind':'region_study','strategy':strategy,
            'unitIds':[jobs[i]['id'] for i in indices],
            'pages':sorted({b['page'] for i in indices for b in jobs[i]['blocks']}),
            'reasoningEffort':STUDY_REASONING_EFFORT,'studyBatchUnits':len(indices),
            'studyBatchContract':str(contract_path),'studyTeachingIdentity':teaching_identity(),
            'studyPackingProfile':'worker-independent-long-short-v2',
            'studyConnectionRepairAllowed':True}
        if DURABLE_STUDY_BODY:provider.context['studyDurable']=True
        if FOREGROUND_STUDY_BODY:provider.context['studyForegroundResponses']=True
        if STUDY_TEMPERATURE is not None:provider.context['temperature']=STUDY_TEMPERATURE
        # Paired partial prose cannot be ownership-checked until its evidence arrives.
        # Publish each accepted unit through the existing preview/commit pipeline.
        raw=complete_study(payload,image=images or None,max_output=18000*len(indices),
            system_prompt=requests[0]['instructions']+BATCH_RULES,response_format=format,
            cache_stable_prefix=True,image_limit=TRANSPORT_BATCH_IMAGES,
            on_study_delta=None,on_delivery_reset=None)
        records,errors=decode_each(raw,contract)
        completed={};failed=[]
        for record in records:
            position=record['index'];i=indices[position]
            try:
                from pdf_newest_k1_2_0_guard import SourceOwnershipError
                try:
                    completed[i]=accept_reply(i,record['raw'],requests[position])
                except SourceOwnershipError as error:
                    write_json(cache/f'ownership-rejected-{jobs[i]["id"]}.json',
                        {'policy':'unit-envelopes-source-quotes-v1','detail':str(error),'raw':record['raw']})
                    # One isolated retry, keeping the accepted partner. All normal
                    # provider budget/rate/cancellation controls still apply.
                    completed[i]=work(i,prepared[i],priority=priority,checked_preview=True)
                    continue
                preview=StudyPreview([((),i)],stream_previews.update)
                preview.feed(json.dumps(record['raw'],ensure_ascii=False));preview.flush()
            except InterruptedError:raise
            except Exception as error:
                failed.append({'unitId':jobs[i]['id'],'stage':'batch_unit_validation',
                               'error':type(error).__name__,'detail':str(error)})
        for error in errors:
            position=error.get('index')
            i=indices[position] if isinstance(position,int) else indices[0]
            failed.append({'unitId':jobs[i]['id'],'stage':'batch_transport',
                           'error':'BatchTransportError','detail':error['error']})
        return completed,failed
    from pdf_ai import BudgetExceeded, CreditExceeded, ContextBudgetExceeded, IncompleteResponseError, Provider
    startup_used=False
    def run_schedule(indices):
        nonlocal startup_used
        deferred=[]
        initial_front=[i for i in front_indices if i in indices] if not startup_used else []
        schedule=deque(request_schedule(transport_subset(frozen_batches,indices),
                       jobs,front=initial_front))
        retry_progress=(len(done),settlements())
        startup_open=threading.Event()
        base_workers=study_workers()
        extra=min(len(initial_front),max(0,MAX_STARTUP_WORKERS-base_workers)) if base_workers==MAX_STUDY_WORKERS and not startup_used else 0
        startup_used=True
        startup_workers=min(MAX_STARTUP_WORKERS,base_workers+extra)
        # The initial work and unfunded recovery use the same one-ahead
        # producer. Only the two original opening units can occupy extra slots.
        # The first completed attempt closes startup; existing 16 naturally
        # drain to 14, without turning later refills into waves or serial work.
        with ExitStack() as stack:
            grant=None
            if extra:
                from pdf_api_slots import startup_priority_slots
                slot_directory=(folder/'.test-api-slots' if getattr(provider,'transport',None)
                    or not isinstance(provider,Provider) else getattr(provider,'rate_directory',None))
                grant=stack.enter_context(startup_priority_slots(directory=slot_directory))
                startup_open.set()
            def close_startup():
                startup_open.clear()
                if grant is not None:grant.close()
            prepared_at={}
            def dispatch(batch,images,priority):
                ready_at=prepared_at.pop(tuple(batch),None)
                if ready_at is not None:
                    record(folder,"prepared_to_worker_wait",ready_at,unitIds=[jobs[i]["id"] for i in batch])
                try:
                    value=work_batch(batch,images,priority=priority)
                except (BudgetExceeded,ContextBudgetExceeded) as error:
                    # A rejected reservation never used network capacity.
                    if isinstance(error,CreditExceeded):close_startup()
                    raise
                except BaseException:
                    close_startup();raise
                close_startup()
                return value
            pool=stack.enter_context(ThreadPoolExecutor(max_workers=startup_workers))
            producer=stack.enter_context(ThreadPoolExecutor(max_workers=1))
            stack.callback(close_startup)
            futures={};preparing=None;prepared=None
            while futures or preparing is not None or prepared is not None or schedule:
                check_cancel(folder)
                ceiling=startup_workers if startup_open.is_set() else base_workers
                if prepared is not None and len(futures)<ceiling:
                    batch,images=prepared
                    priority=grant if len(batch)==1 and batch[0] in initial_front else None
                    futures[pool.submit(dispatch,batch,images,priority)]=batch;prepared=None
                    transport_calls.append([jobs[i]['id'] for i in batch])
                if preparing is None and prepared is None and schedule:
                    batch=schedule.popleft()
                    preparing=(producer.submit(prepare_batch,batch),batch)
                watched=list(futures)+([preparing[0]] if preparing else [])
                if not watched:break
                completed,_=wait(watched,timeout=.1,return_when=FIRST_COMPLETED)
                for future in completed:
                    if preparing is not None and future is preparing[0]:
                        _,batch=preparing;preparing=None
                        try:
                            images,errors=future.result();failures.extend(errors)
                            valid=[i for i in batch if i in images]
                            finish_without_reply([i for i in batch if i not in images])
                            if valid:
                                prepared_at[tuple(valid)]=time.perf_counter()
                                prepared=(valid,images)
                        except InterruptedError:
                            for f in futures:f.cancel()
                            raise
                        except Exception as error:
                            failures.extend({'unitId':jobs[i]['id'],'stage':'render','error':type(error).__name__}
                                            for i in batch)
                            finish_without_reply(batch)
                        continue
                    batch=futures.pop(future)
                    try:
                        completed,errors=future.result();failures.extend(errors)
                        for i,value in completed.items():done[i]=value;persist(i)
                        finish_without_reply([i for i in batch if i not in completed])
                    except InterruptedError:
                        for f in futures:f.cancel()
                        raise
                    except CreditExceeded as error:
                        failures.extend({'unitId':jobs[i]['id'],'error':'CreditExceeded','detail':str(error)} for i in batch)
                        finish_without_reply(batch)
                    except BudgetExceeded as error:
                        # Keep the exact original envelope when money is not
                        # available. Admission timing must not change content.
                        if getattr(error,'study_hedge_exhausted',False):
                            failures.extend({'unitId':jobs[i]['id'],'error':type(error).__name__,
                                             'detail':str(error)} for i in batch)
                            finish_without_reply(batch)
                        else:deferred.extend(batch)
                    except Exception as error:
                        if isinstance(error,(ContextBudgetExceeded,IncompleteResponseError)) and len(batch)>1:
                            # A confirmed terminal/truncated batch can be split
                            # once down to singles. Unknown transport failures,
                            # refusals and cancellation never enter this branch.
                            middle=(len(batch)+1)//2
                            schedule.extendleft(reversed([batch[:middle],batch[middle:]]))
                            continue
                        if type(error).__name__ in ('BudgetExceeded','CreditExceeded'):
                            raise
                        failures.extend({'unitId':jobs[i]['id'],'error':type(error).__name__,'detail':str(error)}
                                        for i in batch)
                        finish_without_reply(batch)
                if not schedule and preparing is None and prepared is None and deferred:
                    progress=(len(done),settlements())
                    if progress!=retry_progress:
                        # A completed/settled request can free money while a
                        # slow paid sibling is still active. Refill this same
                        # pool now; never wait for the whole initial batch.
                        # Without new progress, leave unfunded work deferred
                        # rather than repeatedly rendering/rejecting it.
                        schedule.extend(request_schedule(transport_subset(frozen_batches,deferred),jobs))
                        deferred=[];retry_progress=progress
        return deferred

    def settlements():
        # Copy the append-only ledger list while workers may still be active.
        # A billed reply that later fails validation can release its unused
        # reservation even though it does not publish a completed unit.
        ledger=getattr(provider,'ledger',{}) or {}
        return sum(entry.get('state') in ('settled','not_sent')
                   for entry in list(ledger.get('requests',[])) if isinstance(entry,dict))

    deferred=run_schedule(generation_schedule(ready,jobs,front=front_indices))
    while deferred:
        progress=(len(done),settlements())
        deferred=run_schedule(deferred)
        if deferred and progress==(len(done),settlements()):
            # No money was freed and no unit completed: further admission
            # attempts would only spin on the same unfunded reservations.
            failures.extend({'unitId':jobs[i]['id'],'error':'BudgetExceeded',
                             'detail':'회복 라운드에서 추가 정산이나 완료가 없어 중단했어요.'}
                            for i in deferred)
            finish_without_reply(deferred)
            break
    if failures and callable(getattr(provider,'recover_pending_study',None)):
        # A lost stream can finish storing while healthy siblings are still
        # generating. Check the originals once more before publishing a final
        # partial. This path never creates a new model request.
        restored=provider.recover_pending_study()
        restored_ids={key for record in restored for key in record.get('unitIds',[])}
        pending=[i for i,job in enumerate(jobs)if i not in done and job['id']in restored_ids]
        if pending:
            from pdf_study_batch_recovery import BatchRecoveryIndex
            from pdf_ai import AiResponseError
            fmt=build_request(pending[0],([],[]),canonical=True)['response_format']
            try:index=BatchRecoveryIndex(folder,jobs,provider.model,strategy,teaching_identity(),response_format=fmt)
            except ValueError:
                pending=[]
            for i in pending:
                check_cancel(folder)
                try:
                    recovered=index.recover(jobs[i])
                    if recovered is not None:
                        raw,diagnostic=recovered
                        request=build_request(i,([],[]),canonical=True)
                    else:
                        prepared=prepare(i)
                        raw,request=cached_teaching_reply(provider,
                            lambda **kw:build_request(i,prepared,**kw))
                        diagnostic={'kind':'late_paid_single_receipt','additionalApiRequests':0}
                    done[i]=accept_reply(i,raw,request);persist(i)
                    failures[:]=[f for f in failures if f.get('unitId')!=jobs[i]['id']]
                    reused_replies.append({'unitId':jobs[i]['id'],'paidBatchRecovery':diagnostic})
                except InterruptedError:raise
                except (AiResponseError,ValueError,KeyError,TypeError,OSError)as error:
                    warnings.append({'stage':'late_receipt_validation','unitId':jobs[i]['id'],
                                     'error':type(error).__name__})
    early_overview=overview.result()
    result=assemble(document,strategy,scope,page,targets,jobs,done,failures,warnings,
                    headings=headings,all_blocks=blocks)
    result['overview']=copy.deepcopy(early_overview)
    credit_stopped=bool(getattr(provider,'billing',None) and provider.billing.exhausted)
    if credit_stopped:
        result['creditStopped']=True;result['kind']='partial';result['processingComplete']=False
    overview_fallback=early_overview.get('overviewMethod')=='planned_local_fallback'
    result['earlyStart']=early.metrics()
    result['metrics']={'elapsedSeconds':round(time.monotonic()-started,3),
        'firstResultSeconds':round(first_result,3) if first_result is not None else None,
        'firstPreviewSeconds':stream_previews.first_visible_seconds,
        'localSeconds':round(local_seconds,3),'planningSeconds':round(planning_seconds,3),
        'cropSeconds':round(crop_elapsed if PIPELINE_CROPS else crop_seconds,3),'sourceBlocks':len(blocks),'semanticUnits':len(groups),
        'studyJobs':len(jobs),'newStudyJobs':len(ready),'workers':study_workers(),
        'startupWorkers':min(MAX_STARTUP_WORKERS,study_workers()+sum(i in ready for i in front_indices))
            if study_workers()==MAX_STUDY_WORKERS else study_workers(),
        'openingUnitIds':[jobs[i]['id'] for i in front_indices],
        'schedulingProfile':SCHEDULING_PROFILE,
        'transportBatchUnits':TRANSPORT_BATCH_UNITS,'transportBatchImages':TRANSPORT_BATCH_IMAGES,
        'transportBalanced':TRANSPORT_BALANCED,
        'transportPackingProfile':'worker-independent-long-short-v2',
        'transportBatchAliases':TRANSPORT_BATCH_ALIASES,
        'transportBatchAliasPool':TRANSPORT_BATCH_ALIAS_POOL,
        'sourceCoverageHint':SOURCE_COVERAGE_HINT,
        'nativeTextInputPolicy':TEXT_INPUT_VERSION,
        'statementUncertainty':STATEMENT_UNCERTAINTY,
        'studyInputApi':'responses'if DURABLE_STUDY_BODY else STUDY_INPUT_API,
        'studyCacheNamespace':STUDY_INPUT_API,
        'studyDeliveryProfile':'standard-receipt-aware-20noid-stall60-idle30-v1',
        'processingTierProfile':'standard-v1',
        'transportSubmissions':len(transport_calls),
        'locallyExcludedBlocks':len(skipped),'visualRebalancedPages':visual_rebalances,
        'extraReviewCalls':0,'overviewLocalFallback':overview_fallback}
    result['cacheReuse']={'planningReusedFrom':plan.get('reusedFrom'),
        'addedEdgeBlockIds':plan.get('addedEdgeBlockIds',[]),'replies':reused_replies,
        'sourceIdRepairs':[r for unit in done.values() for r in unit.get('sourceIdRepairs',[])],
        'processingDiagnostics':[r for unit in done.values() for r in unit.get('processingDiagnostics',[])]}
    from pdf_ai import run_usage
    if getattr(provider,'billing',None) and provider.billing.exhausted:
        result['creditStopped']=True;result['kind']='partial';result['processingComplete']=False
    result['runUsage']=run_usage(provider)
    from pdf_k120_timings import unit_timings
    result['metrics']['unitTimings']=unit_timings(jobs,done,failures,getattr(provider,'ledger',{}),
        local_units=set(range(len(jobs)))-teaching_indices,
        admission_timings=getattr(provider,'_admission_timings',{}))
    from pdf_study_pending import pending_originals
    result['pendingOriginalUsage']=pending_originals(folder,provider.model,
        [job['id'] for job in jobs])
    result['visualSelectionVersion']=VISUAL_SELECTION_VERSION
    result['localOutputVersion']=CHECKS_VERSION
    from pdf_symbol_bullets import clean_titles
    result=clean_titles(folder,result)
    save_hierarchy(cache,result)
    write_json(cache/'partial.json',result)
    if result['processingComplete']:
        write_json(cache/'result.json',result)
    write_json(latest_path(folder,strategy,scope,page),result)
    if result['processingComplete']:
        emit('study_timeline',stage='saved',percent=100)
    return result


def recover(folder,document,scope='document',page=None,model='gpt-6-luna',strategy='newest-k1-2-6'):
    page,_,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,model,scope,page)
    saved=saved_complete(folder,document,strategy,model,scope,page) or read_json(root/'partial.json')
    if hierarchy.VERSION=='study-hierarchy-7' and not saved:
        saved,historical_root=historical_saved(folder,document,strategy,model,scope,page)
        if historical_root is not None:root=historical_root
    return display_saved(folder,document,saved,root) if saved else None


def historical_saved(folder,document,strategy,model,scope,page):
    """Reuse exact local teaching after its generation identity has evolved.

    This display-only fallback never starts generation or rewrites a paid
    result. Old workers retain their previous current-identity lookup policy.
    """
    expected={'documentId':document['documentId'],'sourceFingerprint':document['fingerprint'],
              'strategy':strategy,'model':model,'scope':scope,'page':page,'promptVersion':VERSION}
    def eligible(value):
        return (isinstance(value,dict) and type(value.get('page')) is int
            and all(value.get(key)==item for key,item in expected.items())
            and any(isinstance(value.get(key),list) and any(isinstance(item,dict) and item for item in value[key])
                    for key in ('sections','concepts')))
    latest=read_json(latest_path(folder,strategy,scope,page))
    if eligible(latest):return latest,root_path(folder,document,strategy,model,scope,page)
    candidates=[]
    base=Path(folder)/'generated'/strategy
    for name in ('result.json','partial.json'):
        for path in base.glob('*/'+name):
            try:candidates.append((path.stat().st_mtime_ns,path.as_posix(),path))
            except OSError:continue
    for _,_,path in sorted(candidates,reverse=True):
        value=read_json(path)
        if eligible(value):return value,path.parent
    return None,None


def prepare_local_sources(folder,document,model='gpt-6-luna',scope='document',page=None,strategy='newest-k1-2-6'):
    """Warm only the immutable source-layout cache; no provider, grouping or API calls."""
    folder=Path(folder)
    page,targets,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,model,scope,page)
    with generation_lock(folder):
        blocks=extract_layout(folder,document,targets,root,extractor=extract,layout_version=LAYOUT_VERSION)
    return {'kind':'local_prepared','documentId':document['documentId'],
            'pages':len(targets),'sourceBlocks':len(blocks)}


def prepare_group_plan(folder, document, provider, scope='document', page=None, strategy='newest-k1-2-6'):
    """Estimate locally; paid grouping and teaching share the generate run."""
    folder=Path(folder)
    page,targets,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,provider.model,scope,page)
    with generation_lock(folder):
        blocks=extract_layout(folder,document,targets,root,extractor=extract,layout_version=LAYOUT_VERSION)
        write_json(root/'blocks.json',blocks)
        result=reading_plan(folder,document,None,provider.model,scope,page,strategy)
        result['groupingConfirmed']=False
        result['groupingDeferredToGeneration']=True
        result['pendingOriginalUsage']=pending_originals_for_plan(folder,provider.model,root,document)
        return result


def pending_originals_for_plan(folder,model,root,document):
    from pdf_study_pending import pending_originals
    pending=[]
    for job in (read_json(root/'manifest.json') or {}).get('jobs',[]):
        if job.get('skip'):continue
        raw=read_json(root/f'response-{job["id"]}.json')
        if raw is not None:
            try:
                validate(raw,job,document)
                continue
            except (ValueError,KeyError,TypeError):pass
        pending.append(job['id'])
    return pending_originals(folder,model,pending)


def reading_plan(folder,document,pages=None,model='gpt-6-luna',scope='document',page=None,strategy='newest-k1-2-6'):
    page,targets,_=selection(document,scope,page)
    root=root_path(folder,document,strategy,model,scope,page)
    saved=saved_complete(folder,document,strategy,model,scope,page)
    from pdf_newest_k1_2_0_cost import samples, estimate as workload_estimate, workload, VERSION as ESTIMATE_VERSION
    from pdf_k113_coverage import complete as review_complete
    complete=bool(review_complete(saved) and saved.get('localOutputVersion')==CHECKS_VERSION)
    history=[] if complete else samples(Path(folder).parent,model,VERSION,document.get('documentId'))
    prediction = {'usd':0,'tokens':0,'lowUsd':0,'highUsd':0,'sampleCount':0,'workload':{},'stageUsd':{}}
    if not complete:
        # Reuse layout only from this exact source/prompt identity. Extraction is
        # local and receives no cache path, so approval never creates paid results.
        blocks_path=root/'blocks.json'
        try:
            blocks=json.loads(blocks_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            blocks=extract_layout(folder,document,targets,extractor=extract,layout_version=LAYOUT_VERSION)
        work=None
        manifest=read_json(root/'manifest.json')
        plan=read_json(root/'plan.json') or {}
        plan_ready=usable_plan(plan,model,blocks)
        pending_work=None
        if plan_ready and manifest and manifest.get('jobs') is not None:
            work=workload(document,targets,blocks=blocks,jobs=manifest['jobs'])
            from pdf_k113_saved import index as saved_index, reply as saved_reply
            previous=saved_index(folder,document,strategy,model,scope,page,root,prompt_version=VERSION)
            pending=[]
            for job in manifest['jobs']:
                if job.get('skip'):continue
                raw=read_json(root/f'response-{job["id"]}.json')
                if raw is None:
                    raw,_=saved_reply(previous,job)
                if raw is not None:
                    try:
                        unit=validate(raw,job,document)
                        if not any(c['state']=='needs_review' for c in unit['coverage']):continue
                    except (ValueError,KeyError,TypeError):pass
                pending.append(job)
            # Count the remaining payloads, rather than multiplying every job by
            # the same cache percentage (large and small jobs cost differently).
            pending_work=workload(document,targets,blocks=blocks,jobs=pending)
        if work is None:work=workload(document,targets,blocks=blocks)
        prediction=workload_estimate(document,targets,history,work=work,pending_work=pending_work,
            plan_cached=plan_ready,model=model)
    estimate=0 if complete else prediction['usd']
    estimated_tokens=0 if complete else prediction['tokens']
    return {'strategy':strategy,'pages':targets,'totalPages':len(targets),
            'cachedPages':len(targets) if complete else 0,'pendingPages':0 if complete else len(targets),
            'costEstimateUsd':estimate,'totalCostEstimateUsd':estimate,'additionalCostEstimateUsd':0,
            'estimatedTotalTokens':estimated_tokens,
            'estimateLowUsd':0 if complete else prediction['lowUsd'],
            'estimateHighUsd':0 if complete else prediction['highUsd'],
            'estimateVersion':ESTIMATE_VERSION,'estimateSampleCount':prediction['sampleCount'],
            'estimateWorkload':prediction['workload'],'estimateStageUsd':prediction['stageUsd'],
            'estimateBasis':('저장된 완료 결과 재사용' if complete else
                f'Newest_K1.2.6 추정 · '+('확정 묶음 기준' if plan_ready else '의미 묶음 확정 전')+f' · 유사 실측 {prediction["sampleCount"]}개'
                if prediction['sampleCount'] else 'Newest_K1.2.6 임시 추정 · 의미 묶음·캐시 재사용 확정 전')}

# Verification is scoped to actual symbolic/lifetime syntax in the owned source.
from pdf_k121_exact_checks import VERSION as EXACT_CHECK_VERSION
CHECKS_VERSION += ':'+EXACT_CHECK_VERSION
_k121_build_teaching_request = build_teaching_request
def build_teaching_request(folder,job,blocks,document,prepared,**kwargs):
    request=_k121_build_teaching_request(folder,job,blocks,document,prepared,**kwargs)
    from pdf_k121_exact_checks import kinds,RULES,MATH_SELECTION,chart,GRAPH_RULES
    symbolic,lifetime=kinds(job['blocks'])
    if chart(job['blocks']):
        request['instructions']+=GRAPH_RULES
        request['context']['plotSelectionPolicy']=EXACT_CHECK_VERSION
    if symbolic or lifetime:
        request['instructions']+=RULES
        if symbolic:request['instructions']+=MATH_SELECTION
        request['context']['reasoningEffort']='low'
        request['context']['exactTechnicalChecks']=EXACT_CHECK_VERSION
        setup=request['response_format']['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']
        for key in ('observedRelations','boundaryChecks'):setup[key]['minItems']=max(1,setup[key].get('minItems',0))
        exact=request.get('_sourceCoverageExactFormat')
        if exact:
            props=exact['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']
            for key in ('observedRelations','boundaryChecks'):props[key]['minItems']=max(1,props[key].get('minItems',0))
    return request

# K1.2.2 keeps source constraints locally exact while reusing one source-pool
# schema per semantic-check profile. Its duplicate index is derived exclusively
# from the model's MAIN citations; missing citations remain blank for validation.
_k122_request=build_teaching_request
def build_teaching_request(*args,**kwargs):
    request=_k122_request(*args,**kwargs)
    from pdf_k120_compact_coverage import encode_format
    from pdf_k122_cache_format import encode as stable_format
    from pdf_k122_derived_index import encode as indexed_format, RULES, VERSION
    from pdf_newest_k1_2_0_prompts import _COMPACT_COVERAGE,_CANONICAL_COVERAGE
    if request.get('_sourceCoverageExactFormat') is None:
        request['response_format'],request['_sourceCoverageExactFormat']=encode_format(request['response_format'])
        request['instructions']=request['instructions'].replace(_CANONICAL_COVERAGE,RULES)
    else:
        request['response_format']=stable_format(request['response_format'])
        request['instructions']=request['instructions'].replace(_COMPACT_COVERAGE,RULES)
    request['response_format']=indexed_format(request['response_format'])
    request['_derivedMainIndex']=VERSION
    from pdf_k122_relation_checks import RULES as RELATION_CHECKS
    request['instructions']+=RELATION_CHECKS
    targets=request['job']['blocks']
    if (any((block.get('text') or '').strip() for block in targets)
            and all((block.get('planRoleBeforeVisualGuard') or block.get('planRole'))=='exercise'
                    for block in targets)):
        for default, brief in PRACTICE_COMPRESSION:
            request['instructions']=request['instructions'].replace(default,brief,1)
        payload=request['payload']
        payload.pop('titleHint',None)
        current=payload['unitContext'].get('current',{})
        current.pop('title',None)
        current.pop('description',None)
    if SAVINGS_PROFILE == 'dedup':
        from pdf_k126_dedup import deduplicate_instructions
        request['instructions']=deduplicate_instructions(request['instructions'])
    from pdf_k123_contract import encode
    return encode(request)

_k122_accept=accept_teaching_reply
def accept_teaching_reply(cache,document,jobs,job,raw,request):
    from pdf_k123_contract import restore,quarantine_unused_exclusions,remove_wire_annotations
    raw=restore(raw,request)
    raw,annotations=remove_wire_annotations(raw,request)
    if annotations:
        write_json(Path(cache)/f'wire-annotations-{job["id"]}.json',{
            'records':annotations,'learnerClaimsAndSourceReferencesUnchanged':True})
    raw,removed=quarantine_unused_exclusions(raw,request)
    if removed:
        write_json(Path(cache)/f'rejected-dispositions-{job["id"]}.json',{
            'reason':'Unused schema-pool alias cannot exclude any real source',
            'records':removed,'exactSourceAndMainCitationValidationRetained':True})
    if request.get('_derivedMainIndex'):
        from pdf_k122_derived_index import expand
        raw=expand(raw,request['_sourceCoverageExactFormat'])
    return _k122_accept(cache,document,jobs,job,raw,request)

CHECKS_VERSION += ":k122-source-index-cache-bundles-v2:source-relation-grounding-v2:k123-concise-internal-records-v2"
