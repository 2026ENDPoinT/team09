"""Offline facts→learner transport tests; no external files, credentials or API."""
import copy
import socket
import unittest
from unittest.mock import patch

import pdf_new_concept_ver99_study as study
import pdf_owned_teaching as owned
import pdf_source_aliases as aliases
import pdf_source_facts as facts
from pdf_new_concept_ver99_checks import prepare_response
from pdf_study_cache_reuse import constrained_format


class SourceFactsTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.blocks = [
            {'id': 'v2p1f0', 'page': 1, 'kind': 'text', 'bbox': [0, 0, .5, 1],
             'text': '관찰된 크기와 단위예요.', 'hasVisual': False, 'planRole': 'teaching'},
            {'id': 'v2p1f1', 'page': 1, 'kind': 'text', 'bbox': [.5, 0, 1, 1],
             'text': '과정과 관계를 설명해요.', 'hasVisual': False, 'planRole': 'teaching'},
        ]
        self.job = {'id': 'synthetic-facts', 'title': '양과 관계', 'blocks': self.blocks}
        self.document = {'documentId': 'synthetic-document', 'pages': [{'label': '1'}]}
        self.raw = {'concepts': [{
            'title': '측정량과 관계',
            'sourceSetup': {'observedRelations': [
                {'learnerText': '총량은 12 kg이며 부분량 5 kg와 7 kg의 합이에요.',
                 'blockIds': ['v2p1f0']}],
                'boundaryChecks': [], 'interpretation': ''},
            'segments': [
                {'kind': 'definition', 'text': '총량은 여러 부분을 합친 양이에요.', 'blockIds': ['v2p1f0']},
                {'kind': 'explanation', 'text': '같은 단위의 부분량을 더해 전체 관계를 설명해요.', 'blockIds': ['v2p1f0', 'v2p1f1']},
                {'kind': 'easyExplanation', 'text': '두 묶음을 합쳐 한 묶음으로 생각해요.', 'blockIds': ['v2p1f1']}],
            'standardKnowledgeUsed': False}],
            'sequences': [], 'tables': [], 'excludedBlocks': [], 'uncertainBlocks': []}

    def test_schema_couples_facts_with_exact_existing_source_constraints_without_mutation(self):
        original = constrained_format(study.STUDY_FORMAT, self.job)
        before = copy.deepcopy(original)
        encoded = facts.encode_format(original)
        self.assertEqual(original, before)
        schema = encoded['json_schema']['schema']
        concept = schema['properties']['concepts']['items']['properties']
        fact = concept['sourceSetup']['properties']['observedRelations']['items']
        self.assertEqual(set(fact['required']), {'learnerText', 'blockIds'})
        self.assertNotIn('sourceQuote', fact['properties'])
        self.assertFalse(fact['additionalProperties'])
        self.assertEqual(fact['properties']['blockIds'], concept['segments']['items']['properties']['blockIds'])
        self.assertEqual(schema['$defs'], before['json_schema']['schema']['$defs'])
        for name in ['boundaryChecks', 'interpretation']:
            self.assertEqual(concept['sourceSetup']['properties'][name], before['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties'][name])
        # All root constraints, source enums and non-observation fields survive.
        reverted = copy.deepcopy(encoded)
        reverted['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']['observedRelations'] = copy.deepcopy(before['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']['observedRelations'])
        self.assertEqual(reverted, before)

    def test_decoding_canonicalizes_source_notes_and_teaches_fact_once_without_mutation(self):
        before = copy.deepcopy(self.raw)
        result = facts.decode(self.raw)
        self.assertEqual(self.raw, before)
        concept = result['concepts'][0]
        observed = before['concepts'][0]['sourceSetup']['observedRelations'][0]
        self.assertEqual(concept['sourceSetup']['observedRelations'], [observed['learnerText']])
        self.assertEqual(concept['segments'][1], {'kind': 'explanation', 'text': observed['learnerText'], 'blockIds': observed['blockIds']})
        self.assertEqual([concept['segments'][i] for i in (0, 2, 3)], before['concepts'][0]['segments'])
        unit = study.validate(result, self.job, self.document)
        self.assertIn(observed['learnerText'], unit['summary']['parts'][0]['body'])
        self.assertEqual(unit['summary']['parts'][0]['body'].count(observed['learnerText']), 1)

    def test_tex_code_whitespace_captions_and_boundary_checks_preserve_exact_bytes(self):
        literal = '原形  ' + r'\(W=\lim_{n\to\infty}\sum_{i=1}^{n}F(x_i^*)\Delta x\)' + '\n```c\nint (*p)[7];\n```\n'
        concept = self.raw['concepts'][0]
        fact = concept['sourceSetup']['observedRelations'][0]
        fact['learnerText'] = literal
        concept['sourceSetup']['boundaryChecks'] = ['x=0 → r=3', 'x=2 → r=5']
        concept['sourceSetup']['interpretation'] = 'r=|x+3|'
        concept['headingSelection'] = {'source': 'v2p1f0', 'mode': 'body'}
        self.raw['tables'] = [{'conceptTitle': concept['title'], 'headers': ['종류', '값'], 'rows': [['A', '3'], ['B', '4']], 'blockIds': ['v2p1f0'], 'caption': literal}]
        result = facts.decode(self.raw)
        out = result['concepts'][0]
        self.assertEqual(out['sourceSetup']['observedRelations'][0], literal)
        self.assertEqual(out['segments'][1]['text'], literal)
        for key in ['boundaryChecks', 'interpretation']:
            self.assertEqual(out['sourceSetup'][key], concept['sourceSetup'][key])
        self.assertEqual(out['headingSelection'], concept['headingSelection'])
        self.assertEqual(result['tables'], self.raw['tables'])

    def test_only_exact_new_explanation_duplicates_are_suppressed(self):
        concept = self.raw['concepts'][0]
        fact = concept['sourceSetup']['observedRelations'][0]
        concept['segments'][1] = {'kind': 'explanation', 'text': fact['learnerText'], 'blockIds': fact['blockIds'][:]}
        concept['sourceSetup']['observedRelations'].append(copy.deepcopy(fact))
        self.assertEqual(facts.decode(self.raw)['concepts'][0]['segments'], concept['segments'])
        # A substring, different ordered citations or distinct whitespace is not an exact duplicate.
        for change in ['substring', 'citations', 'whitespace']:
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                new = raw['concepts'][0]['sourceSetup']['observedRelations'][0]
                if change == 'substring': new['learnerText'] += ' 추가로 같은 단위를 사용해요.'
                elif change == 'citations': new['blockIds'] = ['v2p1f1']
                else: new['learnerText'] += ' '
                result = facts.decode(raw)
                self.assertEqual(len(result['concepts'][0]['segments']), 4)
                self.assertEqual(result['concepts'][0]['segments'][2], concept['segments'][1])

    def test_aliases_and_owned_tables_compose_with_facts_before_canonical_validation(self):
        payload = study.teaching_payload(self.job, [], {}, [])
        _, alias_format, mapping = aliases.encode(payload, study.STUDY_FORMAT, self.job)
        first = owned.encode_format(facts.encode_format(alias_format))
        second = facts.encode_format(owned.encode_format(alias_format))
        self.assertEqual(first, second)
        wire = copy.deepcopy(self.raw)
        for fact in wire['concepts'][0]['sourceSetup']['observedRelations']:
            fact['blockIds'] = ['a']
        for segment in wire['concepts'][0]['segments']:
            segment['blockIds'] = ['a' if x == 'v2p1f0' else 'b' for x in segment['blockIds']]
        wire['concepts'][0]['tables'] = [{'headers': ['종류', '값'], 'rows': [['A', '3'], ['B', '4']], 'blockIds': ['a']}]
        wire['concepts'][0]['sequences'] = []
        del wire['tables'], wire['sequences']
        canonical = aliases.decode(owned.decode(facts.decode(wire)), mapping)
        unit = study.validate(canonical, self.job, self.document)
        self.assertIn('총량은 12 kg', unit['summary']['parts'][0]['body'])
        self.assertIn('| A | 3 |', unit['summary']['parts'][0]['body'])
        self.assertEqual(canonical['concepts'][0]['sourceSetup']['observedRelations'], ['총량은 12 kg이며 부분량 5 kg와 7 kg의 합이에요.'])

    def test_unknown_ids_are_not_repaired_and_existing_validator_rejects_them(self):
        self.raw['concepts'][0]['sourceSetup']['observedRelations'][0]['blockIds'] = ['unknown']
        canonical = facts.decode(self.raw)
        self.assertEqual(canonical['concepts'][0]['segments'][1]['blockIds'], ['unknown'])
        with self.assertRaises(ValueError):
            study.validate(canonical, self.job, self.document)
        canonical['concepts'][0]['sourceSetup']['observedRelations'] = []
        with self.assertRaises(aliases.SourceAliasError):
            aliases.decode(canonical, {'a': 'v2p1f0', 'b': 'v2p1f1'})

    def test_uncertain_source_and_math_gates_are_not_bypassed(self):
        raw = copy.deepcopy(self.raw)
        raw['uncertainBlocks'] = [{'blockId': 'v2p1f0', 'reason': '읽을 수 없어요.'}]
        fact_text = raw['concepts'][0]['sourceSetup']['observedRelations'][0]['learnerText']
        prepared = prepare_response(facts.decode(raw))
        self.assertFalse(any(fact_text in concept.get('explanation', '') for concept in prepared['concepts']))
        self.assertTrue(prepared['uncertainBlocks'])
        raw = copy.deepcopy(self.raw)
        fact_text = raw['concepts'][0]['sourceSetup']['observedRelations'][0]['learnerText'] = r'\(2+2=5\)예요.'
        prepared = prepare_response(facts.decode(raw))
        self.assertFalse(any(fact_text in concept.get('explanation', '') for concept in prepared['concepts']))
        self.assertTrue(prepared['uncertainBlocks'])

    def test_malformed_facts_are_rejected_without_changing_input(self):
        for change in ['legacy_string', 'unknown', 'missing', 'old_source_quote', 'learner_type', 'learner_blank', 'ids_type', 'ids_empty', 'id_type', 'sourceSetup', 'segments', 'checks']:
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                setup = raw['concepts'][0]['sourceSetup']
                fact = setup['observedRelations'][0]
                if change == 'legacy_string': setup['observedRelations'][0] = 'old transport'
                elif change == 'unknown': fact['unexpected'] = 1
                elif change == 'missing': del fact['learnerText']
                elif change == 'old_source_quote': fact['sourceQuote'] = 'v2 shape is decoded only by its preserved v2 adapter.'
                elif change == 'learner_type': fact['learnerText'] = 1
                elif change == 'learner_blank': fact['learnerText'] = ' '
                elif change == 'ids_type': fact['blockIds'] = 'v2p1f0'
                elif change == 'ids_empty': fact['blockIds'] = []
                elif change == 'id_type': fact['blockIds'] = [1]
                elif change == 'sourceSetup': raw['concepts'][0]['sourceSetup'] = []
                elif change == 'segments': raw['concepts'][0]['segments'] = {}
                else: setup['boundaryChecks'] = [1]
                before = copy.deepcopy(raw)
                with self.assertRaises(facts.SourceFactsError): facts.decode(raw)
                self.assertEqual(raw, before)

    def test_invalid_or_already_encoded_schemas_are_rejected(self):
        for change in ['strict', 'required', 'observations', 'segments', 'already_encoded']:
            with self.subTest(change=change):
                wire = copy.deepcopy(study.STUDY_FORMAT)
                concept = wire['json_schema']['schema']['properties']['concepts']['items']
                if change == 'strict': wire['json_schema']['strict'] = False
                elif change == 'required': concept['required'].remove('sourceSetup')
                elif change == 'observations': concept['properties']['sourceSetup']['properties']['observedRelations']['items'] = {'type': 'object'}
                elif change == 'segments': concept['properties']['segments']['type'] = 'object'
                else: wire = facts.encode_format(wire)
                with self.assertRaises(facts.SourceFactsError): facts.encode_format(wire)

    def test_empty_facts_and_empty_concepts_remain_canonical_and_no_extra_work(self):
        self.raw['concepts'][0]['sourceSetup']['observedRelations'] = []
        self.assertEqual(facts.decode(self.raw), self.raw)
        self.raw['concepts'] = []
        self.assertEqual(facts.decode(self.raw), self.raw)


if __name__ == '__main__':
    unittest.main()
