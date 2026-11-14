"""Offline numbered-label context contracts; no app, provider, or user-store writes."""
import copy
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

import pdf_study_hierarchy as hierarchy
from pdf_numbering_context import build_context


def block(identity, text, *, page=1, kind='text', font=18, x=.07, y=.2,
          zone=0, bounds=None):
    bounds=bounds or [0,0,1,1]
    return {'id':identity,'text':text,'page':page,'zone':zone,'zoneBounds':bounds,
            'kind':kind,'fontSize':font,'bbox':[bounds[0]+x*(bounds[2]-bounds[0]),
                bounds[1]+y*(bounds[3]-bounds[1]),bounds[0]+min(.95,x+.7)*(bounds[2]-bounds[0]),
                bounds[1]+min(.999,y+.03)*(bounds[3]-bounds[1])],
            'hasVisual':False,'visualOnly':False,'planRole':'teaching'}


def heading(identity, parent='', *, title='상위 주제', page=1, level=1,
            kind='title', end=None, end_page=None):
    return {'id':'h:'+identity,'parentId':parent,'title':title,'page':page,
            'level':level,'sourceKind':kind,'sourceHeading':True,
            'startBlockId':identity,'endBlockId':end or identity,'endPage':end_page or page}


def label(identity, ordinal, *, page=1, y=.3, font=17.63, x=.07,
          prefix=None, zone=0, bounds=None):
    title=f'{ordinal}) 관점 {ordinal}' if prefix is None else prefix
    return [block(identity,title,page=page,font=font,x=x,y=y,zone=zone,bounds=bounds),
            block(identity+'a','• 해당 관점의 조건과 작동 원리를 구체적으로 설명해요.',
                  page=page,font=22.07,x=x+.055,y=y+.065,zone=zone,bounds=bounds),
            block(identity+'b','• 같은 범위에서 적용되는 제한과 근거를 설명해요.',
                  page=page,font=22.07,x=x+.055,y=y+.115,zone=zone,bounds=bounds)]


def sequence():
    blocks=[block('root','❖ 공통 원리',kind='heading',font=30.82,y=.08)]
    for ordinal,y in [(1,.25),(2,.48),(3,.71)]:
        blocks.extend(label('n'+str(ordinal),ordinal,y=y,font=22.07 if ordinal==1 else 17.63))
    blocks.extend(label('n4',4,page=2,y=.12,font=22.07))
    blocks.extend(label('n5',5,page=2,y=.46))
    return blocks,[heading('root',title='공통 원리',end='n5b',end_page=2)]


def actual_number(value):
    return value[0] if isinstance(value,(tuple,list)) and len(value)==1 else value


class NumberingContextTests(unittest.TestCase):
    def assert_parent(self,context,identity,parent):
        self.assertIn(identity,context.parents)
        self.assertEqual(context.parents[identity],parent)

    def test_text_labels_continue_on_next_page_despite_different_fonts(self):
        blocks,baseline=sequence();context=build_context(blocks,baseline)
        for ordinal in range(1,6):
            self.assert_parent(context,'n'+str(ordinal),'h:root')
            state=context.states['n'+str(ordinal)]
            self.assertEqual(actual_number(state.ordinal),ordinal)
            self.assertEqual(state.parent_id,'h:root')
        self.assertTrue(context.states['n1'].scope_id);self.assertTrue(context.states['n5'].scope_id)

    def test_multiple_numbering_families_share_the_same_layout_contract(self):
        families=[('a. 첫 관점','b. 둘째 관점'),('(a) 첫 관점','(b) 둘째 관점'),
                  ('I. 첫 관점','II. 둘째 관점'),('Ⅰ. 첫 관점','Ⅱ. 둘째 관점'),
                  ('가. 첫 관점','나. 둘째 관점'),('① 첫 관점','② 둘째 관점'),
                  ('(1) 첫 관점','(2) 둘째 관점')]
        for first,second in families:
            with self.subTest(first=first):
                blocks=[block('root','1. 분류',kind='heading',font=32,y=.04)]
                blocks.extend(label('first',1,prefix=first,y=.25))
                blocks.extend(label('second',2,prefix=second,y=.6))
                context=build_context(blocks,[heading('root',title='1. 분류',kind='numbered',end='secondb')])
                self.assert_parent(context,'first','h:root');self.assert_parent(context,'second','h:root')
                self.assertEqual(actual_number(context.states['first'].ordinal),1)
                self.assertEqual(actual_number(context.states['second'].ordinal),2)

    def test_context_is_detached_immutable_and_deterministic(self):
        blocks,baseline=sequence();original_blocks=copy.deepcopy(blocks);original_baseline=copy.deepcopy(baseline)
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No network')):
            first=build_context(blocks,baseline);second=build_context(blocks,baseline)
        self.assertEqual(blocks,original_blocks);self.assertEqual(baseline,original_baseline)
        self.assertEqual(first.headings,second.headings);self.assertEqual(dict(first.parents),dict(second.parents))
        with self.assertRaises(TypeError):first.parents['n1']='h:other'
        with self.assertRaises(TypeError):first.closures['h:root']='n1'
        with self.assertRaises(TypeError):first.stats['_test']=1
        with self.assertRaises(AttributeError):first.states['n1'].parent_id='h:other'
        try:first.headings[0]['title']='detached test mutation'
        except TypeError:pass  # A stricter immutable node also satisfies the detached contract.
        self.assertEqual(baseline,original_baseline)

    def test_outdented_intro_and_reset_do_not_extend_a_weak_parent(self):
        blocks=[block('weak','참고 관점',kind='heading',font=28,y=.08)]
        blocks.extend(label('old1',1,y=.26,x=.13));blocks.extend(label('old2',2,y=.52,x=.13))
        blocks.append(block('intro','새로운 장치의 동작',page=2,x=.04,y=.1))
        blocks.extend(label('new1',1,page=2,x=.1,y=.3));blocks.extend(label('new2',2,page=2,x=.1,y=.58))
        context=build_context(blocks,[heading('weak',title='참고 관점',end='new2b',end_page=2)])
        self.assertIn('h:weak',context.closures)
        positions={b['id']:i for i,b in enumerate(blocks)}
        self.assertLess(positions[context.closures['h:weak']],positions['intro'])
        self.assertNotEqual(context.parents.get('new1'),'h:weak')

    def test_existing_decimal_parent_edges_are_never_reparented(self):
        blocks=[block('chapter','6. 단원',kind='heading',font=34,y=.04),
                block('first','6.1. 첫 주제',kind='heading',font=28,y=.14)]
        blocks.extend(label('soft1',1,y=.34));blocks.extend(label('soft2',2,y=.6))
        blocks.append(block('second','6.2. 다음 주제',page=2,kind='heading',font=28,y=.1))
        baseline=[heading('chapter',title='6. 단원',kind='numbered',end='second',end_page=2),
                  heading('first','h:chapter',title='6.1. 첫 주제',level=2,kind='numbered',end='soft2b'),
                  heading('second','h:chapter',title='6.2. 다음 주제',page=2,level=2,kind='numbered')]
        context=build_context(blocks,baseline);known={n['id']:n for n in context.headings}
        for original in baseline:self.assertEqual(known[original['id']]['parentId'],original['parentId'])
        self.assert_parent(context,'soft1','h:first');self.assert_parent(context,'soft2','h:first')

    def test_existing_numbered_sibling_anchor_keeps_its_original_parent(self):
        blocks=[block('root','1. 큰 주제',kind='heading',font=34,y=.04),
                block('first','1) 첫 관점',kind='heading',font=24,y=.22),
                block('firstbody','• 첫 관점의 구체적인 설명이에요.',x=.13,y=.3)]
        blocks.extend(label('second',2,page=2,y=.12));blocks.extend(label('third',3,page=2,y=.5))
        baseline=[heading('root',title='1. 큰 주제',kind='numbered',end='thirdb',end_page=2),
                  heading('first','h:root',title='1) 첫 관점',level=2,kind='list',end='firstbody')]
        context=build_context(blocks,baseline);known={n['id']:n for n in context.headings}
        self.assertEqual(known['h:first']['parentId'],'h:root')
        self.assert_parent(context,'second','h:root');self.assert_parent(context,'third','h:root')

    def test_nested_numbering_returns_to_outer_siblings(self):
        blocks=[block('root','1. 원리',kind='heading',font=32,y=.04)]
        blocks.extend(label('outer1',1,y=.15))
        blocks.extend(label('inner1',1,prefix='(1) 첫 세부',x=.15,y=.34))
        blocks.extend(label('inner2',2,prefix='(2) 둘째 세부',x=.15,y=.54))
        blocks.extend(label('outer2',2,y=.76))
        context=build_context(blocks,[heading('root',title='1. 원리',kind='numbered',end='outer2b')])
        self.assert_parent(context,'outer1','h:root');self.assert_parent(context,'outer2','h:root')
        self.assert_parent(context,'inner1','h:outer1');self.assert_parent(context,'inner2','h:outer1')

    def test_unconfirmed_outer_item_cannot_manufacture_a_nested_parent(self):
        blocks=[block('root','1. 원리',kind='heading',font=32,y=.04)]
        blocks.extend(label('outer1',1,y=.18))
        blocks.extend(label('inner1',1,prefix='(1) 첫 세부',x=.15,y=.4))
        blocks.extend(label('inner2',2,prefix='(2) 둘째 세부',x=.15,y=.66))
        context=build_context(blocks,[heading('root',kind='numbered',end='inner2b')])
        for identity in ['outer1','inner1','inner2']:self.assertNotIn(identity,context.parents)

    def test_weak_scope_closure_removes_nested_virtual_descendants_too(self):
        blocks=[block('weak','참고 관점',kind='heading',font=28,y=.04)]
        blocks.extend(label('old1',1,y=.22,x=.13));blocks.extend(label('old2',2,y=.53,x=.13))
        blocks.append(block('intro','새로운 장치의 동작',page=2,x=.04,y=.06))
        blocks.extend(label('new1',1,page=2,x=.1,y=.2));blocks.extend(label('new2',2,page=2,x=.1,y=.45))
        blocks.extend(label('inner1',1,page=2,prefix='(1) 첫 세부',x=.19,y=.64))
        blocks.extend(label('inner2',2,page=2,prefix='(2) 둘째 세부',x=.19,y=.81))
        context=build_context(blocks,[heading('weak',title='참고 관점',end='inner2b',end_page=2)])
        self.assertIn('h:weak',context.closures)
        known={node['id']:node for node in context.headings};positions={b['id']:i for i,b in enumerate(blocks)}
        for node in context.headings:
            if node.get('parentId'):self.assertIn(node['parentId'],known)
            self.assertLessEqual(positions[node['startBlockId']],positions[node['endBlockId']])
        for identity in ['new1','new2','inner1','inner2']:self.assertNotIn(identity,context.parents)

    def test_number_reset_under_strong_parent_starts_a_distinct_scope(self):
        blocks=[block('root','1. 원리',kind='heading',font=32,y=.04)]
        for identity,ordinal,y in [('a1',1,.18),('a2',2,.38),('b1',1,.58),('b2',2,.78)]:
            blocks.extend(label(identity,ordinal,y=y))
        context=build_context(blocks,[heading('root',kind='numbered',end='b2b')])
        for identity in ['a1','a2','b1','b2']:self.assert_parent(context,identity,'h:root')
        self.assertEqual(context.states['a1'].scope_id,context.states['a2'].scope_id)
        self.assertEqual(context.states['b1'].scope_id,context.states['b2'].scope_id)
        self.assertNotEqual(context.states['a1'].scope_id,context.states['b1'].scope_id)
        self.assertNotIn('h:root',context.closures)

    def test_closed_parent_also_bounds_existing_descendant_spans(self):
        from pdf_source_owner_index import SourceIndex
        blocks=[block('weak','❖ 공통 원리',kind='heading',font=30,y=.05)]
        blocks.extend(label('first',1,y=.2,x=.13));blocks.extend(label('second',2,y=.48,x=.13))
        blocks.extend(label('third',3,page=2,y=.12,x=.13))
        blocks.append(block('intro','새로운 장치의 동작',page=2,x=.04,y=.36))
        blocks.extend(label('new1',1,page=2,x=.1,y=.5));blocks.extend(label('new2',2,page=2,x=.1,y=.74))
        baseline=[heading('weak',kind='marked',end='new2b',end_page=2),
            heading('first','h:weak',title='1) 관점 1',kind='list',level=2,end='firstb'),
            heading('second','h:weak',title='2) 관점 2',kind='list',level=2,end='new2b',end_page=2)]
        context=build_context(blocks,baseline);known={n['id']:n for n in context.headings}
        positions={b['id']:i for i,b in enumerate(blocks)};index=SourceIndex(blocks,context.headings)
        self.assertEqual(context.closures['h:weak'],'thirdb')
        for node in context.headings:
            if node.get('parentId'):
                self.assertLessEqual(positions[node['endBlockId']],positions[known[node['parentId']]['endBlockId']])
        for identity in ('new1','new2'):
            self.assertIsNone(index.owner(identity));self.assertNotIn(identity,context.parents)
            self.assertNotIn(identity,context.states)
        for node in context.headings:
            if node.get('structuralRole')=='numbered_heading':
                self.assertEqual(node['numberingContext']['bodyEndBlockId'],node['endBlockId'])
                self.assertEqual(context.states[node['startBlockId']].body_end,node['endBlockId'])

    def test_inner_heading_does_not_steal_next_numbered_sibling(self):
        blocks=[block('root','1. 원리',kind='heading',font=32,y=.04),
                block('first','1) 첫 항목',kind='heading',font=24,y=.16),
                block('detail','▪ 세부 조건',kind='heading',font=20,x=.14,y=.29),
                block('detailbody','상세한 조건을 충분한 길이로 설명하는 본문이에요.',x=.19,y=.37)]
        blocks.extend(label('second',2,page=2,y=.12));blocks.extend(label('third',3,page=2,y=.5))
        baseline=[heading('root',kind='numbered',end='thirdb',end_page=2),
                  heading('first','h:root',title='1) 첫 항목',level=2,kind='list',end='detailbody'),
                  heading('detail','h:first',title='세부 조건',level=3,kind='marked',end='detailbody')]
        context=build_context(blocks,baseline)
        self.assert_parent(context,'second','h:root');self.assert_parent(context,'third','h:root')

    def test_two_page_gap_can_continue_but_unbounded_distant_labels_do_not(self):
        blocks=[block('root','참고 원리',kind='heading',font=32,y=.04),
                block('first','1) 첫 항목',kind='heading',font=24,y=.16),
                block('firstbody','• 첫 항목에 속하는 구체적인 설명이에요.',x=.13,y=.25),
                block('middle','▪ 상세 사례',page=2,kind='heading',font=20,x=.14,y=.2),
                block('middlebody','중간 페이지에서 기존 항목을 더 설명해요.',page=2,x=.19,y=.3)]
        blocks.extend(label('second',2,page=3,y=.12))
        baseline=[heading('root',title='참고 원리',end='secondb',end_page=3),
                  heading('first','h:root',title='1) 첫 항목',level=2,kind='list',end='middlebody',end_page=2),
                  heading('middle','h:first',title='상세 사례',page=2,level=3,kind='marked',end='middlebody')]
        context=build_context(blocks,baseline);self.assert_parent(context,'second','h:root')
        distant=copy.deepcopy(blocks)
        for b in distant:
            if b['id'].startswith('second'):b['page']=20
        distant_baseline=copy.deepcopy(baseline);distant_baseline[0]['endPage']=20
        context=build_context(distant,distant_baseline)
        self.assertNotEqual(context.parents.get('second'),'h:root')

    def test_missing_intervening_source_page_does_not_prove_continuation(self):
        blocks=[block('root','참고 원리',kind='heading',font=32,y=.04),
                block('first','1) 첫 항목',kind='heading',font=24,y=.16),
                block('firstbody','• 첫 항목의 구체적인 설명이에요.',x=.13,y=.25)]
        blocks.extend(label('second',2,page=3,y=.12))
        baseline=[heading('root',title='참고 원리',end='secondb',end_page=3),
                  heading('first','h:root',title='1) 첫 항목',level=2,kind='list',end='secondb',end_page=3)]
        context=build_context(blocks,baseline)
        self.assertNotIn('second',context.parents)

    def test_quiz_options_are_not_promoted_even_with_indented_explanations(self):
        blocks=[block('root','1. 학습 주제',kind='heading',font=32,y=.04),
                block('question','문제 1. 다음 중 옳은 답을 고르시오.',font=22,y=.2)]
        blocks.extend(label('option1',1,y=.35));blocks.extend(label('option2',2,y=.64))
        context=build_context(blocks,[heading('root',kind='numbered',end='option2b')])
        self.assertNotIn('option1',context.parents);self.assertNotIn('option2',context.parents)

    def test_sentence_lists_and_equations_are_not_promoted(self):
        for first,second in [('1) 처음에는 장치를 켜고 표시등을 확인해요.','2) 다음에는 전원을 끄고 정리해요.'),
                             ('1) x = y + z','2) y = z - x')]:
            with self.subTest(first=first):
                blocks=[block('root','1. 원리',kind='heading',font=32,y=.04)]
                blocks.extend(label('a',1,prefix=first,y=.25));blocks.extend(label('b',2,prefix=second,y=.6))
                context=build_context(blocks,[heading('root',kind='numbered',end='bb')])
                self.assertNotIn('a',context.parents);self.assertNotIn('b',context.parents)

    def test_small_bottom_footnotes_are_not_promoted(self):
        blocks=[block('root','1. 원리',kind='heading',font=32,y=.04)]
        for index in range(4):blocks.append(block('main'+str(index),'본문의 주요 조건을 충분히 설명하는 문장이에요.',y=.18+index*.14))
        for identity,ordinal,y in [('note1',1,.85),('note2',2,.93)]:
            blocks.append(block(identity,f'{ordinal}) 부연 항목',font=8,y=y))
            blocks.append(block(identity+'body','• 부연 설명',font=8,x=.13,y=y+.035))
        context=build_context(blocks,[heading('root',kind='numbered',end='note2body')])
        self.assertNotIn('note1',context.parents);self.assertNotIn('note2',context.parents)

    def test_vertical_two_up_panels_can_continue_one_numbering_scope(self):
        top=[0,0,1,.5];bottom=[0,.5,1,1]
        blocks=[block('root','❖ 공통 원리',kind='heading',font=30,zone=0,bounds=top,y=.04)]
        blocks.extend(label('n1',1,zone=0,bounds=top,y=.2));blocks.extend(label('n2',2,zone=0,bounds=top,y=.6))
        blocks.extend(label('n3',3,zone=1,bounds=bottom,y=.12));blocks.extend(label('n4',4,zone=1,bounds=bottom,y=.5))
        context=build_context(blocks,[heading('root',title='공통 원리',end='n4b')])
        for identity in ['n1','n2','n3','n4']:self.assert_parent(context,identity,'h:root')
        self.assertEqual(context.states['n1'].lane,context.states['n3'].lane)

    def test_side_by_side_columns_keep_independent_parent_and_numbering_state(self):
        blocks=[];baseline=[]
        for name,zone,bounds in [('left',0,[0,0,.48,1]),('right',1,[.52,0,1,1])]:
            blocks.append(block(name,name+' 주제',kind='heading',font=30,zone=zone,bounds=bounds,y=.05))
            blocks.extend(label(name+'1',1,zone=zone,bounds=bounds,y=.28))
            blocks.extend(label(name+'2',2,zone=zone,bounds=bounds,y=.62))
            baseline.append(heading(name,title=name+' 주제',end=name+'2b'))
        context=build_context(blocks,baseline)
        for name in ['left','right']:
            self.assert_parent(context,name+'1','h:'+name);self.assert_parent(context,name+'2','h:'+name)
        self.assertNotEqual(context.states['left1'].lane,context.states['right1'].lane)

    def test_projection_preserves_saved_prose_usage_and_paid_cache_identity(self):
        import pdf_new_concept_ver99_study as study
        blocks,baseline=sequence();document={'documentId':'fixture','fingerprint':'stable-source','pages':[{},{}]}
        identity=study.identity(document,'new-concept-v99','gpt-6-luna','document',0)
        raw={'runUsage':{'usageBasedUsd':.0123,'requests':3},'generationOperationId':'paid-original',
             'concepts':[{'term':'관점','definition':'원래 정의예요.'}],
             'sections':[{'title':'공통 원리','parts':[{'title':'첫 관점','body':'원래 설명 $$x+y$$',
                 'easyExplanation':'원래 쉬운 설명','evidence':[{'sourceId':'n1a','page':1}],'visualPages':[1]}]}]}
        original=copy.deepcopy(raw);context=build_context(blocks,baseline)
        projected=hierarchy.decorate(raw,blocks,context.headings)
        self.assertEqual(raw,original);self.assertEqual(projected['runUsage'],raw['runUsage'])
        self.assertEqual(projected['concepts'],raw['concepts'])
        self.assertEqual(projected['generationOperationId'],raw['generationOperationId'])
        for key in ['body','easyExplanation','evidence']:
            self.assertEqual(projected['sections'][0]['parts'][0][key],raw['sections'][0]['parts'][0][key])
        self.assertEqual(study.identity(document,'new-concept-v99','gpt-6-luna','document',0),identity)

    def test_existing_whole_page_visual_heading_refs_keep_legacy_body_voting(self):
        blocks=[block('a','첫 페이지의 제목과 전체 시각 자료',kind='visual',font=None,y=.02),
                block('b','둘째 페이지의 제목과 전체 시각 자료',page=2,kind='visual',font=None,y=.02),
                block('c','둘째 주제를 설명하는 별도 시각 자료',page=3,kind='visual',font=None,y=.02)]
        for value in blocks:value['hasVisual']=True
        baseline=[heading('a',title='첫 주제'),heading('b',title='둘째 주제',page=2,end='c',end_page=3)]
        # Existing native/whole-page heading blocks remain evidence-bearing
        # source bodies. Their titles must not erase a cross-topic comparison.
        owner,_=hierarchy.source_owner(['a','b','c'],blocks,baseline)
        self.assertIsNone(owner)

    @unittest.skipUnless(os.environ.get('SYNESIS_NUMBER_CONTEXT_CORPUS')=='1','opt-in saved corpus review')
    def test_existing_117_protected_source_relations(self):
        root=Path(__file__).resolve().parent.parent
        source=root/'build/local-hierarchy-numbering-state-analysis-20261028'
        baseline=json.loads((source/'protected-source-relations-with-numbered-anchors.json').read_text())
        snapshots=json.loads((source/'source-heading-snapshot.json').read_text())
        by_doc={row['documentId']:row for row in snapshots};current={};failures=[]
        for relation in baseline['relations']:
            doc=relation['documentId']
            if doc not in current:
                source_path=Path(by_doc[doc]['blocksSource'])
                if not source_path.is_file():
                    # User regeneration may retire an older cache identity.
                    # Match every protected anchor against the same PDF's
                    # current layout instead of silently skipping that PDF.
                    required={r[key].removeprefix('h:') for r in baseline['relations'] if r['documentId']==doc
                              for key in ('nodeId','parentId') if r.get(key)}
                    for candidate in sorted(source_path.parents[1].glob('*/blocks.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
                        values=json.loads(candidate.read_text())
                        if required.issubset({b['id'] for b in values}):source_path=candidate;break
                blocks=json.loads(source_path.read_text())
                current[doc]={node['id']:node for node in hierarchy.source_headings(blocks)}
            node=current[doc].get(relation['nodeId'])
            if not node or node['parentId']!=relation['parentId']:failures.append(relation)
        report={'relationsChecked':len(baseline['relations']),'documentsChecked':len(current),
                'changedProtectedRelations':failures,'apiCalls':0,'appUpdates':0}
        output=Path(os.environ.get('SYNESIS_NUMBER_CONTEXT_REPORT',str(root/'build/numbering-context-protected-relations.json')))
        if not output.resolve().is_relative_to((root/'build').resolve()):raise AssertionError('Report must stay inside workspace build/')
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        self.assertEqual(failures,[])


if __name__=='__main__':unittest.main()
