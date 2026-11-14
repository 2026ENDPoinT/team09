"""Separator compaction retains every value and the established paid-cache key."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pdf_json_wire import compact_request, label_images
from pdf_ai import Provider


class CompactWireTests(unittest.TestCase):
    def test_only_separator_whitespace_changes_including_math_and_unicode(self):
        payload={'task':'region_teaching','blocks':[{'id':'s0','text':'띄어  쓰기\n\\(x + y\\)\n| a | b |'}],
                 'neighboringContext':{'text':'  앞뒤 공백  '},'quote':'"인용" 😀'}
        body={'messages':[{'role':'system','content':'원래  지침'},
            {'role':'user','content':[{'type':'text','text':json.dumps(payload,ensure_ascii=False)},
                                    {'type':'image_url','image_url':{'url':'data:image/png;base64,original','detail':'high'}}]}],
              'response_format':{'original':'unchanged'},'metadata':{'request':'same'}}
        before=copy.deepcopy(body);value,saved=compact_request(body,payload['task'])
        self.assertGreater(saved,0);self.assertEqual(body,before)
        self.assertEqual(json.loads(value['messages'][1]['content'][0]['text']),payload)
        value['messages'][1]['content'][0]['text']=body['messages'][1]['content'][0]['text']
        self.assertEqual(value,body)

    def test_quiz_compaction_preserves_shared_targets_and_source_spacing(self):
        for task in ('quiz_plan', 'quiz_questions'):
            payload={'task':task,'sharedTargets':[['t1','ox',['c1'],'조건 비교']],
                     'sources':[{'sourceId':'s1','quotes':[{'quoteId':'q1','text':'원문  공백\\n그대로'}]}]}
            body={'messages':[{'role':'system','content':'공통 지침'},
                              {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]}
            original=copy.deepcopy(body)
            compact,saved=compact_request(body,task)
            self.assertGreater(saved,0)
            self.assertEqual(json.loads(compact['messages'][1]['content']),payload)
            self.assertEqual(body,original)

    def test_non_study_tasks_are_untouched(self):
        body={'messages':[{}, {'content':'not JSON'}]}
        self.assertEqual(compact_request(body,'tutor'),(body,0))

    def test_responses_and_text_only_routes_keep_their_own_framing(self):
        payload={'task':'region_groups','targets':[{'id':1,'text':'원문 전체'}]}
        for key,content in [('messages',json.dumps(payload)),('input',[{'type':'input_text','text':json.dumps(payload)}])]:
            with self.subTest(key=key):
                original={key:[{'content':'instructions'},{'content':content}]}
                value,saved=compact_request(original,'region_groups');self.assertGreater(saved,0)
                text=value[key][1]['content'];text=text if isinstance(text,str)else text[0]['text']
                self.assertEqual(json.loads(text),payload)

    def test_previous_paid_result_is_reused_after_wire_compaction(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return {'choices':[{'message':{'content':'{"concepts":[]}'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':10,'completion_tokens':5}}
        payload={'task':'region_teaching','blocks':[{'id':'s0','text':'원문'}]}
        with tempfile.TemporaryDirectory()as directory:
            folder=Path(directory)
            with patch('pdf_json_wire.compact_request',side_effect=lambda body,task:(body,0)):
                first=Provider(folder,True,.1,transport=transport).complete(payload)
            second=Provider(folder,True,.1,transport=transport).complete(payload)
            self.assertEqual(first,second);self.assertEqual(len(calls),1)

    def test_pair_labels_stay_with_exact_pixels_and_aliased_unit_sources(self):
        payload={'task':'region_teaching_batch','units':{
            'u0':{'crops':[{'page':18,'blockIds':['uaa']}]},
            'u1':{'crops':[{'page':32,'blockIds':['uba']}]}},
            'imageOrder':[{'unit':'u1','cropIndex':0},{'unit':'u0','cropIndex':0}]}
        images=[{'type':'image_url','image_url':{'url':'pixels-page-32'}},
                {'type':'image_url','image_url':{'url':'pixels-page-18'}}]
        body={'messages':[{'content':'same instructions'},
            {'content':[{'type':'text','text':json.dumps(payload)},*images]}]}
        before=copy.deepcopy(body);value,count=label_images(body,payload['task']);self.assertEqual(count,2)
        content=value['messages'][1]['content']
        self.assertEqual(content[2],images[0]);self.assertEqual(content[4],images[1]);self.assertEqual(body,before)
        self.assertEqual(json.loads(content[1]['text'].split(' ',2)[2]),
            {'unit':'u1','cropIndex':0,'pdfPage':32,'targetBlockIds':['uba']})
        self.assertEqual(json.loads(content[3]['text'].split(' ',2)[2])['pdfPage'],18)


if __name__=='__main__':unittest.main()
