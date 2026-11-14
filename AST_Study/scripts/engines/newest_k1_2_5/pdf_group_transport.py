"""Lossless compact transport for contiguous semantic grouping; no extra model pass."""
import copy

from pdf_response_schema import _object

VERSION = 'contiguous-ranges-v1'
RANGE_FORMAT = {'type':'json_schema','json_schema':{'name':'pdf_topic_ranges_v1','strict':True,
    'schema':_object({'groups':{'type':'array','items':_object({
        'title':{'type':'string'},'first':{'type':'integer'},'last':{'type':'integer'},
        'role':{'type':'string','enum':['teaching','illustration','exercise','navigation','uncertain']},
        'continuesPrevious':{'type':'boolean'}})}})}}


def request(targets, before, after, fragment):
    """Local indices replace repeated source IDs only on the wire."""
    mapping = {b['id']:i for i,b in enumerate(before+targets+after)}
    def item(block, target=False):
        value = fragment(block)
        value['id'] = mapping[block['id']]
        if value.get('headingId') in mapping:
            value['headingId'] = mapping[value['headingId']]
        if target:
            value['index'] = targets.index(block)
        return value
    return {'task':'region_groups','targets':[item(b,True) for b in targets],
            'before':[item(b) for b in before],'after':[item(b) for b in after]}


def expand(raw, targets):
    """Reject gaps, overlaps, invalid indices, and context assignments before save."""
    from pdf_ai import AiResponseError
    if not isinstance(raw,dict) or not isinstance(raw.get('groups'),list):
        raise AiResponseError('묶음 범위 응답 형식이 올바르지 않아요. 받은 응답은 보존했어요.')
    result = copy.deepcopy(raw)
    cursor = 0
    for group in result['groups']:
        if not isinstance(group,dict):
            raise AiResponseError('묶음 범위 응답 형식이 올바르지 않아요.')
        first,last = group.pop('first',None),group.pop('last',None)
        if (type(first) is not int or type(last) is not int or first != cursor
                or not first <= last < len(targets)):
            raise AiResponseError('묶음 범위에 누락이나 중복이 있어요. 받은 응답은 보존했어요.')
        group['blockIds'] = [b['id'] for b in targets[first:last+1]]
        cursor = last+1
    if cursor != len(targets):
        raise AiResponseError('묶음 범위의 원문 배정이 완료되지 않았어요. 받은 응답은 보존했어요.')
    return result


def prompt(original):
    return original + '''
COMPACT TRANSPORT CONTRACT (overrides ID-list output wording only)
Each target has a zero-based index. Output first and last inclusive TARGET indices
for each contiguous group, rather than blockIds. Partition indices 0 through the last
target exactly once, in increasing order, with no gaps or overlaps. Before/after are
context only and must not be assigned. Keep precisely the same semantic grouping,
instructional-role decisions and Korean titles. Do not change or shorten the teaching scope.
'''
