"""Observed scope qualifiers survive; absent-source prose stays excluded."""
import copy
import unittest

from pdf_new_concept_ver99_checks import learner_text, prepare_response


class InterpretationBoundaryTests(unittest.TestCase):
    def test_announcement_numbers_do_not_imply_actual_results(self):
        text = ('이는 그림에 제시된 정책 수치이며, 그 자체로 실제 관세 징수 결과를 '
                '뜻하지는 않아요.')
        self.assertEqual(learner_text(text), (text, []))

    def test_observation_and_forecast_inference_limits_are_teaching(self):
        for text in (
            '자료에서 관찰한 상관관계만으로 인과관계를 확정할 수는 없어요.',
            '이 자료에 제시된 예측값은 실제 측정 결과를 보장하지 않아요.',
            '이 자료의 발표만으로 실제 투자의 집행을 단정할 수 없어요.',
        ):
            with self.subTest(text=text):
                self.assertEqual(learner_text(text), (text, []))

    def test_real_source_gaps_do_not_gain_a_sampling_or_inference_exception(self):
        for text in (
            '자료에는 수치가 없어 실제 결과를 입증할 수 없어요.',
            '이 이미지의 수치가 판독되지 않아 발표 내용을 확정할 수 없어요.',
            '이 자료에는 제목만 있어 모델의 주장을 확정할 수 없어요.',
            '제공된 정보가 부족해서 관찰 결과를 입증할 수 없어요.',
            '자료는 두 기법을 소개하지만 각각의 제작 과정이나 시각적 효과는 설명하지 않아요.',
        ):
            with self.subTest(text=text):
                self.assertEqual(learner_text(text), ('', [text]))

    def test_mixed_paragraph_keeps_boundary_and_removes_only_unreadable_filler(self):
        boundary = '자료에서 관찰한 상관관계만으로 인과관계를 확정할 수는 없어요.'
        filler = '이 이미지에는 수치가 없어 값을 읽을 수 없어요.'
        text = '두 변수는 함께 변해요. ' + boundary + ' ' + filler
        kept, removed = learner_text(text)
        self.assertIn('두 변수는 함께 변해요.', kept)
        self.assertIn(boundary, kept)
        self.assertEqual(removed, [filler])

    def raw(self, text, *, uncertain=False):
        return {'concepts': [{'title': '관측과 해석', 'segments': [
            {'kind': 'definition', 'text': '관측값과 해석을 구분해요.', 'blockIds': ['a']},
            {'kind': 'explanation', 'text': text, 'blockIds': ['a']},
            {'kind': 'easyExplanation', 'text': '관측한 범위부터 확인해요.', 'blockIds': ['a']},
        ]}], 'tables': [], 'sequences': [], 'excludedBlocks': [],
            'uncertainBlocks': [{'blockId': 'a', 'reason': '실제 원문을 판독할 수 없어요.'}]
            if uncertain else []}

    def test_materialization_preserves_supported_boundary_without_raw_mutation(self):
        text = '이는 그림에 제시된 정책 수치이며, 그 자체로 실제 관세 징수 결과를 뜻하지는 않아요.'
        raw = self.raw(text)
        original = copy.deepcopy(raw)
        value = prepare_response(raw)
        self.assertEqual(value['concepts'][0]['explanation'], text)
        self.assertEqual(value['uncertainBlocks'], [])
        self.assertEqual(raw, original)
        self.assertEqual(prepare_response(value), value)

    def test_boundary_does_not_republish_uncertain_sources_or_invalid_math(self):
        text = '이 자료의 발표만으로 실제 투자의 집행을 단정할 수 없어요.'
        for raw in (self.raw(text, uncertain=True), self.raw(r'\(2+2=5\)예요. ' + text)):
            with self.subTest(uncertain=raw['uncertainBlocks']):
                value = prepare_response(raw)
                self.assertFalse(any(text in c.get('explanation', '') for c in value['concepts']))
                self.assertTrue(value['uncertainBlocks'])


if __name__ == '__main__':
    unittest.main()
