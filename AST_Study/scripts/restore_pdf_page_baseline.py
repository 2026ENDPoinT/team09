"""Restore only PDF migration integration files; PDF data and caches are never changed."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile

FILES = ('scripts/pdf_ai.py', 'src/main/java/dev/synesis/poc/pdf/PdfWorkspace.java',
         'src/test/java/dev/synesis/poc/pdf/PdfSmokeTest.java', 'build.gradle.kts')


def restore(root, snapshot, apply=False):
    manifest = json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(snapshot/'source.zip') as archive:
        original = {name: archive.read(name) for name in FILES}
    for name, data in original.items():
        if hashlib.sha256(data).hexdigest() != manifest[name]:
            raise ValueError('Baseline checksum mismatch: '+name)
    changed = [name for name, data in original.items() if (root/name).read_bytes() != data]
    report = {'baseline': str(snapshot), 'restoreFiles': changed, 'applied': False,
              'dataPolicy': '.synesis/, PDF files, recordings and credentials are untouched.'}
    if apply and changed:
        recovery = root/'backups'/('before-page-rollback-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        recovery.mkdir(parents=True)
        with zipfile.ZipFile(recovery/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for name in changed:
                archive.write(root/name,name)
        for name in changed:
            target=root/name
            temporary=target.with_suffix(target.suffix+'.restore-tmp')
            temporary.write_bytes(original[name]);temporary.replace(target)
        report.update(applied=True,undoArchive=str(recovery/'source.zip'))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Restore after preserving current integration files.')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    print(json.dumps(restore(root,args.snapshot.resolve(),args.apply),ensure_ascii=False,indent=2))
