"""Smaller chat inputs must not remove capabilities or lose pending authority."""
import copy,unittest
import assistant_protocol as protocol
from assistant_context_policy import active_domains,instructions,CORE,cache_blocks
from home_assistant import SYSTEM,MAX_OUTPUT,chat
from test_assistant_protocol import Host,Model,final,tools,action
from test_assistant_source_folder import intent

class ContextPolicyTests(unittest.TestCase):
    def test_already_at_destination_is_complete_without_repeating_move(self):
        host=self.host();host.context['mutationScope']='libraryWrite';native=host.__call__;moves=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.proposeMove':
                moves.append(args);return {'ok':True,'data':{'alreadyThere':True,'destinationPath':'홈화면 > 공부'}}
            return native(tool,args,quote)
        move=tools(action('library.proposeMove',{'ids':[{'kind':'document','id':'doc'}],'destinationId':'folder','expectedRevision':'r0'}))
        move['libraryIntent']={**intent(),'operations':['move']}
        model=Model(move,final('이미 공부 폴더에 있어요.'))
        answer,effects=protocol.run({'question':'자료를 공부 폴더로 옮겨줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(1,len(moves));self.assertEqual(2,len(model.calls));self.assertEqual([],effects)
        self.assertIn('이미',answer)
    def test_approved_task_cannot_end_with_a_promise_without_native_execution(self):
        for corrected_to_explanation in (False,True):
            host=self.host();native=host.__call__;writes=[]
            def local(tool,args,quote):
                if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
                if tool=='library.createFolder':writes.append(args);return {'ok':True,'data':{'applied':True,'createdFolders':[{'id':'new','name':'공부','path':'홈화면 > 공부'}]}}
                return native(tool,args,quote)
            promised=final('공부 폴더를 만들게요.');promised['libraryIntent']={**intent(),'operations':['create'],'selectionAll':False}
            last=final('실행 요청이 아니라 설명만 했어요.') if corrected_to_explanation else tools(action('library.createFolder',{'name':'공부','parentId':'','expectedRevision':'r0'}))
            if corrected_to_explanation:last['libraryIntent']={**intent(),'decision':'none','operations':[]}
            else:last['completeAfterLocal']=True
            # The full domain is already active, as on a stored approval turn.
            host.context['mutationScope']='libraryWrite'
            model=Model(promised,last)
            answer,effects=protocol.run({'question':'공부 폴더 만들어줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
            self.assertEqual(2,len(model.calls));self.assertIn('libraryExecutionRequired',model.calls[1][0])
            self.assertEqual(0 if corrected_to_explanation else 1,len(writes))
            self.assertNotEqual('공부 폴더를 만들게요.',answer)
    def test_light_read_metadata_does_not_pin_an_incomplete_authority_ceiling(self):
        host=self.host();native=host.__call__;bound=[]
        def local(tool,args,quote):
            if tool=='library.query':return {'ok':True,'data':{'revision':'r0','items':[]}}
            if tool=='internal.libraryIntent':bound.append(args);return {'ok':True,'data':{}}
            return native(tool,args,quote)
        light=tools(action('library.query',{'parentId':'course'}));light['libraryIntent']={**intent(),'decision':'clarify','operations':['create','move'],'sourceScope':'current','selectionAll':False}
        full=final('이 폴더 전체를 두 묶음으로 정리할까요?');full['libraryIntent']={**intent('course'),'decision':'clarify','operations':['create','move'],'selectionAll':True}
        model=Model(light,full)
        protocol.run({'question':'이 폴더 전체를 나눠 정리해줘. 먼저 물어봐'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(1,len(bound));self.assertTrue(bound[0]['selectionAll']);self.assertEqual('course',bound[0]['sourceFolderId'])
        self.assertNotIn('libraryTaskPlan',model.calls[1][0]);self.assertNotIn('libraryPlanCorrection',model.calls[1][0])
    def test_completed_activity_changes_available_tools_without_breaking_fixed_cache_prefix(self):
        first=self.host();second=self.host()
        second.context.update(recoveryInterpretationEligible=True,undo={'id':'undo','domain':'library','available':True})
        models=[]
        for host in (first,second):
            model=Model(final('고마워요.'));protocol.run({'question':'고마워'},model,SYSTEM,MAX_OUTPUT,host,contextual=True);models.append(model)
        self.assertEqual(models[0].assistant_cache_prefix,models[1].assistant_cache_prefix)
        self.assertNotIn('actions.undo',models[0].calls[0][0]['toolCatalog'])
        self.assertIn('actions.undo',models[1].calls[0][0]['toolCatalog'])
        self.assertTrue(all(m.calls[0][1]['cache_stable_prefix'] for m in models))
    def test_arbitrary_open_can_recover_but_named_ambiguity_stays_a_human_choice(self):
        for free_choice in (True,False):
            host=self.host();native=host.__call__;opened=[]
            def local(tool,args,quote):
                if tool=='library.query':return {'ok':True,'data':{'revision':'r0','items':[
                    {'id':'a','kind':'document','name':'같은이름.pdf'}, {'id':'b','kind':'document','name':'같은이름.pdf'}, {'id':'c','kind':'document','name':'다른파일.pdf'}]}}
                if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
                if tool=='library.open':
                    if args['id']!='c':return {'ok':False,'code':'library_ambiguous','error':'같은 이름 두 개 중 어느 파일인가요?'}
                    opened.append(args['id']);return {'ok':True,'data':{'path':'홈화면 > 다른파일.pdf'}}
                return native(tool,args,quote)
            queried=tools(action('library.query',{}))
            bad=tools(action('library.open',{'kind':'document','id':'a','expectedRevision':'r0'}));bad['libraryIntent']={**intent(),'operations':['open']}
            last=tools(action('library.open',{'kind':'document','id':'c','expectedRevision':'r0'})) if free_choice else final('같은 이름 두 개 중 어느 파일인가요?')
            last['completeAfterLocal']=free_choice
            model=Model(queried,bad,last)
            protocol.run({'question':'아무 파일 열어줘' if free_choice else '같은이름.pdf 열어줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
            self.assertEqual(['c'] if free_choice else [],opened)
            self.assertEqual(['c'],[r['id'] for r in model.calls[2][0]['libraryAmbiguityReview']['observedUniqueFiles']])
    def test_multi_write_completion_requires_every_native_success_and_both_partitions(self):
        payload={'localContext':{},'acceptedLibraryIntent':{'decision':'request','operations':['create','move']}}
        requests=[{'tool':'library.proposeMove'},{'tool':'library.proposeMove'}]
        completed=[{'tool':'library.proposeMove','result':{'ok':True,'data':{'applied':True,'movedCount':1}}} for _ in requests]
        effects=[{'tool':'library.createFolder','data':{'createdFolders':[{'id':'mid'},{'id':'final'}]}},
                 {'tool':'library.proposeMove','data':{'moved':[{'parentId':'mid'}]}}]
        self.assertFalse(protocol.can_finish_locally(requests,completed,effects,payload))
        effects.append({'tool':'library.proposeMove','data':{'moved':[{'parentId':'final'}]}})
        self.assertTrue(protocol.can_finish_locally(requests,completed,effects,payload))
        failed=copy.deepcopy(completed);failed[1]['result']['ok']=False
        self.assertFalse(protocol.can_finish_locally(requests,failed,effects,payload))
        mixed=copy.deepcopy(requests);mixed[1]['tool']='planner.apply'
        self.assertFalse(protocol.can_finish_locally(mixed,completed,effects,payload))
    def test_cache_boundaries_preserve_exact_instructions_and_stable_prefix(self):
        first=cache_blocks('fixed rules\nlibrary details','fixed rules\n')
        second=cache_blocks('fixed rules\nplanner details','fixed rules\n')
        self.assertEqual('fixed rules\nlibrary details',''.join(p['text'] for p in first))
        self.assertEqual(first[0],second[0]);self.assertEqual(2,len(first))
        self.assertTrue(all(p['prompt_cache_breakpoint']=={'mode':'explicit'} for p in first))

    def test_root_creation_question_does_not_need_a_paid_contract_review(self):
        host=self.host();native=host.__call__;bound=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bound.append(args);return {'ok':True,'data':{}}
            return native(tool,args,quote)
        response=final('홈화면에 공부 폴더를 만들까요?');response['libraryIntent']={**intent(),'decision':'clarify','sourceScope':'root','selectionAll':False,'operations':['create']}
        model=Model(response)
        _,effects=protocol.run({'question':'홈화면 공부 폴더 만들기 전에 물어봐'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(1,len(model.calls));self.assertEqual([],effects);self.assertEqual('clarify',bound[0]['decision'])
    def host(self):
        host=Host();host.context.update(semanticMutationAuthorization=True,mutationReferences=[])
        host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        return host

    def test_chat_is_one_main_call_with_all_capabilities_and_original_quality_rules(self):
        host=self.host();before=copy.deepcopy(host.context);model=Model(final('고마워요.'))
        result=chat({'question':'너 상당히 고능하구나'},model,local=host)
        payload,options=model.calls[0]
        self.assertEqual(1,len(model.calls));self.assertEqual(0,model.planning);self.assertEqual([],result['effects'])
        self.assertEqual(set(protocol.allowed_tools(before)),set(payload['toolCatalog']))
        self.assertIn(SYSTEM,options['system_prompt']);self.assertIn(CORE,options['system_prompt'])
        self.assertNotIn('<플래너·개인화 실행 의도>',options['system_prompt'])
        self.assertLess(len(options['system_prompt']),len(SYSTEM+protocol.INSTRUCTIONS))
        self.assertEqual(MAX_OUTPUT,options['max_output']);self.assertEqual(before,host.context)

    def test_real_query_runs_without_permission_or_contract_fetch_call(self):
        host=self.host();native=host.__call__;writes=[]
        def local(tool,args,quote):
            if tool=='library.query':return {'ok':True,'data':{'revision':'r0','items':[{'id':'doc','kind':'document','parentId':'','name':'자료.pdf'}]}}
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.open':writes.append(args);return {'ok':True,'data':{'path':'홈화면 > 자료.pdf'}}
            return native(tool,args,quote)
        queried=tools(action('library.query',{}))
        opened=tools(action('library.open',{'kind':'document','id':'doc','expectedRevision':'r0'}));opened['libraryIntent']={**intent(),'operations':['open']};opened['completeAfterLocal']=True
        model=Model(queried,opened)
        protocol.run({'question':'자료 하나 열어줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(2,len(model.calls));self.assertEqual(1,len(writes));self.assertEqual(0,model.planning)
        self.assertIn('<파일·폴더>',model.calls[1][1]['system_prompt']);self.assertNotIn('<플래너>',model.calls[1][1]['system_prompt'])

    def test_first_write_is_not_executed_until_full_original_contract_is_seen(self):
        host=self.host();native=host.__call__;writes=[];bound=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bound.append(args);return {'ok':True,'data':{}}
            if tool=='library.createFolder':writes.append(args);return {'ok':True,'data':{'applied':True,'createdFolders':[{'id':'new','name':'공부','path':'홈화면 > 공부'}]}}
            return native(tool,args,quote)
        response=tools(action('library.createFolder',{'parentId':'','name':'공부','expectedRevision':'r0'}));response['libraryIntent']={**intent(),'operations':['create']};response['completeAfterLocal']=True
        model=Model(copy.deepcopy(response),copy.deepcopy(response))
        protocol.run({'question':'폴더 만들어줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(2,len(model.calls));self.assertEqual(1,len(writes));self.assertEqual(1,len(bound))
        self.assertEqual([],model.calls[1][0]['localResults']);self.assertIn('<파일·폴더>',model.calls[1][1]['system_prompt'])

    def test_explicit_root_creation_uses_existing_native_checks_without_a_review_call(self):
        host=self.host();native=host.__call__;writes=[];bindings=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bindings.append(args);return {'ok':True,'data':{}}
            if tool=='library.createFolder':writes.append(args);return {'ok':True,'data':{'applied':True,'createdFolders':[{'id':'new','name':'공부','path':'홈화면 > 공부'}]}}
            return native(tool,args,quote)
        response=tools(action('library.createFolder',{'parentId':'','name':'공부','expectedRevision':'r0'}));response['libraryIntent']={**intent(),'selectionAll':False,'operations':['create']};response['completeAfterLocal']=True
        model=Model(response)
        protocol.run({'question':'홈화면에 공부 폴더 만들어줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(1,len(model.calls));self.assertEqual(1,len(writes));self.assertEqual(1,len(bindings))

    def test_invalid_light_scope_is_replanned_with_full_contract_before_native_calls(self):
        host=self.host();native=host.__call__;queries=[]
        def local(tool,args,quote):
            if tool=='library.query':queries.append(args);return {'ok':True,'data':{'revision':'r0','items':[]}}
            return native(tool,args,quote)
        bad=tools(action('library.query',{'parentId':'folder'}));bad['libraryIntent']={**intent('folder'),'sourceScope':'current','operations':['open']}
        fixed=tools(action('library.query',{'parentId':'folder'}));fixed['libraryIntent']={**intent('folder'),'operations':['open']}
        model=Model(bad,fixed,final('자료를 조회했어요.'))
        protocol.run({'question':'그 폴더 확인해줘'},model,SYSTEM,MAX_OUTPUT,local,contextual=True)
        self.assertEqual(1,len(queries));self.assertEqual([],model.calls[1][0]['localResults'])
        self.assertIn('validationError',model.calls[1][0]['taskProtocolExpansion'])
        self.assertNotIn('taskProtocolExpansion',model.calls[2][0])

    def test_invalid_scope_is_not_silently_rewritten_or_retried_forever(self):
        host=self.host();bad=tools(action('library.query',{}));bad['libraryIntent']={**intent('folder'),'sourceScope':'current'}
        model=Model(copy.deepcopy(bad),copy.deepcopy(bad))
        from pdf_ai import AiResponseError
        with self.assertRaises(AiResponseError):protocol.run({'question':'폴더 확인'},model,SYSTEM,MAX_OUTPUT,host,contextual=True)
        self.assertEqual(2,len(model.calls));self.assertFalse(any(c[0]=='library.query' for c in host.calls))

    def test_nested_discussion_preserves_complete_original_task_without_extra_call(self):
        host=self.host();pending={'clarificationId':'pending','request':'원본 폴더의 9주차는 기말고사, 나머지는 중간고사',
            'operations':['create','move'],'sourceScope':'current','sourceFolderId':None,'selectionAll':False,
            'requestView':{'currentFolderId':'original','currentPath':'홈화면 > 원본'},
            'confirmationQuestion':'이 분류로 진행할까요?','discussion':[{'question':'무슨 뜻이야?','answer':'9주차를 따로 모아요.'}],
            'targets':[{'kind':'document','id':'nine','name':'9주차.pdf','parentId':'original'}]}
        host.context['library'].update(pendingRequest=pending,currentFolderId='elsewhere')
        for question in ('그럼 왜 9주차를 따로 둬?','그렇다면 참고자료는?','잠깐 삼각형 각의 합은?'):
            model=Model(final('설명만 했어요.'));protocol.run({'question':question},model,SYSTEM,MAX_OUTPUT,host,contextual=True)
            self.assertEqual(1,len(model.calls));self.assertIn('<파일·폴더>',model.calls[0][1]['system_prompt'])
            self.assertEqual(pending,model.calls[0][0]['localContext']['library']['pendingRequest'])
            self.assertFalse(any(c[0] in ('library.createFolder','library.proposeMove') for c in host.calls))

    def test_contracts_keep_every_original_domain_rule_and_do_not_cross_load(self):
        library=instructions(protocol.INSTRUCTIONS,{'library'})
        original=protocol.INSTRUCTIONS.split('<파일·폴더>',1)[1].split('</파일·폴더>',1)[0]
        self.assertIn(original,library);self.assertNotIn('<플래너>',library)
        for domain,tag in [('planner','플래너'),('memory','개인화'),('recovery','직전 작업 복원')]:
            self.assertIn('<'+tag+'>',instructions(protocol.INSTRUCTIONS,{domain}))
        self.assertEqual(set(),active_domains({'library':{'cancelledRequest':{'request':'취소된 작업'}}}))
        self.assertEqual({'planner'},active_domains({'mutationReferences':[{'pending':True,'scopes':['planner']}]}))

if __name__=='__main__':unittest.main()
