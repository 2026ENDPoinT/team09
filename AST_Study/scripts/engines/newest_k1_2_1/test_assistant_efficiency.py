"""Offline regressions for cost cuts without weakening execution provenance."""
import copy
import json
import unittest
from assistant_efficiency import model_payload, model_context
from assistant_protocol import run, can_finish_locally, local_completion_answer
from test_assistant_protocol import Host, Model, final, tools, action
from home_assistant import SYSTEM, MAX_OUTPUT, research_context


class EfficiencyTests(unittest.TestCase):
    def test_pending_request_preserves_original_scope_and_every_target_across_screens(self):
        rows=[{'id':str(n),'kind':'document','name':f'{n}주차_원래 제목.pdf',
               'path':f'홈화면 > 수업 > {n}주차_원래 제목.pdf','parentId':'course',
               'parentPath':'홈화면 > 수업','ancestorIds':['','course']} for n in range(20)]
        context={'library':{'screen':'study','currentFolderId':'elsewhere',
            'pendingRequest':{'clarificationId':'continue-exact','request':'이 폴더 이름을 주차만 남겨 바꿔줘',
                'operations':['rename'],'sourceScope':'current',
                'requestView':{'currentFolderId':'course','currentPath':'홈화면 > 수업','screen':'library',
                               'section':'documents','search':'','libraryVisible':True,'viewRevision':'native-only'},
                'targets':rows}}}
        before=copy.deepcopy(context);pending=model_context(context)['library']['pendingRequest']
        self.assertEqual(context,before);self.assertEqual('continue-exact',pending['clarificationId'])
        self.assertEqual(['rename'],pending['operations']);self.assertEqual('current',pending['sourceScope'])
        self.assertEqual('course',pending['requestView']['currentFolderId'])
        self.assertEqual('documents',pending['requestView']['section']);self.assertNotIn('viewRevision',pending['requestView'])
        self.assertEqual(20,len(pending['targets']));self.assertEqual([str(n) for n in range(20)],[row['id'] for row in pending['targets']])
        self.assertTrue(all(row['parentId']=='course' and row['path'] for row in pending['targets']))
        self.assertNotIn('ancestorIds',str(pending));self.assertNotIn('parentPath',str(pending))

    def test_preview_is_bounded_and_native_scope_and_personalization_are_untouched(self):
        rows=[{'id':str(n),'kind':'document','name':f'자료{n}','path':f'홈화면 > 자료{n}',
               'parentId':'','parentPath':'홈화면','ancestorIds':['','large-parent']} for n in range(100)]
        context={'personalization':{'values':{'tone':'casual','notes':['긴 선호를 그대로 유지'] }},
                 'library':{'visibleItems':rows,'visibleTotal':100,'currentFolderId':'','screen':'library','search':'',
                            'revision':'r1','authorizationQuote':'사용자 직접 지시',
                            'requestView':{'currentFolderId':'','screen':'library','search':'','viewRevision':'native-only'}}}
        original=copy.deepcopy(context);projected=model_context(context)
        self.assertEqual(context,original);self.assertEqual(context['personalization'],projected['personalization'])
        library=projected['library'];self.assertEqual(12,len(library['visibleItems']));self.assertEqual(100,library['visibleTotal'])
        self.assertTrue(library['visibleItemsTruncated']);self.assertTrue(library['visibleItemsOmitted'])
        self.assertNotIn('requestView',library);self.assertNotIn('ancestorIds',str(library))
        self.assertEqual('사용자 직접 지시',library['authorizationQuote'])
        context['library']['currentFolderId']='after-own-navigation'
        self.assertEqual('',model_context(context)['library']['requestView']['currentFolderId'])

    def test_duplicate_query_payloads_are_deduplicated_but_changes_and_errors_survive(self):
        def row(revision='r1',ok=True):
            return {'request':{'id':'q','tool':'library.query','arguments':{'query':'기출'},'authorizationQuote':'do not repeat'},
                    'result':{'ok':ok,'data':{'revision':revision,'items':[{'id':'a','kind':'document','name':'기출','path':'홈화면 > 기출','parentId':'','ancestorIds':['']}],'hasMore':False}}}
        payload={'localContext':{},'localResults':[row(),row(),row('r2'),row('r2',False)],
                 'recentConversation':[{'question':'별명 뭐였지','answer':'맥락 보존'}]}
        before=copy.deepcopy(payload);projected=model_payload(payload)
        self.assertEqual(3,len(projected['localResults']));self.assertEqual(before,payload)
        self.assertNotIn('authorizationQuote',projected['localResults'][0]['request'])
        self.assertEqual(payload['recentConversation'],projected['recentConversation'])
        self.assertLess(len(json.dumps(projected)),len(json.dumps(payload)))

    def test_move_result_keeps_exact_successful_sources_for_later_actions(self):
        record={'request':{'id':'m','tool':'library.proposeMove','authorizationQuote':'native','arguments':{'ids':[{'kind':'document','id':'A'}],'destinationId':'X','expectedRevision':'old'}},
                'result':{'ok':True,'data':{'movedCount':1,'destinationPath':'홈화면 > X','moved':[{'id':'A','kind':'document','parentId':'X','sourceParentId':'old'}]}}}
        projected=model_payload({'localContext':{},'localResults':[record]})['localResults'][0]
        self.assertEqual('A',projected['request']['arguments']['ids'][0]['id'])
        self.assertEqual('X',projected['result']['data']['moved'][0]['parentId'])

    def test_empty_course_folder_result_is_not_reported_as_recursive_search(self):
        record={'request':{'tool':'library.query','arguments':{'parentId':'course','query':'2024'}},
                'result':{'ok':True,'data':{'revision':'r','total':0,'items':[],'hasMore':False}}}
        payload={'localContext':{},'localResults':[record]};before=copy.deepcopy(payload)
        data=model_payload(payload)['localResults'][0]['result']['data']
        self.assertTrue(data['directChildrenOnly']);self.assertIn('하위 폴더는 검색하지 않았어요',data['scopeNotice'])
        self.assertEqual(payload,before)

    def test_local_folder_search_never_needs_a_paid_web_planner(self):
        provider=Model();state={'turns':[],'webResearch':[{'question':'old public topic','answer':'old public result'}]}
        plan,decision,status,research=research_context('기출모음 폴더 검색해줘',state,{},provider,0)
        self.assertFalse(decision['allowed']);self.assertEqual('local_library',status)
        self.assertIsNone(research);self.assertEqual(0,provider.planning)

    def test_single_final_write_skips_paid_prose_call_and_keeps_saved_register(self):
        question='내일 시험 일정 추가해줘';host=Host(question)
        host.context['personalization']={'values':{'tone':'casual'}}
        response=tools(action('planner.apply',{'expectedRevision':4,'changes':[{'entity':'task','operation':'create','id':None,'fields':{'title':'시험 준비','date':'2026-10-26'}}]}))
        response['completeAfterLocal']=True;model=Model(response)
        answer,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(1,len(model.calls));self.assertEqual(1,len(effects));self.assertIn('처리했어.',answer);self.assertIn('시험 준비',answer)
        self.assertEqual(1,sum(tool=='planner.apply' for tool,_,_ in host.calls))

    def test_reads_and_unfinished_library_operations_cannot_finish_locally(self):
        request={'tool':'library.proposeMove'};already={'tool':'library.proposeMove','result':{'ok':True,'data':{'alreadyThere':True}}}
        payload={'localContext':{},'acceptedLibraryIntent':{'operations':['create','move'],'decision':'request'}}
        self.assertFalse(can_finish_locally([request],[already],[],payload))
        payload['acceptedLibraryIntent']['operations']=['move'];self.assertTrue(can_finish_locally([request],[already],[],payload))
        self.assertFalse(can_finish_locally([{'tool':'library.query'}],[{'result':{'ok':True}}],[],payload))
        success={'tool':'library.open','result':{'ok':True,'data':{'animationCompleted':False,'notice':'저장은 완료했지만 전환을 마치지 못했어요.'}}}
        self.assertFalse(can_finish_locally([{'tool':'library.open'}],[success],[],payload))

    def test_query_completion_flag_does_not_replace_a_requested_analysis(self):
        host=Host();query=tools(action('planner.query',{'from':'2026-10-25','to':'2026-10-26'}));query['completeAfterLocal']=True
        model=Model(query,final('조회한 시험 일정을 바탕으로 설명해요.'))
        answer,effects=run({'question':'시험 일정 설명해줘'},model,SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(2,len(model.calls));self.assertIn('설명해요',answer);self.assertEqual([],effects)

    def test_redo_must_continue_after_undo_even_if_model_requests_local_finish(self):
        completed=[{'tool':'actions.undo','result':{'ok':True,'data':{'domain':'planner'}}}]
        self.assertFalse(can_finish_locally([{'tool':'actions.undo'}],completed,[],{'localContext':{'recoveryDecision':'redo'}}))

    def test_mixed_planner_completion_cannot_hide_unfinished_library_or_prior_results(self):
        completed=[{'tool':'planner.apply','result':{'ok':True,'data':{'applied':True}}}]
        payload={'localContext':{},'acceptedLibraryIntent':{'operations':['open'],'decision':'request'}}
        self.assertFalse(can_finish_locally([{'tool':'planner.apply'}],completed,[],payload))
        effects=[{'tool':'library.createFolder','data':{'createdFolders':[{'name':'새모음','path':'홈화면 > 새모음'}]}}]
        already=[{'tool':'library.proposeMove','result':{'ok':True,'data':{'alreadyThere':True,'destinationPath':'보관함'}}}]
        answer=local_completion_answer(already,effects,{})
        self.assertIn('새모음',answer);self.assertIn('이미 있어요',answer)

    def test_memory_completion_uses_new_tone_and_other_languages_keep_model_prose(self):
        effects=[{'tool':'memory.update','data':{'values':{'tone':'casual'}}}]
        completed=[{'tool':'memory.update','result':{'ok':True,'data':effects[0]['data']}}]
        context={'personalization':{'values':{'tone':'polite'}}}
        self.assertIn('처리했어.',local_completion_answer(completed,effects,context))
        effects[0]['data']['values']['language']='en'
        self.assertFalse(can_finish_locally([{'tool':'memory.update'}],completed,effects,{'localContext':context}))

    def test_eligible_recovery_does_not_grant_writes_when_metadata_is_missing(self):
        host=Host();host.context.update(recoveryInterpretationEligible=True,undo={'id':'last','domain':'planner','context':{}})
        attempted=[]
        def local(tool,args,quote):
            if tool=='actions.undo':
                attempted.append(quote)
                return {'ok':False,'code':'authorization_required','error':'현재 직접 복원 요청이 없어 실행하지 않았어요.'}
            return host(tool,args,quote)
        model=Model(tools(action('actions.undo',{'id':'last'})))
        answer,effects=run({'question':'작업 내용이 궁금해요'},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual([''],attempted);self.assertEqual([],effects);self.assertIn('실행하지 않았어요',answer)

    def test_unclear_recovery_removes_writes_before_same_response_actions(self):
        host=Host();host.context.update(recoveryInterpretationEligible=True,undo={'id':'last','domain':'planner','context':{}})
        response=tools(action('actions.undo',{'id':'last'}));response['recoveryIntent']={'intent':'redo','clear':False,'evidence':'다시 해줘'}
        def local(tool,args,quote):
            if tool=='internal.recoveryIntent':
                host.context.update(recoveryInterpretationEligible=False,recoveryDecision='clarify',mutationScope='',authorizationQuote='')
                return {'ok':True,'data':{'intent':'clarify'}}
            return host(tool,args,quote)
        model=Model(response);answer,effects=run({'question':'다시 해줘'},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual([],effects);self.assertFalse(any(tool=='actions.undo' for tool,_,_ in host.calls))

    def test_recovery_none_preserves_current_direct_planner_request_without_extra_model(self):
        host=Host('새 일정 추가해줘');host.context.update(recoveryInterpretationEligible=True,undo={'id':'last','domain':'planner','context':{}})
        response=tools(action('planner.apply',{'expectedRevision':4,'changes':[{'entity':'task','operation':'create','fields':{'title':'새 일정'}}]}))
        response.update(completeAfterLocal=True,recoveryIntent={'intent':'none','clear':False,'evidence':''})
        def local(tool,args,quote):
            if tool=='internal.recoveryIntent':
                host.context.update(recoveryInterpretationEligible=False,recoveryDecision='none')
                return {'ok':True,'data':{'intent':'none'}}
            return host(tool,args,quote)
        model=Model(response);answer,effects=run({'question':'새 일정 추가해줘'},model,SYSTEM,MAX_OUTPUT,local)
        self.assertEqual(1,len(model.calls));self.assertEqual(['planner.apply'],[e['tool'] for e in effects])


if __name__=='__main__':unittest.main()
