"""Visual slots are explicit source ownership, not inferred source repair."""
import copy
import unittest

from pdf_new_concept_ver99_study import STUDY_FORMAT, validate
from pdf_study_cache_reuse import constrained_format
from pdf_source_facts import encode_format as encode_facts, decode as decode_facts
from pdf_visual_teaching import (FIELDS, VERSION, VisualTeachingError,
                                 decode, encode_format)


def fixture():
    job = {'blocks': [
        {'id': 'v2p1f0', 'page': 1, 'kind': 'text', 'text': 'source prose'},
        {'id': 'v2p1f1', 'page': 1, 'kind': 'visual', 'hasVisual': True,
         'bbox': [.4, .1, .9, .9]},
        {'id': 'v2p2f0', 'page': 2, 'kind': 'page', 'hasVisual': True,
         'geometryFallback': True, 'bbox': [0, 0, 1, 1]},
        {'id': 'v2p2f1', 'page': 2, 'kind': 'visual', 'hasVisual': True,
         'bbox': [.93, .93, .97, .97]}]}
    return job, constrained_format(STUDY_FORMAT, job)


def empty():
    return {name: [] for name in FIELDS}


def content(source, text):
    return {
        'concepts': [{'title': text, 'sourceSetup': {
            'observedRelations': [text], 'boundaryChecks': [text],
            'interpretation': text}, 'segments': [
                {'kind': 'definition', 'text': text, 'blockIds': [source]},
                {'kind': 'explanation', 'text': text, 'blockIds': [source]}],
            'standardKnowledgeUsed': False}],
        'sequences': [{'conceptTitle': text, 'title': text,
                       'steps': [{'title': text, 'body': text, 'blockIds': [source]}]}],
        'tables': [{'conceptTitle': text, 'headers': [text], 'rows': [[text]],
                    'blockIds': [source]}],
        'excludedBlocks': [{'blockId': source, 'reason': text}],
        'uncertainBlocks': [{'blockId': source, 'reason': text}]}


def visual_empty():
    return {name: [] for name in ('concepts', 'excludedBlocks', 'uncertainBlocks')}


def visual_content(source, text):
    value = content(source, text)
    for name in ('sequences', 'tables'):
        items = value.pop(name)
        for item in items:
            del item['conceptTitle']
        value['concepts'][0][name] = items
    return value


def wire_reply():
    text = 'v2p1f1 $a_b$ \\(x=1\\) code {"blockId":"v2p2f0"}'
    value = content('v2p1f0', 'native '+text)
    # Deliberately reverse object-key order. Decoding follows source job order.
    value['visualTeaching'] = {'v2p2f0': visual_content('v2p2f0', 'second '+text),
                               'v2p1f1': visual_content('v2p1f1', 'first '+text)}
    return value


class VisualTeachingTests(unittest.TestCase):
    def test_schema_owns_each_visual_and_keeps_native_and_icon_root_sources(self):
        job, original = fixture(); before = copy.deepcopy((job, original))
        encoded, ownership = encode_format(original, job)
        self.assertEqual((job, original), before)
        self.assertEqual(ownership, {'version': VERSION,
                                    'visualIds': ('v2p1f1', 'v2p2f0'),
                                    'nativeIds': ('v2p1f0', 'v2p2f1')})
        schema = encoded['json_schema']['schema']; props = schema['properties']
        visuals = props['visualTeaching']
        self.assertIn('visualTeaching', schema['required'])
        self.assertEqual(visuals['required'], ['v2p1f1', 'v2p2f0'])
        self.assertIs(visuals['additionalProperties'], False)
        for owner in ownership['visualIds']:
            slot = visuals['properties'][owner]
            self.assertEqual(set(slot['required']), {'concepts', 'excludedBlocks', 'uncertainBlocks'})
            concept = slot['properties']['concepts']['items']['properties']
            self.assertIn('tables', slot['properties']['concepts']['items']['required'])
            self.assertIn('sequences', slot['properties']['concepts']['items']['required'])
            table = concept['tables']['items']['properties']
            self.assertNotIn('conceptTitle', table)
            self.assertEqual(table['blockIds']['items']['enum'], [owner])
            self.assertEqual(table['blockIds']['minItems'], 1)
            self.assertEqual(table['headers']['items'], {'type': 'string'})
            self.assertEqual(table['rows']['items']['items'], {'type': 'string'})
            segment = slot['properties']['concepts']['items']['properties']['segments']['items']
            self.assertEqual(segment['properties']['blockIds']['items']['enum'], [owner])
            step = concept['sequences']['items']['properties']['steps']['items']
            self.assertEqual(step['properties']['blockIds']['items']['enum'], [owner])
            for key in ('excludedBlocks', 'uncertainBlocks'):
                self.assertEqual(slot['properties'][key]['items']['properties']['blockId']['enum'], [owner])
        table = props['tables']['items']['properties']
        self.assertEqual(table['blockIds']['items']['enum'], ['v2p1f0', 'v2p2f1'])
        self.assertEqual(encode_format(original, job), (encoded, ownership))

    def test_recursive_fact_source_setup_is_preserved_verbatim_in_every_slot(self):
        job, schema = fixture()
        original_setup = {'type': 'object', 'properties': {
            'facts': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'equation': {'type': 'string'}, 'meaning': {'type': 'string'},
                'factors': {'type': 'array', 'items': {'type': 'string'}}},
                'required': ['equation', 'meaning', 'factors'], 'additionalProperties': False}}},
                'required': ['facts'], 'additionalProperties': False}
        schema['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup'] = original_setup
        before = copy.deepcopy(schema); encoded, _ = encode_format(schema, job)
        self.assertEqual(schema, before)
        root = encoded['json_schema']['schema']['properties']
        for fields in [root]+[v['properties'] for v in root['visualTeaching']['properties'].values()]:
            self.assertEqual(fields['concepts']['items']['properties']['sourceSetup'], original_setup)

    def test_decode_flattens_job_order_losslessly_and_never_changes_inputs(self):
        job, schema = fixture(); _, ownership = encode_format(schema, job)
        raw = wire_reply(); before = copy.deepcopy((raw, ownership))
        decoded = decode(raw, ownership)
        first = content('v2p1f1', raw['visualTeaching']['v2p1f1']['concepts'][0]['title'])
        second = content('v2p2f0', raw['visualTeaching']['v2p2f0']['concepts'][0]['title'])
        expected = {name: copy.deepcopy(raw[name])+first[name]+second[name] for name in FIELDS}
        self.assertEqual(decoded, expected)
        self.assertEqual((raw, ownership), before)
        decoded['concepts'][1]['sourceSetup']['observedRelations'].append('changed')
        self.assertEqual((raw, ownership), before)

    def test_fact_adapter_composition_keeps_facts_but_enforces_visual_owner(self):
        job, schema = fixture()
        facts_schema = encode_facts(schema);before = copy.deepcopy(facts_schema)
        original_fact = facts_schema['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']['observedRelations']['items']['properties']
        encoded, ownership = encode_format(facts_schema, job)
        self.assertEqual(facts_schema, before)
        props = encoded['json_schema']['schema']['properties']
        setups = [(props, ['v2p1f0', 'v2p2f1'])]
        setups.extend((slot['properties'], [source])
                      for source, slot in props['visualTeaching']['properties'].items())
        for fields, allowed in setups:
            setup = fields['concepts']['items']['properties']['sourceSetup']
            fact = setup['properties']['observedRelations']['items']['properties']
            self.assertEqual(fact['blockIds']['items']['enum'], allowed)
            self.assertEqual(set(fact), set(original_fact))
            if 'sourceQuote' in original_fact:
                self.assertEqual(fact['sourceQuote'], {'type': 'string'})
            self.assertEqual(fact['learnerText'], {'type': 'string'})
        raw = wire_reply()
        for container in [raw, *raw['visualTeaching'].values()]:
            for concept in container['concepts']:
                ids = concept['segments'][0]['blockIds']
                concept['sourceSetup']['observedRelations'] = [{
                    **({'sourceQuote': 'visible \\(x+y\\) code {"blockId":"literal"}'}
                       if 'sourceQuote' in original_fact else {}),
                    'learnerText': 'learned \\(x+y\\) code {"blockId":"literal"}',
                    'blockIds': ids[:]}]
        untouched = copy.deepcopy(raw)
        flattened = decode(raw, ownership)
        canonical = decode_facts(flattened)
        self.assertEqual(raw, untouched)
        self.assertEqual([c['segments'][1]['blockIds'] for c in canonical['concepts']],
                         [['v2p1f0'], ['v2p1f1'], ['v2p2f0']])
        self.assertIn('code {"blockId":"literal"}', canonical['concepts'][1]['segments'][1]['text'])
        raw['visualTeaching']['v2p1f1']['concepts'][0]['sourceSetup']['observedRelations'][0]['blockIds'] = ['v2p2f0']
        with self.assertRaises(VisualTeachingError):decode(raw, ownership)
        raw = copy.deepcopy(untouched)
        raw['concepts'][0]['sourceSetup']['observedRelations'][0]['blockIds'] = ['v2p1f1']
        with self.assertRaises(VisualTeachingError):decode(raw, ownership)

    def test_unknown_or_missing_owner_keys_and_top_level_fields_are_rejected(self):
        job, schema = fixture(); _, ownership = encode_format(schema, job)
        for mode in ('missing_owner', 'unknown_owner', 'missing_array', 'unknown_array',
                     'missing_visualTeaching', 'unknown_root', 'unknown_slot_field'):
            with self.subTest(mode=mode):
                raw = wire_reply()
                if mode == 'missing_owner':del raw['visualTeaching']['v2p1f1']
                if mode == 'unknown_owner':raw['visualTeaching']['not-a-target'] = visual_empty()
                if mode == 'missing_array':del raw['tables']
                if mode == 'unknown_array':raw['other'] = []
                if mode == 'missing_visualTeaching':del raw['visualTeaching']
                if mode == 'unknown_root':raw['visualTeaching'] = []
                if mode == 'unknown_slot_field':raw['visualTeaching']['v2p1f1']['other'] = []
                before = copy.deepcopy(raw)
                with self.assertRaises(VisualTeachingError):decode(raw, ownership)
                self.assertEqual(raw, before)

    def test_citations_cannot_cross_owners_or_use_unknown_targets(self):
        job, schema = fixture(); _, ownership = encode_format(schema, job)
        for where in ('root', 'segment', 'table', 'step', 'excluded', 'uncertain'):
            for wrong in ('v2p2f0', 'unknown', None, 3):
                with self.subTest(where=where, wrong=wrong):
                    raw = wire_reply(); slot = raw['visualTeaching']['v2p1f1']
                    if where == 'root':raw['tables'][0]['blockIds'] = ['v2p1f1']
                    if where == 'segment':slot['concepts'][0]['segments'][0]['blockIds'] = [wrong]
                    if where == 'table':slot['concepts'][0]['tables'][0]['blockIds'] = [wrong]
                    if where == 'step':slot['concepts'][0]['sequences'][0]['steps'][0]['blockIds'] = [wrong]
                    if where == 'excluded':slot['excludedBlocks'][0]['blockId'] = wrong
                    if where == 'uncertain':slot['uncertainBlocks'][0]['blockId'] = wrong
                    before = copy.deepcopy(raw)
                    with self.assertRaises(VisualTeachingError):decode(raw, ownership)
                    self.assertEqual(raw, before)

    def test_malformed_or_missing_citations_are_not_repaired(self):
        job, schema = fixture(); _, ownership = encode_format(schema, job)
        for where in ('segment', 'table', 'step', 'excluded', 'uncertain'):
            for value in ('missing', None, 'v2p1f1'):
                with self.subTest(where=where, value=value):
                    raw = wire_reply(); slot = raw['visualTeaching']['v2p1f1']
                    target = {'segment': slot['concepts'][0]['segments'][0],
                              'table': slot['concepts'][0]['tables'][0],
                              'step': slot['concepts'][0]['sequences'][0]['steps'][0],
                              'excluded': slot['excludedBlocks'][0], 'uncertain': slot['uncertainBlocks'][0]}[where]
                    key = 'blockId' if where in ('excluded', 'uncertain') else 'blockIds'
                    if value == 'missing':del target[key]
                    else:target[key] = value
                    # A singular citation string is valid for exclusions.
                    if key == 'blockId' and value == 'v2p1f1':continue
                    with self.assertRaises(VisualTeachingError):decode(raw, ownership)

    def test_no_visual_job_bypasses_adapter_with_independent_copies(self):
        job, schema = fixture();job['blocks'] = [job['blocks'][0], job['blocks'][-1]]
        schema = constrained_format(STUDY_FORMAT, job)
        encoded, ownership = encode_format(schema, job)
        self.assertIsNone(ownership);self.assertEqual(encoded, schema)
        self.assertIsNot(encoded, schema)
        raw = empty();self.assertEqual(decode(raw, None), raw)
        self.assertIsNot(decode(raw, None), raw)

    def test_all_visual_job_requires_empty_root_arrays_without_empty_schema_enum(self):
        job, _ = fixture();job['blocks'] = [job['blocks'][1]]
        schema = constrained_format(STUDY_FORMAT, job)
        encoded, ownership = encode_format(schema, job)
        props = encoded['json_schema']['schema']['properties']
        for name in FIELDS:self.assertEqual(props[name]['maxItems'], 0)
        self.assertNotIn('"enum": []', __import__('json').dumps(encoded))
        raw = empty();raw['visualTeaching'] = {'v2p1f1': visual_content('v2p1f1', 'figure')}
        self.assertEqual(decode(raw, ownership)['concepts'][0]['title'], 'figure')
        raw['concepts'] = [{'title': 'unbound', 'segments': []}]
        with self.assertRaises(VisualTeachingError):decode(raw, ownership)

    def test_empty_visual_slot_stays_empty_for_canonical_pending_checks(self):
        job, schema = fixture();_, ownership = encode_format(schema, job)
        raw = empty();raw['visualTeaching'] = {source: visual_empty() for source in ownership['visualIds']}
        self.assertEqual(decode(raw, ownership), empty())

    def test_orphan_visual_table_cannot_be_flattened_or_given_an_invented_concept(self):
        job, schema = fixture();_, ownership = encode_format(schema, job)
        raw = empty();raw['visualTeaching'] = {source: visual_empty() for source in ownership['visualIds']}
        raw['visualTeaching']['v2p1f1']['tables'] = [{
            'conceptTitle': 'model did not emit this concept', 'headers': ['country', 'value'],
            'rows': [['A', '1'], ['B', '2']], 'blockIds': ['v2p1f1']}]
        before = copy.deepcopy(raw)
        with self.assertRaises(VisualTeachingError):decode(raw, ownership)
        self.assertEqual(raw, before)

    def test_nested_visual_table_reaches_unchanged_canonical_table_validation(self):
        job, _ = fixture();job['blocks'] = [job['blocks'][1]]
        job.update(id='visual-table-fixture', title='표')
        schema = constrained_format(STUDY_FORMAT, job);_, ownership = encode_format(schema, job)
        owner = 'v2p1f1';title = '두 항목의 금액 비교'
        slot = visual_empty()
        slot['concepts'] = [{
            'title': title, 'sourceSetup': {'observedRelations': ['A는1, B는2'],
                                           'boundaryChecks': [], 'interpretation': ''},
            'segments': [
                {'kind': 'definition', 'text': '표는 두 항목의 금액을 비교해요.', 'blockIds': [owner]},
                {'kind': 'explanation', 'text': 'A의 금액은 1이고 B의 금액은 2예요.', 'blockIds': [owner]},
                {'kind': 'easyExplanation', 'text': '각 항목과 바로 옆 금액을 함께 읽어요.', 'blockIds': [owner]}],
            'standardKnowledgeUsed': False, 'sequences': [],
            'tables': [{'headers': ['항목', '금액'], 'rows': [['A', '1'], ['B', '2']],
                        'blockIds': [owner]}]}]
        raw = empty();raw['visualTeaching'] = {owner: slot}
        canonical = decode(raw, ownership)
        self.assertEqual(canonical['tables'][0]['conceptTitle'], title)
        self.assertEqual(canonical['tables'][0]['rows'], [['A', '1'], ['B', '2']])
        unit = validate(canonical, job, {'documentId': 'fixture', 'pages': [{'label': '1'}]})
        self.assertIn('| A | 1 |', unit['summary']['parts'][0]['body'])
        self.assertIn('| B | 2 |', unit['summary']['parts'][0]['body'])
        self.assertEqual(unit['coverage'][0]['state'], 'summarized')
        self.assertEqual(unit['sourceIdRepairs'], [])

    def test_empty_citation_cannot_borrow_another_segment_owner(self):
        job, schema = fixture();_, ownership = encode_format(schema, job)
        for where in ('root', 'segment', 'table', 'step', 'fact'):
            with self.subTest(where=where):
                raw = wire_reply();concept = raw['visualTeaching']['v2p1f1']['concepts'][0]
                if where == 'root':raw['concepts'][0]['segments'][1]['blockIds'] = []
                if where == 'segment':concept['segments'][1]['blockIds'] = []
                if where == 'table':concept['tables'][0]['blockIds'] = []
                if where == 'step':concept['sequences'][0]['steps'][0]['blockIds'] = []
                if where == 'fact':
                    concept['sourceSetup']['observedRelations'] = [{
                        'sourceQuote': 'quote', 'learnerText': 'unowned', 'blockIds': []}]
                with self.assertRaises(VisualTeachingError):decode(raw, ownership)

    def test_empty_or_uncertain_visual_is_not_promoted_by_canonical_validation(self):
        job, _ = fixture();job['blocks'] = [job['blocks'][1]]
        job.update(id='single-visual-fixture', title='도해')
        schema = constrained_format(STUDY_FORMAT, job)
        _, ownership = encode_format(schema, job)
        document = {'documentId': 'fixture', 'pages': [{'label': '1'}]}
        for uncertain in (False, True):
            raw = empty();slot = visual_empty()
            if uncertain:
                slot['uncertainBlocks'] = [{'blockId': 'v2p1f1',
                                             'reason': '도해의 목적지는 읽기 어려워요.'}]
            raw['visualTeaching'] = {'v2p1f1': slot}
            unit = validate(decode(raw, ownership), job, document)
            self.assertEqual(unit['concepts'], [])
            self.assertEqual(unit['summary']['parts'], [])
            self.assertEqual(unit['coverage'][0]['state'], 'needs_review')
            self.assertEqual(unit['sourceIdRepairs'], [])

    def test_invalid_job_schema_and_ownership_contracts_fail(self):
        job, schema = fixture()
        for mode in ('duplicate_job', 'missing_job_id', 'unconstrained', 'different_enum',
                     'unknown_schema_field', 'already_encoded'):
            with self.subTest(mode=mode):
                badjob, badschema = copy.deepcopy((job, schema))
                if mode == 'duplicate_job':badjob['blocks'].append(badjob['blocks'][0])
                if mode == 'missing_job_id':del badjob['blocks'][0]['id']
                if mode == 'unconstrained':badschema = copy.deepcopy(STUDY_FORMAT)
                if mode == 'different_enum':badschema['json_schema']['schema']['$defs']['studySourceId']['enum'] = ['wrong']
                if mode == 'unknown_schema_field':
                    badschema['json_schema']['schema']['properties']['unknown'] = {'type': 'string'}
                    badschema['json_schema']['schema']['required'].append('unknown')
                if mode == 'already_encoded':badschema, _ = encode_format(schema, job)
                with self.assertRaises(VisualTeachingError):encode_format(badschema, badjob)
        for bad in ({}, {'version': VERSION, 'visualIds': ['x'], 'nativeIds': ['x']},
                    {'version': VERSION, 'visualIds': [], 'nativeIds': ['x']},
                    {'version': VERSION, 'visualIds': ['x', 'x'], 'nativeIds': []}):
            with self.assertRaises(VisualTeachingError):decode(wire_reply(), bad)


if __name__ == '__main__':
    unittest.main()
