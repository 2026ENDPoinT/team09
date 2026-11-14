import copy,json,unittest
from pdf_source_reference_guard import bounded_schema
from pdf_json_boundary import JsonBoundary
from pdf_study_batch_transport import _validate,BatchTransportError

class SourceReferenceTests(unittest.TestCase):
 def schema(self):
  return {'type':'object','properties':{'text':{'type':'string'},'blockIds':{'type':'array','items':{'$ref':'#/$defs/id'}}},'required':['text','blockIds'],'additionalProperties':False,'$defs':{'id':{'type':'string','enum':['a','b']}}}
 def test_finite_sources_bound_references_without_bounding_learner_text(self):
  original=self.schema();before=copy.deepcopy(original);wire=bounded_schema(original)
  self.assertEqual(original,before);self.assertEqual(wire['properties']['blockIds']['maxItems'],2)
  self.assertEqual(wire['properties']['text'],{'type':'string'})
  _validate({'text':'explanation '*5000,'blockIds':['a','b']},wire,wire)
  with self.assertRaises(BatchTransportError):_validate({'text':'x','blockIds':['a','b','a']},wire,wire)
 def test_shared_table_array_is_detached_from_reference_bounds(self):
  shared={'type':'array','items':{'$ref':'#/$defs/id'}}
  original={'type':'object','properties':{'blockIds':shared,'rows':shared},'$defs':{'id':{'type':'string','enum':['a']}}}
  wire=bounded_schema(original)
  self.assertEqual(wire['properties']['blockIds']['maxItems'],1);self.assertNotIn('maxItems',wire['properties']['rows'])
 def test_nested_namespaced_units_keep_their_own_source_cardinality(self):
  unit=lambda name:{'type':'object','properties':{'blockIds':{'type':'array','items':{'$ref':'#/$defs/'+name}}}}
  schema={'type':'object','properties':{'u0':unit('left'),'u1':unit('right')},'$defs':{'left':{'enum':['a','b','c']},'right':{'enum':['x']}}}
  wire=bounded_schema(schema)
  self.assertEqual(wire['properties']['u0']['properties']['blockIds']['maxItems'],3)
  self.assertEqual(wire['properties']['u1']['properties']['blockIds']['maxItems'],1)
 def test_reference_loop_is_detected_before_the_full_json_or_token_limit(self):
  guard=JsonBoundary(self.schema());text='{"text":"정상 설명","blockIds":["a","a","a"'
  self.assertEqual(guard.feed(text),'repeated_source_reference');self.assertIsNone(guard.value)
 def test_alternating_reference_loop_is_also_detected_inside_its_array(self):
  guard=JsonBoundary(self.schema())
  self.assertEqual(guard.feed('{"text":"normal","blockIds":["a","b","a","b","a"'),'repeated_source_reference')
 def test_identical_source_in_different_segments_does_not_trigger(self):
  segment={'type':'object','properties':{'blockIds':{'type':'array','items':{'type':'string'}}}}
  schema={'type':'object','properties':{'segments':{'type':'array','items':segment}}}
  value={'segments':[{'blockIds':['a']}for _ in range(100)]};guard=JsonBoundary(schema)
  self.assertIsNone(guard.feed(json.dumps(value)));self.assertEqual(guard.value,value)
 def test_source_id_words_inside_long_math_or_explanation_are_never_cut(self):
  value={'text':'"blockIds":["a","a","a"] '+(' \\ \n'*1000),'blockIds':['a','b']};guard=JsonBoundary(self.schema())
  for char in json.dumps(value):self.assertIsNone(guard.feed(char))
  self.assertEqual(guard.value,value)

if __name__=='__main__':unittest.main()
