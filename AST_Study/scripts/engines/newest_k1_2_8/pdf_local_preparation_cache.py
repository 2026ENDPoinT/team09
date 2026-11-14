"""Disposable, local-only encoding/history caches. No teaching or billing policy."""
import hashlib
import io
import json
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    allow_nan=False).encode()).hexdigest()


def crop_png(crop, directory):
    # Hash actual pixels, not just coordinates: changed PDF/page pixels cannot
    # reuse an old crop. Encoder versions preserve the existing request bytes.
    from PIL import __version__ as pillow_version
    import zlib
    key=_digest([pillow_version,zlib.ZLIB_RUNTIME_VERSION,crop.mode,crop.size,
                 hashlib.sha256(crop.tobytes()).hexdigest()])
    directory=Path(directory);path=directory/(key+'.png');receipt=directory/(key+'.json')
    try:
        raw=path.read_bytes();saved=json.loads(receipt.read_text())
        if saved.get('sha256')==hashlib.sha256(raw).hexdigest():return raw
    except (OSError,ValueError,TypeError,AttributeError):pass
    buf=io.BytesIO();crop.save(buf,format='PNG');raw=buf.getvalue()
    try:
        from pdf_pipeline import write_json
        directory.mkdir(parents=True,exist_ok=True)
        # Readers verify the receipt, so interrupted/concurrent writes are misses.
        from pdf_k123_shared_images import write_shared
        write_shared(path,raw);write_json(receipt,{'sha256':hashlib.sha256(raw).hexdigest()})
    except OSError:pass
    return raw


def _revision(paths):
    result=[]
    for path in paths:
        try:
            stat=path.stat()
            result.append([str(path),stat.st_dev,stat.st_ino,stat.st_size,
                           stat.st_mtime_ns,stat.st_ctime_ns])
        except FileNotFoundError:result.append([str(path),None])
    return _digest(result)


def history_sample(folder,model,prompt_version,paths,calculate):
    path=Path(folder)/'generated/local-cost-history'/(_digest([model,prompt_version])+'.json')
    revision=None
    try:
        revision=_revision(paths)
        saved=json.loads(path.read_text())
        value=saved['value']
        if (saved.get('version')==1 and saved.get('revision')==revision
                and isinstance(value,list) and saved.get('checksum')==_digest(value)):
            return value
    except (OSError,ValueError,KeyError,TypeError):pass
    value=calculate()
    try:
        # Do not certify a snapshot while generation is changing its inputs.
        if revision is not None and _revision(paths)==revision:
            from pdf_pipeline import write_json
            write_json(path,{'version':1,'revision':revision,'value':value,'checksum':_digest(value)})
    except (OSError,ValueError,TypeError):pass
    return value
