"""Native PDF typography supplement contracts; no OCR, API or source writes."""
import copy
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import (DictionaryObject, NameObject, DecodedStreamObject)

import pdf_native_heading_structure as native
from pdf_native_heading_structure import supplement


def make_pdf(folder, pages):
    """Small real PDFs with base fonts; no additional fixture package needed."""
    writer=PdfWriter()
    fonts=DictionaryObject({NameObject('/F1'):DictionaryObject({NameObject('/Type'):NameObject('/Font'),
        NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}),
        NameObject('/F2'):DictionaryObject({NameObject('/Type'):NameObject('/Font'),
        NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica-Bold')})})
    for lines in pages:
        page=writer.add_blank_page(width=600,height=800)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):fonts})
        commands=[]
        for text,size,x,y,bold in lines:
            escaped=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append(f'BT /F{2 if bold else 1} {size} Tf {x} {y} Td ({escaped}) Tj ET')
        stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    path=folder/'source.pdf'
    with path.open('wb')as out:writer.write(out)
    return path


def block(page=1, **extra):
    return {'id':f'p{page}','page':page,'kind':'page','fontSize':None,'bbox':[0,0,1,1],
            'zone':0,'zoneBounds':[0,0,1,1],'text':'','hasVisual':True,**extra}


BODY=[('The explanation has real source conditions and consequences.',12,54,650,False),
      ('A second paragraph describes the operation in ordinary language.',12,54,625,False)]


class NativeHeadingTests(unittest.TestCase):
    def setUp(self):
        native._clear_cache()

    def test_native_top_title_is_metadata_only_and_source_file_is_unchanged(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);path=make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            original=path.read_bytes();blocks=[block(text='General Principles\nThe explanation has real source conditions and consequences.')]
            before=copy.deepcopy(blocks)
            with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
                value=supplement(folder,blocks)
            self.assertEqual(blocks,before);self.assertEqual(path.read_bytes(),original)
            self.assertEqual({k:v for k,v in value[0].items()if k!='nativeHeading'},before[0])
            heading=value[0]['nativeHeading']
            self.assertEqual(heading['title'],'General Principles')
            self.assertAlmostEqual(heading['fontSize'],28)
            self.assertAlmostEqual(heading['bodyFontSize'],12)
            self.assertTrue(heading['bold']);self.assertLess(heading['bbox'][1],.25)

    def test_existing_fragment_typography_does_not_open_the_pdf(self):
        blocks=[block(kind='heading',fontSize=28,text='Existing heading')]
        with patch('pdfplumber.open',side_effect=AssertionError('No read needed')):
            self.assertEqual(supplement(Path('/not-needed'),blocks),blocks)

    def test_small_crop_does_not_claim_an_unrelated_page_title(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            blocks=[block(kind='visual',bbox=[0,.4,.8,.9])]
            self.assertEqual(supplement(folder,blocks),blocks)

    def test_source_text_mismatch_is_not_rebound_to_native_title(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            blocks=[block(text='An unrelated source extraction')]
            self.assertEqual(supplement(folder,blocks),blocks)

    def test_two_equivalent_top_titles_are_ambiguous(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('First Topic',28,54,740,True),
                ('Second Topic',28,54,700,True),*BODY]])
            blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_formula_is_not_a_structural_title(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('y = mx + b',28,54,730,True),*BODY]])
            blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_unlabelled_number_near_chart_does_not_become_a_chapter(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('3000 million tokens',28,54,730,True),*BODY]])
            blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_question_and_choices_are_not_source_chapter_titles(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('Q. Select the correct option?',28,54,750,True),
                ('1) First answer',22,54,710,True),('2) Second answer',22,54,670,True),*BODY]])
            blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_navigation_quiz_and_standalone_translation_are_not_chapters(self):
        for title in ['CONTENTS','QUIZ','(Translation): _','AB']:
            with self.subTest(title=title),tempfile.TemporaryDirectory()as temp:
                folder=Path(temp);make_pdf(folder,[[(title,28,54,730,True),*BODY]])
                blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_overlaid_mixed_font_annotation_is_not_a_clean_title(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('Header',28,54,730,True),
                ('note',14,150,730,False),*BODY]])
            blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)

    def test_same_font_bold_title_needs_repeated_nonconstant_style(self):
        pages=[[('First Topic',12,54,730,True),*BODY],
               [('Second Topic',12,54,730,True),*BODY]]
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,pages)
            value=supplement(folder,[block(1),block(2)])
            self.assertEqual([b['nativeHeading']['title']for b in value],['First Topic','Second Topic'])
        for check in [pages[:1],[pages[0],pages[0]]]:
            with self.subTest(pages=len(check)),tempfile.TemporaryDirectory()as temp:
                folder=Path(temp);make_pdf(folder,check);blocks=[block(i+1)for i in range(len(check))]
                self.assertEqual(supplement(folder,blocks),blocks)

    def test_scan_missing_pdf_and_parse_failures_preserve_original_blocks(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);blocks=[block()]
            self.assertEqual(supplement(folder,blocks),blocks)
            make_pdf(folder,[[]]);self.assertEqual(supplement(folder,blocks),blocks)
            (folder/'source.pdf').write_bytes(b'not a pdf')
            self.assertEqual(supplement(folder,blocks),blocks)

    def test_title_outside_whole_panel_bounds_cannot_be_inherited(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('Page Topic',28,54,730,True),*BODY]])
            blocks=[block(kind='visual',bbox=[0,.3,1,1])]
            self.assertEqual(supplement(folder,blocks),blocks)

    def test_unbalanced_native_fragments_are_not_titles_but_numbered_titles_remain(self):
        for text in [') " (disegno,','A broken (heading','A broken heading,']:
            with self.subTest(text=text),tempfile.TemporaryDirectory()as temp:
                folder=Path(temp);make_pdf(folder,[[(text,28,54,730,True),*BODY]])
                blocks=[block()];self.assertEqual(supplement(folder,blocks),blocks)
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('1) Valid topic (review)',28,54,730,True),*BODY]])
            self.assertEqual(supplement(folder,[block()])[0]['nativeHeading']['title'],'1) Valid topic (review)')

    def test_repeat_read_reuses_metadata_without_sharing_mutable_outputs(self):
        import pdfplumber
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            raw=[block()]
            with patch('pdfplumber.open',wraps=pdfplumber.open)as opener:
                first=supplement(folder,raw);first[0]['nativeHeading']['title']='Changed output'
                first[0]['nativeHeading']['bbox'][0]=.99
                second=supplement(folder,raw)
                self.assertEqual(opener.call_count,1)
            self.assertEqual(second[0]['nativeHeading']['title'],'General Principles')
            self.assertLess(second[0]['nativeHeading']['bbox'][0],.2)
            self.assertNotIn('nativeHeading',raw[0])

    def test_scanned_negative_result_is_cached_but_read_failures_are_not(self):
        import pdfplumber
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[]]);raw=[block()]
            with patch('pdfplumber.open',wraps=pdfplumber.open)as opener:
                self.assertEqual(supplement(folder,raw),raw)
                self.assertEqual(supplement(folder,raw),raw)
                self.assertEqual(opener.call_count,1)
            make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            with patch('pdfplumber.open',side_effect=OSError('Temporary local read failure')):
                self.assertEqual(supplement(folder,raw),raw)
            self.assertIn('nativeHeading',supplement(folder,raw)[0])

    def test_source_rewrite_invalidates_even_when_mtime_is_restored(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);path=make_pdf(folder,[[('First Topic',28,54,730,True),*BODY]])
            first=supplement(folder,[block()]);old=path.stat()
            make_pdf(folder,[[('Other Topic',28,54,730,True),*BODY]])
            os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
            self.assertEqual(path.stat().st_size,old.st_size)
            self.assertEqual(path.stat().st_mtime_ns,old.st_mtime_ns)
            second=supplement(folder,[block()])
            self.assertEqual(first[0]['nativeHeading']['title'],'First Topic')
            self.assertEqual(second[0]['nativeHeading']['title'],'Other Topic')

    def test_text_identity_geometry_and_page_changes_do_not_reuse_wrong_metadata(self):
        import pdfplumber
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('First Topic',28,54,730,True),*BODY],
                                             [('Other Topic',28,54,730,True),*BODY]])
            with patch('pdfplumber.open',wraps=pdfplumber.open)as opener:
                self.assertEqual(supplement(folder,[block()])[0]['nativeHeading']['title'],'First Topic')
                self.assertNotIn('nativeHeading',supplement(folder,[block(text='Unrelated text')])[0])
                self.assertEqual(supplement(folder,[block(id='different')])[0]['id'],'different')
                self.assertNotIn('nativeHeading',supplement(folder,[block(bbox=[0,.3,1,1])])[0])
                self.assertEqual(supplement(folder,[block(2)])[0]['nativeHeading']['title'],'Other Topic')
                self.assertEqual(opener.call_count,5)
                # Unrelated noneligible rows may move without corrupting the
                # eligible-order index used to attach cached metadata.
                extra=block(kind='text',fontSize=12,id='body')
                value=supplement(folder,[extra,block()])
                self.assertEqual(opener.call_count,5)
                self.assertNotIn('nativeHeading',value[0]);self.assertIn('nativeHeading',value[1])

    def test_lru_and_size_bounds_limit_process_memory(self):
        import pdfplumber
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            with patch.object(native,'_CACHE_MAX_ENTRIES',2),patch('pdfplumber.open',wraps=pdfplumber.open)as opener:
                for name in ['a','b','a','c','b']:
                    supplement(folder,[block(id=name)])
                self.assertEqual(opener.call_count,4)
                self.assertLessEqual(len(native._CACHE),2)
            native._clear_cache()
            with patch.object(native,'_CACHE_MAX_BYTES',10):
                supplement(folder,[block()]);self.assertFalse(native._CACHE)
            make_pdf(folder,[[('First Topic',28,54,730,True),*BODY],
                             [('Other Topic',28,54,730,True),*BODY]])
            with patch.object(native,'_CACHE_MAX_HEADINGS',1):
                supplement(folder,[block(1),block(2)]);self.assertFalse(native._CACHE)

    def test_threaded_hits_are_independent_and_pdf_parsing_holds_no_cache_lock(self):
        original=native._lines
        def read_without_cache_lock(page):
            acquired=native._CACHE_LOCK.acquire(blocking=False)
            self.assertTrue(acquired,'PDF parsing held the global cache lock')
            if acquired:native._CACHE_LOCK.release()
            return original(page)
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            with patch.object(native,'_lines',side_effect=read_without_cache_lock):
                supplement(folder,[block()])
            with patch('pdfplumber.open',side_effect=AssertionError('Warm hit must not reparse')):
                with ThreadPoolExecutor(max_workers=8)as pool:
                    results=list(pool.map(lambda _:supplement(folder,[block()]),range(24)))
            results[0][0]['nativeHeading']['title']='Only this result'
            self.assertTrue(all(v[0]['nativeHeading']['title']=='General Principles'for v in results[1:]))

    def test_pdf_changed_during_read_is_not_applied_or_cached(self):
        original=native._lines
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('First Topic',28,54,730,True),*BODY]])
            def rewrite_after_read(page):
                lines=original(page)
                make_pdf(folder,[[('Other Topic',28,54,730,True),*BODY]])
                return lines
            raw=[block()]
            with patch.object(native,'_lines',side_effect=rewrite_after_read):
                self.assertEqual(supplement(folder,raw),raw)
            self.assertFalse(native._CACHE)
            self.assertEqual(supplement(folder,raw)[0]['nativeHeading']['title'],'Other Topic')

    def test_completion_status_distinguishes_success_negative_and_transient_failure(self):
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);status={'complete':True,'callerValue':'preserved'}
            raw=[block()]
            self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertFalse(status['complete']);self.assertEqual(status['callerValue'],'preserved')
            # No eligible source needs no PDF and is a complete projection.
            self.assertEqual(supplement(folder,[block(fontSize=24)],status=status),[block(fontSize=24)])
            self.assertTrue(status['complete'])
            make_pdf(folder,[[('General Principles',28,54,730,True),*BODY]])
            value=supplement(folder,raw,status=status)
            self.assertTrue(status['complete']);self.assertIn('nativeHeading',value[0])
            status['complete']=False
            with patch('pdfplumber.open',side_effect=AssertionError('Warm hit must not reparse')):
                self.assertEqual(supplement(folder,raw,status=status),value)
            self.assertTrue(status['complete'])
            make_pdf(folder,[[]])
            self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertTrue(status['complete'])
            status['complete']=False
            with patch('pdfplumber.open',side_effect=AssertionError('Negative hit must not reparse')):
                self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertTrue(status['complete'])
            (folder/'source.pdf').write_bytes(b'not a pdf')
            self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertFalse(status['complete'])

    def test_completion_status_is_false_for_a_changed_pdf_or_read_error(self):
        original=native._lines
        with tempfile.TemporaryDirectory()as temp:
            folder=Path(temp);make_pdf(folder,[[('First Topic',28,54,730,True),*BODY]])
            raw=[block()];status={'complete':True}
            with patch('pdfplumber.open',side_effect=OSError('Temporary local read failure')):
                self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertFalse(status['complete']);self.assertFalse(native._CACHE)
            def rewrite_after_read(page):
                lines=original(page)
                make_pdf(folder,[[('Other Topic',28,54,730,True),*BODY]])
                return lines
            status['complete']=True
            with patch.object(native,'_lines',side_effect=rewrite_after_read):
                self.assertEqual(supplement(folder,raw,status=status),raw)
            self.assertFalse(status['complete']);self.assertFalse(native._CACHE)
            self.assertIn('nativeHeading',supplement(folder,raw,status=status)[0])
            self.assertTrue(status['complete'])


if __name__=='__main__':unittest.main()
