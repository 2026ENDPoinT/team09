"""Offline stage events follow retrieval, without changing model work or prose."""
import unittest
from unittest.mock import patch

import pdf_ai
from test_pdf_tutor_final_answer import Provider, reply
from test_pdf_tutor_intent import document, semantic


class TutorStageTests(unittest.TestCase):
    def test_search_finishes_before_answer_wait_and_streaming(self):
        events=[]
        original=pdf_ai.tutor_hits
        def hits(*args, **kwargs):
            self.assertEqual(events, [('stage', 'pdf_search')])
            result=original(*args, **kwargs)
            events.append(('search', 'done'))
            return result
        class StreamingProvider(Provider):
            def complete(inner, payload, **kwargs):
                self.assertEqual(events[-1], ('stage', 'answer_wait'))
                return super().complete(payload, **kwargs)
        provider=StreamingProvider([reply('운동량은 보존돼요.')], semantic('운동량'))
        with patch.object(pdf_ai, 'tutor_hits', side_effect=hits):
            result=pdf_ai.tutor(document(), '운동량을 설명해줘', provider,
                stage=lambda value:events.append(('stage',value)),
                progress=lambda value:events.append(('delta',value)))
        self.assertEqual(events[:3], [('stage','pdf_search'),('search','done'),('stage','answer_wait')])
        self.assertEqual(events[-1], ('delta',result['answer']))
        self.assertEqual(len(provider.calls),1)

    def test_stages_do_not_change_payload_usage_or_final_answer(self):
        first=Provider([reply('원리를 설명해요.')],semantic('운동량'))
        second=Provider([reply('원리를 설명해요.')],semantic('운동량'))
        plain=pdf_ai.tutor(document(),'운동량을 설명해줘',first)
        stages=[]
        shown=pdf_ai.tutor(document(),'운동량을 설명해줘',second,stage=stages.append)
        self.assertEqual(first.calls,second.calls)
        self.assertEqual(plain['answer'],shown['answer'])
        self.assertEqual(stages,['pdf_search','answer_wait'])

    def test_web_wait_is_emitted_before_external_answer_call(self):
        events=[]
        class WebProvider(Provider):
            def web_search(inner,*args,**kwargs):
                self.assertEqual(events[-1],'answer_wait')
                return super().web_search(*args,**kwargs)
        provider=WebProvider([],semantic('현재 통계',web='explicit'),
            web={'answer':'확인한 내용이에요.','webSources':[]})
        result=pdf_ai.tutor(document(),'현재 통계를 외부 검색해줘',provider,stage=events.append)
        self.assertEqual(events,['pdf_search','answer_wait'])
        self.assertEqual(result['kind'],'web_generated')
        self.assertEqual(len(provider.searches),1)

    def test_local_greeting_never_pretends_to_wait_for_api(self):
        stages=[]
        pdf_ai.tutor(document(),'안녕',stage=stages.append)
        self.assertEqual(stages,[])


if __name__=='__main__':unittest.main()
