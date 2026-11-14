"""Offline semantic authorization replays; no paid calls or real user stores."""
import copy
import unittest
from assistant_protocol import FORMAT, allowed_tools, run, validate_envelope
from pdf_ai import AiResponseError
from home_assistant import SYSTEM, MAX_OUTPUT
from test_assistant_protocol import Host, Model, action, tools, final


def intent(question, decision='request', scopes=None, operations=None, reference='', **flags):
    return dict(decision=decision,evidence=question,scopes=['planner'] if scopes is None else scopes,
                plannerOperations=['create'] if operations is None else operations,referenceId=reference,
                resetPersonalization=flags.get('reset',False),allRecurring=flags.get('series',False))


class SemanticHost(Host):
    def __init__(self, question):
        super().__init__();self.question=question
        self.context.update(semanticMutationAuthorization=True,mutationReferences=[])
    def __call__(self, tool, args, quote):
        if tool=='internal.mutationIntent':
            self.calls.append((tool,copy.deepcopy(args),quote))
            if args['question']!=self.question or not args['evidence'] or args['evidence'] not in self.question:
                return {'ok':False,'error':'현재 직접 입력한 요청의 근거를 확인해 주세요.'}
            if args['referenceId'] and args['referenceId'] not in [ref['id'] for ref in self.context['mutationReferences']]:
                return {'ok':False,'error':'어떤 작업에 동의하셨는지 확인해 주세요.'}
            actionable=args['decision'] in ('request','approve')
            self.context.update(mutationScope=','.join(args['scopes']) if actionable else '',authorizationQuote='native verified request' if actionable else '')
            return {'ok':True,'data':{'decision':args['decision']}}
        return super().__call__(tool,args,quote)


def create():
    return action('planner.apply',{'expectedRevision':4,'changes':[{'entity':'event','operation':'create','id':None,
        'fields':{'title':'스페인어 수업','start':'2026-10-27T16:00','end':'2026-10-27T18:00'}}]})


class MutationIntentTests(unittest.TestCase):
    def test_five_turns_of_discussion_then_current_consent(self):
        host=SemanticHost('학지 일정 색을 다른 걸로 해줘');memory=None;writes=[]
        questions=['학지 일정 색을 다른 걸로 해줘','분홍과 슬레이트는 어떤 색이야?',
                   '학지에는 어느 쪽이 어울릴까?','슬레이트로 하고 싶은데 잘 보일지 설명해줘. 적용은 기다려',
                   'ㅇㅋ 그렇게 진행해줘.']
        for number,question in enumerate(questions):
            host.question=question;host.context['mutationScope']='';host.context['authorizationQuote']=''
            host.context['mutationReferences']=[] if number==0 else [{'id':'pending-color','question':questions[0],'pending':True}]
            if number==0:
                response=final('어떤 색으로 바꿀까요?');response['mutationIntent']=intent(question,'clarify',operations=['update'])
            elif number<4:
                response=final('슬레이트는 푸른빛이 도는 회색이에요. 아직 적용하지 않았어요.')
                response['mutationIntent']=intent('', 'none',scopes=[],operations=[],reference='pending-color')
            else:
                response=tools(action('planner.apply',{'changes':[{'entity':'event','operation':'update','id':'hakji','fields':{'color':'SLATE'}}]}))
                response.update(mutationIntent=intent(question,'approve',operations=['update'],reference='pending-color'),completeAfterLocal=True)
            model=Model(response);start=len(host.calls)
            from home_assistant import chat
            result=chat({'question':question,'memory':memory},model,local=host);memory=result['memory']
            writes.extend((number,c) for c in host.calls[start:] if c[0]=='planner.apply')
            self.assertEqual(1,len(model.calls));self.assertEqual(0,model.planning)
            if number<4:self.assertEqual([],writes)
        self.assertEqual(1,len(writes));self.assertEqual(4,writes[0][0]);self.assertEqual('hakji',writes[0][1][1]['changes'][0]['id'])

    def test_unrelated_library_housekeeping_never_replaces_a_valid_explanation(self):
        host=SemanticHost('분홍과 슬레이트가 뭐야?');host.context['library']={'available':True,'semanticAuthorization':True}
        response=final('분홍은 밝은 분홍빛, 슬레이트는 푸른빛이 도는 회색이에요.')
        response['libraryIntent']={'decision':'none','evidence':'','operations':[],'sourceScope':'all','sourceFolderId':None,'selectionAll':False,'proposalId':'','clarificationId':''}
        seen=[]
        def old_app(tool,args,quote):
            if tool=='internal.libraryIntent':
                seen.append(args);return {'ok':False,'error':'허용되지 않은 파일 작업 필드예요.'}
            return host(tool,args,quote)
        answer,effects=run({'question':host.question},Model(response),SYSTEM,MAX_OUTPUT,old_app)
        self.assertEqual(response['answer'],answer);self.assertEqual([],effects)
        self.assertNotIn('sourceFolderId',seen[0])

    def test_schema_and_catalog_do_not_need_a_keyword_grant(self):
        schema=FORMAT['json_schema']['schema'];self.assertIn('mutationIntent',schema['required'])
        self.assertNotIn('internal.mutationIntent',schema['properties']['localRequests']['items']['properties']['tool']['enum'])
        self.assertTrue({'planner.apply','memory.update'}.issubset(allowed_tools(SemanticHost('안녕').context)))
        self.assertNotIn('planner.apply',allowed_tools(Host().context))
        for wrong in (dict(intent('x'),scopes=['system']),dict(intent('x'),plannerOperations=['create','create']),dict(intent('x'),decision='approve'),dict(intent('x'),allRecurring='yes')):
            response=final();response['mutationIntent']=wrong
            with self.assertRaises(AiResponseError):validate_envelope(response)

    def test_screenshot_request_queries_then_binds_once_without_extra_ai_call(self):
        question='화요일 16시~18시 스페인어 수업 등록해줘.';host=SemanticHost(question)
        lookup=tools(action('planner.query',{'from':'2026-10-27','to':'2026-10-28'}));lookup['mutationIntent']=intent(question)
        write=tools(create());write['completeAfterLocal']=True;model=Model(lookup,write)
        answer,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(2,len(model.calls));self.assertEqual(['planner.apply'],[e['tool'] for e in effects]);self.assertTrue(answer)
        names=[c[0] for c in host.calls];self.assertEqual(1,names.count('internal.mutationIntent'))
        self.assertLess(names.index('planner.query'),names.index('internal.mutationIntent'));self.assertLess(names.index('internal.mutationIntent'),names.index('planner.apply'))
        self.assertEqual('native verified request',next(c[2] for c in host.calls if c[0]=='planner.apply'))

    def test_free_form_consent_continues_real_user_request(self):
        for question in ('등록해줘','그 방향으로 부탁드릴게요','그래 그 시간이면 딱 괜찮겠다'):
            with self.subTest(question=question):
                host=SemanticHost(question);host.context['mutationReferences']=[{'id':'original','question':'화요일 16~18시 스페인어 수업 등록'}]
                write=tools(create());write.update(mutationIntent=intent(question,'approve',reference='original'),completeAfterLocal=True)
                model=Model(write);_,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,host)
                self.assertEqual(1,len(effects));self.assertEqual(1,len(model.calls))

    def test_ambiguity_records_pending_task_without_granting_or_writing(self):
        question='내일 일정 좀 바꿔줘';host=SemanticHost(question)
        response=final('어느 일정의 어떤 내용을 바꿀까요?');response['mutationIntent']=intent(question,'clarify',operations=['update'])
        answer,effects=run({'question':question},Model(response),SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(response['answer'],answer);self.assertFalse(effects)
        self.assertFalse(any(c[0]=='planner.apply' for c in host.calls))
        self.assertEqual('',host.context['mutationScope'])
        self.assertEqual(1,sum(c[0]=='internal.mutationIntent' for c in host.calls))

    def test_general_conversation_has_no_extra_permission_or_call(self):
        host=SemanticHost('고마워');model=Model(final('도움이 돼서 다행이에요.'))
        _,effects=run({'question':'고마워'},model,SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(1,len(model.calls));self.assertFalse(effects);self.assertEqual(['context.get'],[c[0] for c in host.calls])

    def test_missing_intent_or_reference_asks_instead_of_claiming_unsupported(self):
        for mutation in (None,intent('좋아요','approve',reference='invented')):
            host=SemanticHost('좋아요');write=tools(create());write['mutationIntent']=mutation
            answer,effects=run({'question':'좋아요'},Model(write),SYSTEM,MAX_OUTPUT,host)
            self.assertFalse(effects);self.assertNotIn('지원',answer);self.assertNotIn('planner.apply',[c[0] for c in host.calls])

    def test_stale_evidence_is_rebound_to_direct_current_text(self):
        question='수업 넣어달라니까?';host=SemanticHost(question);write=tools(create());write.update(mutationIntent=intent('수업을 넣어줘'),completeAfterLocal=True)
        model=Model(write);_,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(['planner.apply'],[e['tool'] for e in effects]);self.assertEqual(question,next(c[1]['evidence'] for c in host.calls if c[0]=='internal.mutationIntent'))

    def test_quoted_request_cannot_be_repaired_into_consent(self):
        question='“수업을 넣어줘”를 번역해줘';host=SemanticHost(question);write=tools(create());write['mutationIntent']=intent('수업을 넣어줘')
        model=Model(write);answer,effects=run({'question':question},model,SYSTEM,MAX_OUTPUT,host)
        self.assertFalse(effects);self.assertEqual(1,len(model.calls));self.assertNotIn('planner.apply',[c[0] for c in host.calls]);self.assertIn('인용문',answer)

    def test_multiple_domains_share_one_decision_and_native_provenance(self):
        question='수업 등록하고 내 호칭은 기본으로 해줘';host=SemanticHost(question)
        write=tools(create(),action('memory.update',{'expectedRevision':0,'set':{},'remove':['preferredName']},identifier='m'))
        write['mutationIntent']=intent(question,scopes=['planner','memory'],reset=True)
        _,effects=run({'question':question},Model(write,final('반영했어요.')),SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(['planner.apply','memory.update'],[e['tool'] for e in effects]);self.assertEqual(1,sum(c[0]=='internal.mutationIntent' for c in host.calls))
        self.assertTrue(all(c[2]=='native verified request' for c in host.calls if c[0] in ('planner.apply','memory.update')))

    def test_permission_cannot_expand_after_first_save(self):
        question='수업 등록해줘';host=SemanticHost(question);first=tools(create());first['mutationIntent']=intent(question)
        second=tools(action('memory.update',{'expectedRevision':0,'set':{'tone':'casual'},'remove':[]}));second['mutationIntent']=intent(question,scopes=['planner','memory'])
        answer,effects=run({'question':question},Model(first,second),SYSTEM,MAX_OUTPUT,host)
        self.assertEqual(['planner.apply'],[e['tool'] for e in effects]);self.assertNotIn('memory.update',[c[0] for c in host.calls]);self.assertIn('추가 변경',answer)


if __name__=='__main__':unittest.main()
