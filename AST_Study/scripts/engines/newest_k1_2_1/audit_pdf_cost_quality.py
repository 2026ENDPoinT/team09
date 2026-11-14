"""Offline, read-only source/evidence QA for frozen-plan PDF cost experiments.

This verifier never calls a model, re-renders a PDF, rewrites learner prose, or
repairs cache files. It may inspect a still-running experiment; missing outputs
are then reported as pending rather than silently accepted as complete.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import tempfile


CRITICAL_PAGES = (15, 76, 88)
SOURCE_ANNOTATIONS = frozenset(('planRole', 'planRoleBeforeVisualGuard', 'visualReadingRequired'))
SETUP_FIELDS = ('observedRelations', 'boundaryChecks', 'interpretation')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source(block):
    return {key: value for key, value in block.items() if key not in SOURCE_ANNOTATIONS}


def source_references(value, path=()):
    """Find canonical raw block references without interpreting model prose."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'blockId':
                yield path + (key,), child
            elif key == 'blockIds':
                if isinstance(child, list):
                    for index, ref in enumerate(child):
                        yield path + (key, index), ref
                else:
                    yield path + (key,), child
            elif isinstance(child, (dict, list)):
                yield from source_references(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from source_references(child, path + (index,))


def evidence_objects(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'evidence' and isinstance(child, list):
                for index, item in enumerate(child):
                    yield path + (key, index), item
            elif isinstance(child, (dict, list)):
                yield from evidence_objects(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from evidence_objects(child, path + (index,))


def location(path):
    return '/' + '/'.join(str(key) for key in path)


def evidence_issues(value, allowed, document_id):
    issues = []
    total = 0
    for path, item in evidence_objects(value):
        total += 1
        if not isinstance(item, dict):
            issues.append({'path': location(path), 'kind': 'evidence_not_object'})
            continue
        ref = item.get('sourceId')
        block = allowed.get(ref) if isinstance(ref, str) else None
        if block is None:
            issues.append({'path': location(path), 'kind': 'unknown_or_out_of_scope_source_id', 'sourceId': ref})
            continue
        for field, expected in [('documentId', document_id), ('page', block.get('page'))]:
            if item.get(field) != expected:
                issues.append({'path': location(path), 'kind': 'source_metadata_mismatch',
                               'sourceId': ref, 'field': field, 'actual': item.get(field), 'expected': expected})
        if item.get('bbox') != block.get('bbox'):
            issues.append({'path': location(path), 'kind': 'source_bbox_changed', 'sourceId': ref})
        quote = item.get('quote')
        if not isinstance(quote, str):
            issues.append({'path': location(path), 'kind': 'quote_not_string', 'sourceId': ref})
        elif quote and quote not in block.get('text', ''):
            issues.append({'path': location(path), 'kind': 'nonliteral_source_quote', 'sourceId': ref, 'quote': quote})
    return total, issues


def raw_issues(reply, allowed):
    issues = []
    count = 0
    for path, ref in source_references(reply):
        count += 1
        if not isinstance(ref, str) or ref not in allowed:
            issues.append({'path': location(path), 'kind': 'raw_unknown_or_out_of_job_source_id', 'sourceId': ref})
    setups = []
    for index, concept in enumerate(reply.get('concepts', [])):
        if not isinstance(concept, dict):
            issues.append({'path': f'/concepts/{index}', 'kind': 'concept_not_object'})
            continue
        setup = concept.get('sourceSetup')
        okay = (isinstance(setup, dict) and set(setup) == set(SETUP_FIELDS)
                and all(isinstance(setup.get(key), list) and all(isinstance(x, str) for x in setup[key])
                        for key in ('observedRelations', 'boundaryChecks'))
                and isinstance(setup.get('interpretation'), str))
        if not okay:
            issues.append({'path': f'/concepts/{index}/sourceSetup', 'kind': 'unexpected_source_setup_shape'})
        setups.append({'conceptTitle': concept.get('title'), 'shapeValid': okay,
                       'sourceSetup': setup,
                       'availableCanonicalSourceIds': sorted(allowed),
                       'note': 'Observed relations are model-written private statements, not independently verified literal quotations.'})
    return count, setups, issues


def text_controls(value, path=()):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(text_controls(child, path + (key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(text_controls(child, path + (index,)))
    elif isinstance(value, str):
        bad = sorted({ord(char) for char in value if ord(char) < 32 and char not in '\n\r\t'})
        if bad:
            found.append({'path': location(path), 'codepoints': bad, 'text': value})
    return found


def inline_math_tab_warnings(value, path=()):
    """Flag possible JSON escape damage, without declaring valid whitespace bad."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(inline_math_tab_warnings(child, path + (key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(inline_math_tab_warnings(child, path + (index,)))
    elif isinstance(value, str):
        for match in re.finditer(r'\\\((?:(?!\\\)).)*?\\\)', value, re.S):
            if re.search(r'\t[A-Za-z]{2,}', match.group()):
                found.append({'path': location(path), 'kind': 'tab_before_letters_inside_inline_math',
                              'math': match.group(),
                              'note': 'Possible unescaped JSON backslash command. This is an audit warning, not an automatic correction or mathematical-failure verdict.'})
    return found


def alias_name(index):
    value = ''
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        value = chr(97 + digit) + value
    return value


def normalized_display_text(text):
    """Ignore display-only blockquote prefixes and whitespace, never prose/math."""
    return ' '.join(re.sub(r'(?m)^\s*> ?', '', text).split())


def learner_segment_retention(reply, unit):
    texts = []
    for part in unit.get('summary', {}).get('parts', []):
        texts.extend(part.get(key, '') for key in ('body', 'easyExplanation'))
    for concept in unit.get('concepts', []):
        texts.extend(concept.get(key, '') for key in ('definition', 'explanation', 'easyExplanation'))
    learner = [normalized_display_text(text) for text in texts if isinstance(text, str)]
    records = []
    for concept in reply.get('concepts', []):
        for index, segment in enumerate(concept.get('segments', [])):
            if segment.get('kind') not in ('definition', 'explanation', 'easyExplanation'):
                continue
            text = segment.get('text', '')
            needle = normalized_display_text(text) if isinstance(text, str) else ''
            retained = bool(needle) and any(needle in value for value in learner)
            records.append({'conceptTitle': concept.get('title'), 'segmentIndex': index,
                            'kind': segment.get('kind'), 'blockIds': segment.get('blockIds'),
                            'retainedInLearnerModuloDisplayWhitespace': retained,
                            'text': text if not retained else None})
    return records


def uncertainty_scope(reply):
    supported = set()
    statements = []
    for concept in reply.get('concepts', []):
        for segment in concept.get('segments', []):
            refs = segment.get('blockIds', [])
            if segment.get('kind') == 'uncertain':
                statements.append({'conceptTitle': concept.get('title'), 'blockIds': refs,
                                   'text': segment.get('text')})
            elif segment.get('kind') in ('definition', 'explanation', 'easyExplanation'):
                supported.update(refs)
    for table in reply.get('tables', []):
        supported.update(table.get('blockIds', []))
    whole_ids = {item.get('blockId') for item in reply.get('uncertainBlocks', [])}
    for item in statements:
        item['alsoSupportsTeachingIds'] = sorted(supported.intersection(item['blockIds']))
    return {'wholeRegionUncertaintyCount': len(whole_ids),
            'wholeRegionAlsoClaimedSupportedIds': sorted(whole_ids.intersection(supported)),
            'uncertainStatements': statements,
            'sameRegionStatementCount': sum(bool(item['alsoSupportsTeachingIds']) for item in statements)}


def paid_transport_proof(folder, cache, jobs, ledger_rows, completed, read, *, aliases=False):
    """Trace actual paid envelopes to each canonical reply; never infer by payloadHash.

    New ledgers name responseCacheKey. Old ledgers without it use exact decoded
    content matching, which is explicitly reported as weaker provenance.
    """
    job_map = {job['id']: job for job in jobs}
    replies = {job['id']: read(cache / f'response-{job["id"]}.json')
               for job in jobs if not job.get('skip') and (cache / f'response-{job["id"]}.json').exists()}
    indexed, wire_contents = {}, {}
    for path in sorted((folder / 'generated' / 'paid-responses').glob('*.raw.json')):
        raw = read(path)
        try:
            content = raw['choices'][0]['message']['content']
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        indexed[path.name[:-9]] = (path, parsed)
        wire_contents[str(path)] = content
    records, issues, assigned = [], [], Counter()
    rows = [row for row in ledger_rows if row.get('kind') == 'region_study']
    for row in rows:
        ids = row.get('unitIds', [])
        if not isinstance(ids, list) or not ids or any(key not in job_map for key in ids):
            issues.append({'kind': 'transport_ledger_unknown_units', 'requestId': row.get('requestId'), 'unitIds': ids})
            continue
        if row.get('state') != 'settled':
            continue
        key = row.get('responseCacheKey')
        candidates = [indexed[key]] if key in indexed else ([] if key else list(indexed.values()))
        contract_path = row.get('studyBatchContract')
        batch = len(ids) > 1
        contract = None
        request_issues = []
        if batch:
            candidate_path = cache / Path(contract_path).name if isinstance(contract_path, str) else None
            if candidate_path is None or not candidate_path.exists():
                request_issues.append({'kind': 'batch_contract_missing'})
            else:
                contract = read(candidate_path)
                units = contract.get('units', [])
                if [item.get('jobId') for item in units] != ids:
                    request_issues.append({'kind': 'batch_contract_job_order_mismatch'})
                source_ids = []
                for item in units:
                    job = job_map.get(item.get('jobId'))
                    expected_ids = [block['id'] for block in job['blocks']] if job else []
                    if item.get('sourceIds') != expected_ids:
                        request_issues.append({'kind': 'batch_contract_source_ids_changed', 'jobId': item.get('jobId')})
                    schema_ids = item.get('schema', {}).get('$defs', {}).get('studySourceId', {}).get('enum')
                    if schema_ids != expected_ids:
                        request_issues.append({'kind': 'batch_original_schema_source_enum_changed', 'jobId': item.get('jobId')})
                    source_ids.extend(item.get('sourceIds', []))
                if len(source_ids) != len(set(source_ids)):
                    request_issues.append({'kind': 'batch_units_share_source_ids'})
        matches, decoder_errors = [], []
        for path, wire in candidates:
            if batch:
                if contract is None or not isinstance(wire, dict):
                    continue
                units = contract.get('units', [])
                if set(wire) != {item.get('name') for item in units}:
                    continue
                if any('aliases' in item for item in units):
                    from pdf_study_batch_transport import decode_each, BatchTransportError
                    try:
                        restored, errors = decode_each(wire_contents[str(path)], contract)
                    except BatchTransportError as error:
                        decoder_errors.append({'paidRaw': str(path), 'kind': 'invalid_alias_contract', 'detail': str(error)})
                        continue
                    if errors:
                        decoder_errors.extend({'paidRaw': str(path), **error} for error in errors)
                        continue
                    decoded = {units[item['index']]['jobId']: item['raw'] for item in restored}
                else:
                    decoded = {item['jobId']: wire[item['name']] for item in units}
            else:
                decoded = {ids[0]: wire}
                if aliases is not False:
                    from pdf_source_aliases import decode
                    mapping = {alias_name(index): block['id'] for index, block in enumerate(job_map[ids[0]]['blocks'])}
                    try:
                        restored_single = decode(wire, mapping)
                    except ValueError:
                        if aliases is True:
                            continue
                    else:
                        if aliases is True or restored_single == replies.get(ids[0]):
                            decoded[ids[0]] = restored_single
            if all(key in replies and value == replies[key] for key, value in decoded.items()):
                matches.append((path, decoded))
        if not matches:
            request_issues.append({'kind': 'paid_wire_canonical_mismatch_or_missing', 'responseCacheKey': key})
            if decoder_errors:
                request_issues.append({'kind': 'batch_alias_decode_failed', 'errors': decoder_errors})
        decoded_records = []
        if matches:
            for job_id, reply in matches[0][1].items():
                assigned[job_id] += 1
                allowed = {block['id']: block for block in job_map[job_id]['blocks']}
                _, _, ref_errors = raw_issues(reply, allowed)
                request_issues.extend({'jobId': job_id, **error} for error in ref_errors)
                decoded_records.append({'jobId': job_id, 'pages': sorted({b['page'] for b in allowed.values()}),
                                        'rawCanonicalDeepExact': True, 'sourceIds': list(allowed),
                                        'conceptTitles': [c.get('title') for c in reply.get('concepts', [])]})
        record = {'requestId': row.get('requestId'), 'unitIds': ids, 'isBatch': batch,
                  'studyBatchUnits': row.get('studyBatchUnits', 1), 'responseCacheKey': key,
                  'provenance': 'ledger_response_cache_key' if key else 'legacy_exact_content_match',
                  'paidRawExactMatches': [str(path) for path, _ in matches], 'decodedUnits': decoded_records,
                  'unitAliasSchemas': [{'jobId': item['jobId'], 'canonicalSourceCount': len(item['sourceIds']),
                                        'actualAliasCount': len(item.get('aliases', {})),
                                        'aliasSchemaMode': item.get('aliasSchemaMode', 'enum'),
                                        'wirePattern': item.get('wireSchema', {}).get('$defs', {}).get('studySourceId', {}).get('pattern'),
                                        'runtimeCanonicalEnumCount': len(item['schema']['$defs']['studySourceId']['enum']),
                                        'wireEnumCount': len(item.get('wireSchema', {}).get('$defs', {}).get('studySourceId', {}).get('enum', [])),
                                        'unusedWireEnumSpellings': sorted(set(item.get('wireSchema', {}).get('$defs', {}).get('studySourceId', {}).get('enum', [])) - set(item.get('aliases', {})))}
                                       for item in (contract or {}).get('units', []) if 'aliases' in item],
                  'issues': request_issues}
        records.append(record)
        issues.extend({'requestId': row.get('requestId'), **error} for error in request_issues)
    missing = sorted(set(replies) - set(assigned))
    duplicate = {key: count for key, count in assigned.items() if count > 1}
    if completed and missing:
        issues.append({'kind': 'canonical_reply_has_no_paid_transport_proof', 'jobIds': missing})
    if duplicate:
        issues.append({'kind': 'canonical_reply_assigned_multiple_paid_transports', 'jobs': duplicate})
    return {'requestsChecked': len(records), 'batchedRequests': sum(r['isBatch'] for r in records),
            'singletonRequests': sum(not r['isBatch'] for r in records), 'originalUnitsChecked': len(assigned),
            'pendingOrUnprovenReplyIds': missing, 'issues': issues, 'requests': records,
            'interpretation': 'Exact paid-wire to canonical deep equality proves title, private sourceSetup, prose, math/code, tables and sequence text are unchanged by envelope splitting/structured alias decoding. Source IDs are independently scoped per original job. This does not prove semantic non-mixing or mathematical correctness of model-generated text.'}


def self_test():
    block = {'id': 's1', 'page': 2, 'text': 'a < b, P != p', 'bbox': [.1, .2, .3, .4]}
    evidence = {'sourceId': 's1', 'documentId': 'doc', 'page': 2,
                'quote': 'a < b', 'bbox': [.1, .2, .3, .4]}
    valid = {'body': 'Teaching remains unchanged.', 'evidence': [evidence]}
    original = copy.deepcopy(valid)
    assert evidence_issues(valid, {'s1': block}, 'doc') == (1, [])
    assert valid == original
    for field, value, expected_kind in [('sourceId', 'alias1', 'unknown_or_out_of_scope_source_id'),
                                         ('page', 3, 'source_metadata_mismatch'),
                                         ('bbox', [0, 0, 1, 1], 'source_bbox_changed'),
                                         ('quote', 'a > b', 'nonliteral_source_quote')]:
        altered = copy.deepcopy(valid)
        altered['evidence'][0][field] = value
        assert expected_kind in {issue['kind'] for issue in evidence_issues(altered, {'s1': block}, 'doc')[1]}
    raw = {'concepts': [{'title': 'example', 'sourceSetup': {'observedRelations': ['a < b'],
                            'boundaryChecks': [], 'interpretation': ''},
                         'segments': [{'kind': 'explanation', 'text': 'a < b', 'blockIds': ['s1']}]}]}
    assert raw_issues(raw, {'s1': block})[2] == []
    raw['concepts'][0]['segments'][0]['blockIds'] = ['alias1']
    assert raw_issues(raw, {'s1': block})[2][0]['kind'] == 'raw_unknown_or_out_of_job_source_id'
    assert text_controls({'x': 'a\fb'})[0]['codepoints'] == [12]
    assert not text_controls({'x': 'a\nb\tc'})
    assert inline_math_tab_warnings({'body': '\\(n\\to\typo\\infty\\)'})
    assert not inline_math_tab_warnings({'body': '\\(n\\to\\infty\\)\tordinary prose'})
    segment = {'kind': 'explanation', 'text': '> $$a < b$$\n\nNo rewriting.', 'blockIds': ['s1']}
    reply = {'concepts': [{'title': 'a', 'segments': [segment]}]}
    learner = {'summary': {'parts': [{'body': '$$a < b$$\nNo rewriting.'}]}}
    assert learner_segment_retention(reply, learner)[0]['retainedInLearnerModuloDisplayWhitespace']
    learner['summary']['parts'][0]['body'] = '$$a > b$$ No rewriting.'
    assert not learner_segment_retention(reply, learner)[0]['retainedInLearnerModuloDisplayWhitespace']
    with tempfile.TemporaryDirectory(prefix='synesis-offline-transport-qa-') as directory:
        folder = Path(directory)
        cache = folder / 'cache'
        cache.mkdir()
        paid = folder / 'generated/paid-responses'
        paid.mkdir(parents=True)
        jobs = [{'id': 'j0', 'blocks': [block]},
                {'id': 'j1', 'blocks': [{**block, 'id': 's2', 'page': 3}]}]
        replies = [{'concepts': [], 'sequences': [], 'tables': [],
                    'excludedBlocks': [{'blockId': key, 'reason': 'Title only.'}], 'uncertainBlocks': []}
                   for key in ('s1', 's2')]
        contract = {'units': [{'name': f'u{i}', 'jobId': job['id'], 'sourceIds': [job['blocks'][0]['id']],
                              'schema': {'$defs': {'studySourceId': {'enum': [job['blocks'][0]['id']]}}}}
                             for i, job in enumerate(jobs)]}
        (cache / 'contract.json').write_text(json.dumps(contract))
        for job, value in zip(jobs, replies):
            (cache / f'response-{job["id"]}.json').write_text(json.dumps(value))
        envelope = {'u0': replies[0], 'u1': replies[1]}
        raw_path = paid / 'paid.raw.json'
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(envelope)}}]}))
        row = {'kind': 'region_study', 'state': 'settled', 'requestId': 'request',
               'unitIds': ['j0', 'j1'], 'responseCacheKey': 'paid',
               'studyBatchContract': str(cache / 'contract.json')}
        read = lambda path: json.loads(Path(path).read_text())
        proof = paid_transport_proof(folder, cache, jobs, [row], True, read)
        assert not proof['issues'] and proof['originalUnitsChecked'] == 2, proof
        before = copy.deepcopy(envelope)
        envelope['u0']['excludedBlocks'][0]['reason'] = 'Rewritten prose.'
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(envelope)}}]}))
        assert 'paid_wire_canonical_mismatch_or_missing' in {x['kind'] for x in paid_transport_proof(folder, cache, jobs, [row], True, read)['issues']}
        envelope = before
        envelope['u0']['excludedBlocks'][0]['blockId'] = 's2'
        (cache / 'response-j0.json').write_text(json.dumps(envelope['u0']))
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(envelope)}}]}))
        assert 'raw_unknown_or_out_of_job_source_id' in {x['kind'] for x in paid_transport_proof(folder, cache, jobs, [row], True, read)['issues']}
        from pdf_study_batch_transport import encode
        schema = {'type': 'object', 'properties': {
            'concepts': {'type': 'array', 'items': {'type': 'object'}},
            'sequences': {'type': 'array', 'items': {'type': 'object'}},
            'tables': {'type': 'array', 'items': {'type': 'object'}},
            'excludedBlocks': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'blockId': {'type': 'string'}, 'reason': {'type': 'string'}},
                'required': ['blockId', 'reason'], 'additionalProperties': False}},
            'uncertainBlocks': {'type': 'array', 'items': {'type': 'object'}}},
            'required': ['concepts', 'sequences', 'tables', 'excludedBlocks', 'uncertainBlocks'],
            'additionalProperties': False}
        units = [{'job': job, 'payload': {'blocks': job['blocks']}, 'images': [],
                  'response_format': {'type': 'json_schema', 'json_schema': {
                      'name': 'qa_fixture', 'strict': True, 'schema': schema}}} for job in jobs]
        _, _, _, alias_contract = encode(units, max_units=2, flat_defs=True, alias_pool_size='exact')
        (cache / 'contract.json').write_text(json.dumps(alias_contract))
        alias_canonical = {f'u{index}': {'concepts': [], 'sequences': [], 'tables': [],
                           'excludedBlocks': [{'blockId': job['blocks'][0]['id'], 'reason': 'Title only.'}],
                           'uncertainBlocks': []} for index, job in enumerate(jobs)}
        alias_wire = copy.deepcopy(alias_canonical)
        for index, item in enumerate(alias_contract['units']):
            alias_wire[item['name']]['excludedBlocks'][0]['blockId'] = next(iter(item['aliases']))
            (cache / f'response-{jobs[index]["id"]}.json').write_text(json.dumps(alias_canonical[item['name']]))
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(alias_wire)}}]}))
        proof = paid_transport_proof(folder, cache, jobs, [row], True, read)
        assert not proof['issues'] and proof['originalUnitsChecked'] == 2, proof
        assert all(not x['unusedWireEnumSpellings'] for x in proof['requests'][0]['unitAliasSchemas'])
        alias_wire['u0']['excludedBlocks'][0]['blockId'] = next(iter(alias_contract['units'][1]['aliases']))
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(alias_wire)}}]}))
        assert 'batch_alias_decode_failed' in {x['kind'] for x in paid_transport_proof(folder, cache, jobs, [row], True, read)['issues']}
        singleton_wire = copy.deepcopy(alias_canonical['u0'])
        singleton_wire['excludedBlocks'][0]['blockId'] = 'a'
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(singleton_wire)}}]}))
        singleton_row = {**row, 'unitIds': ['j0']}
        singleton_row.pop('studyBatchContract')
        live_proof = paid_transport_proof(folder, cache, jobs, [singleton_row], False, read, aliases=None)
        assert not live_proof['issues'] and live_proof['originalUnitsChecked'] == 1
        _, _, _, namespace_contract = encode(units, max_units=2, flat_defs=True, alias_pool_size='namespace')
        (cache / 'contract.json').write_text(json.dumps(namespace_contract))
        namespace_wire = copy.deepcopy(alias_canonical)
        for item in namespace_contract['units']:
            namespace_wire[item['name']]['excludedBlocks'][0]['blockId'] = next(iter(item['aliases']))
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(namespace_wire)}}]}))
        namespace_proof = paid_transport_proof(folder, cache, jobs, [row], True, read)
        assert not namespace_proof['issues'] and namespace_proof['originalUnitsChecked'] == 2
        assert all(x['aliasSchemaMode'] == 'namespace' and x['wirePattern'] and x['wireEnumCount'] == 0
                   and x['runtimeCanonicalEnumCount'] == x['actualAliasCount'] == 1
                   for x in namespace_proof['requests'][0]['unitAliasSchemas'])
        namespace_wire['u0']['excludedBlocks'][0]['blockId'] = 'uazzz'
        raw_path.write_text(json.dumps({'choices': [{'message': {'content': json.dumps(namespace_wire)}}]}))
        assert 'batch_alias_decode_failed' in {x['kind'] for x in paid_transport_proof(folder, cache, jobs, [row], True, read)['issues']}
    return {'passed': True, 'checks': ['literal evidence positive', 'unknown source', 'page mismatch',
                                      'bbox mismatch', 'quote mismatch', 'raw source scope',
                                      'sourceSetup shape', 'control characters', 'input immutability',
                                      'display-only math formatting retention', 'changed math detected',
                                      'batched paid provenance positive', 'paid prose mutation detected',
                                      'cross-unit source detected independently of exact raw equality',
                                      'exact namespace aliases decode to unchanged canonical',
                                      'no fake wire enum spellings', 'foreign namespace alias rejected',
                                      'live singleton alias inferred only through exact canonical equality',
                                      'namespace-pattern wire keeps exact runtime source enum',
                                      'pattern-valid but unmapped source alias rejected',
                                      'suspicious inline math tab warning', 'ordinary prose tab unchanged']}


def audit_variant(root, frozen, variant, read, *, critical_pages=CRITICAL_PAGES):
    folder = root / 'runs' / variant
    manifest_paths = sorted(folder.glob('generated/new-concept-v99/*/manifest.json'))
    if len(manifest_paths) != 1:
        return {'variant': variant, 'status': 'pending' if not manifest_paths else 'failed',
                'issues': [{'kind': 'expected_exactly_one_manifest', 'found': len(manifest_paths)}]}
    cache = manifest_paths[0].parent
    manifest = read(manifest_paths[0])
    blocks = read(cache / 'blocks.json')
    plan = read(cache / 'plan.json')
    document = read(folder / 'document.json')
    frozen_cache = frozen
    if not (frozen_cache / 'manifest.json').exists():
        candidates = list(frozen.glob('generated/new-concept-v99/*/manifest.json'))
        if len(candidates) != 1:
            return {'variant': variant, 'status': 'failed',
                    'issues': [{'kind': 'frozen_run_has_no_unique_source_manifest', 'found': len(candidates)}]}
        frozen_cache = candidates[0].parent
    frozen_manifest = read(frozen_cache / 'manifest.json')
    frozen_blocks = read(frozen_cache / 'blocks.json')
    frozen_plan = read(frozen_cache / 'plan.json')
    expected = {block['id']: source(block) for block in frozen_blocks}
    actual = {block['id']: source(block) for block in blocks}
    frozen_jobs = frozen_manifest['jobs']
    jobs = manifest['jobs']
    issue_list = []
    checks = {
        'canonicalBlocksExact': actual == expected and len(blocks) == len(frozen_blocks),
        'canonicalBlockOrderExact': [b['id'] for b in blocks] == [b['id'] for b in frozen_blocks],
        'semanticPlanGroupsExact': plan['groups'] == frozen_plan['groups'],
        'jobIdsAndOrderExact': [j['id'] for j in jobs] == [j['id'] for j in frozen_jobs],
        'jobBlockPayloadsExact': [j['blocks'] for j in jobs] == [j['blocks'] for j in frozen_jobs],
        'sourcePdfByteExact': hashlib.sha256((folder / 'source.pdf').read_bytes()).digest() == hashlib.sha256((frozen / 'source.pdf').read_bytes()).digest(),
        'documentIdentityExact': document.get('documentId') == read(frozen / 'document.json').get('documentId'),
    }
    for name, passed in checks.items():
        if not passed:
            issue_list.append({'kind': 'frozen_source_or_job_mismatch', 'check': name})
    from pdf_group_partition import validate_partition
    try:
        partition = validate_partition(blocks, plan['groups'], require_global_order=False)
    except ValueError as error:
        partition = {'complete': False, 'detail': str(error)}
        issue_list.append({'kind': 'source_partition_invalid', 'detail': str(error)})

    unit_records, critical, missing_outputs = [], [], []
    uncertainty_records = []
    segment_retention = []
    raw_ref_count = evidence_count = setup_count = 0
    all_raw_controls, all_final_controls = [], []
    raw_math_tabs, final_math_tabs = [], []
    for index, job in enumerate(jobs):
        allowed = {b['id']: b for b in job['blocks']}
        pages = sorted({b['page'] for b in job['blocks']})
        reply_path = cache / f'response-{job["id"]}.json'
        unit_path = cache / f'unit-{index:05d}.json'
        reply = read(reply_path) if reply_path.exists() else None
        unit = read(unit_path) if unit_path.exists() else None
        issues, setups = [], []
        if reply is None and not job.get('skip'):
            missing_outputs.append({'kind': 'paid_reply_not_yet_saved', 'jobId': job['id'], 'jobIndex': index})
        if unit is None:
            missing_outputs.append({'kind': 'unit_not_yet_saved', 'jobId': job['id'], 'jobIndex': index})
        if reply is not None:
            refs, setups, raw_errors = raw_issues(reply, allowed)
            raw_ref_count += refs
            setup_count += len(setups)
            issues.extend(raw_errors)
            all_raw_controls.extend({'jobId': job['id'], **item} for item in text_controls(reply))
            raw_math_tabs.extend({'jobId': job['id'], **item} for item in inline_math_tab_warnings(reply))
            scope = uncertainty_scope(reply)
            if scope['wholeRegionUncertaintyCount'] or scope['uncertainStatements']:
                uncertainty_records.append({'jobId': job['id'], 'pages': pages, **scope})
        if unit is not None:
            count, evidence_errors = evidence_issues(unit, allowed, document.get('documentId'))
            evidence_count += count
            issues.extend(evidence_errors)
            if unit.get('unitId') != job['id']:
                issues.append({'kind': 'unit_id_mismatch', 'actual': unit.get('unitId')})
            for item in unit.get('coverage', []):
                if item.get('blockId') not in allowed or item.get('page') != allowed.get(item.get('blockId'), {}).get('page'):
                    issues.append({'kind': 'unit_coverage_out_of_scope', 'item': item})
            all_final_controls.extend({'jobId': job['id'], **item} for item in text_controls(unit))
            final_math_tabs.extend({'jobId': job['id'], **item} for item in inline_math_tab_warnings(unit))
            if reply is not None:
                segment_retention.extend({'jobId': job['id'], **item}
                                         for item in learner_segment_retention(reply, unit))
        record = {'jobIndex': index, 'jobId': job['id'], 'title': job.get('title'), 'pages': pages,
                  'skip': job.get('skip', False), 'rawPresent': reply is not None, 'unitPresent': unit is not None,
                  'rawConcepts': len(reply.get('concepts', [])) if reply is not None else None,
                  'finalConcepts': len(unit.get('concepts', [])) if unit is not None else None,
                  'sourceSetupCount': len(setups), 'issues': issues}
        unit_records.append(record)
        issue_list.extend({'jobId': job['id'], **item} for item in issues)
        if set(pages).intersection(critical_pages) and not job.get('skip'):
            critical.append({**record, 'sourceBlocks': job['blocks'], 'rawResponse': str(reply_path),
                             'unitPath': str(unit_path), 'sourceSetup': setups,
                             'rawConcepts': reply.get('concepts', []) if reply is not None else None,
                             'rawSequences': reply.get('sequences', []) if reply is not None else None,
                             'rawTables': reply.get('tables', []) if reply is not None else None,
                             'rawUncertainBlocks': reply.get('uncertainBlocks', []) if reply is not None else None,
                             'finalSummaryParts': unit.get('summary', {}).get('parts', []) if unit is not None else None,
                             'finalConceptCards': unit.get('concepts', []) if unit is not None else None,
                             'finalCoverage': unit.get('coverage', []) if unit is not None else None,
                             'localDiagnostics': unit.get('processingDiagnostics', []) if unit is not None else None,
                             'manualReviewStatus': 'pending_human_source_comparison'})
    run_path, result_path = folder / 'run.json', folder / 'result.json'
    run = read(run_path, volatile=True) if run_path.exists() else None
    result = read(result_path, volatile=True) if result_path.exists() else None
    completed = run is not None
    if completed:
        if run.get('error'):
            issue_list.append({'kind': 'experiment_run_error', 'error': run['error'], 'detail': run.get('detail')})
        if result is None:
            issue_list.append({'kind': 'completed_run_has_no_result'})
        issue_list.extend(missing_outputs)
    final_coverage = None
    if result is not None:
        count, final_errors = evidence_issues(result, {b['id']: b for b in blocks}, document.get('documentId'))
        issue_list.extend({'stage': 'assembled_result', **item} for item in final_errors)
        ids = [item.get('blockId') for item in result.get('coverage', [])]
        final_coverage = {'counts': dict(Counter(item.get('state') for item in result.get('coverage', []))),
                          'sourceBlockCount': len(blocks), 'coverageCount': len(ids),
                          'missingIds': sorted(set(expected) - set(ids)), 'unknownIds': sorted(set(ids) - set(expected)),
                          'duplicateIds': [key for key, value in Counter(ids).items() if value > 1],
                          'needsReviewPages': sorted({item['page'] for item in result.get('coverage', []) if item.get('state') == 'needs_review'}),
                          'needsReviewReasons': dict(Counter(item.get('reason') for item in result.get('coverage', []) if item.get('state') == 'needs_review')),
                          'processingComplete': result.get('processingComplete'),
                          'coverageComplete': result.get('coverageComplete'),
                          'failedUnits': result.get('failedUnits', []), 'finalEvidenceObjectsChecked': count}
        if (final_coverage['missingIds'] or final_coverage['unknownIds'] or final_coverage['duplicateIds']
                or result.get('processingComplete') is not True or result.get('failedUnits')):
            issue_list.append({'kind': 'assembled_result_incomplete_or_source_coverage_invalid'})
    ledger_summary, all_ledger_rows = [], []
    for path in sorted((folder / 'usage').glob('*.json')):
        ledger = read(path, volatile=not completed)
        rows = ledger.get('requests', [])
        all_ledger_rows.extend(rows)
        kinds = Counter(row.get('kind') for row in rows)
        states = Counter(row.get('state') for row in rows)
        ledger_summary.append({'path': str(path), 'category': ledger.get('category'),
                               'requests': len(rows), 'kinds': dict(kinds), 'states': dict(states),
                               'usageBasedUsd': sum(row.get('estimatedUsd', 0) for row in rows),
                               'reasoningEfforts': dict(Counter(row.get('reasoningEffort') for row in rows if row.get('kind') == 'region_study'))})
        if kinds.get('region_plan'):
            issue_list.append({'kind': 'unexpected_paid_planning_call_in_same_plan_experiment'})
        if completed and any(state != 'settled' for state in states):
            issue_list.append({'kind': 'unsettled_or_failed_paid_request', 'states': dict(states)})
    transport = paid_transport_proof(folder, cache, jobs, all_ledger_rows, completed, read,
                                    aliases=bool(run.get('aliases')) if run else None)
    issue_list.extend({'stage': 'paid_transport', **item} for item in transport['issues'])
    memberships = {job_id: {'requestId': record['requestId'], 'isBatch': record['isBatch'],
                            'siblingUnitIds': [key for key in record['unitIds'] if key != job_id]}
                   for record in transport['requests'] for job_id in record['unitIds']}
    for sample in critical:
        sample['transportMembership'] = memberships.get(sample['jobId'])
    return {'variant': variant, 'status': ('failed' if issue_list else 'automatic_checks_passed_manual_pending' if completed else 'partial_in_progress'),
            'cache': str(cache), 'checks': checks, 'partition': partition,
            'counts': {'jobs': len(jobs), 'paidJobs': sum(not j.get('skip') for j in jobs),
                       'rawReplies': sum(record['rawPresent'] for record in unit_records),
                       'savedUnits': sum(record['unitPresent'] for record in unit_records),
                       'rawSourceReferencesChecked': raw_ref_count, 'unitEvidenceObjectsChecked': evidence_count,
                       'sourceSetupsChecked': setup_count},
            'sourceSetupScope': 'Each concept remains scoped to its frozen job canonical source map. Shape and source-ID ownership are checked automatically; model-written observation truth/omission is only manually judged on critical samples.',
            'runComplete': completed, 'runMetadata': run, 'finalCoverage': final_coverage,
            'paidTransportIntegrity': transport,
            'uncertaintyScope': {
                'wholeRegionStatements': sum(x['wholeRegionUncertaintyCount'] for x in uncertainty_records),
                'paragraphUncertaintyStatements': sum(len(x['uncertainStatements']) for x in uncertainty_records),
                'sameRegionParagraphUncertaintyStatements': sum(x['sameRegionStatementCount'] for x in uncertainty_records),
                'jobs': uncertainty_records,
                'interpretation': 'Shared source IDs show the wire expresses uncertainty at a statement level while retaining some teaching from that region. They do not prove the supported or uncertain model claims are true. Compare source images and actual learner retention on sampled cases.'},
            'learnerSegmentRetention': {
                'checked': len(segment_retention),
                'retainedModuloDisplayWhitespace': sum(x['retainedInLearnerModuloDisplayWhitespace'] for x in segment_retention),
                'notFoundWarnings': [x for x in segment_retention if not x['retainedInLearnerModuloDisplayWhitespace']],
                'interpretation': 'Unsupported/malformed segments may be intentionally rejected by the production validator. These warnings require raw-to-validator-to-learner review; they are not automatically classified as data loss. Private sourceSetup and uncertainty are intentionally outside this learner-prose check.'},
            'ledgerSummary': ledger_summary, 'pendingOutputs': [] if completed else missing_outputs,
            'issues': issue_list, 'rawControlWarnings': all_raw_controls, 'materializedControlWarnings': all_final_controls,
            'inlineMathTabWarnings': {'raw': raw_math_tabs, 'materialized': final_math_tabs},
            'jobs': unit_records, 'criticalPageSamples': critical,
            'manualCriteria': {
                '15': ['f(n)=a_n and lim(x→∞)f(x)=L imply lim(n→∞)a_n=L with conditions retained',
                       'No malformed newline/TeX infinity token; raw versus validator versus learner compared separately'],
                '76': ['s_(2n)=h_(2n)−h_n and logarithmic limit argument',
                       'Original alternating harmonic sum ln2 and two-positive/one-negative rearrangement3/2ln2',
                       'Positive and negative subseries separately diverge; do not assign finite2ln2/ln2 values or inconsistent subtraction',
                       'Distinguish missing per-block accounting from sequence-cited source teaching'],
                '88': ['Keep p-series/limit-comparison continuation separate from integral-test/exponential-decay example',
                       'Record source-title mismatch and uncertainty honestly; no inferred insertion to force apparent completeness'],
            },
            'selectedCriticalPages': list(critical_pages),
            'limitations': ['Automatic reference and partition checks are not a factual/math correctness certificate.',
                            'Fresh generation need not be word-for-word identical; semantic statements, conditions, formulas and source scope require manual comparison.',
                            'A running experiment is a partial snapshot; missing files are pending until run.json exists.']}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--frozen', type=Path)
    parser.add_argument('--variant', nargs='+')
    parser.add_argument('--critical-pages', nargs='+', type=int, default=list(CRITICAL_PAGES))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    tests = self_test()
    if args.self_test and args.root is None:
        print(json.dumps(tests))
        return 0
    if args.root is None:
        parser.error('--root is required for experiment QA')
    network_attempts = 0

    def blocked(*unused, **unused_keywords):
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError('No network is permitted in this verifier')

    socket.socket = blocked
    socket.create_connection = blocked
    root = args.root.resolve()
    frozen = (args.frozen or root / 'frozen-source').resolve()
    if root.is_relative_to(Path('/Users/c4t/SYNESIS Data/library')):
        parser.error('Audit output must not be placed in the user library')
    inputs = {}
    volatile_inputs = set()

    def read(path, *, volatile=False):
        path = Path(path)
        content = path.read_bytes()
        if volatile:
            # The running producer may legitimately update its own ledger.
            # This verifier never writes any of those inputs.
            volatile_inputs.add(str(path))
        else:
            inputs[str(path)] = hashlib.sha256(content).hexdigest()
        return json.loads(content)

    variants = args.variant or sorted(path.name for path in (root / 'runs').iterdir() if path.is_dir())
    output = root / 'quality'
    output.mkdir(exist_ok=True, parents=True)
    results = []
    for variant in variants:
        if not re.fullmatch(r'[A-Za-z0-9-]+', variant):
            parser.error('Variant must be a simple directory name')
        report = audit_variant(root, frozen, variant, read, critical_pages=args.critical_pages)
        manual_path = output / f'{variant}-manual.json'
        if manual_path.exists():
            report['manualSampleReview'] = read(manual_path)
            report['manualSampleReviewPath'] = str(manual_path)
            if report['status'] == 'automatic_checks_passed_manual_pending':
                report['status'] = 'automatic_checks_passed_manual_sample_review_attached'
        report['verification'] = {'apiCalls': 0, 'networkAttempts': network_attempts,
                                  'productionAndUserDataFilesModifiedByVerifier': 0,
                                  'volatileProducerFilesRead': sorted(volatile_inputs),
                                  'selfTests': tests}
        path = output / f'{variant}-source-quality.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        results.append({'variant': variant, 'status': report['status'], 'report': str(path),
                        'counts': report.get('counts'), 'issues': len(report.get('issues', []))})
    changed = [path for path, sha in inputs.items() if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha]
    final = {'variants': results, 'apiCalls': 0, 'networkAttempts': network_attempts,
             'protectedInputsCompared': len(inputs), 'changingInputsObserved': changed,
             'volatileProducerFilesRead': sorted(volatile_inputs),
             'note': 'Live producer changes are distinct from verifier writes; all verifier outputs stay under root/quality.'}
    (output / 'source-quality-index.json').write_text(json.dumps(final, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(final, ensure_ascii=False))
    return 1 if network_attempts or changed or any(row['status'] == 'failed' for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
