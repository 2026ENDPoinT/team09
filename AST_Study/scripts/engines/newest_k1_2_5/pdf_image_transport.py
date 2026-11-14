"""Optional lossless image transport; original PNG cache files stay unchanged."""
from __future__ import annotations

import base64
import io
import hashlib
import json
from pathlib import Path

from PIL import features

VERSION = 'lossless-image-transport-v1'
LOSSLESS_WEBP = True
WEBP_METHOD = 0
MIN_WEBP_PNG_BYTES = 16 * 1024
# A second lossless pass is cheap on text slides but dominates photo-heavy crops.
# Keep legacy data/bytes unchanged; only the optional wire copy follows this budget.
MAX_COMPACT_PNG_BYTES = 512 * 1024
WIRE_POLICY = 'bounded-second-pass-v1'


def _webp_bytes(crop):
    data = io.BytesIO()
    # In lossless mode quality controls encoder effort. These settings were
    # checked against every decoded RGBA byte on representative source crops.
    crop.save(data, format='WEBP', lossless=True, quality=0, method=WEBP_METHOD, exact=True)
    return data.getvalue()


def _compact_webp_bytes(crop):
    data = io.BytesIO()
    # Method 0 can be much larger than PNG on text slides. Method 1 preserves
    # the same pixels, including RGB under transparent pixels, without resizing.
    crop.save(data, format='WEBP', lossless=True, quality=0, method=1, exact=True)
    return data.getvalue()


def encode_crop(crop, png_bytes=None, *, enabled=None, compact=None, cache_dir=None):
    """Return request metadata without changing the crop or its cache file.

    ``png_bytes`` must be the caller's existing PNG encoding of this same crop.
    Tiny crops and unsupported modes/codecs keep PNG. A lossless WebP is used
    only when it is smaller; decoding/semantic checks are not added at runtime.
    """
    if png_bytes is None:
        data = io.BytesIO()
        crop.save(data, format='PNG')
        png_bytes = data.getvalue()
    if not isinstance(png_bytes, bytes):
        raise TypeError('The existing PNG encoding must be bytes.')
    use_webp = LOSSLESS_WEBP if enabled is None else bool(enabled)
    compact_allowed = len(png_bytes)<=MAX_COMPACT_PNG_BYTES if compact is None else bool(compact)
    cache_path = None
    if cache_dir is not None:
        # This is a local encoding cache, separate from paid reply identities.
        from PIL import __version__ as pillow_version
        identity = [WIRE_POLICY,pillow_version,features.version('webp'),crop.mode,crop.size,
                    use_webp,WEBP_METHOD,compact_allowed,hashlib.sha256(png_bytes).hexdigest()]
        cache_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        cache_path = Path(cache_dir)/(cache_key+'.json')
        try:
            from pdf_pipeline import read_json_cache
            stored = read_json_cache(cache_path)
            if isinstance(stored,dict) and stored.get('key')==cache_key:
                from pdf_k122_image_cache import restore
                result = restore(cache_path,stored)
                checksum = hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
                if checksum==stored.get('checksum') and isinstance(result.get('data'),str):
                    return result
        except (OSError,ValueError,KeyError,TypeError):
            pass
    raw, mime, ext = png_bytes, 'image/png', 'png'
    if (use_webp and len(png_bytes) >= MIN_WEBP_PNG_BYTES
            and crop.mode in ('RGB', 'RGBA') and features.check('webp')):
        try:
            candidate = _webp_bytes(crop)
            if len(candidate) < len(png_bytes):
                raw, mime, ext = candidate, 'image/webp', 'webp'
        except (OSError, ValueError, KeyError):
            # Platform builds without a usable encoder must remain functional.
            pass
    result = {'data': 'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii'),
              'width': crop.width, 'height': crop.height, 'bytes': len(raw),
              'mimeType': mime, 'ext': ext}
    if (use_webp and compact_allowed and len(raw) >= MIN_WEBP_PNG_BYTES
            and crop.mode in ('RGB', 'RGBA') and features.check('webp')):
        try:
            compact = _compact_webp_bytes(crop)
            if len(compact) < len(raw):
                # Keep data/bytes exactly as before for paid-cache identities
                # and missing-response guards. Study sends this smaller copy
                # only after those identities have been checked.
                result.update(wireData='data:image/webp;base64,'+
                    base64.b64encode(compact).decode('ascii'), wireBytes=len(compact))
        except (OSError, ValueError, KeyError):
            pass
    if cache_path is not None:
        try:
            from pdf_k122_image_cache import write
            checksum = hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
            write(cache_path,cache_key,result,checksum)
        except (OSError,ValueError):
            pass  # Encoding remains usable even when a cache cannot be saved.
    return result
