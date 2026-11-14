"""Add validated paid/page caches to the matching original PDF, never overwrite existing data."""
import hashlib
import json
from pathlib import Path
import shutil

root=Path('build/pdf-page-live-validation')
counts={'added':0,'alreadyPresent':0}
for prefix in ('b18d6db8cfbc','9a295022e96e'):
    src=root/prefix;dest=next(Path('.synesis/pdf').glob(prefix+'*/source.pdf')).parent
    assert hashlib.sha256((src/'source.pdf').read_bytes()).digest()==hashlib.sha256((dest/'source.pdf').read_bytes()).digest()
    for group in ('page-analysis','paid-responses'):
        for path in (src/'generated'/group).glob('*.json'):
            target=dest/'generated'/group/path.name
            if target.exists():
                assert target.read_bytes()==path.read_bytes(), 'Existing cache differs; refusing overwrite'
                counts['alreadyPresent']+=1;continue
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target);counts['added']+=1
(root/'cache-preservation.json').write_text(json.dumps(counts),encoding='utf-8')
print(json.dumps(counts))
