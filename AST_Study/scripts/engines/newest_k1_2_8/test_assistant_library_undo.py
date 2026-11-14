"""Latest library recovery and context privacy without API calls."""
import unittest
from assistant_protocol import run
from assistant_efficiency import model_context
from home_assistant import SYSTEM, MAX_OUTPUT
from test_assistant_protocol import Host, Model, tools, action

class LibraryUndoTests(unittest.TestCase):
    def test_main_response_undoes_library_without_unrelated_planner(self):
        q='다시 되돌려줘';host=Host();host.context.update(mutationScope='',recoveryInterpretationEligible=True,undo={'id':'latest-files','domain':'library','available':True,'at':1,'context':{'request':'옛 수업 자료 삭제해줘','session':'s','changes':[{'operation':'trash','kind':'document','id':'doc'}]}},library={'available':True,'semanticAuthorization':True,'authorizationQuote':''})
        response=tools(action('actions.undo',{'id':'latest-files'},identifier='undo'));response['recoveryIntent']={'intent':'undo','clear':True,'evidence':q};response['completeAfterLocal']=True
        model=Model(response);calls=[]
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='internal.recoveryIntent':
                self.assertEqual('latest-files',args['id']);host.context.update(mutationScope='undo',authorizationQuote=q,recoveryInterpretationEligible=False,recoveryDecision='undo');return {'ok':True,'data':{'intent':'undo'}}
            if tool=='actions.undo':
                self.assertEqual(q,quote);return {'ok':True,'data':{'undone':True,'domain':'library'}}
            return host(tool,args,quote)
        answer,effects=run({'question':q},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(['actions.undo'],[e['tool']for e in effects]);self.assertIn('파일 작업',answer);self.assertNotIn('플래너',answer);self.assertEqual(1,len(model.calls));self.assertNotIn('planner.apply',calls)
    def test_stale_other_session_or_consumed_details_not_sent_to_model(self):
        for eligible,available,scopes in [(False,True,''),(False,False,'undo'),(False,False,'')]:
            data=model_context({'recoveryInterpretationEligible':eligible,'mutationScope':scopes,'undo':{'available':available,'domain':'planner','id':'old','context':{'request':'오래된 민감한 일정'},'at':1}})
            self.assertNotIn('context',data['undo']);self.assertNotIn('domain',data['undo']);self.assertNotIn('id',data['undo'])
    def test_other_conversation_is_hidden_even_for_direct_undo_words(self):
        data=model_context({'mutationScope':'undo','undo':{'sameSession':False,'available':True,'domain':'planner','id':'old','context':{'request':'다른 대화의 일정'}}})
        self.assertEqual({'available':False},data['undo'])
    def test_irrelevant_none_intent_does_not_block_ordinary_conversation(self):
        host=Host();host.context['recoveryInterpretationEligible']=False
        response=tools();response.update(next='respond',answer='반가워요!',localRequests=[],recoveryIntent={'intent':'none','clear':True,'evidence':''})
        answer,effects=run({'question':'안녕'},Model(response),SYSTEM,MAX_OUTPUT,host)
        self.assertEqual('반가워요!',answer);self.assertEqual([],effects)
    def test_library_recovery_projection_is_bounded(self):
        data=model_context({'recoveryInterpretationEligible':True,'undo':{'available':True,'domain':'library','id':'current','at':1,'context':{'session':'s','turn':'t','request':'파일 정리','changes':[{'operation':'trash','kind':'document','id':str(i)} for i in range(100)]}}})['undo']
        self.assertEqual(12,len(data['context']['changes']));self.assertEqual(100,data['context']['changeCount']);self.assertTrue(data['context']['changesTruncated']);self.assertNotIn('session',data['context'])

if __name__=='__main__':unittest.main()
