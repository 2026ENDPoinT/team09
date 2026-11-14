"""Offline regression tests for observed v99 serialization losses."""
import unittest
from pdf_new_concept_ver99_checks import repair_prose_serialization, prepare_response


class SerializationTests(unittest.TestCase):
    def test_paragraphs_and_math_restore_without_changing_symbols(self):
        self.assertEqual(repair_prose_serialization(r'첫 문단.\n\n식 $f(x)=Wx+b$와 $D$예요.'),
                         '첫 문단.\n\n식 '+r'\(f(x)=Wx+b\)와 \(D\)예요.')

    def test_existing_math_code_currency_and_words_are_preserved(self):
        text=(r'\(\nabla f\) $$a+b$$ \[x=y\] `print("\n\n$x$")` '
              r'가격 $5와 $10, $hello$, \$x\$.'+'\n```python\n'+r'print("\n\n$x$")'+'\n```')
        self.assertEqual(repair_prose_serialization(text),text)
        indented='    '+r'print("\n\n$x$")'+'\n'
        self.assertEqual(repair_prose_serialization(indented),indented)

    def test_flat_card_is_not_discarded_for_serialized_paragraph(self):
        card={'title':'이차원 충돌','blockIds':['p13'],
              'definition':'두 차원에서 일어나는 충돌이에요.',
              'explanation':r'두 방향의 운동량을 보존해요.\n\n조건에 따라 에너지도 보존해요.',
              'easyExplanation':r'가로와 세로를 나누어요.\n\n각 방향을 살펴보아요.'}
        value=prepare_response({'concepts':[card]})
        self.assertEqual(len(value['concepts']),1)
        self.assertIn('\n\n',value['concepts'][0]['explanation'])
        self.assertIn(r'\n\n',card['explanation'])  # No mutation of the raw cache.

    def test_repair_is_idempotent(self):
        text=r'식 $\mathbf{x}$와 $y=x^2$예요.\n\n다음 문단이에요.'
        once=repair_prose_serialization(text)
        self.assertEqual(repair_prose_serialization(once),once)

    def test_corrupt_redundant_unit_annotation_keeps_explicit_quantity(self):
        self.assertEqual(repair_prose_serialization('혈액 1마이크로리터(\x181 L)당 3,200~9,800개예요.'),
                         '혈액 1마이크로리터당 3,200~9,800개예요.')
        for text in ['혈액 (\x181 L)당 개수예요.','1마이크로리터(1 µL)예요.',
                     '`1마이크로리터(\x181 L)`',r'\(1 L\)']:
            self.assertEqual(repair_prose_serialization(text),text)

    def test_paired_soh_math_restores_delimiters_not_missing_content(self):
        text='급수 '+ '\x01'+r'\sum_{n=1}^{\infty}a_n'+'\x01예요.'
        self.assertEqual(repair_prose_serialization(text),'급수 '+r'\(\sum_{n=1}^{\infty}a_n\)'+'예요.')
        for text in ['\x01알 수 없는 한글\x01','식 \x01x+1', '`\x01x+1\x01`']:
            self.assertEqual(repair_prose_serialization(text),text)

    def test_fs_gs_wrapper_around_valid_math_is_redundant(self):
        math=r'\(s_n=\sum_{k=1}^{n}a_k\)'
        self.assertEqual(repair_prose_serialization('\x1c'+math+'\x1d'),math)
        for text in ['`\x1c'+math+'\x1d`','\x1c'+math, '\x1c알 수 없는 내용\x1d']:
            self.assertEqual(repair_prose_serialization(text),text)

    def test_internal_source_ids_never_become_a_visible_comparison_table(self):
        from pdf_new_concept_ver99_study import validate
        job={'id':'table','title':'분류','blocks':[
            {'id':key,'page':1,'text':'분류 설명','bbox':[0,0,1,1]}
            for key in ['v2p1f1','v2p1f2']]}
        doc={'documentId':'doc','pages':[{'label':'1'}]}
        raw={'concepts':[{'title':'분류','definition':'두 유형을 구분해요.',
            'explanation':'기능이 서로 달라요.','easyExplanation':'서로 다른 일을 맡아요.',
            'blockIds':['v2p1f1','v2p1f2']}],
            'tables':[{'conceptTitle':'분류','headers':['v2p1f1','v2p1f2'],
                'rows':[['v2p1f1','v2p1f1'],['v2p1f2','v2p1f2']],
                'blockIds':['v2p1f1','v2p1f2']}],
            'excludedBlocks':[],'uncertainBlocks':[]}
        unit=validate(raw,job,doc)
        self.assertEqual(unit['concepts'][0]['explanation'],'기능이 서로 달라요.')
        raw['tables'][0].update(headers=['유형','기능'],rows=[['A','생산'],['B','포식']])
        unit=validate(raw,job,doc)
        self.assertIn('| 유형 | 기능 |',unit['concepts'][0]['explanation'])

    def test_source_limitation_does_not_become_a_dummy_explanation(self):
        from pdf_new_concept_ver99_checks import learner_text
        text='자료는 두 기법을 소개하지만 각각의 제작 과정이나 시각적 효과는 설명하지 않아요.'
        self.assertEqual(learner_text(text)[0],'')
        condition='자료는 시간이 지나도 바뀌지 않아요.'
        self.assertEqual(learner_text(condition)[0],condition)
        for condition in ['각 자료는 만들어진 방법과 시점이 다를 수 있으므로, 숫자를 모으기만 해서는 같은 상황을 설명한다고 볼 수 없어요.',
                          '자료는 BERT가 모든 LLM의 직접적인 구조라고 설명하지는 않아요.',
                          '자료는 이산화탄소의 이동도 헤모글로빈의 기능으로 제시하지만 구체적 과정은 설명하지 않아요.']:
            self.assertEqual(learner_text(condition)[0],condition)


if __name__=='__main__':unittest.main()
