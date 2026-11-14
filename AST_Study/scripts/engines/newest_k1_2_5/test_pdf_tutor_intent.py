"""Offline contracts for context-aware retrieval and hosted-search spending."""
import copy
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from pdf_ai import Provider, tutor, BudgetExceeded
from pdf_pipeline import query_terms, retrieve
from pdf_tutor_intent import plan_question, planning_context, refined_plan, PLAN_SYSTEM, FOLLOWUP_PLAN_SYSTEM


def chunk(text, page, key):
    return {'id': key, 'documentId': 'doc', 'page': page, 'source': 'native',
            'field': 'markdown', 'start': 0, 'end': len(text), 'text': text}


def document():
    return {'documentId': 'doc', 'pages': [{} for _ in range(17)], 'chunks': [
        chunk('마티스의 삶의 기쁨은 색채와 형태의 혁신을 보여준다.', 16, 'matisse'),
        chunk('거울 속 여성의 몸은 자기 대상화와 자아 욕구를 드러낸다.', 17, 'mirror'),
        chunk('고갱의 작품 탄생에서는 생명의 탄생을 다룬다.', 15, 'gauguin'),
        chunk('고갱의 출생과 생애 연보.', 14, 'bio')]}


def semantic(subject, query=None, intent='explain', page=None, followup=False, web='none', artifact=False, ask=False):
    return dict(subject=subject, query=query or subject, intent=intent, page=page,
                followup=followup, web=web, artifact=artifact, ask=ask,
                scope='external' if web != 'none' else 'general', missingConditions=[])


class Replay:
    model = 'gpt-6-luna'
    def __init__(self, plan=None):
        self.plan = plan
        self.plans, self.answers, self.searches = [], [], []
    def plan_tutor(self, payload):
        self.plans.append(copy.deepcopy(payload))
        if isinstance(self.plan, Exception):
            raise self.plan
        return copy.deepcopy(self.plan)
    def complete(self, payload, **kwargs):
        self.answers.append(copy.deepcopy(payload))
        first = payload['sources'][0] if payload['sources'] else None
        return {'responseKind': 'document' if first else 'general',
                'answer': '자료를 바탕으로 해석하면 이렇게 설명할 수 있어요.',
                'notFound': False, 'needsExternalSearch': True,
                'evidence': [{'sourceId': first['sourceId'], 'quote': first['text']}] if first else []}
    def web_search(self, question, topic_hint=''):
        self.searches.append(question)
        return {'answer': '작품을 확인했어요. [1]',
                'webSources': [{'number': 1, 'title': '미술관', 'url': 'https://example.org/art'}]}


class TutorIntentTests(unittest.TestCase):
    def test_search_normalizes_both_sides_and_removes_request_filler(self):
        query = query_terms('야수파를 알 필요가 있어?')
        self.assertIn('야수파', query)
        for filler in ('야수파를', '필요', '필요가', '있어', '요가', '?'):
            self.assertNotIn(filler, query)
        doc = {'chunks': [chunk('필요가 있어 필요가 있어', 1, 'noise'),
                          chunk('야수파의 색채는 강렬하다.', 2, 'target')]}
        self.assertEqual([c['id'] for c in retrieve(doc, '야수파를 알 필요가 있어?')], ['target'])

    def test_semantic_plan_resolves_varied_ellipses_before_retrieval(self):
        # Deliberately use phrases absent from the local follow-up word list.
        memory = {'documentId': 'doc', 'topicQuestion': '삶의 기쁨 작품의 의미는?',
                  'focus': {'subject': '삶의 기쁨', 'page': 16, 'viewerPage': 16},
                  'turns': [{'question': '삶의 기쁨 작품의 의미는?', 'answer': '마티스 작품이에요.'}]}
        for question in ('그래서 미술사에서 남긴 게 뭔데?', '그걸 높게 쳐주는 까닭은?', '의의는뭐지?'):
            with self.subTest(question=question):
                provider = Replay(semantic('삶의 기쁨', '삶의 기쁨 색채 혁신', 'interpret', 16, True, artifact=True))
                result = tutor(document(), question, provider, memory=memory, current_page=16)
                self.assertEqual(provider.answers[0]['questionPlan']['subject'], '삶의 기쁨')
                self.assertEqual(provider.answers[0]['sources'][0]['sourceId'], 'matisse')
                self.assertEqual(result['memory']['focus']['subject'], '삶의 기쁨')
                self.assertEqual((len(provider.plans), len(provider.answers), len(provider.searches)), (1, 1, 0))

    def test_page_move_releases_old_source_and_scopes_new_page(self):
        provider = Replay(semantic('거울과 자아 욕구', page=17))
        first = tutor(document(), '17페이지의 거울은 어떤 욕구를 충족해?', provider, current_page=16)
        provider.plan = semantic('거울과 자아 욕구', '거울 자아 욕구', 'interpret', 17, True)
        second = tutor(document(), '왜 이렇게 표현한 걸까?', provider, memory=first['memory'], current_page=16)
        self.assertEqual(provider.answers[-1]['requestedPdfPage'], 17)
        self.assertEqual(provider.answers[-1]['sources'][0]['sourceId'], 'mirror')
        # An explicit question's page wins even while viewer position differs.
        self.assertEqual(second['memory']['focus']['page'], 17)
        memory = {'documentId': 'doc', 'topicQuestion': '16페이지 설명해줘',
                  'focus': {'subject': '삶의 기쁨', 'page': 16, 'viewerPage': 16},
                  'sourceIds': ['matisse'], 'turns': [{'question': '16페이지 설명해줘', 'answer': '색채 설명'}]}
        provider.plan = semantic('현재 그림', '거울 여성', 'interpret', 16, True)
        tutor(document(), '이건 무슨 의미야?', provider, memory=memory, current_page=17)
        self.assertEqual(provider.answers[-1]['requestedPdfPage'], 16)
        self.assertEqual(provider.answers[-1]['sources'][0]['sourceId'], 'matisse')

    def test_new_topic_replaces_focus_and_pdf_hits_cannot_choose_topic(self):
        memory = {'documentId': 'doc', 'topicQuestion': '거울 설명해줘',
                  'focus': {'subject': '거울', 'page': 17, 'viewerPage': 17},
                  'sourceIds': ['mirror'], 'turns': [{'question': '거울 설명해줘', 'answer': '여성의 자아 욕구'}]}
        provider = Replay(semantic('고갱의 탄생', '고갱 탄생 작품', artifact=True))
        result = tutor(document(), '고갱의 탄생을 설명해줘', provider, memory=memory, current_page=17)
        self.assertEqual(result['memory']['focus']['subject'], '고갱의 탄생')
        self.assertIsNone(result['memory']['focus']['page'])
        self.assertEqual(provider.answers[0]['sources'][0]['sourceId'], 'gauguin')
        self.assertEqual(provider.answers[0]['topicHint'], '')

    def test_web_search_uses_resolved_entity_not_biography(self):
        provider = Replay(semantic('고갱의 작품 탄생', web='explicit', artifact=True))
        result = tutor(document(), '그 화가가 그린 탄생 쪽 좀 찾아봐', provider)
        self.assertEqual(result['kind'], 'web_generated')
        self.assertEqual((len(provider.searches), len(provider.answers)), (1, 0))
        self.assertIn('작품의 제목/대상: 고갱의 작품 탄생', provider.searches[0])
        self.assertNotIn('색채와 형태의 혁신', provider.searches[0])

    def test_cached_research_reused_until_fresh_lookup_is_requested(self):
        provider = Replay(semantic('고갱의 작품 탄생', web='explicit', artifact=True))
        first = tutor(document(), '고갱의 탄생 작품 검색해줘', provider)
        provider.plan = semantic('고갱의 작품 탄생', followup=True, web='explicit', artifact=True)
        tutor(document(), '검색해서 조금 더 풀어줘', provider, memory=first['memory'])
        self.assertEqual(len(provider.searches), 1)
        provider.plan = semantic('고갱의 작품 탄생', followup=True, web='explicit', artifact=True)
        tutor(document(), '최신 자료로 다시 검색해줘', provider, memory=first['memory'])
        self.assertEqual(len(provider.searches), 2)

    def test_general_reasoning_and_missing_text_do_not_force_hosted_search(self):
        for question, intent in [('야수파를 알 필요가 있어?', 'learning_relevance'),
                                 ('이걸 가상의 예로 풀어줘', 'explain'),
                                 ('요즘 배운 개념을 지금 설명해줘', 'explain')]:
            provider = Replay(semantic('야수파', intent=intent))
            tutor(document(), question, provider)
            self.assertFalse(provider.answers[0]['externalSearchAvailable'])
            self.assertFalse(provider.searches)  # even if answer model requests search

    def test_pdf_local_lookup_and_user_opt_out_override_paid_search(self):
        for question, web in [('이 PDF에서 탄생을 검색해줘', 'none'),
                              ('고갱의 탄생 알려줘. 외부 검색하지 마', 'explicit')]:
            provider = Replay(semantic('고갱의 탄생', web=web, artifact=True))
            tutor(document(), question, provider)
            self.assertFalse(provider.searches)

    def test_unresolved_target_does_not_trigger_search(self):
        provider = Replay(semantic('', query='', web='explicit', ask=True))
        tutor(document(), '그거 검색해', provider)
        self.assertFalse(provider.searches)
        self.assertTrue(provider.answers[0]['questionPlan']['needsClarification'])

    def test_pdf_web_comparison_searches_once_then_synthesizes(self):
        provider = Replay(semantic('삶의 기쁨', intent='compare', web='explicit', artifact=True))
        result = tutor(document(), '이 PDF의 삶의 기쁨 설명과 웹 자료를 검색해서 비교해줘', provider)
        self.assertEqual((len(provider.plans), len(provider.searches), len(provider.answers)), (1, 1, 1))
        self.assertIn('savedWebResearch', provider.answers[0])
        self.assertFalse(provider.answers[0]['externalSearchAvailable'])
        self.assertTrue(result['evidence'])

    def test_viewer_change_is_shared_even_when_local_rules_do_not_recognize_ellipsis(self):
        state = {'focus': {'subject': '삶의 기쁨', 'page': 16, 'viewerPage': 16},
                 'turns': [{'question': '16페이지 설명해줘', 'answer': '마티스 작품'}]}
        local = plan_question('그거 말고 이쪽은 어떤 얘기야?', state, 17, None)
        context=planning_context('그거 말고 이쪽은 어떤 얘기야?', state, local, 17)
        self.assertNotIn('currentPage',context)
        self.assertNotIn('viewerPage',context['focus'])
        self.assertNotIn('pageChanged',context['localHint'])
        self.assertEqual(refined_plan(local, semantic('현재 페이지', page=16, followup=True), 17, None)['page'], 17)

    def test_explicit_lookup_cannot_be_silently_downgraded_by_planner(self):
        provider = Replay(semantic('고갱의 작품 탄생', web='none', artifact=True))
        tutor(document(), '고갱의 탄생 작품 검색해봐', provider)
        self.assertEqual(len(provider.searches), 1)

    def test_planner_failure_falls_back_without_a_retry(self):
        provider = Replay(BudgetExceeded('plan budget'))
        tutor(document(), '삶의 기쁨 작품을 설명해줘', provider)
        self.assertEqual((len(provider.plans), len(provider.answers), len(provider.searches)), (1, 1, 0))

    def test_plan_context_is_small_and_excludes_pdf_sources(self):
        state = {'focus': {}, 'turns': [{'question': '질문' * 2000, 'answer': '답변' * 5000}] * 20}
        local = plan_question('의미가 뭐야?', state, 1, None)
        payload = planning_context('의미가 뭐야?', state, local, 17)
        self.assertLessEqual(len(payload['recent']), 6)
        self.assertLessEqual(len(json.dumps(payload['recent'], ensure_ascii=False).encode()), 10000)
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 16000)
        self.assertNotIn('sources', payload)

    def test_malformed_plan_cannot_override_explicit_page(self):
        local = plan_question('17페이지 설명해줘', {}, 16, 17)
        for bad in ({}, semantic('작품', page=999), {**semantic('작품'), 'intent': []}):
            self.assertEqual(refined_plan(local, bad, 17, 17), local)
        self.assertEqual(refined_plan(local, semantic('작품', page=16), 17, 17)['page'], 17)

    def test_mentor_followup_prompt_does_not_change_the_shared_base_planner(self):
        # Golden digest of the user's pre-change backup; do not duplicate its 4 KB prompt.
        self.assertEqual('7ec1d53c61245605177291d90c11c2fb7218c746a3d3eb60c3732e812f87b85d',
                         hashlib.sha256(PLAN_SYSTEM.encode()).hexdigest())
        self.assertTrue(FOLLOWUP_PLAN_SYSTEM.startswith(PLAN_SYSTEM))
        self.assertNotIn('answerFocus',PLAN_SYSTEM);self.assertNotIn('needsExample',PLAN_SYSTEM)
        suffix=FOLLOWUP_PLAN_SYSTEM[len(PLAN_SYSTEM):]
        self.assertLessEqual(len(suffix.encode()),300)
        self.assertIn('answerFocus',suffix);self.assertIn('needsExample',suffix)

    def test_followup_focus_keeps_referent_and_purpose_without_rewriting_the_question(self):
        state={'focus':{'subject':'클래스 구성요소','page':1,'viewerPage':1},
               'turns':[{'question':'클래스 구성요소를 설명해줘','answer':'Datafield와 Interface를 구분했어요.'}]}
        cases=[('아하 그 멤버변수랑 멤버함수는 그중 뭐야?', '직전 구성요소 분류와 멤버변수·함수의 대응 확인', False),
               ('실제 C++ 코드에서 어느 위치에 선언해? 자세한 예시로 보여줘', '멤버 선언의 실제 코드 위치와 예제 설명', True)]
        for question,focus,needs_example in cases:
            with self.subTest(question=question):
                value={**semantic('클래스 구성요소',page=1,followup=True),'answerFocus':focus,'needsExample':needs_example}
                provider=Replay(value)
                local=plan_question(question,state,1,None)
                planned=provider.plan_tutor(planning_context(question,state,local,17))
                result=refined_plan(local,planned,17,None)
                self.assertEqual(focus,result['answerFocus']);self.assertIs(needs_example,result['needsExample'])
                self.assertEqual(question,provider.plans[0]['question'])
                self.assertEqual(state['turns'][0]['answer'],provider.plans[0]['recent'][0]['answer'])
                self.assertEqual((len(provider.plans),len(provider.answers),len(provider.searches)),(1,0,0))

    def test_invalid_followup_optional_fields_do_not_discard_valid_core_or_sibling(self):
        local=plan_question('그 의미를 확인하고 싶어',{'focus':{'subject':'이전 주제','viewerPage':1}},1,None)
        base=semantic('현재 해석 대상',query='현재 검색어',page=1,followup=True)
        for bad_focus in (None,True,1,[],{},'가'*101):
            with self.subTest(answerFocus=type(bad_focus).__name__):
                result=refined_plan(local,{**base,'answerFocus':bad_focus,'needsExample':False},17,None)
                self.assertEqual('현재 해석 대상',result['subject']);self.assertEqual('현재 검색어',result['query'])
                self.assertNotIn('answerFocus',result);self.assertIs(False,result['needsExample'])
        for bad_example in (None,0,1,'false',[],{}):
            with self.subTest(needsExample=type(bad_example).__name__):
                result=refined_plan(local,{**base,'answerFocus':'요청 관계 확인','needsExample':bad_example},17,None)
                self.assertEqual('현재 해석 대상',result['subject']);self.assertEqual('요청 관계 확인',result['answerFocus'])
                self.assertNotIn('needsExample',result)
        boundary=refined_plan(local,{**base,'answerFocus':'가'*100,'needsExample':True},17,None)
        self.assertEqual('가'*100,boundary['answerFocus']);self.assertIs(True,boundary['needsExample'])

    def test_optional_focus_is_cleared_on_independent_or_viewer_moved_scope(self):
        state={'focus':{'subject':'이전 주제','page':16,'viewerPage':16},'turns':[{'question':'이전 질문','answer':'이전 답변'}]}
        local={**plan_question('새 주제 설명해줘',state,16,None),'answerFocus':'남은 이전 의도','needsExample':False}
        original=copy.deepcopy(local)
        independent=refined_plan(local,{**semantic('새 주제',page=16),'answerFocus':'모델의 잘못된 후속 힌트','needsExample':False},17,None)
        self.assertFalse(independent['followup']);self.assertNotIn('answerFocus',independent);self.assertNotIn('needsExample',independent)
        self.assertEqual(original,local)
        moved={**plan_question('이쪽은 어떤 뜻이야?',state,17,None),'answerFocus':'이전 페이지의 의도','needsExample':False}
        result=refined_plan(moved,{**semantic('현재 페이지',page=16,followup=True),'answerFocus':'이전 페이지 의도','needsExample':False},17,None)
        self.assertEqual(17,result['page']);self.assertFalse(result['followup'])
        self.assertNotIn('answerFocus',result);self.assertNotIn('needsExample',result)

    def test_optional_absence_and_invalid_core_cannot_retain_stale_local_hints(self):
        clean=plan_question('이어서 설명해줘',{'focus':{'subject':'이전 주제','page':1,'viewerPage':1}},1,None)
        local={**clean,'answerFocus':'오래된 힌트','needsExample':False}
        result=refined_plan(local,semantic('현재 주제',page=1,followup=True),17,None)
        self.assertEqual('현재 주제',result['subject']);self.assertNotIn('answerFocus',result);self.assertNotIn('needsExample',result)
        self.assertEqual(clean,refined_plan(local,{},17,None))
        self.assertEqual('오래된 힌트',local['answerFocus'])

    def test_real_provider_planner_is_tool_free_bounded_and_billed(self):
        calls = []
        def transport(body):
            calls.append(body)
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(semantic('야수파'))}}],
                    'usage': {'prompt_tokens': 600, 'completion_tokens': 90}}
        with tempfile.TemporaryDirectory() as temp:
            provider = Provider(Path(temp), True, .02, transport=transport)
            provider.plan_tutor({'taskType': 'tutor', 'operation': 'query_plan', 'question': '야수파?'})
            self.assertEqual(len(calls), 1)
            self.assertNotIn('tools', calls[0])
            self.assertEqual(calls[0]['max_completion_tokens'], 512)
            self.assertEqual(calls[0]['reasoning_effort'], 'low')
            self.assertEqual(provider.ledger['requests'][0]['state'], 'settled')


if __name__ == '__main__':
    unittest.main()
