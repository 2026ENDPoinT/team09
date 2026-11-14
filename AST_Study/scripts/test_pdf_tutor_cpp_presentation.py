"""Local C++ answer presentation regressions; no network or code execution."""
import unittest

from pdf_tutor_cpp import local_code_answer, trace_program


def program(body):
    return '#include <iostream>\n#include <iomanip>\nint main() { ' + body + ' return 0; }'


class CppPresentationTests(unittest.TestCase):
    def test_explanation_precedes_output_and_only_relevant_source_is_excerpted(self):
        code = program('int a=7,b=2; int unused=99; '
                       'std::cout<<a/b<<"\\n"; '
                       'std::cout<<static_cast<double>(a)/b<<"\\n";')
        for mode in ('quick', 'deep'):
            with self.subTest(mode=mode):
                result = local_code_answer('아래 코드 출력 결과를 설명해줘.\n' + code, mode)
                answer = result['answer']
                self.assertFalse(answer.startswith('```'))
                self.assertLess(answer.index('계산값의 자료형'), answer.index('```text'))
                self.assertIn('```text\n3\n3.5\n```', answer)
                first = '```cpp\nint a=7,b=2;\nstd::cout<<a/b<<"\\n";\n```'
                second = '```cpp\nint a=7,b=2;\nstd::cout<<static_cast<double>(a)/b<<"\\n";\n```'
                self.assertIn(first, answer)
                self.assertIn(second, answer)
                self.assertEqual(answer.count('각 출력에 필요한 부분만 발췌'), 1)
                self.assertLess(answer.index(first), answer.index('계산값은 `3`인 `int`형'))
                self.assertLess(answer.index('계산값은 `3`인 `int`형'), answer.index(second))
                self.assertLess(answer.index(second), answer.index('계산값은 `3.5`인 `double`형'))
                for unrelated in ('#include', 'int main', 'unused', 'return 0'):
                    self.assertNotIn(unrelated, answer)
                self.assertEqual(result['computedCode'], trace_program(code))
                self.assertEqual(result['method'], 'local_cpp_arithmetic_trace')
                self.assertFalse(result['executed'])

    def test_format_setup_stays_with_the_output_it_affects(self):
        code = program('std::cout<<std::fixed<<std::setprecision(2); '
                       'std::cout<<3.0; std::cout<<std::defaultfloat; '
                       'std::cout<<" "<<3.0;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'deep')
        answer = result['answer']
        self.assertIn('```text\n3.00 3\n```', answer)
        self.assertIn('```cpp\nstd::cout<<std::fixed<<std::setprecision(2);\n'
                      'std::cout<<3.0;\n```', answer)
        self.assertIn('```cpp\nstd::cout<<std::fixed<<std::setprecision(2);\n'
                      'std::cout<<std::defaultfloat;\n'
                      'std::cout<<" "<<3.0;\n```', answer)
        self.assertEqual(result['computedCode'], trace_program(code))
        self.assertEqual([event['printed'] for event in result['computedCode']['events']], ['3.00', '3'])

    def test_persistent_format_setup_is_repeated_for_later_output_excerpts(self):
        code = program('std::cout<<std::fixed<<std::setprecision(2); '
                       'std::cout<<3.0; std::cout<<4.0;')
        for mode in ('quick', 'deep'):
            with self.subTest(mode=mode):
                result = local_code_answer('코드 출력을 설명해줘.\n' + code, mode)
                for value in ('3.0', '4.0'):
                    self.assertIn('```cpp\nstd::cout<<std::fixed<<std::setprecision(2);\n'
                                  'std::cout<<' + value + ';\n```', result['answer'])
                self.assertIn('```text\n3.004.00\n```', result['answer'])
                self.assertEqual(result['computedCode'], trace_program(code))

    def test_formats_set_in_an_earlier_output_are_explained_without_repeating_output(self):
        code = program('std::cout<<std::fixed<<std::setprecision(2)<<3.0; '
                       'std::cout<<4.0;')
        for mode in ('quick', 'deep'):
            with self.subTest(mode=mode):
                result = local_code_answer('코드 출력을 설명해줘.\n' + code, mode)
                answer = result['answer']
                self.assertEqual(answer.count('std::cout<<std::fixed<<std::setprecision(2)<<3.0;'), 1)
                self.assertIn('앞에서 적용한 출력 형식(`std::fixed`, `std::setprecision(2)`)은 '
                              '새 설정이 나올 때까지 유지돼요.', answer)
                self.assertIn('```cpp\nstd::cout<<4.0;\n```', answer)
                self.assertIn('```text\n3.004.00\n```', answer)
                self.assertEqual(result['computedCode'], trace_program(code))

    def test_a_later_format_override_keeps_only_the_other_inherited_settings(self):
        code = program('std::cout<<std::fixed<<std::setprecision(2)<<3.0; '
                       'std::cout<<std::defaultfloat<<4.0;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        self.assertIn('앞에서 적용한 출력 형식(`std::setprecision(2)`)은 '
                      '새 설정이 나올 때까지 유지돼요.', result['answer'])
        self.assertIn('```text\n3.004\n```', result['answer'])
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_multiple_expressions_keep_order_without_repeating_the_statement(self):
        code = program('std::cout<<7/2<<" "<<static_cast<double>(7)/2;')
        quick = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        deep = local_code_answer('코드 출력을 설명해줘.\n' + code, 'deep')
        snippet = 'std::cout<<7/2<<" "<<static_cast<double>(7)/2;'
        self.assertEqual(deep['answer'].count(snippet), 1)
        self.assertIn('- 1번째 식:', deep['answer'])
        self.assertIn('- 2번째 식:', deep['answer'])
        self.assertLess(deep['answer'].index('계산값은 `3`인 `int`형'),
                        deep['answer'].index('계산값은 `3.5`인 `double`형'))
        self.assertNotIn('7 / 2 = 3 (int)', quick['answer'])
        self.assertIn('7 / 2 = 3 (int)', deep['answer'])
        self.assertEqual(quick['computedCode'], deep['computedCode'])

    def test_string_only_output_has_an_accurate_intro_and_excerpt(self):
        code = program('int hello=7; std::cout<<"hello\\n";')
        result = local_code_answer('출력을 설명해줘.\n' + code, 'quick')
        self.assertTrue(result['answer'].startswith('문자열과 줄바꿈'))
        self.assertIn('```text\nhello\n```', result['answer'])
        self.assertIn('```cpp\nstd::cout<<"hello\\n";\n```', result['answer'])
        self.assertNotIn('int hello=7;', result['answer'])
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_initializer_dependencies_are_included_in_source_order(self):
        code = program('int seed=7; int unused=99; double numerator=seed+0.5; '
                       'int denominator=2; std::cout<<numerator/denominator;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        self.assertIn('```cpp\nint seed=7;\ndouble numerator=seed+0.5;\n'
                      'int denominator=2;\nstd::cout<<numerator/denominator;\n```', result['answer'])
        self.assertNotIn('unused', result['answer'])
        self.assertIn('```text\n3.75\n```', result['answer'])
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_comma_declarations_stay_intact_with_all_their_dependencies(self):
        code = program('int source=3; int first=7,second=source+first; '
                       'std::cout<<first; std::cout<<second;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        for output in ('first', 'second'):
            self.assertIn('```cpp\nint source=3;\nint first=7,second=source+first;\n'
                          'std::cout<<' + output + ';\n```', result['answer'])
        self.assertEqual(result['answer'].count('int source=3;'), 2)
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_declarations_and_format_setup_keep_their_original_order(self):
        code = program('std::cout<<std::fixed; double amount=7.0/2; int unused=9; '
                       'std::cout<<std::setprecision(2)<<amount;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        self.assertIn('```cpp\nstd::cout<<std::fixed;\ndouble amount=7.0/2;\n'
                      'std::cout<<std::setprecision(2)<<amount;\n```', result['answer'])
        self.assertNotIn('unused', result['answer'])
        self.assertIn('```text\n3.50\n```', result['answer'])
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_only_dependencies_of_each_output_are_excerpted(self):
        code = program('int a=7; int b=2; int e3=9; '
                       'std::cout<<a; std::cout<<b; std::cout<<1e3;')
        result = local_code_answer('코드 출력을 설명해줘.\n' + code, 'quick')
        self.assertIn('```cpp\nint a=7;\nstd::cout<<a;\n```', result['answer'])
        self.assertIn('```cpp\nint b=2;\nstd::cout<<b;\n```', result['answer'])
        self.assertIn('```cpp\nstd::cout<<1e3;\n```', result['answer'])
        self.assertNotIn('int e3=9;', result['answer'])
        self.assertEqual(result['computedCode'], trace_program(code))

    def test_explicit_code_presentation_requests_use_the_normal_mentor(self):
        code = program('std::cout<<3;')
        requests = ('출력을 설명하고 전체 코드를 보여줘.',
                    '출력 예제는 완전한 소스 코드로 보여줘.',
                    '출력 코드를 코드만 보여줘.',
                    '코드 없이 출력 결과를 설명해줘.',
                    '코드는 빼고 출력 결과를 설명해줘.',
                    '코드 블록 제외하고 출력 결과를 설명해줘.',
                    '코드를 전부 보여주면서 출력 결과를 설명해줘.',
                    '코드를 생략하고 출력 결과를 설명해줘.',
                    '소스를 모두 보여주면서 출력 결과를 설명해줘.',
                    '소스는 제외하고 출력 결과를 설명해줘.',
                    'Explain the output with the full code.',
                    'Explain the output; code only.',
                    'Explain the output with no code.',
                    'Omit the source and explain the output.')
        for request in requests:
            with self.subTest(request=request):
                self.assertIsNone(local_code_answer(request + '\n' + code, 'deep'))

    def test_simple_output_requests_and_detail_levels_keep_the_local_route(self):
        code = program('int a=7,b=2; std::cout<<a/b;')
        requests = ('출력 결과',
                    '아래 코드 출력 결과를 설명해줘.',
                    '이 코드의 출력 결과를 간단히 설명해줘.',
                    '다음 프로그램의 출력 결과를 상세하게 알려주세요.',
                    '코드 출력을 자세히 설명해주세요.',
                    '이 코드의 실행 결과를 설명해줘.',
                    '출력 결과가 뭐야?',
                    '출력해줘.',
                    'Explain the output.',
                    'Briefly explain the output of this C++ code.',
                    'Explain the output in detail.',
                    'What is the output of this program?')
        for mode in ('quick', 'deep'):
            for request in requests:
                with self.subTest(mode=mode, request=request):
                    result = local_code_answer(request + '\n' + code, mode)
                    self.assertIsNotNone(result)
                    self.assertEqual(result['computedCode'], trace_program(code))

    def test_unknown_wording_and_extra_presentation_intent_use_the_normal_mentor(self):
        code = program('std::cout<<3;')
        requests = ('코드는 보여주지 말고 출력 결과만 설명해줘.',
                    '코드를 적지 말고 출력 결과만 설명해줘.',
                    '출력 결과를 설명하고 전체 프로그램을 보여줘.',
                    '출력 결과를 한 문장으로 요약해줘.',
                    '출력 결과를 그림으로 설명해줘.',
                    '출력 결과를 영어로 설명해줘.',
                    '내 스타일대로 출력 결과를 설명해줘.',
                    'Explain the output without displaying the source.',
                    'Explain the output and show the complete program.')
        for mode in ('quick', 'deep'):
            for request in requests:
                with self.subTest(mode=mode, request=request):
                    self.assertIsNone(local_code_answer(request + '\n' + code, mode))

    def test_presentation_words_inside_source_do_not_change_routing(self):
        code = program('std::cout<<"전체 코드 code only";')
        question = '코드 출력을 설명해줘.\n```cpp\n' + code + '\n```'
        result = local_code_answer(question, 'deep')
        self.assertIsNotNone(result)
        self.assertEqual(result['computedCode']['stdout'], '전체 코드 code only')


if __name__ == '__main__':
    unittest.main()
