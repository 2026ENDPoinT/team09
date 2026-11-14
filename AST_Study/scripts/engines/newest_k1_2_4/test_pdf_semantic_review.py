import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_semantic_review import apply_edits, review, consolidate_cards, normalize_inline_math


class ReviewTests(unittest.TestCase):
    def topic(self):
        part={'title':'돌림힘','body':'수직인 힘의 돌림힘은 \\(rF\\)예요.',
              'easyExplanation':'잘못된 비유예요.','evidence':[{'sourceId':'b1','page':8}],
              'coveredElementIds':['b1'],'standardKnowledgeUsed':True}
        return {'unitId':'u','parentId':'p','coveredBlockIds':['b1'],
                'summary':{'title':'돌림힘','parts':[part],'body':part['body']},'concepts':[]}

    def test_correction_preserves_source_and_unmodified_teaching(self):
        original=self.topic();before=copy.deepcopy(original)
        fixed=apply_edits(original,{'checks':[{'target':'part','index':0,'issue':''}], 'edits':[{'target':'part','index':0,'field':'easyExplanation',
                         'replacement':'추가 예시: 렌치의 긴 손잡이를 수직으로 밀면 같은 힘으로 더 큰 돌림힘을 만들어요.',
                         'reason':'직선 운동을 회전에 비유한 오류를 고쳐요.'}]})
        self.assertEqual(original,before)
        self.assertEqual(fixed['summary']['parts'][0]['evidence'],original['summary']['parts'][0]['evidence'])
        self.assertEqual(fixed['coveredBlockIds'],['b1'])
        self.assertEqual(fixed['summary']['body'],original['summary']['body'])
        self.assertEqual(fixed['teachingReview']['status'],'reviewed')

    def test_invalid_target_and_damaged_replacement_cannot_publish(self):
        for field,text in [('evidence','b2'),('easyExplanation','손상된 \x1b[math]예요.')]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                apply_edits(self.topic(),{'checks':[{'target':'part','index':0,'issue':''}], 'edits':[{'target':'part','index':0,'field':field,
                            'replacement':text,'reason':'수정'}]})

    def test_balanced_dollar_math_is_reused_without_changing_code_money_or_formula(self):
        text=r'기준점 $O$에서 $\tau=rF\sin\theta$예요. `$x$` 비용 $5 또는 $10. $$x^2$$'
        self.assertEqual(normalize_inline_math(text),
                         r'기준점 \(O\)에서 \(\tau=rF\sin\theta\)예요. `$x$` 비용 $5 또는 $10. $$x^2$$')
        response={'checks':[{'target':'part','index':0,'issue':'조건 보완'}],
                  'edits':[{'target':'part','index':0,'field':'body','replacement':r'돌림힘은 $\tau=rF\sin\theta$예요.',
                            'reason':'힘의 방향을 포함해요.'}]}
        fixed=apply_edits(self.topic(),response)
        self.assertEqual(fixed['summary']['parts'][0]['body'],r'돌림힘은 \(\tau=rF\sin\theta\)예요.')
        self.assertIn('$',response['edits'][0]['replacement'])

    def test_failed_review_retains_topic_and_reports_pending_but_cancel_propagates(self):
        class Provider:
            model='gpt-6-luna'
            error=RuntimeError('transport uncertain')
            def complete(self,*args,**kwargs):raise self.error
        with tempfile.TemporaryDirectory() as folder:
            p=Provider();result=review(Path(folder),p,{},self.topic())
            self.assertEqual(result['summary'],self.topic()['summary'])
            self.assertEqual(result['teachingReview']['status'],'pending')
            p.error=InterruptedError('cancelled')
            with self.assertRaises(InterruptedError):review(Path(folder),p,{},self.topic())

    def test_duplicate_card_merge_preserves_all_provenance_and_skips_unique_cards(self):
        card={'name':'돌림힘','definition':'회전 효과예요.','explanation':'조건이에요. 조건이에요.',
              'easyExplanation':'구체적인 예시예요.','example':'','confusion':'',
              'evidence':[{'sourceId':'a'},{'sourceId':'b'}],'consolidatedEntries':2}
        value={'concepts':[{'name':'돌림힘','entries':[card]},
                           {'name':'질량','entries':[{'name':'질량'}]}]}
        class Provider:
            model='gpt-6-luna'
            calls=[]
            def complete(self,payload,**kwargs):
                self.calls.append(payload)
                return {'checks':[{'target':'card','index':0,'issue':'같은 조건이 반복돼요.'}],
                        'edits':[{'target':'card','index':0,'field':'explanation',
                                  'replacement':'조건이에요.','reason':'동일 문장을 한 번만 유지해요.'}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Provider();fixed=consolidate_cards(Path(folder),p,value,[])
        self.assertEqual(len(p.calls),1)
        self.assertEqual(p.calls[0]['purpose'],'merge_repeated_card')
        self.assertNotIn('blocks',p.calls[0]['source'])
        self.assertEqual(fixed['concepts'][0]['entries'][0]['evidence'],card['evidence'])
        self.assertEqual(value['concepts'][0]['entries'][0]['explanation'],'조건이에요. 조건이에요.')
        self.assertEqual(fixed['conceptConsolidation']['pendingGroups'],[])

    def test_original_image_review_does_not_repeat_fallible_transcription(self):
        class Provider:
            model='gpt-6-luna'
            def complete(self,payload,**kwargs):
                self.payload=payload;self.images=kwargs['image']
                return {'checks':[{'target':'part','index':0,'issue':''}],'edits':[]}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source.pdf').write_bytes(b'mocked rendering')
            blocks=[{'id':str(n),'page':n,'text':'잘못 판독될 수 있는 해석','kind':'image'} for n in range(1,7)]
            p=Provider()
            with patch('pdf_page_analysis.render_page',side_effect=lambda f,n:{'page':n}):
                review(root,p,{'blocks':blocks},self.topic())
            pages=p.payload['source']['attachedPages']
            self.assertEqual(pages,[1,2,3,4])
            self.assertEqual(len(p.images),4)
            for b in p.payload['source']['blocks']:
                self.assertEqual('text' in b,b['page'] not in pages)


if __name__=='__main__':unittest.main()
