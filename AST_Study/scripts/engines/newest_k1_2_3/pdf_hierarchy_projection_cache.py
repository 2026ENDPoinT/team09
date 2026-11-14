"""Disposable, locally derived hierarchy projections; never writes paid files.

A projection is reusable only for the exact input result, document labels,
source PDF, source blocks and local rule code. All failures are cache misses.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat as stat_module
import tempfile

from pdf_study_hierarchy import VERSION as _ACTIVE_HIERARCHY_VERSION
from pdf_study_hierarchy import DISPLAY_REVISION

HIERARCHY_VERSION = 'study-hierarchy-7'
ENVELOPE_VERSION = 1
FILENAME = 'display-hierarchy-7.json'
MAX_BYTES = 16 * 1024 * 1024
_UNSET = object()
_RULE_FILES = ('pdf_study_hierarchy.py', 'pdf_heading_signals.py',
               'pdf_source_units.py',
               'pdf_numbering_context.py', 'pdf_native_heading_structure.py',
               'pdf_source_owner_index.py', 'pdf_new_concept_ver99_study.py',
               'pdf_hierarchy_projection_cache.py')


def stamp(path):
    try:
        value = Path(path).stat()
        if not stat_module.S_ISREG(value.st_mode):
            return None
        return (value.st_dev, value.st_ino, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)
    except (OSError, ValueError, TypeError):
        return None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


@lru_cache(maxsize=1)
def _rules_sha():
    digest = hashlib.sha256()
    base = Path(__file__).parent
    for name in _RULE_FILES:
        digest.update(name.encode('utf-8') + b'\0')
        digest.update((base / name).read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def _paths(folder, cache, result):
    if cache is None or not isinstance(result, dict):
        raise ValueError('No local projection cache')
    folder = Path(folder).resolve(strict=True)
    strategy = result.get('strategy')
    if (not isinstance(strategy, str) or not strategy or strategy in ('.', '..')
            or '/' in strategy or '\\' in strategy):
        raise ValueError('Invalid source strategy')
    strategy_root = (folder / 'generated' / strategy).resolve()
    if not strategy_root.is_relative_to(folder):
        raise ValueError('Detached strategy path')
    cache = Path(cache).resolve()
    if not cache.is_relative_to(strategy_root):
        raise ValueError('Detached projection cache')
    return folder, strategy_root, cache


def _blocks_path(folder, strategy_root, value):
    path = Path(value)
    if not path.is_absolute():
        if '..' in path.parts:
            raise ValueError('Invalid relative source path')
        path = folder / path
    path = path.resolve(strict=True)
    if path.name != 'blocks.json' or not path.is_relative_to(strategy_root):
        raise ValueError('Detached source blocks')
    return path


def _layout_stamp(folder, strategy_root, cache):
    # Capture the selector's complete candidate set, not just the one source
    # that happened to win earlier. A new preferred source or a newly newer
    # candidate must invalidate the previous projection without parsing JSON.
    preferred = cache / 'blocks.json'
    candidates = []
    for path in strategy_root.glob('*/blocks.json'):
        value = stamp(path)
        if value is None:
            raise ValueError('Unreadable source candidate')
        candidates.append((path.relative_to(folder).as_posix(), value))
    candidates.sort(key=lambda item: item[0])
    return ((preferred.relative_to(folder).as_posix(), stamp(preferred)),
            tuple(candidates))


def layout_stamp(folder, cache, result):
    """Cheap immutable selector snapshot to capture before reading source JSON."""
    try:
        folder, strategy_root, cache = _paths(folder, cache, result)
        return _layout_stamp(folder, strategy_root, cache)
    except Exception:
        return None


def _key(result, document, pdf_stamp, source_layout):
    if not isinstance(document, dict):
        raise ValueError('Missing source document')
    labels = [page.get('label') or str(index + 1)
              for index, page in enumerate(document['pages'])]
    return _sha({'result': _sha(result),
                 'document': _sha({'documentId': document.get('documentId'),
                                   'fingerprint': document.get('fingerprint'),
                                   'labels': labels}),
                 'pdf': pdf_stamp, 'layout': source_layout, 'rules': _rules_sha()})


def _strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate projection field')
            value[key] = item
        return value
    def constant(_):
        raise ValueError('Nonfinite projection number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _read(path):
    # A sidecar is disposable data, never a symlink to an unrelated file.
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    if path.is_symlink():
        raise ValueError('Symlinked projection cache')
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat_module.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError('Invalid projection size')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized projection')
    return _strict_json(raw)


def _projection(value):
    if (not isinstance(value, dict) or not isinstance(value.get('hierarchy'), dict)
            or value['hierarchy'].get('version') != HIERARCHY_VERSION
            or value['hierarchy'].get('displayRevision') != DISPLAY_REVISION):
        raise ValueError('Unsupported local hierarchy projection')
    return value


def lookup(folder, cache, result, document):
    try:
        if _ACTIVE_HIERARCHY_VERSION != HIERARCHY_VERSION:
            return None
        folder, strategy_root, cache = _paths(folder, cache, result)
        pdf_stamp = stamp(folder / 'source.pdf')
        if pdf_stamp is None:
            return None
        envelope = _read(cache / FILENAME)
        if (not isinstance(envelope, dict) or type(envelope.get('version')) is not int
                or envelope['version'] != ENVELOPE_VERSION
                or envelope.get('hierarchyVersion') != HIERARCHY_VERSION):
            return None
        source_layout = _layout_stamp(folder, strategy_root, cache)
        if envelope.get('key') != _key(result, document, pdf_stamp, source_layout):
            return None
        blocks = _blocks_path(folder, strategy_root, envelope['blocksPath'])
        blocks_stamp = stamp(blocks)
        if blocks_stamp is None or list(blocks_stamp) != envelope.get('blocksStamp'):
            return None
        value = _projection(envelope['projection'])
        if envelope.get('projectionSha256') != _sha(value):
            return None
        # An input changed while reading/parsing this sidecar: retry normally.
        if (stamp(folder / 'source.pdf') != pdf_stamp or stamp(blocks) != blocks_stamp
                or _layout_stamp(folder, strategy_root, cache) != source_layout):
            return None
        return value
    except Exception:
        return None


def store(folder, cache, result, document, blocks_path, projection, *,
          expected_pdf_stamp=None, expected_blocks_stamp=None, expected_layout_stamp=_UNSET):
    temporary = None
    try:
        if _ACTIVE_HIERARCHY_VERSION != HIERARCHY_VERSION:
            return False
        folder, strategy_root, cache = _paths(folder, cache, result)
        blocks = _blocks_path(folder, strategy_root, blocks_path)
        pdf_stamp = stamp(folder / 'source.pdf')
        blocks_stamp = stamp(blocks)
        if pdf_stamp is None or blocks_stamp is None:
            return False
        if expected_pdf_stamp is not None and tuple(expected_pdf_stamp) != pdf_stamp:
            return False
        if expected_blocks_stamp is not None and tuple(expected_blocks_stamp) != blocks_stamp:
            return False
        source_layout = _layout_stamp(folder, strategy_root, cache)
        if expected_layout_stamp is not _UNSET and expected_layout_stamp != source_layout:
            return False
        value = _projection(projection)
        envelope = {'version': ENVELOPE_VERSION, 'hierarchyVersion': HIERARCHY_VERSION,
                    'key': _key(result, document, pdf_stamp, source_layout),
                    'blocksPath': blocks.relative_to(folder).as_posix(),
                    'blocksStamp': list(blocks_stamp),
                    'projectionSha256': _sha(value), 'projection': value}
        raw = _canonical(envelope)
        if len(raw) > MAX_BYTES:
            return False
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.display-hierarchy-',
                                         suffix='.tmp', dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        if (stamp(folder / 'source.pdf') != pdf_stamp or stamp(blocks) != blocks_stamp
                or _layout_stamp(folder, strategy_root, cache) != source_layout):
            return False
        os.replace(temporary, cache / FILENAME)
        temporary = None
        return (stamp(folder / 'source.pdf') == pdf_stamp and stamp(blocks) == blocks_stamp
                and _layout_stamp(folder, strategy_root, cache) == source_layout)
    except Exception:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
