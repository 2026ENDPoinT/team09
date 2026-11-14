"""Rendering must not rewrite the received answer or stored dialogue."""
import unittest
from pdf_ai import tutor
from test_pdf_tutor_final_answer import Provider,reply
from test_pdf_tutor_intent import document,semantic

class TutorMathBoundaryTests(unittest.TestCase):
    def assert_delivered(self,text):
        for mode in ('quick','deep'):
            provider=Provider([reply(text)],semantic('수식'));shown=[]
            result=tutor(document(),'이 표현을 설명해줘.',provider,mode=mode,progress=shown.append)
            self.assertEqual(result['answer'],text)
            self.assertEqual(result['memory']['turns'][-1]['answer'],text)
            self.assertEqual(shown[-1],text)
            self.assertTrue(all(text.startswith(part) for part in shown))
            self.assertEqual(len(provider.calls),1)

    def test_math_notation_and_control_boundaries_are_not_reconstructed(self):
        for formula in [r'\lambda=\alpha x',r'\frac{2L}{3}','dx','L/2']:
            for text in ['값은 \x1c('+formula+')\x1d예요.','값은 \x00'+formula+'\x00예요.']:
                self.assert_delivered(text)

    def test_missing_formula_is_never_invented_or_removed(self):
        self.assert_delivered('보통 \x1b[0m로 나타내며, 균일하면 \x1b[0m이에요.')

    def test_code_and_valid_math_keep_literal_escapes(self):
        for text in [r'선밀도는 \(\lambda=M/L\)예요.',r'\[x=\frac{2L}{3}\]',
                     '$x$ 및 $$M/L$$',r'수식은 \(\lvert x\rvert\)예요.',
                     '가격은 $5이고 다음은 $10이에요.',r'`\frac{a}{b}`',
                     '```python\nx = 1\n```','~~~text\nx=1\n~~~']:
            self.assert_delivered(text)

    def test_code_and_incomplete_math_like_prose_are_not_reinterpreted(self):
        for text in ['`\x00x=1\x00`','```text\n\x00x=1\x00\n```',
                     '\x00일반 설명\x00','\x00x={1\x00','\x00x=1','\x1c(x=1)',
                     '\x00x=1\n문장\x00']:
            self.assert_delivered(text)

    def test_existing_dialogue_is_not_cleaned_again_for_the_next_request(self):
        previous='네, 값은 \\(\\lvert x\\rvert\\)예요. 【Q2】'
        memory={'documentId':'doc','turns':[{'question':'수식이 맞아?','answer':previous}]}
        provider=Provider([reply('예. 같은 수식이에요.')],semantic('수식'))
        result=tutor(document(),'그럼 같은 수식인 거지?',provider,memory=memory)
        self.assertEqual(provider.calls[0][0]['recentConversation'][0]['answer'],previous)
        self.assertEqual(result['memory']['turns'][0]['answer'],previous)

    def test_layout_whitespace_remains_in_body_and_memory(self):
        self.assert_delivered('  네, 이 조건에서는 맞아요.\n\n')

if __name__=='__main__':unittest.main()
