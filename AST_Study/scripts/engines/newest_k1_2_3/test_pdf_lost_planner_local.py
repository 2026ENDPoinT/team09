"""A lost-ID planner can retain exact sources locally without another paid POST."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pdf_ai import Provider, AiResponseError, MissingPaidResponseError
import pdf_new_concept_ver99_study as study
from pdf_study_restart import local_planner_originals


class LostPlannerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name); (self.folder/'usage').mkdir()
        self.entry = {'requestId':'a'*32, 'state':'failed_or_uncertain', 'kind':'region_plan',
            'inputApi':'responses', 'payloadHash':'hash', 'pages':[1], 'maxOutputTokens':6000,
            'sentAtMs':1, 'requestUploadComplete':True, 'requestBodyBytesSent':100,
            'requestBodyBytesExpected':100, 'requestBodyBytes':100, 'reservedUsd':.018049,
            'responseCacheKey':'b'*64}
        self.path = self.folder/'usage/old.json'
        self.provider = SimpleNamespace(folder=self.folder, model='gpt-6-luna',
            ledger_path=self.folder/'usage/current.json', ledger={'model':'gpt-6-luna','requests':[]},
            context={'kind':'region_plan','strategy':'new-concept-v99', 'pages':[1],
                     'studyConnectionRepairAllowed':True})

    def save(self, entry=None):
        self.path.write_text(json.dumps({'model':'gpt-6-luna','requests':[entry or self.entry]}))

    def test_exact_original_metadata_does_not_authorize_resend_or_settle_usage(self):
        self.save(); before=self.path.read_bytes()
        result=local_planner_originals(self.provider,{'hash'},6000)
        self.assertEqual(result[0]['requestId'],'a'*32)
        self.assertEqual(result[0]['reservedUsd'],.018049)
        self.assertEqual(before,self.path.read_bytes())

    def test_unrelated_or_recoverable_originals_never_get_local_permission(self):
        for key,value in [('kind','region_study'),('inputApi','chat'),('state','settled'),
                          ('responseId','resp_original'),('maxOutputTokens',5000),('pages',[2]),
                          ('requestUploadComplete',False),('requestBodyBytesSent',99),
                          ('responseCacheKey','../bad')]:
            with self.subTest(key=key):
                self.save({**self.entry,key:value})
                self.assertEqual(local_planner_originals(self.provider,{'hash'},6000),[])
        self.save(); self.provider.context['kind']='region_study'
        self.assertEqual(local_planner_originals(self.provider,{'hash'},6000),[])

    def test_any_existing_native_or_partial_body_keeps_original_recovery_guard(self):
        self.save(); cache=self.folder/'generated/paid-responses'; cache.mkdir(parents=True)
        for suffix in ('.json','.raw.json','.responses.raw.json','.incomplete.json','.partial.json',
                       '.stream.partial.json'):
            with self.subTest(suffix=suffix):
                p=cache/('b'*64+suffix); p.write_text('{}')
                self.assertEqual(local_planner_originals(self.provider,{'hash'},6000),[]); p.unlink()

    def block(self, ident, page):
        return {'id':ident,'page':page,'kind':'text','text':'원문 정의와 조건',
                'bbox':[.1,.1,.9,.3],'zone':0,'visualOnly':False,'hasVisual':False}

    def test_real_provider_guard_recovers_partition_without_repeating_original_request(self):
        blocks=[self.block('a',1), self.block('b',1)]
        calls=[]
        def fail(body):
            calls.append(body); raise OSError('fixture lost headers')
        first=Provider(self.folder,True,.1,transport=fail)
        with self.assertRaises(AiResponseError):study.plan_groups(self.folder,first,blocks,self.folder)
        entry=first.ledger['requests'][0]
        entry.update({k:v for k,v in self.entry.items() if k in
            ('requestUploadComplete','requestBodyBytesSent','requestBodyBytesExpected','requestBodyBytes')})
        first.ledger_path.write_text(json.dumps(first.ledger)); before=first.ledger_path.read_bytes()
        second=Provider(self.folder,True,.1,transport=lambda body:self.fail('No second POST'))
        groups,warnings=study.plan_groups(self.folder,second,blocks,self.folder)
        self.assertEqual(len(calls),1); self.assertEqual(second.ledger['requests'],[])
        self.assertEqual(first.ledger_path.read_bytes(),before)
        self.assertEqual([b['id']for g in groups for b in g['blocks']],['a','b'])
        self.assertTrue(all(b['planRole']=='uncertain'for g in groups for b in g['blocks']))
        self.assertFalse(warnings)
        plan=json.loads((self.folder/'plan.json').read_text())
        self.assertTrue(study.usable_plan(plan,blocks=blocks))
        audit=plan['assignmentRecovery']; self.assertEqual(audit['semanticGroupingStatus'],'locally_recovered')
        self.assertEqual(audit['localUncertainBlockIds'],['a','b'])
        self.assertEqual(audit['windows'][0]['transportRecovery']['lostIdPlannerOriginals'][0]['requestId'],entry['requestId'])

    def test_only_missing_window_is_local_and_healthy_window_keeps_its_paid_assignment(self):
        blocks=[self.block('a',1),self.block('b',2)]; original=copy.deepcopy(blocks)
        error=MissingPaidResponseError('old lost planner'); error.local_planner_originals=[self.entry]
        def complete(*args,**kwargs):
            if provider.context['pages']==[1]:raise error
            return {'groups':[{'first':0,'last':0,'title':'기존 유료 묶음','role':'teaching'}]}
        provider=SimpleNamespace(model='gpt-6-luna',complete=complete)
        with patch.object(study,'PLAN_WINDOW_BLOCKS',1),patch.object(study,'study_workers',return_value=1):
            groups,_=study.plan_groups(self.folder,provider,blocks,self.folder)
        flat=[b for g in groups for b in g['blocks']]
        self.assertEqual([(b['id'],b['planRole'])for b in flat],[('a','uncertain'),('b','teaching')])
        self.assertEqual([{k:v for k,v in b.items()if k!='planRole'}for b in flat],original)


if __name__=='__main__': unittest.main()
