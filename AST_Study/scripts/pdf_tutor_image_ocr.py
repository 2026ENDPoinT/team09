"""Bounded, on-demand reading of PDF image text with macOS Vision."""
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

MAX_IMAGES = 256
MAX_SIDE = 2400
MAX_TOTAL_PIXELS = 96_000_000
MAX_SECONDS = 32
BATCH_SIZE = 16

# JXA can call the installed Vision framework without an SDK or extra Python
# dependencies. Only temporary local image paths are passed to the script.
_VISION = r"""
ObjC.import("Foundation")
ObjC.import("Vision")
function run(args) {
    const languages = args[0] === "ko" ? ["ko-KR", "en-US"] : ["en-US", "ko-KR"];
    const request = $.VNRecognizeTextRequest.alloc.init;
    request.recognitionLevel = 0;
    request.usesLanguageCorrection = false;
    const supported = ObjC.deepUnwrap(request.supportedRecognitionLanguagesAndReturnError(Ref()));
    const selected = languages.filter(language => supported.indexOf(language) >= 0);
    if (selected.indexOf(languages[0]) < 0) return JSON.stringify(args.slice(1).map(() => null));
    request.recognitionLanguages = $(selected);
    return JSON.stringify(args.slice(1).map(path => {
        try {
            const url = $.NSURL.fileURLWithPath(path);
            const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $({}));
            if (!handler.performRequestsError($([request]), Ref())) return null;
            const lines = [];
            for (let index = 0; index < request.results.count; index++) {
                const candidates = request.results.objectAtIndex(index).topCandidates(1);
                if (candidates.count) lines.push(ObjC.unwrap(candidates.objectAtIndex(0).string));
            }
            return lines;
        } catch (error) {
            return null;
        }
    }));
}
"""


def _recognize(paths, language, timeout):
    if not paths or sys.platform != 'darwin':
        return [None] * len(paths)
    try:
        process = subprocess.run(
            ['/usr/bin/osascript', '-l', 'JavaScript', '-e', _VISION, language, *map(str, paths)],
            capture_output=True, text=True, timeout=timeout, check=True)
        values = json.loads(process.stdout)
    except InterruptedError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        return [None] * len(paths)
    if not isinstance(values, list) or len(values) != len(paths):
        return [None] * len(paths)
    return [value if isinstance(value, list) and all(isinstance(line, str) for line in value) else None
            for value in values]


def _picture(bitmap, crop=None):
    from PIL import Image

    try:
        picture = bitmap.to_pil()
        if crop is not None:
            x0, y0, x1, y1 = crop
            width, height = picture.size
            picture = picture.crop((round(x0 * width), round(y0 * height),
                                    round(x1 * width), round(y1 * height)))
        if picture.mode == 'RGBA':
            picture = Image.alpha_composite(Image.new('RGBA', picture.size, 'white'), picture)
        picture = picture.convert('RGB')
    finally:
        bitmap.close()
    if min(picture.size) < 8:
        return None  # At most a few source pixels cannot hold readable text.
    picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    if max(picture.size) < 500:
        picture = picture.resize(tuple(n * 2 for n in picture.size), Image.Resampling.LANCZOS)
    return picture


def _visible_crop(bounds, page_bounds):
    left, bottom, right, top = bounds
    x0, y0, x1, y1 = page_bounds
    return (max(0., (x0 - left) / (right - left)), max(0., (top - y1) / (top - bottom)),
            min(1., (x1 - left) / (right - left)), min(1., (top - y0) / (top - bottom)))


def _placement(image, bounds):
    # Child bounds alone would merge one image drawn inside differently placed
    # Form XObjects on the same page.
    coordinates = list(bounds)
    container = image.container
    while container is not None:
        matrix = container.get_matrix()
        coordinates.extend((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f))
        container = container.container
    return tuple(round(value, 3) for value in coordinates)


def _regions(pdfium, page, full_page):
    found = False
    for image in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
        width, height = image.get_px_size()
        if min(width, height) < 8:
            continue
        bounds = image.get_bounds()
        left, bottom, right, top = bounds
        if left >= right or bottom >= top:
            continue
        # Top-level object bounds use page coordinates. A Form XObject's
        # child coordinates use its local space and cannot be cropped this way.
        crop = _visible_crop(bounds, page.get_bbox()) if image.level == 0 else (0., 0., 1., 1.)
        if crop[0] >= crop[2] or crop[1] >= crop[3]:
            continue
        found = True
        display_width, display_height = right - left, top - bottom
        if (width < height) != (display_width < display_height):
            width, height = height, width
        scale = max(width / display_width, height / display_height)
        estimated = math.ceil(display_width * scale) * math.ceil(display_height * scale)
        if width * height > 24_000_000 or estimated > 24_000_000:
            # Rendering the entire bitmap could exceed the worker's memory.
            yield None, None
            continue
        yield _placement(image, bounds), _picture(image.get_bitmap(render=True), crop)
    if not found and full_page:
        width, height = page.get_size()
        yield None, _picture(page.render(scale=min(3., MAX_SIDE / max(width, height))))


def scan(folder, document, *, full_page_candidates=(), term=''):
    """Return image text grouped per physical image occurrence and page.

    A repeated raster is read once but can count at distinct positions or on
    different pages. An unprocessed image keeps its page out of checkedPages.
    Full-page candidates are only rendered if no embedded raster was found.
    """
    pages = document.get('pages', [])
    page_numbers = set(range(1, len(pages) + 1))
    result = {'textsByPage': {}, 'checkedPages': [], 'unreadablePages': sorted(page_numbers)}
    if folder is None or not (source := Path(folder) / 'source.pdf').is_file():
        return result
    deadline = time.monotonic() + MAX_SECONDS
    placements = {}
    image_paths = {}
    pixels_used = 0
    unreadable = set()
    full_page_candidates = set(full_page_candidates)
    try:
        import pypdfium2 as pdfium

        with tempfile.TemporaryDirectory(prefix='synesis-image-ocr-') as directory:
            with pdfium.PdfDocument(source) as pdf:
                if len(pdf) != len(pages):
                    return result
                for number, page in enumerate(pdf, 1):
                    if time.monotonic() >= deadline:
                        unreadable.update(range(number, len(pages) + 1))
                        break
                    try:
                        seen = set()
                        for coordinates, picture in _regions(pdfium, page, number in full_page_candidates):
                            if time.monotonic() >= deadline:
                                unreadable.add(number)
                                break
                            if picture is None:
                                unreadable.add(number)
                                continue
                            key = (picture.size, hashlib.blake2s(picture.tobytes()).digest())
                            position = (key, coordinates)
                            if position in seen:
                                continue
                            seen.add(position)
                            if key not in image_paths:
                                pixels = picture.width * picture.height
                                if (len(image_paths) >= MAX_IMAGES or
                                        pixels_used + pixels > MAX_TOTAL_PIXELS):
                                    unreadable.add(number)
                                    continue
                                path = Path(directory) / f'{len(image_paths)}.png'
                                picture.save(path, compress_level=1)
                                image_paths[key] = path
                                pixels_used += pixels
                            placements.setdefault(number, []).append(key)
                    except InterruptedError:
                        raise
                    except (OSError, ValueError, RuntimeError, ZeroDivisionError):
                        unreadable.add(number)
                    finally:
                        page.close()
            keys = list(image_paths)
            readings = {}
            language = 'ko' if re.search(r'[가-힣]', term) else 'en'
            for start in range(0, len(keys), BATCH_SIZE):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                batch = keys[start:start + BATCH_SIZE]
                readings.update(zip(batch, _recognize([image_paths[key] for key in batch], language, remaining)))
    except InterruptedError:
        raise
    except (ImportError, OSError, ValueError, RuntimeError):
        return result
    for number, image_keys in placements.items():
        for key in image_keys:
            lines = readings.get(key)
            if lines is None:
                unreadable.add(number)
            elif lines:
                result['textsByPage'].setdefault(number, []).append('\n'.join(lines))
    result['checkedPages'] = sorted(page_numbers - unreadable)
    result['unreadablePages'] = sorted(unreadable)
    return result
