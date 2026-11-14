"""Offline Windows preflight. Never prints credentials or sends a provider request."""
import argparse
import importlib
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile


def verify_package(root):
    manifest=root/'PACKAGE-CONTENTS.json'
    if not manifest.is_file():return
    for entry in json.loads(manifest.read_text(encoding='utf-8'))['files']:
        # Local API configuration is editable and is deliberately not an integrity-locked resource.
        if entry['path']=='config/credentials.env':continue
        path=root/entry['path']
        if not path.is_file() or path.stat().st_size!=entry['bytes']:
            raise RuntimeError('Incomplete package extraction.')
        if 'sha256' in entry:
            with path.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
            if actual!=entry['sha256']:raise RuntimeError('Package file integrity check failed.')
    print('Package files verified.',flush=True)


def sample_pdf(path):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    content = b'BT /F1 12 Tf 20 120 Td (SYNESIS offline check) Tj ET'
    objects.append(b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream')
    data = bytearray(b'%PDF-1.4\n');offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data));data.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    xref = len(data);data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:data.extend(f'{offset:010} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode());path.write_bytes(data)


def check_storage_paths(data):
    """Exercise real generation-depth writes before any paid request is possible."""
    from synesis_paths import io_path
    from pdf_pipeline import read_json_cache, write_json
    from pdf_semantic import read_json
    from PIL import Image
    runtime=io_path(data)/'.runtime';runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='path-check-',dir=runtime) as temporary:
        cache=io_path(temporary)/'library'/('a'*64)/'generated'/'new-concept-v99'/('b'*64)
        while len(str(cache))<320:cache=cache/'nested-output'
        target=cache/'group-plan.json'
        write_json(target,{'revision':1,'body':'긴 경로 저장 확인'})
        write_json(target,{'revision':2,'body':'긴 경로 저장 확인'})
        assert read_json_cache(target)['revision']==2
        assert read_json(target)['revision']==2
        image=cache/'crops'/('c'*24+'.png');image.parent.mkdir(parents=True,exist_ok=True)
        with Image.new('RGB',(8,8),'white') as pixels:pixels.save(image)
        with Image.open(image) as pixels:assert pixels.size==(8,8)
        assert not list(cache.glob('.s-*.tmp'))
        result={'status':'PASS','pathCharacters':len(str(target)),'temporaryName':'short-exclusive-sibling'}
    print('Generation-depth storage paths verified.',flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True);args=parser.parse_args()
    if sys.platform!='win32' or struct.calcsize('P')!=8:
        raise RuntimeError('This package needs 64-bit Windows.')
    verify_package(Path(__file__).resolve().parent.parent)
    # Keep DLL directory handles alive for optional native PDF dependencies.
    dll_dirs=[]
    for folder in (Path(sys.executable).parent,Path(__file__).resolve().parent.parent/'runtime/java/bin'):
        if hasattr(os,'add_dll_directory'):dll_dirs.append(os.add_dll_directory(str(folder)))
    for name in ('ssl','sqlite3','pypdf','pypdfium2','pdfplumber','PIL.Image','numpy','onnxruntime','markitdown','pdf_pipeline','pdf_ai'):
        print('Checking module: '+name,flush=True)
        importlib.import_module(name)
    storage=check_storage_paths(args.data)
    from synesis_paths import credentials_file
    from pdf_ai import api_key
    if not credentials_file().is_file() or not api_key():
        raise RuntimeError('The private API configuration is missing.')
    folder=args.data/'.runtime';folder.mkdir(parents=True,exist_ok=True)
    pdf=folder/'offline-check.pdf';sample_pdf(pdf)
    import pypdfium2
    with pypdfium2.PdfDocument(pdf) as doc:
        page=doc[0]
        image=page.render().to_pil()
        assert image.width==200 and image.height==200
        image.close();page.close()
    import pdfplumber
    with pdfplumber.open(pdf) as doc:assert 'SYNESIS offline check' in doc.pages[0].extract_text()
    from markitdown import MarkItDown
    assert 'SYNESIS offline check' in MarkItDown().convert(str(pdf)).text_content
    # Windows byte locks, the same primitive used by the Java/Python wallet.
    from pdf_api_slots import api_slot
    with api_slot(directory=folder/'preflight-api-slots'):pass
    from windows_parallel_check import check_parallel_slots
    parallel=check_parallel_slots(folder)
    result={'status':'PASS','python':sys.version.split()[0],'architecture':'x64',
            'checks':['dependencies','private-config-present','pdf-render','pdf-text','markitdown','windows-file-lock','generation-depth-write-read-replace','generation-depth-crop'],
            'storagePaths':storage,'parallelSlots':parallel,
            'remoteRequests':0}
    (folder/'preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Python PDF runtime checks passed. No API request made.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Dependency failures may include local paths; do not log exception messages or key material.
        print('PDF runtime check failed: '+type(error).__name__,file=sys.stderr)
        sys.exit(1)
