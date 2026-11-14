"""Structured batch rename flow and success/error reporting; no API or user data."""
import copy
import unittest
from assistant_protocol import run,allowed_tools,validate_envelope
from home_assistant import SYSTEM,MAX_OUTPUT
from test_assistant_protocol import Host,Model,tools,action

class RenameProtocolTests(unittest.TestCase):
    def replay(self,fail=False):
        q='자료1.pdf는 수학.pdf로, 영어 폴더는 단어로 이름을 바꿔줘'
        intent={'decision':'request','evidence':q,'operations':['rename'],'sourceScope':'all','selectionAll':False,'proposalId':'','clarificationId':''}
        query=tools(action('library.query',{},identifier='q'));query['libraryIntent']=intent
        changes=[{'kind':'document','id':'doc','name':'수학.pdf'},{'kind':'folder','id':'folder','name':'단어'}]
        rename=tools(action('library.rename',{'expectedRevision':'rev','changes':changes},identifier='rename'));rename['libraryIntent']=intent;rename['completeAfterLocal']=True
        model=Model(query,rename);host=Host();host.context.update(mutationScope='',library={'available':True,'semanticAuthorization':True,'authorizationQuote':''});calls=[]
        def local(tool,args,quote):
            calls.append((tool,copy.deepcopy(args),quote))
            if tool=='internal.libraryIntent':
                host.context['library']['authorizationQuote']=q;host.context['mutationScope']='libraryWrite';return {'ok':True,'data':{'decision':'request'}}
            if tool=='library.query':return {'ok':True,'data':{'revision':'rev','items':[{'kind':'document','id':'doc','name':'자료1.pdf'},{'kind':'folder','id':'folder','name':'영어'}],'hasMore':False}}
            if tool=='library.rename':
                self.assertEqual(q,quote);self.assertEqual(changes,args['changes'])
                if fail:return {'ok':False,'code':'library_validation','error':'같은 위치에 같은 이름의 파일이 이미 있어요.'}
                return {'ok':True,'data':{'applied':True,'renamedCount':2,'renamed':[{'oldName':'자료1.pdf','name':'수학.pdf'},{'oldName':'영어','name':'단어'}]}}
            return host(tool,args,quote)
        answer,effects=run({'question':q},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(2,len(model.calls));self.assertEqual(1,sum(c[0]=='library.rename'for c in calls))
        return answer,effects
    def test_single_batch_and_host_confirmed_completion(self):
        answer,effects=self.replay()
        self.assertEqual(['library.rename'],[e['tool']for e in effects]);self.assertIn('자료1.pdf → 수학.pdf',answer);self.assertIn('영어 → 단어',answer)
    def test_collision_stops_without_retry_or_false_success(self):
        answer,effects=self.replay(True)
        self.assertEqual([],effects);self.assertIn('이미 있어요',answer);self.assertNotIn('변경 완료',answer)
    def test_catalog_stays_host_scoped(self):
        self.assertNotIn('library.rename',allowed_tools({'mutationScope':'libraryWrite'}))
        self.assertIn('library.rename',allowed_tools({'mutationScope':'','library':{'available':True,'semanticAuthorization':True}}))

if __name__=='__main__':unittest.main()
