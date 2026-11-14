"""Malformed revision recovery must never absorb an actual catalog conflict."""
import copy
import unittest
from assistant_protocol import library_revision_correction, run,can_finish_locally
from test_assistant_protocol import Host, Model, action, tools, final
from test_assistant_source_folder import intent


class RevisionTests(unittest.TestCase):
    def test_one_partition_cannot_finish_while_another_created_destination_is_unused(self):
        payload={'localContext':{},'acceptedLibraryIntent':{'decision':'request','operations':['create','move']}}
        effects=[{'tool':'library.createFolder','data':{'createdFolders':[{'id':'mid'},{'id':'final'}]}},
                 {'tool':'library.proposeMove','data':{'moved':[{'id':'week2','parentId':'mid'}]}}]
        request={'tool':'library.proposeMove'};result={'tool':'library.proposeMove','result':{'ok':True,'data':{'movedCount':11}}}
        self.assertFalse(can_finish_locally([request],[result],effects,payload))
        effects.append({'tool':'library.proposeMove','data':{'moved':[{'id':'week9','parentId':'final'}]}})
        self.assertTrue(can_finish_locally([request],[result],effects,payload))

    def test_recovery_checks_a_partition_not_yet_emitted_as_a_tool_request(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        original=host.__call__;calls=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool in ('library.createFolder','library.proposeMove'):
                calls.append((tool,copy.deepcopy(args)))
                if args['expectedRevision']=='typo':return {'ok':False,'code':'library_stale','error':'복사 오류'}
                revision='r'+str(len(calls));host.context['library']['revision']=revision
                data={'applied':True,'revision':revision}
                if tool=='library.createFolder':data['createdFolders']=[{'id':args['name'],'name':args['name'],'parentId':''}]
                else:data.update(movedCount=1,moved=[{'id':args['ids'][0]['id'],'parentId':args['destinationId']}])
                return {'ok':True,'data':data}
            return original(tool,args,quote)
        first=tools(action('library.createFolder',{'name':'mid','parentId':'','expectedRevision':'r0'}));first['libraryIntent']={**intent(),'operations':['create','move']}
        second=tools(action('library.createFolder',{'name':'final','parentId':'','expectedRevision':'r1'}))
        ids=[{'kind':'document','id':'week2'}]
        bad=tools(action('library.proposeMove',{'ids':ids,'destinationId':'mid','expectedRevision':'typo'}))
        repaired=tools(action('library.proposeMove',{'ids':ids,'destinationId':'mid','expectedRevision':'r2'}));repaired['completeAfterLocal']=True
        last=tools(action('library.proposeMove',{'ids':[{'kind':'document','id':'week9'}],'destinationId':'final','expectedRevision':'r4'}));last['completeAfterLocal']=True
        model=Model(first,second,bad,repaired,last)
        _,effects=run({'question':'자료를 mid와 final 폴더로 나눠줘'},model,'system',200,local)
        self.assertEqual(5,len(model.calls));self.assertEqual(4,len(effects))
        self.assertEqual('final',model.calls[4][0]['libraryCompletionReview']['unusedFolders'][0]['id'])

    def test_corrected_item_order_does_not_leave_a_phantom_pending_request(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        original=host.__call__;attempts=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.trash':
                attempts.append(args)
                if args['expectedRevision']=='typo':return {'ok':False,'code':'library_stale','error':'복사 오류'}
                return {'ok':True,'data':{'trashedCount':2,'applied':True,'revision':'r1'}}
            return original(tool,args,quote)
        ids=[{'kind':'document','id':'a'},{'kind':'document','id':'b'}]
        bad=tools(action('library.trash',{'ids':ids,'expectedRevision':'typo'}));bad['libraryIntent']=intent()
        fixed=tools(action('library.trash',{'ids':list(reversed(ids)),'expectedRevision':'r0'}));fixed['completeAfterLocal']=True
        model=Model(bad,fixed)
        _,effects=run({'question':'자료 둘 지워줘'},model,'system',200,local)
        self.assertEqual(2,len(model.calls));self.assertEqual(2,len(attempts));self.assertEqual(1,len(effects))

    def test_unknown_revision_only_when_native_catalog_is_unchanged(self):
        request={'tool':'library.rename','arguments':{'expectedRevision':'typo'}}
        result={'ok':False,'code':'library_stale'}
        payload={'localContext':{'library':{'revision':'r0'}},'localResults':[
            {'request':{'tool':'library.createFolder'},'result':{'ok':True,'data':{'revision':'r1'}}}]}
        fresh={'ok':True,'data':{'library':{'revision':'r1'}}}
        self.assertEqual('r1',library_revision_correction(request,result,payload,fresh)['revision'])
        self.assertNotIn('expectedRevision',library_revision_correction(request,result,payload,fresh)['failedRequest']['arguments'])
        self.assertEqual('typo',request['arguments']['expectedRevision'])
        for revision in ('r0','r1'):
            request['arguments']['expectedRevision']=revision
            self.assertIsNone(library_revision_correction(request,result,payload,fresh))
        request['arguments']['expectedRevision']='typo'
        fresh['data']['library']['revision']='external'
        self.assertIsNone(library_revision_correction(request,result,payload,fresh))
        fresh['ok']=False
        self.assertIsNone(library_revision_correction(request,result,payload,fresh))

    def test_correction_discards_remaining_batch_and_never_repeats_success(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        original=host.__call__;calls=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.createFolder':
                calls.append(copy.deepcopy(args))
                if args['expectedRevision']=='typo':return {'ok':False,'code':'library_stale','error':'버전 오류'}
                host.context['library']['revision']='r'+str(len(calls))
                return {'ok':True,'data':{'applied':True,'revision':host.context['library']['revision'],'createdFolders':[]}}
            return original(tool,args,quote)
        plan={**intent(),'operations':['create']}
        first=tools(action('library.createFolder',{'name':'one','parentId':'','expectedRevision':'r0'}));first['libraryIntent']=plan
        bad=tools(action('library.createFolder',{'name':'two','parentId':'','expectedRevision':'typo'}),action('library.createFolder',{'name':'three','parentId':'','expectedRevision':'r1'},identifier='r2'))
        corrected=tools(action('library.createFolder',{'name':'two','parentId':'','expectedRevision':'r1'}));corrected['completeAfterLocal']=True
        remaining=tools(action('library.createFolder',{'name':'three','parentId':'','expectedRevision':'r3'}))
        model=Model(first,bad,corrected,final('완료했어요.'),remaining,final('이제 모두 완료했어요.'))
        _,effects=run({'question':'폴더 둘 만들어줘'},model,'system',200,local)
        self.assertEqual(['one','two','two','three'],[c['name'] for c in calls])
        self.assertEqual(3,len(effects))
        self.assertEqual('r1',model.calls[2][0]['libraryRevisionCorrection']['revision'])
        self.assertEqual('three',model.calls[3][0]['libraryPendingRequests'][0]['arguments']['name'])
        self.assertIn('libraryIncompleteTask',model.calls[4][0])
        self.assertNotIn('libraryIncompleteTask',model.calls[5][0])

    def test_repeated_bad_tokens_are_bounded(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r'}
        original=host.__call__;attempts=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.createFolder':
                attempts.append(args);return {'ok':False,'code':'library_stale','error':'버전 오류'}
            return original(tool,args,quote)
        bad=tools(action('library.createFolder',{'name':'one','parentId':'','expectedRevision':'typo'}));bad['libraryIntent']={**intent(),'operations':['create']}
        model=Model(copy.deepcopy(bad),copy.deepcopy(bad),copy.deepcopy(bad))
        answer,effects=run({'question':'폴더 만들어줘'},model,'system',200,local)
        self.assertEqual(3,len(attempts));self.assertEqual([],effects);self.assertIn('버전 오류',answer)

    def test_external_edit_after_partial_success_stops_without_retry(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        original=host.__call__;writes=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.createFolder':
                writes.append(copy.deepcopy(args))
                if len(writes)==1:
                    host.context['library']['revision']='r1'
                    return {'ok':True,'data':{'applied':True,'revision':'r1','createdFolders':[]}}
                host.context['library']['revision']='external-edit'
                return {'ok':False,'code':'library_stale','error':'실제 외부 변경'}
            return original(tool,args,quote)
        first=tools(action('library.createFolder',{'name':'one','parentId':'','expectedRevision':'r0'}));first['libraryIntent']={**intent(),'operations':['create']}
        bad=tools(action('library.createFolder',{'name':'two','parentId':'','expectedRevision':'typo'}),action('library.createFolder',{'name':'must-not-run','parentId':'','expectedRevision':'r1'},identifier='r2'))
        model=Model(first,bad)
        answer,effects=run({'question':'폴더 둘 만들어줘'},model,'system',200,local)
        self.assertEqual(2,len(model.calls));self.assertEqual(2,len(writes));self.assertEqual(1,len(effects))
        self.assertIn('실제 외부 변경',answer)

    def test_revision_repair_does_not_allow_new_operation(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'revision':'r0'}
        original=host.__call__;writes=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':return {'ok':True,'data':{}}
            if tool=='library.createFolder':return {'ok':False,'code':'library_stale','error':'잘못 복사한 버전'}
            if tool=='library.trash':writes.append(args);raise AssertionError('scope widened on repair')
            return original(tool,args,quote)
        bad=tools(action('library.createFolder',{'name':'one','parentId':'','expectedRevision':'typo'}));bad['libraryIntent']={**intent(),'operations':['create']}
        widened=tools(action('library.trash',{'ids':[],'expectedRevision':'r0'}));widened['libraryIntent']=intent()
        answer,effects=run({'question':'폴더 만들어줘'},Model(bad,widened),'system',200,local)
        self.assertEqual([],writes);self.assertEqual([],effects);self.assertIn('의도가 바뀌어',answer)


if __name__=='__main__':unittest.main()
