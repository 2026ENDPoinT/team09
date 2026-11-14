"""Tutor prose/code interleaving preserves source, escapes and streamed text."""
import itertools
import json
import unittest

from pdf_ai import tutor,partial_json_answer
from test_pdf_tutor_conversation_contract import StreamingProvider,response
from test_pdf_tutor_intent import document,semantic


class CodePresentationTests(unittest.TestCase):
    def delivered(self,text):
        p=StreamingProvider([response(text)],semantic('코드와 수식'));shown=[]
        result=tutor(document(),'주어진 표현을 설명해줘.',p,progress=shown.append)
        self.assertEqual(shown[-1],text)
        self.assertEqual(result['memory']['turns'][-1]['answer'],text)
        return result['answer']

    def test_explanation_and_coherent_excerpts_survive_stream_and_memory_in_both_modes(self):
        intro='핵심은 값을 바꾼 뒤 그 값을 출력하는 순서예요.'
        declaration='int count = 1;'
        update='++count;'
        output=r'std::cout << "\n안녕" << count;'
        # A full overview can be followed by genuinely useful repeated excerpts.
        code='int main() {\n\t'+declaration+'\n\t'+update+'\n\t'+output+'\n}'
        text=(intro+'\n\n전체 구조를 먼저 볼게요.\n\n```cpp\n'+code+'\n```\n\n'
              '값을 바꾸는 부분이에요.\n\n```cpp\n'+update+'\n```\n\n'
              '이제 값은 2예요. 다음은 출력 부분이에요.\n\n```cpp\n'+output+'\n```\n\n'
              '문자열의 줄바꿈과 숫자 2를 함께 출력해요.')
        for mode,shape in itertools.product(('quick','deep'),('direct','structured')):
            with self.subTest(mode=mode,shape=shape):
                development='값을 바꾸는 부분이에요.'+text.split('\n\n값을 바꾸는 부분이에요.',1)[1]
                value=response(text) if shape=='direct' else response('',teaching={
                    'lead':intro,'case':{'setup':'전체 구조를 먼저 볼게요.\n\n```cpp\n'+code+'\n```',
                                        'development':development}})
                p=StreamingProvider([value],semantic('출력 순서'));shown=[]
                result=tutor(document(),'변수 변경과 출력 부분을 코드 블록으로 나눠 설명해줘.',
                             p,mode=mode,progress=shown.append)
                self.assertEqual(result['answer'],text)
                self.assertEqual(shown[-1],text)
                self.assertTrue(all(text.startswith(part) for part in shown))
                self.assertEqual(result['memory']['turns'][-1]['answer'],text)
                self.assertEqual(result['answer'].count(code),1)
                self.assertEqual(result['answer'].count(output),2)
                self.assertEqual(len(p.calls),1)

    def test_code_literals_are_not_rewritten_by_prose_or_math_cleanup(self):
        examples=[r'```cpp\nstd::cout << "\n안녕";\n```',
                  r'```python\npattern = r"\lvert x\rvert"\n```',
                  r'~~~sql\nSELECT \'\\n안녕\';\n~~~',
                  r'`"\n안녕"`',r'`r"\lvert x\rvert"`']
        for encoded in examples:
            # Only the visible separators become newlines, never source escapes.
            text=encoded.replace('```cpp\\n','```cpp\n').replace('```python\\n','```python\n')
            text=text.replace('~~~sql\\n','~~~sql\n').replace('\\n```','\n```').replace('\\n~~~','\n~~~')
            with self.subTest(text=text):self.assertEqual(self.delivered(text),text)
        text='수식은 \\(\\lvert x\\rvert\\)예요.'
        self.assertEqual(self.delivered(text),text)

    def test_nested_fences_and_long_inline_delimiters_preserve_code(self):
        examples=[
            '설명 ``pattern = r"\\lvert `x`\\rvert"`` 이에요.',
            '- 소스 일부\n\n    ```python\n    pattern = r"\\lvert x\\rvert"\n    ```',
            '> ```python\n> pattern = r"\\lvert x\\rvert"\n> ```',
            '- ```cpp\n  std::cout << "\\n안녕";\n  ```',
            '````text\n문자열에 ```가 있어요.\n\\lvert x\\rvert\n````',
        ]
        for text in examples:
            with self.subTest(text=text):self.assertEqual(self.delivered(text),text)

    def test_incomplete_streaming_fences_preserve_every_completed_source_character(self):
        text='출력문을 볼게요.\n\n```cpp\nstd::cout << "\\n안녕";\n```\n\n줄바꿈 뒤 인사를 출력해요.'
        encoded=json.dumps({'answer':text},ensure_ascii=False)
        for end in range(len(encoded)+1):
            partial=partial_json_answer(encoded[:end])
            self.assertTrue(text.startswith(partial),repr(partial))

    def test_no_code_requests_and_non_code_explanations_stay_plain_prose(self):
        for mode,question,text in itertools.product(('quick','deep'),
                ('코드 없이 두 개념의 차이를 설명해줘.','분산과 표준편차가 어떻게 달라?'),
                ('핵심 관계를 말로 설명해요.','같은 예시를 작은 단계로 나누면 이해하기 쉬워요.')):
            p=StreamingProvider([response(text)],semantic('개념 비교'));shown=[]
            result=tutor(document(),question,p,mode=mode,progress=shown.append)
            self.assertEqual(result['answer'],text)
            self.assertNotIn('```',result['answer'])
            self.assertEqual(len(p.calls),1)


if __name__=='__main__':unittest.main()
