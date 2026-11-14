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
