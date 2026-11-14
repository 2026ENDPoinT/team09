"""Answer-blind conservative balance checks for long Korean prose options."""
import copy
import unittest

from pdf_quiz_quality import _option_prose, local_issues


# Exact option text from the five paid art high-review recovery examples.
# No answer key is needed or embedded in this fixture.
ACTUAL_RECOVERED_OPTIONS = [{'id': '7168f025f68140cbbd9bf7fcaa8fa1eb',
  'texts': ['전쟁 이전의 도시적 활기는 다다의 배경과 구별해야 한다. 다다는 전쟁기의 불안과 문명에 대한 회의를 바탕으로 이성과 전통적 미학에 저항한 운동으로 해석할 수 있다.',
            '도시적 활기가 다다보다 앞섰으므로 다다의 반이성적 태도도 그 활기가 낳은 결과이며, 전쟁과 문명에 대한 회의는 부차적이다.',
            '취리히가 중립국이었으므로 전쟁은 다다의 형성에 영향을 주지 않았다. 따라서 다다의 전통 거부는 전쟁기의 위기와 무관하다.',
            '다다의 혼돈과 비이성은 전통 미학의 표현 기법만 바꾼 것이므로, 기존 체계에 대한 저항과는 구별해야 한다.']},
 {'id': '7bbf51e8637147fe8f89d17967f6b1c1',
  'texts': ['㉠은 음성시, ㉡은 우연성의 법칙에 부합한다. 우연성의 법칙은 작가의 제작 과정 전체가 개입 없이 이루어져야 한다는 뜻이다.',
            '㉠은 음성시, ㉡은 우연성의 법칙에 부합한다. 작가는 조각을 준비하고 떨어뜨리지만, 이후 배치에 대한 의도적 통제를 줄여 우발적 사건이 구도를 이끌게 한다.',
            '㉠은 우연성의 법칙, ㉡은 음성시에 부합한다. 두 사례 모두 작품의 의미를 미리 정하지 않는 점이 핵심이다.',
            '두 사례 모두 음성시에 부합한다. ㉡의 종이 조각 배치도 음절의 운율을 시각적으로 옮긴 것이기 때문이다.']},
 {'id': '070a2dfe5b82478db885ba9655cdd7be',
  'texts': ['사진은 현실을 기록하는 매체이므로 조각들을 결합한 뒤에도 화면 전체는 한 장면의 사실 기록으로 보아야 한다. 지폐는 인물의 경제적 성공을 나타낸다.',
            '이미지를 결합해 새로운 공간을 만든다는 형식적 특징은 인정할 수 있지만, 사진과 글자를 사용한 작품에는 정치적 비판이 성립하지 않는다.',
            '서로 다른 맥락의 사진 조각을 병치하면 원래의 장면 기록과는 다른 관계와 의미가 생긴다. 지폐는 인물에게 미치는 자본주의의 영향력을 드러내며, 이런 결합은 사회 비판의 '
            '수단이 될 수 있다.',
            '지폐 이미지가 들어간 작품은 자본주의를 지지하는 선전으로 해석해야 한다. 사진의 맥락을 바꾸는 편집은 정치적 의미에 영향을 주지 않는다.']},
 {'id': '3dc4e1d23a904d9f89bc7f3e59e8237a',
  'texts': ['㉠은 인화 과정에서 빛을 이용한 솔라리제이션이고, ㉡과 ㉢은 카메라 없는 사진 기법에 해당한다. ㉣은 카메라를 사용하지만 새로운 시각 표현을 추구하므로 뉴 비전의 접근과 '
            '맞닿으며, 안내문의 설명은 지나치게 넓다.',
            '㉠은 레이요그램이고 ㉡은 솔라리제이션이다. ㉢은 뉴 비전이며, ㉣은 카메라를 사용했으므로 예술적 사진 표현과 무관하다.',
            '㉡과 ㉢은 모두 카메라 없는 기법이므로 서로 다른 기법으로 확정할 수 있다. ㉣은 뉴 비전의 사례이므로 카메라를 사용한 사진은 뉴 비전으로 분류된다.',
            '㉠은 뉴 비전이고 ㉣은 솔라리제이션이다. 사진의 새로운 표현은 카메라가 없는 경우에만 가능하므로 안내문의 설명은 타당하다.']},
 {'id': '0722613e36ca45d0b82ee932b9c41158',
  'texts': ['전시 거부는 작품으로 인정되는 기준에 미술 제도가 관여함을 드러낼 수 있다. 그러나 ㉡은 손으로 그린 부분이 있으므로 고전적 미의 관습을 흔드는 관념과는 무관하다.',
            '㉠은 전시 주최 측이 거부했으므로 제도 비판과 무관하다. ㉡은 원본의 시각적 아름다움을 보존하므로 고전적 미의 기준을 강화한다.',
            '두 작품 모두 작품으로 승인되었는지만이 의미를 결정한다. 따라서 ㉠의 선택 행위와 ㉡의 변형 및 제목은 해석에 영향을 주지 않는다.',
            '㉠의 거부는 무엇이 작품으로 인정되는지가 전시 제도와 연결됨을 드러낼 수 있고, 일상 사물의 선택·제시는 그 기준에 도전한다. ㉡도 수염을 덧그린 행위만으로 의미가 '
            '소진되지 않으며, 이미지 변형과 언어유희로 고전적 미의 관습을 흔든다.']}]


def question(texts, answer=None):
    result = {'type': 'mcq', 'stem': '옳은 설명을 고르시오.',
              'options': [{'id': label, 'text': text, 'explanation': '보기의 내용을 검토한다.'}
                          for label, text in zip('ABCD', texts)],
              'explanation': '제시된 조건을 검토한 결과이다.'}
    if answer is not None:
        result['answer'] = answer
    return result


def sized(lengths):
    return question([syllable*length for syllable, length in zip('가나다라', lengths)])


def imbalance(value):
    return [finding for finding in local_issues(value) if finding['code']=='uneven_option_detail']


class QuizOptionLengthTests(unittest.TestCase):
    def test_actual_five_recovered_art_examples_are_all_caught_without_keys(self):
        expected = [(91, 68), (87, 69), (105, 82), (118, 83), (131, 91)]
        for row, pair in zip(ACTUAL_RECOVERED_OPTIONS, expected):
            with self.subTest(id=row['id']):
                self.assertEqual(tuple(sorted(map(len, row['texts']), reverse=True)[:2]), pair)
                item = question(row['texts'])
                self.assertNotIn('answer', item)
                self.assertEqual(len(imbalance(item)), 1)

    def test_exact_ratio_and_difference_boundaries_use_integer_comparisons(self):
        cases = [((90, 72, 60, 55), True),
                 ((91, 73, 60, 55), False),
                 ((85, 68, 60, 55), False),
                 ((124, 100, 80, 60), False),
                 ((125, 100, 80, 60), True),
                 ((89, 72, 60, 55), False)]
        for lengths, expected in cases:
            with self.subTest(lengths=lengths):
                self.assertEqual(bool(imbalance(sized(lengths))), expected)

    def test_tied_longest_options_are_not_flagged(self):
        self.assertFalse(imbalance(sized((90, 90, 60, 55))))
        self.assertFalse(imbalance(sized((90, 90, 90, 90))))

    def test_answer_key_or_option_id_changes_do_not_change_finding(self):
        texts = ACTUAL_RECOVERED_OPTIONS[0]['texts']
        baseline = local_issues(question(texts))
        for answer in ('A', 'B', 'C', 'D', 'unknown'):
            with self.subTest(answer=answer):
                self.assertEqual(local_issues(question(texts, answer)), baseline)
        item = question(texts)
        for i, option in enumerate(item['options']):
            option['id'] = str(i+101)
        self.assertEqual(local_issues(item), baseline)
        self.assertNotIn('A', baseline[0]['message'])

    def test_long_distractor_is_treated_like_any_other_long_option(self):
        item = sized((90, 72, 60, 55)); item['answer'] = 'D'
        self.assertEqual(len(imbalance(item)), 1)

    def test_normal_word_spaces_survive_but_markup_and_repeated_spaces_do_not(self):
        self.assertEqual(_option_prose('  이것은   긴\n한국어 **설명**이다.  '), '이것은 긴 한국어 설명이다.')
        self.assertEqual(_option_prose('<em>설명</em>과 [다른 내용](https://example.com/path)'), '설명과 다른 내용')
        self.assertEqual(_option_prose('이것은&nbsp;설명이다.'), '이것은 설명이다.')
        self.assertEqual(len(_option_prose('가 나 다')), 5)
        texts = ACTUAL_RECOVERED_OPTIONS[0]['texts']
        formatted = ['**'+text.replace(' ', '  \n\t')+'**' for text in texts]
        self.assertEqual(imbalance(question(texts)), imbalance(question(formatted)))
        linked = ['['+text+'](https://example.com/x/y)' for text in texts]
        self.assertEqual(imbalance(question(texts)), imbalance(question(linked)))

    def test_markup_and_spacing_cannot_create_a_false_length_outlier(self):
        item = sized((72, 72, 60, 55))
        item['options'][0]['text'] = '**`<strong>'+item['options'][0]['text']+'</strong>`**'
        self.assertFalse(imbalance(item))
        item['options'][0]['text'] = '  '+item['options'][0]['text']+'\n\t'
        self.assertFalse(imbalance(item))

    def test_short_terms_or_one_option_below_twenty_hangul_are_out_of_scope(self):
        self.assertFalse(imbalance(question(['포토몽타주', '레이요그램', '우연성의 법칙', '다다이즘'])))
        self.assertFalse(imbalance(sized((90, 72, 60, 19))))

    def test_low_hangul_ratio_is_out_of_scope_even_with_twenty_hangul(self):
        item = sized((90, 72, 60, 55))
        item['options'][2]['text'] = '가'*20+'EnglishText'*10
        self.assertFalse(imbalance(item))

    def test_formula_options_are_conservatively_out_of_scope(self):
        for formula in [r'\(F=ma\)', '∫₀¹x²dx', 'x²', 'πr', '2+3', 'x/2', '$x$']:
            with self.subTest(formula=formula):
                item = sized((90, 72, 60, 55))
                item['options'][1]['text'] += ' '+formula
                self.assertFalse(imbalance(item))

    def test_only_four_mcq_options_qualify_and_input_is_unchanged(self):
        item = sized((90, 72, 60, 55)); item['evidence'] = [{'quote': '원문 길이는 검사하지 않는다.'}]
        before = copy.deepcopy(item)
        self.assertTrue(imbalance(item)); self.assertEqual(item, before)
        for count in (0, 1, 2, 3):
            partial = copy.deepcopy(item); partial['options'] = partial['options'][:count]
            self.assertFalse(imbalance(partial))
        essay = copy.deepcopy(item); essay['type'] = 'essay'
        self.assertFalse(imbalance(essay))


if __name__ == '__main__':
    unittest.main()
