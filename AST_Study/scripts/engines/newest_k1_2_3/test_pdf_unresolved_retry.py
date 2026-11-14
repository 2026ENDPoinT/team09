"""Explicit missing-receipt retry keeps old costs and never retries within a run."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from pdf_ai import Provider, AiResponseError, MissingPaidResponseError, BudgetExceeded


class UnresolvedRetryTests(unittest.TestCase):
    def test_receipt_absence_is_distinct_from_auth_network_or_invalid_content(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'usage').mkdir()
            entry={'requestId':'a'*32,'state':'reserved','kind':'region_study','inputApi':'chat',
                   'sentAtMs':1,'responseCacheKey':'b'*64,'chatCompletionId':'chatcmpl_fixture',
                   'recoveryRequestTag':'a'*32,'reservedUsd':.02}
            path=folder/'usage/old.json'
            original={'operationId':'old','model':'gpt-6-luna','requests':[entry]}
            path.write_text(json.dumps(original))
            for status in (401,429,500,404):
                provider=Provider(folder,True,.1,transport=lambda _:None)
                def opener(req,timeout):raise urllib.error.HTTPError(req.full_url,status,'fixture',{},None)
                provider.recover_pending_study(open_url=opener)
                self.assertEqual(provider.unavailable_study_request_ids,{'a'*32} if status==404 else set())
                saved=json.loads(path.read_text())['requests'][0]
                self.assertEqual(saved['state'],'reserved');self.assertEqual(saved['reservedUsd'],.02)
            entry.pop('chatCompletionId');path.write_text(json.dumps(original))
            provider=Provider(folder,True,.1,transport=lambda _:None)
            provider.recover_pending_study(open_url=lambda req,timeout:io.StringIO('{"data":[],"has_more":false}'))
            self.assertEqual(provider.unavailable_study_request_ids,{'a'*32})
            provider=Provider(folder,True,.1,transport=lambda _:None)
            provider.recover_pending_study(open_url=lambda req,timeout:io.StringIO('{"data":[{}],"has_more":false}'))
            self.assertEqual(provider.unavailable_study_request_ids,set())

    def test_explicit_retry_is_bounded_and_old_ledger_remains_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);payload={'task':'retry fixture'};calls=[]
            def fail(body):calls.append(1);raise OSError('fixture interrupted')
            first=Provider(folder,True,.1,transport=fail)
            first.context={'kind':'region_study'}
            with self.assertRaises(AiResponseError):first.complete(payload)
            first.ledger['requests'][0]['state']='reserved'
            first.ledger_path.write_text(json.dumps(first.ledger))
            before=first.ledger_path.read_bytes();ident=first.ledger['requests'][0]['requestId']
            retry=Provider(folder,True,.1,transport=fail,retry_missing_responses=True)
            retry.context={'kind':'region_study'}
            retry.retry_unresolved_responses=True
            with self.assertRaises(MissingPaidResponseError):retry.complete(payload)
            retry.unavailable_study_request_ids.add(ident)
            retry.max_usd=.0000001
            with self.assertRaises(BudgetExceeded):retry.complete(payload)
            retry.max_usd=.1
            with self.assertRaises(AiResponseError):retry.complete(payload)
            with self.assertRaises(MissingPaidResponseError):retry.complete(payload)
            self.assertEqual(len(calls),2)
            self.assertEqual(before,first.ledger_path.read_bytes())
            self.assertEqual(retry.ledger['requests'][0]['unresolvedOriginalRequestIds'],[ident])
            # A new desktop run plus another 404 must not grant a third paid try.
            again=Provider(folder,True,.1,transport=fail,retry_missing_responses=True)
            again.context={'kind':'region_study'};again.retry_unresolved_responses=True
            again.unavailable_study_request_ids.update(
                [ident,retry.ledger['requests'][0]['requestId']])
            with self.assertRaises(MissingPaidResponseError):again.complete(payload)
            self.assertEqual(len(calls),2)

if __name__=='__main__':unittest.main()
