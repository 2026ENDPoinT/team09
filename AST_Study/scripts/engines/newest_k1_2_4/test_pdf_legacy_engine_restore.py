"""Offline original-engine identity and saved-format/recovery compatibility."""
import copy,hashlib,importlib.util,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pdf_new_concept_ver99_study as study
import pdf_saved_teaching_compat as compat
from pdf_pipeline import write_json

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/lecture-quality-supervision/20261028/backups/before-quality-v1-20261028T040822Z/files'

class LegacyEngineRestoreTests(unittest.TestCase):
 def test_generation_prompt_schema_payload_and_limits_match_initial_user_backup(self):
  spec=importlib.util.spec_from_file_location('restored_baseline',BASE/'scripts/pdf_new_concept_ver99_study.py')
  original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
  for key in ('STUDY_PROMPT','STUDY_FORMAT','EXPERIMENTAL_SOURCE_PROMPT','PLAN_PROMPT','PLAN_FORMAT','TEACHING_RULES',
   'TRANSPORT_BATCH_UNITS','TRANSPORT_BATCH_IMAGES','MAX_STUDY_WORKERS','MAX_STARTUP_WORKERS','STUDY_INPUT_API','STUDY_REASONING_EFFORT'):
   self.assertEqual(getattr(study,key),getattr(original,key),key)
  self.assertEqual(study.teaching_identity(),original.teaching_identity())
  self.assertNotIn('contentContract',study.STUDY_FORMAT['json_schema']['schema']['properties'])
  self.assertFalse(hasattr(compat,'RULES'));self.assertFalse(hasattr(compat,'response_format'))
  for name in ('pdf_new_concept_ver99_prompts.py','pdf_study_reading_policy.py','pdf_new_concept_v02_regions.py','pdf_new_concept_v02_math.py'):
   self.assertEqual((ROOT/'scripts'/name).read_bytes(),(BASE/'scripts'/name).read_bytes(),name)

 def test_saved_v3_v4_reading_retains_composed_parts_and_each_lookup_card(self):
  blocks=[{'id':'s1','page':1,'kind':'text','text':'두 조건에서 다른 결과를 설명해요.','bbox':[.1,.1,.9,.6],
   'hasVisual':False,'visualOnly':False}]
  doc={'documentId':'offline-legacy-compat','pages':[{'number':1,'label':'1'}]}
  for version in compat.SUPPORTED_VERSIONS:
   raw={'contentContract':version,'concepts':[{'title':title,'parentTitle':'','presentation':'concept',
    'sourceSetup':{'observedRelations':[],'boundaryChecks':[],'interpretation':''},'standardKnowledgeUsed':False,
    'segments':[{'kind':'explanation','text':body,'blockIds':['s1']}]}for title,body in [('조건','조건이 있을 때 적용해요.'),('결과','그 조건에 따라 결과가 달라져요.')]],
    'lectureUnits':[{'title':'조건과 결과','conceptTitles':['조건','결과'],'bridge':{'text':'','blockIds':[],'sourceQuote':''}}],
    'diagnostics':[],'tables':[],'sequences':[],'excludedBlocks':[],'uncertainBlocks':[]}
   with patch.object(socket.socket,'connect',side_effect=AssertionError('No network')):
    result=study.validate(raw,{'id':'job','title':'조건','blocks':blocks},doc)
   self.assertEqual(len(result['summary']['parts']),1)
   self.assertEqual(len(result['concepts']),2)
   consolidated=study.consolidate_entries({0:copy.deepcopy(result)})
   self.assertEqual(len(consolidated[0]['concepts']),2)
   self.assertEqual(result['contentContract'],version)

 def test_read_only_local_complete_pointer_selects_full_result_and_rejects_stale_latest(self):
  with tempfile.TemporaryDirectory()as temporary:
   folder=Path(temporary);doc={'documentId':'offline','fingerprint':'fp','pages':[]};model='gpt-6-luna'
   root=study.root_path(folder,doc,'new-concept-v99',model,'document',0);root.mkdir(parents=True)
   latest=study.latest_path(folder,'new-concept-v99','document',0)
   write_json(latest,{'processingComplete':False})
   recovered={'documentId':'offline','sourceFingerprint':'fp','strategy':'new-concept-v99','model':model,
    'scope':'document','page':0,'processingComplete':True,'localRecovery':{'newPaidCalls':0},'partialUnits':24,'totalUnits':24}
   name='a'*64;target=root.parent/name/'result.json';write_json(target,recovered)
   sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
   pointer=latest.with_name('local-complete-document-0.json')
   write_json(pointer,{'rootName':name,'originalLatestSha256':sha(latest),'resultSha256':sha(target)})
   before={p:p.read_bytes()for p in (target,latest,pointer)}
   self.assertEqual(study.saved_complete(folder,doc,'new-concept-v99',model,'document',0),recovered)
   self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
   write_json(latest,{'processingComplete':False,'changed':True})
   self.assertIsNone(study.saved_complete(folder,doc,'new-concept-v99',model,'document',0))

if __name__=='__main__':unittest.main()
