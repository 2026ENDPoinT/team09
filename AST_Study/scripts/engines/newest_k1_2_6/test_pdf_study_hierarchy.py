"""Offline display contracts. No paid checker, judge, or repair pipeline."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pdf_study_hierarchy as h
import pdf_new_concept_ver99_study as study
from test_pdf_request_packing import block


def source():
    return [block('chapter','6. 기업의 재무제표',kind='heading'),
            block('income','6.1. 손익계산서',kind='heading'),
            block('cost','기업의 네 가지 비용'),
            *[block('c'+str(i),str(i)+': 비용',1 if i<3 else 2) for i in range(1,5)],
            block('profit','영업이익',2),
            block('balance','6.2. 재무상태표',2,kind='heading'),
            block('asset','자산',2)]


def part(title,refs,**extra):
    return {'title':title,'body':'원문에 근거한 설명 $$a=b$$',
            'easyExplanation':'쉬운 설명',
            'evidence':[{'sourceId':r,'page':1 if r in ('income','c1','c2') else 2} for r in refs],
            'visualPages':[1 if r in ('income','c1','c2') else 2 for r in refs],**extra}


class HierarchyTests(unittest.TestCase):
    def headings(self):
        return h.source_headings(source())

    def test_source_chapter_survives_navigation_and_costs_span_pages(self):
        blocks=source();blocks[0]['localRole']='navigation'
        nodes=h.source_headings(blocks)
        self.assertEqual([(n['id'],n['level'],n['parentId']) for n in nodes],
            [('h:chapter',1,''),('h:income',2,'h:chapter'),('h:cost',3,'h:income'),('h:balance',2,'h:chapter')])
        costs=next(n for n in self.headings() if n['startBlockId']=='cost')
        self.assertEqual((costs['level'],costs['endBlockId'],costs['endPage']),(3,'c4',2))

    def test_decimal_paragraph_and_incomplete_list_do_not_become_headings(self):
        blocks=source()+[block('decimal','4.0 전후). 가격에 대한 설명이에요.\n다음 문장이 이어져요.',2,kind='heading')]
        blocks=[b for b in blocks if b['id']!='c3']
        ids={n['id'] for n in h.source_headings(blocks)}
        self.assertNotIn('h:decimal',ids);self.assertNotIn('h:cost',ids)

    def test_missing_ancestors_keep_numbered_siblings_and_depth_is_bounded(self):
        blocks=[block(str(i),title,kind='heading') for i,title in enumerate([
            '3.1. 첫 소단원','3.2. 다음 소단원','4. 다른 단원','4.1. 하위',
            '4.1.1. 개념','4.1.1.1. 세부','4.1.1.1.1. 더 세부'])]
        nodes=h.source_headings(blocks)
        self.assertEqual([n['parentId'] for n in nodes[:3]],['','',''])
        self.assertEqual([n['level'] for n in nodes],[1,1,1,2,3,4,4])

    def test_source_math_digits_are_readable_without_modifying_source(self):
        blocks=source();blocks[2]['text']='기업의 𝟒 가지 비용';original=copy.deepcopy(blocks)
        self.assertEqual(next(n['title'] for n in h.source_headings(blocks) if n['id']=='h:cost'),'기업의 4 가지 비용')
        self.assertEqual(blocks,original)

    def test_sibling_names_cannot_be_hidden_by_legacy_body_mode(self):
        raw={'sections':[{'parts':[part('영업이익',['profit'],headingId='h:income',headingMode='body')]}]}
        value=h.decorate(raw,source(),self.headings())
        self.assertEqual(value['hierarchy']['nodes'][-1]['title'],'영업이익')

    def test_omitted_page_number_does_not_require_another_planner_call(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        blocks=[block('text','원리'),block('footer','47',kind='page_number')]
        complete=Mock(return_value={'groups':[{'title':'원리','blockIds':['text'],'role':'teaching','continuesPrevious':False}],
                                    'displayHeadings':[]})
        # This fixture returns ID lists. Exercise that transport explicitly;
        # range-format admission has its own contract and coverage tests.
        with tempfile.TemporaryDirectory() as directory,patch.object(study,'PLAN_TRANSPORT','ids'):
            groups,warnings=study.plan_groups(Path(directory),SimpleNamespace(model='gpt-6-luna',complete=complete),blocks,Path(directory))
        self.assertEqual(complete.call_count,1);self.assertFalse(warnings)
        self.assertEqual({b['id'] for g in groups for b in g['blocks']},{'text','footer'})
        self.assertEqual(blocks[1]['planRole'],'decoration')

    def test_body_attaches_once_and_all_prose_is_unchanged(self):
        raw={'sections':[{'title':'묶음','parts':[
            part('손익계산서',['income'],headingId='h:income',headingMode='body'),
            part('기업의 네 가지 비용',['c1','c2','c3','c4'],headingId='h:cost',headingMode='body'),
            part('지급이자',['c3'],headingId='h:cost',headingMode='child')]}]}
        before=copy.deepcopy(raw);result=h.decorate(raw,source(),self.headings())
        self.assertEqual(raw,before)
        nodes=result['hierarchy']['nodes'];known={n['id']:n for n in nodes}
        self.assertEqual([n['level'] for n in nodes],[1,2,3,4])
        self.assertEqual(len([n for n in nodes if n['title']=='기업의 네 가지 비용']),1)
        parts=result['sections'][0]['parts']
        for old,new in zip(raw['sections'][0]['parts'],parts):
            for k,v in old.items():self.assertEqual(new[k],v)
            self.assertIn(new['contentId'],known[new['nodeId']]['contentIds'])

    def test_stable_parent_and_anchor_across_partial_arrivals(self):
        p=part('영업이익',['profit'],headingId='h:income',headingMode='child')
        first=h.decorate({'sections':[{'parts':[p]}]},source(),self.headings())
        final=h.decorate({'sections':[{'parts':[part('네 가지 비용',['c1','c4'],headingId='h:cost',headingMode='body'),p]}]},source(),self.headings())
        self.assertEqual(first['sections'][0]['parts'][0]['nodeId'],final['sections'][0]['parts'][1]['nodeId'])
        self.assertEqual(first['sections'][0]['parts'][0]['contentId'],final['sections'][0]['parts'][1]['contentId'])

    def test_legacy_fallback_uses_deepest_source_span(self):
        blocks=source();options=h.options_for({'blocks':blocks},self.headings(),blocks)
        value=h.placement({'title':'세금','blockIds':['c4']},{'blocks':blocks,'headingOptions':options})
        self.assertEqual(value,{'headingId':'h:cost','headingMode':'child'})

    def test_heading_options_do_not_change_parallel_jobs(self):
        group={'title':'손익계산서','blocks':source()}
        workers=study.WORKERS
        jobs=study.jobs_for([group]);before=copy.deepcopy(jobs)
        for job in jobs:job['headingOptions']=h.options_for(job,self.headings(),source())
        self.assertEqual([{k:v for k,v in j.items() if k!='headingOptions'} for j in jobs],before)
        self.assertEqual(study.WORKERS,workers)
        self.assertGreater(workers,1)
        payload=study.teaching_payload(jobs[0],[],{},[])
        self.assertNotIn('headingOptions',payload)
        self.assertNotIn('headingId',study.STUDY_FORMAT['json_schema']['schema']['properties']['concepts']['items']['properties'])

    def test_shared_source_citations_preserve_original_sibling_order(self):
        raw={'sections':[{'parts':[part('매출원가',['c1','c2']),part('판매 및 일반관리비',['c1','c2'])]}]}
        value=h.decorate(raw,source(),self.headings())
        self.assertEqual([n['title'] for n in value['hierarchy']['nodes'][-2:]],['매출원가','판매 및 일반관리비'])

    def test_compact_machine_export_has_no_body_or_formatted_text(self):
        result=h.decorate({'sections':[{'parts':[part('비용',['c1','c4'])]}]},source(),self.headings())
        with tempfile.TemporaryDirectory() as directory:
            h.export(directory,result);paths=list(Path(directory).iterdir())
            self.assertEqual([p.name for p in paths],['hierarchy.json'])
            content=paths[0].read_text();self.assertNotIn('\n',content)
            self.assertNotIn('원문에 근거한 설명',content)
            self.assertEqual(json.loads(content),result['hierarchy'])

    def test_saved_prose_upgrade_is_local_and_preserves_file_bytes(self):
        document={'documentId':'doc','fingerprint':'fp','pages':[{'label':'47'},{'label':'48'}]}
        raw={'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99','scope':'document','page':0,
             'processingComplete':True,'sections':[{'title':'묶음','parts':[part('세금',['c4'])],
                 'evidence':[{'sourceId':'c4'}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path=study.latest_path(directory,raw['strategy'],'document',0);path.parent.mkdir(parents=True)
            path.write_text(json.dumps(raw,ensure_ascii=False));before=path.read_bytes()
            old=path.parent/'old';old.mkdir();(old/'blocks.json').write_text(json.dumps(source(),ensure_ascii=False))
            with patch.object(study,'Provider',create=True,side_effect=AssertionError('No API')):
                result=study.recover(directory,document,model='gpt-6-luna')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['sections'][0]['parts'][0]['body'],raw['sections'][0]['parts'][0]['body'])
            self.assertEqual(result['hierarchy']['nodes'][0]['pageLabel'],'47')

    def test_homonyms_under_different_parents_remain_distinct(self):
        raw={'sections':[{'parts':[part('비용',['c1'],headingId='h:income',headingMode='child'),
                                  part('비용',['asset'],headingId='h:balance',headingMode='child')]}]}
        result=h.decorate(raw,source(),self.headings())
        self.assertEqual(len({p['nodeId'] for p in result['sections'][0]['parts']}),2)


class GeneralHierarchyTests(unittest.TestCase):
    def layout(self,key,text,page=1,font=18,kind='text',top=.2,role=None):
        value=block(key,text,page,kind);value.update(fontSize=font,bbox=[.05,top,.8,top+.05],zoneBounds=[0,0,1,1])
        if role:value['localRole']=role
        return value

    def ordered(self,result):
        nodes=result['hierarchy']['nodes'];out=[]
        def visit(parent):
            for n in nodes:
                if n['parentId']==parent:out.extend(n['contentIds']);visit(n['id'])
        visit('');return out

    def test_unmapped_glyphs_are_not_learner_heading_text(self):
        blocks=[self.layout('a','(cid:123)복습(cid:124) 행렬 곱',font=28,kind='heading',top=.05),
                self.layout('b','행렬을 설명하는 충분히 긴 본문이에요.')]
        before=copy.deepcopy(blocks)
        self.assertEqual(h.source_headings(blocks)[0]['title'],'복습 행렬 곱')
        self.assertEqual(blocks,before)

    def test_quantity_in_diagram_is_not_numbered_chapter(self):
        blocks=[self.layout('a','1. 모델의 이해',font=32,kind='heading',top=.05),
                self.layout('body','개념을 설명하는 충분히 긴 본문이에요.'),
                self.layout('quantity','3000 억 토큰',2,28,'heading',.85),
                self.layout('next','학습 방법',3,32,'heading',.05)]
        self.assertNotIn('3000 억 토큰',[n['title'] for n in h.source_headings(blocks)])
        self.assertEqual(h.source_headings(blocks)[-1]['parentId'],'h:a')

    def test_contiguous_repeated_slide_titles_share_scope_but_return_is_distinct(self):
        blocks=[]
        for page,title in enumerate(['손실 함수','손실 함수','손실 함수','최적화','손실 함수'],1):
            blocks.extend([self.layout('h'+str(page),title,page,32,'heading',.05),
                           self.layout('b'+str(page),'주제를 설명하는 충분히 긴 본문이에요.',page)])
        nodes=h.source_headings(blocks)
        self.assertEqual([(n['title'],n['page'],n['endPage']) for n in nodes],
            [('손실 함수',1,3),('최적화',4,4),('손실 함수',5,5)])

    def test_same_size_siblings_do_not_staircase_when_a_font_tier_is_absent(self):
        blocks=[self.layout('root','구조',font=40,kind='heading',top=.05),
                self.layout('mid','큰 단원',2,32,'heading',.05),
                self.layout('a','첫 세부',3,24,'heading',.05),
                self.layout('b','둘째 세부',4,24,'heading',.05),
                self.layout('body','기본 본문을 충분히 길게 설명해요.',4,18)]
        nodes=h.source_headings(blocks);a=next(n for n in nodes if n['id']=='h:a');b=next(n for n in nodes if n['id']=='h:b')
        self.assertEqual((a['level'],a['parentId']),(b['level'],b['parentId']))

    def test_slide_font_tolerance_does_not_flatten_a_larger_chapter(self):
        blocks=[]
        for page,(title,font) in enumerate([('첫 기관',40),('세부 구조',28),('세부 기능',28),
                                            ('다음 기관',38),('하위 구조',28),('하위 기능',32)],1):
            blocks.extend([self.layout('h'+str(page),title,page,font,'heading',.05),
                           self.layout('b'+str(page),'기본 본문을 충분히 길게 설명해요.',page,18)])
        nodes=h.source_headings(blocks)
        self.assertEqual([(n['title'],n['level']) for n in nodes],
                         [('첫 기관',1),('세부 구조',2),('세부 기능',2),('다음 기관',1),('하위 구조',2),('하위 기능',2)])

    def test_continued_heading_owns_later_generated_subtopics(self):
        blocks=[self.layout('root','1. 단원',font=36,kind='heading',top=.05)]
        for page in [2,3]:blocks.extend([self.layout('h'+str(page),'손실 함수',page,28,'heading',.05),
                                       self.layout('b'+str(page),'해당 개념을 설명하는 충분한 길이의 본문이에요.',page)])
        raw={'sections':[{'title':'첫 손실','visualPages':[2],'parts':[part('첫 손실',['b2'])]},
                         {'title':'다른 손실','visualPages':[3],'parts':[part('다른 손실',['b3'])]}]}
        result=h.decorate(raw,blocks);known={n['id']:n for n in result['hierarchy']['nodes']}
        leaf=known[result['sections'][1]['parts'][0]['nodeId']]
        self.assertEqual(known[leaf['parentId']]['title'],'손실 함수')

    def test_question_in_repeated_slide_title_track_is_structural(self):
        blocks=[]
        for page,title in enumerate(['모델','기계는 어떻게 학습할까?','손실 함수'],1):
            blocks.extend([self.layout('h'+str(page),title,page,32,'heading',.05),
                           self.layout('b'+str(page),'기본 본문을 충분히 길게 설명해요.',page,18)])
        self.assertIn('기계는 어떻게 학습할까?',[n['title'] for n in h.source_headings(blocks)])

    def test_whole_slide_visual_recovers_only_an_adjacent_exact_heading(self):
        visual=self.layout('visual','학습 과정\n알고리즘의 작동을 설명하는 본문이에요.',1,0,'visual',0)
        visual['bbox']=[0,0,1,1]
        blocks=[visual,self.layout('next','학습 과정',2,32,'heading',.05),
                self.layout('body','본문을 충분히 길게 설명해요.',2,18)]
        before=copy.deepcopy(blocks);nodes=h.source_headings(blocks)
        self.assertEqual([(n['title'],n['page'],n['endPage']) for n in nodes],[('학습 과정',1,2)])
        self.assertEqual(blocks,before)
        blocks[0]['text']='학습 단계\n비슷하지만 다른 제목이에요.'
        self.assertEqual(h.source_headings(blocks)[0]['page'],2)
        blocks[0]=copy.deepcopy(visual);blocks[0]['bbox']=[0,.4,.5,.8]
        self.assertEqual(h.source_headings(blocks)[0]['page'],2)

    def test_contents_and_learning_questions_cannot_own_body(self):
        blocks=[self.layout('cover','12. 표지 제목',font=45,kind='heading',role='navigation'),
            self.layout('toc','Contents',font=30,kind='heading',role='navigation'),
            self.layout('topic','실제 본문 제목',2,32,'heading',.05),self.layout('body','충분히 긴 실제 본문 설명이에요.',2),
            self.layout('question','2. 왜 이 방법을 사용하는가?',3,25,'heading',.05),
            self.layout('more','질문 뒤에도 본문이 계속 이어져요.',3)]
        nodes=h.source_headings(blocks)
        self.assertEqual([n['title'] for n in nodes],['실제 본문 제목'])

    def test_english_objectives_are_not_a_structural_parent(self):
        blocks=[self.layout('objectives','Learning Objectives',font=30,kind='heading',role='navigation'),
                self.layout('item','1. Why does this work?',font=25,kind='heading'),
                self.layout('real','2. Hardware',2,30,'heading',.05)]
        self.assertEqual([n['title'] for n in h.source_headings(blocks)],['2. Hardware'])

    def test_unnumbered_font_tiers_follow_source_without_subject_rules(self):
        blocks=[]
        for i,(key,title,font) in enumerate([('a','입력 장치',40),('b','키보드',28),('c','출력 장치',38),('d','모니터',28)],1):
            blocks += [self.layout(key,title,i,font,'heading',.05),self.layout(key+'text','설계와 작동 방식을 설명하는 본문이에요.',i)]
        nodes=h.source_headings(blocks)
        self.assertEqual([(n['title'],n['level'],n['parentId']) for n in nodes],
                         [('입력 장치',1,''),('키보드',2,'h:a'),('출력 장치',1,''),('모니터',2,'h:c')])

    def test_constant_furniture_is_ignored_but_changing_running_titles_are_used(self):
        blocks=[]
        for page,title in enumerate(['첫 주제','첫 주제','둘째 주제','둘째 주제'],1):
            blocks += [self.layout('header'+str(page),title,page,10,top=.02,role='decoration'),
                       self.layout('author'+str(page),'같은 저자',page,10,top=.96,role='decoration'),
                       self.layout('body'+str(page),'해당 주제의 충분한 길이의 설명문이에요.',page)]
        self.assertEqual([(n['title'],n['page']) for n in h.source_headings(blocks)],[('첫 주제',1),('둘째 주제',3)])

    def test_objectives_keep_corroborated_running_boundary_not_their_list(self):
        blocks=[]
        for page,title in enumerate(['앞 단원','앞 단원','다음 단원','다음 단원'],1):
            blocks += [self.layout('header'+str(page),title,page,10,top=.02,role='decoration'),
                       self.layout('body'+str(page),'본문을 충분한 길이로 설명하는 문장이에요.',page)]
        blocks.insert(5,self.layout('objective','학습 목표\n세부 항목을 배웁니다',3,18))
        blocks.insert(6,self.layout('list','1. 목록의 항목',3,24,'heading',.3))
        original=copy.deepcopy(blocks)
        nodes=h.source_headings(blocks)
        self.assertEqual([(n['title'],n['page']) for n in nodes],[('앞 단원',1),('다음 단원',3)])
        self.assertEqual(blocks,original)
        panels=copy.deepcopy(blocks)
        for b in panels:
            page=b['page'];zone=(page-1)%2;b['page']=(page+1)//2;b['zone']=zone
            b['zoneBounds']=[0,zone*.5,1,(zone+1)*.5]
            b['bbox'][1]=zone*.5+b['bbox'][1]*.5;b['bbox'][3]=zone*.5+b['bbox'][3]*.5
        self.assertEqual([n['startBlockId'] for n in h.source_headings(panels)],['header1','header3'])
        raw={'sections':[{'parts':[part('새 개념',['body3'])]}]}
        result=h.decorate(raw,blocks)
        known={n['id']:n for n in result['hierarchy']['nodes']}
        owner=known[result['sections'][0]['parts'][0]['nodeId']]
        self.assertEqual(known[owner['parentId']]['title'],'다음 단원')
        for navigation in ['Contents','Table of Contents','목차','Learning Objectives\nContents']:
            blocks[5]['text']=navigation
            self.assertEqual(h.source_headings(blocks)[-1]['page'],4)
        blocks[5]['text']='Learning Objectives'
        self.assertEqual(h.source_headings(blocks)[-1]['page'],3)
        # A header elsewhere in the document does not corroborate this panel.
        blocks[-2]['page']=8;blocks[-1]['page']=8
        self.assertEqual(h.source_headings(blocks)[-1]['page'],8)

    def test_examples_equations_and_chart_labels_are_not_headings(self):
        blocks=[self.layout('heading','일반적인 단원',font=32,kind='heading',top=.05),
                self.layout('body','본문과 차트에 쓰인 기본 크기의 문장이에요.'),
                self.layout('example','Example 1. Find the answer',2,32,'heading',.05),
                self.layout('equation','lim x = 0',3,32,'heading',.05),
                self.layout('chart','그래프의 범례',4,18,'heading',.12)]
        self.assertEqual([n['title'] for n in h.source_headings(blocks)],['일반적인 단원'])

    def test_distant_equal_titles_remain_separate_occurrences_in_order(self):
        blocks=[block('root','1. 공통 단원',kind='heading'),block('first','첫 위치'),
                block('middle','중간 위치',2),block('later','나중 위치',40)]
        raw={'sections':[{'title':'내용','parts':[part('판정법',['first']),part('다른 내용',['middle']),part('판정법',['later'])]}]}
        result=h.decorate(raw,blocks);parts=result['sections'][0]['parts']
        self.assertNotEqual(parts[0]['nodeId'],parts[2]['nodeId'])
        self.assertEqual(self.ordered(result),[p['contentId'] for p in parts])

    def test_cross_references_to_earlier_pages_do_not_reorder_prose(self):
        blocks=[block('root','1. 공통 단원',kind='heading'),block('old','앞 내용'),block('new','뒤 내용',10)]
        raw={'sections':[{'parts':[part('나중 개념',['new']),part('앞을 참조하는 설명',['old'])]}]}
        result=h.decorate(raw,blocks)
        self.assertEqual(self.ordered(result),[p['contentId'] for p in result['sections'][0]['parts']])

    def test_parent_explanation_after_a_child_is_not_pulled_up(self):
        blocks=[block('root','1. 공통 단원',kind='heading'),block('first','첫 설명'),block('more','나중 설명',2)]
        raw={'sections':[{'parts':[part('하위 개념',['first']),part('공통 단원',['more'])]}]}
        result=h.decorate(raw,blocks)
        self.assertEqual(self.ordered(result),[p['contentId'] for p in result['sections'][0]['parts']])

    def test_identical_source_and_title_never_drop_distinct_or_duplicate_prose(self):
        blocks=[block('root','1. 단원',kind='heading'),block('a','원문')]
        a=part('같은 제목',['a']);b=copy.deepcopy(a);b['body']='다른 설명도 그대로 보존해요.'
        result=h.decorate({'sections':[{'parts':[a,b,a]}]},blocks);parts=result['sections'][0]['parts']
        self.assertEqual(len({p['contentId'] for p in parts}),3)
        self.assertEqual(self.ordered(result),[p['contentId'] for p in parts])

    def test_closed_source_branch_is_a_new_occurrence_instead_of_reordering(self):
        blocks=[block('one','1. 첫 단원',kind='heading'),block('a','첫 내용'),
                block('two','2. 둘째 단원',2,kind='heading'),block('b','둘째 내용',2)]
        raw={'sections':[{'parts':[part('첫 설명',['a']),part('둘째 설명',['b']),part('첫 단원 재참조',['a'])]}]}
        result=h.decorate(raw,blocks)
        self.assertEqual(self.ordered(result),[p['contentId'] for p in result['sections'][0]['parts']])

    def test_repeated_returns_to_the_same_source_keep_unique_branches(self):
        blocks=[block('one','1. 첫 단원',kind='heading'),block('a','첫 내용'),
                block('two','2. 둘째 단원',2,kind='heading'),block('b','둘째 내용',2)]
        entries=[part('첫 설명',['a']),part('둘째 설명',['b'])]*4
        result=h.decorate({'sections':[{'parts':entries}]},blocks)
        ids=[n['id'] for n in result['hierarchy']['nodes']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.ordered(result),[p['contentId'] for p in result['sections'][0]['parts']])

    def test_equivalent_classification_titles_do_not_add_a_duplicate_heading(self):
        self.assertTrue(h.same_title('기본 네 가지 항목','기본 4 가지 종류의 항목'))
        self.assertFalse(h.same_title('3가지 항목','4가지 항목'))
        self.assertFalse(h.same_title('3 가지 항목','4 가지 항목'))

    def test_cross_page_counted_list_skips_furniture_without_joining_new_sections(self):
        blocks=[block('root','1. 단원',kind='heading'),block('list','두 가지 유형'),
                block('a','① 첫 항목',kind='heading'),block('footer','저자')]
        blocks[-1]['localRole']='decoration'
        blocks += [block('b','② 둘째 항목',2,kind='heading')]
        nodes=h.source_headings(blocks)
        self.assertEqual([n['id'] for n in nodes],['h:root','h:list'])
        blocks[-1]=block('new','2. 새로운 단원',2,kind='heading')
        self.assertNotIn('h:list',{n['id'] for n in h.source_headings(blocks)})

    def test_new_topic_does_not_inherit_an_old_font_only_subsection(self):
        blocks=[self.layout('main','장치',font=40,kind='heading',top=.05),
                self.layout('sub','상세 기능',2,28,'heading',.05),self.layout('a','첫 기능을 설명하는 내용이에요.',2),
                self.layout('b','새로운 주제에 관한 내용이에요.',3)]
        first={'title':'상세 기능','visualPages':[2],'parts':[part('기능 설명',['a'])]}
        second={'title':'새로운 주제','visualPages':[3],'parts':[part('다른 기능',['b'])]}
        result=h.decorate({'sections':[first,second]},blocks);known={n['id']:n for n in result['hierarchy']['nodes']}
        leaf=known[result['sections'][1]['parts'][0]['nodeId']]
        self.assertEqual(known[leaf['parentId']]['title'],'새로운 주제')
        self.assertEqual(known[known[leaf['parentId']]['parentId']]['title'],'장치')

    def test_equation_example_and_numeric_wrappers_are_omitted(self):
        blocks=[self.layout('main','장치',font=40,kind='heading',top=.05),
                self.layout('sub','상세 기능',2,28,'heading',.05),
                self.layout('a','첫 기능을 설명하는 내용이에요.',2),
                self.layout('b','새로운 주제에 관한 내용이에요.',3)]
        for title in ['∞','1','n = 2 ⇒ 15×2 < 20',
                      '참고 1) 다음과 같이 쓸 수 있다.',
                      '예제 함수의 멱급수를 구하여라.']:
            with self.subTest(title=title):
                raw={'sections':[{'title':'상세 기능','visualPages':[2],'parts':[part('첫 설명',['a'])]},
                     {'title':title,'visualPages':[3],'parts':[part('다음 개념',['b']),part('다른 개념',['b'])]}]}
                original=copy.deepcopy(raw);result=h.decorate(raw,blocks)
                self.assertEqual(raw,original)
                nodes={n['id']:n for n in result['hierarchy']['nodes']}
                self.assertNotIn(title,[n['title'] for n in nodes.values()])
                for p in result['sections'][1]['parts']:
                    self.assertEqual(nodes[nodes[p['nodeId']]['parentId']]['title'],'장치')
                self.assertEqual(self.ordered(result),[p['contentId'] for s in result['sections'] for p in s['parts']])

    def test_invalid_root_uses_existing_concepts_without_inventing_titles(self):
        raw={'sections':[{'title':'∞','parts':[part('첫 개념',['a']),part('둘째 개념',['b'])]}]}
        result=h.decorate(raw,[block('a','원문'),block('b','다음 원문',2)])
        self.assertEqual([(n['title'],n['level']) for n in result['hierarchy']['nodes']],
                         [('첫 개념',1),('둘째 개념',1)])
        self.assertEqual(self.ordered(result),[p['contentId'] for p in result['sections'][0]['parts']])
        self.assertEqual(result['sections'][0]['title'],'∞') # Saved source metadata stays intact.

    def test_ambiguous_existing_wrapper_and_named_functions_are_preserved(self):
        for title in ['중요한 Maclaurin 급수와 수렴 구간','sin 함수의 멱급수','일의 응용']:
            raw={'sections':[{'title':title,'parts':[part('관련 개념',['a'])]}]}
            result=h.decorate(raw,[block('a','원문')])
            self.assertEqual(result['hierarchy']['nodes'][0]['title'],title)

    def test_no_safe_replacement_does_not_drop_or_rewrite_prose(self):
        raw={'sections':[{'title':'∞','parts':[part('1',['a'])]}]}
        result=h.decorate(raw,[block('a','원문')])
        self.assertEqual(result['sections'][0]['parts'][0]['body'],raw['sections'][0]['parts'][0]['body'])
        self.assertEqual(len(self.ordered(result)),1)

    def test_concept_formula_titles_are_never_filtered_as_wrappers(self):
        blocks=[block('root','1. 단원',kind='heading'),block('a','원문')]
        raw={'sections':[{'title':'단원','parts':[part('E = mc²',['a'])]}]}
        result=h.decorate(raw,blocks)
        self.assertIn('E = mc²',[n['title'] for n in result['hierarchy']['nodes']])

    def test_prior_metadata_is_rebuilt_without_mutating_saved_prose(self):
        document={'documentId':'d','fingerprint':'f','pages':[{'label':'1'}]}
        raw={'documentId':'d','sourceFingerprint':'f','strategy':'new-concept-v99','scope':'document','page':0,
             'processingComplete':True,'hierarchy':{'version':'study-hierarchy-1','nodes':[]},
             'sections':[{'title':'단원','parts':[part('설명',['a'])],'evidence':[{'sourceId':'a','page':1}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path=study.latest_path(directory,'new-concept-v99','document',0);path.parent.mkdir(parents=True)
            path.write_text(json.dumps(raw,ensure_ascii=False));before=path.read_bytes()
            cache=path.parent/'old';cache.mkdir();(cache/'blocks.json').write_text(json.dumps([block('a','원문')]))
            result=study.recover(directory,document)
            self.assertEqual(result['hierarchy']['version'],h.VERSION)
            self.assertEqual(result['sections'][0]['parts'][0]['body'],raw['sections'][0]['parts'][0]['body'])
            self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
