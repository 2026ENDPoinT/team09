"""Request/assembly and exact output regressions. No network or executable user code."""
import unittest
from unittest.mock import Mock
from pdf_tutor_cpp import trace_program, local_code_answer, Unsupported
from pdf_tutor_delivery import learning_task, assemble_teaching, worked_format
from pdf_ai import tutor
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import semantic


def program(body):
    return '#include <iostream>\n#include <iomanip>\nint main() { ' + body + ' }'


class CppTraceTests(unittest.TestCase):
    def test_exact_output_values_and_format_are_separate_in_both_modes(self):
        code=program('int a=7,b=2; std::cout<<a/b<<"\\n"; '
            'std::cout<<static_cast<double>(a)/b<<"\\n"; '
            'std::cout<<static_cast<double>(a/b)<<"\\n";')
        provider=Mock();provider.model='unused'
        for mode in ('quick','deep'):
            shown=[];result=tutor({'documentId':'test','pages':[{}],'chunks':[]},
                '아래 코드 출력 결과를 설명해줘.\n'+code,provider,mode=mode,progress=shown.append)
            self.assertEqual(result['computedCode']['stdout'],'3\n3.5\n3\n')
            self.assertIn('```text\n3\n3.5\n3\n```',result['answer'])
            self.assertEqual(result['computedCode']['events'][-1]['value'],'3.0')
            self.assertEqual(result['computedCode']['events'][-1]['printed'],'3')
            self.assertFalse(result['executed']);self.assertEqual(shown[-1],result['answer'])
            self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        provider.complete.assert_not_called();provider.plan_tutor.assert_not_called()

    def test_variants_not_just_the_observed_numbers(self):
        for a,b in [(8,3),(-7,2),(7,-2),(-7,-2),(0,9),(100,7)]:
            with self.subTest(a=a,b=b):
                row=trace_program(program(f'int a={a},b={b};std::cout<<a/b<<" "<<a%b;'))
                quotient=int(a/b);self.assertEqual(row['stdout'],f'{quotient} {a-quotient*b}')

    def test_explicit_formatting_and_format_state(self):
        rows=[('std::cout<<3.0;', '3'),
              ('std::cout<<std::fixed<<std::setprecision(2)<<3.0;', '3.00'),
              ('std::cout<<std::showpoint<<3.0;', '3.00000'),
              ('std::cout<<std::scientific<<std::setprecision(2)<<3.0;', '3.00e+00'),
              ('std::cout<<std::fixed<<std::setprecision(1)<<3.0<<" "<<std::defaultfloat<<3.0;', '3.0 3'),
              ('double a=7.0/2;int b=7.0/2;std::cout<<a<<" "<<b;', '3.5 3'),
              ('std::cout<<-7/2<<" "<<-7%2<<std::endl;', '-3 -1\n')]
        for body,expected in rows:
            with self.subTest(body=body):self.assertEqual(trace_program(program(body))['stdout'],expected)

    def test_unsupported_programs_never_get_a_partial_computed_answer(self):
        for body in ['int a=1/0;std::cout<<a;', 'std::cout<<2147483647+1;',
                     'int a=7; a=9;std::cout<<a;', 'for(int i=0;i<3;i++){std::cout<<i;}',
                     'std::cout<<unknown;', 'int a=01;std::cout<<a;',
                     'int double=3;std::cout<<double;', 'int and=3;std::cout<<and;', 'return 0;std::cout<<3;',
                     'std::cout<<"ok";system("echo nope");', 'std::cout<<3.0%2;',
                     'std::cout<<'+'('*50+'3'+')'*50+';']:
            with self.subTest(body=body):
                self.assertIsNone(local_code_answer('코드 출력을 설명해줘.\n'+program(body),'deep'))
        self.assertIsNone(local_code_answer('코드 출력과 그리고 네임스페이스도 설명해줘.\n'+program('std::cout<<3;'),'deep'))


class TeachingContractTests(unittest.TestCase):
    def test_examples_are_optional_and_legacy_schema_remains_readable(self):
        task=learning_task('기계공학 전공 학생이야. 운동량 보존을 설명해줘.','deep',{'subject':'운동량'})
        self.assertEqual(task['major'],'기계공학');self.assertEqual(task['responseContract'],'direct')
        schema=worked_format()['json_schema']['schema']
        self.assertIn('teaching',schema['required'])
        self.assertEqual(schema['properties']['answer']['enum'],[''])
        self.assertNotIn('connection',schema['properties']['teaching']['properties']['case']['properties'])

    def test_solution_and_simple_confirmation_do_not_force_extra_examples(self):
        for question in ['2kg 물체가 3m/s로 움직일 때 운동량을 구해줘.','운동량은 보존되는 게 맞지?']:
            self.assertEqual(learning_task(question,'deep',{})['responseContract'],'direct')

    def test_structured_response_allows_streaming_and_enters_memory(self):
        response=reply('', teaching={'lead':'내부 힘은 전체 운동량을 바꾸지 않아요.',
            'case':{'setup':'가상의 두 운반차가 마찰 없는 레일에서 충돌한다고 해볼게요.',
                    'development':'2kg 운반차가 잃은 운동량 4kg·m/s를 다른 운반차가 얻어요.',
                    'connection':'두 변화량을 합하면 0이어서 전체 운동량은 같아요.'}})
        p=Provider([response],semantic('운동량'));shown=[]
        result=tutor({'documentId':'doc','pages':[{}],'chunks':[]},'기계공학 전공인데 운동량 보존을 설명해줘.',p,mode='deep',progress=shown.append)
        self.assertEqual(result['answer'],assemble_teaching(response)['answer'])
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertEqual(shown[-1],result['answer']);self.assertEqual(len(p.calls),1)
        payload,options=p.calls[0]
        self.assertEqual(payload['learningTask']['major'],'기계공학')
        self.assertNotIn('response_format',options)
        self.assertTrue(callable(options['on_delta']))

    def test_social_reply_in_deep_mode_does_not_require_a_worked_case(self):
        response=reply('', teaching={'lead':'이해됐다니 기뻐요.',
            'case':{'setup':'','development':''}})
        response.update(responseKind='social', claimVerdict='none', requiresPdfEvidence=False)
        p=Provider([response],semantic('이전 학습 내용'));shown=[]
        result=tutor({'documentId':'doc','pages':[{}],'chunks':[]},
            'ㅇㅋㅇㅋ완전히 이해했어 고맙다잉',p,mode='deep',progress=shown.append)
        self.assertEqual(result['kind'],'social')
        self.assertEqual(result['answer'],'이해됐다니 기뻐요.')
        self.assertEqual(result['memory']['turns'][-1]['answer'],result['answer'])
        self.assertEqual(len(p.calls),1)

    def test_social_contract_is_semantic_not_a_specific_phrase(self):
        for lead in ('반가워요!', '잠깐 쉬었다 이어가요.', '도움이 됐다니 기뻐요.'):
            value={'responseKind':'social','teaching':{'lead':lead,'case':{}}}
            self.assertEqual(assemble_teaching(value)['answer'],lead)

    def test_optional_teaching_fields_do_not_erase_received_prose(self):
        for fields in ({'responseKind':'general'},
                       {'responseKind':'social','requiresPdfEvidence':True},
                       {'responseKind':'social','claimVerdict':'confirmed'},
                       {'responseKind':'social','evidence':[{'sourceId':'s','quoteId':'q'}]},
                       {'responseKind':'social','needsExternalSearch':True}):
            with self.subTest(fields=fields):
                self.assertEqual(assemble_teaching({**fields,'teaching':{'lead':'실제 답변','case':{}}})['answer'],
                                 '실제 답변')

    def test_missing_information_does_not_force_an_invented_case(self):
        value={'needsClarification':True,'teaching':{'lead':'어떤 두 물체를 뜻하나요?','case':{}}}
        self.assertEqual(assemble_teaching(value)['answer'],'어떤 두 물체를 뜻하나요?')

    def test_new_case_contract_renders_three_parts_without_an_extra_conclusion(self):
        value={'answer':'','teaching':{'lead':'핵심 답변',
            'case':{'setup':'구체적인 초기 조건','development':'변화와 결과 및 그 이유'}}}
        self.assertEqual(assemble_teaching(value)['answer'],'핵심 답변\n\n구체적인 초기 조건\n\n변화와 결과 및 그 이유')

    def test_unknown_major_is_not_invented(self):
        task=learning_task('수열의 수렴을 설명해줘.','deep',{'subject':'수열'})
        self.assertIsNone(task['major'])
        self.assertEqual(task['subject'],'수열')

    def test_unsupported_cpp_keeps_the_normal_single_answer_route(self):
        p=Provider([reply('0, 1, 2가 순서대로 출력돼요.')],semantic('C++ 반복문'))
        q='출력을 설명해줘.\n'+program('for(int i=0;i<3;++i){std::cout<<i;}')
        result=tutor({'documentId':'doc','pages':[{}],'chunks':[]},q,p,mode='deep')
        self.assertEqual(len(p.calls),1)
        self.assertEqual(p.calls[0][0]['learningTask']['kind'],'code_output')
        self.assertNotIn('computedCode',result)


if __name__=='__main__':unittest.main()
