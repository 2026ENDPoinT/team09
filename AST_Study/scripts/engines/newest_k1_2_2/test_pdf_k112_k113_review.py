import copy
import importlib
import tempfile
import threading
import unittest
import re
from pathlib import Path
from types import SimpleNamespace

from pdf_ai import Provider, ContextBudgetExceeded, study_math_issues
from pdf_new_concept_ver99_checks import prepare_learner_segment, math_semantics
from pdf_study_progress_attempts import FourAttemptRace
from test_pdf_newest_k1_1_1 import block, response


class ReviewRegressionTest(unittest.TestCase):
    def test_empty_images_follow_text_path_and_invalid_image_remains_invalid(self):
        # Passes image validation and reaches the input budget calculation.
        p=SimpleNamespace(context={},folder=Path(tempfile.gettempdir()),model='gpt-6-luna',input_bound_limit=0)
        for image in (None,[]):
            with self.assertRaises(ContextBudgetExceeded) as got:
                Provider._complete_once(p,{'task':'region_teaching'},image=image,system_prompt='test')
            self.assertNotIn('이미지',str(got.exception))
        with self.assertRaisesRegex(ValueError,'2800px'):
            Provider._complete_once(p,{'task':'region_teaching'},image=[{}],system_prompt='test')

    def test_deterministic_local_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            p=SimpleNamespace(context={},folder=Path(tmp),_lock=threading.RLock())
            def fail(payload,**kw):
                calls.append(1);raise ValueError('invalid local input')
            p._complete_once=fail
            with self.assertRaisesRegex(ValueError,'invalid local input'):
                FourAttemptRace(p,{},{}).run()
            self.assertEqual(len(calls),1)

    def test_modulo_and_complete_envelopes_without_erasing_corruption(self):
        text='나머지는 6%2=0, 3%2=1, 1%2=1이에요.'
        fixed,_=prepare_learner_segment(text)
        self.assertIn('`6%2=0`',fixed)
        self.assertFalse(math_semantics(fixed))
        for text in [r'$\(x=2\)$',r'\(\(x=2\)\)']:
            fixed,_=prepare_learner_segment(text)
            self.assertFalse(study_math_issues({'body':fixed}),fixed)
        corrupt,_=prepare_learner_segment('힘은 \x1c이고 변위는 \x1c예요.')
        self.assertTrue(study_math_issues({'body':corrupt}))
        code=r'`$\(x=2\)$`'
        self.assertEqual(prepare_learner_segment(code)[0],code)
        self.assertTrue(math_semantics(r'\(2+2=5\)'))
        text=r'에너지 $\Delta E_{\mathrm{mech}}=0$, $U=mgy$예요.'
        prepared,_=prepare_learner_segment(text)
        self.assertFalse(study_math_issues({'body':prepared}),prepared)
        self.assertNotIn('$',prepared)

    def test_intact_serialized_math_and_real_teaching_negations_survive(self):
        for text in ['위치는 \tx_i\t에서 \tx_f\t까지예요.',
                     '일은 \t'+r'\frac12kx_{\max}^2'+'\t예요.',
                     '벡터 $\n'+r'\mathbf{u}=\begin{bmatrix}u_1\\u_2\end{bmatrix}$'+'예요.']:
            prepared,_=prepare_learner_segment(text)
            self.assertFalse(study_math_issues({'body':prepared}),prepared)
            self.assertNotIn('\t',prepared)
            self.assertNotIn('$',prepared)
        text='같은 방향으로 같은 길이만큼 움직이는 화살표라면, 그림에서 어디에 놓였는지는 동등성을 바꾸지 않아요.'
        self.assertEqual(prepare_learner_segment(text),(text,[]))
        for code in ['```c\n\tint x = 2;\n\tint y = x;\n```','열1\t열2\t열3']:
            self.assertEqual(prepare_learner_segment(code)[0],code)
        self.assertEqual(prepare_learner_segment('이 그림에는 수치가 없어 값을 읽을 수 없어요.')[0],'')
        text='띠 \x00(위쪽 값-아래쪽 값)'+r'\times\Delta x'+'\x00예요.'
        self.assertFalse(study_math_issues({'body':prepare_learner_segment(text)[0]}))
        text='값은 \x00x이고, 다음 그림은 \x00y예요.'
        self.assertTrue(study_math_issues({'body':prepare_learner_segment(text)[0]}))

    def test_both_schemas_exclude_control_characters_but_preserve_newlines_and_code(self):
        for version in ('2','3'):
            engine=importlib.import_module('pdf_newest_k1_1_'+version)
            pattern=engine.STUDY_FORMAT['json_schema']['schema']['properties']['concepts']['items']['properties']['segments']['items']['properties']['text']['pattern']
            self.assertIsNotNone(re.fullmatch(pattern,'한글\n```c\n\tint x = 0;\n```'))
            for marker in ('\x00','\x1a','\x1b','\x1c','\x7f'):
                self.assertIsNone(re.fullmatch(pattern,'기호'+marker+'x'))

    def test_both_engines_keep_supported_coverage_but_not_real_uncertainty(self):
        for version in ('2','3'):
            engine=importlib.import_module('pdf_newest_k1_1_'+version)
            b=block(0);b.update(id='a',hasVisual=True,kind='visual',bbox=[.1,.1,.8,.7],visualKinds=['vector'])
            job={'id':'j','title':'제목','blocks':[b]};doc={'documentId':'test','pages':[{'label':'1'}]*10}
            raw=response('a');raw['excludedBlocks']=[{'blockId':'a','reason':'설명에 통합했어요.','referenceContext':None}]
            value=engine.validate(copy.deepcopy(raw),job,doc)
            self.assertEqual(value['coverage'][0]['state'],'summarized')
            raw['concepts'][0]['segments'].append({'kind':'uncertain','text':'그림의 일부 수치는 읽지 못했어요.','blockIds':['a']})
            value=engine.validate(raw,job,doc)
            self.assertEqual(value['coverage'][0]['state'],'needs_review')

    def test_both_guards_do_not_infer_rival_ownership_from_missing_visual_text(self):
        quotes=['A uniquely identifiable full sentence.','Another distinct source phrase here.']
        raw=response('a');raw['concepts'][0]['sourceSetup']['sourceQuotes']=quotes
        peer={'job':{'id':'other','blocks':[{'text':' '.join(quotes)}]}}
        for version in ('2','3'):
            guard=importlib.import_module('pdf_newest_k1_1_'+version+'_guard')
            own={'job':{'blocks':[{'text':'A title','hasVisual':True}]}}
            guard.ensure_owned(raw,own,[peer])
            own['job']['blocks'][0]['hasVisual']=False
            with self.assertRaises(guard.SourceOwnershipError):guard.ensure_owned(raw,own,[peer])

    def test_packing_preserves_order_and_limits(self):
        from pdf_study_review import pack_crop_runs
        runs=[[{'id':str(i),'kind':'heading' if i%3==0 else 'text'}]for i in range(9)]
        groups=pack_crop_runs(runs,lambda xs:[[x]for x in xs],len,4,100)
        self.assertEqual([x['id']for g in groups for x in g],[str(i)for i in range(9)])
        self.assertTrue(all(len(g)<=4 for g in groups));self.assertLess(len(groups),9)


if __name__=='__main__':unittest.main()
