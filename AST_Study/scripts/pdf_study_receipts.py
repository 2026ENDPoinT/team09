"""Reconcile original stored Chat/Responses receipts, never create a generation.

Only exact persisted request IDs/cache keys in this document are eligible. A
network timeout or an empty metadata lookup is NOT evidence that a POST was free.
Returned output still passes the ordinary unit/source validator when reused.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from pdf_auth_rejection import is_authentication_rejection


def proven_unsent(entry):
    """Only the instrumented pre-write phase proves that no model POST existed."""
    return (isinstance(entry,dict)and isinstance(entry.get('requestId'),str)
        and re.fullmatch('[a-f0-9]{32}',entry['requestId'])is not None
        and entry.get('httpTransport')=='pooled_http1_no_retries'
        and entry.get('transportFailurePhase')=='connecting'
        and entry.get('requestWriteAttempted') is False
        and all(type(entry.get(k))is int and entry[k]==0 for k in
            ('requestBodyBytesSent','requestWireBytesSent','requestBodyBytesAttemptedUpperBound'))
        and not any(entry.get(k)for k in ('responseId','chatCompletionId','serverRequestId','requestUploadComplete'))
        and entry.get('state')in ('reserved','failed_or_uncertain','usage_unknown','not_sent'))


def strict_object(raw):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('Duplicate stored response field')
            value[key]=item
        return value
    def constant(_):raise ValueError('Nonfinite stored response number')
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    if not isinstance(value,dict):raise ValueError('Stored answer must be an object')
    return value


def stored_original(entry, *, key, open_url, timeout=20, wait_window=0,
                    check=lambda:None, clock=time.monotonic, sleep=time.sleep, outcome=None):
    from pdf_study_chat import COMPLETION_ID
    if entry.get('inputApi')=='responses':
        from pdf_study_connection import RESPONSE_ID
        from pdf_responses_transport import response_body
        ident=entry.get('responseId')
        if not isinstance(ident,str)or not RESPONSE_ID.fullmatch(ident):return None
        request=urllib.request.Request('https://api.openai.com/v1/responses/'+ident,
            headers={'Authorization':'Bearer '+key},method='GET')
        deadline=clock()+wait_window
        for attempt in range(18):
            check()
            read_timeout=min(timeout,max(.001,deadline-clock()))if wait_window else timeout
            with open_url(request,timeout=read_timeout)as stream:native=json.load(stream)
            if outcome is not None:outcome['lookupPerformed']=True
            if not isinstance(native,dict)or native.get('id')!=ident:return None
            if native.get('status')not in ('queued','in_progress')or clock()>=deadline:break
            left=min(15,1.7**attempt,max(0,deadline-clock()))
            while left>0:
                check();delay=min(.25,left);sleep(delay);left-=delay
        if not isinstance(native,dict)or native.get('id')!=ident or native.get('status')!='completed':return None
        value=response_body(native)
        choice=value['choices'][0];usage=value.get('usage')
        if (choice.get('finish_reason')!='stop'or choice.get('message',{}).get('refusal')
                or not isinstance(usage,dict)or any(type(usage.get(k))is not int or usage[k]<0
                    for k in ('prompt_tokens','completion_tokens'))):return None
        return value,strict_object(choice['message']['content'])
    ident=entry.get('chatCompletionId');tag=entry.get('recoveryRequestTag')
    if not isinstance(ident,str)or not COMPLETION_ID.fullmatch(ident):ident=None
    if not isinstance(tag,str)or not re.fullmatch('[a-f0-9]{32}',tag):tag=None
    if ident is None and tag is None:return None
    url='https://api.openai.com/v1/chat/completions'
    url+=('/'+ident if ident else '?'+urllib.parse.urlencode({'limit':2,'metadata[synesis_request_id]':tag}))
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+key},method='GET')
    with open_url(request,timeout=timeout)as stream:value=json.load(stream)
    if outcome is not None:outcome['lookupPerformed']=True
    if ident is None:
        candidates=value.get('data')if isinstance(value,dict)else None
        if candidates == [] and value.get('has_more') is False and outcome is not None:
            outcome['unavailable']=True
        if not isinstance(candidates,list)or len(candidates)!=1 or value.get('has_more')is not False:return None
        value=candidates[0]
    if not isinstance(value,dict):return None
    found=value.get('id')
    if not isinstance(found,str)or not COMPLETION_ID.fullmatch(found)or ident and found!=ident:return None
    if tag is not None and value.get('metadata',{}).get('synesis_request_id')!=tag:return None
    choices=value.get('choices');usage=value.get('usage')
    if not isinstance(choices,list)or len(choices)!=1 or not isinstance(choices[0],dict):return None
    if not isinstance(usage,dict)or any(type(usage.get(k))is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):return None
    choice=choices[0]
    if choice.get('finish_reason')!='stop'or choice.get('message',{}).get('refusal'):return None
    content=choice.get('message',{}).get('content')
    if not isinstance(content,str):return None
    parsed=strict_object(content)
    return value,parsed


def receipt_cost(model, usage, entry):
    from pdf_ai import PRICES,LUNA_LONG_CONTEXT_THRESHOLD
    input_rate,output_rate=PRICES[model]
    count=usage['prompt_tokens'];output=usage['completion_tokens']
    details=usage.get('prompt_tokens_details')or{}
    cached=min(count,max(0,details.get('cached_tokens',0)))
    writes=min(count-cached,max(0,details.get('cache_write_tokens',0)))
    long=model=='gpt-6-luna'and count>LUNA_LONG_CONTEXT_THRESHOLD
    tier=2 if entry.get('billedServiceTier',entry.get('requestedServiceTier'))in ('fast','priority')else 1
    input_rate*=tier*(2 if long else 1);output_rate*=tier*(1.5 if long else 1)
    cached_rate=.01*tier*(2 if long else 1)
    premium=writes*input_rate*.25/1_000_000
    actual=((count-cached)*input_rate+cached*cached_rate+output*output_rate)/1_000_000+premium
    return actual,premium


def reconcile(provider, *, open_url=None):
    """At a safe document-lock boundary, restore output and settle ORIGINAL holds.

    An injected in-memory completion fixture never contacts a remote server.
    Custom audits can inject a GET-only opener. Old receipt settlement does not
    create a charge or reserve in the new generation operation.
    """
    if provider.transport is not None and open_url is None:return []
    from pdf_pipeline import check_cancel,write_json
    transport=getattr(provider,'study_http_transport',None)
    if open_url is None:
        open_url=(lambda req,timeout:transport.open(req,timeout))if transport is not None else urllib.request.urlopen
    results=[];folder=Path(provider.folder).resolve()
    if not hasattr(provider,'unavailable_study_request_ids'):
        provider.unavailable_study_request_ids=set()
    deadline=time.monotonic()+getattr(provider,'study_recovery_window',180)
    for path in sorted((folder/'usage').glob('*.json')):
        check_cancel(folder)
        if not path.resolve().is_relative_to(folder):continue
        current=path==provider.ledger_path.resolve()
        try:ledger=provider.ledger if current else json.loads(path.read_text())
        except (OSError,ValueError):continue
        if not isinstance(ledger,dict)or not isinstance(ledger.get('requests'),list)or ledger.get('model')!=provider.model:continue
        for entry in ledger.get('requests',[]):
            if time.monotonic() >= deadline:return results
            from pdf_generation_cancel import retryable
            if isinstance(entry,dict) and retryable(entry) and not entry.get('recoveryBillingPending'):
                continue
            if (not isinstance(entry,dict)or entry.get('inputApi')not in ('chat','responses')
                    or entry.get('kind')not in ('region_study','region_plan')or 'sentAtMs'not in entry
                    or entry.get('state')=='not_sent'and not entry.get('notSentBillingPending')
                    or is_authentication_rejection(entry)):continue
            bounded_attempt=entry.get('hedgePolicy') in ('four-attempts-30-60-v1','four-attempts-progress-30-60-v1','four-attempts-progress-20-60-v1')
            # A finished four-attempt race must not acquire another 180-second
            # wait in this run's final reconciliation. Preserve the receipt/hold
            # for a later invocation; cancellation already runs independently.
            if (bounded_attempt and current and entry.get('hedgeRaceFinished') is True
                    and not entry.get('recoveryBillingPending')):continue
            discarded_attempt=bounded_attempt and (entry.get('attemptExpired') is True
                or entry.get('clientStopReason') in ('attempt_deadline','hedge_superseded','user_cancelled'))
            if entry.get('state')=='settled'and not entry.get('recoveryBillingPending'):continue
            if proven_unsent(entry):
                # Repair older pre-write timeouts without deleting their audit
                # history or mistaking an ambiguous, fully sent POST for free work.
                if current and entry.get('state')!='not_sent':provider.spent-=entry.get('reservedUsd',0)
                entry.update(state='not_sent',estimatedUsd=0,notSentConfirmedAtMs=int(time.time()*1000),notSentBillingPending=True)
                write_json(path,ledger)
                billing=getattr(provider,'billing',None)
                if current:provider.settle_credits(entry)
                elif billing is not None:
                    from pdf_credit_billing import Billing
                    category=ledger.get('category')or('planning'if entry.get('kind')=='region_plan'else billing.category)
                    Billing(billing.path,ledger['operationId'],category,ledger.get('createdAtMs'),path).settle(entry['requestId'],0)
                entry.pop('notSentBillingPending',None);write_json(path,ledger)
                continue
            cache_key=entry.get('responseCacheKey')
            if not isinstance(cache_key,str)or not re.fullmatch('[a-f0-9]{64}',cache_key):continue
            cache=folder/'generated/paid-responses'/(cache_key+'.json')
            if not cache.resolve().is_relative_to(folder):continue
            from pdf_study_rejection import is_rejected,rejected_entry,mark_rejected
            if rejected_entry(entry):mark_rejected(cache,entry)
            rejected_result=is_rejected(cache,entry)
            if not entry.get('recoveryBillingPending'):
                outcome={}
                try:found=stored_original(entry,key=provider.key,open_url=open_url,
                    timeout=min(6 if discarded_attempt else 20,max(.001,deadline-time.monotonic())),
                    wait_window=max(0,deadline-time.monotonic())if entry.get('inputApi')=='responses'and not discarded_attempt else 0,
                    check=lambda:check_cancel(folder),outcome=outcome)
                except urllib.error.HTTPError as failure:
                    entry.update(receiptLookupHttpStatus=failure.code,receiptLookupAtMs=int(time.time()*1000))
                    write_json(path,ledger)
                    if (failure.code==404 and not current and entry.get('kind')=='region_study'
                            and not entry.get('unresolvedRetryApproved')
                            and not entry.get('durableRecoveryOf') and not entry.get('foregroundRecoveryOf')):
                        provider.unavailable_study_request_ids.add(entry.get('requestId'))
                    continue
                except (OSError,ValueError,TypeError,KeyError):continue
                if entry.get('kind')=='region_plan'and outcome.get('lookupPerformed'):
                    entry.update(receiptLookupHttpStatus=200,receiptLookupAtMs=int(time.time()*1000))
                    write_json(path,ledger)
                if found is None:
                    # Never turn a network/auth failure or an active Responses job into a retry grant.
                    if (outcome.get('unavailable') is True and not current and entry.get('kind')=='region_study'
                            and not entry.get('unresolvedRetryApproved')
                            and not entry.get('durableRecoveryOf') and not entry.get('foregroundRecoveryOf')):
                        provider.unavailable_study_request_ids.add(entry.get('requestId'))
                    continue
                native,parsed=found
                # A live stream can reject this attempt while the receipt GET
                # is in flight. Recheck before creating any reusable answer.
                if rejected_entry(entry):mark_rejected(cache,entry)
                rejected_result=is_rejected(cache,entry)
                if entry.get('requestedServiceTier'):
                    tier=native.get('service_tier')
                    entry['billedServiceTier']='default' if tier=='default' else 'fast'
                actual,premium=receipt_cost(provider.model,native['usage'],entry)
                if current:provider.spent+=actual-entry.get('reservedUsd',0)
                entry.update(state='settled',usage=native['usage'],estimatedUsd=actual,
                    cacheWritePremiumUsd=premium,
                    recoveredOriginalResponse=True,recoveryBillingPending=True,
                    networkPhase='recovered_original',receiptRecoveredAtMs=int(time.time()*1000))
                if entry.get('inputApi')=='responses':
                    write_json(cache.with_suffix('.responses.raw.json'),native['_responsesApiRaw'])
                    entry.update(responseId=native['_responsesApiRaw']['id'],serverTerminalStatus='completed')
                else:entry['chatCompletionId']=native['id']
                write_json(cache.with_suffix('.raw.json'),native)
                if not rejected_result:write_json(cache,parsed)
                else:entry['recoveredOriginalResultRejected']=True
                write_json(path,ledger)
            billing=getattr(provider,'billing',None)
            if current:provider.settle_credits(entry)
            elif billing is not None:
                from pdf_credit_billing import Billing
                category=ledger.get('category')or('planning'if entry.get('kind')=='region_plan'else billing.category)
                Billing(billing.path,ledger['operationId'],category,
                    ledger.get('createdAtMs'),path).settle(entry['requestId'],entry['estimatedUsd'])
            entry.pop('recoveryBillingPending',None);write_json(path,ledger)
            rejected_result=rejected_result or is_rejected(cache,entry)
            results.append({'requestId':entry['requestId'],'responseCacheKey':cache_key,
                'unitIds':[] if discarded_attempt or rejected_result else entry.get('unitIds',[]),
                'additionalGenerations':0})
    return results
