"""Offline slot ownership, shared parallel context, type balance and publication."""
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_quiz as quiz
from pdf_quiz_sources import wire_generation_payload
from pdf_quiz_targets import balanced_counts, target_index, wire_assignment
from pdf_quiz_transport import pack_generation_jobs, validate_job
from test_pdf_quiz import fixture, question
from test_pdf_quiz_parallel import ConcurrentProvider


def target_plan(count, kinds=('ox',), *, units=1):
    rows = []
    for unit in range(units):
        slots = [{'type': kinds[i % len(kinds)], 'conceptIds': [f'c{unit+1}'],
                  'goal': f'고유목표[{i}]: 적용 조건과 판단 결과를 구별한다.'}
                 for i in range(unit, count, units)]
        if slots:
            rows.append({'unitId': f'u{unit+1}', 'conceptIds': [f'c{unit+1}'], 'targets': slots})
    return {'allocations': rows, 'unallocated': 0, 'reason': '', 'customTypeRatio': False}


def slot_answers(payload):
    targets = {t[0]: t for t in payload['sharedTargets']}
    assignment = payload['assignment']
    questions = []
    tasks = assignment.get('tasks')
    if tasks is None:
        tasks = [dict(targetId=tid, unitId=unit['unitId'], type=targets[tid][1],
                      conceptIds=targets[tid][2], goal=targets[tid][3])
                 for unit in assignment.get('units', [assignment]) for tid in unit['targetIds']]
    for task in tasks:
        tid, kind, ids, goal = task['targetId'], task['type'], task['conceptIds'], task['goal']
        q = question(kind, ids[0], stem=json.dumps(goal, ensure_ascii=False) if isinstance(goal, (list, dict)) else goal)
        q.update(unitId=task['unitId'], targetId=tid)
        if kind == 'mcq':
            options = q.pop('options')
            q['answer'] = options[0]['text']
            q['distractors'] = [{k: v for k, v in o.items() if k != 'id'} for o in options[1:]]
        quotes = next(s['quotes'] for s in payload['sources'] if s['sourceId'] == q['evidence'][0]['sourceId'])
        q['evidence'] = [{'sourceId': q['evidence'][0]['sourceId'], 'quoteId': quotes[0]['quoteId']}]
        questions.append(q)
    return {'questions': questions, 'unfilled': 0, 'reason': ''}


class QuestionTargetTests(unittest.TestCase):
    def run_plan(self, count, allowed, plan, *, answer=slot_answers, instructions='', no_pack=False, difficulty='중', theme='understanding'):
        doc, req = fixture(count, allowed, size=max(2, len(plan['allocations'])))
        req['quiz'].update(instructions=instructions, difficulty=difficulty, theme=theme)
        provider = ConcurrentProvider(plan, answer)
        with tempfile.TemporaryDirectory() as directory, patch.object(quiz, 'emit'), \
                patch('socket.socket.connect', side_effect=AssertionError('no network allowed')):
            if no_pack:
                with patch.object(quiz, 'pack_generation_jobs', side_effect=lambda rows, *args: rows):
                    result = quiz.generate(Path(directory), doc, req, provider)
            else:
                result = quiz.generate(Path(directory), doc, req, provider)
        self.assertFalse(result['errors'], result['errors'])
        self.assertEqual(result['refillRounds'], 0)
        self.assertFalse(any(p.get('completion') or p['task'] == 'quiz_review' for p, _, _ in provider.calls))
        return result, provider

    def test_balance_all_sizes_subsets_and_themes(self):
        for allowed in (list(quiz.TYPES), ['word','essay'], ['mcq']):
            for count in (1, 2, 3, 4, 5, 10, 17, 120):
                for theme in quiz.THEMES:
                    actual = balanced_counts(count, allowed, theme)
                    self.assertEqual(sum(actual.values()), count)
                    values = [actual[t] for t in allowed]
                    self.assertLessEqual(max(values)-min(values), 1)
                    self.assertTrue(all(actual[t] == 0 for t in quiz.TYPES if t not in allowed))

    def test_generic_instructions_do_not_retype_goals(self):
        result, _ = self.run_plan(10, list(quiz.TYPES), target_plan(10, ['mcq']), instructions='해설은 짧게 써 주세요.')
        self.assertEqual(Counter(q['type'] for q in result['questions']), {'mcq':3})
        self.assertEqual(result['plan']['unallocated'],7)
        self.assertEqual(len(result['plan']['targetSelection']['excludedTargets']),7)

    def test_saved_six_goal_finance_plan_preserves_types_and_both_advanced(self):
        raw=json.loads((Path(__file__).parent/'testdata/quiz_roles_finance_plan.json').read_text())
        original=copy.deepcopy(raw)
        catalog=[{'id':f'c{i}'} for i in range(1,17)]
        config={'totalCount':5,'allowedTypes':list(quiz.TYPES),'theme':'understanding','instructions':''}
        plan=quiz.validate_plan(raw,catalog,config)
        chosen=[t for u in plan['allocations'] for t in u['targets']]
        self.assertEqual(raw,original)
        self.assertEqual(len(chosen),5)
        self.assertEqual(Counter(t['profile'] for t in chosen),{'general':3,'advanced':2})
        self.assertEqual(Counter(t['type'] for t in chosen),{'mcq':2,'ox':1,'word':1,'essay':1})
        self.assertTrue(any(t['conceptIds']==['c16'] and t['type']=='essay' for t in chosen))
        self.assertTrue(any(t['conceptIds']==['c13'] and t['type']=='mcq' for t in chosen))
        originals=[t for u in raw['allocations'] for t in u['targets']]
        for t in chosen:
            self.assertIn({k:v for k,v in t.items() if k!='id'},originals)
        self.assertEqual(len(plan['targetSelection']['excludedTargets']),1)

    def test_concept_basic_policy_survives_plan_selection_and_generation(self):
        from pdf_quiz_profiles import policy, apply_profile_plan
        raw=target_plan(5,['ox','mcq','word','essay','mcq'])
        for unit in raw['allocations']:
            for target in unit['targets']:
                target.update(profile='general',additionalJudgment='',profileEvidenceSourceIds=[])
        original=copy.deepcopy(raw)
        doc,req=fixture(5,list(quiz.TYPES));req['quiz']['theme']='concept_completion'
        config,outline,catalog,concepts,sources=quiz.context(doc,req)
        plan=apply_profile_plan(quiz.validate_plan(raw,catalog,config),{'sources':list(sources.values())},config,concepts)
        self.assertEqual(plan['profileAllocation']['targetCounts'],{'general':5,'advanced':0})
        self.assertEqual(plan['profileAllocation']['advancedShortfall'],0)
        self.assertEqual(plan['unallocated'],0)
        self.assertEqual(sum(len(u['targets']) for u in plan['allocations']),5)
        payload=quiz.generation_payload(config,outline,plan,plan['allocations'][0],concepts,sources,[],'offline')
        self.assertEqual(payload['request']['theme'],'concept_completion')
        self.assertTrue(all(t['profile']=='general' for t in payload['assignment']['tasks']))
        self.assertEqual(raw,original)
        result,provider=self.run_plan(5,list(quiz.TYPES),raw,theme='concept_completion')
        self.assertEqual(provider.calls[0][0]['profilePolicy']['targetCounts'],{'general':5,'advanced':0})
        self.assertEqual(len(result['questions']),5)
        self.assertEqual(result['plan']['profileAllocation']['advancedShortfall'],0)
        for payload,options,context in provider.calls[1:]:
            self.assertTrue(all(t['profile']=='general' for t in payload['assignment']['tasks']))
            self.assertIn('짧은 회상과 직접 구별도 충분한 수행', options['system_prompt'])
        for mode in ('understanding','practice_set','recall'):
            self.assertEqual(policy(5,mode)['targetCounts'],{'general':3,'advanced':2})

    def test_explicit_ratio_overrides_default_balancing(self):
        plan = target_plan(4, ['mcq','mcq','mcq','essay'])
        plan['customTypeRatio'] = True
        result, _ = self.run_plan(4, ['mcq','essay'], plan, instructions='4지선다 3개, 서술형 1개를 내 주세요.')
        self.assertEqual(Counter(q['type'] for q in result['questions']), {'mcq':3, 'essay':1})

    def test_parallel_jobs_own_disjoint_slots_and_share_all_other_goals_once(self):
        raw = target_plan(12, ['ox'], units=12)
        original = copy.deepcopy(raw)
        result, provider = self.run_plan(12, ['ox'], raw, no_pack=True)
        self.assertEqual(raw, original)
        self.assertEqual(len(provider.calls), 13)
        payloads = [p for p, _, _ in provider.calls[1:]]
        sent = [task['targetId'] for p in payloads for task in p['assignment']['tasks']]
        self.assertEqual(len(sent), len(set(sent)))
        self.assertEqual(set(sent), {q['targetId'] for q in result['questions']})
        for p in payloads:
            own = {t['targetId'] for t in p['assignment']['tasks']}
            others = {row[0] for row in p['sharedTargets']}
            self.assertFalse(own & others)
            self.assertEqual(own | others, set(sent))
            serialized = json.dumps(p, ensure_ascii=False)
            self.assertNotIn('plan', p)
            self.assertNotIn('targets', p['assignment'])
            self.assertNotIn('totalCount', p['request'])
            self.assertEqual(serialized.count('고유목표[0]:'), 1)
        self.assertLessEqual(provider.peak_active, 10)

    def test_output_splitting_preserves_every_goal_once(self):
        result, provider = self.run_plan(40, list(quiz.TYPES), target_plan(40, list(quiz.TYPES)))
        self.assertEqual(len(provider.calls), 1 + (40 + quiz.MAX_BATCH_QUESTIONS - 1) // quiz.MAX_BATCH_QUESTIONS)
        self.assertEqual(len(result['questions']), 40)
        self.assertEqual(len({q['targetId'] for q in result['questions']}), 40)
        self.assertEqual(Counter(q['type'] for q in result['questions']), dict.fromkeys(quiz.TYPES, 10))
        self.assertTrue(all(p['assignment']['questionCount'] <= quiz.MAX_BATCH_QUESTIONS
                            for p, _, _ in provider.calls[1:]))

    def test_context_split_preserves_integrative_goal_scope(self):
        doc, req = fixture(2, ['ox'])
        for c in req['studyContent']['concepts']:
            c['entries'][0]['explanation'] = '구체적인 적용 조건의 설명이다. ' * 400
        config, outline, catalog, concepts, sources = quiz.context(doc, req)
        plan = quiz.validate_plan(target_plan(2, ['ox'], units=2), catalog, config)
        first, second = plan['allocations']
        merged = {**first, 'conceptIds': ['c1','c2'], 'targets': first['targets']+second['targets'],
                  'counts': {'ox':2,'mcq':0,'word':0,'essay':0}}
        def payload(a):
            return wire_generation_payload(quiz.generation_payload(config, outline, plan, a, concepts, sources, [], 'fixed'))[0]
        schema = quiz._schema('questions')
        limit = quiz.input_bound(payload(merged), '', schema)-1
        children = list(quiz.fitting_batches(merged, payload, '', schema, limit))
        self.assertEqual([a['conceptIds'] for a in children], [['c1'],['c2']])
        self.assertEqual([s['id'] for a in children for s in a['targets']], [s[0] for s in target_index(plan)])
        # One integrative target must never have one of its required concepts removed.
        merged['targets'] = [{**first['targets'][0], 'conceptIds':['c1','c2']}]
        merged['counts']['ox'] = 1
        with self.assertRaises(ValueError):
            list(quiz.fitting_batches(merged, payload, '', schema, quiz.input_bound(payload(merged), '', schema)-1))

    def test_short_plan_does_not_invent_objectives_or_retry(self):
        result, provider = self.run_plan(5, ['ox'], target_plan(2))
        self.assertEqual((len(result['questions']), result['unfilled'], len(provider.calls)), (2,3,2))
        self.assertEqual(result['completionStatus'], 'partial')

    def test_missing_response_does_not_retry_and_duplicate_stems_are_kept(self):
        def answer(payload):
            raw = slot_answers(payload)
            raw['questions'] = raw['questions'][:2]
            for q in raw['questions']:
                q['stem'] = '같은 지문'
            return raw
        result, provider = self.run_plan(4, ['ox'], target_plan(4), answer=answer)
        self.assertEqual((len(result['questions']), result['unfilled'], len(provider.calls)), (2,2,2))
        self.assertEqual(len({q['id'] for q in result['questions']}), 2)
        self.assertEqual(len({q['stem'] for q in result['questions']}), 1)

    def test_high_short_answers_can_be_inferred_numbers_or_relations_without_grading(self):
        for answer in ('-4 m/s', 'v₂ = −v₁/2', '증가'):
            def reply(payload):
                raw = slot_answers(payload)
                raw['questions'][0]['answer'] = answer
                return raw
            result, provider = self.run_plan(1, ['word'], target_plan(1, ['word']), answer=reply, difficulty='상')
            self.assertEqual(result['questions'][0]['answer'], answer)
            self.assertNotIn('correct', result['questions'][0])
            self.assertEqual(len(provider.calls), 2)

    def test_all_difficulties_use_role_efforts_and_unchanged_output_ceiling(self):
        for level in ('중', '중상', '상', '최상'):
            result, provider = self.run_plan(2, ['word'], target_plan(2, ['word']), difficulty=level)
            self.assertEqual(len(result['questions']), 2)
            for _, options, context in provider.calls:
                self.assertEqual(context['reasoningEffort'], 'high' if context['kind']=='quiz_plan' else 'low')
                self.assertEqual(options['max_output'], 128000)
            self.assertEqual(len(provider.calls), 2)

    def test_book_profiles_replace_legacy_difficulty_without_extra_calls(self):
        plan = target_plan(1, ['word'])
        plan['allocations'][0]['targets'][0]['goal'] = '계의 경계 변경 → 외력 재분류 → 보존되는 성분 판정'
        result, provider = self.run_plan(1, ['word'], plan, difficulty='상')
        difficulty = quiz.difficulty_instruction('상', ['word'], 'understanding')
        self.assertTrue(provider.calls[0][1]['system_prompt'].startswith(
                         (quiz.PROMPTS / 'planner.md').read_text().strip()))
        self.assertEqual(provider.calls[0][1]['system_prompt'].count(difficulty), 0)
        self.assertIn('profilePolicy',provider.calls[0][0])
        self.assertIn('planningEvidence',provider.calls[0][0])
        for level in ('중', '중상', '최상'):
            self.assertNotIn(quiz.difficulty_instruction(level, ['word'], 'understanding'),
                             provider.calls[0][1]['system_prompt'])
        self.assertEqual(provider.calls[1][1]['system_prompt'].count(difficulty), 0)
        self.assertEqual(provider.calls[1][0]['assignment']['tasks'][0]['goal'], plan['allocations'][0]['targets'][0]['goal'])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result['refillRounds'], 0)

    def test_structured_goal_survives_parallel_scope_and_wire_compaction(self):
        plan = target_plan(2, ['word'], units=2)
        goals = []
        for index, unit in enumerate(plan['allocations']):
            goal = {'given': f'관측 조건 {index}', 'derive': f'숨은 상태 {index}',
                    'ask': f'그 상태가 결정하는 후속 결과 {index}'}
            unit['targets'][0]['goal'] = goal
            goals.append(goal)
        result, provider = self.run_plan(2, ['word'], plan, difficulty='상', no_pack=True)
        self.assertEqual(len(provider.calls), 3)
        for payload, _, _ in provider.calls[1:]:
            indexed = {row[0]: row[3] for row in payload['sharedTargets']}
            indexed.update({task['targetId']: task['goal'] for task in payload['assignment']['tasks']})
            self.assertEqual([indexed[tid] for tid in sorted(indexed)],
                             [[g[k] for k in ('given', 'derive', 'ask')] for g in goals])
        self.assertEqual([u['targets'][0]['goal'] for u in result['plan']['allocations']], goals)
        self.assertEqual(len(result['questions']), 2)

    def test_slot_scope_can_add_catalog_concept_missing_from_parent_summary(self):
        plan = target_plan(1, ['word'])
        plan['allocations'][0]['targets'][0]['conceptIds'] = ['c1', 'c2']
        result, provider = self.run_plan(1, ['word'], plan)
        self.assertEqual(result['plan']['allocations'][0]['conceptIds'], ['c1', 'c2'])
        self.assertEqual(provider.calls[1][0]['assignment']['tasks'][0]['conceptIds'], ['c1', 'c2'])
        self.assertEqual(len(provider.calls), 2)

    def test_judgment_and_confusion_survive_plan_and_generation_inputs(self):
        from pdf_quiz_targets import valid_goal, target_index
        plan=target_plan(2,['ox'],units=2)
        for i,u in enumerate(plan['allocations']):
            u['targets'][0]['goal']={'judgment':f'구별 기준 {i}','confusion':f'잘못된 적용 {i}'}
        result,provider=self.run_plan(2,['ox'],plan,no_pack=True)
        expected=[u['targets'][0]['goal'] for u in plan['allocations']]
        actual=[t['goal'] for payload,_,_ in provider.calls[1:] for t in payload['assignment']['tasks']]
        self.assertCountEqual(actual,expected)
        for payload,_,_ in provider.calls[1:]:
            self.assertTrue(all(isinstance(row[3],dict) for row in payload['sharedTargets']))
        self.assertTrue(valid_goal({'judgment':'정확한 사실 회상','confusion':''}))
        self.assertFalse(valid_goal({'judgment':'','confusion':'오류'}))
        self.assertEqual(len(provider.calls),3) # Existing plan + two generation jobs, no new stage.

    def test_given_boundary_survives_split_shared_goals_and_saved_target(self):
        from pdf_quiz_targets import valid_goal
        plan = target_plan(2, ['word'], units=2)
        goals = []
        for i, unit in enumerate(plan['allocations']):
            goal = {'given': f'학생에게 제공할 관측 자료 {i}',
                    'judgment': f'학생이 판정할 관계 {i}', 'confusion': ''}
            unit['targets'][0]['goal'] = goal
            goals.append(goal)
        original = copy.deepcopy(plan)
        result, provider = self.run_plan(2, ['word'], plan, no_pack=True)
        self.assertEqual(plan, original)
        for payload, _, context in provider.calls[1:]:
            sent = [t['goal'] for t in payload['assignment']['tasks']]
            sent += [t[3] for t in payload['sharedTargets']]
            self.assertCountEqual(sent, goals)
            self.assertEqual(context['reasoningEffort'], 'high' if context['kind']=='quiz_plan' else 'low')
            # All text survives once, not duplicated as an additional prompt.
            serialized = json.dumps(payload, ensure_ascii=False)
            for goal in goals:
                self.assertEqual(serialized.count(goal['given']), 1)
        self.assertCountEqual([q['targetGoal'] for q in result['questions']], goals)
        self.assertEqual(len(provider.calls), 3)
        self.assertTrue(valid_goal({'given': '', 'judgment': '핵심 사실 회상', 'confusion': ''}))
        self.assertFalse(valid_goal({'given': [], 'judgment': '관계', 'confusion': ''}))
        # Contract validity is not a semantic leakage test; keep the response.
        self.assertTrue(valid_goal({'given': 'A', 'judgment': 'A', 'confusion': ''}))

    def test_goal_contract_accepts_direct_recall_without_inventing_steps(self):
        from pdf_quiz_targets import valid_goal
        self.assertTrue(valid_goal({'given': '정의', 'derive': '', 'ask': '용어'}))
        self.assertFalse(valid_goal({'given': '정의', 'ask': '용어'}))
        self.assertFalse(valid_goal({'given': '정의', 'derive': [], 'ask': '용어'}))
        self.assertFalse(valid_goal({'given': '', 'derive': '', 'ask': '용어'}))
        # This is not a semantic quality gate: nonsense is not silently deleted.
        self.assertTrue(valid_goal({'given': 'A', 'derive': 'A', 'ask': 'A'}))

    def test_schema_emits_goal_once_without_planner_id_counts_or_focus(self):
        item = quiz._schema('planner')['json_schema']['schema']['properties']['allocations']['items']
        self.assertEqual(set(item['properties']), {'unitId','conceptIds','targets'})
        self.assertEqual(set(item['properties']['targets']['items']['properties']), {'type','conceptIds','goal','profile','additionalJudgment','profileEvidenceSourceIds'})
        goal = item['properties']['targets']['items']['properties']['goal']
        self.assertEqual(goal['type'], 'object')
        self.assertEqual(set(goal['properties']), {'given','judgment','confusion'})
        question_schema = quiz._schema('questions')['json_schema']['schema']['properties']['questions']['items']
        self.assertIn('targetId', question_schema['required'])
        self.assertNotIn('options', question_schema['properties'])


class FlatAssignmentTests(unittest.TestCase):
    def setUp(self):
        document, request = fixture(6, list(quiz.TYPES), size=3)
        self.config, self.outline, catalog, self.concepts, self.sources = quiz.context(document, request)
        self.plan = quiz.validate_plan(target_plan(6, ['ox','mcq','word','essay','mcq','word'], units=3), catalog, self.config)

    def payload(self, assignment):
        return quiz.generation_payload(self.config, self.outline, self.plan, assignment,
                                       self.concepts, self.sources, [], 'flat-test')

    def job(self):
        return pack_generation_jobs(self.plan['allocations'][:2], self.payload, '',
                                    quiz._schema('questions'), 240000)[0]

    def test_two_packed_units_become_explicit_tasks_without_changing_plan_or_job(self):
        job = self.job()
        before_plan, before_job = copy.deepcopy(self.plan), copy.deepcopy(job)
        assignment = self.payload(job)['assignment']
        self.assertEqual(set(assignment), {'unitId', 'questionCount', 'tasks'})
        self.assertEqual(assignment['unitId'], job['unitId'])
        self.assertEqual(assignment['questionCount'], 4)
        self.assertEqual([(t['unitId'], t['targetId']) for t in assignment['tasks']],
                         [(unit['unitId'], slot['id']) for unit in job['units'] for slot in unit['targets']])
        for task in assignment['tasks']:
            self.assertEqual(set(task), {'targetId', 'unitId', 'type', 'conceptIds', 'goal'})
        assignment['tasks'][0]['conceptIds'].append('outside')
        self.assertEqual(self.plan, before_plan)
        self.assertEqual(job, before_job)

    def test_own_and_other_goals_cover_the_entire_plan_once(self):
        for assignment in [self.job(), *self.plan['allocations']]:
            with self.subTest(unit=assignment['unitId']):
                payload = self.payload(assignment)
                own = {task['targetId'] for task in payload['assignment']['tasks']}
                others = {row[0] for row in payload['sharedTargets']}
                self.assertFalse(own & others)
                self.assertEqual(own | others, {row[0] for row in target_index(self.plan)})
                serialized = json.dumps(payload, ensure_ascii=False)
                for row in target_index(self.plan):
                    self.assertEqual(serialized.count(row[3]), 1)

    def test_flat_tasks_keep_logical_scope_and_cross_unit_question_is_only_warned(self):
        job = self.job()
        payload = self.payload(job)
        task = payload['assignment']['tasks'][0]
        self.assertEqual(task['conceptIds'], ['c1'])
        self.assertEqual({c['id'] for c in payload['concepts']}, {'c1', 'c2'})
        wrong = question('ox', 'c2', '다른 배정의 개념과 출처를 사용한 문항')
        wrong.update(unitId=task['unitId'], targetId=task['targetId'])
        with self.assertRaisesRegex(ValueError, '개념 범위'):
            quiz._question(wrong, job['units'][0], self.concepts, self.sources)
        raw = {'questions': [wrong], 'unfilled': 3, 'reason': ''}
        displayed, rejected = validate_job(raw, job, self.concepts, self.sources, set())
        self.assertEqual((len(displayed), rejected), (1, 0))
        self.assertTrue(displayed[0]['warnings'])
        self.assertEqual(displayed[0]['rawQuestion'], wrong)

    def test_legacy_count_only_assignment_keeps_wire_fields_and_shared_goals(self):
        legacy = {'unitId': 'old', 'conceptIds': ['c1'],
                  'counts': {'ox': 1, 'mcq': 0, 'word': 0, 'essay': 0}, 'focus': '예전 배정'}
        payload = self.payload(legacy)
        self.assertEqual(payload['assignment'], legacy)
        self.assertEqual(payload['sharedTargets'], target_index(self.plan))
        packed = {'unitId': 'old-transport', 'conceptIds': ['c1', 'c2'],
                  'counts': {'ox': 2, 'mcq': 0, 'word': 0, 'essay': 0},
                  'units': [legacy, {**legacy, 'unitId': 'old-two', 'conceptIds': ['c2']}]}
        self.assertEqual(wire_assignment(packed), packed)

    def test_single_target_split_uses_current_logical_unit_and_only_its_sources(self):
        source = self.plan['allocations'][0]
        child = quiz.scoped_targets(source, source['targets'][:1], source['unitId'] + '/batch-0')
        payload = self.payload(child)
        self.assertEqual(payload['assignment']['questionCount'], 1)
        self.assertEqual(payload['assignment']['tasks'][0]['unitId'], child['unitId'])
        self.assertEqual(payload['assignment']['tasks'][0]['targetId'], source['targets'][0]['id'])
        expected_sources = {sid for cid in child['conceptIds'] for sid in self.concepts[cid]['sourceIds']}
        self.assertEqual({s['sourceId'] for s in payload['sources']}, expected_sources)


if __name__ == '__main__':
    unittest.main()
