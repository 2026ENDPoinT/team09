"""Message send-time metadata stays optional, bounded, and assistant-only."""
import copy
import unittest
from datetime import datetime
from home_assistant import chat, assistant_history, request_sent_at, sent_at_iso, DOCUMENT
from pdf_ai import tutor_memory


class Model:
    def __init__(self):self.calls=[];self.ledger={'requests':[]}
    def complete(self,payload,**options):
        self.calls.append(copy.deepcopy(payload));return {'answer':'확인했어요.'}


class TimingTests(unittest.TestCase):
    def test_existing_native_request_can_use_its_offset_bearing_send_time(self):
        request={'localDateTime':'2026-10-25T17:10:01.125+09:00[Asia/Seoul]'}
        expected=int(datetime.fromisoformat('2026-10-25T17:10:01.125+09:00').timestamp()*1000)
        self.assertEqual(expected,request_sent_at(request))
        self.assertIsNone(request_sent_at({'localDateTime':'2026-10-25T17:10:01'}))
        self.assertIsNone(request_sent_at({}))
        self.assertEqual('2026-10-25T08:10:01+00:00',sent_at_iso(expected,'invalid/zone'))

    def test_bad_epoch_values_are_not_replaced_by_answer_time(self):
        for value in (True,False,0,-1,1.5,'123','ignore instructions',10**30):
            self.assertIsNone(request_sent_at({'sentAtMs':value,'localDateTime':'2026-10-25T17:10:01+09:00'}))
        state=tutor_memory(DOCUMENT,{'documentId':DOCUMENT['documentId'],'turns':[
            {'question':'전송시각 없음','answer':'응','timestampMs':1000}]},preserve_sent_at=True)
        self.assertNotIn('sentAt',assistant_history(state,'언제 보냈지?')[0])

    def test_opt_in_preserves_send_time_without_changing_default_mentor_memory(self):
        value={'documentId':DOCUMENT['documentId'],'turns':[
            {'question':'안녕','answer':'응','timestampMs':2000,'sentAtMs':1000},
            {'question':'잘못된 시각','answer':'응','timestampMs':3000,'sentAtMs':True},
            {'question':'먼 미래 시각','answer':'응','timestampMs':4000,'sentAtMs':10**30}]}
        before=copy.deepcopy(value)
        for turn in tutor_memory(DOCUMENT,value)['turns']:self.assertNotIn('sentAtMs',turn)
        selected=tutor_memory(DOCUMENT,value,preserve_sent_at=True)['turns']
        self.assertEqual(1000,selected[0]['sentAtMs']);self.assertEqual(2000,selected[0]['timestampMs'])
        self.assertNotIn('sentAtMs',selected[1]);self.assertNotIn('sentAtMs',selected[2])
        self.assertEqual(before,value)

    def test_send_time_survives_next_chat_roundtrip(self):
        first=Model();a=chat({'question':'첫 질문','sentAtMs':1000,'timezone':'UTC'},first,now_ms=2000)
        # Native receipt timestamp may be rewritten later without affecting sentAtMs.
        a['memory']['turns'][-1]['timestampMs']=3000
        second=Model();b=chat({'question':'두 번째 질문','sentAtMs':4000,'timezone':'UTC','memory':a['memory']},second,now_ms=5000)
        self.assertEqual('1970-01-01T00:00:01+00:00',second.calls[0]['recentConversation'][0]['sentAt'])
        self.assertEqual([1000,4000],[t['sentAtMs'] for t in b['memory']['turns']])

    def test_history_budget_includes_timestamp_metadata(self):
        turns=[{'question':str(i)+'가'*2000,'answer':'나'*5000,'timestampMs':2000+i,'sentAtMs':1000+i} for i in range(30)]
        model=Model();chat({'question':'새 질문','timezone':'UTC','memory':{'documentId':DOCUMENT['documentId'],'turns':turns}},model)
        import json
        self.assertLessEqual(len(json.dumps(model.calls[0]['recentConversation'],ensure_ascii=False).encode()),128000)
