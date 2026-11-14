"""Bind observed source facts to learner paragraphs on the response wire.

Only the provider-facing schema changes. Decoding restores the canonical
sourceSetup and segments before the existing source/math/uncertainty checks.
No source text, citation, equation, code, boundary check or prose is rewritten.
"""
from __future__ import annotations

import copy


VERSION = 'source-facts-wire-v3'
SOURCE_FACTS_OUTPUT = '''
SOURCE FACT OUTPUT: sourceSetup.observedRelations is an array of objects with
learnerText and target blockIds. learnerText is the supported learner paragraph
that teaches ONLY the observed proposition, including its quantities, bounds,
variables and units. Do not summarize the other observations again in each fact.
It becomes an explanation directly, so do not leave an important observed fact
only in internal notes. Normal definition/explanation segments connect facts and
explain relationships or mechanisms; they must not retell dates, quantities or
stated purposes already taught by learnerText. Do not add another overview of
the same fact paragraphs. Keep every segment grounded in its cited target blocks.
Do not transcribe table cells here: put their readable pairings once in tables;
observations may explain the column meanings or an essential scope constraint.
Do not put uncertainty reasons or outside facts in learnerText. Preserve normal
boundaryChecks/interpretation and all existing source/uncertainty/math rules.
Do not output a second source transcription. The canonical internal observation
will reuse learnerText as a model-written supported statement, not a verbatim quote.
'''


class SourceFactsError(ValueError):
    """The fact wire structure cannot be decoded unambiguously."""


def _object(value, where):
    if not isinstance(value, dict):
        raise SourceFactsError(f'{where} must be an object.')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise SourceFactsError(f'{where} must be an array.')
    return value


def _strict_object(schema, where):
    schema = _object(schema, where)
    properties = _object(schema.get('properties'), where+'.properties')
    required = _array(schema.get('required'), where+'.required')
    if (schema.get('type') != 'object' or schema.get('additionalProperties') is not False
            or any(not isinstance(key, str) for key in required)
            or len(required) != len(set(required)) or set(required) != set(properties)):
        raise SourceFactsError(f'{where} must be a strict object with all fields required.')
    return properties


def encode_format(wire_format):
    """Copy a strict canonical schema and couple observations to learner text.

    Copy the existing segment citation schema verbatim, including job-local
    enums/$refs and their bounds. Other schema fields and definitions are intact.
    This can compose with source aliases and concept-owned tables in either order.
    """
    original = _object(wire_format, 'format')
    if original.get('type') != 'json_schema':
        raise SourceFactsError('format must use json_schema.')
    value = copy.deepcopy(original)
    contract = _object(value.get('json_schema'), 'format.json_schema')
    if contract.get('strict') is not True:
        raise SourceFactsError('format.json_schema must be strict.')
    schema = _object(contract.get('schema'), 'format.json_schema.schema')
    root = _strict_object(schema, 'response schema')
    concepts = _object(root.get('concepts'), 'concepts schema')
    if concepts.get('type') != 'array':
        raise SourceFactsError('concepts schema must be an array.')
    concept = _strict_object(concepts.get('items'), 'concept schema')
    setup = _strict_object(concept.get('sourceSetup'), 'sourceSetup schema')
    # Canonical schemas intentionally reuse small Python schema objects (SS/S).
    # Deepcopy preserves that alias graph, so detach this slot before editing it.
    relations = copy.deepcopy(_object(setup.get('observedRelations'), 'observedRelations schema'))
    setup['observedRelations'] = relations
    if (relations.get('type') != 'array'
            or _object(relations.get('items'), 'observedRelations.items').get('type') != 'string'):
        raise SourceFactsError('observedRelations must start as an array of strings.')
    segments = _object(concept.get('segments'), 'segments schema')
    if segments.get('type') != 'array':
        raise SourceFactsError('segments schema must be an array.')
    segment = _strict_object(segments.get('items'), 'segment schema')
    text = _object(segment.get('text'), 'segment text schema')
    block_ids = _object(segment.get('blockIds'), 'segment blockIds schema')
    if text.get('type') != 'string' or block_ids.get('type') != 'array':
        raise SourceFactsError('segments need string text and an array of blockIds.')
    relations['items'] = {
        'type': 'object',
        'properties': {
            'learnerText': copy.deepcopy(text),
            'blockIds': copy.deepcopy(block_ids),
        },
        'required': ['learnerText', 'blockIds'],
        'additionalProperties': False,
    }
    return value


def _references(value, where):
    values = _array(value, where)
    if not values or any(not isinstance(item, str) or not item for item in values):
        raise SourceFactsError(f'{where} needs non-empty source references.')
    # Unknown string IDs deliberately remain for the unchanged alias/source
    # validator to reject. This transport layer cannot assert source support.
    return values


def _segment_key(segment):
    """Exact text AND ordered source identity; no substring/prose normalization."""
    if segment.get('kind') != 'explanation':
        return None
    text, ids = segment.get('text'), segment.get('blockIds')
    if not isinstance(text, str) or not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
        return None
    return text, tuple(ids)


def decode(raw):
    """Return model-written observations plus directly cited explanations.

    Newly coupled paragraphs are inserted after definitions and before the first
    explanation/easy paragraph. Existing segments, tables and metadata are copied
    intact. Only an exact added explanation duplicate with the same ordered
    citations is suppressed; observations and all original segments are retained.
    """
    _object(raw, 'response')
    value = copy.deepcopy(raw)
    for concept in _array(value.get('concepts'), 'concepts'):
        _object(concept, 'concepts[]')
        setup = _object(concept.get('sourceSetup'), 'concepts.sourceSetup')
        observed = _array(setup.get('observedRelations'), 'sourceSetup.observedRelations')
        segments = _array(concept.get('segments'), 'concepts.segments')
        for segment in segments:
            _object(segment, 'concepts.segments[]')
        checks = _array(setup.get('boundaryChecks'), 'sourceSetup.boundaryChecks')
        if any(not isinstance(check, str) for check in checks) or not isinstance(setup.get('interpretation'), str):
            raise SourceFactsError('sourceSetup checks/interpretation must retain their string format.')
        observations, added = [], []
        seen = {key for segment in segments if (key := _segment_key(segment)) is not None}
        for fact in observed:
            _object(fact, 'observedRelations[]')
            if set(fact) != {'learnerText', 'blockIds'}:
                raise SourceFactsError('An observed fact has missing or unknown fields.')
            if not isinstance(fact['learnerText'], str) or not fact['learnerText'].strip():
                raise SourceFactsError('An observed fact needs a learner string.')
            ids = _references(fact['blockIds'], 'observedRelations.blockIds')
            # This field is an internal model observation, not a source quote.
            observations.append(fact['learnerText'])
            segment = {'kind': 'explanation', 'text': fact['learnerText'], 'blockIds': ids}
            key = _segment_key(segment)
            if key not in seen:
                seen.add(key)
                added.append(segment)
        setup['observedRelations'] = observations
        index = next((index for index, segment in enumerate(segments)
                      if segment.get('kind') != 'definition'), len(segments))
        concept['segments'] = segments[:index] + added + segments[index:]
    return value
