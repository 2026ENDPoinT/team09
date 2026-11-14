"""Trash protocol/host-rejection flow, without API calls or real user data."""
import copy
import unittest
from assistant_protocol import run, allowed_tools, validate_envelope, TOOLS
from assistant_efficiency import model_context, model_result
from home_assistant import SYSTEM, MAX_OUTPUT
from test_assistant_protocol import Host, Model, tools, action

class TrashTests(unittest.TestCase):
    def replay(self, blocked=False):
        question='수업 자료와 옛 과제는 지워줘'
        intent={'decision':'request','evidence':question,'operations':['trash'],'sourceScope':'all','selectionAll':False,'proposalId':'','clarificationId':''}
        query=tools(action('library.query',{},identifier='q'));query['libraryIntent']=intent
        args={'ids':[{'kind':'document','id':'doc'},{'kind':'folder','id':'folder'}],'expectedRevision':'rev'}
        trash=tools(action('library.trash',args,identifier='t'));trash['libraryIntent']=intent;trash['completeAfterLocal']=True
        validate_envelope(trash)
        model=Model(query,trash);host=Host();host.context.update(mutationScope='',library={'available':True,'semanticAuthorization':True,'authorizationQuote':''});calls=[]
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='internal.libraryIntent':
                self.assertEqual(['trash'],args['operations']);host.context['mutationScope']='libraryWrite';host.context['library']['authorizationQuote']=question;return {'ok':True,'data':{'decision':'request'}}
            if tool=='library.query':return {'ok':True,'data':{'revision':'rev','items':[{'kind':'document','id':'doc','trashed':blocked}],'hasMore':False}}
            if tool=='library.trash':
                self.assertEqual(question,quote)
                if blocked:return {'ok':False,'code':'library_manual_delete_required','error':'휴지통에서 직접 ‘영구 삭제하기’를 눌러 주세요.'}
                return {'ok':True,'data':{'applied':True,'trashedCount':2,'moved':[{'id':'doc','parentId':'synesis-trash'}],'destinationPath':'홈화면 > 휴지통'}}
            return host(tool,args,quote)
        answer,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(2,len(model.calls));self.assertEqual(1,calls.count('library.trash'));return answer,effects
    def test_committed_trash_finishes_without_extra_model_call(self):
        answer,effects=self.replay();self.assertEqual(['library.trash'],[e['tool'] for e in effects]);self.assertIn('2개 항목을 휴지통',answer)
    def test_native_manual_refusal_stops_without_retry(self):
        answer,effects=self.replay(True);self.assertEqual([],effects);self.assertIn('직접',answer);self.assertNotIn('이동했어요',answer)
    def test_no_permanent_delete_tool(self):
        catalog=allowed_tools({'library':{'available':True,'semanticAuthorization':True},'mutationScope':''})
        self.assertIn('library.trash',catalog);self.assertNotIn('library.delete',catalog);self.assertNotIn('library.permanentlyDelete',TOOLS)
    def test_token_projection_preserves_trash_facts(self):
        row={'id':'d','kind':'document','name':'과제','trashed':True};folder={'id':'synesis-trash','kind':'folder','name':'휴지통','systemTrash':True,'trashed':False}
        context=model_context({'library':{'visibleItems':[row,folder],'currentFolderInTrash':True}})
        self.assertTrue(context['library']['visibleItems'][0]['trashed']);self.assertTrue(context['library']['visibleItems'][1]['systemTrash']);self.assertTrue(context['library']['currentFolderInTrash'])
        projected=model_result({'request':{'tool':'library.query','arguments':{}},'result':{'ok':True,'data':{'items':[row,folder]}}})
        self.assertTrue(projected['result']['data']['items'][0]['trashed'])
        projected=model_result({'request':{'tool':'library.trash','arguments':{}},'result':{'ok':True,'data':{'trashedCount':2}}})
        self.assertEqual(2,projected['result']['data']['trashedCount'])

if __name__=='__main__':unittest.main()
