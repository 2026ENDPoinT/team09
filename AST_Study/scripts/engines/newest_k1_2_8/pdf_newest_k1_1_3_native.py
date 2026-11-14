"""Read-only native title evidence for whole-page/whole-panel source blocks.

This projection never changes a source ID, the original text, generation input,
or image geometry. It only annotates a copied block with one corroborated title.
Ambiguous layouts and image-only pages deliberately retain the original block.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import statistics
import threading
import unicodedata
from collections import OrderedDict, defaultdict
from pathlib import Path
from pdf_heading_signals import strip_prefix

VERSION = 'native-heading-structure-2'
_CACHE_MAX_ENTRIES = 32
_CACHE_MAX_HEADINGS = 4096
_CACHE_MAX_BYTES = 2 * 1024 * 1024
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_BYTES = 0
_CACHE_HEADINGS = 0
_EXERCISE = re.compile(r'^(?:Q[.：:)\s]|Question\b|Exercise\b|Problem\b|Example\b|'
    r'Solution\b|Proof\b|Quiz\b|예제|연습문제|문제\s*\d|보기|풀이|해설|참고)', re.I)
_NAVIGATION = re.compile(r'^(?:Contents|Table of Contents|Learning Objectives?|목차|차례|학습\s*목표)\s*$', re.I)
_MATH = re.compile(r'[=∑∫∞→⇒≤≥]|\\(?:frac|sum|int|sqrt|lim)\b')
_CHOICE = re.compile(r'^\s*(?:\(?\d{1,2}[.)]|[①-⑳]|\([A-Za-z]\))\s*\S')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value):
    return (isinstance(value, (list, tuple)) and len(value) == 4
        and all(_finite(v) for v in value) and value[0] < value[2] and value[1] < value[3])


def _key(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def _letters(text):
    return sum(c.isalpha() for c in text)


def _eligible(block):
    if (block.get('fontSize') or block.get('nativeHeading') or block.get('kind') not in ('page', 'visual')
            or block.get('localRole') in ('decoration', 'navigation', 'exercise')
            or type(block.get('page')) is not int or block['page'] < 1):
        return False
    bounds = block.get('zoneBounds', [0., 0., 1., 1.])
    bbox = block.get('bbox', [0., 0., 1., 1.] if block.get('kind') == 'page' else None)
    if not _box(bounds) or not _box(bbox):
        return False
    area = (bbox[2]-bbox[0])*(bbox[3]-bbox[1])
    return area >= .5*(bounds[2]-bounds[0])*(bounds[3]-bounds[1])


def _source_fingerprint(source):
    try:
        stat = source.stat()
        return (str(source.resolve()), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns)
    except (OSError, ValueError):
        return None


def _cache_key(fingerprint, eligible):
    if fingerprint is None:
        return None
    try:
        # Keep only exact identities and hashes, never another copy of source
        # text. Eligible-order indices remain valid if unrelated blocks move.
        signatures = []
        for block in eligible:
            fields = {key: block.get(key) for key in
                      ('id', 'page', 'kind', 'fontSize', 'bbox', 'zone', 'zoneBounds', 'localRole')}
            fields['textSha256'] = hashlib.sha256(block.get('text', '').encode('utf-8')).hexdigest()
            signatures.append(fields)
        encoded = json.dumps(signatures, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
        return (VERSION, fingerprint, hashlib.sha256(encoded).digest())
    except (AttributeError, TypeError, ValueError):
        return None


def _cache_get(key):
    if key is None:
        return None
    with _CACHE_LOCK:
        found = _CACHE.pop(key, None)
        if found is not None:
            _CACHE[key] = found
            return found[0]  # Immutable JSON string, decoded outside the lock.
    return None


def _cache_put(key, annotations):
    global _CACHE_BYTES, _CACHE_HEADINGS
    if key is None:
        return
    payload = json.dumps(annotations, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    size = len(payload.encode('utf-8')); count = len(annotations)
    if (size > _CACHE_MAX_BYTES or count > _CACHE_MAX_HEADINGS
            or _CACHE_MAX_ENTRIES < 1):
        return
    with _CACHE_LOCK:
        previous = _CACHE.pop(key, None)
        if previous is not None:
            _CACHE_BYTES -= previous[1]; _CACHE_HEADINGS -= previous[2]
        _CACHE[key] = (payload, size, count)
        _CACHE_BYTES += size; _CACHE_HEADINGS += count
        while (_CACHE and (len(_CACHE) > _CACHE_MAX_ENTRIES
                or _CACHE_BYTES > _CACHE_MAX_BYTES or _CACHE_HEADINGS > _CACHE_MAX_HEADINGS)):
            _, discarded = _CACHE.popitem(last=False)
            _CACHE_BYTES -= discarded[1]; _CACHE_HEADINGS -= discarded[2]


def _clear_cache():
    """Discard process-local derived metadata; no file or source-state changes."""
    global _CACHE_BYTES, _CACHE_HEADINGS
    with _CACHE_LOCK:
        _CACHE.clear(); _CACHE_BYTES = 0; _CACHE_HEADINGS = 0


def _lines(page):
    """Use native words and their real font attributes; never perform OCR."""
    import pdfplumber
    origin_x, origin_y = page.bbox[:2]
    width, height = page.width, page.height
    if not width or not height:
        return []
    chars = [c for c in page.chars if c.get('text') and _finite(c.get('size'))
        and all(_finite(c.get(k)) for k in ('x0', 'x1', 'top', 'bottom'))]
    words = pdfplumber.utils.extract_words(chars, extra_attrs=['size', 'fontname'])
    rows = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        box = [(word['x0']-origin_x)/width, (word['top']-origin_y)/height,
               (word['x1']-origin_x)/width, (word['bottom']-origin_y)/height]
        if not _box(box) or not (0 <= (box[1]+box[3])/2 <= 1):
            continue
        item = {'text': word['text'], 'box': box, 'size': word['size'],
                'bold': any(s in word.get('fontname', '').casefold() for s in ('bold', 'black', 'heavy', 'demi'))}
        match = next((r for r in reversed(rows[-4:])
            if min(r['box'][3], box[3])-max(r['box'][1], box[1])
                > min(r['box'][3]-r['box'][1], box[3]-box[1])*.5), None)
        if match is None:
            rows.append({'box': box[:], 'words': [item]})
        else:
            match['words'].append(item)
            match['box'] = [min(match['box'][0], box[0]), min(match['box'][1], box[1]),
                            max(match['box'][2], box[2]), max(match['box'][3], box[3])]
    result = []
    for row in rows:
        # A wide gap can be a second column or an axis legend. Preserve it as
        # another line candidate so an unknown two-column page is not merged.
        chunks = []; current = []; right = 0
        for word in sorted(row['words'], key=lambda w: w['box'][0]):
            if current and word['box'][0]-right > .05:
                chunks.append(current); current = []
            current.append(word); right = word['box'][2]
        if current: chunks.append(current)
        for chunk in chunks:
            text = ' '.join(w['text'] for w in chunk).strip()
            sizes = [w['size'] for w in chunk for _ in range(max(1, len(w['text'])))]
            count = sum(max(1, len(w['text'])) for w in chunk)
            median_size=statistics.median(sizes)
            result.append({'text': text, 'bbox': [min(w['box'][0] for w in chunk),
                min(w['box'][1] for w in chunk), max(w['box'][2] for w in chunk), max(w['box'][3] for w in chunk)],
                'fontSize': median_size,
                '_coherent': sum(abs(size-median_size)<=max(.5,median_size*.035) for size in sizes)/len(sizes)>=.85,
                'bold': sum(max(1, len(w['text'])) for w in chunk if w['bold']) > count*.65})
    return sorted(result, key=lambda r: (r['bbox'][1], r['bbox'][0]))


def _inside(line, bounds):
    box = line['bbox']; x = (box[0]+box[2])/2; y = (box[1]+box[3])/2
    return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]


def _title(line):
    text = line['text']
    fragment=strip_prefix(text).strip()
    if (re.match(r'^[)\]}〉》]',fragment) or re.search(r'[,，、]$',fragment)
            or any(fragment.count(left)!=fragment.count(right) for left,right in [('(',')'),('[',']'),('{','}')])):
        return False
    return (2 <= _letters(text) and len(text) <= 120 and '\n' not in text
        and not _EXERCISE.match(text) and not _NAVIGATION.match(text) and not _MATH.search(text)
        and line.get('_coherent',False)
        and not re.search(r'[.!。;:]$', text)
        and not re.fullmatch(r'\([^)]*\)[:_\s]*',text)
        # An unlabelled amount/date near a chart is insufficient title evidence.
        # Explicit section punctuation ("1. Topic") remains eligible.
        and not re.match(r'^[+-]?\d+(?:[.,]\d+)*\s+\S', text)
        and not re.fullmatch(r'[\d\W]+', text))


def _candidates(block, lines):
    bounds = block.get('zoneBounds', [0., 0., 1., 1.])
    bbox = block.get('bbox', [0., 0., 1., 1.])
    panel = [line for line in lines if _inside(line, bounds)]
    # A question with answer choices is not a lesson heading even when the
    # first option is in the upper quarter of the page and uses a large font.
    if (any(_EXERCISE.match(line['text']) for line in panel)
            and sum(bool(_CHOICE.match(line['text'])) for line in panel) >= 2):
        return []
    result = []
    for line in panel:
        box = line['bbox']; relative_y = (box[1]-bounds[1])/(bounds[3]-bounds[1])
        if not (0 <= relative_y <= .25 and _inside(line, bbox) and _title(line)):
            continue
        # The native title must also be present in the saved source text when
        # that text exists. Never replace an unrelated crop's source identity.
        if block.get('text', '').strip() and _key(line['text']) not in _key(block['text']):
            continue
        below = [other for other in panel if other['bbox'][1] > box[3]
                 and (other['bbox'][1]-bounds[1])/(bounds[3]-bounds[1]) < .9
                 and _letters(other['text']) >= 2]
        if not below:
            # A native slide title above an image body needs corroboration by
            # the same title track on other pages; a lone cover cannot qualify.
            if block.get('hasVisual') or block.get('kind')=='visual':
                result.append({**line,'bodyFontSize':0,'_distinct':False,
                    '_normalBody':False,'_visualBody':True,'_bounds':bounds})
            continue
        sizes = [other['fontSize'] for other in below
                 for _ in range(min(120, max(1, _letters(other['text']))))]
        body_size = statistics.median(sizes)
        distinct = line['fontSize']-body_size > max(.5, line['fontSize']*.035)
        normal_body = any(not other['bold'] for other in below)
        result.append({**line, 'bodyFontSize': body_size, '_distinct': distinct,
                       '_normalBody': normal_body, '_bounds': bounds})
    return result


def supplement(folder, blocks, *, status=None):
    """Return an annotated copy; native read failures leave the source unchanged.

    Only one native title per eligible whole block can be added. Subsections
    inside an indivisible source block are not guessed or assigned artificial IDs.
    An optional status mapping distinguishes a complete negative result from a
    transient read failure so callers can safely persist derived projections.
    """
    if status is not None:
        status['complete'] = False
    value = copy.deepcopy(list(blocks)); eligible = [b for b in value if _eligible(b)]
    source = Path(folder)/'source.pdf'
    if not eligible:
        if status is not None:
            status['complete'] = True
        return value
    if not source.is_file():
        return value
    fingerprint = _source_fingerprint(source)
    if fingerprint is None:
        return value
    cache_key = _cache_key(fingerprint, eligible)
    cached = _cache_get(cache_key)
    if cached is not None and _source_fingerprint(source) == fingerprint:
        for index, annotation in json.loads(cached):
            eligible[index]['nativeHeading'] = annotation
        if status is not None:
            status['complete'] = True
        return value
    candidates = {}; styles = defaultdict(set)
    try:
        import pdfplumber
        with pdfplumber.open(source) as pdf:
            pages = {}
            for block in eligible:
                number = block['page']
                if number > len(pdf.pages):
                    continue
                if number not in pages:
                    pages[number] = _lines(pdf.pages[number-1])
                found = _candidates(block, pages[number]); candidates[id(block)] = found
                for candidate in found:
                    bounds = candidate['_bounds']; box = candidate['bbox']
                    style = (round(candidate['fontSize']/pdf.pages[number-1].height, 3),
                        round((box[0]-bounds[0])/(bounds[2]-bounds[0])/.04),
                        round((box[1]-bounds[1])/(bounds[3]-bounds[1])/.04), candidate['bold'])
                    candidate['_style'] = style
                    styles[style].add((number, _key(candidate['text'])))
    except Exception:
        # PDF parsing/font failures are local uncertainty, not permission for a
        # model call or for changing the saved source/generation cache.
        return value
    annotations = []
    for index, block in enumerate(eligible):
        def repeated(candidate):
            style=styles[candidate['_style']]
            return len({page for page,_ in style})>=2 and len({title for _,title in style})>=2
        found = [c for c in candidates.get(id(block), [])
                 if (c['_distinct'] or c['bold'] and c['_normalBody'] and repeated(c)
                     or c.get('_visualBody') and repeated(c))
                 and (_letters(c['text'])>=4 or repeated(c))]
        if not found:
            continue
        largest = max(c['fontSize'] for c in found)
        top = [c for c in found if largest-c['fontSize'] <= max(.5, largest*.035)]
        if len(top) != 1:
            continue
        chosen = top[0]
        annotation = {k: copy.deepcopy(chosen[k])
            for k in ('text', 'fontSize', 'bbox', 'bodyFontSize', 'bold')}
        annotation['title'] = annotation.pop('text')
        annotations.append((index, annotation))
    # A successful parse with no title is a useful negative result. Never cache
    # transient read/parse failures or metadata obtained while the PDF changed.
    if _source_fingerprint(source) != fingerprint:
        return value
    _cache_put(cache_key, annotations)
    for index, annotation in annotations:
        eligible[index]['nativeHeading'] = annotation
    if status is not None:
        status['complete'] = True
    return value
