"""Regression checks for unexpected Japanese/Chinese model output."""
import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path

import pdf_page_study as fused
from pdf_output_language import (STRICT_KOREAN_RETRY, analysis_issues,
                                 foreign_prose, generated_issues, study_issues)
from test_pdf_page_analysis import document
from test_pdf_page_study import study_response


class LanguageGuardTests(unittest.TestCase):
    def test_japanese_and_chinese_explanations_are_rejected_but_source_quotes_are_not(self):
        self.assertTrue(foreign_prose("直接金融とは、証券を販売して資金を調達する方式です。"))
        self.assertTrue(foreign_prose("直接金融是通过证券市场筹集资金的方式。"))
        self.assertFalse(foreign_prose("직접금융은 금융시장에서 자금을 조달하는 방식입니다."))
        result={"summary":{"title":"직접금융","body":"한국어 설명입니다.",
                           "evidence":[{"quote":"証券を販売する"}]},"concepts":[]}
        self.assertFalse(generated_issues(result))
        result["summary"]["body"]="証券を販売して資金を調達する方式です。"
        self.assertEqual(study_issues(result),["summary.body"])
        reading={"inventory":[{"label":"金融市場の説明"}],
                 "elements":[{"transcription":"証券を販売する"}]}
        self.assertTrue(analysis_issues(reading,"한국어 금융 강의 자료입니다. 금융시장을 설명합니다."))

    def test_fused_page_retries_once_in_korean_and_reuses_good_cache(self):
        class Provider:
            model="gpt-6-luna"
            def __init__(self): self.calls=[]; self.context={}
            def complete(self,payload,**kwargs):
                self.calls.append(kwargs)
                value=study_response(payload)
                if len(self.calls)==1:
                    value=copy.deepcopy(value)
                    value["analysis"]["inventory"][0]["label"]="金融市場の説明"
                    value["study"]["summary"]["parts"][0]["body"]="証券を販売して資金を調達する方式です。"
                return value
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            folder=Path(temporary)
            handout=document(folder)
            provider=Provider()
            analysis, study, _=fused.request_study(folder,handout,1,provider,{})
            self.assertEqual(analysis["status"],"ready")
            self.assertFalse(study_issues(study))
            self.assertEqual(len(provider.calls),2)
            self.assertIn(STRICT_KOREAN_RETRY,provider.calls[1]["system_prompt"])
            self.assertTrue(list((folder/"generated"/"page-study").glob("*/combined-korean-retry.json")))
            fused.request_study(folder,handout,1,provider,{})
            self.assertEqual(len(provider.calls),2)


if __name__ == "__main__":
    unittest.main()
