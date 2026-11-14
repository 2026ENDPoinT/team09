import copy
import json
import tempfile
import unittest
from pathlib import Path
import pdf_newest_k1_2_0 as engine
from pdf_k124_examples import earlier_teaching, merge_worked_methods, sibling_context, routine_disposition
from test_pdf_k120_compact_coverage import fixture


class ExampleSelection(unittest.TestCase):
    def decision(self, kind='routine_exercise'):
        return {'blockId':'a','reason':'현재 영상의 개별 문제 조건에 수를 대입하는 반복 계산이에요.',
                'referenceContext':None,
                'sourceDisposition':{'kind':kind,
                    'observations':['주어진 초기 위치와 속도로 구간 가속도를 계산하는 풀이예요.'],
                    'independentLearningPoint':'','keptConceptTitle':''},
                'exerciseSelection':{'kind':'worked_example','sourceQuote':'처음 속도는 2 m/s이며 가속도는 얼마인가?',
                                     'keptConceptTitle':''}}

    def test_image_only_exercise_can_be_accounted_without_inventing_a_concept(self):
        job,_,_,_=fixture()
        for b in job['blocks']:b.update(text='',hasVisual=True,kind='visual')
        raw={'concepts':[],'tables':[],'sequences':[],'uncertainBlocks':[],
             'excludedBlocks':[{**copy.deepcopy(self.decision()),'blockId':b['id']} for b in job['blocks']]}
        with tempfile.TemporaryDirectory() as tmp:
            request=engine.build_teaching_request(Path(tmp),job,job['blocks'],
                {'documentId':'doc','pages':[{'label':'1'}]},([],[]))
            result=engine.accept_teaching_reply(Path(tmp),{'documentId':'doc','pages':[{'label':'1'}]},
                [job],job,raw,request)
        self.assertEqual(result['concepts'],[])
        self.assertTrue(all(c['state']=='context' and c['resolution']['kind']=='routine_exercise'
                            for c in result['coverage']))

    def test_new_learning_unreadable_or_unanchored_omission_is_not_accepted(self):
        block={'id':'a','text':'일반적인 정의','hasVisual':True}
        for change in ('new','no_observation','no_quote','mismatched_concept'):
            d=self.decision()
            if change=='new':d['sourceDisposition']['independentLearningPoint']='처음 도입하는 조건'
            if change=='no_observation':d['sourceDisposition']['observations']=[]
            if change=='no_quote':d['exerciseSelection']['sourceQuote']=''
            if change=='mismatched_concept':d['sourceDisposition']['keptConceptTitle']='Missing'
            self.assertIsNone(routine_disposition(d,block,[block],[]))
        block['hasVisual']=False
        self.assertIsNone(routine_disposition(self.decision(),block,[block],[]))

    def accept(self, job, raw):
        for concept in raw['concepts']:
            concept['sourceSetup']['observedRelations'] = ['시각에 따라 위치가 달라져요.']
            concept['sourceSetup']['boundaryChecks'] = ['서로 다른 시각의 위치를 비교해요.']
            concept['sourceSetup']['sourceQuotes'] = ['물체의 위치가 시간에 따라 달라지는 운동']
        document = {'documentId': 'doc', 'fingerprint': 'test-pdf', 'pages': [{'label': '1'}]}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            request = engine.build_teaching_request(cache, job, job['blocks'], document, ([], []))
            result = engine.accept_teaching_reply(cache, document, [job], job, raw, request)
            saved = json.loads((cache / 'response-unit.json').read_text())
            self.assertEqual(engine.validate(saved, job, document), result)
        final = engine.assemble(document, 'newest-k1-2-4', 'document', None, [1], [job],
                                {0: result}, [], [], all_blocks=job['blocks'])
        return result, final

    def test_contradictory_practice_only_card_is_removed_from_lecture_and_concepts(self):
        job, _, _, raw = fixture()
        raw.pop('sourceCoverage')
        for block in job['blocks']:
            block.update(text='', hasVisual=True, kind='visual')
        raw['concepts'][0]['sourceSetup']['teachingRole'] = 'source_case'
        raw['concepts'][0]['title'] = '문제의 수치 풀이'
        raw['excludedBlocks'] = [{**self.decision('pure_practice'), 'blockId': block['id']}
                                 for block in job['blocks']]

        result, final = self.accept(job, raw)

        self.assertEqual(result['summary']['parts'], [])
        self.assertEqual(result['concepts'], [])
        self.assertEqual(final['sections'], [])
        self.assertEqual(final['concepts'], [])
        self.assertTrue(final['coverageComplete'])
        self.assertEqual([item['resolution']['kind'] for item in result['coverage']],
                         ['pure_practice', 'pure_practice'])

    def test_mixed_card_preserves_independent_main_and_its_table(self):
        job, _, _, raw = fixture()
        raw.pop('sourceCoverage')
        job['blocks'][0].update(text='', hasVisual=True, kind='visual')
        concept = raw['concepts'][0]
        concept['title'] = '이동 방법의 원리'
        for segment in concept['segments']:
            segment['blockIds'] = ['b']
        concept['segments'] += [
            # Identical MAIN text must not allow the old source index to attach
            # the excluded a citation to the surviving b paragraph again.
            {**concept['segments'][1], 'blockIds': ['a']},
            {'kind': 'explanation', 'text': '첫 문제에 주어진 속도를 숫자로 대입해요.', 'blockIds': ['a']},
            {'kind': 'easyExplanation', 'text': '첫 문제의 정답은 17이에요.', 'blockIds': ['a']},
        ]
        raw['tables'] = [
            {'conceptTitle': concept['title'], 'headers': ['구분', '의미'],
             'rows': [['위치', '물체가 있는 곳'], ['변위', '위치의 변화']], 'blockIds': ['b']},
            {'conceptTitle': concept['title'], 'headers': ['구간', '첫 문제 정답'],
             'rows': [['처음', '17'], ['나중', '23']], 'blockIds': ['a']},
        ]
        raw['sequences'] = [
            {'conceptTitle': concept['title'], 'title': '첫 문제 풀이 순서',
             'orderKind': 'procedure', 'transitions': [],
             'steps': [{'title': '문제 수치 대입', 'body': '첫 문제의 값 17을 계산해요.', 'blockIds': ['a']}]},
            {'conceptTitle': concept['title'], 'title': '변위의 일반적인 계산',
             'orderKind': 'procedure', 'transitions': [],
             'steps': [{'title': '위치의 차', 'body': '나중 위치에서 처음 위치를 빼요.', 'blockIds': ['b']}]},
        ]
        raw['excludedBlocks'] = [self.decision('pure_practice')]

        result, final = self.accept(job, raw)

        part, = final['sections'][0]['parts']
        self.assertIn('서로 다른 시각의 위치를 비교', part['body'])
        self.assertIn('| 변위 | 위치의 변화 |', part['body'])
        self.assertIn('나중 위치에서 처음 위치를 빼요', part['body'])
        self.assertNotIn('첫 문제', part['body'] + part['easyExplanation'])
        self.assertNotIn('stepFlow', part)
        self.assertEqual({item['sourceId'] for item in part['evidence']}, {'b'})
        self.assertEqual({item['blockId']: item['state'] for item in result['coverage']},
                         {'a': 'context', 'b': 'summarized'})

    def test_jointly_cited_new_method_survives_routine_receipt(self):
        job, _, _, raw = fixture()
        raw.pop('sourceCoverage')
        job['blocks'][0].update(text='', hasVisual=True, kind='visual')
        job['blocks'][1]['text'] = '각 층의 무게에 이동 거리를 곱하여 적분한다.'
        raw['excludedBlocks'] = [self.decision('pure_practice')]
        raw['concepts'][0]['segments'][1]['text'] = '각 층의 무게와 이동 거리를 곱해 일의 적분식을 세워요.'

        _, final = self.accept(job, raw)

        part, = final['sections'][0]['parts']
        self.assertIn('각 층의 무게와 이동 거리를 곱해', part['body'])
        self.assertIn('b', {item['sourceId'] for item in part['evidence']})

    def test_worked_method_reaches_saved_main_without_a_duplicate_card(self):
        job, _, _, raw = fixture()
        document = {'documentId': 'doc', 'fingerprint': 'test-pdf', 'pages': [{'label': '1'}]}
        raw.pop('sourceCoverage')
        job['blocks'][0].update(text='', hasVisual=True, kind='visual')
        method = raw['concepts'][0]
        method['title'] = '지수식의 치환'
        for segment in method['segments']:
            segment['blockIds'] = ['a']
        first_segment = method['segments'].pop(0)
        method['principle'] = {'text': '지수식을 새 변수로 두는 치환적분이에요.',
                               'blockIds': first_segment['blockIds']}
        method['segments'][0]['text'] = '지수식으로 변수를 바꾸면 미분량도 함께 바꿔요.'
        method['segments'].append({'kind': 'equation', 'text': r'\[u=e^x,\quad dx=du/u\]',
                                   'blockIds': ['a'], 'contentRole': 'instruction'})
        method['sourceSetup']['sourceQuotes'] = ['지수 함수의 미분']
        method['sourceSetup']['observedRelations'] = ['지수 함수의 미분으로 치환 관계를 얻어요.']
        method['sourceSetup']['boundaryChecks'] = ['치환한 변수는 양수예요.']
        regular = copy.deepcopy(method)
        regular['title'] = '다음 이론'
        regular['segments'].insert(0, {'kind': 'definition', **regular.pop('principle')})
        for segment in regular['segments']:
            segment['blockIds'] = ['b']
        regular['segments'].append({'kind': 'explanation', 'text': '원문에 없는 가정이에요.',
                                    'blockIds': ['b'], 'contentRole': 'hypothesis'})
        method['segments'].append({'kind': 'explanation', 'text': '이 문제의 정답은 17이에요.',
                                   'blockIds': ['a'], 'contentRole': 'instance'})
        raw['tables'] = [{'conceptTitle': method['title'], 'headers': ['문제', '정답'],
                          'rows': [['가', '17']], 'blockIds': ['a'], 'contentRole': 'instance'}]
        raw['workedMethods'] = [method]
        raw['concepts'] = [regular]
        raw['excludedBlocks'] = [self.decision('pure_practice')]
        original = copy.deepcopy(raw)
        with tempfile.TemporaryDirectory() as tmp:
            request = engine.build_teaching_request(Path(tmp), job, job['blocks'], document, ([], []))
            schema = request['response_format']['json_schema']['schema']
            self.assertEqual(next(iter(schema['properties'])), 'workedMethods')
            self.assertIn('equation', schema['properties']['concepts']['items']['properties']
                          ['segments']['items']['properties']['kind']['enum'])
            pattern = schema['properties']['workedMethods']['items']['properties']['principle']['properties']['text']['pattern']
            self.assertRegex(method['principle']['text'], pattern)
            self.assertNotRegex('\t' * 20, pattern)
            self.assertNotRegex('문' * 451, pattern)
            merged = merge_worked_methods(raw, request['_sourceCoverageExactFormat'])
            self.assertEqual(raw, original)
            self.assertNotIn('workedMethods', merged)
            self.assertEqual([c['title'] for c in merged['concepts']], ['지수식의 치환', '다음 이론'])
            result = engine.accept_teaching_reply(Path(tmp), document, [job], job, raw, request)
            saved = json.loads((Path(tmp) / 'response-unit.json').read_text())
            self.assertNotIn('workedMethods', saved)
            self.assertNotIn('principle', saved['concepts'][0])
            self.assertEqual(saved['tables'], [])
            self.assertEqual(engine.validate(saved, job, document), result)
        first, second = result['summary']['parts']
        self.assertIn(r'dx=du/u', first['body'])
        self.assertNotIn(r'$$\[', first['body'])
        self.assertNotIn('정답', first['body'])
        self.assertNotIn('원문에 없는 가정', second['body'])
        self.assertTrue(first['body'].startswith('지수식을 새 변수로'))
        self.assertEqual(second['title'], '다음 이론')
        self.assertTrue(all(row['state'] == 'summarized' for row in result['coverage']))

    def test_selected_method_uses_generic_math_and_keeps_the_source_citation(self):
        job, _, _, raw = fixture()
        raw.pop('sourceCoverage')
        method, = raw['concepts']
        raw['concepts'] = []
        method.update(methodTemplate='integral_remainder_log_power', principle={
            'text': '적분으로 나머지를 제한해요.', 'blockIds': ['a'],
        })
        method['segments'] = [{'kind': 'explanation', 'text': '예제에서는 지수에 3을 대입해요.',
                               'blockIds': ['a']}]
        method['sourceSetup']['observedRelations'] = ['양의 감소 급수의 꼬리를 적분으로 제한해요.']
        method['sourceSetup']['boundaryChecks'] = ['마지막 인덱스부터 꼬리 적분을 시작해요.']
        method['sourceSetup']['sourceQuotes'] = ['나머지 오차']
        raw['workedMethods'] = [method]
        result, final = self.accept(job, raw)
        part, = final['sections'][0]['parts']
        self.assertIn('L=m+N-1', part['body'])
        self.assertIn(r'(p-1)(\ln L)^{p-1}', part['body'])
        self.assertNotIn('지수에 3', part['body'])
        self.assertEqual({e['sourceId'] for e in part['evidence']}, {'a'})
        self.assertEqual(result['coverage'][0]['state'], 'summarized')

    def test_earlier_teaching_supplies_source_text_only_to_possible_applications(self):
        earlier = {'blocks': [
            {'id': 'far', 'page': 1, 'text': '먼 이론', 'planRole': 'teaching'},
            {'id': 'theory', 'page': 4, 'text': '가까운 이론', 'planRole': 'teaching'},
            {'id': 'exercise', 'page': 5, 'text': '다른 문제', 'planRole': 'exercise'},
        ]}
        own = {'id': 'target', 'page': 7, 'text': '현재 문제', 'planRoleBeforeVisualGuard': 'exercise'}
        self.assertEqual(earlier_teaching({'topicIndex': 1, 'blocks': [own]}, [earlier]),
                         [{'page': 4, 'nativeFragments': ['가까운 이론']}])
        self.assertEqual(earlier_teaching({'topicIndex': 1, 'blocks': [{'page': 7}]}, [earlier]), [])

    def test_visual_application_is_read_without_grouping_role_and_bounds_effort(self):
        blocks = [{'id': f'page-{page}', 'page': page, 'kind': 'visual', 'text': '',
                   'bbox': [0, 0, 1, 1], 'hasVisual': True, 'visualOnly': True,
                   'planRole': 'uncertain', 'planRoleBeforeVisualGuard': 'exercise'}
                  for page in range(1, 5)]
        job = {'id': 'application', 'blocks': blocks, 'title': '계획 제목',
               'unitContext': {'current': {'title': '계획 제목', 'description': '계획 설명', 'index': 2}}}
        document = {'documentId': 'doc', 'pages': [{} for _ in blocks]}
        with tempfile.TemporaryDirectory() as tmp:
            request = engine.build_teaching_request(Path(tmp), job, blocks, document, ([], []))
        payload = request['payload']
        self.assertNotIn('titleHint', payload)
        self.assertEqual(payload['unitContext']['current'], {'index': 2})
        self.assertTrue(all('planRole' not in block and 'planRoleBeforeVisualGuard' not in block
                            for block in payload['blocks']))
        self.assertEqual(request['context']['reasoningEffort'], 'medium')
        self.assertIn('The owned pages may be independent exercises.', request['instructions'])
        self.assertTrue(request['_checkedWorksheetOutput'])
        method = request['response_format']['json_schema']['schema']['properties']['workedMethods']['items']
        self.assertIn('methodTemplate', method['required'])
        self.assertEqual(job['unitContext']['current']['title'], '계획 제목')

    def test_unanchored_or_independently_teaching_source_is_not_suppressed(self):
        for kind in ('unanchored_native', 'independent_condition', 'duplicate_receipt',
                     'linked_title', 'legacy_routine'):
            with self.subTest(kind=kind):
                job, _, _, raw = fixture()
                raw.pop('sourceCoverage')
                for segment in raw['concepts'][0]['segments']:
                    segment['blockIds'] = ['a']
                receipt = self.decision('routine_exercise' if kind == 'legacy_routine' else 'pure_practice')
                if kind != 'unanchored_native':
                    job['blocks'][0].update(text='', hasVisual=True, kind='visual')
                if kind == 'independent_condition':
                    receipt['sourceDisposition']['independentLearningPoint'] = '처음 가르치는 적용 조건'
                elif kind == 'linked_title':
                    receipt['sourceDisposition']['keptConceptTitle'] = raw['concepts'][0]['title']
                    receipt['exerciseSelection']['keptConceptTitle'] = raw['concepts'][0]['title']
                raw['excludedBlocks'] = [receipt]
                if kind == 'duplicate_receipt':
                    raw['excludedBlocks'].append(copy.deepcopy(receipt))

                _, final = self.accept(job, raw)

                self.assertIn('서로 다른 시각의 위치를 비교', final['sections'][0]['body'])

    def test_uncertain_visual_is_not_counted_as_successfully_excluded(self):
        job, _, _, raw = fixture()
        raw.pop('sourceCoverage')
        job['blocks'][0].update(text='', hasVisual=True, kind='visual')
        for segment in raw['concepts'][0]['segments']:
            segment['blockIds'] = ['b']
        raw['concepts'][0]['segments'].append({
            'kind': 'uncertain', 'text': '그림 안의 식이 가려져 확인이 필요해요.', 'blockIds': ['a'],
        })
        raw['excludedBlocks'] = [self.decision('pure_practice')]

        result, final = self.accept(job, raw)

        self.assertIn('서로 다른 시각의 위치를 비교', final['sections'][0]['body'])
        unknown = next(item for item in result['coverage'] if item['blockId'] == 'a')
        self.assertEqual(unknown['state'], 'needs_review')
        self.assertFalse(final['coverageComplete'])

    def test_source_siblings_are_bounded_exact_background_not_target_citations(self):
        source=[{'id':str(i),'page':i,'text':'원래 이론 '+str(i)} for i in range(1,12)]
        before=copy.deepcopy(source)
        context=sibling_context({'blocks':source[7:9]}, {'blocks':source},limit=40)
        self.assertLessEqual(sum(len(s) for p in context['pages']for s in p['nativeFragments']),40)
        self.assertTrue(context['notProofOfPriorTeaching'])
        self.assertTrue(all(p['page'] not in [8,9] for p in context['pages']))
        self.assertTrue(all(s in [b['text']for b in source]for p in context['pages']for s in p['nativeFragments']))
        self.assertEqual(source,before)
        self.assertNotIn('blockIds',str(context))


if __name__=='__main__':unittest.main()
