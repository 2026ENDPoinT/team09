import copy
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch

import pdf_summary_editor as editor
from pdf_ai import AiResponseError, BudgetExceeded


def sections():
    return [{'title': '기회' if i == 0 else '위험', 'body': text,
             'semanticUnitId': f'u{i}', 'evidence': [{'sourceId': f'b{i}', 'quote': text}],
             'visualPages': [i + 1], 'standardKnowledgeUsed': i == 1,
             'evidenceIncomplete': i == 1,
             'parts': [{'coveredElementIds': [f'b{i}'],
                        'easyExplanation': '새 일자리가 생기는 상황을 떠올려요.' if i == 0
                        else '일을 잃으면 생활비도 줄어드는 상황이에요.'}]} for i, text
            in enumerate(['새로운 일자리를 얻을 기회가 생겨요.', '일을 잃으면 소득이 줄 수 있어요.'])]


def response():
    return {'sections': [
        {'title': '산업화의 기회와 위험', 'body': '새로운 일자리를 얻기도 하지만 일을 잃으면 소득이 줄 수 있어요.',
         'easyExplanation': '일할 기회와 소득을 잃을 위험을 함께 살펴봐요.',
         'addedIllustration': False, 'sourceSectionIds': ['s0', 's1']}]}


class Provider:
    model = 'offline'
    def __init__(self, error=None):
        self.calls = []; self.error = error
    def complete(self, payload, **kwargs):
        self.calls.append(payload)
        if self.error:
            raise self.error
        if payload['task'] == 'lecture_flow_from_headings':
            return {'body': '산업화의 기회와 위험을 살펴봐요.', 'topicIds': ['s0']}
        return response()


class EditorTests(unittest.TestCase):
    def test_merge_preserves_provenance_flags_and_does_not_mutate_drafts(self):
        source = sections(); saved = copy.deepcopy(source)
        result = editor.validate_edit(response(), source)
        self.assertEqual(source, saved)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['visualPages'], [1, 2])
        self.assertEqual(result[0]['semanticUnitIds'], ['u0', 'u1'])
        self.assertEqual(result[0]['parts'][0]['coveredElementIds'], ['b0', 'b1'])
        self.assertEqual([e['sourceId'] for e in result[0]['evidence']], ['b0', 'b1'])
        self.assertTrue(result[0]['standardKnowledgeUsed'])

    def test_multistep_easy_explanation_survives_edit_without_truncation(self):
        easy = ('함수는 이름을 붙여 둔 작업이에요.\n\n'
                '1. **선언**: `void starbar(void);`로 이름과 입출력 정보를 알려요.\n'
                '2. **호출**: `starbar();`를 만나면 함수로 이동해요.\n'
                '3. **정의**: `void starbar(void) { ... }` 안에 실행할 코드를 적어요.\n\n'
                '함수가 끝나면 호출 다음 위치로 돌아와요. 지역 변수는 그 함수 안에서만 써요.')
        value = response()
        value['sections'][0]['easyExplanation'] = easy
        result = editor.validate_edit(value, sections())
        self.assertEqual(result[0]['parts'][0]['easyExplanation'], easy)

    def test_new_illustration_is_labeled_and_marks_standard_knowledge(self):
        value = response()
        value['sections'][0]['sourceSectionIds'] = ['s0']
        value['sections'][0]['addedIllustration'] = True
        value['sections'][0]['easyExplanation'] = (
            '기회는 새로운 선택지가 생기는 일이에요.\n\n'
            '**추가 예시** 동네 가게가 새 직원을 뽑으면 지원할 자리가 하나 늘어나요.'
        )
        result = editor.validate_edit(value, sections()[:1])
        self.assertTrue(result[0]['standardKnowledgeUsed'])
        self.assertIn('**추가 예시**', result[0]['parts'][0]['easyExplanation'])
        value['sections'][0]['easyExplanation'] = '동네 가게가 새 직원을 뽑아요.'
        result = editor.validate_edit(value, sections()[:1])
        self.assertTrue(result[0]['standardKnowledgeUsed'])

    def test_missing_duplicate_and_foreign_source_ids_rejected(self):
        for ids in [['s0'], ['s0', 's0'], ['s0', 's2'], []]:
            with self.subTest(ids=ids):
                value = response(); value['sections'][0]['sourceSectionIds'] = ids
                with self.assertRaises(ValueError):
                    editor.validate_edit(value, sections())

    def test_presentation_order_is_fixed_locally_without_changing_group_membership(self):
        value = response(); first = value['sections'][0]
        first['sourceSectionIds'] = ['s1']
        value['sections'].append({**first, 'sourceSectionIds': ['s0']})
        result = editor.validate_edit(value, sections())
        self.assertEqual([s['sourceSectionIds'] for s in result], [['s0'], ['s1']])
        value = response(); value['sections'][0]['sourceSectionIds'] = ['s1', 's0']
        result = editor.validate_edit(value, sections())
        self.assertEqual(result[0]['sourceSectionIds'], ['s0', 's1'])

    def test_later_topic_revisit_can_join_earlier_section_without_losing_other_topics(self):
        source = sections() + [copy.deepcopy(sections()[0])]
        value = response()
        first = value['sections'][0]
        first['sourceSectionIds'] = ['s0', 's2']
        value['sections'].append({**first, 'sourceSectionIds': ['s1']})
        result = editor.validate_edit(value, source)
        self.assertEqual([s['sourceSectionIds'] for s in result], [['s0', 's2'], ['s1']])

    def test_editor_and_title_only_flow_cache_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = Provider(); cache = Path(temp)
            for _ in range(2):
                _, result, status = editor.edit_summary(provider, cache, sections())
                self.assertEqual(status['status'], 'edited')
                self.assertEqual(len(result), 1)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(provider.calls[1], {'task': 'lecture_flow_from_headings',
                'topics': [{'id': 's0', 'title': '산업화의 기회와 위험',
                            'subheadings': ['산업화의 기회와 위험']}]})
            self.assertNotIn('evidence', provider.calls[0]['drafts'][0])
            self.assertNotIn('easyExplanation', provider.calls[0]['drafts'][0])
            self.assertFalse(provider.calls[0]['drafts'][0]['standardKnowledgeUsed'])
            self.assertTrue(provider.calls[0]['drafts'][1]['standardKnowledgeUsed'])
            self.assertEqual(provider.calls[0]['drafts'][0]['easyHints'],
                             ['새 일자리가 생기는 상황을 떠올려요.'])
            self.assertEqual(provider.calls[0]['drafts'][1]['easyHints'],
                             ['일을 잃으면 생활비도 줄어드는 상황이에요.'])

    def test_easy_hints_use_part_explanations_once_with_section_fallback(self):
        source = sections()
        source[0]['parts'].append({'easyExplanation': source[0]['parts'][0]['easyExplanation']})
        source[1]['parts'] = []
        source[1]['easyExplanation'] = '생활비가 줄어드는 상황이에요.'
        items = editor.draft_items(source)
        self.assertEqual(items[0]['easyHints'], ['새 일자리가 생기는 상황을 떠올려요.'])
        self.assertEqual(items[1]['easyHints'], ['생활비가 줄어드는 상황이에요.'])

    def test_optional_edit_failure_keeps_complete_drafts_without_second_call(self):
        for error in [AiResponseError('offline'), BudgetExceeded('budget'), ValueError('invalid'),
                      RuntimeError('CLI transport error'), OSError('IO')]:
            with self.subTest(error=type(error)), tempfile.TemporaryDirectory() as temp:
                provider = Provider(error); source = sections()
                _, result, status = editor.edit_summary(provider, Path(temp), source)
                self.assertEqual(result, source)
                self.assertEqual(status['status'], 'drafts_retained')
                self.assertEqual(len(provider.calls), 1)

    def test_cancellation_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(InterruptedError):
                editor.edit_summary(Provider(InterruptedError('cancelled')), Path(temp), sections())

    def test_oversize_or_local_only_never_calls_api(self):
        for local in [False, True]:
            with self.subTest(local=local), tempfile.TemporaryDirectory() as temp:
                provider = Provider()
                with patch.object(editor, 'MAX_INPUT_BYTES', 1):
                    _, result, status = editor.edit_summary(provider, Path(temp), sections(), local_only=local)
                self.assertEqual(provider.calls, [])
                self.assertEqual(result, sections())
                self.assertEqual(status['status'], 'drafts_retained')

    def test_cached_only_revalidation_never_buys_a_missing_response(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = Provider()
            _, result, status = editor.edit_summary(provider, Path(temp), sections(), cached_only=True)
            self.assertEqual(provider.calls, [])
            self.assertEqual(result, sections())
            self.assertEqual(status['reason'], 'no_saved_edit')

    def test_invalid_paid_result_is_saved_and_not_rebought(self):
        class Invalid(Provider):
            def complete(self, payload, **kwargs):
                self.calls.append(payload)
                value = response(); value['sections'][0]['sourceSectionIds'] = ['s0']
                return value
        with tempfile.TemporaryDirectory() as temp:
            provider = Invalid()
            for _ in range(2):
                _, result, status = editor.edit_summary(provider, Path(temp), sections())
                self.assertEqual(status['status'], 'drafts_retained')
                self.assertEqual(result, sections())
            self.assertEqual(len(provider.calls), 1)


class ParallelEditorTests(unittest.TestCase):
    def test_groups_run_together_and_keep_global_source_ids(self):
        source=[copy.deepcopy(sections()[i%2]) for i in range(8)]
        for i,s in enumerate(source):
            s['semanticUnitId']=f'u{i}';s['visualPages']=[i//4+1]
        gate=threading.Barrier(2)
        class Parallel(Provider):
            def complete(self,payload,**kwargs):
                self.calls.append(payload)
                self_case.assertLessEqual(len(payload['drafts']),4)
                gate.wait(2)
                return {'sections':[{'title':'기회와 위험','body':'\n\n'.join(x['body'] for x in payload['drafts']),
                    'easyExplanation':'기회와 위험을 함께 살펴봐요.','addedIllustration':False,
                    'sourceSectionIds':[x['id'] for x in payload['drafts']]}]}
        self_case=self
        with tempfile.TemporaryDirectory() as temp:
            p=Parallel();result,status=editor.parallel_edit(p,Path(temp),source)
            self.assertEqual(len(p.calls),2)
            self.assertEqual(status['pendingGroups'],[])
            self.assertEqual([i for s in result for i in s['sourceSectionIds']],[f's{i}' for i in range(8)])
            self.assertEqual([i for s in result for i in s['semanticUnitIds']],[f'u{i}' for i in range(8)])

    def test_failed_group_keeps_its_checked_drafts(self):
        source=sections()*3
        for s in source:s['visualPages']=[1]
        with tempfile.TemporaryDirectory() as temp:
            result,status=editor.parallel_edit(Provider(AiResponseError('uncertain')),Path(temp),source)
        self.assertEqual(result,source)
        self.assertEqual(status['pendingGroups'],[0,1])

    def test_independent_complete_topics_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Provider();result,status=editor.parallel_edit(p,Path(temp),sections())
        self.assertEqual(p.calls,[])
        self.assertEqual(result,sections())
        self.assertEqual(status['status'],'source_retained')


if __name__ == '__main__':
    unittest.main()
