import copy,json,unittest
from pdf_json_boundary import JsonBoundary
from test_pdf_responses_transport import FORMAT

class JsonBoundaryTests(unittest.TestCase):
 def guard(self):return JsonBoundary(FORMAT['json_schema']['schema'])
 def test_valid_complete_root_is_not_itself_an_error(self):
  g=self.guard()
  for c in '{"ok":true}':self.assertIsNone(g.feed(c))
  self.assertTrue(g.finished);self.assertEqual(g.value,{'ok':True})
 def test_post_root_padding_or_extra_object_triggers_without_changing_prefix(self):
  for tail in ('\n'*257,'} \n<|assistant|>','{"ok":false}'):
   g=self.guard();self.assertIsNotNone(g.feed('{"ok":true}'+tail));self.assertEqual(g.value,{'ok':True})
 def test_long_learner_string_and_literal_braces_are_never_cut(self):
  schema={'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}
  value={'text':'quoted " brace } slash \\ '+(' \n'*1000)+'<|assistant|>'}
  raw=json.dumps(value);g=JsonBoundary(schema)
  for char in raw:self.assertIsNone(g.feed(char))
  self.assertEqual(g.value,value)
 def test_partial_missing_required_fields_wrong_type_duplicate_keys_not_accepted(self):
  for raw in ('{"ok":','{}','{"ok":"true"}','{"ok":true,"ok":false}'):
   g=self.guard();g.feed(raw);self.assertIsNone(g.value)
 def test_unclosed_json_padding_is_detected_but_never_returned_as_result(self):
  g=self.guard();self.assertEqual(g.feed('{"ok":'+(' '*257)),'padding_before_complete');self.assertIsNone(g.value)
 def test_json_whitespace_under_limit_is_preserved(self):
  g=self.guard();self.assertIsNone(g.feed('{\n  "ok":true\n}\n'));self.assertEqual(g.value,{'ok':True})

if __name__=='__main__':unittest.main()
