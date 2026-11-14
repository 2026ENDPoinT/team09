"""Ownership is structural, while source, content and ordinary checks stay intact."""
import copy
import unittest

import pdf_new_concept_ver99_study as study
import pdf_owned_teaching as owned
import pdf_source_aliases as aliases


class OwnedTeachingTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [{'id': 'v2p1f0', 'page': 1, 'kind': 'text', 'bbox': [0, 0, .5, 1],
                        'text': '조건에 따라 경로를 선택해요.', 'hasVisual': False, 'planRole': 'teaching'},
                       {'id': 'v2p1f1', 'page': 1, 'kind': 'text', 'bbox': [.5, 0, 1, 1],
                        'text': '결과를 확인하고 되돌아가요.', 'hasVisual': False, 'planRole': 'teaching'}]
        self.job = {'id': 'fixture', 'title': '경로', 'blocks': self.blocks}
        self.payload = study.teaching_payload(self.job, [], {}, [])
        self.raw = {'concepts': [{
            'title': '조건과 경로',
            'sourceSetup': {'observedRelations': ['a는 설명 속 문자이며 출처 ID가 아니에요.'],
                            'boundaryChecks': [], 'interpretation': ''},
            'segments': [{'kind': 'definition', 'text': '조건에 따라 경로를 선택하는 원리예요.', 'blockIds': ['a']},
                         {'kind': 'explanation', 'text': '조건을 확인하고 결과에 따라 되돌아가요.', 'blockIds': ['a', 'b']},
                         {'kind': 'easyExplanation', 'text': '갈림길을 하나씩 살펴요.', 'blockIds': ['b']}],
            'standardKnowledgeUsed': False,
            'tables': [{'headers': ['조건', '결과'], 'rows': [['참', '이동'], ['거짓', '대기']],
                        'blockIds': ['a', 'b']}],
            'sequences': [{'title': '조건별 경로', 'steps': [
                {'title': '선택', 'body': '조건을 확인해요.', 'blockIds': ['a']},
                {'title': '되돌아감', 'body': '결과를 확인하고 돌아가요.', 'blockIds': ['b']}]}]}],
                    'excludedBlocks': [], 'uncertainBlocks': []}

    def encoded(self):
        return owned.encode_format(aliases.encode(self.payload, study.STUDY_FORMAT, self.job)[1])

    def test_strict_schema_moves_owners_without_mutating_content_or_source_enums(self):
        _, wire_format, _ = aliases.encode(self.payload, study.STUDY_FORMAT, self.job)
        before = copy.deepcopy(wire_format)
        result = owned.encode_format(wire_format)
        self.assertEqual(wire_format, before)
        schema = result['json_schema']['schema']
        concept = schema['properties']['concepts']['items']
        self.assertNotIn('tables', schema['properties'])
        self.assertNotIn('sequences', schema['required'])
        for name in ['tables', 'sequences']:
            self.assertIn(name, concept['required'])
            item = concept['properties'][name]['items']
            self.assertNotIn('conceptTitle', item['properties'])
            self.assertNotIn('conceptTitle', item['required'])
            self.assertFalse(item['additionalProperties'])
        self.assertEqual(schema['$defs'], before['json_schema']['schema']['$defs'])
        for name in ['title', 'segments', 'sourceSetup', 'standardKnowledgeUsed']:
            self.assertEqual(concept['properties'][name],
                             before['json_schema']['schema']['properties']['concepts']['items']['properties'][name])
        self.assertEqual(concept['properties']['tables']['items']['properties']['headers'],
                         {'type': 'array', 'items': {'type': 'string'}})

    def test_flattening_derives_each_table_and_flow_owner_from_its_parent(self):
        second = copy.deepcopy(self.raw['concepts'][0])
        second['title'] = '별개의 원리'
        self.raw['concepts'].append(second)
        before = copy.deepcopy(self.raw)
        result = owned.decode(self.raw)
        self.assertEqual(self.raw, before)
        self.assertEqual([x['conceptTitle'] for x in result['tables']], ['조건과 경로', '별개의 원리'])
        self.assertEqual([x['conceptTitle'] for x in result['sequences']], ['조건과 경로', '별개의 원리'])
        self.assertNotIn('tables', result['concepts'][0])
        self.assertNotIn('sequences', result['concepts'][0])
        self.assertEqual(result['concepts'][0]['segments'], before['concepts'][0]['segments'])

    def test_alias_then_owned_round_trip_passes_unchanged_canonical_validation(self):
        _, wire_format, mapping = aliases.encode(self.payload, study.STUDY_FORMAT, self.job)
        owned.encode_format(wire_format)
        canonical = aliases.decode(owned.decode(self.raw), mapping)
        doc = {'documentId': 'fixture-doc', 'pages': [{'label': '1'}]}
        result = study.validate(canonical, self.job, doc)
        self.assertEqual(len(result['summary']['parts']), 1)
        part = result['summary']['parts'][0]
        self.assertIn('| 참 | 이동 |', part['body'])
        # Ownership decoding must preserve the two-stage teaching, while the
        # new card policy deliberately presents it as ordinary prose.
        self.assertNotIn('stepFlow',part)
        self.assertIn('조건을 확인해요.',part['body'])
        self.assertIn('결과를 확인하고 돌아가요.',part['body'])
        self.assertEqual({e['sourceId'] for e in part['evidence']}, {'v2p1f0', 'v2p1f1'})
        self.assertEqual(canonical['concepts'][0]['sourceSetup']['observedRelations'],
                         self.raw['concepts'][0]['sourceSetup']['observedRelations'])

    def test_equations_code_captions_and_heading_selection_are_not_rewritten(self):
        raw = copy.deepcopy(self.raw)
        literal = 'a는 문자열이에요. ' + r'\(F=ma\)' + '\n```cpp\nint *p = &x;\n```'
        raw['concepts'][0]['segments'][1]['text'] = literal
        raw['concepts'][0]['headingSelection'] = {'id': 'h:source', 'mode': 'body'}
        raw['concepts'][0]['tables'][0]['caption'] = '그림 a: v2p1f0는 인용문 속 문자예요.'
        result = owned.decode(raw)
        self.assertEqual(result['concepts'][0]['segments'][1]['text'], literal)
        self.assertEqual(result['concepts'][0]['headingSelection'], raw['concepts'][0]['headingSelection'])
        self.assertEqual(result['tables'][0]['caption'], raw['concepts'][0]['tables'][0]['caption'])

    def test_optional_existing_schema_fields_and_strict_constraints_survive(self):
        wire = copy.deepcopy(study.STUDY_FORMAT)
        schema = wire['json_schema']['schema']
        schema['properties']['uncertainBlocks']['maxItems'] = 0
        concept = schema['properties']['concepts']['items']
        concept['properties']['headingSelection'] = {'type': 'string', 'enum': ['h:a', 'h:b']}
        concept['required'].append('headingSelection')
        table = schema['properties']['tables']['items']
        table['properties']['caption'] = {'type': 'string'}
        table['required'].append('caption')
        result = owned.encode_format(wire)['json_schema']['schema']
        self.assertEqual(result['properties']['uncertainBlocks']['maxItems'], 0)
        self.assertEqual(result['properties']['concepts']['items']['properties']['headingSelection'],
                         {'type': 'string', 'enum': ['h:a', 'h:b']})
        self.assertEqual(result['properties']['concepts']['items']['properties']['tables']['items']['properties']['caption'],
                         {'type': 'string'})

    def test_ambiguous_root_or_item_owner_is_rejected(self):
        for variant in ['root_tables', 'unknown_root', 'own_title', 'missing_nested', 'wrong_nested']:
            with self.subTest(variant=variant):
                raw = copy.deepcopy(self.raw)
                if variant == 'root_tables': raw['tables'] = []
                elif variant == 'unknown_root': raw['unexpected'] = []
                elif variant == 'own_title': raw['concepts'][0]['tables'][0]['conceptTitle'] = '다른 원리'
                elif variant == 'missing_nested': del raw['concepts'][0]['tables']
                else: raw['concepts'][0]['sequences'] = {}
                with self.assertRaises(owned.OwnedTeachingError):
                    owned.decode(raw)

    def test_malformed_containers_are_rejected_without_touching_the_reply(self):
        for variant in ['concept', 'title', 'table', 'row', 'sequence', 'step']:
            with self.subTest(variant=variant):
                raw = copy.deepcopy(self.raw)
                if variant == 'concept': raw['concepts'][0] = []
                elif variant == 'title': raw['concepts'][0]['title'] = 1
                elif variant == 'table': raw['concepts'][0]['tables'][0] = []
                elif variant == 'row': raw['concepts'][0]['tables'][0]['rows'][0] = 'not an array'
                elif variant == 'sequence': raw['concepts'][0]['sequences'][0]['title'] = []
                else: raw['concepts'][0]['sequences'][0]['steps'][0] = 'not an object'
                before = copy.deepcopy(raw)
                with self.assertRaises(owned.OwnedTeachingError):
                    owned.decode(raw)
                self.assertEqual(raw, before)

    def test_old_or_non_strict_schemas_cannot_be_moved_silently(self):
        for variant in ['not_strict', 'missing_required', 'already_owned', 'missing_owner']:
            with self.subTest(variant=variant):
                wire = self.encoded() if variant == 'already_owned' else copy.deepcopy(study.STUDY_FORMAT)
                schema = wire['json_schema']['schema']
                if variant == 'not_strict': wire['json_schema']['strict'] = False
                elif variant == 'missing_required': schema['required'].remove('tables')
                elif variant == 'missing_owner':
                    item = schema['properties']['tables']['items']
                    del item['properties']['conceptTitle']
                    item['required'].remove('conceptTitle')
                with self.assertRaises(owned.OwnedTeachingError):
                    owned.encode_format(wire)

    def test_unknown_source_still_fails_the_existing_alias_decoder(self):
        self.raw['concepts'][0]['tables'][0]['blockIds'] = ['unknown']
        value = owned.decode(self.raw)
        with self.assertRaises(aliases.SourceAliasError):
            aliases.decode(value, {'a': 'v2p1f0', 'b': 'v2p1f1'})

    def test_empty_owned_content_stays_empty(self):
        value = owned.decode({'concepts': [], 'excludedBlocks': [], 'uncertainBlocks': []})
        self.assertEqual(value, {'concepts': [], 'tables': [], 'sequences': [],
                                 'excludedBlocks': [], 'uncertainBlocks': []})


if __name__ == '__main__':
    unittest.main()
