"""No-network admission regressions: real order, not ordered presentation."""
import copy
import unittest

from pdf_step_flow_policy import VERSION, assess_sequence, is_eligible_module, _body_key


def fixture(text='준비 결과를 처리의 입력으로 사용한다. 처리 결과를 확인의 입력으로 전달한다.'):
    source = {'s': {'id': 's', 'text': text, 'kind': 'text', 'hasVisual': False}}
    steps = [{'title': title, 'body': body, 'evidence': [{'sourceId': 's', 'quote': text}]}
        for title, body in [('준비', '재료를 확보한다.'), ('처리', '재료를 변환한다.'),
                            ('확인', '변환된 값을 검사한다.')]]
    item = {'title': '과정', 'orderKind': 'process', 'transitions': [
        {'fromStep': 0, 'toStep': 1, 'relation': '준비 결과를 처리 입력으로 사용한다.',
         'blockIds': ['s'], 'sourceQuote': text},
        {'fromStep': 1, 'toStep': 2, 'relation': '처리 결과를 확인 입력으로 전달한다.',
         'blockIds': ['s'], 'sourceQuote': text}]}
    return item, steps, source


class StepFlowPolicyTests(unittest.TestCase):
    def test_source_grounded_dependency_passes_without_mutation(self):
        args = fixture()
        before = copy.deepcopy(args)
        self.assertEqual(assess_sequence(*args), {'policyVersion': VERSION, 'kind': 'process',
            'sourceGrounded': True, 'transitionCount': 2})
        self.assertEqual(args, before)

    def test_real_two_stage_process_is_plain(self):
        item, steps, source = fixture()
        self.assertIsNone(assess_sequence(item, steps[:2], source))

    def test_number_punctuation_space_and_case_cannot_hide_duplicate_stages(self):
        for key, pair in [('title', ('1. 준비!', '(2) 준 비')),
                          ('title', ('① PREPARE!', 'Step 2: prepare')),
                          ('body', ('1. 재료를 확보한다.', '2) 재료를 확보한다.'))]:
            with self.subTest(key=key, pair=pair):
                item, steps, source = fixture()
                steps[0][key], steps[1][key] = pair
                self.assertIsNone(assess_sequence(item, steps, source))

    def test_distinct_numeric_values_are_not_presentation_prefixes(self):
        item, steps, source = fixture()
        steps[0]['body'], steps[1]['body'] = '1.0 m', '2.0 m'
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_formula_operators_and_code_case_are_distinct_body_content(self):
        item, steps, source = fixture()
        for step, body in zip(steps, ['x+1', 'x-1', 'X-1']):
            step['body'] = body
        self.assertIsNotNone(assess_sequence(item, steps, source))
        self.assertNotEqual(_body_key('*p'), _body_key('p'))
        self.assertNotEqual(_body_key('a==b'), _body_key('a!=b'))
        self.assertNotEqual(_body_key('int *p;'), _body_key('int p;'))

    def test_paired_outer_emphasis_and_presentation_prefix_do_not_hide_duplicates(self):
        item, steps, source = fixture()
        steps[0]['body'], steps[1]['body'] = '1. **같은 본문.**', '2) 같은 본문.'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_final_punctuation_is_not_removed_from_body(self):
        self.assertNotEqual(_body_key('값.'), _body_key('값!'))

    def test_order_kind_self_report_cannot_admit_plain_categories(self):
        for text in ['종류는 준비, 처리, 확인이다.',
                     '첫째 준비, 둘째 처리, 마지막 확인.',
                     '먼저 준비를 설명하고 다음으로 처리와 확인을 소개한다.',
                     '세 특성: 준비는 간단하다. 처리는 빠르다. 확인은 편리하다.',
                     'The three types are preparation, processing and inspection.',
                     'The hierarchy: 준비 → 처리 → 확인.',
                     '분류 체계: 준비 → 처리 → 확인.',
                     '분류: 준비 → 처리 → 확인.',
                     '성숙도: 준비 → 처리 → 확인.',
                     '등급 서열: 준비 → 처리 → 확인.',
                     '준비의 특징은 생성, 처리의 특징은 변환, 확인의 특징은 전달이다.']:
            with self.subTest(text=text):
                item, steps, source = fixture(text)
                self.assertIsNone(assess_sequence(item, steps, source))

    def test_parallel_imperative_principles_are_not_a_process(self):
        text = '출처를 확인하세요. 근거를 구분하세요. 예외를 적으세요.'
        item, steps, source = fixture(text)
        steps[0].update(title='출처 확인', body='출처를 확인하세요.')
        steps[1].update(title='근거 구분', body='근거를 구분하세요.')
        steps[2].update(title='예외 기록', body='예외를 적으세요.')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_nominal_causal_chain_does_not_need_imperative_words(self):
        item, steps, source = fixture('준비 → 처리 → 확인')
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_independent_arrow_mappings_are_not_a_chain(self):
        item, steps, source = fixture('준비 → 재료\n처리 → 변환\n확인 → 검사')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_bare_chronological_dates_are_not_a_process(self):
        item, steps, source = fixture('준비: 1900년\n처리: 1910년\n확인: 1920년')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_real_procedure_and_english_dependency_are_admitted(self):
        self.assertIsNotNone(assess_sequence(*fixture(
            '준비를 완료한 후 처리한다. 처리 결과를 확인에 사용한다.')))
        item, steps, source = fixture('The output of preparation is used as the input of processing; '
            'the processing result is passed to inspection.')
        for step, title in zip(steps, ['preparation', 'processing', 'inspection']):
            step['title'] = title
        item['transitions'][0]['relation'] = 'The output of preparation is input to processing.'
        item['transitions'][1]['relation'] = 'The result of processing is passed to inspection.'
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_formula_implication_is_not_required_to_contain_prose(self):
        item, steps, source = fixture(r'x=1 \Rightarrow y=2 \Rightarrow z=3')
        item['orderKind'] = 'derivation'
        for step, title, body in zip(steps, ['초깃값', '중간값', '최종값'],
                                    ['x=1', 'y=2', 'z=3']):
            step.update(title=title, body=body)
        item['transitions'][0]['relation'] = 'x=1에 값을 대입하여 y=2를 도출한다.'
        item['transitions'][1]['relation'] = 'y=2에 값을 대입하여 z=3을 도출한다.'
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_relation_adverbs_cannot_replace_actual_endpoint_content(self):
        item, steps, source = fixture()
        item['transitions'][0]['relation'] = '이전 단계의 결과가 다음 단계의 입력으로 사용된다.'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_unrelated_causal_verb_elsewhere_in_large_quote_is_insufficient(self):
        item, steps, source = fixture('준비 결과를 처리의 입력으로 사용한다. '
            '확인은 독립 특징이다. 다른 값은 변환될 수 있다.')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_state_change_relation_names_both_endpoints(self):
        self.assertIsNotNone(assess_sequence(*fixture(
            '준비에서 처리로 전환한다. 처리의 출력은 확인의 입력으로 사용된다.')))

    def test_short_exact_quote_may_use_only_its_own_source_sentence(self):
        text = '준비 결과인 재료를 처리의 입력으로 사용한다. 처리 결과를 확인의 입력으로 전달한다.'
        item, steps, source = fixture(text)
        item['transitions'][0]['sourceQuote'] = '재료를 처리의 입력으로 사용한다.'
        self.assertIsNotNone(assess_sequence(item, steps, source))
        # The producer is in a different sentence: it must not be borrowed.
        source['s']['text'] = ('준비 결과인 재료이다. 재료를 처리의 입력으로 사용한다. '
                               '처리 결과를 확인의 입력으로 전달한다.')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_repeated_short_quote_requires_every_occurrence_to_support_same_edge(self):
        good = '준비 결과인 재료를 처리의 입력으로 사용한다. '
        item, steps, source = fixture(good+good+'처리 결과를 확인의 입력으로 전달한다.')
        item['transitions'][0]['sourceQuote'] = '재료를 처리의 입력으로 사용한다.'
        self.assertIsNotNone(assess_sequence(item, steps, source))
        source['s']['text'] = (good+'유형 설명에서는 재료를 처리의 입력으로 사용한다. '
                               '처리 결과를 확인의 입력으로 전달한다.')
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_generation_probe_manufacturing_has_consumed_output_and_partial_stage_label(self):
        text = ('성형 공정: 가열로 원료를 액상으로 변환한다. 가열 결과인 액상 원료를 주형에 주입한다. '
                '주입 결과를 냉각하면 주형의 모양을 가진 고체 제품으로 변환된다.')
        item, steps, source = fixture(text)
        for step, title, body in zip(steps, ['가열', '주형에 주입', '냉각'],
                ['원료를 액상으로 변환해요.', '가열로 얻은 액상 원료를 주형에 넣어요.',
                 '주입된 원료를 냉각해 주형 모양의 고체 제품으로 만들어요.']):
            step.update(title=title, body=body)
        item['transitions'][0].update(relation='가열로 만들어진 액상 원료가 다음 단계에서 주형에 주입돼요.',
            sourceQuote='가열 결과인 액상 원료를 주형에 주입한다.')
        item['transitions'][1].update(relation='주형에 주입된 원료를 냉각하면 주형 모양의 고체 제품이 돼요.',
            sourceQuote='주입 결과를 냉각하면 주형의 모양을 가진 고체 제품으로 변환된다.')
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_generation_probe_data_short_quote_preserves_producer_in_same_sentence(self):
        item, steps, source = fixture('수집 결과인 원자료를 정제의 입력으로 사용한다. '
            '정제를 완료한 후 정제 결과를 집계 입력으로 전달한다.')
        for step, title, body in zip(steps, ['수집', '정제', '집계'],
                ['처리할 원자료를 모아요.', '수집한 원자료를 정제해 다음 단계에 넘길 결과를 만들어요.',
                 '정제 결과를 입력으로 받아 집계해요.']):
            step.update(title=title, body=body)
        item['transitions'][0].update(relation='수집한 원자료가 정제의 입력으로 사용돼요.',
            sourceQuote='원자료를 정제의 입력으로 사용한다.')
        item['transitions'][1].update(relation='정제 결과가 집계의 입력으로 전달돼요.',
            sourceQuote='정제 결과를 집계 입력으로 전달한다.')
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_generation_probe_feedback_retains_actual_state_transition_context(self):
        text = ('측정에서 얻은 현재 상태를 오차 계산의 입력으로 사용한다. '
                '오차 계산의 결과를 조절 입력으로 전달한다. '
                '조절로 인해 실제 상태가 바뀌고, 조절 후 상태를 다시 측정한다.')
        item, steps, source = fixture(text)
        steps.append({'title':'조절 후 상태 재측정',
            'body':'조절로 바뀐 상태를 다시 측정해 다음 오차 계산에 연결해요.',
            'evidence':[{'sourceId':'s'}]})
        for step, title, body in zip(steps, ['현재 상태 측정', '오차 계산', '조절'],
                ['현재 상태를 측정해 오차 계산에 사용할 값을 얻어요.',
                 '측정한 현재 상태를 입력으로 사용해 오차를 계산해요.',
                 '오차 계산 결과를 조절 입력으로 사용해 실제 상태를 바꿔요.']):
            step.update(title=title, body=body)
        item['orderKind'] = 'cycle'
        item['transitions'] = [
            {'fromStep':0,'toStep':1,'relation':'측정한 현재 상태가 오차 계산의 입력이 돼요.',
             'blockIds':['s'],'sourceQuote':'현재 상태를 오차 계산의 입력으로 사용한다.'},
            {'fromStep':1,'toStep':2,'relation':'오차 계산 결과가 조절 입력으로 전달돼요.',
             'blockIds':['s'],'sourceQuote':'오차 계산의 결과를 조절 입력으로 전달한다.'},
            {'fromStep':2,'toStep':3,'relation':'조절이 실제 상태를 바꾸고, 바뀐 상태를 다시 측정해 다음 순환에 연결해요.',
             'blockIds':['s'],'sourceQuote':'조절 후 상태를 다시 측정한다.'}]
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_inequalities_and_three_independent_equations_are_not_transitions(self):
        for text in ['준비 > 처리 > 확인', 'x=1; y=2; z=3']:
            with self.subTest(text=text):
                self.assertIsNone(assess_sequence(*fixture(text)))

    def test_literal_quote_required_not_model_claim(self):
        item, steps, source = fixture('준비, 처리, 확인의 세 유형이 있다.')
        for edge in item['transitions']:
            edge['sourceQuote'] = '준비 결과를 처리의 입력으로 사용한다.'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_case_changed_quote_is_not_literal(self):
        item, steps, source = fixture('A causes B. B causes C.')
        item['transitions'][0]['sourceQuote'] = 'a causes B.'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_relation_must_be_nonempty_even_with_native_proof(self):
        item, steps, source = fixture()
        item['transitions'][0]['relation'] = ''
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_exact_pair_set_not_count_alone(self):
        mutations = [lambda e: e.update(fromStep=True), lambda e: e.update(fromStep=-1),
            lambda e: e.update(toStep=3), lambda e: e.update(fromStep=1, toStep=1),
            lambda e: e.update(fromStep=1, toStep=0),
            lambda e: e.update(fromStep=0, toStep=1)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                item, steps, source = fixture()
                mutate(item['transitions'][1])
                self.assertIsNone(assess_sequence(item, steps, source))

    def test_transition_order_in_json_can_differ_but_pairs_must_be_exact(self):
        item, steps, source = fixture()
        item['transitions'].reverse()
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_unknown_or_outside_scope_ids_are_not_accepted(self):
        for ids in [['unknown'], ['s', 'unknown'], [True], [[]], []]:
            with self.subTest(ids=ids):
                item, steps, source = fixture()
                item['transitions'][0]['blockIds'] = ids
                self.assertIsNone(assess_sequence(item, steps, source))

    def test_each_edge_source_must_touch_both_step_owners(self):
        item, steps, source = fixture()
        source['other'] = {'id': 'other', 'text': source['s']['text']}
        steps[1]['evidence'] = [{'sourceId': 'other'}]
        self.assertIsNone(assess_sequence(item, steps, source))
        for edge in item['transitions']:
            edge['blockIds'].append('other')
        self.assertIsNotNone(assess_sequence(item, steps, source))

    def test_visual_observation_is_explicitly_marked_and_not_literal_proof(self):
        item, steps, source = fixture('')
        source['s'].update(kind='visual', hasVisual=True)
        for edge in item['transitions']:
            edge['sourceQuote'] = ''
        stamp = assess_sequence(item, steps, source)
        self.assertIsNotNone(stamp)
        self.assertTrue(stamp['inferredFromVisual'])

    def test_visual_metadata_alone_cannot_admit_empty_or_generic_relation(self):
        for relation in ['', '다음으로 진행한다.', '첫 단계가 다음 단계보다 먼저여야 한다.',
                         '순서가 중요한 세 단계이다.']:
            with self.subTest(relation=relation):
                item, steps, source = fixture('')
                source['s'].update(kind='visual', hasVisual=True)
                for edge in item['transitions']:
                    edge.update(sourceQuote='', relation=relation)
                self.assertIsNone(assess_sequence(item, steps, source))

    def test_empty_native_quote_does_not_become_visual_evidence(self):
        item, steps, source = fixture('')
        self.assertIsNone(assess_sequence(item, steps, source))
        source['s']['kind'] = 'page'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_nonnative_quote_is_not_allowed_just_because_a_visual_exists(self):
        item, steps, source = fixture('')
        source['s'].update(kind='visual', hasVisual=True)
        for edge in item['transitions']:
            edge['sourceQuote'] = '그림에 존재한다고 주장하는 문장'
        self.assertIsNone(assess_sequence(item, steps, source))

    def test_display_guard_requires_current_stamp_not_old_cached_module(self):
        item, steps, source = fixture()
        module = {'moduleId': 'synesis.step-flow', 'schemaVersion': 1, 'steps': steps,
                  'eligibility': assess_sequence(item, steps, source)}
        self.assertTrue(is_eligible_module(module))
        for field, value in [('policyVersion', 'old'), ('kind', 'list'),
                             ('sourceGrounded', 1), ('transitionCount', True),
                             ('transitionCount', 1)]:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(module)
                changed['eligibility'][field] = value
                self.assertFalse(is_eligible_module(changed))
        del module['eligibility']
        self.assertFalse(is_eligible_module(module))

    def test_guard_rechecks_minimum_and_normalized_duplicates(self):
        item, steps, source = fixture()
        module = {'moduleId': 'synesis.step-flow', 'schemaVersion': 1, 'steps': steps,
                  'eligibility': assess_sequence(item, steps, source)}
        for field in ['title', 'body']:
            changed = copy.deepcopy(module)
            changed['steps'][1][field] = '2. '+changed['steps'][0][field]
            self.assertFalse(is_eligible_module(changed))
        module['steps'] = module['steps'][:2]
        module['eligibility']['transitionCount'] = 1
        self.assertFalse(is_eligible_module(module))

    def test_guard_does_not_reinterpret_source_or_change_math_code(self):
        item, steps, source = fixture()
        steps[0]['body'] += '\n```python\nx = f(y)\n```\n$z > 0$'
        module = {'moduleId': 'synesis.step-flow', 'schemaVersion': 1, 'steps': steps,
                  'eligibility': assess_sequence(item, steps, source)}
        before = copy.deepcopy(module)
        self.assertTrue(is_eligible_module(module))
        self.assertEqual(module, before)

    def test_malformed_raw_values_are_plain_not_exceptions(self):
        item, steps, source = fixture()
        for value in [None, [], '', {'orderKind': []}, {'orderKind': {}}]:
            with self.subTest(value=value):
                self.assertIsNone(assess_sequence(value, steps, source))
        for value in [None, [], '', {'eligibility': []}]:
            self.assertFalse(is_eligible_module(value))


if __name__ == '__main__':
    unittest.main()
