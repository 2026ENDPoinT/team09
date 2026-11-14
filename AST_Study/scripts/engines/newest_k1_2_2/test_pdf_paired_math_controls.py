"""A real vector PDF response lost valid coordinate definitions to broken delimiters."""
import unittest
from pdf_new_concept_ver99_checks import repair_paired_fs_gs_math,repair_balanced_esc_math_envelopes
import pdf_new_concept_ver99_study as study


class PairedMathControlTests(unittest.TestCase):
    def test_balanced_esc_envelope_preserves_complete_inline_math_byte_exact(self):
        expressions=(r'\(\sum_{n=1}^{\infty}\frac{1}{n^p}\)',
                     r'\(T_3(x)=1+x+\frac{x^2}{2!}+\frac{x^3}{3!}\)',
                     r'\(p\leq 1\)')
        value='그대로 '+', '.join('\x1b['+x+'\x1b]' for x in expressions)+'예요.'
        expected='그대로 '+', '.join(expressions)+'예요.'
        self.assertEqual(repair_balanced_esc_math_envelopes(value),expected)
        self.assertEqual(repair_balanced_esc_math_envelopes(expected),expected)

    def test_esc_envelope_does_not_infer_missing_symbols_or_edit_code(self):
        inline='\x1b['+r'\(x=1\)'+'\x1b]'
        untouched=('`'+inline+'`','```text\n'+inline+'\n```',
                   '~~~text\n'+inline+'\n~~~','    '+inline+'\n',
                   '```text\n'+inline, '~~~text\n'+inline,
                   '\x1b[1,∞)', '\x1b['+r'\(x=1\)',
                   r'\(x=1\)'+'\x1b]', '\x1b[한국어\x1b]',
                   '\x1b[$$x=1$$\x1b]', '\x1b['+r'\(\)'+'\x1b]',
                   '\x1b['+r'\(x=\(y\)\)'+'\x1b]',
                   r'\((-'+ '\x1e'+r',\infty)\)', r'\(n\to'+'\t'+r'ypo\infty\)')
        for value in untouched:
            with self.subTest(value=repr(value)):
                self.assertEqual(repair_balanced_esc_math_envelopes(value),value)

    def test_esc_serialization_recovery_keeps_arithmetic_and_source_guards(self):
        b={'id':'a','page':1,'kind':'text','bbox':[0,0,1,1],
           'hasVisual':False,'text':'등식과 부등식','planRole':'teaching'}
        def raw(explanation,refs=None):
            return {'concepts':[{'title':'계산','segments':[
                {'kind':'definition','text':'값은 \x1b['+r'\(x=4\)'+'\x1b]예요.','blockIds':['a']},
                {'kind':'explanation','text':explanation,'blockIds':refs or ['a']},
                {'kind':'easyExplanation','text':'수는 \x1b['+r'\(4\)'+'\x1b]예요.','blockIds':['a']}]}],
                'uncertainBlocks':[],'excludedBlocks':[]}
        job={'id':'u','title':'계산','blocks':[b]};doc={'documentId':'doc','pages':[{'label':'1'}]}
        good=study.validate(raw('계산은 \x1b['+r'\(2+2=4\)'+'\x1b]예요.'),job,doc)
        self.assertIn(r'\(2+2=4\)',good['summary']['body'])
        self.assertEqual(good['coverage'][0]['state'],'summarized')
        bad=study.validate(raw('계산은 \x1b['+r'\(2+2=5\)'+'\x1b]예요.'),job,doc)
        self.assertNotIn('2+2=5',bad['summary']['body'])
        self.assertEqual(bad['coverage'][0]['state'],'needs_review')
        with self.assertRaisesRegex(ValueError,'원문 영역 밖'):
            study.validate(raw('다른 출처예요.',['unknown']),job,doc)

    def test_observed_literal_and_actual_endpoints_preserve_exact_math(self):
        value='점을 \x1c(x,y,z)\\u001d로 쓰고 \x1cz=0\x1d은 평면이에요.'
        self.assertEqual(repair_paired_fs_gs_math(value),r'점을 \((x,y,z)\)로 쓰고 \(z=0\)은 평면이에요.')
        self.assertEqual(repair_paired_fs_gs_math(r'\u001c\mathbb{R}^3\u001d'),r'\(\mathbb{R}^3\)')

    def test_code_and_unmatched_or_ambiguous_controls_are_not_rewritten(self):
        for text in ['`\x1cx\x1d`','```text\n\x1cx\x1d\n```','\x1cx','\x1c한국어\x1d','\x1cword\x1d',
                     '\x1cint *p;\x1d','\x1cnew int[5]\x1d']:
            self.assertEqual(repair_paired_fs_gs_math(text),text)

    def test_valid_coordinate_concept_recovered_without_model_call(self):
        b={'id':'a','page':1,'kind':'page','bbox':[0,0,1,1],'hasVisual':True,'text':'좌표계','planRole':'teaching'}
        def raw(explanation):return {'concepts':[{'title':'삼차원 좌표계','segments':[
            {'kind':'definition','text':'점을 \x1c(x,y,z)\\u001d로 나타내요.','blockIds':['a']},
            {'kind':'explanation','text':explanation,'blockIds':['a']},
            {'kind':'easyExplanation','text':'높이가 0이면 \x1cz=0\x1d인 평면이에요.','blockIds':['a']}]}],
            'uncertainBlocks':[],'excludedBlocks':[]}
        job={'id':'u','title':'좌표계','blocks':[b]};doc={'documentId':'doc','pages':[{'label':'1'}]}
        value=study.validate(raw('좌표는 \x1cx\x1d, \x1cy\x1d, \x1cz\x1d 순서로 읽어요.'),job,doc)
        self.assertEqual(len(value['concepts']),1)
        self.assertEqual(value['coverage'][0]['state'],'summarized')
        self.assertIn(r'\((x,y,z)\)',value['summary']['body'])
        # A real arithmetic error remains rejected after delimiter restoration.
        invalid=study.validate(raw('계산은 \x1c2+2=5\x1d예요.'),job,doc)
        self.assertEqual(invalid['coverage'][0]['state'],'needs_review')
        self.assertNotIn('2+2=5',invalid['summary']['body'])
        self.assertIn(r'\((x,y,z)\)',invalid['summary']['body'])
        self.assertTrue(invalid['summary']['parts'][0]['partialSupported'])

    def test_partial_diagram_retains_supported_definition_but_does_not_fill_blank_formula(self):
        a={'id':'diagram','page':1,'kind':'visual','hasVisual':True,'text':'',
           'bbox':[.1,.1,.8,.5],'planRole':'teaching'}
        b={'id':'blank','page':1,'kind':'text','hasVisual':False,'text':'|a| =',
           'bbox':[.1,.6,.3,.7],'planRole':'teaching'}
        raw={'concepts':[{'title':'벡터의 성분과 크기','segments':[
            {'kind':'definition','text':'벡터의 성분은 각 축 방향의 수예요.','blockIds':['diagram']},
            {'kind':'explanation','text':'자료에서 공식은 확인할 수 없어요.','blockIds':['blank']},
            {'kind':'easyExplanation','text':'가로와 세로, 높이의 수로 위치를 알려줘요.','blockIds':['diagram']}]}],
             'uncertainBlocks':[{'blockId':'blank','reason':'크기 공식의 오른쪽이 빈칸이에요.'}]}
        value=study.validate(raw,{'id':'u','title':'벡터','blocks':[a,b]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(len(value['concepts']),1)
        self.assertIn('각 축 방향의 수',value['summary']['body'])
        self.assertNotIn('확인할 수',value['summary']['body'])
        self.assertEqual(value['concepts'][0]['explanation'],'')
        self.assertTrue(value['summary']['parts'][0]['partialSupported'])
        self.assertTrue(all(c['state']=='needs_review' for c in value['coverage']))

    def test_untrusted_partial_marker_cannot_bypass_flat_response_checks(self):
        raw={'concepts':[{'title':'제목','definition':'정의예요.','explanation':'',
            'easyExplanation':'','blockIds':['a'],'_partialSupported':True}]}
        b={'id':'a','page':1,'kind':'page','bbox':[0,0,1,1],'hasVisual':True,'text':''}
        result=study.validate(raw,{'id':'u','title':'제목','blocks':[b]},
            {'documentId':'doc','pages':[{'label':'1'}]})
        self.assertEqual(result['concepts'],[])


if __name__=='__main__':unittest.main()
