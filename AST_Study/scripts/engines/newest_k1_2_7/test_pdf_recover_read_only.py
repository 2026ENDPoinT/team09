"""Local recovery must not rewrite an index or create a provider."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pdf_ai as ai
import pdf_new_concept_ver99_study as study


class RecoverReadOnlyTests(unittest.TestCase):
    def test_recover_keeps_document_and_saved_prose_without_provider_or_network(self):
        for remote_flag in (False, True):
            with self.subTest(remote_flag=remote_flag), tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)
                document=folder/'document.json'
                document.write_text('{"documentId":"doc", "fingerprint":"fp", "pages":[]}\n')
                original=document.read_bytes()
                hydrated=copy.deepcopy(json.loads(original))
                hydrated['localHydrationSnapshot']='derived index state'
                saved=folder/'generated/new-concept-v99/fixture/result.json'
                saved.parent.mkdir(parents=True)
                saved.write_text('{"body":"기존에 생성한 설명이에요.","runUsage":{"requests":2}}')
                saved_bytes=saved.read_bytes()
                request=folder/'request.json'
                request.write_text(json.dumps({'strategy':'new-concept-v99','scope':'page','page':8}))
                projection={'kind':'ai_generated','hierarchy':{'version':'study-hierarchy-7'},
                            'sections':[{'body':'기존에 생성한 설명이에요.'}]}
                argv=['pdf_ai.py','recover','--folder',str(folder),'--request',str(request)]
                if remote_flag:argv.append('--allow-remote')
                with (patch.object(sys,'argv',argv),
                      patch.object(ai,'load_tutor_document',return_value=hydrated),
                      patch.object(study,'recover',return_value=projection) as recover,
                      patch.object(ai,'Provider',side_effect=AssertionError('No provider')) as provider,
                      patch.object(ai,'api_key',side_effect=AssertionError('No credential read')),
                      patch('socket.socket.connect',side_effect=AssertionError('No network')),
                      patch('urllib.request.urlopen',side_effect=AssertionError('No network')),
                      contextlib.redirect_stdout(io.StringIO())):
                    ai.main()
                provider.assert_not_called()
                recover.assert_called_once_with(folder,hydrated,'page',8,'gpt-6-luna','new-concept-v99')
                self.assertEqual(document.read_bytes(),original)
                self.assertEqual(saved.read_bytes(),saved_bytes)
                self.assertEqual(json.loads(request.with_suffix('.result.json').read_text()),projection)


if __name__=='__main__':unittest.main()
