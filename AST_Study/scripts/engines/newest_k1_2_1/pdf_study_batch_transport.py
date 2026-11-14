"""Lossless packing of independent teaching requests.

This module does not schedule work, call a provider, merge teaching, or validate
its meaning. Append RULES to the unchanged teaching instructions, send the
returned payload/format/images once, then pass each decoded reply to the ordinary
unit validator. Production packs at most two original units; larger envelopes
remain explicit audit options rather than changing semantic teaching groups.
"""
from __future__ import annotations

import copy
import json
import math
import re

from pdf_study_cache_reuse import constrained_format


VERSION = 'independent-study-pair-v1'
RULES = '''\nINDEPENDENT UNIT TRANSPORT: Each entry in units (u0, u1, ...) is an independent
original teaching unit. Apply every teaching/detail/grounding rule fully to each
unit separately. Never merge, omit, swap, summarize together, or cross-cite units;
a source ID belongs only to its own unit. Keep each unit's own titleHint, entry
hints, document context, and neighboring context. Images follow imageOrder, where
each entry identifies its unit and zero-based cropIndex in that unit's crops.
Return exactly the supplied unit keys, each with its complete original response.
This packaging adds no review stage and does not reduce either unit's detail.\n'''


class BatchTransportError(ValueError):
    """A pair cannot be represented or split without losing unit ownership."""


def _object(value, where):
    if not isinstance(value, dict):
        raise BatchTransportError(f'{where} must be an object.')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise BatchTransportError(f'{where} must be an array.')
    return value


def _source_ids(blocks, where):
    values = []
    for block in _array(blocks, where):
        key = _object(block, where + '[]').get('id')
        if not isinstance(key, str) or not key or key in values:
            raise BatchTransportError(f'{where} requires unique non-empty source IDs.')
        values.append(key)
    if not values:
        raise BatchTransportError(f'{where} must contain at least one target.')
    return values


def _references(values, allowed, where):
    if not _array(values, where) or any(not isinstance(key, str) or key not in allowed for key in values):
        raise BatchTransportError(f'{where} must reference its own unit targets.')


def _resolve(root, reference):
    if reference == '#':
        return root
    if not isinstance(reference, str) or not reference.startswith('#/'):
        raise BatchTransportError('Only local schema references are supported.')
    node = root
    try:
        for part in reference[2:].split('/'):
            key = part.replace('~1', '/').replace('~0', '~')
            node = node[int(key)] if isinstance(node, list) and re.fullmatch(r'0|[1-9]\d*', key) else node[key]
    except (KeyError, TypeError, IndexError):
        raise BatchTransportError('A local schema reference cannot be resolved.') from None
    return _object(node, 'referenced schema')


_SCHEMA_KEYS = {'$ref', '$defs', 'type', 'properties', 'required', 'additionalProperties',
                'items', 'enum', 'const', 'anyOf', 'oneOf', 'allOf', 'minItems', 'maxItems',
                'uniqueItems', 'minLength', 'maxLength', 'pattern', 'minimum', 'maximum',
                'exclusiveMinimum', 'exclusiveMaximum', 'description', 'title', '$comment'}


def _check_schema(node, root):
    """Fail closed when a future format needs a validator feature not supported here."""
    _object(node, 'schema')
    if set(node) - _SCHEMA_KEYS:
        raise BatchTransportError('The experimental transport does not support this schema keyword.')
    if '$ref' in node:
        _resolve(root, node['$ref'])
    for name in ('$defs', 'properties'):
        for child in _object(node.get(name, {}), 'schema.' + name).values():
            _check_schema(child, root)
    for name in ('items', 'additionalProperties'):
        child = node.get(name)
        if isinstance(child, dict):
            _check_schema(child, root)
    for name in ('anyOf', 'oneOf', 'allOf'):
        if name in node:
            for child in _array(node[name], 'schema.' + name):
                _check_schema(child, root)


def _validate(value, node, root, where='$', depth=0):
    """Check wire shape/ownership only; normal study validation still runs next."""
    if depth > 160:
        raise BatchTransportError('Response nesting exceeds the transport limit.')
    if '$ref' in node:
        _validate(value, _resolve(root, node['$ref']), root, where, depth + 1)
    for name in ('anyOf', 'oneOf', 'allOf'):
        if name in node:
            successes = 0
            for alternative in node[name]:
                try:
                    _validate(value, alternative, root, where, depth + 1)
                    successes += 1
                except BatchTransportError:
                    pass
            if (name == 'allOf' and successes != len(node[name]) or
                    name == 'anyOf' and not successes or name == 'oneOf' and successes != 1):
                raise BatchTransportError(f'{where} does not match the unit schema.')
    expected = node.get('type')
    kinds = {
        'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
        'string': lambda: isinstance(value, str), 'boolean': lambda: type(value) is bool,
        'integer': lambda: type(value) is int,
        'number': lambda: type(value) in (int, float) and math.isfinite(value),
        'null': lambda: value is None}
    if expected is not None and (expected not in kinds or not kinds[expected]()):
        raise BatchTransportError(f'{where} has the wrong JSON type.')
    if 'enum' in node and not any(type(value) is type(item) and value == item for item in node['enum']):
        raise BatchTransportError(f'{where} contains a value outside its unit schema.')
    if 'const' in node and (type(value) is not type(node['const']) or value != node['const']):
        raise BatchTransportError(f'{where} differs from its unit schema constant.')
    if isinstance(value, dict):
        properties = node.get('properties', {})
        if any(key not in value for key in node.get('required', [])):
            raise BatchTransportError(f'{where} is missing a required field.')
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, where + '.' + key, depth + 1)
            elif node.get('additionalProperties') is False:
                raise BatchTransportError(f'{where} contains an unknown field.')
            elif isinstance(node.get('additionalProperties'), dict):
                _validate(item, node['additionalProperties'], root, where + '.*', depth + 1)
    if isinstance(value, list):
        if len(value) < node.get('minItems', 0) or len(value) > node.get('maxItems', math.inf):
            raise BatchTransportError(f'{where} has an invalid array length.')
        if node.get('uniqueItems') and any(item in value[:i] for i, item in enumerate(value)):
            raise BatchTransportError(f'{where} contains duplicate items.')
        if 'items' in node:
            for index, item in enumerate(value):
                _validate(item, node['items'], root, f'{where}[{index}]', depth + 1)
    if isinstance(value, str):
        if len(value) < node.get('minLength', 0) or len(value) > node.get('maxLength', math.inf):
            raise BatchTransportError(f'{where} has an invalid string length.')
        if 'pattern' in node and re.search(node['pattern'], value) is None:
            raise BatchTransportError(f'{where} does not match its schema pattern.')
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise BatchTransportError(f'{where} is not a finite JSON number.')
        for key, invalid in (('minimum', lambda bound: value < bound),
                             ('maximum', lambda bound: value > bound),
                             ('exclusiveMinimum', lambda bound: value <= bound),
                             ('exclusiveMaximum', lambda bound: value >= bound)):
            if key in node and invalid(node[key]):
                raise BatchTransportError(f'{where} is outside its schema bound.')


def _namespace(schema, name):
    value = copy.deepcopy(schema)
    prefix = '#/$defs/' + name
    def walk(node):
        if isinstance(node, dict):
            if '$ref' in node:
                reference = node['$ref']
                _resolve(schema, reference)
                node['$ref'] = prefix + (reference[1:] if reference != '#' else '')
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return value


def _flat_namespace(schema, name):
    """Hoist local schema targets so every ref is one top-level $defs name.

    Nested JSON pointers are valid standard JSON Schema, but a provider's strict
    grammar may support a narrower subset. This alternate representation changes
    reference routing only; the original schema remains in the decode contract.
    """
    names = {(): name}
    used = {name}

    def register(path, suggested=None):
        if path not in names:
            base = name + '__' + (re.sub(r'[^A-Za-z0-9_-]', '_', suggested)
                                  if suggested else 'ref' + str(len(names)))
            candidate, suffix = base, 2
            while candidate in used:
                candidate = base + '_' + str(suffix)
                suffix += 1
            names[path] = candidate
            used.add(candidate)
        return names[path]

    def pointer(reference):
        _resolve(schema, reference)
        return (() if reference == '#' else
                tuple(part.replace('~1', '/').replace('~0', '~') for part in reference[2:].split('/')))

    def children(node, path):
        for field in ('$defs', 'properties'):
            for key, child in node.get(field, {}).items():
                yield child, path + (field, key)
        for field in ('items', 'additionalProperties'):
            if isinstance(node.get(field), dict):
                yield node[field], path + (field,)
        for field in ('anyOf', 'oneOf', 'allOf'):
            for index, child in enumerate(node.get(field, [])):
                yield child, path + (field, str(index))

    def collect(node, path=()):
        for key in node.get('$defs', {}):
            register(path + ('$defs', key), key if not path else '__'.join(path + (key,)))
        if '$ref' in node:
            register(pointer(node['$ref']))
        for child, child_path in children(node, path):
            collect(child, child_path)
    collect(schema)

    def original(path):
        node = schema
        for key in path:
            node = node[int(key)] if isinstance(node, list) else node[key]
        return node

    def convert(node):
        result = {}
        for key, value in node.items():
            if key == '$defs':
                continue
            if key == '$ref':
                result[key] = '#/$defs/' + names[pointer(value)]
            elif key == 'properties':
                result[key] = {key: convert(child) for key, child in value.items()}
            elif key in ('items', 'additionalProperties') and isinstance(value, dict):
                result[key] = convert(value)
            elif key in ('anyOf', 'oneOf', 'allOf'):
                result[key] = [convert(child) for child in value]
            else:
                result[key] = copy.deepcopy(value)
        return result
    return {flat_name: convert(original(path)) for path, flat_name in names.items()}


def encode(units, *, max_images=4, max_units=2, flat_defs=False, alias_pool_size=None):
    """Return ``(batch_payload, batch_format, flat_images, contract)``.

    Each input object has job, payload, response_format, images. Defaults require
    exactly two units and at most four total images. Trusted experiments can
    explicitly raise max_units up to four and max_images to eight or sixteen;
    each individual original unit must still have at most four images.
    Their original payloads are retained verbatim under units.u0/units.u1. Image
    dicts (including bytes/data URLs and optional sourceLabel) are copied without
    resizing, recoding, or relabeling. Pass ``flat_images or None`` to Provider.

    Canonical source IDs must be globally disjoint. Optional aliases are allowed
    only when their caller-provided spelling is also globally disjoint; the
    helper never guesses a mapping or applies two colliding job-local mappings.
    flat_defs=True opts into top-level-only definition refs for a provider grammar
    compatibility experiment. False preserves the original nested representation.
    alias_pool_size optionally uses disjoint ua/ub/uc/ud source-ID namespaces
    with a positive-integer fixed pool, 'exact' real-target-only pool, or
    'namespace' static per-unit pattern. The pattern enumerates no spare aliases;
    actual mapping membership is still checked strictly on decode. It changes
    only structured source IDs;
    the contract and returned decoded replies retain canonical sources. Image
    source labels are rejected in this mode rather than searched/replaced.
    """
    if type(max_units) is not int or not 2 <= max_units <= 4:
        raise BatchTransportError('The explicit unit limit must be an integer from two to four.')
    if type(max_images) is not int or max_images not in (4, 8, 16):
        raise BatchTransportError('The explicit total image limit must be four, eight, or sixteen.')
    if type(flat_defs) is not bool:
        raise BatchTransportError('The flat definition option must be an explicit boolean.')
    exact_aliases = type(alias_pool_size) is str and alias_pool_size == 'exact'
    namespace_aliases = type(alias_pool_size) is str and alias_pool_size == 'namespace'
    if (alias_pool_size is not None and not exact_aliases and not namespace_aliases and
            (type(alias_pool_size) is not int or alias_pool_size < 1)):
        raise BatchTransportError('The optional alias pool must be a positive integer, exact, or namespace.')
    if not isinstance(units, (list, tuple)) or not 2 <= len(units) <= max_units:
        raise BatchTransportError('The original unit count exceeds the explicitly allowed batch size.')
    payload = {'task': 'region_teaching_batch', 'units': {}, 'imageOrder': []}
    contract = {'version': VERSION, 'units': []}
    definitions, images, job_ids, all_sources = {}, [], set(), set()
    for index, supplied in enumerate(units):
        supplied = _object(supplied, 'unit')
        job = _object(supplied.get('job'), 'unit.job')
        name = 'u' + str(index)
        job_id = job.get('id')
        if not isinstance(job_id, str) or not job_id or job_id in job_ids:
            raise BatchTransportError('Units must have distinct non-empty job IDs.')
        job_ids.add(job_id)
        ids = _source_ids(job.get('blocks'), 'job.blocks')
        if all_sources.intersection(ids):
            raise BatchTransportError('Source IDs must be globally disjoint across units.')
        all_sources.update(ids)
        original = _object(supplied.get('payload'), 'unit.payload')
        actual = _source_ids(original.get('blocks'), 'payload.blocks')
        if len(ids) != len(actual) or set(ids) != set(actual):
            raise BatchTransportError('Every original unit target must occur exactly once in its payload.')
        for hint in _array(original.get('entryHints', []), 'payload.entryHints'):
            if _object(hint, 'entryHint').get('startsAt') not in ids:
                raise BatchTransportError('An entry hint references another or missing source.')
        crops = _array(original.get('crops', []), 'payload.crops')
        original_images = supplied.get('images', [])
        original_images = [] if original_images is None else _array(original_images, 'unit.images')
        if len(original_images) > 4:
            raise BatchTransportError('Each original unit may contain at most four images.')
        if len(crops) != len(original_images):
            raise BatchTransportError('Each original crop must have exactly one original image.')
        for crop_index, (crop, image) in enumerate(zip(crops, original_images)):
            crop = _object(crop, 'payload.crops[]')
            _references(crop.get('blockIds'), ids, 'payload.crops[].blockIds')
            if type(crop.get('page')) is not int or crop['page'] < 1:
                raise BatchTransportError('Each crop needs its original positive page.')
            _object(image, 'unit.images[]')
            if alias_pool_size is not None and image.get('sourceLabel') is not None:
                raise BatchTransportError('Canonical image source labels require opting out of batch aliases.')
            images.append(copy.deepcopy(image))
            payload['imageOrder'].append({'unit': name, 'cropIndex': crop_index})
        original_format = _object(supplied.get('response_format'), 'unit.response_format')
        if original_format.get('type') != 'json_schema':
            raise BatchTransportError('The original strict JSON-schema format is required.')
        wrapper = _object(original_format.get('json_schema'), 'response_format.json_schema')
        if wrapper.get('strict') is not True:
            raise BatchTransportError('The original response format must remain strict.')
        schema = _object(wrapper.get('schema'), 'response_format.schema')
        previous = schema.get('$defs', {}).get('studySourceId')
        if previous is not None and (not isinstance(previous, dict) or previous.get('enum') != ids):
            raise BatchTransportError('The original exact source enum must match its ordered job targets.')
        unit_schema = constrained_format(original_format, job)['json_schema']['schema']
        _check_schema(unit_schema, unit_schema)
        contract_unit = {'name': name, 'jobId': job_id, 'sourceIds': list(ids),
                         'schema': copy.deepcopy(unit_schema)}
        wire_payload, wire_schema = copy.deepcopy(original), unit_schema
        if alias_pool_size is not None:
            from pdf_source_aliases import encode as alias_encode, SourceAliasError
            try:
                wire_payload, wire_format, aliases = alias_encode(original, original_format, job,
                    stable_pool_size=len(ids) if exact_aliases or namespace_aliases else alias_pool_size,
                    alias_prefix='u'+chr(ord('a')+index))
            except SourceAliasError as error:
                raise BatchTransportError(str(error)) from error
            wire_schema = wire_format['json_schema']['schema']
            if namespace_aliases:
                wire_schema['$defs']['studySourceId'] = _alias_namespace_definition(index)
                contract_unit['aliasSchemaMode'] = 'namespace'
            contract_unit.update(aliases=aliases, wireSchema=copy.deepcopy(wire_schema))
        if flat_defs:
            definitions.update(_flat_namespace(wire_schema, name))
        else:
            definitions[name] = _namespace(wire_schema, name)
        payload['units'][name] = wire_payload
        contract['units'].append(contract_unit)
    if len(images) > max_images:
        raise BatchTransportError('The batch exceeds its explicitly allowed total image count.')
    names = [unit['name'] for unit in contract['units']]
    schema = {'type': 'object', 'properties': {name: {'$ref': '#/$defs/' + name} for name in names},
              'required': names, 'additionalProperties': False, '$defs': definitions}
    _check_schema(schema, schema)
    format = {'type': 'json_schema', 'json_schema': {'name': 'independent_study_pair_v1',
                                                   'strict': True, 'schema': schema}}
    return payload, format, images, contract


def _strict_json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise BatchTransportError('The response contains a duplicate JSON key.')
            value[key] = item
        return value
    def constant(_):
        raise BatchTransportError('The response contains a non-finite JSON constant.')
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError) as error:
        if isinstance(error, BatchTransportError):
            raise
        raise BatchTransportError('The response is not strict JSON.') from None


def _alias_namespace_definition(index):
    # Wire grammar restricts ownership, while the real-target mapping remains
    # finite/exact. Never interpret another valid namespace spelling as a source.
    return {'type':'string','pattern':'^u'+chr(ord('a')+index)+'[a-z]+$'}


def _contract_units(contract):
    """Validate every owner before even one unit can be returned for persistence."""
    _object(contract, 'contract')
    if contract.get('version') != VERSION:
        raise BatchTransportError('The transport contract version is unsupported.')
    units = _array(contract.get('units'), 'contract.units')
    names = [f'u{i}' for i in range(len(units))]
    if not 2 <= len(units) <= 4 or [unit.get('name') if isinstance(unit, dict) else None for unit in units] != names:
        raise BatchTransportError('The transport contract must own two to four sequential unit keys.')
    sources, job_ids = set(), set()
    for index, unit in enumerate(units):
        ids = unit.get('sourceIds')
        if (not isinstance(ids, list) or not ids or any(not isinstance(key, str) or not key for key in ids)
                or len(set(ids)) != len(ids) or sources.intersection(ids)
                or not isinstance(unit.get('jobId'), str) or not unit['jobId'] or unit['jobId'] in job_ids):
            raise BatchTransportError('The transport contract has ambiguous target ownership.')
        sources.update(ids)
        job_ids.add(unit['jobId'])
        schema = _object(unit.get('schema'), 'contract unit schema')
        definitions = _object(schema.get('$defs', {}), 'contract canonical definitions')
        if definitions.get('studySourceId') != {'type': 'string', 'enum': ids}:
            raise BatchTransportError('The unit source enum differs from its exact contract.')
        _check_schema(schema, schema)
        if 'aliasSchemaMode' in unit and unit['aliasSchemaMode']!='namespace':
            raise BatchTransportError('The alias schema mode is unsupported.')
        if 'aliases' in unit or 'wireSchema' in unit or 'aliasSchemaMode' in unit:
            aliases = _object(unit.get('aliases'), 'contract unit aliases')
            wire = _object(unit.get('wireSchema'), 'contract unit wire schema')
            definitions = _object(wire.get('$defs', {}), 'contract wire definitions')
            source_definition = _object(definitions.get('studySourceId'), 'contract wire source definition')
            namespace_aliases = unit.get('aliasSchemaMode')=='namespace'
            if namespace_aliases:
                pool_size = len(ids)
            else:
                pool = source_definition.get('enum')
                if not isinstance(pool, list) or len(pool) < len(ids):
                    raise BatchTransportError('The alias wire pool cannot omit a canonical target.')
                pool_size = len(pool)
            # Reconstruct the only permitted alias mapping/schema. A matching
            # canonical enum alone cannot justify a relaxed wire schema, a
            # changed mapping or an alias from another unit's namespace.
            from pdf_source_aliases import encode as alias_encode, SourceAliasError
            try:
                _, expected, mapping = alias_encode({'blocks': [{'id': key} for key in ids]},
                    {'json_schema': {'schema': schema}}, {'blocks': [{'id': key} for key in ids]},
                    stable_pool_size=pool_size, alias_prefix='u'+chr(ord('a')+index))
            except SourceAliasError as error:
                raise BatchTransportError(str(error)) from error
            expected_schema = expected['json_schema']['schema']
            if namespace_aliases:
                expected_schema['$defs']['studySourceId'] = _alias_namespace_definition(index)
            if aliases != mapping or wire != expected_schema:
                raise BatchTransportError('The alias wire contract differs from its exact canonical sources.')
            _check_schema(wire, wire)
    return units


def _decode_unit(value, unit, where):
    """Validate wire ownership, restore references, then validate canonical shape."""
    schema = unit['schema']
    _object(value, 'unit response')
    from pdf_saved_teaching_compat import processing_records
    ids=unit.get('aliases',{})or {i:i for i in unit['sourceIds']}
    value,_=processing_records(_plain_copy(value),ids)
    if 'aliases' in unit:
        wire = unit['wireSchema']
        _validate(value, wire, wire, where)
        from pdf_source_aliases import decode as alias_decode, SourceAliasError
        try:
            restored = alias_decode(_plain_copy(value), unit['aliases'])
        except SourceAliasError as error:
            raise BatchTransportError(str(error)) from error
    else:
        restored = _plain_copy(value)
    _validate(restored, schema, schema, where)
    return restored


def decode(raw, contract):
    """Strict split into independent, unchanged canonical raw objects.

    Each result must still pass the existing study.validate(result, job, document).
    Missing/unknown units, malformed fields, and cross-unit/unknown citations are
    rejected rather than repaired. A raw JSON string also rejects duplicate keys;
    an already-parsed dict cannot reveal keys overwritten by its earlier parser.
    """
    units = _contract_units(contract)
    value = _strict_json(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    _object(value, 'response')
    if set(value) != {unit['name'] for unit in units}:
        raise BatchTransportError('The response must contain exactly all original units.')
    results = []
    for unit in units:
        results.append(_decode_unit(value[unit['name']], unit, '$.' + unit['name']))
    return results


class _JsonObject(dict):
    """Keep ambiguous keys visible for partial acceptance of other units only."""
    def __init__(self, items):
        super().__init__()
        self.duplicate_keys = set()
        for key, item in items:
            if key in self:
                self.duplicate_keys.add(key)
            self[key] = item


def _partial_json(raw):
    def constant(_):
        # Invalid JSON constants are a container-level parse failure, not a
        # number silently normalized into a seemingly valid teaching response.
        raise BatchTransportError('The response contains a non-finite JSON constant.')
    try:
        return json.loads(raw, object_pairs_hook=_JsonObject, parse_constant=constant)
    except (ValueError, TypeError) as error:
        if isinstance(error, BatchTransportError):
            raise
        raise BatchTransportError('The response is not strict JSON.') from None


def _has_duplicate_keys(value):
    if isinstance(value, dict):
        return (bool(getattr(value, 'duplicate_keys', set())) or
                any(_has_duplicate_keys(item) for item in value.values()))
    return isinstance(value, list) and any(_has_duplicate_keys(item) for item in value)


def _plain_copy(value):
    if isinstance(value, dict):
        return {key: _plain_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_copy(item) for item in value]
    return copy.deepcopy(value)


def decode_each(raw, contract):
    """Return ``(valid_records, errors)`` without discarding an independent peer.

    Valid records are ``{index, name, raw}``; errors are ``{index, name, error,
    code}``. Container errors use index/name=None. A malformed contract always
    raises before any acceptance. A malformed/missing/cross-citing response unit
    fails locally; unknown container keys also produce an explicit error while
    retaining valid expected units. Callers must mark the overall batch partial
    whenever errors exist, persist only normally validated valid records, and
    record failed units without adding an automatic paid retry.

    String inputs retain duplicate-key locations, so an ambiguous unit is never
    accepted while an unambiguous peer can survive. As with decode, dictionaries
    cannot expose duplicate keys discarded before this helper received them.
    """
    units = _contract_units(contract)
    try:
        value = _partial_json(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
        _object(value, 'response')
    except BatchTransportError as error:
        return [], [{'index': None, 'name': None, 'error': str(error), 'code': 'invalid_container'}]
    records, errors = [], []
    names = {unit['name'] for unit in units}
    duplicate_container = getattr(value, 'duplicate_keys', set())
    if set(value) - names:
        errors.append({'index': None, 'name': None, 'error': 'The response contains an unknown unit key.',
                       'code': 'unknown_unit'})
    if duplicate_container - names:
        errors.append({'index': None, 'name': None, 'error': 'The response container contains a duplicate unknown key.',
                       'code': 'duplicate_container_key'})
    for index, unit in enumerate(units):
        name = unit['name']
        if name not in value:
            errors.append({'index': index, 'name': name, 'error': 'The original unit response is missing.',
                           'code': 'missing_unit'})
            continue
        try:
            if name in duplicate_container or _has_duplicate_keys(value[name]):
                raise BatchTransportError('The unit response contains an ambiguous duplicate JSON key.')
            records.append({'index': index, 'name': name, 'raw': _decode_unit(value[name], unit, '$.' + name)})
        except BatchTransportError as error:
            errors.append({'index': index, 'name': name, 'error': str(error), 'code': 'invalid_unit'})
    return records, errors
