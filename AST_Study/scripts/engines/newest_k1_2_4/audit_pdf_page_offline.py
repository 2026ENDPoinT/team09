"""Read local fixtures, render in temp copies, and mock all model responses.
Report metadata only. Never imports/constructs the real Provider or reads secrets.
"""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import time
from unittest.mock import patch
from PIL import Image
import pdf_page_analysis as vision
from test_pdf_page_analysis import response


def snapshot(folder):
    files=[folder/'document.json', *folder.glob('generated/**/*.json')]
    return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    reports=[]
    for path in Path('.synesis/pdf').glob('*/document.json'):
        doc=json.loads(path.read_text(encoding='utf-8'))
        count=len(doc['pages'])
        if count!=32 and not (count==9 and path.parent.name.startswith('9a295')):continue
        original=snapshot(path.parent);started=time.perf_counter()
        class OfflineProvider:
            model='gpt-6-luna'
            def __init__(self):self.calls=0;self.areas=[]
            def complete(self,payload,**kwargs):
                self.calls+=1
                image=kwargs['image']
                with Image.open(io.BytesIO(base64.b64decode(image['data'].split(',',1)[1]))) as picture:
                    assert picture.size==(image['width'],image['height'])
                    assert max(picture.size)<=vision.MAX_SIDE
                    self.areas.append(picture.width*picture.height)
                value=response(payload)
                # Independent decorative object and overlapping educational diagram share a box.
                value['inventory'].append({'key':'ornament','kind':'decoration','label':'mock ornament','anchorIds':[]})
                value['elements'].append(dict(value['elements'][2],key='ornament',kind='decoration',title='mock ornament'))
                return value
        provider=OfflineProvider()
        with tempfile.TemporaryDirectory(prefix='synesis-page-audit-') as temp, \
             patch.object(socket,'create_connection',side_effect=AssertionError('Network forbidden')), \
             contextlib.redirect_stdout(io.StringIO()):
            folder=Path(temp);shutil.copyfile(path.parent/'source.pdf',folder/'source.pdf')
            vision.analyze_pages(folder,doc,provider)
            first=provider.calls
            vision.analyze_pages(folder,doc,provider)
            assert provider.calls==first==count
            assert all(len(p['pageAnalysis']['elements'])==5 for p in doc['pages'])
            assert all(any(r.get('kind')=='diagram' and r.get('origin')==vision.VERSION for r in p['slideLensRegions']) for p in doc['pages'])
            assert not any(r.get('kind')=='decoration' and r.get('origin')==vision.VERSION for p in doc['pages'] for r in p['slideLensRegions'])
        assert snapshot(path.parent)==original
        reports.append({'pages':count,'legacyImageRegions':sum(len(p.get('imageRegions',[])) for p in doc['pages']),
            'firstPageImageRequestsMocked':first,'decorationOnlyRequests':0,'resumeRequests':provider.calls-first,
            'fullPageImagesRendered':len(provider.areas),'overlapPreservedInMockCatalog':True,
            'existingDataUnchanged':True,'remoteRequests':0,'elapsedSeconds':round(time.perf_counter()-started,2),
            'limit':'Mock verifies routing and preservation, not Luna interpretation or semantic bounding-box accuracy.'})
    Path('build/pdf-page-offline-audit.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports))


if __name__=='__main__':main()
