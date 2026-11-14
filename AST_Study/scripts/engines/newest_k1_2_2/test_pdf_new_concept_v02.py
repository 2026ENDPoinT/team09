"""ver.02 regression gates: actual source layout + deterministic output failures."""
import json
import tempfile
import unittest
from pathlib import Path
import pdf_new_concept_v02_regions as layout
import pdf_new_concept_ver99_study as study
from pdf_new_concept_ver99_checks import learner_text,math_semantics,prepare_response,numeric

BASE=Path('build/calculus-fiveway-20261011/runs/new-concept-v1')
class Ver02Tests(unittest.TestCase):
    def test_adjacent_duplicate_titles_keep_conditions_and_evidence_once(self):
        def unit(page,title,condition):
            common={'evidence':[{'page':page}],'visualPages':[page],'standardKnowledgeUsed':False,'easyExplanation':'얇은 조각을 더해요.'}
            return {'summary':{'parts':[{'title':title,'body':'정의예요.\n\n'+condition,**common}]},
                    'concepts':[{'name':title,'definition':'정의예요.','explanation':condition,**common}]}
        original={0:unit(23,'일의 정적분','힘의 방향을 고려해요.'),1:unit(24,'일의 정적분','위치별 힘을 더해요.'),2:unit(90,'일의 정적분','다른 장이에요.')}
        value=study.consolidate_entries(original)
        self.assertEqual(len(original[1]['concepts']),1)
        self.assertEqual(value[1]['concepts'],[])
        first=value[0]['concepts'][0]
        self.assertEqual(first['visualPages'],[23,24]);self.assertIn('방향',first['explanation']);self.assertIn('위치별',first['explanation'])
        self.assertEqual(first['easyExplanation'],'얇은 조각을 더해요.')
        self.assertEqual(len(value[2]['concepts']),1)
    def test_adjacent_easy_explanations_drop_only_identical_analogy_opening(self):
        def unit(page,easy):
            common={'evidence':[{'page':page}],'visualPages':[page],
                    'standardKnowledgeUsed':False,'easyExplanation':easy}
            return {'summary':{'parts':[{'title':'깊이 우선 탐색','body':'정의예요.\n\n절차예요.',**common}]},
                    'concepts':[{'name':'깊이 우선 탐색','definition':'정의예요.',
                                 'explanation':'절차예요.',**common}]}
        value=study.consolidate_entries({0:unit(1,'갈림길이 있는 길을 살핀다고 생각해 보세요. 스택을 써요.'),
                                         1:unit(2,'갈림길이 있는 길을 살핀다고 생각해 보세요. A에서 B로 가요.')})
        easy=value[0]['concepts'][0]['easyExplanation']
        self.assertEqual(easy.count('갈림길이 있는 길'),1)
        self.assertIn('A에서 B로 가요.',easy)
        value=study.consolidate_entries({0:unit(1,'속도가 10보다 클 때만 적용해요.'),
                                         1:unit(2,'속도가 10보다 작을 때만 적용해요.')})
        easy=value[0]['concepts'][0]['easyExplanation']
        self.assertIn('클 때',easy);self.assertIn('작을 때',easy)
    def test_math_delimiters_preserve_calculus_code_and_conditions(self):
        from pdf_new_concept_v02_math import format_math
        text=r'일은 W=\int_a^b kx\,dx로 구해요. Δx가 작아져요. 구간은 0.05≤x≤0.08이에요.'
        value=format_math(text)
        self.assertIn(r'\(W=\int_a^b kx\,dx\)',value)
        self.assertIn(r'\(Δx\)',value)
        self.assertEqual(format_math('W=∫ₐᵇ kx dx예요.'),r'\(W=∫ₐᵇ kx dx\)예요.')
        for code in [r'`W=\int_a^b kx\,dx`','```python\nvalue = "x²"\n```',r'\(W=\int_a^b kx\,dx\)']:
            self.assertEqual(format_math(code),code)
        self.assertEqual(format_math('$100을 받아 $110을 갚아요.'),'$100을 받아 $110을 갚아요.')
        self.assertEqual(format_math(value),value)
    def test_limitation_sentence_only_and_subject_conditions_retained(self):
        text='힘과 이동 방향이 같고 힘이 일정하면 W=Fd예요. 다만 이 자료에는 제목만 있어서 계산법을 알 수 없어요. 에너지는 보존돼요.'
        value,removed=learner_text(text)
        self.assertIn('W=Fd',value);self.assertIn('에너지는',value);self.assertNotIn('계산법',value);self.assertEqual(len(removed),1)
        value,_=learner_text('다만 힘이 일정할 때만 이 식을 쓸 수 있어요.')
        self.assertIn('힘이 일정',value)
    def test_narrow_math_check_rejects_wrong_integral_without_touching_good_one(self):
        wrong=r'$$\int_{0}^{8} \pi y^{2/3}\,dy = \frac{48\pi}{5}$$'
        good=wrong.replace('48','96')
        self.assertIn('monomial_integral',math_semantics(wrong));self.assertEqual(math_semantics(good),[])
        self.assertIn('numeric_equality',math_semantics(r'\(2*3=7\)'))
        self.assertEqual(math_semantics(r'\(F=ma\)'),[])
        with self.assertRaises((ValueError,SyntaxError)):numeric('__import__("os").system("true")')
    def test_invalid_entry_does_not_abort_other_concepts(self):
        a={'title':'개념','definition':'뜻이에요.','explanation':'원리예요.','easyExplanation':'쉬운 설명이에요.','blockIds':['a']}
        b={**a,'explanation':'잘못된 \x00 수식','blockIds':['b']}
        v=prepare_response({'concepts':[a,b]})
        self.assertEqual(len(v['concepts']),1);self.assertEqual(v['uncertainBlocks'][0]['blockId'],'b')
    def test_empty_math_is_flagged_without_aborting_other_paid_concepts(self):
        for text in ['$$$$', r'\(\)', r'\[ \]']:
            self.assertIn('empty_math',math_semantics(text))
        good={'title':'내적','definition':'두 벡터로 스칼라를 구해요.',
              'explanation':'성분별 곱을 더해요.','easyExplanation':'각 성분을 짝지어요.',
              'blockIds':['a']}
        bad={'title':'손상된 식','segments':[
            {'kind':kind,'text':text,'blockIds':['b']} for kind,text in [
                ('definition','성분 표현이에요.'),
                ('explanation','내적은\n\n$$\x1b[?]$$\n\n이에요.'),
                ('easyExplanation','각 성분을 짝지어요.')]]}
        result=prepare_response({'concepts':[good,bad]})
        self.assertTrue(any(c['title']=='내적' for c in result['concepts']))
        self.assertTrue(any(c['blockId']=='b' for c in result['uncertainBlocks']))
        self.assertTrue(any(c['reason']=='invalid_or_empty_supported_paragraph'
                            for c in result['processingDiagnostics']))
    def test_pointer_code_controls_restore_the_saved_teaching(self):
        entry={'title':'포인터와 주소 연산자',
               'definition':'주소 연산자 \x1c&\x1c는 변수의 주소를 구해요.',
               'explanation':'\x1cptr = &pooh;\x1c는 주소를 \x1cptr\x1c에 저장해요.',
               'easyExplanation':'\x1c&pooh\x1c는 위치를 뜻해요.','blockIds':['p30']}
        value=prepare_response({'concepts':[entry]})
        self.assertEqual(len(value['concepts']),1)
        self.assertEqual(value['uncertainBlocks'],[])
        self.assertIn('`ptr = &pooh;`',value['concepts'][0]['explanation'])
    def test_unambiguous_plural_examples_correct_conflicting_rule(self):
        entry={'title':'강세 표시 모음이 있는 명사의 복수형',
               'definition':'단수형이 모음으로 끝나고 강세 표시가 있는 명사는 -s를 붙여요.',
               'explanation':'baúl은 baúles, país는 países가 돼요.',
               'easyExplanation':'baúl에 -es를 붙이면 baúles가 돼요.','blockIds':['p27']}
        value=prepare_response({'concepts':[entry]})
        self.assertIn('자음으로 끝나고',value['concepts'][0]['definition'])
        self.assertIn('-es를 붙',value['concepts'][0]['definition'])
        different={**entry,'explanation':'baúl은 baúles가 돼요.'}
        self.assertIn('모음으로 끝나고',prepare_response({'concepts':[different]})['concepts'][0]['definition'])
    def test_empty_text_visual_is_never_silently_excluded(self):
        block={'id':'p38','page':1,'bbox':[0,0,1,1],'kind':'page','text':'','hasVisual':True}
        job={'id':'visual','title':'자료의 종류','blocks':[block]}
        document={'documentId':'example','pages':[{'label':'1'}]}
        raw={'concepts':[],'excludedBlocks':[{'blockId':'p38','reason':'내용이 없는 페이지 블록이에요.'}]}
        value=study.validate(raw,job,document)
        self.assertEqual(value['coverage'][0]['state'],'needs_review')
    def test_image_only_slide_leads_next_related_teaching_without_extra_job(self):
        def block(number,page,kind,text,heading):
            return {'id':number,'page':page,'kind':kind,'text':text,'zone':0,
                    'bbox':[0,0,1,1],'planRole':'teaching','headingTitle':heading,
                    'hasVisual':kind=='page','visualOnly':kind=='page'}
        groups=[{'title':'데이터의 의미','blocks':[
            block('text',36,'text','관측값은 데이터예요.','Data'),
            block('diagram',38,'page','','Data')]},
            {'title':'범주형 데이터의 표현','blocks':[
                block('next',39,'text','범주형 값은 숫자로 표현할 수 있어요.','data')]}]
        moved,pages=study.lead_with_visual_page(groups)
        self.assertEqual(pages,[38]);self.assertEqual(len(study.jobs_for(moved)),len(study.jobs_for(groups)))
        self.assertEqual([b['id'] for b in moved[1]['blocks']],['diagram','next'])
        self.assertEqual([b['id'] for b in groups[0]['blocks']],['text','diagram'])
        payload=study.teaching_payload(study.jobs_for(moved)[1],[],{},[])
        self.assertEqual(payload['blocks'][0]['kind'],'visual')
        self.assertTrue(payload['blocks'][0]['hasVisual'])
        self.assertNotIn('zone',payload['blocks'][0])
    def test_grounded_sequence_attaches_to_summary_without_extra_call(self):
        blocks=[{'id':'a','page':1,'bbox':[0,0,.5,.4],'kind':'text',
                 'text':'초기화 결과인 후보 목록을 꺼내 조사에 사용한다.','hasVisual':False},
                {'id':'b','page':1,'bbox':[0,.4,.5,.8],'kind':'text',
                 'text':'조사 결과에 의해 갱신할 후보가 결정된다.','hasVisual':False}]
        job={'id':'process','title':'탐색','blocks':blocks}
        doc={'documentId':'example','pages':[{'label':'1'}]}
        concept={'title':'탐색 과정','definition':'정점을 조사해요.',
                 'explanation':'후보를 관리하며 탐색해요.',
                 'easyExplanation':'갈림길로 돌아갈 수 있어요.','blockIds':['a','b'],
                 'standardKnowledgeUsed':False}
        raw={'concepts':[concept],'sequences':[{'conceptTitle':'탐색 과정','title':'탐색 순서','orderKind':'procedure',
            'transitions':[{'fromStep':0,'toStep':1,'relation':'초기화 결과 후보 목록을 조사에 사용해요.',
                            'blockIds':['a'],'sourceQuote':blocks[0]['text']},
                           {'fromStep':1,'toStep':2,'relation':'조사 결과가 갱신할 후보를 결정해요.',
                            'blockIds':['b'],'sourceQuote':blocks[1]['text']}],
            'steps':[{'title':'초기화','body':'후보 목록을 만들어요.','blockIds':['a']},
                     {'title':'조사','body':'후보 목록에서 꺼낸 후보를 조사해요.','blockIds':['a','b']},
                     {'title':'갱신','body':'조사 결과에 따라 후보를 갱신해요.','blockIds':['b']}]}],
             'excludedBlocks':[],'uncertainBlocks':[]}
        result=study.validate(raw,job,doc)
        flow=result['summary']['parts'][0]['stepFlow']
        self.assertEqual(flow['moduleId'],'synesis.step-flow')
        self.assertEqual([s['evidence'][0]['sourceId'] for s in flow['steps']],['a','a','b'])
        self.assertTrue(all(s['evidence'][0]['quote'] for s in flow['steps']))
        raw['sequences'][0]['steps'][1]['blockIds']=['outside']
        result=study.validate(raw,job,doc)
        self.assertNotIn('stepFlow',result['summary']['parts'][0])
        self.assertEqual(len(result['concepts']),1)
    def test_grounded_comparison_table_renders_without_another_request(self):
        block={'id':'figure','page':1,'bbox':[0,0,1,1],'kind':'page',
               'text':'','hasVisual':True,'planRole':'teaching'}
        job={'id':'types','title':'자료 유형','blocks':[block]}
        doc={'documentId':'example','pages':[{'label':'1'}]}
        concept={'title':'자료 유형','definition':'자료에는 수치형과 범주형이 있어요.',
                 'explanation':'각 자료는 나타내는 방식이 달라요.',
                 'easyExplanation':'수량과 종류를 구분해요.','blockIds':['figure'],
                 'standardKnowledgeUsed':False}
        raw={'concepts':[concept],'sequences':[],
             'tables':[{'conceptTitle':'자료 유형','headers':['유형','구분 기준','예'],
                 'rows':[['수치형','양을 나타냄','길이'],['범주형','종류를 나타냄','색']],
                 'blockIds':['figure']}],
             'excludedBlocks':[],'uncertainBlocks':[]}
        result=study.validate(raw,job,doc)
        body=result['summary']['parts'][0]['body']
        self.assertIn('| 유형 | 구분 기준 | 예 |',body)
        self.assertIn('| --- | --- | --- |',body)
        self.assertIn('| 수치형 | 양을 나타냄 | 길이 |',body)
        raw['tables'][0]['rows']=[['수치형','이산형','개수'],['수치형','연속형','길이']]
        result=study.validate(raw,job,doc)
        self.assertIn('| 수치형 | 연속형 | 길이 |',result['summary']['parts'][0]['body'])
        # A real anatomy table has fourteen organ/function pairs. A renderer
        # limit must not discard the entire grounded table after a paid answer.
        raw['tables'][0]['rows']=[[f'기관{i}',f'기능{i}',f'설명{i}'] for i in range(14)]
        result=study.validate(raw,job,doc)
        self.assertIn('| 기관13 | 기능13 | 설명13 |',result['summary']['parts'][0]['body'])
        self.assertIn('| 기관0 | 기능0 | 설명0 |',result['concepts'][0]['explanation'])
        raw['tables'][0]['rows'][1]=['범주형','색']
        result=study.validate(raw,job,doc)
        self.assertNotIn('| 유형 |',result['summary']['parts'][0]['body'])
    def test_wide_source_tables_reach_final_summary_and_concepts(self):
        block={'id':'figure','page':1,'bbox':[0,0,1,1],'kind':'page',
               'text':'','hasVisual':True,'planRole':'teaching'}
        job={'id':'comparison','title':'국가별 비교','blocks':[block]}
        doc={'documentId':'wide-table','fingerprint':'source','pages':[{'label':'1'}]}
        concept={'title':'국가별 비교','definition':'국가별 구성비를 비교해요.',
                 'explanation':'같은 원천에서 각 국가의 비율을 읽어요.',
                 'easyExplanation':'행과 열을 맞춰 비교해요.','blockIds':['figure']}
        for width in (5,9):
            with self.subTest(columns=width):
                headers=['원천']+[f'국가{i}' for i in range(width-1)]
                rows=[[f'원천{row}']+[f'{row*10+column}%' for column in range(width-1)]
                      for row in range(2)]
                raw={'concepts':[concept],'tables':[{'conceptTitle':'국가별 비교',
                     'headers':headers,'rows':rows,'blockIds':['figure']}],
                     'excludedBlocks':[],'uncertainBlocks':[]}
                unit=study.validate(raw,job,doc)
                result=study.assemble(doc,'new-concept-v99','document',0,[1],[job],
                                      {0:unit},[],[])
                header='| '+' | '.join(headers)+' |'
                final_row='| '+' | '.join(rows[-1])+' |'
                for text in (result['sections'][0]['body'],
                             result['sections'][0]['parts'][0]['body'],
                             result['concepts'][0]['entries'][0]['explanation']):
                    self.assertEqual(text.count(header),1)
                    self.assertIn(final_row,text)
                self.assertTrue(result['coverageComplete'])
                self.assertTrue(result['processingComplete'])

    def test_source_limitation_prose_is_removed_without_removing_real_conditions(self):
        text='사진에 나온 동물은 예시 이미지일 뿐, 구체적인 규칙은 제시되어 있지 않아요. 값이 바뀌면 결과도 바뀌어요.'
        value,_=learner_text(text)
        self.assertEqual(value,'값이 바뀌면 결과도 바뀌어요.')
        value,_=learner_text('함수에 값만 건네면 원래 변수의 주소는 알 수 없어요.')
        self.assertIn('주소는 알 수 없어요',value)
    def test_paired_null_math_is_repaired_without_inventing_symbols(self):
        from pdf_new_concept_v02_checks import repair_paired_null_math
        self.assertEqual(repair_paired_null_math('구간 \x00x=a\x00부터'),r'구간 \(x=a\)부터')
        self.assertEqual(repair_paired_null_math('변수 \x00x'+r'\u0000'),r'변수 \(x\)')
        self.assertIn('\x00',repair_paired_null_math('값 \x00 없음'))
        self.assertNotIn('\x00',repair_paired_null_math('띠 \x00(위쪽 값-아래쪽 값)'+r'\times\Delta x'+'\x00예요.'))
    def test_uncertain_source_is_not_published_as_certain_teaching(self):
        entry={'title':'제목','definition':'정의예요.','explanation':'설명이에요.','easyExplanation':'쉽게 설명해요.','blockIds':['a']}
        value=prepare_response({'concepts':[entry],'uncertainBlocks':[{'blockId':'a','reason':'좌표 충돌'}]})
        self.assertEqual(value['concepts'],[])
    def test_damaged_interval_reuses_only_identical_intact_math_peer(self):
        from pdf_new_concept_v02_checks import repair_repeated_math_span
        value='구간 \x1ba,b\x1d에서 '+r'\([a,b]\)를 적분해요.'
        self.assertNotIn('\x1b',repair_repeated_math_span(value))
        self.assertIn('\x1b',repair_repeated_math_span('구간 \x1ba,b\x1d'))
    def test_real_ruled_table_survives(self):
        import pdfplumber
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'table.pdf';writer=PdfWriter();page=writer.add_blank_page(width=600,height=800)
            commands=[]
            for x in (50,250,450):commands.append(f'{x} 350 m {x} 650 l S')
            for y in (350,450,550,650):commands.append(f'50 {y} m 450 {y} l S')
            for i,y in enumerate((375,475,575)):
                for j,x in enumerate((70,270)):commands.append(f'BT /F1 12 Tf {x} {y} Td (Cell {i} {j}) Tj ET')
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode());page[NameObject('/Contents')]=writer._add_object(stream)
            writer.write(path)
            with pdfplumber.open(path) as p:self.assertEqual(len(layout.table_regions(p.pages[0])),1)
    def test_heading_and_slide_boundary_not_recropped_together(self):
        a={'page':1,'zone':0,'kind':'text','bbox':[.1,.4,.9,.45]}
        h={'page':1,'zone':1,'kind':'heading','bbox':[.1,.46,.9,.49]}
        self.assertEqual(len(layout.crop_runs([a,h])),2)
    @unittest.skipUnless(BASE.exists(),'local fixture missing')
    def test_calculus_no_fullpage_tables_and_unique_text_ownership(self):
        d=json.loads((BASE/'document.json').read_text())
        with tempfile.TemporaryDirectory() as t:
            bs=layout.extract(BASE,d,range(1,32),Path(t));data=json.loads((Path(t)/'local-layout.json').read_text())
            self.assertFalse(any(b['bbox']==[0,0,1,1] for b in bs))
            for p in data['pages']:
                assigned=[i for b in p['fragments'] for i in b['wordIds']]
                self.assertEqual(len(assigned),len(set(assigned)))
                self.assertEqual(set(assigned),{w['id'] for w in p['words']})
                for b in p['fragments']:
                    for w in p['words']:
                        if w['id'] in b['wordIds']:self.assertTrue(layout.contains(b['bbox'],w['bbox']))
            self.assertTrue(all(b.get('localRole') in ('navigation','decoration') for b in bs if b['page']==31))
            self.assertTrue(any('위치함수' in b['text'] and not b.get('localRole') for b in bs if b['page']==21))
            self.assertFalse(any(b.get('headingTitle')=='6.5 함수의 평균값' for b in bs if 2<=b['page']<=30))
    def test_dense_panel_stays_within_four_image_transport_limit(self):
        bs=[{'id':str(i),'page':1,'zone':0,'kind':'text','text':'x = '+str(i),'bbox':[.1,.06+i*.13,.8,.10+i*.13]} for i in range(6)]
        self.assertLessEqual(len(layout.crop_runs(bs)),4)
        jobs=study.jobs_for([{'title':'formula','blocks':bs}])
        self.assertEqual({b['id'] for j in jobs for b in j['blocks']},{b['id'] for b in bs})
        self.assertTrue(all(len(layout.crop_runs(j['blocks']))<=4 for j in jobs))
    def test_plain_paragraphs_are_not_split_into_sentences(self):
        value='첫 번째 문장이에요. 두 번째 문장이에요.'
        self.assertEqual(learner_text(value)[0],value)
    def test_cache_separate_from_v1(self):
        import pdf_new_concept_study as old
        doc={'documentId':'d','fingerprint':'f'}
        self.assertNotEqual(study.root_path('/tmp',doc,'new-concept-v02','model','document',0),old.root_path('/tmp',doc,'new-concept-v1','model','document',0))
if __name__=='__main__':unittest.main()
