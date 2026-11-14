import copy,json,unittest
from assistant_library_refs import LibraryRefs
from assistant_protocol import run
from test_assistant_protocol import Host,Model,tools,action,final
from test_assistant_source_folder import intent


class LibraryRefsTest(unittest.TestCase):
    def test_malformed_envelopes_are_left_for_the_existing_validator(self):
        refs=LibraryRefs()
        for value in (None,[],{'localRequests':None},{'localRequests':5},{'localRequests':[None,{'tool':'library.query','argumentsJson':'{broken'}]}):
            self.assertEqual(value,refs.response(value))

    def test_exact_round_trip_and_domain_isolation(self):
        source='12345678-1234-1234-1234-123456789012';document='a'*64;revision='b'*64
        value={'localContext':{'library':{'revision':revision,'currentFolderId':source,'visibleItems':[{'id':document,'name':source,'parentId':source}]},'plannerAccess':{'revision':revision}},
               'libraryTaskPlan':{'ceiling':{'sourceFolderId':source}},'localResults':[]}
        original=copy.deepcopy(value);refs=LibraryRefs();wire=refs.payload(value)
        self.assertEqual(original,value);self.assertEqual(source,wire['localContext']['library']['visibleItems'][0]['name'])
        self.assertEqual(revision,wire['localContext']['plannerAccess']['revision'])
        folder=wire['localContext']['library']['currentFolderId'];rev=wire['localContext']['library']['revision'];doc=wire['localContext']['library']['visibleItems'][0]['id']
        self.assertEqual(folder,wire['libraryTaskPlan']['ceiling']['sourceFolderId'])
        response={'libraryIntent':{'sourceFolderId':folder},'localRequests':[{'tool':'library.proposeMove','id':'request1','argumentsJson':json.dumps({'destinationId':folder,'expectedRevision':rev,'ids':[{'kind':'document','id':doc}]})},{'tool':'planner.query','argumentsJson':json.dumps({'id':doc})}]}
        decoded=refs.response(response);arguments=json.loads(decoded['localRequests'][0]['argumentsJson'])
        self.assertEqual(source,decoded['libraryIntent']['sourceFolderId']);self.assertEqual(document,arguments['ids'][0]['id']);self.assertEqual(revision,arguments['expectedRevision'])
        self.assertEqual(response['localRequests'][1],decoded['localRequests'][1])

    def test_aliases_are_stable_within_turn_and_unknown_values_are_never_guessed(self):
        refs=LibraryRefs();value={'localContext':{'library':{'currentFolderId':'a'*64}},'localResults':[]}
        self.assertEqual(refs.payload(value),refs.payload(value))
        response={'libraryIntent':{'sourceFolderId':'LI999'},'localRequests':[{'tool':'library.query','argumentsJson':'{"parentId":"LI999"}'}]}
        self.assertEqual('LI999',refs.response(response)['libraryIntent']['sourceFolderId'])
        self.assertEqual('LI1',LibraryRefs().response({'libraryIntent':{'sourceFolderId':'LI1'}})['libraryIntent']['sourceFolderId'])

    def test_real_protocol_decodes_aliases_before_any_native_permission_or_write(self):
        source='12345678-1234-1234-1234-123456789012';document='a'*64;revision='b'*64
        host=Host();host.context['library']={'available':True,'semanticAuthorization':True,'currentFolderId':source,'revision':revision}
        original=host.__call__;seen=[]
        def local(tool,args,quote):
            if tool=='library.query':
                self.assertEqual(source,args['parentId']);return {'ok':True,'data':{'revision':revision,'items':[{'id':document,'kind':'document','parentId':source}]}}
            if tool=='internal.libraryIntent':
                self.assertEqual(source,args['sourceFolderId']);return {'ok':True,'data':{}}
            if tool=='library.trash':
                seen.append(args);return {'ok':True,'data':{'trashedCount':1,'applied':True}}
            return original(tool,args,quote)
        queried=tools(action('library.query',{'parentId':'LI1'}));queried['libraryIntent']={**intent('LI1'),'selectionAll':False}
        written=tools(action('library.trash',{'ids':[{'kind':'document','id':'LI2'}],'expectedRevision':'LR1'}));written['completeAfterLocal']=True
        model=Model(queried,written,final('완료했어요.'))
        _,effects=run({'question':'이 폴더 자료를 지워줘'},model,'system',200,local)
        self.assertEqual(document,seen[0]['ids'][0]['id']);self.assertEqual(revision,seen[0]['expectedRevision']);self.assertEqual(1,len(effects))


if __name__=='__main__':unittest.main()
