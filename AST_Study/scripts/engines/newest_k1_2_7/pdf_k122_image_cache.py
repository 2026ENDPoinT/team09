"""Small image-cache metadata plus content-addressed lossless binary blobs.

The reconstructed request dictionary is byte-for-byte equal to the former
inline Base64 dictionary. Corrupt/missing local data is a cache miss; native
receipts, paid-answer identities, source PNGs and source PDFs are untouched.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

VERSION = 'k122-binary-image-cache-v1'
FIELDS = ('data', 'wireData')


def _blob_path(cache, digest):
    if not isinstance(digest, str) or re.fullmatch('[a-f0-9]{64}', digest) is None:
        raise ValueError('Invalid image digest')
    return Path(cache).parent / '.encoded-blobs' / (digest + '.bin')


def _write_blob(path, raw):
    from pdf_k123_shared_images import write_shared
    write_shared(path,raw)


def write(cache, key, result, checksum):
    stored = copy.deepcopy(result)
    binary = {}
    for field in FIELDS:
        data = stored.get(field)
        if not isinstance(data, str) or ';base64,' not in data:
            continue
        prefix, encoded = data.split(';base64,', 1)
        if prefix not in ('data:image/png', 'data:image/webp'):
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            continue
        if base64.b64encode(raw).decode('ascii') != encoded:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        _write_blob(_blob_path(cache, digest), raw)
        binary[field] = {'sha256': digest, 'prefix': prefix, 'bytes': len(raw)}
        del stored[field]
    from pdf_pipeline import write_json
    write_json(cache, {'key': key, 'checksum': checksum, 'result': stored,
                      'binaryImageCacheVersion': VERSION, 'binaryFields': binary,
                      'resultFieldOrder': list(result)})


def restore(cache, stored):
    if not isinstance(stored.get('result'), dict):
        raise ValueError('Invalid image-cache result')
    if stored.get('binaryImageCacheVersion') is None:
        return stored['result']  # Original inline caches remain readable.
    if stored.get('binaryImageCacheVersion') != VERSION:
        raise ValueError('Unknown image-cache format')
    result = copy.deepcopy(stored['result'])
    fields = stored['binaryFields']
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise ValueError('Invalid binary image fields')
    for field, metadata in fields.items():
        if (not isinstance(metadata, dict) or field in result
                or metadata.get('prefix') not in ('data:image/png', 'data:image/webp')):
            raise ValueError('Invalid image field')
        raw = _blob_path(cache, metadata['sha256']).read_bytes()
        if len(raw) != metadata['bytes'] or hashlib.sha256(raw).hexdigest() != metadata['sha256']:
            raise ValueError('Corrupt image-cache blob')
        result[field] = metadata['prefix'] + ';base64,' + base64.b64encode(raw).decode('ascii')
    order = stored.get('resultFieldOrder')
    if not isinstance(order, list) or any(not isinstance(k,str) for k in order):
        raise ValueError('Invalid image field order')
    if len(order) != len(set(order)) or set(order) != set(result):
        raise ValueError('Image field order does not match payload')
    return {key: result[key] for key in order}
