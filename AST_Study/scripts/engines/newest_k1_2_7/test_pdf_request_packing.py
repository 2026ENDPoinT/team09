"""Offline request packing regressions; no model or review pipeline."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import pdf_new_concept_ver99_study as study
from pdf_study_cache_reuse import reusable_reply


def block(identity, text, page=1, kind='text'):
    return {'id':identity,'page':page,'kind':kind,'text':text,'zone':0,
            'bbox':[.1,.1,.9,.9],'hasVisual':False,'visualOnly':False,'planRole':'teaching'}


class RequestPackingTests(unittest.TestCase):
    def dense_group(self):
        blocks=[block('intro','손익계산서: '+'일정 기간의 손익을 설명해요. '*12),
                block('parent','기업의 네 가지 비용')]
        blocks += [block(str(i),chr(ord('①')+i-1)+' '+name+': '+'비용의 뜻을 설명해요. '*6,
                         1 if i<3 else 2)
                   for i,name in enumerate(('매출원가','판매관리비','지급이자','세금'),1)]
        blocks += [block('profit'+str(i),name+': '+'의미와 계산 관계를 설명해요. '*12,2)
                   for i,name in enumerate(('영업이익','EBIT','EBT','당기순이익','배당성향'))]
        return {'title':'손익계산서','blocks':blocks}

    def test_cross_page_classification_remains_in_one_request(self):
        group=self.dense_group();jobs=study.jobs_for([group])
        self.assertEqual(study.generation_cuts(group),{'4'})
        self.assertEqual(len(jobs),2)
        self.assertTrue({'parent','1','2','3','4'}.issubset({b['id'] for b in jobs[0]['blocks']}))
        self.assertEqual([b['id'] for j in jobs for b in j['blocks']],
                         [b['id'] for b in group['blocks']])
        self.assertEqual({j['topicIndex'] for j in jobs},{0})
        self.assertEqual({j['title'] for j in jobs},{group['title']})

    def test_small_request_is_unchanged(self):
        group=self.dense_group()
        for b in group['blocks']:b['text']=b['text'].split(':')[0]+': 뜻이에요.'
        self.assertEqual(study.generation_cuts(group),set())
        self.assertEqual(len(study.jobs_for([group])),1)

    def test_incomplete_classification_is_not_split(self):
        group=self.dense_group();group['blocks']=[b for b in group['blocks'] if b['id']!='3']
        self.assertEqual(study.generation_cuts(group),set())
        self.assertEqual(len(study.jobs_for([group])),1)

    def test_numbered_independent_headings_do_not_create_or_merge_topics(self):
        first={'title':'미분방정식','blocks':[block('a','3. 미분방정식',kind='heading'),
                    block('b','미분방정식: '+'원리를 설명해요. '*30)]}
        second={'title':'고차미분방정식','blocks':[block('c','4. 고차미분방정식',kind='heading'),
                    block('d','고차미분방정식: '+'다른 원리를 설명해요. '*30)]}
        jobs=study.jobs_for([first,second])
        self.assertEqual([(j['title'],j['topicIndex']) for j in jobs],
                         [('미분방정식',0),('고차미분방정식',1)])

    def test_derivation_with_variable_definitions_stays_whole(self):
        group={'title':'유도 과정','blocks':[block('parent','네 가지 변수')]+[
            block(str(i),chr(ord('①')+i-1)+f' x{i}: '+'유도에 쓰는 변수예요. '*10)
            for i in range(1,5)]+[block('result'+str(i),'결과: '+'식의 관계를 설명해요. '*10)
                                   for i in range(3)]}
        self.assertEqual(study.generation_cuts(group),set())
        self.assertEqual(len(study.jobs_for([group])),1)

    def test_intervening_table_or_continued_explanation_is_not_cut(self):
        for kind,text,visual in [('visual','',True),('caption','비용을 비교한 표예요.',False),
                                  ('text','위 항목들의 관계를 설명해요.',False)]:
            with self.subTest(kind=kind):
                group=self.dense_group();extra=block('table',text,2,kind)
                extra['hasVisual']=visual;group['blocks'].insert(6,extra)
                self.assertEqual(study.generation_cuts(group),set())

    def test_unicode_count_and_page_footer_do_not_cut_cross_page_members(self):
        group=self.dense_group();group['blocks'][1]['text']='기업이 발생시키는 𝟒 가지 종류의 비용'
        group['blocks'].insert(4,block('footer','47',1))
        self.assertEqual(study.generation_cuts(group),{'4'})
        self.assertEqual(len(study.jobs_for([group])),2)

    def test_arabic_numbered_classification_is_supported(self):
        group=self.dense_group()
        for b in group['blocks']:
            if b['id'].isdigit():b['text']=b['id']+'. '+b['text'][2:]
        self.assertEqual(study.generation_cuts(group),{'4'})

    def test_duplicate_or_reset_numbering_is_not_an_atomic_classification(self):
        for prefix in ('①','③'):
            group=self.dense_group();group['blocks'][3]['text']=prefix+group['blocks'][3]['text'][1:]
            self.assertEqual(study.generation_cuts(group),set())

    def test_transport_packing_does_not_mutate_saved_groups(self):
        group=self.dense_group();before=copy.deepcopy(group)
        study.jobs_for([group])
        self.assertEqual(group,before)

    def test_split_requests_keep_later_profit_definitions_as_background(self):
        group=self.dense_group()
        for b in group['blocks']:b['headingId']='income-statement'
        jobs=study.jobs_for([group]);positions={b['id']:i for i,b in enumerate(group['blocks'])}
        context=study.job_neighbors(group['blocks'],jobs[0],positions)
        self.assertTrue(any('EBIT' in b['text'] for b in context))
        self.assertTrue(all(b['backgroundOnly'] for b in context))
        self.assertNotIn('profit1',{b['id'] for b in jobs[0]['blocks']})

    def test_old_short_context_reply_is_not_reused_after_context_expands(self):
        job=study.jobs_for([self.dense_group()])[0];old={**job}
        old.pop('contextDepth')
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/('response-'+old['id']+'.json')).write_text(json.dumps({'concepts':[]}))
            self.assertEqual(reusable_reply(tmp,[old],job),(None,None))
            old['contextDepth']=job['contextDepth']
            self.assertIsNotNone(reusable_reply(tmp,[old],job)[0])

    def test_split_replies_assemble_back_into_one_ui_topic(self):
        group=self.dense_group();jobs=study.jobs_for([group])
        document={'documentId':'doc','fingerprint':'fp','pages':[{'label':'1'},{'label':'2'}]}
        done={}
        for i,job in enumerate(jobs):
            raw={'concepts':[{'title':['네 가지 비용','이익 단계'][i],
                'definition':'뜻을 설명해요.','explanation':'관계를 설명해요.',
                'easyExplanation':'쉬운 말로 설명해요.','blockIds':[b['id'] for b in job['blocks']]}]}
            done[i]=study.validate(raw,job,document)
        result=study.assemble(document,'new-concept-v99','document',0,[1,2],jobs,done,[],[])
        self.assertTrue(result['processingComplete'])
        self.assertEqual(len(result['sections']),1)
        self.assertEqual(result['sections'][0]['title'],group['title'])
        self.assertEqual([p['title'] for p in result['sections'][0]['parts']],['네 가지 비용','이익 단계'])


if __name__=='__main__':unittest.main()
