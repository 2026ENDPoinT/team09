"""Citation recovery must preserve original facts and never invent supporting text."""
import copy
import unittest

from pdf_ai import tutor, review_evidence, tutor_exercise_pages, AiResponseError
from pdf_tutor_evidence import original_quote, citation_sources, bind_citations
from test_pdf_tutor_intent import chunk, document, semantic
from test_pdf_tutor_final_answer import Provider, reply


class CitationTests(unittest.TestCase):
    def delivered(self,text):
        provider=Provider([reply(text)],semantic('본문 보존'))
        result=tutor(document(),'내용을 설명해줘',provider,web_fallback=False)
        self.assertEqual(result['memory']['turns'][-1]['answer'],text)
        return result['answer']

    def test_literal_labels_code_math_and_links_are_preserved_in_the_model_body(self):
        for marker in ('{Q2}','[Q5]','【Q6】','〔Q8〕','［Q9］','[Q2, Q5]','{Q2; Q5}', '**[Q2]**'):
            with self.subTest(marker=marker):
                text='인수와 합병을 뜻해요. '+marker
                self.assertEqual(self.delivered(text),text)
        preserved=['`[Q5]`','```python\nprint("{Q2}")\n```',
            r'\(\{Q2\}\)',r'\[Q2\]',r'$$[Q5]$$',r'$Q2$','[Q2](https://example.org/q2)',
            '외부 출처 [1]과 Q2 문항을 비교해요.']
        for text in preserved:
            with self.subTest(preserve=text):self.assertEqual(self.delivered(text),text)

    def test_binding_evidence_does_not_rewrite_new_or_saved_answers(self):
        value=reply('인수와 합병을 설명해요. {Q2} [Q5]')
        value.update(responseKind='document',requiresPdfEvidence=True,
                     evidence=[{'sourceId':'matisse','quote':'마티스의 삶의 기쁨은 색채와 형태의 혁신을 보여준다.'}])
        provider=Provider([value],semantic('삶의 기쁨',page=16))
        memory={'documentId':'doc','turns':[{'question':'Q2 문항을 설명해줘','answer':'이전 설명이에요. 【Q2】'}]}
        result=tutor(document(),'16쪽 내용을 설명해줘',provider,memory=memory)
        self.assertEqual(result['answer'],value['answer'])
        self.assertEqual(result['evidence'][0]['sourceId'],'matisse')
        self.assertIn('【Q2】',str(provider.calls[0][0]['recentConversation']))
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertEqual(len(provider.calls),1)

    def test_typography_and_word_wrap_restore_exact_original(self):
        original = '원금은 𝟏𝟎𝟎만 달러예요. 예를 들\n어 계약 서류를 재사\n용할 수 있어요.'
        quote = '원금은 100만 달러예요. 예를 들어 계약 서류를 재사용할 수 있어요.'
        self.assertEqual(original_quote(quote, original), original)

    def test_sign_decimal_negation_and_order_changes_are_rejected(self):
        for quote, original in [('수익은 +10원', '수익은 -10원'),
                                ('값은 1.5예요', '값은 15예요'),
                                ('값은 x2예요', '값은 x²예요'),
                                ('금액은 10원', '금액은 1 0원'),
                                ('손실이 있다', '손실이 없다'),
                                ('A가 B에게 빌려줌', 'B가 A에게 빌려줌')]:
            self.assertIsNone(original_quote(quote, original))

    def test_ligatures_and_combining_marks_map_back_to_original(self):
        self.assertEqual(original_quote('café office', 'cafe\u0301 oﬃce'), 'cafe\u0301 oﬃce')

    def test_passages_cover_original_once_and_keep_long_source_tail(self):
        text = ('앞부분 설명이에요.\n' * 80) + '마지막에만 나오는 결론이에요.'
        parts, catalog = citation_sources([{'sourceId': 's', 'text': text}])
        self.assertEqual(''.join(p['text'] for p in parts), text)
        self.assertTrue(all(len(p['text']) <= 650 for p in parts))
        selected = bind_citations({'evidence': [{'sourceId': 's', 'quoteId': parts[-1]['quoteId']}]}, catalog)
        self.assertIn('마지막에만', selected['evidence'][0]['quote'])
        self.assertNotEqual(selected['evidence'][0]['quote'], text[:650])

    def test_unknown_cross_source_ids_and_rewrites_are_not_defaulted(self):
        parts, catalog = citation_sources([{'sourceId': 'right', 'text': '상환 순서는 계약에 따라 달라져요.'}])
        value = {'evidence': [{'sourceId': 'wrong', 'quoteId': parts[0]['quoteId']},
                              {'sourceId': 'right', 'quoteId': 'Q999'}]}
        bound = bind_citations(value, catalog)
        verified, incomplete = review_evidence(bound['evidence'],
            {'right': chunk('상환 순서는 계약에 따라 달라져요.', 1, 'right')}, normalize_typography=True)
        self.assertFalse(verified)
        self.assertTrue(incomplete)

    def test_valid_id_avoids_paid_quote_repair_and_preserves_both_pages(self):
        class IdProvider(Provider):
            def complete(self, payload, **kwargs):
                self.calls.append(copy.deepcopy(payload))
                refs = [{'sourceId': s['sourceId'], 'quoteId': s['quoteId']}
                        for s in payload['sources'] if s['sourceId'] in {'matisse', 'mirror'}]
                value = reply('두 페이지의 설명을 비교하면 이렇게 구별할 수 있어요.')
                value.update(responseKind='document', requiresPdfEvidence=True, evidence=refs)
                return value
        provider = IdProvider([], semantic('삶의 기쁨 거울', intent='compare'))
        result = tutor(document(), '16쪽과 17쪽의 설명을 비교해줘', provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual({e['page'] for e in result['evidence']}, {16, 17})
        self.assertFalse(result['evidenceIncomplete'])

    def test_legacy_quote_format_difference_needs_no_extra_model_call(self):
        doc = {'documentId': 'doc', 'pages': [{}], 'chunks': [
            chunk('𝟏𝟎𝟎만 원을 재사\n용해요.', 1, 's')]}
        value = reply('자료는 100만 원을 재사용한다고 설명해요.')
        value.update(responseKind='document', requiresPdfEvidence=True,
                     evidence=[{'sourceId': 's', 'quote': '100만 원을 재사용해요.'}])
        provider = Provider([value], semantic('재사용', page=1))
        result = tutor(doc, '1쪽 문장을 설명해줘', provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['evidence'][0]['quote'], '𝟏𝟎𝟎만 원을 재사\n용해요.')

    def test_unknown_extra_reference_is_filtered_without_rewriting_valid_prose(self):
        class ReferenceProvider(Provider):
            def complete(self, payload, **kwargs):
                self.calls.append((copy.deepcopy(payload), kwargs))
                source = payload['sources'][0]
                value = reply('자료에서 확인되는 설명이에요.')
                value.update(responseKind='document', requiresPdfEvidence=True,
                    evidence=[{'sourceId':source['sourceId'],'quoteId':source['quoteId']},
                              {'sourceId':'unseen','quoteId':'Q999'}])
                return value
        provider = ReferenceProvider([], semantic('삶의 기쁨', page=16))
        result = tutor(document(), '16쪽 자료를 설명해줘', provider)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(result['answer'],'자료에서 확인되는 설명이에요.')
        self.assertTrue(result['evidenceIncomplete'])
        self.assertEqual([e['sourceId'] for e in result['evidence']],['matisse'])

    def test_new_subject_drops_old_answer_prose_and_never_stores_retrieval_text(self):
        memory = {'documentId': 'doc', 'focus': {'subject': '이전 주제', 'page': 16, 'viewerPage': 16},
                  'topicQuestion': '이전 주제', 'turns': [
                      {'question': '이전 주제 설명해줘', 'answer': '검색 결과에서 우연히 나온 다른 주제예요.'}]}
        provider = Provider([reply('새 질문에 대한 설명이에요.')], semantic('새 질문'))
        result = tutor(document(), '적분 상수를 설명해줘', provider, memory=memory)
        self.assertLessEqual(len(provider.calls[0][0]['recentConversation']), 2)
        self.assertEqual(result['memory']['focus']['subject'], '새 질문')
        self.assertEqual(result['memory']['turns'][-1]['subject'], '새 질문')
        self.assertNotIn('sources', result['memory'])
        self.assertNotIn('거울 속 여성의 몸', str(result['memory']))

    def test_misclassified_followup_keeps_current_scenario_not_pdf_defaults(self):
        memory = {'documentId': 'doc', 'topicQuestion': '가상 포인터 코드',
                  'turns': [{'question': f'이전 질문 {i}', 'answer': 'PDF 예시의 a=100'} for i in range(4)] + [
                      {'question': 'p=&b 뒤 *p+=3을 하면?', 'answer': 'a=25, b=10이고 p는 b를 가리켜요.'}]}
        value = reply('p는 b를 가리키고 a는 25예요.')
        plan = {**semantic('포인터', page=1, followup=False), 'scope': 'general'}
        doc = {'documentId': 'doc', 'pages': [{}], 'chunks': [chunk('int a=100; int* p=&a;', 1, 's')]}
        provider = Provider([value], plan)
        tutor(doc, '여기까지 실행한 뒤 p와 a를 정리해줘', provider, memory=memory)
        payload = provider.calls[0][0]
        self.assertIn('a=25, b=10', str(payload['recentConversation']))
        self.assertNotIn('requestedPdfPage', payload)

    def test_qualified_confirmation_is_one_answer_and_local_display_cleanup_is_free(self):
        answer='맞아요. 이 조건에서는 같은 값이에요. 다만 다른 조건에서는 같다는 뜻은 아니에요.'
        value=reply(answer,claimVerdict='confirmed')
        provider=Provider([value],semantic('조건에 따른 값'))
        result=tutor(document(),'이 조건이면 값이 같은 거지?',provider)
        self.assertEqual(result['answer'],answer)
        self.assertEqual(len(provider.calls),1)

    def test_changed_multistep_calculation_keeps_current_case_in_one_answer_call(self):
        answer='3x-2x²=x(3-2x)=0이므로 경계는 x=0, 3/2이고 넓이는 9/8이에요.'
        question='계수를 바꾼 변형 문제의 넓이를 계산해줘'
        provider=Provider([reply(answer)],semantic('변경한 넓이 계산'))
        result=tutor(document(),question,provider)
        self.assertEqual(result['answer'],answer)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(provider.calls[0][0]['question'],question)

    def test_exercise_heading_context_survives_clipped_quotes_and_saved_guides(self):
        doc = {'chunks': [chunk('QUIZ\nOX\n가설이 참이다.', 3, 'quiz'),
                          chunk('해설\n가설은 거짓이다.', 2, 'lecture')]}
        self.assertEqual(tutor_exercise_pages(doc), [3])

    def test_unrequested_quiz_does_not_supply_lesson_facts_but_can_be_opened(self):
        doc = {'documentId': 'doc', 'pages': [{}, {}], 'chunks': [
            chunk('하트필드 작품은 정치적 선전이다.', 1, 'lesson'),
            chunk('QUIZ\nOX\n하트필드 작품은 정치적 선전과 무관하다.', 2, 'quiz')]}
        first = Provider([reply('정치적 선전과 관련돼요.')], semantic('하트필드', page=1))
        tutor(doc, '1쪽 하트필드 작품을 설명해줘', first)
        self.assertNotIn('quiz', [s['sourceId'] for s in first.calls[0][0]['sources']])
        second = Provider([reply('이 OX 문장은 틀렸어요.')], semantic('하트필드', page=2))
        tutor(doc, '2쪽 OX 문장이 맞아?', second)
        self.assertIn('quiz', [s['sourceId'] for s in second.calls[0][0]['sources']])

    def test_tutor_does_not_rewrite_display_controls_in_received_body(self):
        provider = Provider([reply('결과는 \x1c\\(x^2\\)\x1c이에요.')], semantic('수식'))
        result = tutor(document(), '수식을 정리해줘', provider)
        self.assertEqual(result['answer'], '결과는 \x1c\\(x^2\\)\x1c이에요.')
        self.assertEqual(len(provider.calls), 1)

    def test_verdict_metadata_does_not_authorize_deleting_an_opening(self):
        value = reply('네. 이 경우에는 해당하지 않아요.', claimVerdict='rejected')
        provider = Provider([value], semantic('조건 확인'))
        result = tutor(document(), '그 조건에 해당해?', provider)
        self.assertEqual(result['answer'], value['answer'])
        self.assertEqual(len(provider.calls), 1)

    def test_explicit_confirmed_judgment_survives_display_and_memory(self):
        value = reply('네, 맞아요. 참조 대상과 저장된 값은 달라요.', claimVerdict='confirmed')
        provider = Provider([value], semantic('참조와 값'))
        result = tutor(document(), '참조 대상과 저장된 값은 다른 뜻이 맞아?', provider)
        self.assertEqual(result['answer'], value['answer'])
        self.assertEqual(result['memory']['turns'][-1]['answer'], result['answer'])
        self.assertEqual(len(provider.calls), 1)

    def test_openings_and_qualified_judgments_are_delivered_verbatim(self):
        for text in ['아니요. 값은 달라요.', '예를 들어 둘을 비교해요.', '네.', '맞아요.',
                     '네, 가능해요.', '네, 맞아요. 값은 같아요.',
                     '예. 주어진 조건에서만 맞아요.', '일부만 맞아요. 조건을 구분해요.',
                     '네, 초대 정부는 이승만 대통령이 이끌었던 제1공화국 정부를 말해요.']:
            self.assertEqual(self.delivered(text),text)

    def test_verdict_metadata_does_not_authorize_replacing_a_streamed_answer(self):
        answer='맞아요. 이 조건에서는 값이 같아요.'
        for verdict in ('rejected','mixed','confirmed'):
            with self.subTest(verdict=verdict):
                provider=Provider([reply(answer,claimVerdict=verdict)],semantic('같은 값'))
                result=tutor(document(),'이 조건에서 값이 같아?',provider)
                self.assertEqual(result['answer'],answer)
                self.assertEqual(len(provider.calls),1)

    def test_citation_metadata_is_verified_without_editing_model_prose(self):
        value = reply('본문의 설명이에요. citeQ1 웹 출처는 [1]이에요.')
        value.update(responseKind='document', requiresPdfEvidence=True,
                     evidence=[{'sourceId': 'matisse', 'quote': '마티스의 삶의 기쁨은 색채와 형태의 혁신을 보여준다.'}])
        provider = Provider([value], semantic('삶의 기쁨', page=16))
        result = tutor(document(), '16쪽 내용을 설명해줘', provider)
        self.assertEqual(result['answer'],value['answer'])
        self.assertIn('[1]', result['answer'])
        self.assertEqual(result['evidence'][0]['sourceId'], 'matisse')
        self.assertEqual(len(provider.calls), 1)

    def test_marker_like_model_text_is_not_silently_deleted(self):
        provider = Provider([reply('citeQ1')], semantic('일반 개념'))
        result=tutor(document(), '개념을 설명해줘', provider)
        self.assertEqual(result['answer'],'citeQ1')
        self.assertEqual(len(provider.calls), 1)

    def test_empty_answer_still_fails_without_a_rewrite_or_retry(self):
        for text in ('','  \n  '):
            provider=Provider([reply(text)],semantic('개념'))
            with self.assertRaises((AiResponseError,ValueError)):
                tutor(document(),'개념을 설명해줘',provider)
            self.assertEqual(len(provider.calls),1)


if __name__ == '__main__':
    unittest.main()
