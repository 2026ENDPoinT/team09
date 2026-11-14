"""Numbered unit continuity, independent of topic words and paid generation."""
import copy
import unittest
from unittest.mock import patch

import pdf_study_hierarchy as h
from pdf_source_units import continue_units, VERSION
from test_pdf_numbering_context import block,heading


def fixture():
    blocks=[block('root','1. 큰 단원',kind='heading',font=34,y=.05),
            block('u1','1) 첫 원리',kind='heading',font=26,y=.2),
            block('a','❖ 원리의 조건',kind='heading',font=26,y=.3),
            block('ab','• 원리의 조건을 충분히 설명해요.',x=.13,y=.4),
            block('u2','2) 다음 원리',page=3,font=26,y=.1),
            block('b','참고 원리\n• 본문 설명을 충분히 포함해요.',page=3,kind='visual',font=None,x=.03,y=.2),
            block('c','❖ 적용과 결과',page=4,kind='heading',font=24,y=.1),
            block('cb','• 적용되는 범위와 결과에 대한 설명이에요.',page=4,x=.13,y=.3),
            block('u3','3) 마지막 원리',page=5,kind='heading',font=26,y=.1),
            block('d','❖ 정리할 내용',page=6,kind='heading',font=26,y=.1),
            block('db','• 마지막 원리의 내용과 조건을 설명해요.',page=6,x=.13,y=.3)]
    blocks[5]['nativeHeading']={'fontSize':24,'bbox':[.09,.25,.6,.29]}
    baseline=[heading('root',kind='numbered',end='db',end_page=6),
        heading('u1','h:root',title='1) 첫 원리',level=2,kind='list'),
        heading('a','h:root',title='원리의 조건',level=2,kind='marked',end='ab'),
        heading('u2','h:root',title='2) 다음 원리',page=3,level=2,kind='title'),
        heading('b','h:root',title='참고 원리',page=3,level=2,kind='title'),
        heading('c','h:root',title='적용과 결과',page=4,level=2,kind='marked',end='cb'),
        heading('u3','h:root',title='3) 마지막 원리',page=5,level=2,kind='list'),
        heading('d','h:root',title='정리할 내용',page=6,level=2,kind='marked',end='db',end_page=6)]
    return blocks,h.span_headings(baseline,blocks)


class SourceUnitTests(unittest.TestCase):
    def test_numbered_units_own_their_subheadings_across_pages(self):
        blocks,heads=fixture();before=copy.deepcopy((blocks,heads))
        with patch('socket.socket.connect',side_effect=AssertionError('No API')):
            nodes=continue_units(blocks,heads)
        known={n['id']:n for n in nodes}
        for child,parent in [('a','u1'),('b','u2'),('c','u2'),('d','u3')]:
            self.assertEqual(known['h:'+child]['parentId'],'h:'+parent)
        self.assertEqual(known['h:u2']['endBlockId'],'cb')
        self.assertEqual(known['h:u2']['sourceUnit']['version'],VERSION)
        self.assertEqual((blocks,heads),before)
        pos={b['id']:i for i,b in enumerate(blocks)}
        for n in nodes:
            if n.get('parentId'):
                self.assertLessEqual(pos[n['endBlockId']],pos[known[n['parentId']]['endBlockId']])

    def test_generated_job_boundaries_do_not_close_a_proven_source_unit(self):
        blocks,heads=fixture();nodes=continue_units(blocks,heads)
        raw={'sections':[
            {'title':'첫 생성 단위','visualPages':[1],'parts':[{'title':'첫 설명','body':'저장된 첫 설명','evidence':[{'sourceId':'ab','page':1}]}]},
            {'title':'다른 이름의 생성 단위','visualPages':[3],'parts':[{'title':'본문','body':'저장된 본문','evidence':[{'sourceId':'b','page':3}]}]},
            {'title':'다음 생성 단위','visualPages':[4],'parts':[{'title':'적용','body':'저장된 적용','evidence':[{'sourceId':'cb','page':4}]}]}],
             'runUsage':{'requests':3,'usageBasedUsd':.03}}
        before=copy.deepcopy(raw);value=h.decorate(raw,blocks,nodes)
        known={n['id']:n for n in value['hierarchy']['nodes']}
        for section in value['sections'][1:]:
            node=known[section['parts'][0]['nodeId']];path=[]
            while node:path.append(node['id']);node=known.get(node.get('parentId'))
            self.assertIn('h:u2',path)
        self.assertEqual([s['parts'][0]['body'] for s in value['sections']],[s['parts'][0]['body']for s in before['sections']])
        self.assertEqual(value['runUsage'],before['runUsage']);self.assertEqual(raw,before)

    def test_single_unconfirmed_number_font_changes_and_columns_do_not_merge(self):
        for alteration in ('missing-first','font','column'):
            blocks,heads=fixture()
            if alteration=='missing-first':
                heads=[n for n in heads if n['id']!='h:u1']
            elif alteration=='font':blocks[4]['fontSize']=35;blocks[8]['fontSize']=42
            else:blocks[4]['zoneBounds']=[.5,0,1,1];blocks[8]['zoneBounds']=[.5,0,1,1]
            nodes=continue_units(blocks,heads)
            self.assertTrue(all(n.get('structuralRole')!='numbered_unit' for n in nodes),alteration)

    def test_outdented_heading_is_a_boundary_not_a_previous_unit_child(self):
        blocks,heads=fixture();blocks[6]['bbox'][0]=.01
        nodes={n['id']:n for n in continue_units(blocks,heads)}
        self.assertEqual(nodes['h:c']['parentId'],'h:root')
        self.assertEqual(nodes['h:u2']['endBlockId'],'b')

    def test_bounded_numbered_labels_and_explicit_decimal_edges_are_preserved(self):
        blocks,heads=fixture()
        for n in heads:
            if n['id'] in ('h:u1','h:u2','h:u3'):
                n['bounded']=True;n['structuralRole']='numbered_heading'
        self.assertEqual(continue_units(blocks,heads),heads)

    def test_full_source_pipeline_keeps_same_font_marker_below_the_numbered_unit(self):
        blocks,heads=fixture();blocks[5]['nativeHeading']['title']='관찰된 원리'
        nodes={n['id']:n for n in h.source_headings(blocks)}
        self.assertEqual(nodes['h:a']['parentId'],'h:u1')
        self.assertEqual(nodes['h:b']['parentId'],'h:u2')
        self.assertEqual(nodes['h:c']['parentId'],'h:u2')


if __name__=='__main__':unittest.main()
