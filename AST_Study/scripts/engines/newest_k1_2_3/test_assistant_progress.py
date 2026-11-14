"""Offline progress ordering and truthful outcomes without additional model calls."""
import copy
import unittest
from assistant_progress import Activity, result_text
from assistant_protocol import run, validate_envelope
from home_assistant import chat
from test_assistant_protocol import Host, Model, action, tools, final
from pdf_ai import AiResponseError


class ProgressTests(unittest.TestCase):
    def test_schedule_completion_reports_details_without_repeating_execution_or_extra_calls(self):
        for tone in ('polite','casual','formal'):
            rows=[];host=Host('해커톤 OT 일정 등록해줘');host.context['personalization']['values']['tone']=tone
            host.context['plannerAccess']['scheduleBatchSupported']=True
            response=tools(action('planner.scheduleBatch',{}));response['completeAfterLocal']=True
            data={'addedCount':1,'entries':[{'title':'해커톤 OT','addedCount':1,'firstAdded':'2026-11-04T18:00','lastAdded':'2026-11-04T18:00'}]}
            def local(tool,args,quote):
                if tool=='planner.scheduleBatch':return {'ok':True,'data':data}
                return host(tool,args,quote)
            model=Model(response)
            answer,_=run({'question':'해커톤 OT 일정 등록해줘'},model,'system',100,local,activity=rows.append)
            self.assertEqual(1,len(model.calls));self.assertEqual(0,model.planning)
            self.assertIn('1개 일정을 등록',rows[-1]['text']);self.assertNotIn('1개 일정을 등록',answer)
            self.assertIn('해커톤 OT',answer);self.assertIn('2026-11-04',answer)
            self.assertNotIn('검증',str(rows)+answer)

    def test_schedule_conflicts_and_already_registered_counts_survive_detail_summary(self):
        from assistant_protocol import schedule_batch_summary
        data={'addedCount':1,'alreadyPresentCount':2,'skippedCount':1,'entries':[],'blockers':[]}
        answer=schedule_batch_summary(data,details_only=True)
        self.assertIn('등록된 일정: 1개',answer);self.assertIn('2개는',answer)
        self.assertIn('1개 회차',answer);self.assertIn('추가할까요',answer)

    def test_existing_rounds_report_before_and_after_host_without_extra_call(self):
        rows=[];host=Host();model=Model(tools(action('planner.query',{})),final('일정을 확인했어요.'))
        def local(tool,args,quote):
            if tool=='planner.query':
                self.assertEqual('plan',rows[-1]['phase'])
                self.assertFalse(any(r['phase']=='result' for r in rows))
            return host(tool,args,quote)
        answer,effects=run({'question':'일정 알려줘'},model,'system',100,local,activity=rows.append)
        self.assertEqual(2,len(model.calls));self.assertEqual(['plan','result'],[r['phase'] for r in rows])
        self.assertIn('1개',rows[1]['text']);self.assertEqual('일정을 확인했어요.',answer)
        self.assertNotIn('activity',model.calls[-1][0]);self.assertEqual([],effects)

    def test_model_note_is_displayed_but_premature_answer_is_never_shown(self):
        rows=[];host=Host();pending=tools(action('planner.query',{}))
        pending.update(answer='저장 완료!',progress='해당 기간의 일정을 확인할게요.')
        model=Model(pending,final())
        run({'question':'일정 조회'},model,'system',100,host,activity=rows.append)
        self.assertEqual(pending['progress'],rows[0]['text'])
        self.assertNotIn('저장 완료!',str(rows))

    def test_plain_conversation_has_no_work_updates(self):
        rows=[];model=Model(final('안녕하세요.'))
        result=chat({'question':'안녕'},model,local=Host(),activity=rows.append)
        self.assertEqual([],rows);self.assertEqual(1,len(model.calls))
        self.assertEqual('안녕하세요.',result['answer'])

    def test_completed_write_can_still_finish_without_final_model_call(self):
        rows=[];host=Host('일정 추가해줘');value=tools(action('planner.apply',{'changes':[{'operation':'create','fields':{'title':'시험'}}]}))
        value['completeAfterLocal']=True;model=Model(value)
        _,effects=run({'question':'일정 추가해줘'},model,'system',100,host,activity=rows.append)
        self.assertEqual(1,len(model.calls));self.assertEqual(1,len(effects))
        self.assertEqual('result',rows[-1]['phase'])

    def test_failed_action_is_not_announced_as_completed(self):
        rows=[];activity=Activity(rows.append)
        local=activity.wrap(lambda *args:{'ok':False,'error':'대상이 바뀌었어요.'})
        local('library.confirmMove',{},'')
        self.assertEqual(['plan','error'],[r['phase'] for r in rows])
        self.assertIn('완료하지 못',rows[-1]['text']);self.assertNotIn('옮겼어요',rows[-1]['text'])
        def fail(*args):raise InterruptedError('stopped')
        with self.assertRaises(InterruptedError):activity.wrap(fail)('library.rename',{},'')
        self.assertIn('결과를 확인하지 못',rows[-1]['text'])

    def test_move_proposal_already_present_partial_and_actual_move_are_distinct(self):
        proposed=result_text('library.proposeMove',{'ok':True,'data':{'proposalId':'p'}})
        self.assertIn('아직',proposed);self.assertNotIn('옮겼어요',proposed)
        self.assertIn('이미',result_text('library.confirmMove',{'ok':True,'data':{'alreadyThere':True}}))
        self.assertIn('3개',result_text('library.confirmMove',{'ok':True,'data':{'movedCount':3,'destinationPath':'홈 > 수업'}}))
        partial=result_text('planner.scheduleBatch',{'ok':True,'data':{'addedCount':4,'skippedCount':2}})
        self.assertIn('4개',partial);self.assertIn('겹친 2개',partial)

    def test_cached_legacy_envelope_and_invalid_progress(self):
        value=final();validate_envelope(value);self.assertEqual('',value['progress'])
        for note in (None,{},'가'*241):
            value=final();value['progress']=note
            with self.assertRaises(AiResponseError):validate_envelope(value)

    def test_updates_are_not_put_in_saved_model_memory(self):
        rows=[];model=Model(tools(action('planner.query',{})),final('내일 시험이 있어요.'))
        result=chat({'question':'일정 알려줘'},model,local=Host(),activity=rows.append)
        self.assertEqual(2,len(rows));self.assertEqual('내일 시험이 있어요.',result['memory']['turns'][-1]['answer'])
        self.assertNotIn('activity',str(result['memory']))

    def test_internal_checks_are_silent_and_saved_tone_is_used(self):
        rows=[];host=Host();host.context['personalization']['values']['tone']='casual'
        local=Activity(rows.append).wrap(host)
        local('context.get',{},'');self.assertEqual([],rows)
        local('planner.query',{},'')
        self.assertTrue(rows[0]['text'].endswith('할게.'));self.assertTrue(rows[-1]['text'].endswith('했어.'))


if __name__=='__main__':unittest.main()
