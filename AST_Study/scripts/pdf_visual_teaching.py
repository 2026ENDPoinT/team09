"""Job-local visual-owned output slots for a single teaching response.

This is a wire adapter, not another model/review stage. It copies the supplied
canonical schema and never rewrites source text, learner prose, math, or code.
Decode only fresh provider replies before the unchanged canonical validation.
"""
from __future__ import annotations

import copy

from pdf_owned_teaching import (OwnedTeachingError, encode_format as encode_owned,
                               decode as decode_owned)
from pdf_visual_selection import substantive_visual

VERSION = 'visual-teaching-wire-v2'
FIELDS = ('concepts', 'sequences', 'tables', 'excludedBlocks', 'uncertainBlocks')
RULES = '''
VISUAL-OWNED OUTPUT: visualTeaching has one required slot per substantial target
figure ID. Read that figure and put its learner concepts, routes and tables in
its own slot, using only that slot's source ID. Teach the figure's visible
connections and destinations, not just adjacent prose that names the same organs.
WITHIN EACH VISUAL SLOT, put tables and sequences INSIDE the concept that teaches
them; every visual concept has both arrays, empty when inapplicable. A visual
table/sequence cannot be emitted without its owning concept. A visual slot has
only concepts, excludedBlocks and uncertainBlocks, not slot-root tables/sequences.
Keep the root arrays for native/non-substantial targets only. Do not duplicate
visual teaching in root arrays or another figure slot. Preserve all source text,
equations and code; never invent unreadable content. Use the existing uncertainty
or exclusion arrays in the owning slot when appropriate.
'''


class VisualTeachingError(ValueError):
    """A visual slot, target set, or citation cannot be decoded unambiguously."""


def _object(value, where):
    if not isinstance(value, dict):
        raise VisualTeachingError(f'{where} must be an object.')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise VisualTeachingError(f'{where} must be an array.')
    return value


def _strict_fields(schema, where):
    schema = _object(schema, where)
    fields = _object(schema.get('properties'), where+'.properties')
    required = _array(schema.get('required'), where+'.required')
    if (schema.get('type') != 'object' or schema.get('additionalProperties') is not False
            or any(not isinstance(key, str) for key in required)
            or len(required) != len(set(required)) or set(required) != set(fields)):
        raise VisualTeachingError(f'{where} must require every property strictly.')
    return fields


def _target_sets(job):
    ids, visual = [], []
    for block in _array(_object(job, 'job').get('blocks'), 'job.blocks'):
        block = _object(block, 'job.blocks[]')
        source = block.get('id')
        if not isinstance(source, str) or not source or source in ids:
            raise VisualTeachingError('Job targets need unique, non-empty source IDs.')
        ids.append(source)
        if substantive_visual(block):
            visual.append(source)
    return ids, visual, [source for source in ids if source not in visual]


def _narrow_citations(fields, allowed):
    """Detach only canonical citation properties, preserving all content schema.

    sourceSetup may be a recursive experimental facts schema. Keep its content
    shape intact; narrow only its explicit structured citation properties too.
    """
    reference = {'type': 'string', 'enum': list(allowed)}

    def narrow(record, plural):
        props = _object(_object(record, 'citation schema').get('properties'),
                        'citation schema.properties')
        field = 'blockIds' if plural else 'blockId'
        if field not in props:
            raise VisualTeachingError('Canonical citation schema is incomplete.')
        if plural:
            value = copy.deepcopy(_object(props[field], 'blockIds schema'))
            if value.get('type') != 'array':
                raise VisualTeachingError('blockIds schema must be an array.')
            value['items'] = copy.deepcopy(reference)
            value['minItems'] = max(1, value.get('minItems', 0))
        else:
            value = copy.deepcopy(reference)
        props[field] = value

    concepts = _object(fields['concepts'].get('items'), 'concepts.items')
    concept_fields = _object(concepts.get('properties'), 'concepts.items.properties')
    narrow(_object(concept_fields['segments'].get('items'), 'segments.items'), True)

    def setup_citations(node):
        if isinstance(node, dict):
            props = node.get('properties', {})
            if isinstance(props, dict):
                if 'blockId' in props:
                    narrow(node, False)
                if 'blockIds' in props:
                    narrow(node, True)
            for child in node.values():
                setup_citations(child)
        elif isinstance(node, list):
            for child in node:
                setup_citations(child)

    setup_citations(concept_fields.get('sourceSetup'))
    narrow(_object(fields['tables'].get('items'), 'tables.items'), True)
    sequences = _object(fields['sequences'].get('items'), 'sequences.items')
    sequence_fields = _object(sequences.get('properties'), 'sequences.items.properties')
    narrow(_object(sequence_fields['steps'].get('items'), 'sequences.steps.items'), True)
    for name in ('excludedBlocks', 'uncertainBlocks'):
        narrow(_object(fields[name].get('items'), name+'.items'), False)


def encode_format(wire_format, job):
    """Return ``(independent_format, ownership)``; ownership is None if unused.

    The input must be the canonical format already constrained to these job IDs.
    No-visual jobs use the supplied schema unchanged. Substantial visuals have
    required keyed slots in original job order; the remaining root arrays own
    only native/non-substantial targets. Empty native sets force empty root arrays.
    """
    ids, visual, native = _target_sets(job)
    value = copy.deepcopy(_object(wire_format, 'format'))
    if not visual:
        return value, None
    if value.get('type') != 'json_schema':
        raise VisualTeachingError('format must use json_schema.')
    contract = _object(value.get('json_schema'), 'format.json_schema')
    if contract.get('strict') is not True:
        raise VisualTeachingError('format.json_schema must be strict.')
    schema = _object(contract.get('schema'), 'format.json_schema.schema')
    fields = _strict_fields(schema, 'response schema')
    if set(fields) != set(FIELDS):
        raise VisualTeachingError('Expected the five canonical teaching arrays.')
    definition = _object(_object(schema.get('$defs'), 'schema.$defs').get('studySourceId'),
                         'schema.$defs.studySourceId')
    source_ids = definition.get('enum')
    if (not isinstance(source_ids, list) or any(not isinstance(x, str) for x in source_ids)
            or len(source_ids) != len(ids) or set(source_ids) != set(ids)):
        raise VisualTeachingError('Source enum must match the complete canonical job.')
    template = {name: copy.deepcopy(fields[name]) for name in FIELDS}
    for name in FIELDS:
        if _object(template[name], name+' schema').get('type') != 'array':
            raise VisualTeachingError('Canonical teaching fields must be arrays.')
    slots = {}
    for source in visual:
        slot_fields = copy.deepcopy(template)
        _narrow_citations(slot_fields, [source])
        slot_format = copy.deepcopy(value)
        slot_format['json_schema']['schema'] = {
            'type': 'object', 'properties': slot_fields, 'required': list(FIELDS),
            'additionalProperties': False,
            '$defs': copy.deepcopy(schema.get('$defs', {}))}
        owned_schema = encode_owned(slot_format)['json_schema']['schema']
        # $refs in the unchanged content/facts schema resolve at the common root.
        # Slot-local duplicated definitions are unnecessary and can be rejected
        # by strict providers that only admit definitions at the response root.
        owned_schema.pop('$defs', None)
        slots[source] = owned_schema
    if native:
        _narrow_citations(fields, native)
    else:
        for name in FIELDS:
            # An empty enum is invalid JSON Schema for some strict providers.
            # maxItems=0 makes the item schema unreachable without changing it.
            fields[name] = {**copy.deepcopy(fields[name]), 'maxItems': 0}
    fields['visualTeaching'] = {'type': 'object', 'properties': slots,
                                'required': list(visual), 'additionalProperties': False}
    schema['required'] = [*schema['required'], 'visualTeaching']
    ownership = {'version': VERSION, 'visualIds': tuple(visual), 'nativeIds': tuple(native)}
    return value, ownership


def _ownership(value):
    value = _object(value, 'ownership')
    if set(value) != {'version', 'visualIds', 'nativeIds'} or value['version'] != VERSION:
        raise VisualTeachingError('Unknown ownership contract.')
    ids = []
    for name in ('visualIds', 'nativeIds'):
        values = value[name]
        if (not isinstance(values, (tuple, list))
                or any(not isinstance(source, str) or not source for source in values)):
            raise VisualTeachingError('Ownership IDs must be ordered source strings.')
        ids.extend(values)
    if not value['visualIds'] or len(set(ids)) != len(ids):
        raise VisualTeachingError('Ownership sets must be nonempty and disjoint.')
    return list(value['visualIds']), list(value['nativeIds'])


def _validate_citations(container, allowed, where):
    if set(_object(container, where)) != set(FIELDS):
        raise VisualTeachingError(f'{where} has missing or unknown teaching arrays.')
    for name in FIELDS:
        _array(container[name], where+'.'+name)

    def citation(record, plural, label):
        record = _object(record, label)
        field = 'blockIds' if plural else 'blockId'
        if field not in record:
            raise VisualTeachingError(f'{label} is missing its citation.')
        ids = _array(record[field], label+'.'+field) if plural else [record[field]]
        if not ids or any(not isinstance(source, str) or source not in allowed for source in ids):
            raise VisualTeachingError(f'{label} has an unknown or different owner citation.')

    for concept in container['concepts']:
        concept = _object(concept, where+'.concepts[]')
        if 'blockIds' in concept:
            citation(concept, True, where+'.concepts[]')
        for segment in _array(concept.get('segments'), where+'.segments'):
            citation(segment, True, where+'.segments[]')

        def setup_citations(node):
            if isinstance(node, dict):
                if 'blockIds' in node:
                    citation(node, True, where+'.sourceSetup')
                if 'blockId' in node:
                    citation(node, False, where+'.sourceSetup')
                for child in node.values():
                    setup_citations(child)
            elif isinstance(node, list):
                for child in node:
                    setup_citations(child)

        setup_citations(concept.get('sourceSetup'))
    for table in container['tables']:
        citation(table, True, where+'.tables[]')
    for sequence in container['sequences']:
        sequence = _object(sequence, where+'.sequences[]')
        if 'blockIds' in sequence:
            citation(sequence, True, where+'.sequences[]')
        for step in _array(sequence.get('steps'), where+'.sequences.steps'):
            citation(step, True, where+'.sequences.steps[]')
    for name in ('excludedBlocks', 'uncertainBlocks'):
        for record in container[name]:
            citation(record, False, where+'.'+name+'[]')


def decode(raw, ownership):
    """Flatten explicit visual owners; never repair or infer source references.

    Empty slots remain empty so normal canonical checks keep unread teaching
    pending. The slot contract prevents omitted keys, not semantic omissions.
    """
    if ownership is None:
        return copy.deepcopy(raw)
    visual, native = _ownership(ownership)
    _object(raw, 'response')
    if set(raw) != {*FIELDS, 'visualTeaching'}:
        raise VisualTeachingError('Response has missing or unknown root fields.')
    slots = _object(raw['visualTeaching'], 'visualTeaching')
    if set(slots) != set(visual):
        raise VisualTeachingError('Missing or unknown visual owner keys.')
    root = {name: raw[name] for name in FIELDS}
    _validate_citations(root, set(native), 'root')
    if not native and any(root[name] for name in FIELDS):
        raise VisualTeachingError('Root teaching must be empty without native targets.')
    decoded_slots = {}
    for source in visual:
        # Ownership is provider-selected structurally, never inferred from a
        # title or fabricated after an orphan table has failed validation.
        try:
            decoded_slots[source] = decode_owned(slots[source])
        except OwnedTeachingError as error:
            raise VisualTeachingError('Invalid concept-owned visual slot: '+str(error)) from error
        _validate_citations(decoded_slots[source], {source}, 'visualTeaching slot')
    value = copy.deepcopy(root)
    for source in visual:
        for name in FIELDS:
            value[name].extend(copy.deepcopy(decoded_slots[source][name]))
    return value
