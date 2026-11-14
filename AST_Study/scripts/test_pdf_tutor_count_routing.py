"""Keep visual word counts distinct from document metadata and object questions."""
import unittest

from pdf_ai import tutor
from pdf_tutor_document_find import request
from test_pdf_tutor_intent import Replay, document, semantic


SCREENSHOT = '이 pdf 전체에서 이미지 속 데이먼이라는 말이 몇번 나와?'


class TutorCountRoutingTests(unittest.TestCase):
    def test_literal_image_count_forms_resolve_term_and_scope(self):
        cases = [
            (SCREENSHOT, '데이먼'),
            ('PDF 안 그림에 “포인터”는 몇 번 나와?', '포인터'),
            ('이 문서에서 사진 속에 적힌 배열이라는 단어는 총 몇 회 나와?', '배열'),
            ('이 PDF에서 이미지 안에서만 “맷 데이먼”이 몇 번 나와?', '맷 데이먼'),
            ('PDF 전체 이미지들에서 제이미라는 이름이 몇 번 언급돼?', '제이미'),
            ('PDF 도표의 글자 중 감소가 몇 번 나와?', '감소'),
            ('How many times does "Damon" appear inside images in the PDF?', 'Damon'),
        ]
        for question, term in cases:
            with self.subTest(question=question):
                lookup = request(question)
                self.assertEqual(lookup['term'], term)
                self.assertEqual(lookup['scope'], 'images')

    def test_image_scope_does_not_include_unrelated_text_or_image_objects(self):
        self.assertNotIn('scope', request('이 PDF에서 “이미지 속”은 몇 번 나와?'))
        self.assertIsNone(request('이 PDF 이미지에서 자동차가 몇 번 나와?'))
        self.assertIsNone(request('PDF 이미지로 “데이먼”이 몇 번 나와?'))
        self.assertIsNone(request('이 PDF의 그림 속 “포인터”가 몇 번 나오는지와 뜻을 설명해줘'))

    def test_referential_and_multi_term_requests_do_not_count_a_partial_name(self):
        for question in ('이 PDF 이미지 속 데이먼과 고든이라는 말이 몇 번 나와?',
                         '이 PDF 이미지 속 “데이먼”이나 고든이 몇 번 나와?',
                         '이 PDF 이미지 속 그 사람이라는 말이 몇 번 나와?',
                         '이 PDF 이미지 속 맷 데이먼이라는 말이 몇 번 나와?',
                         '이 PDF에서 아까 말한 그분은 몇 번 나와?'):
            with self.subTest(question=question):
                self.assertIsNone(request(question))

    def test_explicit_image_and_text_scope_is_preserved(self):
        for question in ('이 PDF에서 본문과 이미지의 “주가”는 몇 회 나와?',
                         '이 PDF에서 이미지까지 포함해서 “주가”는 몇 번 나와?'):
            with self.subTest(question=question):
                self.assertEqual(request(question)['scope'], 'all')

    def test_wrong_semantic_page_count_cannot_bypass_a_content_answer(self):
        for question in ('이 PDF 그림 속 자동차는 몇 번 나와?',
                         '이 PDF 전체는 몇 페이지고 핵심 내용은 뭐야?',
                         '다다이즘은 몇 페이지에 있어?'):
            with self.subTest(question=question):
                provider = Replay(semantic('문서 분량', intent='page_count'))
                result = tutor(document(), question, provider)
                self.assertNotIn('documentMetadata', result)
                self.assertEqual(len(provider.plans), 1)
                self.assertEqual(len(provider.answers), 1)
                self.assertNotEqual(provider.answers[0]['questionPlan']['intent'], 'page_count')


if __name__ == '__main__':
    unittest.main()
