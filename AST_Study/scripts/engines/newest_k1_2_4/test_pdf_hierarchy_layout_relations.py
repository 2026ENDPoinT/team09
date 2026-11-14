"""Offline document-layout hierarchy contracts, independent of subject vocabulary."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pdf_study_hierarchy as hierarchy


def layout(identity, text, *, page=1, font=18, kind='text', left=.07,
           top=.15, zone=0, bounds=None):
    bounds=bounds or [0,0,1,1]
    return {'id': identity, 'text': text, 'page': page, 'fontSize': font,
            'kind': kind, 'bbox': [left, top, min(bounds[2]-.01,left+.65), top+.045],
            'zone': zone, 'zoneBounds': bounds,
            'hasVisual': False, 'visualOnly': False, 'planRole': 'teaching'}


def paragraph(identity, *, page=1, left=.14, top=.3, zone=0, bounds=None):
    return layout(identity, '이 항목의 조건과 작동 방식을 구체적으로 설명하는 본문이에요.',
                  page=page, left=left, top=top, zone=zone, bounds=bounds)


def concept(title, refs, body='이전에 생성한 설명과 수식 $x+y$를 그대로 보존해요.'):
    return {'title': title, 'body': body, 'easyExplanation': '이전에 생성한 쉬운 설명이에요.',
            'evidence': [{'sourceId': ref, 'page': 1} for ref in refs],
            'visualPages': [1]}


class LayoutRelationTests(unittest.TestCase):
    def outline(self, blocks):
        return {node['id']: node for node in hierarchy.source_headings(blocks)}

    def parent(self, nodes, identity):
        self.assertIn('h:'+identity, nodes)
        return nodes['h:'+identity]['parentId']

    def slide(self, marker='❖', child_font=26.51, child_left=.07):
        blocks=[layout('root', '1) 공통 원리', font=30.82, kind='heading', top=.11)]
        for index, title in enumerate(['첫 관점', '둘째 관점', '셋째 관점']):
            top=.23+index*.24
            blocks.extend([
                layout('child'+str(index), marker+' '+title, font=child_font,
                       kind='heading', left=child_left, top=top),
                paragraph('body'+str(index), left=child_left+.06, top=top+.065)])
        return blocks

    def test_multiple_markers_identify_siblings_anywhere_in_panel(self):
        for marker in ['❖', '◆', '▪', '■']:
            with self.subTest(marker=marker):
                blocks=self.slide(marker);before=copy.deepcopy(blocks)
                nodes=self.outline(blocks)
                self.assertEqual([self.parent(nodes,'child'+str(i)) for i in range(3)],
                                 ['h:root']*3)
                self.assertEqual(len({nodes['h:child'+str(i)]['level'] for i in range(3)}),1)
                self.assertEqual(blocks,before)

    def test_parenthesis_numbering_has_peers_below_outer_numbering(self):
        blocks=[layout('root','1) 재료의 구분',font=32,kind='heading',top=.08)]
        for index in range(2):
            top=.28+index*.28
            blocks.extend([layout('sub'+str(index),f'({index+1}) 분류 항목',
                                  font=25,kind='heading',left=.12,top=top),
                           paragraph('body'+str(index),left=.18,top=top+.07)])
        nodes=self.outline(blocks)
        self.assertEqual([self.parent(nodes,'sub0'),self.parent(nodes,'sub1')],
                         ['h:root','h:root'])

    def test_same_slide_peers_keep_the_inherited_cross_page_parent(self):
        blocks=[layout('chapter','2. 構造と条件',font=35,kind='heading',top=.08),
                layout('first','1) 第一の条件',font=27,kind='heading',top=.2),
                paragraph('body1',top=.3),
                layout('second','2) 第二の条件',page=2,font=27,kind='heading',top=.13),
                paragraph('body2',page=2,top=.25),
                layout('peer1','❖ First perspective',page=3,font=26.5,kind='heading',top=.13),
                paragraph('body3',page=3,top=.25),
                layout('peer2','❖ Second perspective',page=3,font=26.5,kind='heading',top=.62),
                paragraph('body4',page=3,top=.72),
                layout('third','3) 第三の条件',page=4,font=27,kind='heading',top=.13),
                paragraph('body5',page=4,top=.25)]
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'peer1'),self.parent(nodes,'peer2'))
        self.assertNotEqual(self.parent(nodes,'peer2'),'')
        self.assertEqual(self.parent(nodes,'third'),'h:chapter')
        parts=[concept('First concept',['body3','body4'])]
        parts[0]['visualPages']=[3]
        for e in parts[0]['evidence']:e['page']=3
        saved={'sections':[{'title':'학습 내용','parts':parts}],'concepts':[]}
        projected=hierarchy.decorate(saved,blocks,list(nodes.values()))
        self.assertNotIn('학습 내용',[n['title'] for n in projected['hierarchy']['nodes']])

    def test_unbound_placeholder_uses_the_existing_concept_title(self):
        for title in ['학습 내용','학습내용','개념 정리','Learning content']:
            saved={'sections':[{'title':title,'parts':[concept('Boundary conditions',[])]}]}
            before=copy.deepcopy(saved)
            projected=hierarchy.decorate(saved)
            self.assertEqual(projected['hierarchy']['nodes'][0]['title'],'Boundary conditions')
            self.assertEqual(saved,before)
            self.assertEqual(projected['sections'][0]['parts'][0]['body'],saved['sections'][0]['parts'][0]['body'])

    def test_placeholder_does_not_close_a_source_topic_on_the_next_page(self):
        blocks=[layout('root','2. Main unit',font=34,kind='heading'),
                layout('title','Boundary conditions',font=26,kind='heading',top=.3),
                paragraph('body',page=2)]
        headings=[{'id':'h:root','parentId':'','title':'2. Main unit','level':1,
                    'page':1,'endPage':2,'startBlockId':'root','endBlockId':'body',
                    'sourceHeading':True,'sourceKind':'numbered'},
                  {'id':'h:title','parentId':'h:root','title':'Boundary conditions','level':2,
                    'page':1,'endPage':2,'startBlockId':'title','endBlockId':'body',
                    'sourceHeading':True,'sourceKind':'title'}]
        part=concept('Specific condition',['body']);part['visualPages']=[2]
        for e in part['evidence']:e['page']=2
        result=hierarchy.decorate({'sections':[{'title':'학습 내용','visualPages':[2],'parts':[part]}]},blocks,headings)
        nodes={n['id']:n for n in result['hierarchy']['nodes']}
        self.assertIn('h:title',nodes)
        self.assertEqual(nodes[result['sections'][0]['parts'][0]['nodeId']]['parentId'],'h:title')

    def test_wrapped_heading_continues_under_its_outer_parent_on_next_page(self):
        blocks=[layout('root','3) 변화가 남긴 결과',font=30.82,kind='heading',top=.114),
                layout('first','(1) 첫 번째 결과',font=26.51,kind='heading',left=.089,top=.265),
                paragraph('body1',left=.126,top=.35),
                layout('second','(2) 두 번째 결과',page=2,font=26.51,kind='heading',left=.076,top=.116),
                paragraph('body2',page=2,left=.112,top=.226),
                layout('third','(3) 세 번째 결과',page=3,font=26.51,kind='heading',left=.08,top=.116),
                paragraph('body3',page=3,left=.13,top=.226)]
        nodes=self.outline(blocks)
        self.assertEqual([self.parent(nodes,k) for k in ['first','second','third']],['h:root']*3)
        self.assertEqual([nodes['h:'+k]['level'] for k in ['first','second','third']],[2]*3)

    def test_native_wrapped_title_keeps_the_parent_across_a_page_break(self):
        blocks=[layout('root','3) 구조의 변화',font=30.82,kind='heading',top=.114),
                layout('first','(1) 첫 결과',font=26.51,kind='heading',left=.089,top=.265),
                paragraph('body1',left=.13,top=.35),
                layout('second','원본 그림의 설명',page=2,font=None,kind='visual',left=.076,top=.116),
                paragraph('body2',page=2,left=.13,top=.3)]
        blocks[3]['nativeHeading']={'title':'(2) 다음 결과','fontSize':26.51,'bbox':blocks[3]['bbox']}
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'second'),'h:root')
        self.assertEqual(nodes['h:second']['level'],nodes['h:first']['level'])

    def test_cross_page_numbering_does_not_reopen_a_closed_parent(self):
        blocks=[layout('root','3) 첫 범위',font=31,kind='heading',top=.1),
                layout('first','(1) 첫 항목',font=26.5,kind='heading',left=.09,top=.27),
                paragraph('body1',left=.13,top=.35),
                layout('new','4) 새로운 범위',page=2,font=31,kind='heading',top=.1),
                layout('second','(2) 독립된 항목',page=2,font=26.5,kind='heading',left=.09,top=.27),
                paragraph('body2',page=2,left=.13,top=.35)]
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'second'),'h:new')

    def test_circled_prominent_titles_with_bodies_are_siblings(self):
        blocks=[layout('root','1) 주요 변환',font=32,kind='heading',top=.08)]
        for index, marker in enumerate(['①','②']):
            top=.27+index*.3
            blocks.extend([layout('sub'+str(index),marker+' 변환 방식',font=25,
                                  kind='heading',left=.12,top=top),
                           paragraph('body'+str(index),left=.18,top=top+.07)])
        nodes=self.outline(blocks)
        self.assertEqual([self.parent(nodes,'sub0'),self.parent(nodes,'sub1')],
                         ['h:root','h:root'])

    def test_same_font_indentation_and_repeated_marker_can_supply_depth(self):
        nodes=self.outline(self.slide(child_font=30.82,child_left=.14))
        self.assertEqual([self.parent(nodes,'child'+str(i)) for i in range(3)],
                         ['h:root']*3)

    def test_repeated_subheadings_do_not_form_a_staircase(self):
        nodes=self.outline(self.slide())
        levels=[nodes['h:child'+str(i)]['level'] for i in range(3)]
        self.assertEqual(levels,[2,2,2])
        self.assertEqual(nodes['h:root']['endBlockId'],'body2')

    def test_next_outer_number_closes_previous_subheading_scope(self):
        blocks=self.slide()
        blocks.extend([layout('next','2) 새로운 원리',page=2,font=30.82,kind='heading',top=.11),
                       paragraph('nextbody',page=2,top=.25)])
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'next'),'')
        self.assertEqual(nodes['h:root']['endBlockId'],'body2')
        self.assertEqual(nodes['h:child2']['endBlockId'],'body2')

    def test_repeated_marker_under_new_same_page_parent_does_not_reopen_old_branch(self):
        for intro in [False,True]:
            with self.subTest(intro=intro):
                blocks=[layout('root','1) 첫 범주',font=32,kind='heading',top=.08),
                        layout('a','❖ 첫 속성',font=26,kind='heading',top=.2),
                        paragraph('abody',top=.27),
                        layout('next','2) 다음 범주',font=32,kind='heading',top=.43)]
                if intro:blocks.append(paragraph('intro',top=.5))
                blocks.extend([layout('b','❖ 다음 속성',font=26,kind='heading',top=.62),
                               paragraph('bbody',top=.7)])
                nodes=self.outline(blocks)
                self.assertEqual(self.parent(nodes,'next'),'')
                self.assertEqual(self.parent(nodes,'b'),'h:next')
                self.assertEqual(nodes['h:root']['endBlockId'],'abody')

    def test_plain_body_lists_do_not_become_structural_titles(self):
        blocks=[layout('root','1) 장치의 동작',font=30,kind='heading',top=.08)]
        for index, text in enumerate(['• 전원을 켜면 표시등이 점등돼요.',
                                      '▪ 표시등을 확인하고 다음 단계를 진행해요.',
                                      '① 버튼을 누르고 화면 상태를 확인해요.']):
            blocks.append(layout('body'+str(index),text,left=.14,top=.27+index*.12))
        self.assertEqual(set(self.outline(blocks)),{'h:root'})

    def test_visual_only_children_are_owned_without_text_or_api(self):
        blocks=[layout('root','도식의 구성',font=32,kind='heading',top=.08)]
        for i in range(2):
            blocks.append(layout('sub'+str(i),'❖ 도식 '+str(i),font=28,kind='heading',top=.27+i*.3))
            visual=layout('v'+str(i),'',font=None,kind='visual',left=.14,top=.34+i*.3)
            visual.update(hasVisual=True,bbox=[.14,.34+i*.3,.8,.52+i*.3]);blocks.append(visual)
        nodes=self.outline(blocks)
        self.assertEqual([self.parent(nodes,'sub'+str(i)) for i in range(2)],['h:root']*2)

    def test_middle_parent_without_direct_body_can_introduce_children(self):
        blocks=[layout('outer','단원',font=36,kind='heading',top=.07),
                paragraph('intro',top=.19),
                layout('middle','세부 범주',font=30,kind='heading',top=.4),
                layout('sub','❖ 세부 속성',font=26,kind='heading',left=.12,top=.55),
                paragraph('body',left=.17,top=.64)]
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'middle'),'h:outer')
        self.assertEqual(self.parent(nodes,'sub'),'h:middle')

    def test_numeric_quantity_is_not_a_chapter_even_when_large(self):
        blocks=[layout('root','1) 처리량',font=30,kind='heading',top=.08),
                paragraph('body',top=.23),
                layout('quantity','3000 억 토큰',font=28,kind='heading',top=.55)]
        self.assertNotIn('h:quantity',self.outline(blocks))

    def test_discussion_questions_keep_document_style_and_parent_structure(self):
        blocks=[layout('chapter','1. 일반적인 주제',font=35,kind='heading',top=.11),
                paragraph('cb',top=.24),
                layout('question','2. 이 현상은 왜 발생할까?',page=2,font=35,kind='heading',top=.11),
                layout('a','❖ 첫 관점은 무엇인가?',page=2,font=26,kind='heading',top=.3),
                paragraph('ab',page=2,top=.37),
                layout('b','❖ 둘째 관점은 무엇인가?',page=2,font=26,kind='heading',top=.6),
                paragraph('bb',page=2,top=.67)]
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'question'),'')
        self.assertEqual(self.parent(nodes,'a'),'h:question')
        self.assertEqual(self.parent(nodes,'b'),'h:question')

    def test_small_font_difference_uses_parent_and_correlated_question_style(self):
        blocks=[layout('parent','1) 범주의 변화',font=26.51,kind='heading',top=.08),
                layout('first','1. 첫 효과는 어떻게 달라질까?',font=24.23,kind='heading',top=.217),
                paragraph('fb',top=.3),
                layout('next','2. 둘째 효과는 어떻게 달라질까?',page=2,font=24.23,kind='heading',top=.112),
                paragraph('nb',page=2,top=.23)]
        self.assertIn('h:first',self.outline(blocks));self.assertIn('h:next',self.outline(blocks))

    def test_multiple_choice_options_are_not_promoted_as_large_titles(self):
        blocks=[layout('root','1. 실제 단원',font=35,kind='heading',top=.08),
                paragraph('body',top=.2),
                layout('quiz','Q. 다음 중 올바른 선택은?',page=2,font=35,kind='heading',top=.125)]
        for i in range(4):
            blocks.append(layout('option'+str(i),str(i+1)+') 선택 항목',page=2,font=30,top=.25+i*.1))
        self.assertEqual(set(self.outline(blocks)),{'h:root'})

    def test_columns_with_separate_titles_do_not_inherit_each_others_subheadings(self):
        blocks=[]
        for zone,left in [(0,.03),(1,.54)]:
            bounds=[0,0,.48,1] if zone==0 else [.51,0,1,1]
            root='left' if zone==0 else 'right'
            blocks.extend([
                layout(root,'왼쪽 주제' if zone==0 else '오른쪽 주제',font=30,
                       kind='heading',left=left,top=.08,zone=zone,bounds=bounds),
                layout(root+'sub','❖ 개별 속성',font=25,kind='heading',
                       left=left+.02,top=.3,zone=zone,bounds=bounds),
                paragraph(root+'body',left=left+.05,top=.38,zone=zone,bounds=bounds)])
        nodes=self.outline(blocks)
        self.assertEqual(self.parent(nodes,'leftsub'),'h:left')
        self.assertEqual(self.parent(nodes,'right'),'')
        self.assertEqual(self.parent(nodes,'rightsub'),'h:right')

    def test_numbering_normalization_removes_only_a_title_prefix(self):
        for prefix in ['1)', '(1)', '①', '１）', '1.2.']:
            with self.subTest(prefix=prefix):
                self.assertTrue(hierarchy.same_title(prefix+' 공통 원리','공통 원리'))
        self.assertFalse(hierarchy.same_title('3 가지 조건','4 가지 조건'))
        self.assertFalse(hierarchy.same_title('공통 원리 1','공통 원리 2'))

    def test_body_evidence_outweighs_an_earlier_ancestor_heading_reference(self):
        blocks=self.slide()
        raw={'sections':[{'title':'공통 원리','parts':[
            concept('공통 원리',['root','child0','body0'])]}]}
        before=copy.deepcopy(raw)
        value=hierarchy.decorate(raw,blocks)
        nodes={node['id']:node for node in value['hierarchy']['nodes']}
        content=value['sections'][0]['parts'][0]
        owner=nodes[content['nodeId']]
        ancestors=[]
        while owner:
            ancestors.append(owner['id']);owner=nodes.get(owner['parentId'])
        self.assertIn('h:child0',ancestors)
        self.assertEqual(raw,before)
        for key in ['body','easyExplanation','evidence']:
            self.assertEqual(content[key],before['sections'][0]['parts'][0][key])

    def test_equal_body_evidence_for_siblings_keeps_their_common_parent(self):
        blocks=self.slide()
        raw={'sections':[{'parts':[concept('관점 비교',['body0','body1'])]}]}
        value=hierarchy.decorate(raw,blocks)
        nodes={node['id']:node for node in value['hierarchy']['nodes']}
        owner=nodes[value['sections'][0]['parts'][0]['nodeId']]
        self.assertEqual(nodes[owner['parentId']]['id'],'h:root')

    def test_equivalent_numbered_title_does_not_duplicate_the_parent(self):
        blocks=[layout('root','1) 공통 원리',font=30,kind='heading',top=.08),
                paragraph('body',top=.25)]
        value=hierarchy.decorate({'sections':[{'parts':[concept('공통 원리',['body'])]}]},blocks)
        nodes=value['hierarchy']['nodes']
        self.assertEqual(len(nodes),1)
        self.assertEqual(nodes[0]['id'],'h:root')
        self.assertEqual(nodes[0]['contentIds'],[value['sections'][0]['parts'][0]['contentId']])

    def test_shared_sources_do_not_merge_distinct_explanations(self):
        blocks=self.slide()
        entries=[concept('관점의 조건',['body0'],'조건을 설명하는 원래 문장이에요.'),
                 concept('관점의 한계',['body0'],'한계를 설명하는 별도의 원래 문장이에요.')]
        before=copy.deepcopy(entries)
        value=hierarchy.decorate({'sections':[{'parts':entries}]},blocks)
        parts=value['sections'][0]['parts']
        self.assertEqual([part['body'] for part in parts],[part['body'] for part in before])
        self.assertEqual(len({part['contentId'] for part in parts}),2)
        self.assertEqual(len({part['nodeId'] for part in parts}),2)

    def test_ancestor_named_saved_explanation_uses_child_source_label(self):
        blocks=self.slide()
        raw={'sections':[{'parts':[concept('공통 원리',['root','child0','body0'])]}]}
        value=hierarchy.decorate(raw,blocks)
        self.assertEqual([n['id'] for n in value['hierarchy']['nodes']],['h:root','h:child0'])
        self.assertEqual(value['sections'][0]['parts'][0]['title'],'공통 원리')

    def test_typographical_quotes_and_separators_do_not_duplicate_a_source_title(self):
        self.assertTrue(hierarchy.same_title('❖ 가장 추상적, 보편적인 ‘사회’ 개념',
                                             '가장 추상적·보편적인 사회 개념'))
        self.assertTrue(hierarchy.same_title('II. 일반적인 원리','일반적인 원리'))
        self.assertTrue(hierarchy.same_title('(b) 일반적인 원리','일반적인 원리'))

    def test_existing_partial_and_complete_are_upgraded_without_overwriting_paid_files(self):
        import pdf_new_concept_ver99_study as study
        for complete in [False,True]:
            with self.subTest(complete=complete),tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);cache=folder/'generated/new-concept-v99/fixture';cache.mkdir(parents=True)
                blocks=self.slide();(cache/'blocks.json').write_text(json.dumps(blocks))
                raw={'documentId':'doc','sourceFingerprint':'fp','strategy':'new-concept-v99',
                     'scope':'document','page':0,'processingComplete':complete,'hierarchy':{'version':'study-hierarchy-5'},
                     'sections':[{'parts':[concept('공통 원리',['root','child0','body0'])]}],
                     'runUsage':{'usageBasedUsd':.03,'requests':2}}
                saved=cache/('result.json'if complete else'partial.json');saved.write_text(json.dumps(raw))
                paid=folder/'generated/paid-responses/paid.json';paid.parent.mkdir();paid.write_text('{"fixture":true}')
                before={p:p.read_bytes() for p in [saved,paid,cache/'blocks.json']}
                document={'documentId':'doc','fingerprint':'fp','pages':[{'label':'8'}]}
                with patch.object(study,'hierarchy',hierarchy),patch('socket.socket.connect',side_effect=AssertionError('No API')):
                    result=study.display_saved(folder,document,raw,cache)
                self.assertEqual(result['hierarchy']['version'],hierarchy.VERSION)
                self.assertEqual(result['sections'][0]['parts'][0]['nodeId'],'h:child0')
                self.assertEqual(result['runUsage'],raw['runUsage'])
                self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))

    def test_missing_source_keeps_the_existing_saved_projection(self):
        import pdf_new_concept_ver99_study as study
        raw={'strategy':'new-concept-v99','hierarchy':{'version':'old','nodes':[{'id':'old'}]},
             'sections':[{'parts':[concept('기존 설명',['missing'])]}]}
        with tempfile.TemporaryDirectory() as temp,patch.object(study,'hierarchy',hierarchy):
            result=study.display_saved(Path(temp),{'pages':[]},raw)
        self.assertEqual(result['hierarchy'],raw['hierarchy'])

    def test_rollout_gate_keeps_installed_workers_and_paid_cache_identity_unchanged(self):
        script=('import json,pdf_new_concept_ver99_study as s;'
                'print(json.dumps([s.hierarchy.VERSION,s.identity({"documentId":"d","fingerprint":"fp"},'
                '"new-concept-v99","gpt-6-luna","document",0),s.teaching_identity(),s.planner_identity("gpt-6-luna")]))')
        values=[]
        for enabled in [False,True]:
            env=os.environ.copy();env.pop('SYNESIS_LOCAL_HIERARCHY',None)
            if enabled:env['SYNESIS_LOCAL_HIERARCHY']='7'
            env['PYTHONPATH']=str(Path(__file__).parent)
            values.append(json.loads(subprocess.check_output([sys.executable,'-c',script],env=env,text=True)))
        self.assertEqual([v[0]for v in values],['study-hierarchy-5','study-hierarchy-7'])
        self.assertEqual(values[0][1:],values[1][1:])

    def test_native_title_projection_never_leaks_into_generation_jobs_or_payload(self):
        import pdf_new_concept_ver99_study as study
        from pdf_native_heading_structure import supplement
        blocks=[layout('whole','원문 제목\n원래 PDF의 전체 본문이에요.',font=None,kind='visual',top=0)]
        blocks[0].update(bbox=[0,0,1,1],hasVisual=True)
        original=copy.deepcopy(blocks);jobs_before=study.jobs_for([{'title':'기존 묶음','blocks':blocks}])
        payload_before=study.teaching_payload(jobs_before[0],[],{},[])
        with tempfile.TemporaryDirectory() as temp:
            native=copy.deepcopy(blocks)
            native[0]['nativeHeading']={'title':'원문 제목','fontSize':30,'bodyFontSize':18,'bold':True,'bbox':[.1,.08,.7,.13]}
            with patch('pdf_native_heading_structure.supplement',return_value=native),patch.object(study,'hierarchy',hierarchy):
                headings=study.display_source_headings(Path(temp),blocks)
        self.assertEqual(headings[0]['title'],'원문 제목')
        self.assertEqual(blocks,original)
        jobs_after=study.jobs_for([{'title':'기존 묶음','blocks':blocks}])
        self.assertEqual(jobs_before,jobs_after)
        self.assertEqual(payload_before,study.teaching_payload(jobs_after[0],[],{},[]))


if __name__=='__main__':unittest.main()
