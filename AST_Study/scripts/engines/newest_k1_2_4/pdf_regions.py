"""Local PDF partitions and crops. No model, API key, or network is used here.

Partitions tile the physical page so figures outside native text are never lost.
Cuts only pass through whitespace between known text/image/table objects. When
geometry is uncertain (scans, rotation, CropBox offsets), retain the whole page.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from pathlib import Path

from pdf_pipeline import check_cancel, write_json

VERSION = 'local-regions-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def box_ok(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def inside(box, region):
    x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
    return region[0] <= x < region[2] and region[1] <= y < region[3]


def partitions(objects, bounds=(0., 0., 1., 1.), depth=0):
    """Conservative XY cuts; an indivisible spanning figure prevents a cut."""
    if depth >= 3 or len(objects) < 2:
        return [list(bounds)]
    choices = []
    for axis in (1, 0):
        intervals = sorted((b[axis], b[axis+2]) for b in objects)
        right = intervals[0][1]
        for left, end in intervals[1:]:
            gap = left-right
            threshold = .018 if axis == 1 else .045
            cut = (left+right)/2
            if gap >= threshold and bounds[axis]+.08 < cut < bounds[axis+2]-.08:
                choices.append((gap/(bounds[axis+2]-bounds[axis]), axis, cut))
            right = max(right, end)
    if not choices:
        return [list(bounds)]
    _, axis, cut = max(choices)
    a, b = list(bounds), list(bounds)
    a[axis+2], b[axis] = cut, cut
    return (partitions([o for o in objects if o[axis+2] <= cut], a, depth+1)
            + partitions([o for o in objects if o[axis] >= cut], b, depth+1))


def words_text(words):
    rows = []
    for word in sorted(words, key=lambda w: (w['bbox'][1], w['bbox'][0])):
        b = word['bbox']
        if not rows or abs(b[1]-rows[-1][0]) > max(.003, (b[3]-b[1])*.4):
            rows.append((b[1], []))
        rows[-1][1].append(word)
    return '\n'.join(' '.join(w['text'] for w in sorted(row, key=lambda w:w['bbox'][0]))
                     for _, row in rows)


def page_blocks(page, compatible=True):
    number = page['number']
    words = [w for w in page.get('words', []) if box_ok(w.get('bbox')) and w.get('text')]
    objects = [r['bbox'] for key in ('textRegions', 'imageRegions', 'tableRegions')
               for r in page.get(key, []) if box_ok(r.get('bbox'))]
    # Words not captured by paragraph detection still prohibit unsafe cuts.
    objects += [w['bbox'] for w in words]
    boxes = partitions(objects) if words and compatible else [[0., 0., 1., 1.]]
    boxes.sort(key=lambda b: (round(b[1], 3), b[0]))
    blocks = []
    for index, box in enumerate(boxes):
        selected = [w for w in words if inside(w['bbox'], box)]
        text = (page.get('nativeText', '') if len(boxes) == 1 else words_text(selected))
        blocks.append({'id': f'p{number}b{index}', 'page': number, 'bbox': box,
                       'text': text, 'visualOnly': not text.strip(),
                       'geometryFallback': not compatible})
    return blocks


def extract(folder, document, numbers):
    from pdf_page_analysis import frame_compatible
    blocks = []
    for n in numbers:
        check_cancel(folder)
        blocks.extend(page_blocks(document['pages'][n-1], frame_compatible(folder, n)))
    return blocks


from pdf_performance import timed

@timed("page_image_render_or_cache_decode")
def page_image(folder, number, root):
    from pdf_page_analysis import render_page
    from PIL import Image
    path = root / 'pages' / f'{number:05d}.png'
    if not path.is_file():
        value = render_page(folder, number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(value['data'].split(',', 1)[1]))
    with Image.open(path) as image:
        return image.convert('RGB')


def render_crops(folder, blocks, root):
    """At most one crop per physical page, preserving order and full resolution.

    Caller serializes local rendering before parallel API work (PDFium is not
    thread safe). Crops keep native rendered pixel density, never upscale.
    """
    root = Path(root)
    images, manifest = [], []
    for n in sorted({b['page'] for b in blocks}):
        check_cancel(folder)
        selected = [b for b in blocks if b['page'] == n]
        box = union([b['bbox'] for b in selected])
        padded = [max(0, box[0]-.008), max(0, box[1]-.008),
                  min(1, box[2]+.008), min(1, box[3]+.008)]
        with page_image(folder, n, root) as page:
            pixels = (math.floor(padded[0]*page.width), math.floor(padded[1]*page.height),
                      math.ceil(padded[2]*page.width), math.ceil(padded[3]*page.height))
            with page.crop(pixels) as crop:
                path = root / 'crops' / (digest([n, padded, crop.size])[:24]+'.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                with io.BytesIO() as out:
                    crop.save(out, format='PNG')
                    raw = out.getvalue()
                if not path.is_file():
                    path.write_bytes(raw)
                images.append({'data':'data:image/png;base64,'+base64.b64encode(raw).decode(),
                               'width':crop.width, 'height':crop.height, 'bytes':len(raw)})
        manifest.append({'page':n, 'bbox':padded, 'blockIds':[b['id'] for b in selected],
                         'path':str(path), 'width':images[-1]['width'], 'height':images[-1]['height']})
    return images, manifest
