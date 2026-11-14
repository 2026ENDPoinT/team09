"""Fresh-chat replays of nested lookup and stale model evidence, without paid calls."""
import copy
import unittest
from assistant_protocol import run
from home_assistant import SYSTEM, MAX_OUTPUT
from test_assistant_protocol import Host, Model, tools, action, final


def intent(question, operations=None, scope='all', decision='request'):
    return {'decision':decision,'evidence':question,'operations':operations or ['open'],
            'sourceScope':scope,'selectionAll':False,'proposalId':'','clarificationId':''}


class FreshChatTests(unittest.TestCase):
    def host(self):
        host=Host();host.context.update(library={'available':True,'semanticAuthorization':True,
            'authorizationQuote':'','currentFolderId':'','currentPath':'홈화면','visibleItems':[]})
        return host

    def test_lookup_can_refine_scope_before_first_real_action_and_bind_current_request(self):
        question='프입 24기출좀 열어달라니까?';stale='프입 24기출좀 열어줘'
        first=tools(action('library.query',{'query':'24기출','parentId':'course-folder'}));first['libraryIntent']=intent(stale,scope='current')
        second=tools(action('library.query',{'query':'2024','kind':'document'}));second['libraryIntent']=intent(stale)
        opened=tools(action('library.open',{'kind':'document','id':'exam-2024','expectedRevision':'r1'}));opened.update(libraryIntent=intent(stale),completeAfterLocal=True)
        host=self.host();calls=[]
        def local(tool,args,quote):
            calls.append((tool,copy.deepcopy(args),quote))
            if tool=='internal.libraryIntent':
                self.assertEqual(question,args['question']);self.assertEqual(question,args['evidence'])
                self.assertEqual('all',args['sourceScope']);host.context['library']['authorizationQuote']=question
                return {'ok':True,'data':{}}
            if tool=='library.query':
                items=[] if args.get('parentId') else [{'id':'exam-2024','kind':'document','name':'2024자료','parentId':'archive-folder','path':'홈화면 > 과목폴더 > 기출폴더 > 2024자료'}]
                return {'ok':True,'data':{'revision':'r1','items':items,'total':len(items),'hasMore':False}}
            if tool=='library.open':
                self.assertEqual(question,quote)
                return {'ok':True,'data':{'path':'홈화면 > 과목폴더 > 기출폴더 > 2024자료','status':'opened'}}
            return host(tool,args,quote)
        model=Model(first,second,opened)
        answer,effects=run({'question':question,'recentConversation':[]},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(['library.open'],[e['tool'] for e in effects]);self.assertIn('2024자료',answer)
        self.assertEqual(1,sum(tool=='internal.libraryIntent' for tool,_,_ in calls))
        self.assertEqual(3,len(model.calls));self.assertEqual(['library.query','library.query','internal.libraryIntent','library.open'],[tool for tool,_,_ in calls if tool!='context.get'])

    def test_recorded_final_clarification_is_shown_instead_of_an_intent_change_error(self):
        question='프입 24기출좀 열어줘';host=self.host()
        first=tools(action('library.query',{'query':'24기출','parentId':'course-folder'}));first['libraryIntent']=intent(question,scope='current')
        second=tools(action('library.query',{'query':'기출','parentId':'course-folder'}));second['libraryIntent']=intent(question,scope='current')
        clarify=final('후보가 여러 개예요. 어느 자료를 열까요?');clarify['libraryIntent']=intent(question,scope='current',decision='clarify');clarify['libraryIntent']['operations']=[]
        calls=[]
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.query':return {'ok':True,'data':{'revision':'r1','items':[],'total':0,'hasMore':False}}
            return host(tool,args,quote)
        answer,effects=run({'question':question,'recentConversation':[]},Model(first,second,clarify),SYSTEM,MAX_OUTPUT,local)
        self.assertEqual('후보가 여러 개예요. 어느 자료를 열까요?',answer);self.assertEqual([],effects)
        self.assertNotIn('의도가 바뀌어',answer);self.assertNotIn('library.open',calls)

    def test_later_question_does_not_reset_a_completed_create_grant(self):
        question='기출모음 폴더 만들고 자료를 정리해줘';host=self.host();calls=[]
        created=tools(action('library.createFolder',{'parentId':'','name':'기출모음','expectedRevision':'r1'}));created['libraryIntent']=intent(question,['create','move'])
        clarify=final('어느 자료를 넣을까요?');clarify['libraryIntent']=intent(question,decision='clarify');clarify['libraryIntent']['operations']=[]
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='internal.libraryIntent':
                host.context['library']['authorizationQuote']=question
                return {'ok':True,'data':{}}
            if tool=='library.createFolder':return {'ok':True,'data':{'createdFolders':[{'id':'new','name':'기출모음','path':'홈화면 > 기출모음'}]}}
            return host(tool,args,quote)
        answer,effects=run({'question':question},Model(created,clarify),SYSTEM,MAX_OUTPUT,local)
        self.assertIn('어느 자료',answer);self.assertEqual(['library.createFolder'],[e['tool'] for e in effects])
        self.assertEqual(1,calls.count('internal.libraryIntent'))

    def test_quoted_confirmation_is_not_promoted_to_current_user_approval(self):
        question='“엉 맞어”라는 표현을 설명해줘';host=self.host();calls=[]
        host.context['library']['pendingMove']={'proposalId':'pending','approved':False}
        response=tools(action('library.confirmMove',{'proposalId':'pending'}))
        response['libraryIntent']=intent('엉 맞어',['move'],decision='approve');response['libraryIntent']['proposalId']='pending'
        def local(tool,args,quote):
            calls.append(tool)
            if tool in ('internal.libraryIntent','library.confirmMove'):raise AssertionError('quoted consent must not become host approval')
            return host(tool,args,quote)
        answer,effects=run({'question':question},Model(response),SYSTEM,MAX_OUTPUT,local)
        self.assertEqual([],effects);self.assertNotIn('library.confirmMove',calls)

    def test_readonly_open_plan_cannot_expand_to_move_after_search_results(self):
        question='2024 자료 열어줘';host=self.host();calls=[]
        first=tools(action('library.query',{'query':'2024'}));first['libraryIntent']=intent(question)
        second=tools(action('library.proposeMove',{'ids':[{'kind':'document','id':'exam'}],'destinationId':'elsewhere','expectedRevision':'r1'}));second['libraryIntent']=intent(question,['move'])
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='library.query':return {'ok':True,'data':{'revision':'r1','items':[],'total':0,'hasMore':False}}
            if tool in ('internal.libraryIntent','library.proposeMove'):raise AssertionError('query results cannot expand open into move')
            return host(tool,args,quote)
        answer,effects=run({'question':question},Model(first,second),SYSTEM,MAX_OUTPUT,local)
        self.assertEqual([],effects);self.assertNotIn('library.proposeMove',calls)

    def test_destination_confirmation_repairs_metadata_without_widening_or_moving_excluded_files(self):
        # Recorded failure shape: a named source folder is not the current home;
        # after a destination confirmation the model flips false -> true and all -> current.
        question='엉 맞아';host=self.host();calls=[]
        rows=[{'kind':'document','id':'society','name':'사회 자료','parentId':'named-source'},
              {'kind':'document','id':'anatomy','name':'해부학','parentId':'named-source'}]
        first=tools(action('library.query',{'parentId':'named-source'}));first['libraryIntent']=intent(question,['move'])
        args={'ids':[{'kind':'document','id':'society'}],'destinationId':'society-folder','expectedRevision':'r1'}
        wrong=tools(action('library.proposeMove',args));wrong['libraryIntent']={**intent(question,['move'],scope='current'),'selectionAll':True}
        fixed=tools(action('library.proposeMove',args));fixed.update(libraryIntent=intent(question,['move']),completeAfterLocal=True)
        def local(tool,args,quote):
            calls.append((tool,copy.deepcopy(args)))
            if tool=='library.query':return {'ok':True,'data':{'revision':'r1','items':rows,'hasMore':False}}
            if tool=='internal.libraryIntent':
                self.assertFalse(args['selectionAll']);self.assertEqual('all',args['sourceScope'])
                host.context['library']['authorizationQuote']=question
                return {'ok':True,'data':{}}
            if tool=='library.proposeMove':
                self.assertEqual(['society'],[r['id'] for r in args['ids']]);self.assertEqual('society-folder',args['destinationId'])
                return {'ok':True,'data':{'applied':True,'movedCount':1,'destinationPath':'홈화면 > 사회'}}
            return host(tool,args,quote)
        model=Model(first,wrong,fixed)
        answer,effects=run({'question':question,'recentConversation':[{'question':'보건 관련 자료를 제외하고 사회 폴더로 모두 옮겨줘','answer':'이 목적지가 맞나요?'}]},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(1,len(effects));self.assertIn('사회',answer)
        self.assertEqual(1,sum(t=='internal.libraryIntent' for t,_ in calls))
        self.assertEqual(1,sum(t=='library.proposeMove' for t,_ in calls))
        correction=model.calls[2][0]['libraryPlanCorrection']
        self.assertFalse(correction['executed']);self.assertFalse(correction['ceiling']['selectionAll'])
        self.assertEqual(2,len(correction['issues']));self.assertEqual(3,len(model.calls))

    def test_scope_only_metadata_correction_keeps_the_first_task_ceiling(self):
        question='지정한 폴더의 자료를 보관함으로 옮겨줘';host=self.host();calls=[]
        first=tools(action('library.query',{'parentId':'named-source'}));first['libraryIntent']=intent(question,['move'])
        args={'ids':[{'kind':'document','id':'doc'}],'destinationId':'target','expectedRevision':'r1'}
        wrong=tools(action('library.proposeMove',args));wrong['libraryIntent']=intent(question,['move'],scope='root')
        fixed=copy.deepcopy(wrong);fixed['libraryIntent']['sourceScope']='all';fixed['completeAfterLocal']=True
        def local(tool,args,quote):
            calls.append(tool)
            if tool=='library.query':return {'ok':True,'data':{'revision':'r1','items':[{'kind':'document','id':'doc','parentId':'named-source'}],'hasMore':False}}
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.proposeMove':return {'ok':True,'data':{'applied':True,'movedCount':1}}
            return host(tool,args,quote)
        _,effects=run({'question':question},Model(first,wrong,fixed),SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(1,len(effects));self.assertEqual(1,calls.count('library.proposeMove'))

    def test_metadata_repair_does_not_allow_new_operations_or_repeated_expansion(self):
        for repair in ('repeat','new_operation','new_token'):
            with self.subTest(repair=repair):
                host=self.host();calls=[];question='엉 맞아'
                first=tools(action('library.query',{}));first['libraryIntent']=intent(question,['move'])
                wrong=tools(action('library.proposeMove',{'ids':[],'destinationId':'target','expectedRevision':'r1'}));wrong['libraryIntent']={**intent(question,['move']),'selectionAll':True}
                last=copy.deepcopy(wrong)
                if repair=='new_operation':last['libraryIntent'].update(operations=['trash'],selectionAll=False)
                if repair=='new_token':
                    first['libraryIntent']['clarificationId']='original'
                    wrong['libraryIntent']['clarificationId']='original'
                    last['libraryIntent'].update(clarificationId='changed',selectionAll=False)
                def local(tool,args,quote):
                    calls.append(tool)
                    if tool=='library.query':return {'ok':True,'data':{'revision':'r1','items':[],'hasMore':False}}
                    if tool in ('internal.libraryIntent','library.proposeMove'):raise AssertionError('invalid repair must not execute')
                    return host(tool,args,quote)
                answer,effects=run({'question':question},Model(first,wrong,last),SYSTEM,MAX_OUTPUT,local)
                self.assertEqual([],effects);self.assertIn('처음 요청한 파일 작업',answer)
                self.assertNotIn('internal.libraryIntent',calls)


if __name__=='__main__':unittest.main()
