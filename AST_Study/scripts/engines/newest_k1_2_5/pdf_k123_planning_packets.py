"""Coarser planning input; teaching keeps exact original text, IDs and crops."""
import copy
import hashlib
import json
import re

VERSION='k123-planning-packets-v1'


def members(block):return block.get('_planningSources',[block])


def bounds(items):
    return [min(b['bbox'][0]for b in items),min(b['bbox'][1]for b in items),
            max(b['bbox'][2]for b in items),max(b['bbox'][3]for b in items)]


def joins(left,right):
    if (left['page'],left.get('zone'),left.get('headingId'))!=(right['page'],right.get('zone'),right.get('headingId')):return False
    if left.get('localRole')or right.get('localRole')or right.get('kind')=='heading':return False
    if any(b.get('geometryFallback')or b.get('pageEdgeClipped')for b in (left,right)):return False
    if re.match(r'^\s*(?:▶|\(?문제\s*\d|\(?예제\s*\d|\(?example\s*\d|\(?problem\s*\d)',right.get('text',''),re.I):return False
    a,b=left['bbox'],right['bbox'];gap=b[1]-a[3]
    overlap=min(a[2],b[2])-max(a[0],b[0]);width=min(a[2]-a[0],b[2]-b[0])
    return (width>0 and overlap>=width*.65 and -.005<=gap<=.105
        and bounds([left,right])[3]-bounds([left,right])[1]<=.55
        and len(left.get('text',''))+len(right.get('text',''))<=2400)


def merge(a,b):
    value=copy.deepcopy(a);children=copy.deepcopy(members(a)+members(b))
    key=hashlib.sha256(json.dumps([x['id']for x in children]).encode()).hexdigest()[:20]
    value.update(id='pp'+key,text='\n'.join(x['text']for x in (a,b)if x.get('text')),
        bbox=bounds([a,b]),kind='text',_planningSources=children,
        hasVisual=bool(a.get('hasVisual')or b.get('hasVisual')))
    value['visualOnly']=not bool(value['text'].strip())
    value.pop('nativeTextProof',None)
    return value


def pack(targets):
    packets=[]
    for block in targets:
        if packets and joins(packets[-1],block):packets[-1]=merge(packets[-1],block)
        else:
            packet=copy.deepcopy(block)
            packet['_planningSources']=[copy.deepcopy(block)]
            packets.append(packet)
    originals=[b for packet in packets for b in members(packet)]
    if originals!=targets:raise ValueError('Planning packets lost or changed original sources')
    mapping={b['id']:p['id']for p in packets for b in members(p)}
    for packet in packets:
        heading=packet.get('headingId')
        if heading in mapping:packet['headingId']=mapping[heading]
    return packets


def fragment(packet,original_fragment):
    value=original_fragment(packet)
    headings=[b['text']for b in members(packet)if b.get('kind')=='heading']
    if headings:value['containedHeadings']=headings
    return value


def recover(raw,packets,targets):
    from pdf_group_partition import recover_ranges
    value,audit=recover_ranges(raw,packets)
    lookup={p['id']:[b['id']for b in members(p)]for p in packets}
    for group in value['groups']:
        group['blockIds']=[key for packet_id in group['blockIds']for key in lookup[packet_id]]
    # Gaps, overlaps and invalid ranges remain visible to repair_partition on the
    # full original target set. No guessed assignment is promoted to a model plan.
    audit.update(planningPacketPolicy=VERSION,planningTargetCount=len(packets),
                 sourceTargetCount=len(targets),originalTargetsPreserved=True)
    return value,audit
