"""K1.2.0 customer holds: expected cost × 1.3, separate from provider caps.

This is a local prediction, never a token/output limit or a usage receipt. The
provider's reservedUsd still protects the explicitly authorized operation cap.
"""
import json
import math
import statistics
from decimal import Decimal
from pathlib import Path

VERSION = 'k120-estimate-1.3-v1'
MULTIPLIER = Decimal('1.3')
METADATA_KEYS = ('strategy', 'reservationPolicy', 'customerSettlementPolicy',
    'userEstimatedUsd', 'customerReservedUsd', 'reservationMultiplier',
    'providerUpperBoundUsd', 'reservationEstimateBasis', 'reservationEstimateSamples',
    'reservationInputTokens', 'reservationOutputTokens')


def _positive(value, default=0.):
    try:
        number=float(value)
        return number if math.isfinite(number) and number>=0 else default
    except (ValueError, TypeError):return default


def _texts(messages):
    for message in messages or []:
        if not isinstance(message,dict):continue
        content=message.get('content')
        if isinstance(content,str):yield content
        elif isinstance(content,list):
            for part in content:
                if isinstance(part,dict) and part.get('type') in ('text','input_text') and isinstance(part.get('text'),str):
                    yield part['text']


def _past(provider):
    # One bounded disk read per run; newly settled requests are read from memory.
    if not hasattr(provider,'_k120_reservation_history'):
        records=[]
        folder=Path(provider.folder)/'usage'
        paths=sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:128]
        for path in paths:
            if path==getattr(provider,'ledger_path',None):continue
            try:
                ledger=json.loads(path.read_text())
                if ledger.get('model')==provider.model:
                    records.extend(row for row in ledger.get('requests',[]) if isinstance(row,dict))
            except (OSError,ValueError,TypeError,AttributeError):continue
        provider._k120_reservation_history=records
    return [*provider._k120_reservation_history,*provider.ledger.get('requests',[])]


def _samples(provider,entry,rates):
    samples=[]
    for row in _past(provider):
        if (row.get('state')!='settled' or row.get('strategy') not in ('newest-k1-1-3','newest-k1-2-2')
                or row.get('kind')!=entry.get('kind')
                or row.get('studyTeachingIdentity')!=entry.get('studyTeachingIdentity')
                or row.get('requestedServiceTier')!=entry.get('requestedServiceTier')):continue
        usage=row.get('usage') or {}
        if not isinstance(usage,dict):continue
        input_tokens=_positive(usage.get('prompt_tokens',usage.get('input_tokens')))
        output_tokens=_positive(usage.get('completion_tokens',usage.get('output_tokens')))
        usd=_positive(row.get('estimatedUsd'))
        # Refused/cancelled/truncated responses cannot calibrate a full lesson.
        if input_tokens<=0 or output_tokens<=0 or usd<=0:continue
        terminal=row.get('serverTerminalStatus')
        if (terminal!='completed' if terminal is not None else row.get('finishReason')!='stop'):continue
        if row.get('finishReason') not in (None,'stop') or row.get('responseStatus') in ('failed','cancelled','incomplete'):continue
        basic=(input_tokens*rates[0]+output_tokens*rates[1])/1_000_000
        if basic>0:samples.append({'usd':usd,'ratio':usd/basic,'payloadHash':row.get('payloadHash')})
    return samples


def estimate(provider,entry,*,payload=None,messages=None,max_output=None):
    """Return whitelisted metadata; callers do not change reservedUsd or max_output."""
    if entry.get('strategy')!='newest-k1-2-2':return {}
    from pdf_ai import PRICES
    from pdf_newest_k1_2_0_cost import text_tokens
    rates=PRICES[provider.model]
    bound=_positive(entry.get('reservedUsd'))
    maximum=_positive(max_output if max_output is not None else entry.get('maxOutputTokens'),18000)
    texts=list(_texts(messages))
    image_bound=_positive(entry.get('imageInputTokenEstimate'))
    byte_text=sum(len(text.encode('utf-8')) for text in texts)
    overhead=max(0.,_positive(entry.get('inputTokenBound'))-image_bound-byte_text)
    input_tokens=sum(text_tokens(text) for text in texts)+overhead*.28
    if not texts:input_tokens=max(0.,_positive(entry.get('inputTokenBound'))-image_bound)*.36
    images=entry.get('imageDimensions') or []
    visual_tokens=0.
    for shape in images:
        if isinstance(shape,(list,tuple)) and len(shape)==2:
            width,height=map(_positive,shape)
            visual_tokens+=min(math.ceil(width/32)*math.ceil(height/32),1536)*2.46
    input_tokens+=visual_tokens if images else image_bound
    payload=payload if isinstance(payload,dict) else {}
    kind=entry.get('kind')
    if kind=='region_study':
        blocks=payload.get('blocks') or []
        if not isinstance(blocks,list):blocks=[]
        source=sum(text_tokens(str(b.get('text') or '')) for b in blocks if isinstance(b,dict))
        output_tokens=min(maximum,500+source*1.1+len(images)*350+len(blocks)*60)
    elif kind=='region_plan':
        fragments=payload.get('targets') or payload.get('fragments') or []
        output_tokens=min(maximum,80+100*len(fragments)) if isinstance(fragments,list) and fragments else min(maximum,2000)
    elif kind=='summary_reduce':output_tokens=min(maximum,250)
    else:output_tokens=min(maximum,2400)
    tier=2 if entry.get('requestedServiceTier')=='fast' else .5 if entry.get('requestedServiceTier')=='flex' else 1
    # Use the same local workload proxy as the displayed estimate. Cold requests
    # include the known explicit-cache-write premium, not an assumed cache hit.
    prior=(input_tokens*rates[0]*1.25+output_tokens*rates[1])/1_000_000*tier
    samples=_samples(provider,entry,rates)
    exact=[sample['usd'] for sample in samples if sample['payloadHash']==entry.get('payloadHash') and entry.get('payloadHash')]
    basis='local_request_workload'
    if exact:
        predicted=statistics.median(exact);basis='same_payload_confirmed_usage'
    elif len(samples)>=3:
        ratio=min(2.5,max(.1,statistics.median(s['ratio'] for s in samples[-100:])))
        predicted=(input_tokens*rates[0]+output_tokens*rates[1])/1_000_000*ratio
        basis='local_request_workload_with_confirmed_usage'
    else:predicted=prior
    # The prediction can never claim greater actual usage than the existing upper
    # bound. The 30% customer margin remains an exact separate multiplication.
    predicted=min(bound,max(0.,predicted)) if bound>0 else 0.
    estimated=Decimal(str(round(predicted,10)))
    reserved=estimated*MULTIPLIER
    return {'strategy':'newest-k1-2-2','reservationPolicy':VERSION,
        'customerSettlementPolicy':'available-balance-v1',
        'userEstimatedUsd':float(estimated),'customerReservedUsd':float(reserved),
        'reservationMultiplier':float(MULTIPLIER),'providerUpperBoundUsd':bound,
        'reservationEstimateBasis':basis,'reservationEstimateSamples':len(exact) if exact else len(samples),
        'reservationInputTokens':round(input_tokens),'reservationOutputTokens':round(output_tokens)}


def metadata(value):
    """Billing accepts only explicit K1.2.0 policy metadata, never arbitrary keys."""
    if (not isinstance(value,dict) or value.get('strategy')!='newest-k1-2-2'
            or value.get('reservationPolicy')!=VERSION
            or value.get('customerSettlementPolicy')!='available-balance-v1'):return {}
    return {key:value[key] for key in METADATA_KEYS if key in value}
