"""Lossless, job-local source IDs for the teaching request wire format.

Only structured source references are encoded/decoded. Source text, model prose,
math/code, headings, and canonical on-disk replies are never searched/replaced.
Decode only a newly returned provider reply, before caching it canonically.
"""
from __future__ import annotations

import copy
import re

from pdf_study_cache_reuse import constrained_format


class SourceAliasError(ValueError):
    """A source mapping or structured reference cannot be resolved uniquely."""


def bucket_pool_size(count, minimum=32):
    """Choose a positive power-of-two schema pool without truncating targets."""
    if type(count) is not int or count<1 or type(minimum) is not int or minimum<1:
        raise SourceAliasError('Source count and minimum pool size must be positive integers.')
    return 1 << (max(count, minimum)-1).bit_length()


def _alias(index):
    """Zero-based bijective base 26: a..z, aa..az, ba..zz, aaa..."""
    result = ''
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(ord('a') + digit) + result
    return result


def _mapping(mapping):
    if not isinstance(mapping, dict) or not mapping:
        raise SourceAliasError('A non-empty source alias mapping is required.')
    if any(not isinstance(alias, str) or not re.fullmatch('[a-z]+', alias)
           or not isinstance(source, str) or not source for alias, source in mapping.items()):
        raise SourceAliasError('Aliases and canonical source IDs must be non-empty strings.')
    if len(set(mapping.values())) != len(mapping):
        raise SourceAliasError('Multiple aliases refer to the same canonical source.')
    if any(source in mapping and mapping[source] != source for source in mapping.values()):
        raise SourceAliasError('Canonical source IDs overlap ambiguously with wire aliases.')
    return dict(mapping)


def _object(value, where):
    if not isinstance(value, dict):
        raise SourceAliasError(f'{where} must be an object.')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise SourceAliasError(f'{where} must be an array.')
    return value


def _reference(value, mapping, where):
    if not isinstance(value, str) or value not in mapping:
        # Do not include source/prose values in an exception or provider log.
        raise SourceAliasError(f'{where} contains an unknown source reference.')
    return mapping[value]


def _references(value, mapping, where):
    return [_reference(source, mapping, where) for source in _array(value, where)]


def encode(payload, format, job, *, stable_pool_size=None, alias_prefix=''):
    """Return independent ``(wire_payload, wire_format, alias_to_canonical)``.

    Job block order fixes the aliases. Every target must occur exactly once in
    payload.blocks; hints/crops may refer only to those targets. An already
    constrained schema must refer to precisely the same canonical sources.

    An optional experimental fixed schema pool contains unused alias spellings,
    never additional sources. The returned mapping remains limited to the real
    job, so decode rejects every unused pool member rather than guessing an ID.
    An optional lowercase ASCII prefix gives independent units disjoint wire
    namespaces. Its empty default preserves every existing alias and schema.
    """
    _object(payload, 'payload')
    _object(format, 'format')
    _object(job, 'job')
    if not isinstance(alias_prefix, str) or re.fullmatch('[a-z]*', alias_prefix) is None:
        raise SourceAliasError('The alias prefix must contain only lowercase ASCII letters.')
    targets = _array(job.get('blocks'), 'job.blocks')
    ids = []
    for block in targets:
        source = _object(block, 'job.blocks[]').get('id')
        if not isinstance(source, str) or not source or source in ids:
            raise SourceAliasError('Job targets must have unique, non-empty source IDs.')
        ids.append(source)
    mapping = _mapping({alias_prefix+_alias(index): source for index, source in enumerate(ids)})
    if stable_pool_size is not None and (type(stable_pool_size) is not int
            or stable_pool_size<len(ids)):
        raise SourceAliasError('The stable alias pool must fit every actual job target.')
    forward = {source: alias for alias, source in mapping.items()}
    wire = copy.deepcopy(payload)
    blocks = _array(wire.get('blocks'), 'payload.blocks')
    supplied = [_object(block, 'payload.blocks[]').get('id') for block in blocks]
    if (len(supplied) != len(ids) or any(not isinstance(source, str) for source in supplied)
            or len(set(supplied)) != len(ids) or set(supplied) != set(ids)):
        raise SourceAliasError('Payload targets must match all job targets exactly once.')
    for block in blocks:
        block['id'] = forward[block['id']]
    for hint in _array(wire.get('entryHints', []), 'payload.entryHints'):
        _object(hint, 'payload.entryHints[]')
        hint['startsAt'] = _reference(hint.get('startsAt'), forward, 'entryHints.startsAt')
    for crop in _array(wire.get('crops', []), 'payload.crops'):
        _object(crop, 'payload.crops[]')
        crop['blockIds'] = _references(crop.get('blockIds'), forward, 'crops.blockIds')
    for check in _array(wire.get('sourceConditionChecks', []), 'payload.sourceConditionChecks'):
        _object(check, 'payload.sourceConditionChecks[]')
        check['blockId'] = _reference(check.get('blockId'), forward, 'sourceConditionChecks.blockId')
    for check in _array(wire.get('sourceConnectionChecks', []), 'payload.sourceConnectionChecks'):
        _object(check, 'payload.sourceConnectionChecks[]')
        check['blockIds'] = _references(check.get('blockIds'), forward, 'sourceConnectionChecks.blockIds')
    schema = _object(_object(format.get('json_schema'), 'format.json_schema').get('schema'),
                     'format.json_schema.schema')
    definitions = _object(schema.get('$defs', {}), 'format.schema.$defs')
    if 'studySourceId' in definitions:
        previous = _object(definitions['studySourceId'], 'studySourceId').get('enum')
        if (not isinstance(previous, list) or any(not isinstance(source, str) for source in previous)
                or len(previous) != len(ids) or set(previous) != set(ids)):
            raise SourceAliasError('Existing source enum does not match the complete job.')
    wire_format = constrained_format(format, {'blocks': [{'id': alias} for alias in mapping]})
    if stable_pool_size is not None:
        wire_format['json_schema']['schema']['$defs']['studySourceId']['enum'] = [
            alias_prefix+_alias(index) for index in range(stable_pool_size)]
    return wire, wire_format, mapping


def decode(raw, mapping):
    """Restore source references in a *new wire reply*, leaving all prose intact.

    Missing/malformed citation fields in present segments, tables, sequence steps
    or transition/exclusion records are errors. Empty lists are preserved for the normal
    study validator; this transport helper never invents or drops a citation.
    """
    mapping = _mapping(mapping)
    _object(raw, 'response')
    from pdf_saved_teaching_compat import processing_records
    value,_ = processing_records(raw,mapping)

    def records(container, name):
        return [_object(item, name + '[]')
                for item in _array(container.get(name, []), name)]

    for concept in records(value, 'concepts'):
        # The legacy concept reference slot is also structured data, never text.
        if 'blockIds' in concept:
            concept['blockIds'] = _references(concept['blockIds'], mapping, 'concepts.blockIds')
        for segment in records(concept, 'segments'):
            segment['blockIds'] = _references(segment.get('blockIds'), mapping, 'segments.blockIds')
        if 'learning' in concept:
            learning=_object(concept['learning'],'concepts.learning')
            for relation in records(learning,'relations'):
                relation['blockIds']=_references(relation.get('blockIds'),mapping,'learning.relations.blockIds')
    for table in records(value, 'tables'):
        table['blockIds'] = _references(table.get('blockIds'), mapping, 'tables.blockIds')
    for sequence in records(value, 'sequences'):
        if 'blockIds' in sequence:
            sequence['blockIds'] = _references(sequence['blockIds'], mapping, 'sequences.blockIds')
        for step in records(sequence, 'steps'):
            step['blockIds'] = _references(step.get('blockIds'), mapping, 'sequences.steps.blockIds')
        for transition in records(sequence, 'transitions'):
            transition['blockIds'] = _references(transition.get('blockIds'), mapping,
                                                'sequences.transitions.blockIds')
    for item in records(value,'diagnostics'):
        item['blockIds']=_references(item.get('blockIds'),mapping,'diagnostics.blockIds')
    for unit in records(value,'lectureUnits'):
        bridge=_object(unit.get('bridge'),'lectureUnits.bridge')
        bridge['blockIds']=_references(bridge.get('blockIds'),mapping,'lectureUnits.bridge.blockIds')
    for field in ('uncertainBlocks', 'excludedBlocks'):
        for record in records(value, field):
            record['blockId'] = _reference(record.get('blockId'), mapping, field + '.blockId')
    for record in records(value,'sourceCoverage'):
        record['blockId']=_reference(record.get('blockId'),mapping,'sourceCoverage.blockId')
    return value
