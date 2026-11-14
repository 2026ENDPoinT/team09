"""One foreground structured study completion; no commentary channel or retries.

Preserves server finish reason and usage. Preview text is only a callback and
cannot turn a lost or incomplete stream into a successful paid response.
"""
import json
import math
import re
import time
import urllib.error
import urllib.request
import urllib.parse
from pdf_study_connection import (HEADERS_TIMEOUT, IDLE_TIMEOUT, RECOVERY_TIMEOUT,
    RECOVERY_READS, RECOVERY_WINDOW, MAX_EVENT_BYTES, StudyConnectionError, _read_timeout)

COMPLETION_ID = re.compile(r'chatcmpl[-_][A-Za-z0-9_-]{1,240}\Z')


def collect(stream, *, check=lambda:None, update=lambda **x:None,
            on_delta=None, clock=time.monotonic, schema=None):
    started=clock();last_progress=started;parts=[];usage=None;finish=None;done=False
    ident=None;model=None;tier=None;refusal='';events=0;first_text=False;chars=0
    headers=getattr(stream,'headers',{})
    if 'text/event-stream'not in headers.get('content-type',headers.get('Content-Type','')).lower():
        # Compatible test/local transports can return one terminal JSON object.
        return json.load(stream)
    guard=None
    if isinstance(schema,dict):
        from pdf_json_boundary import JsonBoundary
        guard=JsonBoundary(schema)
    try:
        while True:
            check();remaining=IDLE_TIMEOUT-(clock()-last_progress)
            if remaining<=0:raise StudyConnectionError('chat_stream_idle')
            _read_timeout(stream,remaining);line=stream.readline(MAX_EVENT_BYTES+1)
            if not line:break
            if len(line)>MAX_EVENT_BYTES:raise StudyConnectionError('chat_oversized_event')
            if isinstance(line,bytes):line=line.decode('utf-8')
            if not line.startswith('data:'):continue
            data=line[5:].strip()
            if data=='[DONE]':done=True;break
            chunk=json.loads(data);events+=1
            if chunk.get('error'):raise StudyConnectionError('chat_stream_error')
            fields={'streamEvents':events}
            if chunk.get('id'):
                if not isinstance(chunk['id'],str) or not COMPLETION_ID.fullmatch(chunk['id']):
                    raise StudyConnectionError('chat_invalid_id')
                if ident is not None and ident!=chunk['id']:raise StudyConnectionError('chat_id_changed')
                ident=chunk['id'];fields['chatCompletionId']=ident
            if chunk.get('model'):model=chunk['model']
            if isinstance(chunk.get('service_tier'),str):tier=chunk['service_tier']
            if isinstance(chunk.get('usage'),dict):usage=chunk['usage'];last_progress=clock()
            for choice in chunk.get('choices',[]):
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta')or{}
                if isinstance(delta.get('refusal'),str):refusal+=delta['refusal'];last_progress=clock()
                content=delta.get('content')
                if isinstance(content,str)and content:
                    parts.append(content);chars+=len(content);last_progress=clock()
                    if not first_text:fields['firstFinalTextSeconds']=round(clock()-started,4);first_text=True
                    fields.update(finalTextChars=chars,lastNetworkProgressAtMs=int(time.time()*1000))
                    if guard is not None:
                        was_complete=guard.finished;reason=guard.feed(content)
                        if guard.finished and not was_complete:
                            fields.update(completeJsonSeconds=round(clock()-started,4),completeJsonChars=guard.end)
                        if reason:
                            # Only JSON framing/duplicate fields/outside padding;
                            # never a length limit on learner prose or formulas.
                            fields.update(clientStopReason=reason,networkPhase='output_anomaly',
                                          discardedTailChars=guard.tail_chars)
                            update(**fields)
                            raise StudyConnectionError('chat_output_anomaly')
                    if on_delta:
                        try:on_delta(content)
                        except InterruptedError:raise
                        except Exception:pass
                if choice.get('finish_reason')is not None:finish=choice['finish_reason'];last_progress=clock()
            update(**fields)
        if not done or finish is None:raise StudyConnectionError('chat_stream_incomplete')
        update(networkPhase='response_received')
        message={'role':'assistant','content':''.join(parts)}
        if refusal:message['refusal']=refusal
        value={'id':ident,'model':model,'choices':[{'index':0,'message':message,'finish_reason':finish}],'usage':usage}
        if tier is not None:value['service_tier']=tier
        return value
    except Exception as error:
        # Durable evidence, never a fabricated terminal result/usage. Provider
        # records the incomplete status and retains the original reservation.
        error.study_partial_response={'id':ident,'model':model,'content':''.join(parts),
            'usage':usage,'finishReason':finish,'terminalReceived':done,'streamEvents':events}
        if guard is not None and guard.finished:
            # Evidence only. A local JSON boundary is not an API terminal status
            # or a billing receipt, so this is never promoted to a paid success.
            error.study_partial_response['completeJsonCandidate']=guard.value
        raise


def request_once(request, *, open_url, update, check=lambda:None, on_headers=lambda h:None,
                 on_delta=None, on_partial=lambda p:None, clock=time.monotonic, sleep=time.sleep,
                 recover_without_id=True, recovery_window=RECOVERY_WINDOW,
                 recovery_reads=RECOVERY_READS, recovery_timeout=RECOVERY_TIMEOUT,
                 headers_timeout=HEADERS_TIMEOUT):
    """One foreground POST; bounded read-only recovery by exact ID or request tag.

    Closing a failed stream does not assert server cancellation or zero charge.
    Only a genuine stored completion can release an unknown-usage reservation.
    """
    started=clock();headers_at=None;request_tag=None
    try:
        body=json.loads(request.data or b'{}')
        schema=body.get('response_format',{}).get('json_schema',{}).get('schema')
        tag=body.get('metadata',{}).get('synesis_request_id')
        if body.get('store')is True and isinstance(tag,str)and re.fullmatch(r'[a-f0-9]{32}',tag):request_tag=tag
        update(networkPhase='waiting_headers',networkMode='chat_sse_v1')
        with open_url(request,timeout=headers_timeout)as stream:
            headers_at=clock();headers=getattr(stream,'headers',{})
            on_headers(headers)
            fields={'networkPhase':'receiving_events',
                    'connectionAndResponseHeadersSeconds':round(headers_at-started,4)}
            trace=headers.get('x-request-id')
            if isinstance(trace,str)and re.fullmatch(r'[A-Za-z0-9_-]{1,200}',trace):fields['serverRequestId']=trace
            raw_ms=headers.get('openai-processing-ms')
            try:
                server_ms=float(raw_ms)if raw_ms is not None and len(str(raw_ms))<=64 else None
                if server_ms is not None and math.isfinite(server_ms)and 0<=server_ms<=86_400_000:
                    fields['serverProcessingMs']=server_ms
            except (TypeError,ValueError):pass
            update(**fields)
            result=collect(stream,check=check,update=update,on_delta=on_delta,clock=clock,schema=schema)
        update(networkPhase='response_received',responseBodySeconds=round(clock()-headers_at,4))
        return result
    except (InterruptedError,urllib.error.HTTPError):raise
    except (OSError,ValueError)as failure:
        partial=getattr(failure,'study_partial_response',{})
        if partial:on_partial(partial)
        phase=failure.phase if isinstance(failure,StudyConnectionError)else('chat_stream_idle'if headers_at is not None else'waiting_headers')
        update(networkPhase=phase,connectionFailureType=type(failure).__name__)
        ident=partial.get('id')
        if not isinstance(ident,str)or not COMPLETION_ID.fullmatch(ident):ident=None
        if ident is None and not recover_without_id:
            # Only the optional title-only roadmap selects this policy. Healthy
            # header waits/streams and ID-based recovery are unchanged. Once an
            # unidentified connection has already failed, use local headings
            # rather than holding all completed teaching for speculative GETs.
            # The original POST and unknown charge remain in the ledger.
            update(recoverySkipped='optional_overview_without_receipt')
            raise StudyConnectionError('chat_optional_overview_unacknowledged',failure)from failure
        if ident is None and request_tag is None:raise StudyConnectionError(phase,failure)from failure
        # A malformed, actively growing output must not be accepted through the
        # recovery path. Retain its exact partial and no duplicate paid POST.
        if phase=='chat_output_anomaly':raise
        auth=request.get_header('Authorization');headers={'Authorization':auth}if isinstance(auth,str)else{}
        deadline=clock()+recovery_window
        for attempt in range(recovery_reads):
            check();remaining=deadline-clock()
            if remaining<=0:break
            url='https://api.openai.com/v1/chat/completions'
            if ident is not None:url+='/'+ident
            else:url+='?'+urllib.parse.urlencode({'limit':2,'metadata[synesis_request_id]':request_tag})
            get=urllib.request.Request(url,headers=headers,method='GET')
            update(networkPhase='recovering_original',recoveryReads=attempt+1,
                   recoveryLookup='completion_id'if ident is not None else'exact_request_tag')
            try:
                with open_url(get,timeout=min(recovery_timeout,remaining))as stream:value=json.load(stream)
                if ident is None:
                    candidates=value.get('data')if isinstance(value,dict)else None
                    # Never use a latest completion, an unfiltered response,
                    # ambiguous matches, or another document's paid result.
                    if not isinstance(candidates,list)or len(candidates)!=1 or value.get('has_more')is not False:raise ValueError('No unique stored request')
                    value=candidates[0]
                    if not isinstance(value,dict)or value.get('metadata',{}).get('synesis_request_id')!=request_tag:raise ValueError('Stored request tag mismatch')
                    found=value.get('id')
                    if not isinstance(found,str)or not COMPLETION_ID.fullmatch(found):raise ValueError('Invalid stored completion ID')
                    ident=found
                choice=value.get('choices',[None])[0]if isinstance(value,dict)else None
                if (value.get('id')==ident and isinstance(choice,dict)
                        and choice.get('finish_reason')is not None and isinstance(value.get('usage'),dict)):
                    update(networkPhase='recovered_original',recoveredOriginalResponse=True,chatCompletionId=ident)
                    return value
            except urllib.error.HTTPError as error:
                if error.code in (401,403):raise
            except (OSError,ValueError,TypeError,IndexError,AttributeError):pass
            if attempt+1<recovery_reads:
                # A stored list may appear only after generation completes.
                # Spread bounded reads across the recovery window instead of
                # treating a few immediate empty lookups as a final failure.
                wait=min(15,1.7**attempt)if ident is not None else min(15,7+attempt)
                left=min(wait,max(0,deadline-clock()))
                while left>0:
                    check();delay=min(.25,left);sleep(delay);left-=delay
        error=StudyConnectionError('chat_recovery_pending',failure)
        if partial:error.study_partial_response=partial
        raise error from failure
