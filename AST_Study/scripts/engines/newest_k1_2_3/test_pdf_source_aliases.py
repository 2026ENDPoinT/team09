"""Job-local IDs reduce wire repetition without changing source content/citations."""
import copy
import json
import unittest

from pdf_new_concept_ver99_study import STUDY_FORMAT
from pdf_source_aliases import encode, decode, bucket_pool_size, SourceAliasError
from pdf_study_cache_reuse import constrained_format


def fixture(count=3):
    ids = [f'v2p{index // 20 + 1}f{index}' for index in range(count)]
    text = 'v2p1f0 a b aa: `$a$`, \\(v2p1f0\\), code {"blockId":"a"}'
    blocks = [{'id': source, 'page': 1, 'text': text, 'kind': 'text'} for source in ids]
    job = {'id': 'local-job', 'title': text, 'blocks': copy.deepcopy(blocks)}
    payload = {'task': 'region_teaching', 'titleHint': text, 'blocks': blocks,
               'entryHints': [{'title': text, 'startsAt': source} for source in ids],
               'crops': [{'page': 1, 'blockIds': ids}],
               'neighboringContext': [{'text': text}],
               'documentContext': {'openingCues': [text]},
               'headingOptions': [{'id': 'h:v2p1f0', 'title': text}],
               'selectedHeading': 'h:v2p1f0'}
    return payload, job, ids, text


def reply(text):
    return {'concepts': [{'title': text, 'sourceSetup': {'observedRelations': [text]},
                         'selectedHeading': 'a', 'segments': [
                             {'kind': 'definition', 'text': text, 'blockIds': ['a']},
                             {'kind': 'explanation', 'text': text, 'blockIds': ['b', 'c', 'a']},
                             {'kind': 'easyExplanation', 'text': text, 'blockIds': ['c']},
                             {'kind': 'uncertain', 'text': text, 'blockIds': ['b']}]}],
            'tables': [{'conceptTitle': text, 'headers': ['a', 'v2p1f0'],
                        'rows': [['b', 'c'], ['v2p1f0', text]], 'blockIds': ['a', 'b']}],
            'sequences': [{'conceptTitle': text, 'title': text, 'steps': [
                {'title': text, 'body': text, 'blockIds': ['c', 'a']}],
                'transitions':[{'fromStep':0,'toStep':1,'relation':text,
                                'blockIds':['a','c'],'sourceQuote':text}]}],
            'uncertainBlocks': [{'blockId': 'b', 'reason': text}],
            'excludedBlocks': [{'blockId': 'c', 'reason': text}],
            'selectedHeading': 'a', 'unrelatedMetadata': {'blockId': 'a'}}


class SourceAliasTests(unittest.TestCase):
    def test_optional_lowercase_prefix_preserves_default_and_fixed_pool(self):
        payload, job, ids, text = fixture()
        self.assertEqual(encode(payload, STUDY_FORMAT, job),
                         encode(payload, STUDY_FORMAT, job, alias_prefix=''))
        before = copy.deepcopy((payload, job, STUDY_FORMAT))
        wire, schema, mapping = encode(payload, STUDY_FORMAT, job, alias_prefix='ua', stable_pool_size=32)
        self.assertEqual(mapping, dict(zip(('uaa', 'uab', 'uac'), ids)))
        self.assertEqual([block['id'] for block in wire['blocks']], ['uaa', 'uab', 'uac'])
        pool = schema['json_schema']['schema']['$defs']['studySourceId']['enum']
        self.assertEqual((pool[0], pool[-1], len(pool)), ('uaa', 'uaaf', 32))
        self.assertEqual(wire['titleHint'], text)
        self.assertEqual((payload, job, STUDY_FORMAT), before)
        raw = reply(text)
        def prefix(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == 'blockIds':node[key] = ['ua'+key for key in value]
                    elif key == 'blockId':node[key] = 'ua'+value
                    elif isinstance(value, (dict, list)):prefix(value)
            elif isinstance(node, list):
                for value in node:prefix(value)
        # Do not use unrelatedMetadata; it is deliberately outside decoder slots.
        del raw['unrelatedMetadata'];prefix(raw)
        restored = decode(raw, mapping)
        self.assertEqual(restored['concepts'][0]['segments'][0]['blockIds'], ids[:1])
        self.assertEqual(restored['concepts'][0]['segments'][0]['text'], text)
        self.assertEqual(restored['selectedHeading'], 'a')
        for invalid in (None, True, 1, 'u0', 'u_a', 'UA', '한글'):
            with self.subTest(prefix=invalid), self.assertRaises(SourceAliasError):
                encode(payload, STUDY_FORMAT, job, alias_prefix=invalid)

    def test_schema_buckets_grow_without_truncating_any_source(self):
        for count,expected in ((1,32),(22,32),(32,32),(33,64),(64,64),(65,128),(256,256),(257,512)):
            self.assertEqual(bucket_pool_size(count),expected)
        self.assertEqual(bucket_pool_size(1,minimum=1),1)
        self.assertEqual(bucket_pool_size(33,minimum=33),64)
        self.assertEqual(bucket_pool_size(1,minimum=64),64)
        for invalid in (0,-1,True,1.0,'32',None):
            with self.subTest(count=invalid), self.assertRaises(SourceAliasError):bucket_pool_size(invalid)
            with self.subTest(minimum=invalid), self.assertRaises(SourceAliasError):bucket_pool_size(1,minimum=invalid)

    def test_round_trip_changes_only_structured_source_slots(self):
        payload, job, ids, text = fixture()
        originals = copy.deepcopy((payload, STUDY_FORMAT, job))
        wire, schema, mapping = encode(payload, STUDY_FORMAT, job)
        self.assertEqual(mapping, dict(zip(('a', 'b', 'c'), ids)))
        expected = copy.deepcopy(payload)
        for index, block in enumerate(expected['blocks']):block['id'] = 'abc'[index]
        for index, hint in enumerate(expected['entryHints']):hint['startsAt'] = 'abc'[index]
        expected['crops'][0]['blockIds'] = ['a', 'b', 'c']
        self.assertEqual(wire, expected)
        self.assertEqual((payload, STUDY_FORMAT, job), originals)
        source_id = schema['json_schema']['schema']['$defs']['studySourceId']
        self.assertEqual(source_id['enum'], ['a', 'b', 'c'])
        # Shared SS schema objects must not constrain table text/math to source IDs.
        table = schema['json_schema']['schema']['properties']['tables']['items']['properties']
        self.assertEqual(table['headers']['items'], {'type': 'string'})
        self.assertEqual(table['rows']['items']['items'], {'type': 'string'})
        raw = reply(text); untouched = copy.deepcopy(raw)
        decoded = decode(raw, mapping)
        self.assertEqual(raw, untouched)
        self.assertEqual(decoded['concepts'][0]['segments'][1]['blockIds'], [ids[1], ids[2], ids[0]])
        self.assertEqual(decoded['tables'][0]['blockIds'], ids[:2])
        self.assertEqual(decoded['sequences'][0]['steps'][0]['blockIds'], [ids[2], ids[0]])
        self.assertEqual(decoded['sequences'][0]['transitions'][0],
                         {**raw['sequences'][0]['transitions'][0],'blockIds':[ids[0],ids[2]]})
        self.assertEqual(decoded['uncertainBlocks'][0]['blockId'], ids[1])
        self.assertEqual(decoded['excludedBlocks'][0]['blockId'], ids[2])
        self.assertEqual(decoded['selectedHeading'], 'a')
        self.assertEqual(decoded['concepts'][0]['selectedHeading'], 'a')
        self.assertEqual(decoded['unrelatedMetadata'], {'blockId': 'a'})
        self.assertEqual(decoded['concepts'][0]['segments'][0]['text'], text)
        self.assertEqual(decoded['tables'][0]['headers'], raw['tables'][0]['headers'])
        self.assertEqual(decoded['tables'][0]['rows'], raw['tables'][0]['rows'])
        self.assertEqual(decoded['sequences'][0]['steps'][0]['body'], text)
        self.assertEqual(decoded['excludedBlocks'][0]['reason'], text)
        decoded['tables'][0]['rows'].append(['changed', 'only output'])
        self.assertEqual(raw, untouched)

    def test_more_than_26_targets_have_stable_unique_short_names(self):
        payload, job, ids, _ = fixture(705)
        wire, schema, mapping = encode(payload, STUDY_FORMAT, job)
        aliases = list(mapping)
        self.assertEqual([aliases[i] for i in (0, 25, 26, 51, 52, 701, 702, 704)],
                         ['a', 'z', 'aa', 'az', 'ba', 'zz', 'aaa', 'aac'])
        self.assertEqual(list(mapping.values()), ids)
        self.assertEqual(len(set(aliases)), len(ids))
        self.assertEqual(encode(payload, STUDY_FORMAT, job), (wire, schema, mapping))
        encoded = {'tables': [{'headers': ['a', 'b'], 'rows': [], 'blockIds': aliases}]}
        self.assertEqual(decode(encoded, mapping)['tables'][0]['blockIds'], ids)

    def test_aliases_follow_job_order_even_if_payload_order_differs(self):
        payload, job, ids, _ = fixture()
        payload['blocks'].reverse()
        wire, _, mapping = encode(payload, STUDY_FORMAT, job)
        self.assertEqual(list(mapping.values()), ids)
        self.assertEqual([b['id'] for b in wire['blocks']], ['c', 'b', 'a'])

    def test_an_already_constrained_format_replaces_only_source_enum(self):
        payload, job, _, _ = fixture()
        original = constrained_format(STUDY_FORMAT, job); before = copy.deepcopy(original)
        _, wire, _ = encode(payload, original, job)
        self.assertEqual(original, before)
        self.assertEqual(wire['json_schema']['schema']['$defs']['studySourceId']['enum'], ['a', 'b', 'c'])
        bad = copy.deepcopy(original)
        bad['json_schema']['schema']['$defs']['studySourceId']['enum'] = ['v2p1f0']
        with self.assertRaises(SourceAliasError):encode(payload, bad, job)

    def test_targets_hints_and_crop_references_must_be_complete_and_known(self):
        for mutation in ('duplicate_job', 'empty_job', 'missing_target', 'unknown_target',
                         'duplicate_target', 'unknown_hint', 'missing_hint', 'unknown_crop', 'missing_crop'):
            with self.subTest(mutation=mutation):
                payload, job, _, _ = fixture()
                if mutation == 'duplicate_job':job['blocks'].append(job['blocks'][0])
                if mutation == 'empty_job':job['blocks'] = []
                if mutation == 'missing_target':payload['blocks'].pop()
                if mutation == 'unknown_target':payload['blocks'][0]['id'] = 'unknown'
                if mutation == 'duplicate_target':payload['blocks'][1]['id'] = payload['blocks'][0]['id']
                if mutation == 'unknown_hint':payload['entryHints'][0]['startsAt'] = 'unknown'
                if mutation == 'missing_hint':del payload['entryHints'][0]['startsAt']
                if mutation == 'unknown_crop':payload['crops'][0]['blockIds'] = ['unknown']
                if mutation == 'missing_crop':del payload['crops'][0]['blockIds']
                before = copy.deepcopy((payload, job))
                with self.assertRaises(SourceAliasError):encode(payload, STUDY_FORMAT, job)
                self.assertEqual((payload, job), before)

    def test_unknown_missing_or_malformed_response_citations_fail_without_mutation(self):
        payload, job, _, _ = fixture()
        _, _, mapping = encode(payload, STUDY_FORMAT, job)
        for location in ('segment', 'table', 'step', 'transition', 'uncertain', 'excluded'):
            for invalid in ('unknown', None, 1, ['a']):
                with self.subTest(location=location, invalid=invalid):
                    raw = reply('prose stays a v2p1f0')
                    if location == 'segment':raw['concepts'][0]['segments'][0]['blockIds'] = invalid
                    if location == 'table':raw['tables'][0]['blockIds'] = invalid
                    if location == 'step':raw['sequences'][0]['steps'][0]['blockIds'] = invalid
                    if location == 'transition':raw['sequences'][0]['transitions'][0]['blockIds'] = invalid
                    if location == 'uncertain':raw['uncertainBlocks'][0]['blockId'] = invalid
                    if location == 'excluded':raw['excludedBlocks'][0]['blockId'] = invalid
                    # ['a'] is a valid plural citation; use an unknown member instead.
                    if location in ('segment', 'table', 'step', 'transition') and invalid == ['a']:continue
                    before = copy.deepcopy(raw)
                    with self.assertRaises(SourceAliasError):decode(raw, mapping)
                    self.assertEqual(raw, before)
        for raw in ({'concepts': [{'segments': [{}]}]}, {'tables': [{}]},
                    {'sequences': [{'steps': [{}]}]}, {'sequences':[{'transitions':[{}]}]},
                    {'uncertainBlocks': [{}]}, {'excludedBlocks': [{}]}):
            with self.assertRaises(SourceAliasError):decode(raw, mapping)
        with self.assertRaises(SourceAliasError):decode({'tables': [{'blockIds': ['a', 'unknown']}]}, mapping)

    def test_fixed_pool_changes_only_schema_and_rejects_unused_aliases(self):
        payload,job,ids,text=fixture()
        before=copy.deepcopy((payload,job,STUDY_FORMAT))
        exact,exact_format,exact_mapping=encode(payload,STUDY_FORMAT,job)
        wire,schema,mapping=encode(payload,STUDY_FORMAT,job,stable_pool_size=32)
        self.assertEqual((wire,mapping),(exact,exact_mapping))
        expected=copy.deepcopy(exact_format)
        expected['json_schema']['schema']['$defs']['studySourceId']['enum']=[
            chr(ord('a')+i) for i in range(26)]+['aa','ab','ac','ad','ae','af']
        self.assertEqual(schema,expected)
        self.assertEqual((payload,job,STUDY_FORMAT),before)
        self.assertEqual(decode(reply(text),mapping)['sequences'][0]['transitions'][0]['blockIds'],[ids[0],ids[2]])
        for raw in ({'concepts':[{'segments':[{'blockIds':['d']}]}]},
                    {'sequences':[{'transitions':[{'blockIds':['af']}]}]},
                    {'excludedBlocks':[{'blockId':'d'}]}):
            original=copy.deepcopy(raw)
            with self.assertRaises(SourceAliasError):decode(raw,mapping)
            self.assertEqual(raw,original)

    def test_same_pool_is_the_same_schema_for_different_actual_counts(self):
        formats=[]
        for count in (1,3,22,32):
            payload,job,ids,_=fixture(count)
            _,schema,mapping=encode(payload,STUDY_FORMAT,job,stable_pool_size=32)
            self.assertEqual(len(mapping),count)
            self.assertEqual(list(mapping.values()),ids)
            formats.append(schema)
        self.assertTrue(all(schema==formats[0] for schema in formats))
        payload,job,_,_=fixture()
        for invalid in (0,-1,2,True,32.0,'32'):
            with self.subTest(pool=invalid), self.assertRaises(SourceAliasError):
                encode(payload,STUDY_FORMAT,job,stable_pool_size=invalid)

    def test_schema_walk_covers_every_current_structured_source_reference(self):
        payload,job,ids,text=fixture()
        _,schema,mapping=encode(payload,STUDY_FORMAT,job,stable_pool_size=32)
        paths=[]
        raw=self.schema_reply(schema['json_schema']['schema'],text,paths=paths)
        before=copy.deepcopy(raw)
        decoded=decode(raw,mapping)
        self.assertTrue(any('transitions' in path for path in paths))
        self.assertGreaterEqual(len(paths),6)
        for path in paths:
            original,restored=raw,decoded
            for part in path:original,restored=original[part],restored[part]
            self.assertEqual(original,'b')
            self.assertEqual(restored,ids[1],path)
        # Replacing just the schema-declared citation leaves identical prose,
        # sourceSetup strings, tables, titles, code and transition witnesses.
        stripped=copy.deepcopy(decoded)
        for path in paths:
            node=stripped
            for part in path[:-1]:node=node[part]
            node[path[-1]]='b'
        self.assertEqual(stripped,raw)
        self.assertEqual(raw,before)

    def test_optional_wire_adapters_restore_all_sources_before_alias_decode(self):
        from pdf_owned_teaching import encode_format as owned_format, decode as owned_decode
        from pdf_source_facts import encode_format as facts_format, decode as facts_decode
        payload,job,ids,text=fixture()
        for owned,facts in ((False,True),(True,False),(True,True)):
            with self.subTest(owned=owned,facts=facts):
                _,schema,mapping=encode(payload,STUDY_FORMAT,job,stable_pool_size=32)
                if owned:schema=owned_format(schema)
                if facts:schema=facts_format(schema)
                wire=self.schema_reply(schema['json_schema']['schema'],text)
                original=copy.deepcopy(wire)
                raw=facts_decode(wire) if facts else wire
                raw=owned_decode(raw) if owned else raw
                restored=decode(raw,mapping)
                refs=[]
                def walk(value):
                    if isinstance(value,dict):
                        for name,item in value.items():
                            if name=='blockIds':refs.extend(item)
                            elif name=='blockId':refs.append(item)
                            elif isinstance(item,(dict,list)):walk(item)
                    elif isinstance(value,list):
                        for item in value:walk(item)
                walk(restored)
                self.assertTrue(refs)
                self.assertEqual(set(refs),{ids[1]})
                self.assertEqual(restored['concepts'][0]['segments'][0]['text'],text)
                self.assertEqual(wire,original)

    @staticmethod
    def schema_reply(schema,text,*,paths=None):
        paths=[] if paths is None else paths
        definitions=schema.get('$defs',{})
        def build(node,path=()):
            if '$ref' in node:
                if node['$ref']=='#/$defs/studySourceId':
                    paths.append(path);return 'b'
                return build(definitions[node['$ref'].split('/')[-1]],path)
            if 'anyOf' in node:return build(node['anyOf'][0],path)
            if node.get('type')=='object':
                return {name:build(item,path+(name,)) for name,item in node.get('properties',{}).items()}
            if node.get('type')=='array':return [build(node['items'],path+(0,))]
            if 'enum' in node:return node['enum'][0]
            if node.get('type')=='boolean':return False
            if node.get('type') in ('integer','number'):return 0
            return text
        return build(schema)

    def test_bad_and_ambiguous_mappings_are_rejected(self):
        for mapping in ({}, None, {'a': None}, {'a': 'v2p1f0', 'b': 'v2p1f0'},
                        {'A': 'v2p1f0'}, {'a': 'b', 'b': 'v2p1f0'}):
            with self.subTest(mapping=mapping):
                with self.assertRaises(SourceAliasError):decode({}, mapping)

    def test_empty_reference_lists_and_duplicate_references_are_not_invented_or_dropped(self):
        payload, job, ids, _ = fixture();_, _, mapping = encode(payload, STUDY_FORMAT, job)
        result = decode({'tables': [{'blockIds': []}, {'blockIds': ['a', 'a']}]}, mapping)
        self.assertEqual([t['blockIds'] for t in result['tables']], [[], [ids[0], ids[0]]])

    def test_canonical_cache_cannot_be_accidentally_decoded_as_a_wire_reply(self):
        payload, job, ids, _ = fixture();_, _, mapping = encode(payload, STUDY_FORMAT, job)
        with self.assertRaises(SourceAliasError):decode({'tables': [{'blockIds': [ids[0]]}]}, mapping)

    def test_wire_changes_no_source_text_and_saves_id_characters(self):
        payload, job, _, _ = fixture(60);wire, schema, mapping = encode(payload, STUDY_FORMAT, job)
        self.assertEqual([b['text'] for b in wire['blocks']], [b['text'] for b in payload['blocks']])
        canonical_schema = constrained_format(STUDY_FORMAT, job)
        self.assertLess(len(json.dumps([wire, schema])), len(json.dumps([payload, canonical_schema])))


if __name__ == '__main__':
    unittest.main()
