"""Lossless host state stays local; the model receives only useful representations."""
import copy
import json

PREVIEW_LIMIT = 12
ROW_FIELDS = ('id','kind','name','path','parentId','exactMatch','matchQuality','systemTrash','trashed')


def library_row(row, preview=False):
    if not isinstance(row,dict):return copy.deepcopy(row)
    fields=('id','kind','name','systemTrash','trashed') if preview else ROW_FIELDS
    return {key:copy.deepcopy(row[key]) for key in fields if key in row}


def model_context(context):
    out=copy.deepcopy(context)
    library=out.get('library')
    if isinstance(library,dict):
        view=library.pop('requestView',None)  # Native validation retains the complete source view.
        if isinstance(view,dict) and any(view.get(k)!=library.get(k) for k in ('currentFolderId','screen','search')):
            library['requestView']={k:copy.deepcopy(view[k]) for k in ('currentFolderId','currentPath','screen','search','libraryVisible') if k in view}
        rows=library.get('visibleItems',[])
        if isinstance(rows,list):
            total=max(len(rows),library.get('visibleTotal',len(rows)))
            library['visibleItems']=[library_row(row,True) for row in rows[:PREVIEW_LIMIT]]
            library['visibleTotal']=total
            library['visibleItemsTruncated']=bool(library.get('visibleItemsTruncated') or total>PREVIEW_LIMIT)
            if library['visibleItemsTruncated']:library['visibleItemsOmitted']=True
        if isinstance(library.get('breadcrumbs'),list):
            library['breadcrumbs']=[{k:copy.deepcopy(row[k]) for k in ('id','name','path') if k in row} for row in library['breadcrumbs']]
        pending=library.get('pendingMove')
        if isinstance(pending,dict):
            if isinstance(pending.get('sources'),list):pending['sources']=[library_row(row) for row in pending['sources']]
            if isinstance(pending.get('destination'),dict):pending['destination']=library_row(pending['destination'])
        pending=library.get('pendingClarification')
        if isinstance(pending,dict) and isinstance(pending.get('candidates'),list):
            pending['candidates']=[library_row(row) for row in pending['candidates']]
        pending=library.get('pendingRequest')
        if isinstance(pending,dict):
            if isinstance(pending.get('targets'),list):
                pending['targets']=[library_row(row) for row in pending['targets']]
        for name in ('pendingClarification','pendingRequest'):
            pending=library.get(name)
            if isinstance(pending,dict) and isinstance(pending.get('requestView'),dict):
                pending['requestView']={key:copy.deepcopy(pending['requestView'][key])
                                        for key in ('currentFolderId','currentPath','screen','section','search','libraryVisible')
                                        if key in pending['requestView']}
    # Old/unavailable/other-session recovery details are not conversational context.
    undo=out.get('undo')
    if isinstance(undo,dict):
        if undo.get('sameSession') is False or out.get('recoveryInterpretationEligible') is not True and 'undo' not in str(out.get('mutationScope','')).split(','):
            out['undo']={'available':undo.get('available',False) and undo.get('sameSession') is not False}
        elif undo.get('available') is not True:
            out['undo']={k:copy.deepcopy(undo[k]) for k in ('available','reason') if k in undo}
        else:
            undo.pop('at',None);undo.pop('revision',None);undo.pop('undone',None)
            if isinstance(undo.get('context'),dict):
                undo['context']={k:copy.deepcopy(undo['context'][k]) for k in ('request','changes','keys','bulkSchedule','changeCount','changesTruncated') if k in undo['context']}
                if undo.get('domain')=='library' and isinstance(undo['context'].get('changes'),list):
                    changes=undo['context']['changes'];undo['context']['changeCount']=len(changes)
                    undo['context']['changes']=[{k:copy.deepcopy(row[k]) for k in ('operation','kind','id','oldName','name','sourceParentId','parentId') if k in row} for row in changes[:PREVIEW_LIMIT]]
                    if len(changes)>PREVIEW_LIMIT:undo['context']['changesTruncated']=True
    # Volatile checks and bookkeeping are native facts, not reasoning inputs.
    for name in ('plannerAccess','profile'):
        if isinstance(out.get(name),dict):out[name].pop('checkedAt',None)
    return out


def model_result(record):
    out=copy.deepcopy(record)
    out.pop('plannerContextRead',None)
    request=out.get('request',{})
    request.pop('authorizationQuote',None);request.pop('argumentsJson',None)
    tool=request.get('tool','')
    if tool not in ('planner.query','library.query','profile.get','memory.read'):
        arguments=request.pop('arguments',None)  # Actual committed fields below are authoritative.
        if tool=='library.proposeMove' and isinstance(arguments,dict):
            request['arguments']={key:copy.deepcopy(arguments[key]) for key in ('ids','destinationId') if key in arguments}
        elif tool=='library.confirmMove' and isinstance(arguments,dict):
            request['arguments']={key:copy.deepcopy(arguments[key]) for key in ('proposalId',) if key in arguments}
    result=out.get('result',{})
    data=result.get('data')
    if isinstance(data,dict) and tool.startswith('library.'):
        if isinstance(data.get('items'),list):data['items']=[library_row(row) for row in data['items']]
        if tool=='library.query' and request.get('arguments',{}).get('parentId') is not None:
            data['directChildrenOnly']=True
            if data.get('total')==0:
                data['scopeNotice']='이 조회는 지정 폴더의 바로 아래만 확인했어요. 하위 폴더는 검색하지 않았어요. 현재 화면만 지정한 요청이 아니면 parentId를 생략한 전체 이름/연도 검색과 결과 경로로 대상을 확인해요.'
        if tool!='library.query':
            # Undo receipts, graph ancestry and animation bookkeeping stay in the host.
            keep={'revision','applied','status','kind','id','name','path','alreadyOpen','alreadyThere',
                  'destinationPath','movedCount','trashedCount','moved','createdFolders','notice','animationCompleted'}
            data={k:v for k,v in data.items() if k in keep}
            if isinstance(data.get('createdFolders'),list):data['createdFolders']=[library_row(row) for row in data['createdFolders']]
            if isinstance(data.get('moved'),list):data['moved']=[{k:copy.deepcopy(row[k]) for k in ('kind','id','parentId') if k in row} for row in data['moved']]
            result['data']=data
    return out


def model_payload(payload, tool_catalog_in_system=False):
    out={key:copy.deepcopy(value) for key,value in payload.items() if key not in ('sessionId','turnId','localContext','localResults')}
    if tool_catalog_in_system and isinstance(out.get('toolCatalog'),dict):
        # Trusted tool definitions live in the stable system suffix; dynamic data stays here.
        out['toolCatalog']=sorted(out['toolCatalog'])
    out['localContext']=model_context(payload.get('localContext',{}))
    seen=set();results=[]
    for record in payload.get('localResults',[]):
        if record.get('plannerContextRead'):
            current=payload.get('plannerContext',{}).get('revision',payload.get('localContext',{}).get('plannerAccess',{}).get('revision'))
            result=record.get('result',{})
            if current is not None and (not result.get('ok') or result.get('data',{}).get('revision')!=current):continue
        projected=model_result(record)
        request=projected.get('request',{})
        if request.get('tool') in ('library.query','planner.query') and projected.get('result',{}).get('ok'):
            # Full result participates: a changed revision or changed data is never hidden.
            fingerprint=json.dumps({'tool':request['tool'],'arguments':request.get('arguments',{}),'result':projected['result']},sort_keys=True,ensure_ascii=False)
            if fingerprint in seen:continue
            seen.add(fingerprint)
        results.append(projected)
    out['localResults']=results
    return out
