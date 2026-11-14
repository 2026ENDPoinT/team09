"""Conservative native prose transport. Missing proof always keeps the image.

Only ordinary Korean prose with matching glyphs and no intersecting graphics is
eligible. The complete text, canonical IDs, page and box stay in the request.
This is not a guarantee that a PDF's Unicode map is semantically correct.
"""
import math
import re

VERSION = 'native-korean-prose-v1'
POLICY = '''\nSOURCE INPUT: nativeTextOnly targets contain complete locally checked native
prose, with their original IDs/pages. Read them fully as source text even without
an image; they have the same coverage and citation obligations as image targets.
All other targets retain their source images. Do not infer that an absent image
means an absent source. Crops and images have the same order.\n'''
COMPACT_SETUP = '''\nCOMPACT SOURCE SETUP: sourceSetup is a minimal safety check, not a second
summary, transcript, explanation or list of all source sentences. For ordinary
unambiguous prose use observedRelations=[], boundaryChecks=[], interpretation="".
For equations/coordinates, code declarations, reported numerical bounds, negation,
ambiguous actors/recipients or diagram relationships retain the short decisive
source phrases and the applicable checks required above. Record each decisive
fact once; do not paraphrase it again in interpretation. Use interpretation only
for an essential disambiguation or result of a check. Keep complete relevant
checks; never truncate them to meet a length quota. For tables record only column
meanings, units and interpretation constraints here, not a second copy of cells.
Every source-taught fact, qualification and relationship still belongs in learner
segments/tables with target blockIds. Internal notes never replace learner text.
Definition, explanation, easyExplanation, uncertainty and coverage rules remain
unchanged. Compress internal duplication, never source meaning or evidence.\n'''


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def native_prose_verified(page, block, chars):
    """Check original page glyphs and graphics before marking an extracted block."""
    if (block.get('kind') not in ('text', 'heading', 'caption')
            or block.get('hasVisual') or block.get('visualOnly')
            or block.get('geometryFallback') or block.get('pageEdgeClipped')
            or getattr(page, 'rotation', 0)):
        return False
    text = block.get('text', '')
    # Latin letters/numbers, math, code, exotic punctuation and missing glyphs
    # keep their images. No language/subject inference is used to remove them.
    if not re.fullmatch(r'[가-힣\s.,·!?():：…‘’“”「」『』\-–—•※]+', text) or len(re.findall('[가-힣]', text)) < 4:
        return False
    try:
        box = [block['bbox'][0]*page.width, block['bbox'][1]*page.height,
               block['bbox'][2]*page.width, block['bbox'][3]*page.height]
        if not all(math.isfinite(v) for v in box) or not (0 <= box[0] < box[2] <= page.width and 0 <= box[1] < box[3] <= page.height):
            return False
        # Any graphic, including a small line or a raster under native text,
        # may change meaning. Do not rely solely on the extractor's hasVisual.
        padded = [box[0]-2, box[1]-2, box[2]+2, box[3]+2]
        for item in [*page.images, *page.curves, *page.rects, *page.lines]:
            bounds = [item['x0'], item['top'], item['x1'], item['bottom']]
            color = item.get('non_stroking_color')
            white = color == 1 or isinstance(color,(tuple,list)) and len(color) in (1,3) and all(c == 1 for c in color)
            if (item.get('object_type') == 'rect' and item.get('fill') and not item.get('stroke')
                    and white and (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) >= page.width*page.height*.8):
                # A flat page-size white background carries no figure/table data.
                # Smaller white backplates and all colored/stroked shapes remain.
                continue
            # Thin rules have zero area; give them a narrow collision box.
            bounds = [bounds[0]-.1, bounds[1]-.1, bounds[2]+.1, bounds[3]+.1]
            if overlaps(padded, bounds):
                return False
        selected = []
        for char in chars:
            bounds = [char['x0'], char['top'], char['x1'], char['bottom']]
            if not overlaps(box, bounds):
                continue
            if (not char.get('upright', False) or
                    re.search(r'wingding|webding|symbol|math|hwp.?eq', char.get('fontname', ''), re.I)
                    or not (box[0]-.1 <= bounds[0] < bounds[2] <= box[2]+.1 and
                            box[1]-.1 <= bounds[1] < bounds[3] <= box[3]+.1)):
                return False
            selected.append(char)
        if not selected:
            return False
        from pdfplumber.utils import extract_text
        observed = extract_text(selected)
        compact = lambda s: re.sub(r'\s+', '', s)
        return compact(observed) == compact(text)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def select_images(blocks, images, crops):
    """Drop only wholly verified crops; preserve mixed crops and exact ordering."""
    if len(images) != len(crops):
        raise ValueError('원문 이미지와 출처 목록의 순서가 맞지 않아요.')
    known = {b['id']: b for b in blocks}
    kept_images, kept_crops = [], []
    text_only = {b['id'] for b in blocks if not requires_image([b])}
    for image, crop in zip(images, crops):
        ids = crop.get('blockIds', [])
        safe = bool(ids) and all(i in known for i in ids) and not requires_image([known[i] for i in ids])
        if safe:
            text_only.update(ids)
        else:
            kept_images.append(image); kept_crops.append(crop)
    # A block in a mixed retained image is not described as text-only.
    text_only.difference_update(i for crop in kept_crops for i in crop.get('blockIds', []))
    return kept_images, kept_crops, text_only


def requires_image(blocks):
    return not blocks or not all(b.get('nativeTextProof') == VERSION
        and b.get('text', '').strip() and not b.get('hasVisual')
        and not b.get('visualOnly') and not b.get('geometryFallback')
        and not b.get('pageEdgeClipped') for b in blocks)


def render_blocks(blocks):
    """Re-crop mixed runs around risky sources, without multiplying images.

    Full native prose remains in the canonical payload. If separation makes more
    crops or increases total crop area, retain the original image envelope.
    """
    from pdf_new_concept_v02_regions import crop_runs
    candidate = [b for b in blocks if requires_image([b])]
    if len(candidate) == len(blocks):
        return blocks
    def envelope(items):
        runs = crop_runs(items)
        area = sum((max(b['bbox'][2] for b in run)-min(b['bbox'][0] for b in run)) *
                   (max(b['bbox'][3] for b in run)-min(b['bbox'][1] for b in run)) for run in runs)
        return len(runs), area
    old_count, old_area = envelope(blocks)
    count, area = envelope(candidate)
    return candidate if count <= old_count and area <= old_area else blocks
