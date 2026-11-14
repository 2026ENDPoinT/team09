"""Offline fail-closed contracts for the real independent quiz review stage."""
import copy
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
import pdf_quiz_review as review
from test_pdf_quiz import FakeProvider, fixture, planned, question


def approve(payload):
    return {'reviews': [verdict(row) for row in payload['candidates']]}


def independent_solution(candidate, answer=None):
    """Solve the fixture by its known contract, without reading a hidden key."""
    kind = candidate['type']
    answer = answer if answer is not None else {
        'mcq': 'A', 'word': '용어', 'ox': 'O', 'essay': '모범 답안'}[kind]
    return {'answer': answer, 'explanation': '독립 풀이로 조건과 원문을 대조한 결과이다.',
            'optionExplanations': [{'id': option['id'], 'explanation': '독립 판단 ' + option['id']}
                                   for option in candidate.get('options', [])] if kind == 'mcq' else [],
            'keyPoints': ['핵심 조건'] if kind == 'essay' else []}


def revision(candidate):
    """Build a complete replacement; review payloads deliberately omit answers."""
    fields = ('type', 'conceptIds', 'stem', 'options', 'answer', 'explanation', 'keyPoints')
    return {**{key: copy.deepcopy(candidate[key]) for key in fields},
            'evidence': [{'sourceId': e['sourceId'], 'quote': e['quote']} for e in candidate['evidence']]}


def verdict(row, **changes):
    candidate = row['question']
    solution = independent_solution(candidate)
    data = {'questionId': row['id'], 'decision': 'keep', 'issues': [],
            'reason': '원문과 조건을 대조하여 독립 풀이했다.', 'solvable': True,
            'answerSupported': True,
            'correctOptionIds': [solution['answer']] if candidate['type'] == 'mcq' else [],
            'difficultyAdequate': True, 'directApplicationOnly': False, 'unstatedAssumptions': [],
            'reasoningTask': '제시한 조건을 비교하여 결론을 도출한다.',
            'wordingClear': True, 'replacement': None, 'solution': solution}
    if changes.get('decision') in ('revise', 'reject'):
        data['solution'] = None
    data.update(changes)
    return data


class QuizReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.document, self.request = fixture(4, size=2)
        self.document['pages'][0]['nativeText'] = 'PDF 원문 첫 페이지. 독립 풀이에 필요한 원래 조건이다.'
        self.document['pages'][1]['nativeText'] = 'PDF 원문 둘째 페이지. 다른 개념의 원문이다.'
        self.config, _, _, self.concepts, self.sources = quiz.context(self.document, self.request)
        images_patch = patch.object(review, '_images', return_value=([], [], []))
        self.images = images_patch.start()
        self.addCleanup(images_patch.stop)
        recheck_patch = patch.object(review, 'VERIFY_REVISED_QUESTIONS', False)
        recheck_patch.start()
        self.addCleanup(recheck_patch.stop)

    def candidates(self, kinds=('mcq',), cid='c1'):
        rows, assignment_by_id = [], {}
        for index, kind in enumerate(kinds):
            assignment = {'unitId': 'unit-' + str(index), 'conceptIds': [cid],
                          'counts': {t: int(t == kind) for t in quiz.TYPES}, 'focus': '조건 비교'}
            raw = question(kind, cid, stem=f'{index}번 사례의 조건을 판단하시오.')
            candidate = quiz._question(raw, assignment, self.concepts, self.sources)
            candidate['id'] = 'candidate-' + str(index)
            rows.append(candidate)
            assignment_by_id[candidate['id']] = assignment
        return rows, assignment_by_id

    def run_review(self, replies, candidates=None, assignments=None, on_progress=None, previous=None):
        if candidates is None:
            candidates, assignments = self.candidates()
        provider = FakeProvider(replies)
        accepted, audit = review.review_candidates(self.folder, self.document, self.config,
            candidates, self.concepts, self.sources, provider, assignments, previous or set(),
            on_progress=on_progress)
        return accepted, audit, provider

    def test_real_review_keeps_verified_types_and_passes_shared_quality_once(self):
        candidates, assignments = self.candidates(('mcq', 'word', 'ox', 'essay'))
        accepted, audit, provider = self.run_review([approve], candidates, assignments)
        self.assertEqual([q['id'] for q in accepted], [q['id'] for q in candidates])
        self.assertEqual((audit['status'], audit['reviewed'], audit['accepted'], audit['calls']),
                         ('passed', 4, 4, 1))
        self.assertEqual(provider.calls[0][2]['kind'], 'quiz_review')
        self.assertEqual(provider.calls[0][2]['reasoningEffort'], 'low')
        self.assertEqual(provider.context, {})
        payload, options, _ = provider.calls[0]
        quality = (review.PROMPTS / 'quality.md').read_text().strip()
        self.assertEqual(options['system_prompt'].count(quality), 1)
        self.assertEqual(payload['task'], 'quiz_review')
        self.assertNotIn('outline', payload)

    def test_blind_payload_never_exposes_draft_answer_or_any_draft_explanation(self):
        candidates, assignments = self.candidates()
        candidates[0]['answer'] = 'D'
        candidates[0]['explanation'] = 'SECRET_DRAFT_GENERAL_EXPLANATION'
        candidates[0]['keyPoints'] = ['SECRET_DRAFT_KEY_POINT']
        for option in candidates[0]['options']:
            option['explanation'] = 'SECRET_DRAFT_OPTION_EXPLANATION_' + option['id']
        _, _, provider = self.run_review([approve], candidates, assignments)
        row = provider.calls[0][0]['candidates'][0]['question']
        self.assertEqual(set(row), {'type', 'conceptIds', 'stem', 'options', 'evidence'})
        self.assertTrue(all(set(o) == {'id', 'text'} for o in row['options']))
        self.assertNotIn('SECRET_DRAFT', json.dumps(provider.calls[0][0], ensure_ascii=False))

    def test_keep_uses_independent_solution_and_maps_option_explanations_by_id(self):
        candidates, assignments = self.candidates()
        before = copy.deepcopy(candidates)
        def reply(payload):
            row = payload['candidates'][0]
            solution = independent_solution(row['question'])
            solution['explanation'] = '독립 풀이 첫 줄\n' + r'\(F=ma\)' + '\n최종 결론이다.'
            solution['optionExplanations'].reverse()
            return {'reviews': [verdict(row, solution=solution)]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(len(accepted), 1)
        final = accepted[0]
        self.assertEqual(final['id'], candidates[0]['id'])
        self.assertEqual(final['stem'], candidates[0]['stem'])
        self.assertEqual(final['evidence'], candidates[0]['evidence'])
        self.assertEqual(final['explanation'], '독립 풀이 첫 줄\n' + r'\(F=ma\)' + '\n최종 결론이다.')
        self.assertEqual([o['id'] for o in final['options']], ['A', 'B', 'C', 'D'])
        self.assertEqual({o['id']: o['explanation'] for o in final['options']},
                         {key: '독립 판단 ' + key for key in 'ABCD'})
        self.assertEqual(audit['revised'], 0)
        self.assertEqual(candidates, before)

    def test_blind_solution_disagreement_is_withheld_and_changed_key_is_recorded(self):
        candidates, assignments = self.candidates()
        candidates[0]['answer'] = 'D'
        accepted, audit, provider = self.run_review([approve], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(candidates[0]['answer'], 'D')
        self.assertEqual(audit['revised'], 0)
        self.assertTrue(audit['reviews'][0]['answerKeyChanged'])
        self.assertEqual(audit['reviews'][0]['publicationDecision'], 'reject')
        self.assertEqual(len(provider.calls), 1)

    def test_ox_disagreement_is_withheld_but_free_response_rewording_is_not_graded(self):
        for kind, old_answer, changed in [('ox', 'X', True), ('word', '원래 명칭', False), ('essay', '기존 표현', False)]:
            with self.subTest(kind=kind):
                candidates, assignments = self.candidates((kind,))
                candidates[0]['answer'] = old_answer
                accepted, audit, provider = self.run_review([approve], candidates, assignments)
                self.assertEqual(len(accepted), 0 if changed else 1)
                self.assertEqual(audit['revised'], 0)
                self.assertEqual(audit['reviews'][0]['answerKeyChanged'], changed)
                self.assertEqual(len(provider.calls), 1)

    def test_matching_correct_ids_cannot_approve_an_unconfirmed_blind_key_change(self):
        candidates, assignments = self.candidates()
        for correct_ids in [['A'], ['B']]:
            with self.subTest(correct_ids=correct_ids):
                def reply(payload):
                    row = payload['candidates'][0]
                    return {'reviews': [verdict(row, correctOptionIds=correct_ids,
                        solution=independent_solution(row['question'], 'B'))]}
                accepted, audit, provider = self.run_review([reply], candidates, assignments)
                self.assertEqual(accepted, [])
                self.assertTrue(audit['reviews'][0]['answerKeyChanged'])
                self.assertEqual(audit['reviews'][0]['publicationDecision'], 'reject')
                self.assertEqual(len(provider.calls), 1)

    def test_missing_null_or_incomplete_independent_solution_fails_closed(self):
        for mutation in ('missing', 'null', 'list', 'empty', 'missing_answer', 'missing_explanation', 'missing_keyPoints'):
            with self.subTest(mutation=mutation):
                def reply(payload):
                    row = verdict(payload['candidates'][0])
                    if mutation == 'missing': row.pop('solution')
                    elif mutation == 'null': row['solution'] = None
                    elif mutation == 'list': row['solution'] = []
                    elif mutation == 'empty': row['solution'] = {}
                    else: row['solution'].pop(mutation.removeprefix('missing_'))
                    return {'reviews': [row]}
                accepted, audit, provider = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)
                self.assertEqual(len(provider.calls), 1)

    def test_malformed_independent_option_explanations_fail_closed(self):
        for mutation in ('missing_option', 'duplicate_id', 'blank_explanation', 'bad_type'):
            with self.subTest(mutation=mutation):
                def reply(payload):
                    row = verdict(payload['candidates'][0]); solution = row['solution']
                    if mutation == 'missing_option': solution['optionExplanations'].pop()
                    elif mutation == 'duplicate_id': solution['optionExplanations'][1]['id'] = 'A'
                    elif mutation == 'blank_explanation': solution['optionExplanations'][0]['explanation'] = ''
                    else: solution['optionExplanations'] = 'not a list'
                    return {'reviews': [row]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)

    def test_independent_solution_is_revalidated_for_question_type_and_free_guard(self):
        candidates, assignments = self.candidates(('word',))
        for mutation in ('formula', 'option_explanations'):
            with self.subTest(mutation=mutation):
                def reply(payload):
                    row = verdict(payload['candidates'][0]); solution = row['solution']
                    if mutation == 'formula': solution['answer'] = r'\int_0^1 f(x)dx'
                    elif mutation == 'option_explanations': solution['optionExplanations'] = [{'id': 'A', 'explanation': '선지 없음'}]
                    return {'reviews': [row]}
                accepted, audit, _ = self.run_review([reply], candidates, assignments)
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)

    def test_unused_word_solution_points_are_removed_but_essay_needs_comparison_points(self):
        candidates, assignments = self.candidates(('word',))
        def with_points(payload):
            row = verdict(payload['candidates'][0]); row['solution']['keyPoints'] = ['사용하지 않는 표시용 정보']
            return {'reviews': [row]}
        accepted, _, _ = self.run_review([with_points], candidates, assignments)
        self.assertEqual(accepted[0]['keyPoints'], [])
        candidates, assignments = self.candidates(('essay',))
        def without_points(payload):
            row = verdict(payload['candidates'][0]); row['solution']['keyPoints'] = []
            return {'reviews': [row]}
        accepted, audit, _ = self.run_review([without_points], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(audit['rejected'], 1)

    def test_revise_cannot_supply_an_ambiguous_second_solution(self):
        candidates, assignments = self.candidates()
        replacement = revision(candidates[0])
        def reply(payload):
            row = payload['candidates'][0]
            return {'reviews': [verdict(row, decision='revise', issues=['wording'],
                replacement=replacement, solution=independent_solution(row['question']))]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(audit['rejected'], 1)

    def test_response_schema_requires_explicit_review_and_nullable_replacement(self):
        data = review._schema()['json_schema']
        item = data['schema']['properties']['reviews']['items']
        self.assertTrue(data['strict'])
        self.assertFalse(item['additionalProperties'])
        self.assertEqual(set(item['required']), {
            'questionId', 'decision', 'issues', 'reason', 'solvable', 'answerSupported',
            'correctOptionIds', 'difficultyAdequate', 'directApplicationOnly', 'unstatedAssumptions',
            'reasoningTask', 'wordingClear', 'replacement', 'solution'})
        self.assertIn({'type': 'null'}, item['properties']['replacement']['anyOf'])
        solution = item['properties']['solution']['anyOf'][0]
        self.assertEqual(set(solution['required']), {'answer', 'explanation', 'optionExplanations', 'keyPoints'})
        self.assertFalse(solution['additionalProperties'])
        replacement = item['properties']['replacement']['anyOf'][0]
        evidence = replacement['properties']['evidence']['items']
        self.assertEqual(evidence['required'], ['sourceId', 'quoteId'])
        self.assertEqual(set(evidence['properties']), {'sourceId', 'quoteId'})
        self.assertFalse(evidence['additionalProperties'])

    def test_review_preserves_user_preferences_and_explicit_low_reasoning_context(self):
        self.config['instructions'] = '실험 사례를 사용하고, 문장은 짧게 작성해 주세요.'
        _, _, provider = self.run_review([approve])
        payload, _, context = provider.calls[0]
        self.assertEqual(payload['request']['instructions'], self.config['instructions'])
        self.assertEqual(context, {'kind': 'quiz_review', 'reasoningEffort': 'low'})

    def test_wire_sources_send_only_cited_summary_excerpts_but_all_original_text(self):
        native = ('첫 줄\n' + r'\(r=\frac{2}{5}(10-x)\)' + '\n원문을 잘라 버리지 않는다. ') * 21
        material = {
            'study:c1:e1': {'sourceId': 'study:c1:e1', 'sourceKind': 'saved_concept',
                            'text': '인용한 개념. 전송하지 않을 긴 요약 설명.', 'pages': [1]},
            'study:c2:e1': {'sourceId': 'study:c2:e1', 'sourceKind': 'saved_concept',
                            'text': '인용하지 않은 개념.', 'pages': [1]},
            's1': {'sourceId': 's1', 'sourceKind': 'native', 'text': '중복된 native chunk.', 'pages': [1]},
            'pdf:p1': {'sourceId': 'pdf:p1', 'sourceKind': 'native', 'text': native, 'pages': [1]},
        }
        candidates = [{'evidence': [{'sourceId': 'study:c1:e1', 'quote': '인용한 개념.'}]},
                      {'evidence': [{'sourceId': 'study:c1:e1', 'quote': '인용한 개념.'}]}]
        before = copy.deepcopy((material, candidates))
        wire, quotes = review._wire_sources(material, candidates)
        by_id = {source['sourceId']: source for source in wire}
        self.assertEqual(set(by_id), {'study:c1:e1', 'pdf:p1'})
        self.assertEqual(by_id['study:c1:e1']['quotes'], [{'quoteId': 'q1', 'text': '인용한 개념.'}])
        chunks = by_id['pdf:p1']['quotes']
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk['text']) <= 240 for chunk in chunks))
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), native)
        self.assertTrue(all(quotes[('pdf:p1', chunk['quoteId'])] == chunk['text'] for chunk in chunks))
        self.assertNotIn('전송하지 않을 긴 요약 설명', json.dumps(wire, ensure_ascii=False))
        self.assertEqual((material, candidates), before)

    def test_resolve_quote_ids_preserves_source_text_newlines_and_latex(self):
        exact = '원문 첫 줄\n' + r'\(W=\int_2^{10}1568\pi x(10-x)^2\,dx\)' + '\n원문 마지막 줄'
        raw = {'evidence': [{'sourceId': 'pdf:p1', 'quoteId': 'q2'},
                            {'sourceId': 'study:c1:e1', 'quote': '기존 정확 인용'}]}
        before = copy.deepcopy(raw)
        resolved = review._resolve_quotes(raw, {('pdf:p1', 'q2'): exact})
        self.assertEqual(resolved['evidence'][0], {'sourceId': 'pdf:p1', 'quote': exact})
        self.assertEqual(resolved['evidence'][1], raw['evidence'][1])
        self.assertEqual(raw, before)

    def test_unknown_quote_id_or_wrong_source_quote_pair_is_rejected(self):
        quotes = {('pdf:p1', 'q1'): '원문', ('study:c1:e1', 'q1'): '개념 인용'}
        for sid, qid in [('pdf:p1', 'q999'), ('unknown', 'q1'), ('study:c2:e1', 'q1')]:
            with self.subTest(sourceId=sid, quoteId=qid), self.assertRaises(ValueError):
                review._resolve_quotes({'evidence': [{'sourceId': sid, 'quoteId': qid}]}, quotes)

    def test_review_payload_omits_uncited_summary_body_and_keeps_complete_pdf(self):
        native = ('원본\n' + r'\(F=ma\)' + ' 원본 페이지 전체를 보존한다. ') * 22
        self.document['pages'][0]['nativeText'] = native
        _, _, provider = self.run_review([approve])
        payload = provider.calls[0][0]
        sources = {s['sourceId']: s for s in payload['sources']}
        self.assertEqual(sources['study:c1:e1']['quotes'], [{'quoteId': 'q1', 'text': '핵심 정의 1'}])
        self.assertNotIn('핵심 설명 1', json.dumps(payload['sources'], ensure_ascii=False))
        self.assertNotIn('비유는 출제하면 안 돼요', json.dumps(payload, ensure_ascii=False))
        self.assertNotIn('s1', sources)
        self.assertEqual(''.join(q['text'] for q in sources['pdf:p1']['quotes']), native)
        self.assertTrue(all('text' not in source for source in payload['sources']))
        self.assertEqual(set(payload['concepts'][0]['sourceIds']), set(sources))

    def test_a_keep_cannot_override_free_guard_for_exposed_answer(self):
        candidates, assignments = self.candidates(('word',))
        candidates[0].update(stem='탄동 진자에서 총알을 발사한다. 장치의 이름을 쓰시오.', answer='탄동 진자')
        def reply(payload):
            row = payload['candidates'][0]
            return {'reviews': [verdict(row, solution=independent_solution(row['question'], '탄동 진자'))]}
        accepted, audit, provider = self.run_review([reply], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(audit['rejected'], 1)
        self.assertEqual(audit['reviews'][0]['publicationDecision'], 'reject')
        self.assertIn('answer_in_stem', {i['code'] for i in provider.calls[0][0]['candidates'][0]['localIssues']})

    def test_same_review_call_can_fix_exposed_answer_without_changing_identity(self):
        candidates, assignments = self.candidates(('word',))
        candidates[0].update(stem='탄동 진자에서 총알을 발사한다. 장치의 이름을 쓰시오.', answer='탄동 진자')
        replacement = revision(candidates[0])
        replacement['stem'] = '총알이 박힌 나무토막의 상승 높이로 총알의 속력을 측정하는 장치의 이름을 쓰시오.'
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                issues=['answer_exposure'], replacement=replacement)]}
        accepted, audit, provider = self.run_review([reply], candidates, assignments)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['stem'], replacement['stem'])
        self.assertEqual(accepted[0]['id'], candidates[0]['id'])
        self.assertEqual((audit['revised'], len(provider.calls)), (1, 1))
        self.assertIn('탄동 진자에서', candidates[0]['stem'])

    def test_each_final_quality_flag_must_be_true(self):
        for field in ('solvable', 'answerSupported', 'difficultyAdequate', 'wordingClear'):
            with self.subTest(field=field):
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], **{field: False})]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)

    def test_multiple_empty_wrong_or_duplicate_correct_option_ids_are_blocked(self):
        for ids in (['A', 'C'], [], ['B'], ['A', 'A']):
            with self.subTest(ids=ids):
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], correctOptionIds=ids)]}
                accepted, audit, _ = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertIn('정답 후보', audit['reviews'][0]['publicationReason'])

    def test_non_mcq_cannot_claim_option_answers(self):
        candidates, assignments = self.candidates(('ox',))
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0], correctOptionIds=['A'])]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(audit['rejected'], 1)

    def test_keep_with_issues_replacement_or_no_reasoning_is_blocked(self):
        changes = [{'issues': ['missing_condition']}, {'replacement': question('mcq')},
                   {'reasoningTask': '   '}, {'decision': 'reject'}]
        for change in changes:
            with self.subTest(change=change):
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], **change)]}
                accepted, audit, provider = self.run_review([reply])
                self.assertEqual(accepted, [])
                self.assertEqual((audit['rejected'], len(provider.calls)), (1, 1))

    def test_replacement_type_concept_source_quote_and_controls_cannot_escape(self):
        candidates, assignments = self.candidates(('mcq',))
        base = revision(candidates[0])
        replacements = []
        wrong_type = question('word'); replacements.append(wrong_type)
        wrong_concept = copy.deepcopy(base); wrong_concept['conceptIds'] = ['c2']; replacements.append(wrong_concept)
        wrong_source = copy.deepcopy(base); wrong_source['evidence'][0]['sourceId'] = 'study:c2:e1'; replacements.append(wrong_source)
        wrong_quote = copy.deepcopy(base); wrong_quote['evidence'][0]['quote'] = '자료에 없는 인용'; replacements.append(wrong_quote)
        broken = copy.deepcopy(base); broken['options'][1]['text'] = '\x08igl(깨진 수식)'; replacements.append(broken)
        for replacement in replacements:
            with self.subTest(replacement=replacement):
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                        issues=['draft_error'], replacement=replacement)]}
                accepted, audit, _ = self.run_review([reply], candidates, assignments)
                self.assertEqual(accepted, [])
                self.assertEqual(audit['rejected'], 1)

    def test_replacement_can_use_linked_original_pdf_text(self):
        candidates, assignments = self.candidates()
        replacement = revision(candidates[0])
        replacement['evidence'] = [{'sourceId': 'pdf:p1', 'quote': '독립 풀이에 필요한 원래 조건이다.'}]
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                issues=['source_conflict'], replacement=replacement)]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['evidence'][0]['sourceKind'], 'native')
        self.assertEqual(accepted[0]['evidence'][0]['page'], 1)
        self.assertEqual(audit['revised'], 1)

    def test_replacement_selects_original_quote_id_without_retyping_math(self):
        native = '원본 첫 줄\n' + r'\(r=\frac{2}{5}(10-x)\)' + '\n원본 마지막 줄'
        self.document['pages'][0]['nativeText'] = native
        candidates, assignments = self.candidates()
        replacement = revision(candidates[0])
        replacement['evidence'] = [{'sourceId': 'pdf:p1', 'quoteId': 'q1'}]
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                issues=['source_correction'], replacement=replacement)]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(audit['revised'], 1)
        self.assertEqual(accepted[0]['evidence'][0]['quote'], native)
        self.assertEqual(accepted[0]['evidence'][0]['sourceKind'], 'native')
        self.assertNotIn('quoteId', accepted[0]['evidence'][0])

    def test_replacement_can_select_cited_summary_quote_id(self):
        candidates, assignments = self.candidates()
        replacement = revision(candidates[0])
        replacement['evidence'] = [{'sourceId': 'study:c1:e1', 'quoteId': 'q1'}]
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                issues=['wording'], replacement=replacement)]}
        accepted, _, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(accepted[0]['evidence'][0]['quote'], '핵심 정의 1')
        self.assertEqual(accepted[0]['evidence'][0]['sourceKind'], 'saved_concept')

    def test_replacement_unknown_quote_id_cannot_be_published(self):
        candidates, assignments = self.candidates()
        for sid in ['study:c1:e1', 'pdf:p1']:
            with self.subTest(sourceId=sid):
                replacement = revision(candidates[0])
                replacement['evidence'] = [{'sourceId': sid, 'quoteId': 'q999'}]
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                        issues=['wording'], replacement=replacement)]}
                accepted, audit, _ = self.run_review([reply], candidates, assignments)
                self.assertEqual(accepted, [])
                self.assertIn('인용 ID', audit['reviews'][0]['publicationReason'])

    def test_quote_id_from_another_reviewed_concepts_page_cannot_escape_assignment(self):
        candidates, assignments = self.candidates()
        others, other_assignments = self.candidates(cid='c2')
        others[0]['id'] = 'other-candidate'
        assignments['other-candidate'] = next(iter(other_assignments.values()))
        candidates.extend(others)
        for sid in ['study:c2:e1', 'pdf:p2']:
            with self.subTest(sourceId=sid):
                replacement = revision(candidates[0])
                replacement['evidence'] = [{'sourceId': sid, 'quoteId': 'q1'}]
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                        issues=['wording'], replacement=replacement), verdict(payload['candidates'][1])]}
                accepted, audit, _ = self.run_review([reply], candidates, assignments)
                self.assertEqual([q['id'] for q in accepted], ['other-candidate'])
                self.assertEqual(audit['rejected'], 1)
                self.assertIn('근거', audit['reviews'][0]['publicationReason'])

    def test_keep_cannot_override_formula_in_word_answer(self):
        candidates, assignments = self.candidates(('word',))
        candidates[0]['stem'] = ('원래 길이가 0.20m인 용수철을 0.24m에서 0.27m까지 늘인다. '
                                 '용수철 상수가 k일 때 필요한 일을 나타내는 정적분을 쓰시오.')
        candidates[0]['answer'] = r'\(\displaystyle W=\int_{0.04}^{0.07}kx\,dx\)'
        def reply(payload):
            row = payload['candidates'][0]
            return {'reviews': [verdict(row, solution=independent_solution(row['question'], candidates[0]['answer']))]}
        accepted, audit, provider = self.run_review([reply], candidates, assignments)
        self.assertEqual(accepted, [])
        self.assertEqual(audit['rejected'], 1)
        self.assertIn('word_answer_is_formula',
            {i['code'] for i in provider.calls[0][0]['candidates'][0]['localIssues']})

    def test_replacement_answer_change_needs_matching_final_correct_option(self):
        candidates, assignments = self.candidates()
        replacement = revision(candidates[0])
        replacement['answer'] = 'B'
        replacement['explanation'] = '수정된 조건에서는 B만 성립한다.'
        for correct_ids, expected_count in [(['A'], 0), (['B'], 1)]:
            with self.subTest(correct_ids=correct_ids):
                def reply(payload):
                    return {'reviews': [verdict(payload['candidates'][0], decision='revise',
                        issues=['answer_error'], correctOptionIds=correct_ids, replacement=replacement)]}
                accepted, _, _ = self.run_review([reply], candidates, assignments)
                self.assertEqual(len(accepted), expected_count)
                if accepted:
                    self.assertEqual(accepted[0]['answer'], 'B')

    def test_revised_duplicate_and_previous_stem_are_blocked(self):
        candidates, assignments = self.candidates(('mcq', 'mcq'))
        replacement = revision(candidates[1]); replacement['stem'] = candidates[0]['stem']
        def reply(payload):
            return {'reviews': [verdict(payload['candidates'][0]), verdict(payload['candidates'][1],
                decision='revise', issues=['wording'], replacement=replacement)]}
        accepted, audit, _ = self.run_review([reply], candidates, assignments)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(audit['rejected'], 1)
        accepted, audit, _ = self.run_review([approve], [candidates[0]], assignments,
                                            previous={quiz._quote_key(candidates[0]['stem'])})
        self.assertEqual(accepted, [])

    def test_missing_duplicate_and_unknown_review_ids_fail_closed(self):
        candidates, assignments = self.candidates(('mcq', 'ox'))
        for mutation in ('missing', 'duplicate', 'unknown'):
            with self.subTest(mutation=mutation):
                def reply(payload):
                    data = approve(payload)
                    if mutation == 'missing': data['reviews'].pop()
                    elif mutation == 'duplicate': data['reviews'][1]['questionId'] = data['reviews'][0]['questionId']
                    else: data['reviews'][1]['questionId'] = 'not-a-candidate'
                    return data
                provider = FakeProvider([reply]); progress = []
                with self.assertRaises(ValueError):
                    review.review_candidates(self.folder, self.document, self.config,
                        candidates, self.concepts, self.sources, provider, assignments, set(),
                        on_progress=lambda *args: progress.append(args))
                self.assertEqual(progress, [])
                self.assertEqual(len(provider.calls), 1)

    def test_provider_failure_does_not_retry_and_clears_context(self):
        candidates, assignments = self.candidates()
        provider = FakeProvider([RuntimeError('simulated provider failure')]); progress = []
        with self.assertRaises(RuntimeError):
            review.review_candidates(self.folder, self.document, self.config,
                candidates, self.concepts, self.sources, provider, assignments, set(),
                on_progress=lambda *args: progress.append(args))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.context, {})
        self.assertEqual(progress, [])

    def test_malformed_review_envelope_never_implies_approval(self):
        candidates, assignments = self.candidates()
        for raw in [None, {}, {'reviews': None}, {'reviews': ['invalid row']}]:
            with self.subTest(raw=raw):
                provider = FakeProvider([raw]); progress = []
                with self.assertRaises(ValueError):
                    review.review_candidates(self.folder, self.document, self.config,
                        candidates, self.concepts, self.sources, provider, assignments, set(),
                        on_progress=lambda *args: progress.append(args))
                self.assertEqual(progress, [])
                self.assertEqual(len(provider.calls), 1)

    def test_progress_preserves_only_completed_review_batches_on_later_failure(self):
        candidates, assignments = self.candidates(('mcq', 'ox'))
        provider = FakeProvider([approve, RuntimeError('second review failed')]); progress = []
        def record(accepted, audit):
            progress.append((copy.deepcopy(accepted), copy.deepcopy(audit)))
        with patch.object(review, 'MAX_REVIEW_QUESTIONS', 1), self.assertRaises(RuntimeError):
            review.review_candidates(self.folder, self.document, self.config,
                candidates, self.concepts, self.sources, provider, assignments, set(), on_progress=record)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(progress), 1)
        self.assertEqual([q['id'] for q in progress[0][0]], [candidates[0]['id']])
        self.assertEqual(progress[0][1]['accepted'], 1)

    def test_source_context_adds_unique_linked_native_pages_without_easy_explanations(self):
        document, request = fixture(2, size=2)
        document['chunks'][1]['page'] = 1
        request['studyContent']['concepts'][1]['entries'][0]['evidence'][0]['page'] = 1
        document['pages'][0]['nativeText'] = '공유된 실제 PDF 페이지의 내용이다.'
        document['pages'][1]['nativeText'] = '출제하지 않은 페이지는 보내지 않는다.'
        _, _, _, concepts, sources = quiz.context(document, request)
        original_concepts, original_sources = copy.deepcopy(concepts), copy.deepcopy(sources)
        selected, material, _ = review._source_context(document,
            [{'conceptIds': ['c1']}, {'conceptIds': ['c2']}], concepts, sources)
        self.assertEqual(list(material).count('pdf:p1'), 1)
        self.assertNotIn('pdf:p2', material)
        self.assertIn('pdf:p1', selected['c1']['sourceIds'])
        self.assertIn('pdf:p1', selected['c2']['sourceIds'])
        wire = json.dumps(material, ensure_ascii=False)
        self.assertEqual(wire.count('공유된 실제 PDF 페이지의 내용이다.'), 1)
        self.assertNotIn('비유는 출제하면 안 돼요', wire)
        self.assertEqual(concepts, original_concepts)
        self.assertEqual(sources, original_sources)

    def test_context_overflow_does_not_truncate_or_spend_on_unreviewable_candidate(self):
        candidates, assignments = self.candidates()
        provider = FakeProvider([]); provider.input_bound_limit = 1
        accepted, audit = review.review_candidates(self.folder, self.document, self.config,
            candidates, self.concepts, self.sources, provider, assignments, set())
        self.assertEqual(accepted, [])
        self.assertEqual(provider.calls, [])
        self.assertEqual(audit['status'], 'partial')
        self.assertEqual(audit['reviews'][0]['issues'], ['context_limit'])

    def test_option_shuffle_preserves_ids_answers_and_explanations_and_balances_positions(self):
        candidates, _ = self.candidates(tuple(['mcq'] * 20 + ['word']))
        before, repeat = copy.deepcopy(candidates), copy.deepcopy(candidates)
        review.shuffle_display_options(candidates, 'stable-run-id')
        review.shuffle_display_options(repeat, 'stable-run-id')
        self.assertEqual(candidates, repeat)
        positions = Counter()
        for old, final in zip(before, candidates):
            self.assertEqual(old['answer'], final['answer'])
            self.assertEqual(old['id'], final['id'])
            self.assertEqual({o['id']: o for o in old['options']}, {o['id']: o for o in final['options']})
            if final['type'] == 'mcq':
                positions[next(i for i, o in enumerate(final['options']) if o['id'] == final['answer'])] += 1
            else:
                self.assertEqual(old, final)
        self.assertEqual(sorted(positions.values()), [5, 5, 5, 5])

    def generate(self, replies, count=1):
        document, request = fixture(count, ['ox'])
        document['pages'][0]['nativeText'] = '검증할 원본 PDF 텍스트이다.'
        plan = planned({'ox': count, 'mcq': 0, 'word': 0, 'essay': 0}, ['c1'])
        generated = {'questions': [question(stem=f'검증할 명제 {i}') for i in range(count)],
                     'unfilled': 0, 'reason': ''}
        provider = FakeProvider([plan, generated, *replies])
        snapshots = []; real_write = quiz.write_json
        def write(path, value):
            if path.name == 'latest.json':
                snapshots.append(copy.deepcopy(value))
            return real_write(path, value)
        with patch.object(quiz, 'emit'), patch.object(quiz, 'write_json', side_effect=write):
            result = quiz.generate(self.folder, document, request, provider)
        return result, provider, snapshots

    def test_real_generate_publishes_immediately_without_review_usage(self):
        def forbidden_review(payload):
            self.fail('Production generation must not call the independent reviewer')
        result, provider, snapshots = self.generate([forbidden_review])
        self.assertEqual(len(result['questions']), 1)
        self.assertEqual(result['quality']['status'], 'disabled')
        self.assertEqual(result['runUsage']['usageBasedUsd'], .02)
        self.assertEqual(result['runUsage']['byKind']['quiz_review']['requests'], 0)
        self.assertEqual([x[0]['task'] for x in provider.calls], ['quiz_plan', 'quiz_questions'])
        self.assertTrue(any(s['questions'] for s in snapshots))
        self.assertTrue(all(not s['candidateQuestions'] for s in snapshots))

    def test_unused_review_failure_does_not_hide_generated_questions(self):
        result, provider, _ = self.generate([RuntimeError('review transport failure')])
        self.assertEqual((len(result['questions']), result['unfilled']), (1, 0))
        self.assertEqual(result['candidateQuestions'], [])
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(result['processingComplete'])

    def test_unused_review_batch_settings_do_not_change_direct_publication(self):
        with patch.object(review, 'MAX_REVIEW_QUESTIONS', 1):
            result, provider, _ = self.generate([approve, RuntimeError('second batch failed')], count=2)
        self.assertEqual((len(result['questions']), len(result['candidateQuestions'])), (2, 0))
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(result['runUsage']['usageBasedUsd'], .02)
        self.assertEqual(result['runUsage']['byKind']['quiz_review']['requests'], 0)
        self.assertEqual(len(provider.calls), 2)

    def test_unused_review_cancellation_does_not_cancel_completed_generation(self):
        result, provider, _ = self.generate([InterruptedError('cancelled')], count=2)
        self.assertEqual(len(result['questions']), 2)
        self.assertFalse(result.get('cancelled', False))
        self.assertEqual(result['unfilled'], 0)
        self.assertEqual(len(provider.calls), 2)


if __name__ == '__main__':
    unittest.main()
