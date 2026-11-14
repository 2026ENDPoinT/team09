"""Offline experiment: shared request transport never merges original units."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
import pdf_study_batch_transport as batch
from pdf_study_batch_transport import BatchTransportError, RULES, decode, decode_each, encode
from pdf_study_cache_reuse import constrained_format


def fixture(index, image_count=1):
    literal = ('u0 u1 v2p1f0 a: sourceSetup stays literal; '
               r'\(x_{i+1}=x_i-1\), code {"blockId":"u1"}')
    ids = [f'v2p{index + 1}f{i}' for i in range(2)]
    blocks = [{'id': key, 'page': index + 1, 'kind': 'text', 'planRole': 'teaching',
               'bbox': [.1, .1 + i * .25, .9, .3 + i * .25], 'hasVisual': False,
               'text': f'{index + 1} 주제 {i + 1}: 조건이 바뀌면 결과가 달라져요. ' + literal}
              for i, key in enumerate(ids)]
    job = {'id': f'job-{index}', 'title': f'독립 주제 {index + 1}', 'blocks': blocks}
    crops = [{'page': index + 1, 'blockIds': list(ids)} for _ in range(image_count)]
    payload = study.teaching_payload(job, crops, {'pageCount': 2, 'pageCues': [literal]},
                                     [{'side': 'before', 'text': f'Only neighbor {index}: ' + literal}])
    payload['entryHints'] = [{'title': f'{index} 단위 시작점', 'startsAt': ids[0]}]
    payload['headingOptions'] = [{'id': f'h:{ids[0]}', 'title': literal}]
    images = [{'width': 100 + i, 'height': 120 + i,
               'data': f'data:image/webp;base64,original-{index}-{i}',
               'sourceLabel': f'Original image {index} {i}'} for i in range(image_count)]
    return {'job': job, 'payload': payload, 'response_format': study.STUDY_FORMAT, 'images': images}


def reply(unit, *, all_fields=False):
    ids = [block['id'] for block in unit['job']['blocks']]
    literal = unit['payload']['blocks'][0]['text']
    title = unit['job']['title']
    value = {'concepts': [{'title': title,
                          'sourceSetup': {'observedRelations': [literal], 'boundaryChecks': [literal],
                                          'interpretation': literal},
                          'segments': [
                              {'kind': 'definition', 'text': '조건에 따라 결과가 달라지는 원리예요.', 'blockIds': ids[:1]},
                              {'kind': 'explanation', 'text': '입력 조건을 먼저 확인하면 결과의 차이를 설명할 수 있어요. ' + literal,
                               'blockIds': ids},
                              {'kind': 'easyExplanation', 'text': '같은 조건끼리 비교한 뒤 달라진 조건을 확인해요.', 'blockIds': ids}],
                          'standardKnowledgeUsed': False}],
             'sequences': [], 'tables': [], 'excludedBlocks': [], 'uncertainBlocks': []}
    if all_fields:
        value['tables'] = [{'conceptTitle': title, 'headers': ['u0', 'u1'],
                            'rows': [[ids[0], literal]], 'blockIds': ids}]
        value['sequences'] = [{'conceptTitle': title, 'title': literal, 'orderKind': 'procedure',
                              'steps': [{'title': literal, 'body': literal, 'blockIds': [ids[0]]}],
                              'transitions': [{'fromStep': 0, 'toStep': 1, 'relation': literal,
                                               'blockIds': ids, 'sourceQuote': literal}]}]
        value['excludedBlocks'] = [{'blockId': ids[0], 'reason': literal, 'referenceContext': None}]
        value['uncertainBlocks'] = [{'blockId': ids[1], 'reason': literal}]
    return value


def alias_reply(raw, mapping):
    """Fixture-only forward map of schema citation slots; prose is untouched."""
    value = copy.deepcopy(raw)
    forward = {source: alias for alias, source in mapping.items()}
    def walk(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == 'blockIds':node[key] = [forward[source] for source in item]
                elif key == 'blockId':node[key] = forward[item]
                elif isinstance(item, (dict, list)):walk(item)
        elif isinstance(node, list):
            for item in node:walk(item)
    walk(value)
    return value


class StudyBatchTransportTests(unittest.TestCase):
    def setUp(self):
        # No provider is instantiated, but guard networking against accidental
        # future fixture changes as these tests may run while real experiments run.
        self.guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network in transport tests'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_payload_and_images_round_trip_without_any_content_change(self):
        units = [fixture(0, 2), fixture(1, 2)]
        before = copy.deepcopy(units)
        payload, format, images, contract = encode(units)
        self.assertEqual(payload, {'task': 'region_teaching_batch',
            'units': {'u0': units[0]['payload'], 'u1': units[1]['payload']},
            'imageOrder': [{'unit': 'u0', 'cropIndex': 0}, {'unit': 'u0', 'cropIndex': 1},
                           {'unit': 'u1', 'cropIndex': 0}, {'unit': 'u1', 'cropIndex': 1}]})
        self.assertEqual(images, units[0]['images'] + units[1]['images'])
        self.assertNotEqual(payload['units']['u0']['titleHint'], payload['units']['u1']['titleHint'])
        self.assertNotEqual(payload['units']['u0']['neighboringContext'], payload['units']['u1']['neighboringContext'])
        self.assertEqual(units, before)
        raw = {'u0': reply(units[0], all_fields=True), 'u1': reply(units[1], all_fields=True)}
        raw_before, contract_before = copy.deepcopy(raw), copy.deepcopy(contract)
        self.assertEqual(decode(raw, contract), [raw['u0'], raw['u1']])
        self.assertEqual(decode(json.dumps(raw, ensure_ascii=False), contract), [raw['u0'], raw['u1']])
        self.assertEqual(raw, raw_before)
        self.assertEqual(contract, contract_before)
        # Returned data is independent as well as lossless.
        payload['units']['u0']['blocks'][0]['text'] = 'only returned request'
        images[0]['data'] = 'only returned image'
        decoded = decode(raw, contract)
        decoded[0]['concepts'][0]['segments'][0]['text'] = 'only returned response'
        self.assertEqual(units, before)
        self.assertEqual(raw, raw_before)
        self.assertTrue(format['json_schema']['strict'])
        self.assertIn('Never merge', RULES)

    def test_fixed_disjoint_alias_pools_round_trip_exact_prose_sources_and_images(self):
        units = [fixture(0, 2), fixture(1, 2)]
        for unit in units:
            for image in unit['images']:image.pop('sourceLabel')
        before = copy.deepcopy(units)
        payload, format, images, contract = encode(units, alias_pool_size=32, flat_defs=True)
        self.assertEqual(images, units[0]['images']+units[1]['images'])
        canonical = {f'u{i}': reply(unit, all_fields=True) for i, unit in enumerate(units)}
        raw = {f'u{i}': alias_reply(canonical[f'u{i}'], contract['units'][i]['aliases'])
               for i in range(2)}
        self.assertEqual(decode(raw, contract), list(canonical.values()))
        records, errors = decode_each(json.dumps(raw), contract)
        self.assertEqual(errors, [])
        self.assertEqual([row['raw'] for row in records], list(canonical.values()))
        for i in range(2):
            owner = contract['units'][i];name = f'u{i}'
            aliases = owner['aliases']
            self.assertTrue(all(key.startswith(('ua','ub')[i]) for key in aliases))
            self.assertEqual(owner['sourceIds'], [b['id'] for b in units[i]['job']['blocks']])
            expected = constrained_format(units[i]['response_format'], units[i]['job'])['json_schema']['schema']
            self.assertEqual(owner['schema'], expected)
            restored = copy.deepcopy(payload['units'][name])
            for block in restored['blocks']:block['id'] = aliases[block['id']]
            for hint in restored['entryHints']:hint['startsAt'] = aliases[hint['startsAt']]
            for crop in restored['crops']:crop['blockIds'] = [aliases[key] for key in crop['blockIds']]
            self.assertEqual(restored, units[i]['payload'])
            self.assertEqual(len(owner['wireSchema']['$defs']['studySourceId']['enum']), 32)
            self.assertEqual(owner['wireSchema']['$defs']['studySourceId']['enum'][0], ('uaa','uba')[i])
        self.assertEqual(units, before)
        self.assertEqual(format['json_schema']['schema']['$defs']['u0__studySourceId'],
                         contract['units'][0]['wireSchema']['$defs']['studySourceId'])

    def test_alias_unused_cross_namespace_and_canonical_wire_references_fail_closed(self):
        units = [fixture(0, 0), fixture(1, 0)]
        _, _, _, contract = encode(units, alias_pool_size=32)
        original = {f'u{i}': alias_reply(reply(unit), contract['units'][i]['aliases'])
                    for i, unit in enumerate(units)}
        for invalid in ('uac', 'uaaf', 'uba', units[0]['job']['blocks'][0]['id']):
            with self.subTest(reference=invalid):
                raw = copy.deepcopy(original)
                raw['u0']['concepts'][0]['segments'][0]['blockIds'] = [invalid]
                with self.assertRaises(BatchTransportError):decode(raw, contract)
                records, errors = decode_each(raw, contract)
                self.assertEqual([row['name'] for row in records], ['u1'])
                self.assertEqual(records[0]['raw'], reply(units[1]))
                self.assertEqual([row['index'] for row in errors], [0])
        for mutation in ('mapping_owner', 'mapping_namespace', 'relaxed_wire', 'canonical_enum',
                         'wire_definitions_type', 'wire_source_type'):
            with self.subTest(contract=mutation):
                broken = copy.deepcopy(contract);owner = broken['units'][0]
                if mutation == 'mapping_owner':owner['aliases']['uaa'] = units[1]['job']['blocks'][0]['id']
                if mutation == 'mapping_namespace':owner['aliases']['uba'] = owner['aliases'].pop('uaa')
                if mutation == 'relaxed_wire':owner['wireSchema']['additionalProperties'] = True
                if mutation == 'canonical_enum':owner['schema']['$defs']['studySourceId']['enum'].reverse()
                if mutation == 'wire_definitions_type':owner['wireSchema']['$defs'] = []
                if mutation == 'wire_source_type':owner['wireSchema']['$defs']['studySourceId'] = None
                with self.assertRaises(BatchTransportError):decode_each(original, broken)

    def test_alias_pool_schema_is_identical_across_actual_source_counts(self):
        formats = []
        for count in (1, 2, 22, 32):
            units = [fixture(0, 0), fixture(1, 0)]
            for index, unit in enumerate(units):
                blocks = [{**unit['job']['blocks'][0], 'id': f'source{index}block{n}'} for n in range(count)]
                unit['job']['blocks'] = blocks
                unit['payload']['blocks'] = copy.deepcopy(blocks)
                unit['payload']['entryHints'] = []
            _, format, _, contract = encode(units, alias_pool_size=32, flat_defs=True)
            formats.append(format)
            self.assertEqual([len(unit['aliases']) for unit in contract['units']], [count, count])
        self.assertTrue(all(format == formats[0] for format in formats))

    def test_batch_aliases_opt_out_on_image_labels_or_insufficient_invalid_pool(self):
        units = [fixture(0), fixture(1)]
        with self.assertRaises(BatchTransportError):encode(units, alias_pool_size=32)
        units = [fixture(0, 0), fixture(1, 0)]
        for value in (True, False, 0, -1, '32', 32., 1, 'Exact', 'EXACT', ' exact', 'exact ', '', [], {}):
            with self.subTest(pool=value), self.assertRaises(BatchTransportError):encode(units, alias_pool_size=value)
        self.assertEqual(encode(units), encode(units, alias_pool_size=None))

    def test_exact_alias_pool_contains_only_each_units_actual_sources(self):
        units = [fixture(0, 0), fixture(1, 0), fixture(2, 0), fixture(3, 0)]
        units[0]['job']['blocks'] = units[0]['job']['blocks'][:1]
        units[0]['payload']['blocks'] = units[0]['payload']['blocks'][:1]
        before = copy.deepcopy(units)
        payload, _, images, contract = encode(units, max_units=4, max_images=16,
                                              alias_pool_size='exact', flat_defs=True)
        self.assertEqual(images, [])
        canonical = {f'u{i}': reply(unit) for i, unit in enumerate(units)}
        raw = {f'u{i}': alias_reply(canonical[f'u{i}'], owner['aliases'])
               for i, owner in enumerate(contract['units'])}
        for i, owner in enumerate(contract['units']):
            pool = owner['wireSchema']['$defs']['studySourceId']['enum']
            self.assertEqual(pool, list(owner['aliases']))
            self.assertEqual(len(pool), len(units[i]['job']['blocks']))
            self.assertEqual([block['id'] for block in payload['units'][f'u{i}']['blocks']], pool)
        self.assertEqual(decode(raw, contract), list(canonical.values()))
        records, errors = decode_each(raw, contract)
        self.assertEqual(errors, [])
        self.assertEqual([row['raw'] for row in records], list(canonical.values()))
        self.assertEqual(units, before)
        # A model cannot enumerate unused pool IDs: there are none in the enum.
        raw['u0']['excludedBlocks'] = [{'blockId': 'uab', 'reason': 'Unused source'}]
        with self.assertRaises(BatchTransportError):decode(raw, contract)
        records, errors = decode_each(raw, contract)
        self.assertEqual([row['name'] for row in records], ['u1', 'u2', 'u3'])
        self.assertEqual([row['index'] for row in errors], [0])

    def test_namespace_pattern_changes_only_the_wire_source_definition_from_exact_aliases(self):
        units=[fixture(0,2),fixture(1,2)]
        for unit in units:
            for image in unit['images']:image.pop('sourceLabel')
        before=copy.deepcopy(units)
        exact=encode(units,alias_pool_size='exact',flat_defs=True)
        patterned=encode(units,alias_pool_size='namespace',flat_defs=True)
        self.assertEqual((patterned[0],patterned[2]),(exact[0],exact[2]))
        expected_format=copy.deepcopy(exact[1]);expected_contract=copy.deepcopy(exact[3])
        for i,owner in enumerate(expected_contract['units']):
            definition={'type':'string','pattern':'^u'+chr(ord('a')+i)+'[a-z]+$'}
            expected_format['json_schema']['schema']['$defs'][f'u{i}__studySourceId']=definition
            owner['wireSchema']['$defs']['studySourceId']=copy.deepcopy(definition)
            owner['aliasSchemaMode']='namespace'
        self.assertEqual(patterned[1],expected_format)
        self.assertEqual(patterned[3],expected_contract)
        canonical={f'u{i}':reply(unit,all_fields=True) for i,unit in enumerate(units)}
        wire={name:alias_reply(raw,patterned[3]['units'][i]['aliases'])
              for i,(name,raw) in enumerate(canonical.items())}
        batch._validate(wire,patterned[1]['json_schema']['schema'],patterned[1]['json_schema']['schema'])
        self.assertEqual(decode(wire,patterned[3]),list(canonical.values()))
        records,errors=decode_each(json.dumps(wire),patterned[3])
        self.assertEqual(errors,[])
        self.assertEqual([record['raw'] for record in records],list(canonical.values()))
        self.assertEqual(units,before)
        self.assertNotIn('aliasSchemaMode',exact[3]['units'][0])

    def test_namespace_schema_is_static_without_enumerating_unused_ids_across_source_counts(self):
        formats=[]
        for count in (1,2,22,32,33,65):
            units=[fixture(0,0),fixture(1,0)]
            for i,unit in enumerate(units):
                blocks=[{**unit['job']['blocks'][0],'id':f'canonical{i}block{n}'} for n in range(count)]
                unit['job']['blocks']=blocks
                unit['payload']['blocks']=copy.deepcopy(blocks)
                unit['payload']['entryHints']=[]
            _,format,_,contract=encode(units,alias_pool_size='namespace',flat_defs=True)
            formats.append(format)
            for i,owner in enumerate(contract['units']):
                definition=owner['wireSchema']['$defs']['studySourceId']
                self.assertEqual(definition,{'type':'string','pattern':'^u'+chr(ord('a')+i)+'[a-z]+$'})
                self.assertNotIn('enum',definition)
                self.assertEqual(len(owner['aliases']),count)
                self.assertEqual(len(owner['schema']['$defs']['studySourceId']['enum']),count)
                if count>26:self.assertIn('u'+chr(ord('a')+i)+'aa',owner['aliases'])
        self.assertTrue(all(format==formats[0] for format in formats))

    def test_namespace_decoder_rejects_ghost_cross_unit_and_noncanonical_references_in_every_slot(self):
        units=[fixture(0,0),fixture(1,0)]
        _,_,_,contract=encode(units,alias_pool_size='namespace')
        canonical={f'u{i}':reply(unit,all_fields=True) for i,unit in enumerate(units)}
        original={name:alias_reply(raw,contract['units'][i]['aliases'])
                  for i,(name,raw) in enumerate(canonical.items())}
        # The static pattern intentionally admits namespace spellings; the real
        # mapping still rejects every unprovided source after wire shape checks.
        ghost=copy.deepcopy(original['u0'])
        ghost['concepts'][0]['segments'][0]['blockIds']=['uaaf']
        schema=contract['units'][0]['wireSchema']
        batch._validate(ghost,schema,schema)
        for location in ('segment','table','step','transition','excluded','uncertain'):
            for invalid in ('uac','uaaf','uba','uda',units[0]['job']['blocks'][0]['id'],'ua','uAA','uaa\n'):
                with self.subTest(location=location,source=invalid):
                    raw=copy.deepcopy(original);unit=raw['u0']
                    if location=='segment':unit['concepts'][0]['segments'][0]['blockIds']=[invalid]
                    if location=='table':unit['tables'][0]['blockIds']=[invalid]
                    if location=='step':unit['sequences'][0]['steps'][0]['blockIds']=[invalid]
                    if location=='transition':unit['sequences'][0]['transitions'][0]['blockIds']=[invalid]
                    if location=='excluded':unit['excludedBlocks'][0]['blockId']=invalid
                    if location=='uncertain':unit['uncertainBlocks'][0]['blockId']=invalid
                    before=copy.deepcopy((raw,contract))
                    with self.assertRaises(BatchTransportError):decode(raw,contract)
                    valid,errors=decode_each(raw,contract)
                    self.assertEqual([(record['index'],record['name']) for record in valid],[(1,'u1')])
                    self.assertEqual(valid[0]['raw'],canonical['u1'])
                    self.assertEqual([error['index'] for error in errors],[0])
                    self.assertEqual((raw,contract),before)

    def test_namespace_contract_requires_explicit_mode_and_exact_deterministic_reconstruction(self):
        units=[fixture(0,0),fixture(1,0)]
        _,_,_,contract=encode(units,alias_pool_size='namespace')
        raw={f'u{i}':alias_reply(reply(unit),contract['units'][i]['aliases']) for i,unit in enumerate(units)}
        for mutation in ('missing_mode','unknown_mode','exact_mode','relaxed_pattern','wrong_namespace',
                         'reinserted_enum','extra_pattern_keyword','changed_body_schema','mapping_owner','missing_mapping'):
            with self.subTest(mutation=mutation):
                broken=copy.deepcopy(contract);owner=broken['units'][1]
                if mutation=='missing_mode':owner.pop('aliasSchemaMode')
                if mutation=='unknown_mode':owner['aliasSchemaMode']='namespaces'
                if mutation=='exact_mode':owner['aliasSchemaMode']='exact'
                if mutation=='relaxed_pattern':owner['wireSchema']['$defs']['studySourceId']['pattern']='^[a-z]+$'
                if mutation=='wrong_namespace':owner['wireSchema']['$defs']['studySourceId']['pattern']='^ua[a-z]+$'
                if mutation=='reinserted_enum':owner['wireSchema']['$defs']['studySourceId']={'type':'string','enum':list(owner['aliases'])}
                if mutation=='extra_pattern_keyword':owner['wireSchema']['$defs']['studySourceId']['minLength']=3
                if mutation=='changed_body_schema':owner['wireSchema']['additionalProperties']=True
                if mutation=='mapping_owner':owner['aliases']['uba']=units[0]['job']['blocks'][0]['id']
                if mutation=='missing_mapping':owner.pop('aliases')
                # Even u0 cannot escape before the entire local contract passes.
                with self.assertRaises(BatchTransportError):decode_each(raw,broken)
        legacy=encode(units)[3];legacy['units'][0]['aliasSchemaMode']='namespace'
        with self.assertRaises(BatchTransportError):decode_each({'u0':reply(units[0]),'u1':reply(units[1])},legacy)

    def test_namespace_mode_supports_four_disjoint_owners_and_preserves_exact_fixed_backcompat(self):
        units=[fixture(i,0) for i in range(4)]
        before=copy.deepcopy(units)
        _,_,_,contract=encode(units,max_units=4,alias_pool_size='namespace',flat_defs=True)
        raw={f'u{i}':alias_reply(reply(unit),contract['units'][i]['aliases']) for i,unit in enumerate(units)}
        for i,owner in enumerate(contract['units']):
            self.assertEqual(owner['wireSchema']['$defs']['studySourceId']['pattern'],'^u'+chr(ord('a')+i)+'[a-z]+$')
        self.assertEqual(decode(raw,contract),[reply(unit) for unit in units])
        self.assertEqual(units,before)
        for mode in ('exact',32):
            _,_,_,legacy=encode(units,max_units=4,alias_pool_size=mode)
            wire={f'u{i}':alias_reply(reply(unit),legacy['units'][i]['aliases']) for i,unit in enumerate(units)}
            self.assertEqual(decode(wire,legacy),[reply(unit) for unit in units])
            self.assertTrue(all('aliasSchemaMode' not in owner for owner in legacy['units']))
        for invalid in ('Namespace','NAMESPACE',' namespace','namespace ',True,False):
            with self.subTest(mode=invalid),self.assertRaises(BatchTransportError):encode(units[:2],alias_pool_size=invalid)

    def test_each_unit_retains_the_exact_original_constrained_schema(self):
        units = [fixture(0), fixture(1)]
        _, format, _, contract = encode(units)
        schema = format['json_schema']['schema']
        self.assertEqual(schema['required'], ['u0', 'u1'])
        self.assertFalse(schema['additionalProperties'])
        for i, unit in enumerate(units):
            name = f'u{i}'
            expected = constrained_format(study.STUDY_FORMAT, unit['job'])['json_schema']['schema']
            actual = copy.deepcopy(schema['$defs'][name])
            def restore(node):
                if isinstance(node, dict):
                    if '$ref' in node:
                        self.assertTrue(node['$ref'].startswith(f'#/$defs/{name}'))
                        node['$ref'] = '#' + node['$ref'][len(f'#/$defs/{name}'):]
                    for child in node.values():restore(child)
                elif isinstance(node, list):
                    for child in node:restore(child)
            restore(actual)
            self.assertEqual(actual, expected)
            self.assertEqual(contract['units'][i]['schema'], expected)
            self.assertEqual(schema['properties'][name], {'$ref': f'#/$defs/{name}'})
        self.assertNotEqual(schema['$defs']['u0']['$defs']['studySourceId']['enum'],
                            schema['$defs']['u1']['$defs']['studySourceId']['enum'])

    def test_original_validator_receives_identical_unit_replies(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        document = {'documentId': 'synthetic-pair', 'fingerprint': 'offline',
                    'pages': [{'number': i + 1, 'label': str(i + 1), 'nativeText': ''} for i in range(2)]}
        raw = {'u0': reply(units[0]), 'u1': reply(units[1])}
        for i, split in enumerate(decode(raw, contract)):
            direct = study.validate(raw[f'u{i}'], units[i]['job'], document)
            through_batch = study.validate(split, units[i]['job'], document)
            self.assertEqual(through_batch, direct)
            self.assertTrue(through_batch['concepts'])
            self.assertEqual({item['state'] for item in through_batch['coverage']}, {'summarized'})

    def test_original_context_and_literal_ids_are_never_recursively_rewritten(self):
        units = [fixture(0), fixture(1)]
        payload, _, _, contract = encode(units)
        raw = {'u0': reply(units[0], all_fields=True), 'u1': reply(units[1], all_fields=True)}
        outputs = decode(raw, contract)
        for i, output in enumerate(outputs):
            self.assertEqual(payload['units'][f'u{i}'], units[i]['payload'])
            self.assertEqual(output, raw[f'u{i}'])
            self.assertIn('"blockId":"u1"', output['concepts'][0]['sourceSetup']['interpretation'])
            self.assertIn(r'\(x_{i+1}=x_i-1\)', output['sequences'][0]['transitions'][0]['sourceQuote'])

    def test_zero_images_and_already_constrained_formats_are_supported(self):
        units = [fixture(0, 0), fixture(1, 0)]
        for unit in units:unit['response_format'] = constrained_format(study.STUDY_FORMAT, unit['job'])
        before = copy.deepcopy(units)
        payload, _, images, contract = encode(units)
        self.assertEqual(images, [])
        self.assertEqual(payload['imageOrder'], [])
        self.assertEqual(decode({'u0': reply(units[0]), 'u1': reply(units[1])}, contract),
                         [reply(units[0]), reply(units[1])])
        self.assertEqual(units, before)

    def test_pair_size_image_limit_and_crop_ownership_are_strict(self):
        for units in ([], [fixture(0)], [fixture(0), fixture(1), fixture(2)], [fixture(0, 3), fixture(1, 2)]):
            with self.subTest(size=len(units)), self.assertRaises(BatchTransportError):encode(units)
        for mutation in ('image_missing', 'crop_missing', 'cross_crop', 'empty_crop', 'unknown_hint',
                         'duplicate_job', 'same_sources', 'payload_missing', 'payload_duplicate', 'empty_job'):
            with self.subTest(mutation=mutation):
                units = [fixture(0), fixture(1)]
                if mutation == 'image_missing':units[0]['images'] = []
                if mutation == 'crop_missing':units[0]['payload']['crops'] = []
                if mutation == 'cross_crop':units[0]['payload']['crops'][0]['blockIds'] = [units[1]['job']['blocks'][0]['id']]
                if mutation == 'empty_crop':units[0]['payload']['crops'][0]['blockIds'] = []
                if mutation == 'unknown_hint':units[0]['payload']['entryHints'][0]['startsAt'] = 'unknown'
                if mutation == 'duplicate_job':units[1]['job']['id'] = units[0]['job']['id']
                if mutation == 'same_sources':units[1] = copy.deepcopy(units[0]); units[1]['job']['id'] = 'different-job'
                if mutation == 'payload_missing':units[0]['payload']['blocks'].pop()
                if mutation == 'payload_duplicate':units[0]['payload']['blocks'][1]['id'] = units[0]['payload']['blocks'][0]['id']
                if mutation == 'empty_job':units[0]['job']['blocks'] = []
                before = copy.deepcopy(units)
                with self.assertRaises(BatchTransportError):encode(units)
                self.assertEqual(units, before)

    def test_missing_unknown_swapped_and_malformed_unit_outputs_are_rejected(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        for mutation in ('missing', 'unknown', 'swapped', 'null_unit', 'missing_array', 'unknown_field', 'unknown_segment_field',
                         'missing_reference', 'string_reference', 'wrong_segment_type'):
            with self.subTest(mutation=mutation):
                raw = {'u0': reply(units[0]), 'u1': reply(units[1])}
                if mutation == 'missing':raw.pop('u1')
                if mutation == 'unknown':raw['u2'] = raw['u1']
                if mutation == 'swapped':raw['u0'], raw['u1'] = raw['u1'], raw['u0']
                if mutation == 'null_unit':raw['u1'] = None
                if mutation == 'missing_array':raw['u0'].pop('tables')
                if mutation == 'unknown_field':raw['u0']['newMetadata'] = 'not in original format'
                if mutation == 'unknown_segment_field':raw['u0']['concepts'][0]['segments'][0]['other'] = 'unknown'
                if mutation == 'missing_reference':raw['u0']['concepts'][0]['segments'][0].pop('blockIds')
                if mutation == 'string_reference':raw['u0']['concepts'][0]['segments'][0]['blockIds'] = 'v2p1f0'
                if mutation == 'wrong_segment_type':raw['u0']['concepts'][0]['segments'][0]['kind'] = 'table'
                before = copy.deepcopy(raw)
                with self.assertRaises(BatchTransportError):decode(raw, contract)
                self.assertEqual(raw, before)

    def test_every_reference_slot_rejects_cross_unit_and_unknown_sources(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        for location in ('segment', 'table', 'step', 'transition', 'uncertain', 'excluded'):
            for source in (units[1]['job']['blocks'][0]['id'], 'unknown-source'):
                with self.subTest(location=location, source=source):
                    raw = {'u0': reply(units[0], all_fields=True), 'u1': reply(units[1])}
                    unit = raw['u0']
                    if location == 'segment':unit['concepts'][0]['segments'][0]['blockIds'] = [source]
                    if location == 'table':unit['tables'][0]['blockIds'] = [source]
                    if location == 'step':unit['sequences'][0]['steps'][0]['blockIds'] = [source]
                    if location == 'transition':unit['sequences'][0]['transitions'][0]['blockIds'] = [source]
                    if location == 'uncertain':unit['uncertainBlocks'][0]['blockId'] = source
                    if location == 'excluded':unit['excludedBlocks'][0]['blockId'] = source
                    with self.assertRaises(BatchTransportError):decode(raw, contract)

    def test_duplicate_json_keys_at_every_level_and_nonfinite_json_fail(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        first, second = json.dumps(reply(units[0])), json.dumps(reply(units[1]))
        text = '{"u0":' + first + ',"u1":' + second + '}'
        cases = ['{"u0":' + first + ',"u0":' + first + ',"u1":' + second + '}',
                 text.replace('"tables": []', '"tables": [], "tables": []', 1),
                 text.replace('"standardKnowledgeUsed": false', '"standardKnowledgeUsed": NaN', 1), '{', '[]']
        for bad in cases:
            with self.subTest(text=bad[:30]), self.assertRaises(BatchTransportError):decode(bad, contract)
        self.assertEqual(len(decode(text.encode(), contract)), 2)

    def test_nested_definitions_and_local_schema_pointer_refs_are_namespaced(self):
        units = [fixture(0), fixture(1)]
        custom = {'type': 'json_schema', 'json_schema': {'name': 'local_fixture', 'strict': True,
            'schema': {'type': 'object', 'properties': {'concepts': {'type': 'array', 'items': {'$ref': '#/$defs/part'}}},
                       'required': ['concepts'], 'additionalProperties': False,
                       '$defs': {'part': {'type': 'object', 'properties': {'blockIds': {'type': 'array', 'items': {'type': 'string'}},
                                                                        'text': {'$ref': '#/$defs/text'}},
                                         'required': ['blockIds', 'text'], 'additionalProperties': False},
                                 'text': {'type': 'string'}}}}}
        for unit in units:unit['response_format'] = custom
        _, format, _, contract = encode(units)
        for name in ('u0', 'u1'):
            part = format['json_schema']['schema']['$defs'][name]['$defs']['part']
            self.assertEqual(part['properties']['text']['$ref'], f'#/$defs/{name}/$defs/text')
            self.assertEqual(part['properties']['blockIds']['items']['$ref'], f'#/$defs/{name}/$defs/studySourceId')
        raw = {f'u{i}': {'concepts': [{'blockIds': [unit['job']['blocks'][0]['id']], 'text': 'unchanged'}]}
               for i, unit in enumerate(units)}
        self.assertEqual(decode(raw, contract), [raw['u0'], raw['u1']])

    def test_unsupported_or_mismatched_formats_and_contracts_fail_closed(self):
        for mutation in ('not_strict', 'wrong_enum', 'external_ref', 'unsupported_keyword'):
            with self.subTest(mutation=mutation):
                units = [fixture(0), fixture(1)]
                units[0]['response_format'] = constrained_format(study.STUDY_FORMAT, units[0]['job'])
                schema = units[0]['response_format']['json_schema']['schema']
                if mutation == 'not_strict':units[0]['response_format']['json_schema']['strict'] = False
                if mutation == 'wrong_enum':schema['$defs']['studySourceId']['enum'] = ['unknown-source']
                if mutation == 'external_ref':schema['properties']['tables'] = {'$ref': 'https://invalid.example/schema'}
                if mutation == 'unsupported_keyword':schema['dependentSchemas'] = {}
                with self.assertRaises(BatchTransportError):encode(units)
        units = [fixture(0), fixture(1)]
        _, _, _, original = encode(units)
        for mutation in ('version', 'unit_order', 'duplicate_job', 'duplicate_source', 'schema_mismatch'):
            with self.subTest(mutation=mutation):
                contract = copy.deepcopy(original)
                if mutation == 'version':contract['version'] = 'future'
                if mutation == 'unit_order':contract['units'].reverse()
                if mutation == 'duplicate_job':contract['units'][1]['jobId'] = contract['units'][0]['jobId']
                if mutation == 'duplicate_source':contract['units'][1]['sourceIds'] = contract['units'][0]['sourceIds']
                if mutation == 'schema_mismatch':contract['units'][0]['schema']['$defs']['studySourceId']['enum'] = ['unknown-source']
                with self.assertRaises(BatchTransportError):decode({'u0': reply(units[0]), 'u1': reply(units[1])}, contract)

    def test_colliding_per_job_aliases_are_rejected_without_canonical_mutation(self):
        from pdf_source_aliases import encode as alias_encode
        units = [fixture(0), fixture(1)]
        for unit in units:
            payload, format, _ = alias_encode(unit['payload'], unit['response_format'], unit['job'])
            unit['payload'], unit['response_format'] = payload, format
            unit['job'] = {**unit['job'], 'blocks': copy.deepcopy(payload['blocks'])}
        self.assertEqual(units[0]['job']['blocks'][0]['id'], units[1]['job']['blocks'][0]['id'])
        with self.assertRaises(BatchTransportError):encode(units)

    def test_larger_experiments_require_explicit_limits_and_preserve_every_unit(self):
        for count, image_limit in ((2, 8), (3, 16), (4, 16)):
            with self.subTest(count=count):
                units = [fixture(i, 4) for i in range(count)]
                before = copy.deepcopy(units)
                with self.assertRaises(BatchTransportError):encode(units)
                payload, format, images, contract = encode(units, max_units=count, max_images=image_limit)
                names = [f'u{i}' for i in range(count)]
                self.assertEqual(list(payload['units']), names)
                self.assertEqual(format['json_schema']['schema']['required'], names)
                self.assertEqual(len(images), count * 4)
                self.assertEqual(images, [image for unit in units for image in unit['images']])
                raw = {f'u{i}': reply(unit, all_fields=True) for i, unit in enumerate(units)}
                self.assertEqual(decode(raw, contract), [raw[name] for name in names])
                self.assertEqual(units, before)
                # A later unit cannot cite an earlier one, even in a transition.
                raw[names[-1]]['sequences'][0]['transitions'][0]['blockIds'] = [units[0]['job']['blocks'][0]['id']]
                with self.assertRaises(BatchTransportError):decode(raw, contract)
        units = [fixture(i, 4) for i in range(3)]
        with self.assertRaises(BatchTransportError):encode(units, max_units=3, max_images=8)
        with self.assertRaises(BatchTransportError):encode([fixture(0, 5), fixture(1, 0)], max_images=8)

    def test_trusted_limits_reject_bool_noninteger_and_unsupported_values(self):
        units = [fixture(0, 0), fixture(1, 0)]
        for invalid in (True, False, None, '4', 4.0, 0, 1, 5, -1):
            with self.subTest(max_units=invalid), self.assertRaises(BatchTransportError):encode(units, max_units=invalid)
        for invalid in (True, False, None, '8', 8.0, 0, 1, 5, 12, 32, -1):
            with self.subTest(max_images=invalid), self.assertRaises(BatchTransportError):encode(units, max_images=invalid)

    def test_partial_decode_preserves_an_independent_valid_unit_without_retry(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        for mutation in ('malformed', 'crosscite', 'missing', 'unknown_container', 'missing_field'):
            with self.subTest(mutation=mutation):
                raw = {'u0': reply(units[0]), 'u1': reply(units[1])}
                if mutation == 'malformed':raw['u1'] = None
                if mutation == 'crosscite':raw['u1']['concepts'][0]['segments'][0]['blockIds'] = [units[0]['job']['blocks'][0]['id']]
                if mutation == 'missing':raw.pop('u1')
                if mutation == 'unknown_container':raw['u2'] = reply(units[1])
                if mutation == 'missing_field':raw['u1'].pop('concepts')
                before = copy.deepcopy((raw, contract))
                valid, errors = decode_each(raw, contract)
                self.assertTrue(errors)
                self.assertEqual(valid[0], {'index': 0, 'name': 'u0', 'raw': reply(units[0])})
                self.assertEqual(len(valid), 2 if mutation == 'unknown_container' else 1)
                self.assertEqual((raw, contract), before)
                with self.assertRaises(BatchTransportError):decode(raw, contract)
                valid[0]['raw']['concepts'].clear()
                self.assertEqual(raw, before[0])

    def test_partial_decode_duplicate_keys_fail_only_the_ambiguous_unit(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        first, second = json.dumps(reply(units[0])), json.dumps(reply(units[1]))
        cases = ['{"u0":' + first + ',"u1":' + second + ',"u1":' + second + '}',
                 '{"u0":' + first + ',"u1":' + second.replace('"tables": []', '"tables": [], "tables": []') + '}']
        for text in cases:
            valid, errors = decode_each(text, contract)
            self.assertEqual(valid, [{'index': 0, 'name': 'u0', 'raw': reply(units[0])}])
            self.assertEqual([(error['index'], error['name'], error['code']) for error in errors], [(1, 'u1', 'invalid_unit')])
            self.assertIs(type(valid[0]['raw']), dict)
            self.assertIs(type(valid[0]['raw']['concepts'][0]), dict)
        extra = '{"u0":' + first + ',"u1":' + second + ',"unknown":{},"unknown":{}}'
        valid, errors = decode_each(extra, contract)
        self.assertEqual(len(valid), 2)
        self.assertEqual({error['code'] for error in errors}, {'unknown_unit', 'duplicate_container_key'})

    def test_partial_decode_validates_whole_contract_before_accepting_any_unit(self):
        units = [fixture(0), fixture(1)]
        _, _, _, contract = encode(units)
        raw = {'u0': reply(units[0]), 'u1': reply(units[1])}
        contract['units'][1]['sourceIds'] = list(contract['units'][0]['sourceIds'])
        with self.assertRaises(BatchTransportError):decode_each(raw, contract)
        _, _, _, contract = encode(units)
        for invalid in ('{', '[]', [], None, 3):
            valid, errors = decode_each(invalid, contract)
            self.assertEqual(valid, [])
            self.assertEqual([error['code'] for error in errors], ['invalid_container'])
            self.assertIsNone(errors[0]['index'])
            self.assertIsNone(errors[0]['name'])
        valid, errors = decode_each(raw, contract)
        self.assertEqual(valid, [{'index': i, 'name': f'u{i}', 'raw': reply(unit)} for i, unit in enumerate(units)])
        self.assertEqual(errors, [])

    def test_flat_definitions_only_change_reference_routing_not_payload_or_contract(self):
        units = [fixture(0, 2), fixture(1, 2)]
        before = copy.deepcopy(units)
        normal = encode(units)
        flat = encode(units, flat_defs=True)
        self.assertEqual(flat[0], normal[0])
        self.assertEqual(flat[2:], normal[2:])
        self.assertEqual(units, before)
        schema = flat[1]['json_schema']['schema']
        self.assertEqual(list(schema['$defs']), ['u0', 'u0__studySourceId', 'u1', 'u1__studySourceId'])
        self.assertEqual(schema['required'], ['u0', 'u1'])
        def check_refs(node, root=True):
            if isinstance(node, dict):
                if not root:self.assertNotIn('$defs', node)
                if '$ref' in node:
                    self.assertRegex(node['$ref'], r'^#/\$defs/[^/]+$')
                for child in node.values():check_refs(child, False)
            elif isinstance(node, list):
                for child in node:check_refs(child, False)
        check_refs(schema)
        for i in range(2):
            name = f'u{i}'
            self.assertEqual(schema['$defs'][name + '__studySourceId'],
                             normal[3]['units'][i]['schema']['$defs']['studySourceId'])
        raw = {'u0': reply(units[0], all_fields=True), 'u1': reply(units[1], all_fields=True)}
        batch._validate(raw, schema, schema)
        self.assertEqual(decode(raw, flat[3]), list(raw.values()))
        self.assertEqual(decode_each(raw, flat[3]),
                         ([{'index': i, 'name': f'u{i}', 'raw': raw[f'u{i}']} for i in range(2)], []))
        raw['u1']['sequences'][0]['transitions'][0]['blockIds'] = [units[0]['job']['blocks'][0]['id']]
        with self.assertRaises(BatchTransportError):batch._validate(raw, schema, schema)

    def test_flat_definitions_handle_nested_defs_escaped_names_and_pointer_targets(self):
        units = [fixture(0, 0), fixture(1, 0)]
        schema = {'type': 'object', 'properties': {
            'text': {'type': 'string'},
            'detail': {'type': 'object', 'properties': {'a': {'$ref': '#/$defs/a~1b'},
                                                      'b': {'$ref': '#/$defs/a_b'},
                                                      'c': {'$ref': '#/properties/detail/$defs/local'},
                                                      'd': {'$ref': '#/properties/text'}},
                       'required': ['a', 'b', 'c', 'd'], 'additionalProperties': False,
                       '$defs': {'local': {'type': 'string'}}},
            'value': {'anyOf': [{'type': 'integer'}, {'type': 'null'}]},
            'otherValue': {'$ref': '#/properties/value/anyOf/0'}},
            'required': ['text', 'detail', 'value', 'otherValue'], 'additionalProperties': False,
            '$defs': {'a/b': {'type': 'string'}, 'a_b': {'type': 'string'}}}
        for unit in units:
            unit['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'nested_refs', 'strict': True, 'schema': schema}}
        before = copy.deepcopy(units)
        payload, format, _, contract = encode(units, flat_defs=True)
        wire = format['json_schema']['schema']
        self.assertEqual(units, before)
        self.assertIn('u0__a_b', wire['$defs'])
        self.assertIn('u0__a_b_2', wire['$defs'])
        self.assertEqual(payload['units']['u0'], units[0]['payload'])
        raw = {f'u{i}': {'text': f'literal u{i} #/$defs/a~1b', 'detail': {
            'a': 'same', 'b': 'different', 'c': 'nested', 'd': 'pointer'}, 'value': None,
            'otherValue': 3} for i in range(2)}
        batch._validate(raw, wire, wire)
        self.assertEqual(decode(raw, contract), list(raw.values()))
        def walk(node):
            if isinstance(node, dict):
                if '$ref' in node:self.assertRegex(node['$ref'], r'^#/\$defs/[^/]+$')
                for child in node.values():walk(child)
            elif isinstance(node, list):
                for child in node:walk(child)
        walk(wire)
        for invalid in (0, 1, None, 'true', [], {}):
            with self.subTest(flat_defs=invalid), self.assertRaises(BatchTransportError):encode(units, flat_defs=invalid)


if __name__ == '__main__':
    unittest.main()
