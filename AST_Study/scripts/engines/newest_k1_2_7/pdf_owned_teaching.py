"""Make table/flow ownership structural on the wire, preserving canonical replies.

This adapter changes no prose, source reference, equation or validation rule.
The provider's strict schema validates content fields; ordinary source decoding
and study checks still run after this ownership-only decoding step.
"""
from __future__ import annotations

import copy

VERSION = 'owned-teaching-wire-v1'
OWNED_OUTPUT = '''
OWNED OUTPUT: Put tables and sequences INSIDE the concept that teaches them.
Each concept requires tables and sequences arrays, empty when not applicable.
Do not output root tables/sequences or a nested conceptTitle: ownership is the
parent concept itself. Preserve every readable source pairing, number, condition
and route; nesting changes ownership only, never the teaching scope.
'''


class OwnedTeachingError(ValueError):
    """The wire format cannot express an unambiguous ownership conversion."""


def _object(value, where):
    if not isinstance(value, dict):
        raise OwnedTeachingError(f'{where} must be an object.')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise OwnedTeachingError(f'{where} must be an array.')
    return value


def _strict_object(schema, where):
    schema = _object(schema, where)
    properties = _object(schema.get('properties'), where+'.properties')
    required = _array(schema.get('required'), where+'.required')
    if (schema.get('type') != 'object' or schema.get('additionalProperties') is not False
            or any(not isinstance(k, str) for k in required)
            or len(required) != len(set(required)) or set(required) != set(properties)):
        raise OwnedTeachingError(f'{where} must be a strict object with all properties required.')
    return properties


def encode_format(wire_format):
    """Return an independent strict schema with concept-owned tables and flows."""
    original = _object(wire_format, 'format')
    if original.get('type') != 'json_schema':
        raise OwnedTeachingError('format must use json_schema.')
    value = copy.deepcopy(original)
    contract = _object(value.get('json_schema'), 'format.json_schema')
    if contract.get('strict') is not True:
        raise OwnedTeachingError('format.json_schema must be strict.')
    schema = _object(contract.get('schema'), 'format.json_schema.schema')
    root = _strict_object(schema, 'response schema')
    concepts = _object(root.get('concepts'), 'concepts schema')
    if concepts.get('type') != 'array':
        raise OwnedTeachingError('concepts schema must be an array.')
    concept_schema = _object(concepts.get('items'), 'concepts.items schema')
    concept = _strict_object(concept_schema, 'concept schema')
    if 'title' not in concept or any(name in concept for name in ('tables', 'sequences')):
        raise OwnedTeachingError('concept schema is missing a title or is already owner-encoded.')
    for name in ('tables', 'sequences'):
        nested = copy.deepcopy(_object(root.get(name), name+' schema'))
        if nested.get('type') != 'array':
            raise OwnedTeachingError(name+' schema must be an array.')
        item = _object(nested.get('items'), name+'.items schema')
        fields = _strict_object(item, name+'.items schema')
        if 'conceptTitle' not in fields:
            raise OwnedTeachingError(name+' schema needs an explicit owner before encoding.')
        del fields['conceptTitle']
        item['required'] = [key for key in item['required'] if key != 'conceptTitle']
        concept[name] = nested
        concept_schema['required'] = [*concept_schema['required'], name]
        del root[name]
    schema['required'] = [key for key in schema['required'] if key not in ('tables', 'sequences')]
    return value


def decode(raw):
    """Flatten a new owned wire reply before source-alias decoding and caching.

    Reject ambiguous root ownership and malformed ownership containers. Existing
    concept metadata/content is copied verbatim, leaving its semantic and source
    validation to the unchanged canonical pipeline.
    """
    _object(raw, 'response')
    expected = {'concepts', 'excludedBlocks', 'uncertainBlocks'}
    if set(raw) != expected:
        raise OwnedTeachingError('Owned response has missing or unknown root fields.')
    for name in expected:
        _array(raw[name], name)
    value = copy.deepcopy(raw)
    tables, sequences = [], []
    for concept in value['concepts']:
        _object(concept, 'concepts[]')
        title = concept.get('title')
        if not isinstance(title, str) or not title.strip():
            raise OwnedTeachingError('Every concept must have a non-empty title.')
        for name, collected in (('tables', tables), ('sequences', sequences)):
            for item in _array(concept.pop(name, None), 'concepts.'+name):
                _object(item, 'concepts.'+name+'[]')
                if 'conceptTitle' in item:
                    raise OwnedTeachingError('An owned item cannot supply its own conceptTitle.')
                required = ('headers', 'rows', 'blockIds') if name == 'tables' else ('title', 'steps')
                if any(key not in item for key in required):
                    raise OwnedTeachingError('An owned '+name+' item is incomplete.')
                if name == 'tables':
                    for key in required:
                        _array(item[key], 'tables.'+key)
                    for row in item['rows']:
                        _array(row, 'tables.rows[]')
                else:
                    if not isinstance(item['title'], str):
                        raise OwnedTeachingError('A sequence title must be a string.')
                    for step in _array(item['steps'], 'sequences.steps'):
                        _object(step, 'sequences.steps[]')
                collected.append({'conceptTitle': title, **item})
    value['tables'], value['sequences'] = tables, sequences
    return value
