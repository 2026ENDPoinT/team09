"""One verified copy of disposable image bytes with atomic cache aliases.

Request dictionaries, source pixels and paid response identities are unchanged.
Hard links are an optimization: unsupported filesystems use the same atomic bytes.
"""
import hashlib
import os
from pathlib import Path
import tempfile

VERSION='k123-shared-lossless-images-v1'


def _root(path):
    fallback=path.parent/'.image-blobs'
    for parent in path.parents:
        if parent.name=='newest-k1-2-3'and parent.parent.name=='generated':
            return parent/'.image-blobs'
        if parent.name in ('crops','crop-encoding-cache','transport-cache'):
            fallback=parent.parent/'.image-blobs'
    return fallback


def _atomic_bytes(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.image-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb')as stream:stream.write(raw)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def write_shared(path,raw):
    if not isinstance(raw,bytes):raise TypeError('Image bytes are required')
    path=Path(path);digest=hashlib.sha256(raw).hexdigest();blob=_root(path)/(digest+'.bin')
    try:valid=hashlib.sha256(blob.read_bytes()).hexdigest()==digest
    except OSError:valid=False
    if not valid:_atomic_bytes(blob,raw)
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        if path.exists()and os.path.samefile(path,blob):return
    except OSError:pass
    fd,temp=tempfile.mkstemp(prefix='.image-link-',suffix='.tmp',dir=path.parent)
    os.close(fd);os.unlink(temp)
    try:
        try:os.link(blob,temp)
        except OSError:
            _atomic_bytes(path,raw)
            return
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
