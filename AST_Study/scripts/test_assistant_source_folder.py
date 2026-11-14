"""Scope stays attached to existing answer calls and cannot expand after binding."""
import copy
import unittest
from assistant_protocol import (validate_library_intent, library_intent_narrows,
    library_intent_within_ceiling, library_clarification_plan, library_plan_correction, FORMAT, run)
from assistant_efficiency import model_context
from test_assistant_protocol import Host, Model, action, tools, final
from pdf_ai import AiResponseError


def intent(folder=None):
    return {'decision':'request','evidence':'폴더 안 전부 옮겨줘','operations':['trash'],
            'sourceScope':'all','sourceFolderId':folder,'selectionAll':True,'proposalId':'','clarificationId':''}


class SourceFolderTests(unittest.TestCase):
    def test_followup_ceiling_comes_from_pending_task_before_native_binding(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'pendingRequest':{
            'clarificationId':'pending','operations':['trash'],'sourceScope':'all','sourceFolderId':'source','selectionAll':False}}
        original=host.__call__;bindings=[];writes=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bindings.append(copy.deepcopy(args));return {'ok':True,'data':{}}
            if tool=='library.trash':writes.append(args);return {'ok':True,'data':{'trashedCount':1,'applied':True}}
            return original(tool,args,quote)
        wrong=tools(action('library.trash',{'ids':[{'kind':'document','id':'a'}],'expectedRevision':'r'}));wrong['libraryIntent']={**intent('source'),'clarificationId':'pending'}
        fixed=copy.deepcopy(wrong);fixed['libraryIntent']['selectionAll']=False;fixed['completeAfterLocal']=True
        model=Model(wrong,fixed)
        _,effects=run({'question':'그대로 해줘'},model,'system',200,local)
        self.assertEqual(1,len(bindings));self.assertFalse(bindings[0]['selectionAll']);self.assertEqual(1,len(writes));self.assertEqual(1,len(effects))
        self.assertFalse(model.calls[1][0]['libraryPlanCorrection']['ceiling']['selectionAll'])

    def test_cancellation_can_reference_pending_task_without_write_authority(self):
        for token_field in ('clarificationId','proposalId'):
            value={**intent(),'decision':'reject','operations':[],token_field:'pending'}
            validate_library_intent(value)
            value['operations']=['move']
            with self.assertRaises(AiResponseError):validate_library_intent(value)
        value={**intent(),'decision':'none','operations':[],'proposalId':'pending'}
        with self.assertRaises(AiResponseError):validate_library_intent(value)

    def test_lost_source_and_selection_metadata_is_repaired_without_writes(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True}
        original=host.__call__;writes=[];bindings=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bindings.append(copy.deepcopy(args));return {'ok':True,'data':{}}
            if tool=='library.query':return {'ok':True,'data':{'revision':'r','items':[{'kind':'document','id':'a','parentId':'source'}]}}
            if tool=='library.trash':
                writes.append(copy.deepcopy(args));return {'ok':True,'data':{'trashedCount':1,'applied':True}}
            return original(tool,args,quote)
        fixed={**intent('source'),'selectionAll':False}
        query=tools(action('library.query',{'parentId':'source'}));query['libraryIntent']=copy.deepcopy(fixed)
        # The screenshot's second response lost the source and flipped selectionAll.
        lost=tools(action('library.trash',{'ids':[{'kind':'document','id':'outside'}],'expectedRevision':'r'}))
        lost['libraryIntent']={**intent(),'selectionAll':True}
        corrected=tools(action('library.trash',{'ids':[{'kind':'document','id':'a'}],'expectedRevision':'r'}))
        corrected['libraryIntent']=copy.deepcopy(fixed);corrected['completeAfterLocal']=True
        model=Model(query,lost,corrected)
        _,effects=run({'question':'원본에서 9주차 말고 정리해줘'},model,'system',200,local)
        self.assertEqual(1,len(effects));self.assertEqual(1,len(writes))
        self.assertEqual('a',writes[0]['ids'][0]['id']);self.assertEqual('source',bindings[0]['sourceFolderId'])
        self.assertEqual(fixed,model.calls[1][0]['libraryTaskPlan']['ceiling'])
        self.assertTrue(model.calls[2][0]['libraryPlanCorrection']['issues'])
        self.assertEqual(0,model.planning)

    def test_different_concrete_source_or_new_operation_is_not_repaired(self):
        payload={'localContext':{'library':{}},'localResults':[]}
        for changed in ({**intent('destination')},{**intent('source'),'operations':['rename']}):
            self.assertIsNone(library_plan_correction(intent('source'),changed,[],payload))

    def test_related_explanation_preserves_reference_without_authority(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True}
        original=host.__call__;bindings=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':bindings.append(copy.deepcopy(args));return {'ok':True,'data':{}}
            return original(tool,args,quote)
        response=final('중간고사와 기말고사 폴더로 분류한다는 뜻이에요.')
        response['libraryIntent']={**intent(),'decision':'none','operations':[],'selectionAll':False,'clarificationId':'pending'}
        model=Model(response)
        _,effects=run({'question':'그렇게 분류하면 어떤 차이야?'},model,'system',200,local)
        self.assertEqual([],effects);self.assertEqual('pending',bindings[0]['clarificationId'])
        self.assertEqual([],bindings[0]['operations'])

    def test_validation_is_backward_compatible_but_rejects_conflicting_scope(self):
        legacy=intent();legacy.pop('sourceFolderId');validate_library_intent(legacy)
        for folder in ('folder-id',None):validate_library_intent(intent(folder))
        for bad in ('',[],5,'a'*129):
            with self.assertRaises(AiResponseError):validate_library_intent(intent(bad))
        value=intent('folder-id');value['sourceScope']='current'
        with self.assertRaises(AiResponseError):validate_library_intent(value)

    def test_fixed_folder_cannot_be_removed_or_changed(self):
        fixed=intent('source')
        for changed in (intent(None),intent('destination')):
            self.assertFalse(library_intent_narrows(fixed,changed))
            self.assertFalse(library_intent_within_ceiling(fixed,changed))
        self.assertTrue(library_intent_within_ceiling(intent(),fixed))
        self.assertFalse(library_intent_narrows(intent(),fixed))
        self.assertTrue(library_intent_narrows(fixed,copy.deepcopy(fixed)))

    def test_clarification_and_compacted_context_keep_named_source(self):
        initial=intent('source');clarify={**intent(),'decision':'clarify','operations':[]}
        self.assertEqual('source',library_clarification_plan(clarify,initial)['sourceFolderId'])
        value={'library':{'pendingRequest':{'sourceFolderId':'source','targets':[]},'pendingClarification':{'sourceFolderId':'source','candidates':[]}}}
        projected=model_context(value)
        for name in ('pendingRequest','pendingClarification'):
            self.assertEqual(value['library'][name],projected['library'][name])

    def test_preflight_checks_selected_parents_not_the_current_screen(self):
        value=intent('source');request=action('library.trash',{'ids':[{'kind':'document','id':'a'}]})
        request['arguments']={'ids':[{'kind':'document','id':'a'}]}
        payload={'localContext':{'library':{'requestView':{'currentFolderId':'unrelated'}}},
                 'localResults':[{'request':{'tool':'library.query'},'result':{'ok':True,'data':{'items':[{'kind':'document','id':'a','parentId':'source'}]}}}]}
        self.assertIsNone(library_plan_correction(value,value,[request],payload))
        payload['localResults'][0]['result']['data']['items'][0]['parentId']='outside'
        self.assertIsNotNone(library_plan_correction(value,value,[request],payload))

    def test_no_new_classifier_or_answer_round_is_added(self):
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True}
        original=host.__call__;received=[]
        def local(tool,args,quote):
            if tool=='internal.libraryIntent':received.append(args);return {'ok':True,'data':{}}
            if tool=='library.query':return {'ok':True,'data':{'revision':'r','items':[]}}
            if tool=='library.trash':return {'ok':True,'data':{'trashedCount':1,'applied':True}}
            return original(tool,args,quote)
        query=tools(action('library.query',{'parentId':'source'}));query['libraryIntent']=intent('source')
        write=tools(action('library.trash',{'ids':[{'kind':'document','id':'a'}],'expectedRevision':'r'}));write['libraryIntent']=intent('source');write['completeAfterLocal']=True
        model=Model(query,write)
        _,effects=run({'question':'폴더 안 전부 옮겨줘'},model,'system',200,local)
        self.assertEqual(2,len(model.calls));self.assertEqual(0,model.planning)
        self.assertEqual('source',received[0]['sourceFolderId']);self.assertEqual(1,len(effects))
        schema=FORMAT['json_schema']['schema']['properties']['libraryIntent']['anyOf'][1]
        self.assertIn('sourceFolderId',schema['required'])


if __name__=='__main__':unittest.main()
