"""Real PDF/MarkItDown/no-OCR checks against generated fixtures; no network or personal files."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import time
import sys
from unittest.mock import patch
from pdf_pipeline import prepare, retrieve, write_json

ROOT = Path('build/pdf-tests')


def analyze(name, suffix=''):
    folder = ROOT / 'cache' / (name + suffix)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / (name + '.pdf'), folder / 'source.pdf')
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        result = prepare(folder)
    return result, folder, round(time.perf_counter()-started, 3)


def main():
    def forbid_env_read(event,args):
        if event == 'open' and isinstance(args[0],(str,bytes)) and Path(args[0]).name == '.env':
            raise AssertionError('PDF dependency attempted to read .env')
    sys.addaudithook(forbid_env_read)
    results = {}
    import base64
    from PIL import Image
    from pdf_page_analysis import render_page
    rotation_folder=ROOT/'cache'/'rotation-frame';rotation_folder.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'crop-rotation.pdf',rotation_folder/'source.pdf')
    picture=render_page(rotation_folder,1)
    with Image.open(io.BytesIO(base64.b64decode(picture['data'].split(',',1)[1]))) as py, Image.open(ROOT/'crop-rotation-java.png') as java:
        assert abs(py.width/py.height-java.width/java.height)<.0001
        for x,y in ((.25,.25),(.75,.25),(.25,.75),(.75,.75)):
            assert py.convert('RGB').getpixel((int(py.width*x),int(py.height*y)))==java.convert('RGB').getpixel((int(java.width*x),int(java.height*y)))
    results['renderCoordinateFrame']='PASS: PDFium and PDFBox agree with rotation and offset CropBox'
    text, folder, elapsed = analyze('text')
    assert len(text['pages']) == 3 and not text['incompletePages']
    assert text['pageAnalysisStates'] == [
        {'page': n, 'state': 'pending', 'analyzed': 0, 'complete': 0} for n in (1,2,3)]
    assert all(not p['ocrNeeded'] for p in text['pages'])
    assert text['visualReviewPages'] == [1,2,3] and all(p['contentMode'] == 'text' for p in text['pages'])
    assert retrieve(text, '회전운동')[0]['page'] == 2
    assert {c['page'] for c in retrieve(text, '에너지 보존')} >= {1, 3}
    for c in text['chunks']:
        assert c['text'] == text['pages'][c['page']-1]['markdown'][c['start']:c['end']]
    results['text'] = {'seconds': elapsed, 'pages': 3, 'ocrPages': 0, 'searchPage': 2}
    before = (folder/'pages/00001.json').stat().st_mtime_ns
    with patch('markitdown.MarkItDown', side_effect=AssertionError('Cache should skip converter')):
        cached, _, cache_elapsed = analyze('text')
    assert cached == text and before == (folder/'pages/00001.json').stat().st_mtime_ns
    results['cache'] = {'seconds': cache_elapsed, 'pageFileUnchanged': True}
    scan, _, elapsed = analyze('scan')
    assert not scan['incompletePages'] and not scan['pages'][0]['nativeText'].strip()
    assert scan['pages'][0]['ocrBlocks'] == [] and scan['ocrDisabled']
    assert scan['visualReviewPages'] == [1] and not scan['chunks']
    results['scan'] = {'seconds': elapsed, 'ocrDisabled': True}
    mixed, _, elapsed = analyze('table-math-image')
    assert not mixed['incompletePages'] and not mixed['pages'][0]['ocrBlocks']
    assert mixed['pages'][0]['contentMode'] == 'mixed' and mixed['visualReviewPages'] == [1]
    assert 'E = m c^2' in mixed['pages'][0]['nativeText']
    assert '42' in mixed['pages'][0]['markdown']
    results['tableMathImage'] = {'seconds': elapsed, 'markdown': mixed['pages'][0]['markdown'], 'warnings': mixed['pages'][0]['warnings']}
    long, _, elapsed = analyze('long-120')
    assert len(long['pages']) == 120 and not long['incompletePages']
    assert retrieve(long, '장문검색표식')[0]['page'] == 117
    assert len(json.dumps(retrieve(long,'엔트로피'),ensure_ascii=False).encode()) <= 18000
    results['long120'] = {'seconds': elapsed, 'pages': 120, 'lateSearchPage': 117, 'chunks': len(long['chunks'])}
    failed_folder = ROOT/'cache'/'ocr-failure'
    failed_folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/'scan.pdf',failed_folder/'source.pdf')
    with contextlib.redirect_stdout(io.StringIO()):
        recovered = prepare(failed_folder, retry=True)
    assert recovered['incompletePages'] == [] and recovered['ocrDisabled']
    (failed_folder/'cancel').write_text('cancel')
    try:
        with contextlib.redirect_stdout(io.StringIO()): prepare(failed_folder, retry=True)
        raise AssertionError('Cancellation ignored')
    except InterruptedError:
        pass
    finally:
        (failed_folder/'cancel').unlink()
    results['failureRetryCancel'] = 'PASS'
    write_json(ROOT/'integration-results.json',results)
    print(json.dumps({'status':'PASS', 'checks':list(results), 'timings':{k:v.get('seconds') for k,v in results.items() if isinstance(v,dict)}},ensure_ascii=False))


if __name__ == '__main__':
    main()
