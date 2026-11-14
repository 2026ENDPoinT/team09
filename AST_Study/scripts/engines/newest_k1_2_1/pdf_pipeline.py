"""Local, page-addressable PDF preparation. This module never reads .env or calls an API."""
from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import tempfile
from collections import Counter
from synesis_paths import hydrate, portable, io_path
from pdf_equation_font import repair_chars
from pdf_symbol_bullets import repair_symbol_chars
from pdf_slide_lens import ensure_region_catalog

# Keep the extraction worker independent of provider credentials.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

VERSION = "pdf-local-v7-equation-font"
VISUAL_ROUTING_VERSION = 3
CHUNK_CHARS = 1800
MAX_CONTEXT_BYTES = 18000
_EMIT_LOCK = threading.Lock()


def read_json_cache(path, expected_type=dict):
    """Treat a damaged derived cache as a miss; paid raw responses remain recoverable."""
    try:
        value = hydrate(json.loads(io_path(path).read_text(encoding="utf-8")), path)
        return value if isinstance(value, expected_type) else None
    except (OSError, ValueError):
        return None


def write_json(path: Path, value):
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The previous destination + PID + UUID name pushed ordinary Windows caches
    # past MAX_PATH. Keep an exclusive short sibling for the atomic replacement.
    fd, name = tempfile.mkstemp(prefix='.s-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(portable(value, path), ensure_ascii=False, indent=2))
        for attempt in range(8):
            try:
                os.replace(temp, path)
                return
            except OSError as error:
                # Windows readers and file scanners can briefly lock the destination.
                transient = (getattr(error, "winerror", None) in (5, 32)
                             or error.errno in (errno.EACCES, errno.EBUSY))
                if not transient or attempt == 7:
                    raise
                time.sleep(min(0.03 * (2 ** attempt), 0.2))
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def emit(kind, **values):
    with _EMIT_LOCK:
        print(json.dumps({"type": kind, **values}, ensure_ascii=False), flush=True)


def check_cancel(folder):
    from pdf_worker_control import cancelled
    if cancelled():raise InterruptedError('분석을 취소했습니다. 완료된 페이지는 보관됩니다.')
    # Comparison variants live two levels below the source folder. The UI writes
    # one cancellation marker for the whole approved two-stage run.
    source_folder = folder.parent.parent if folder.parent.name == "comparison" else folder
    if (folder / "cancel").exists() or (source_folder / "cancel").exists():
        raise InterruptedError("분석을 취소했습니다. 완료된 페이지는 보관됩니다.")


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def make_chunks(document_id, pages, text_field="markdown"):
    chunks = []
    for page in pages:
        sources = [("native", text_field, page.get(text_field, ""), None)]
        for source, field, text, bbox in sources:
            start = 0
            while start < len(text):
                end = min(start + CHUNK_CHARS, len(text))
                if end < len(text):
                    boundary = text.rfind("\n", start + CHUNK_CHARS//2, end)
                    if boundary > start:
                        end = boundary + 1
                excerpt = text[start:end]
                if excerpt.strip():
                    identifier = f"p{page['number']}-{source}-{len(chunks)+1}"
                    chunks.append({"id": identifier, "documentId": document_id,
                        "page": page["number"], "pageLabel": page.get("label"), "source": source,
                        "field": field, "start": start, "end": end, "text": excerpt,
                        "bbox": bbox, "lectureLink": None})
                if end == len(text):
                    break
                start = max(start + 1, end - 160)
    return chunks


def image_regions(page):
    """Embedded raster image boxes in normalized PDF-page coordinates."""
    regions = []
    for item in page.images:
        x0, y0 = max(0, item["x0"]), max(0, item["top"])
        x1, y1 = min(page.width, item["x1"]), min(page.height, item["bottom"])
        if x1 > x0 and y1 > y0:
            box = [x0/page.width, y0/page.height, x1/page.width, y1/page.height]
            region = {"bbox": box, "kind": "raster"}
            # Include masks and image metadata: identical compressed streams alone
            # do not necessarily represent the same visible image.
            try:
                from pdfminer.pdftypes import resolve1
                stream = resolve1(item.get("stream"))
                digest = hashlib.sha256(stream.get_data())
                for key in ("Width", "Height", "BitsPerComponent", "ColorSpace", "Decode", "ImageMask", "Mask", "SMask"):
                    value = resolve1(stream.attrs.get(key))
                    digest.update(key.encode())
                    digest.update(value.get_data() if hasattr(value, "get_data") else repr(value).encode())
                region["imageHash"] = digest.hexdigest()
            except (AttributeError, TypeError, ValueError, KeyError):
                pass  # Unknown identity is never deduplicated.
            # Co-located, distinct streams must stay separate. Do not change the
            # identity or index of duplicates already present in v2 documents.
            if not any(all(abs(a-b) < .004 for a,b in zip(box, old["bbox"]))
                       and region.get("imageHash") and region.get("imageHash") == old.get("imageHash")
                       for old in regions):
                regions.append(region)
    return regions


def table_regions(page):
    """Detect ruled PDF tables; their text and lines may have no raster image object."""
    try:
        if not 4 <= len(page.edges) <= 2000:
            return []
        regions = []
        for table in page.find_tables(table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}):
            if len(table.cells) < 4:
                continue
            x0, y0, x1, y1 = table.bbox
            box = [max(0, x0 / page.width), max(0, y0 / page.height),
                   min(1, x1 / page.width), min(1, y1 / page.height)]
            if box[2] - box[0] >= .07 and box[3] - box[1] >= .04:
                regions.append({"bbox": box, "kind": "table"})
        return regions
    except (ValueError, TypeError, AttributeError):
        return []


def text_regions(page, textmap=None):
    """Group positioned PDF text lines into conservative paragraph-sized crop targets."""
    try:
        lines = (textmap.extract_text_lines(return_chars=False) if textmap is not None
                 else page.extract_text_lines(return_chars=False))
    except (ValueError, TypeError, AttributeError):
        return []
    groups = []
    for line in sorted(lines, key=lambda item: (item["top"], item["x0"])):
        if not line.get("text", "").strip():
            continue
        width, height = line["x1"] - line["x0"], line["bottom"] - line["top"]
        if width < 20 or height < 3:
            continue
        matching = None
        for group in reversed(groups):
            gap = line["top"] - group["bottom"]
            overlap = min(line["x1"], group["x1"]) - max(line["x0"], group["x0"])
            if (0 <= gap <= max(10, group["lineHeight"] * 1.1) and
                    overlap >= min(width, group["x1"] - group["x0"]) * .45 and
                    abs(line["x0"] - group["leftEdge"]) <= 40 and
                    .65 <= height / group["lineHeight"] <= 1.5):
                matching = group
                break
        if matching is None:
            groups.append({"x0": line["x0"], "top": line["top"], "x1": line["x1"],
                           "bottom": line["bottom"], "leftEdge": line["x0"],
                           "lineHeight": height, "text": line["text"]})
        else:
            matching["x0"] = min(matching["x0"], line["x0"])
            matching["x1"] = max(matching["x1"], line["x1"])
            matching["bottom"] = max(matching["bottom"], line["bottom"])
            matching["text"] += "\n" + line["text"]
    return [{"bbox": [max(0, group["x0"] / page.width), max(0, group["top"] / page.height),
                     min(1, group["x1"] / page.width), min(1, group["bottom"] / page.height)],
             "kind": "text", "text": group["text"][:700]} for group in groups
            if group["bottom"] <= page.height and group["x1"] <= page.width]


def enrich_layout_regions(document, source):
    need_tables = document.get("tableRegionsVersion") != 1
    need_text = document.get("textRegionsVersion") != 1
    if not (need_tables or need_text):
        return False
    import pdfplumber
    with pdfplumber.open(source) as pdf:
        for saved, page in zip(document["pages"], pdf.pages):
            if need_tables:
                saved["tableRegions"] = table_regions(page)
            if need_text:
                saved["textRegions"] = text_regions(page, repaired_textmap(page)[0])
            page.close()
    document["tableRegionsVersion"] = 1
    document["textRegionsVersion"] = 1
    return True


def deduplicated_pdf_chars(chars):
    """Collapse overprinted glyphs without merging different fonts or nearby symbols."""
    from pdfplumber.utils import dedupe_chars
    return dedupe_chars(chars, tolerance=.3, extra_attrs=("fontname", "size"))


def repaired_textmap(page):
    """Keep PDF layout while repairing repeated overlays and legacy equation glyphs."""
    from pdfplumber.utils import chars_to_textmap

    unique_chars = deduplicated_pdf_chars(page.chars)
    chars, repair = repair_chars(unique_chars)
    chars, symbol_count = repair_symbol_chars(chars)
    repair["symbolBulletGlyphs"] = symbol_count
    repair["replacedGlyphs"] += symbol_count
    repair["deduplicatedGlyphs"] = len(page.chars) - len(unique_chars)
    if not repair["replacedGlyphs"] and not repair["deduplicatedGlyphs"]:
        return None, chars, repair
    return chars_to_textmap(chars, layout_bbox=page.bbox), chars, repair


def enrich_image_regions(document, source):
    """Upgrade old extraction caches without rerunning OCR or MarkItDown."""
    if document.get("imageRegionsVersion") == 2:
        return False
    import pdfplumber
    with pdfplumber.open(source) as pdf:
        for saved, page in zip(document["pages"], pdf.pages):
            saved["imageRegions"] = image_regions(page)
    document["imageRegionsVersion"] = 2
    return True


def classify_visual_page(data, image_coverage):
    """Conservative local routing hint; it never claims to understand an image."""
    native = len(re.sub(r"\s", "", data.get("nativeText", "")))
    ocr = "\n".join(block.get("text", "") for block in data.get("ocrBlocks", []))
    recognized = len(re.sub(r"\s", "", ocr))
    mode = "image_only" if native < 20 and image_coverage >= .6 else (
        "mixed" if data.get("ocrNeeded") else "text")
    if native < 20 and not data.get("ocrNeeded"):
        mode = "empty"
    combined = data.get("nativeText", "") + "\n" + ocr
    visual_terms = re.search(
        r"그림|도식|도표|그래프|다이어그램|화살표|지렛대|레버|모멘트|"
        r"figure\s*\d|fig\.?\s*\d|diagram|graph|plot|lever|fulcrum|torque|flowchart",
        combined, flags=re.IGNORECASE)
    reasons = []
    if mode == "image_only" and recognized < 80:
        reasons.append("이미지형 페이지에서 인식한 글자가 적어 그림 내용을 놓쳤을 수 있음")
    if data.get("ocrNeeded") and visual_terms:
        reasons.append("그림·도식·그래프를 가리키는 표현이 있어 배치와 관계 확인 필요")
    if data.get("ocrNeeded") and any(word in combined for word in ("→", "←", "↑", "↓", "∑", "∫")):
        reasons.append("방향 또는 수식 기호가 있어 원본 대조 필요")
    return {"contentMode": mode, "imageCoverage": round(image_coverage, 3),
            "visualReview": {"recommended": bool(reasons), "reasons": reasons,
                             "status": "not_analyzed" if reasons else "not_required"}}


def enrich_visual_routing(document):
    changed = document.get("visualRoutingVersion") != VISUAL_ROUTING_VERSION
    for page in document["pages"]:
        page["ocrBlocks"] = []
        page["ocrNeeded"] = False
        page["warnings"] = [w for w in page.get("warnings", []) if "OCR" not in w]
        has_text = bool((page.get("nativeText") or page.get("markdown") or "").strip())
        page["textState"] = "failed" if page.get("status") == "failed" else "ready" if has_text else "no_text_detected"
        page["status"] = "failed" if page.get("status") == "failed" else "ready"
        page["contentMode"] = "mixed" if has_text and page.get("imageRegions") else "text" if has_text else "image_only"
        page["visualReview"] = {"recommended": True, "reasons": ["페이지 전체 시각 분석 대상"]}
    document["chunks"] = [c for c in document.get("chunks", []) if c.get("source") != "ocr"]
    document["visualReviewPages"] = [p["number"] for p in document["pages"]]
    document["visualOnlyPages"] = [p["number"] for p in document["pages"] if p["textState"] == "no_text_detected"]
    document["incompletePages"] = [p["number"] for p in document["pages"] if p["status"] != "ready"]
    document["qualityReviewPages"] = [p["number"] for p in document["pages"] if p.get("warnings")]
    document["visualRoutingVersion"] = VISUAL_ROUTING_VERSION
    document["ocrDisabled"] = True
    return changed


def prepare(folder: Path, retry=False):
    import pdfplumber
    from pypdf import PdfReader

    source = folder / "source.pdf"
    document_id = digest_file(source)
    fingerprint = VERSION + ";" + ";".join(f"{x}={importlib.metadata.version(x)}" for x in
        ("pypdf", "pdfplumber", "pypdfium2")) + ";no-ocr"
    cache_file = folder / "document.json"
    if cache_file.exists() and not retry:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint and cached.get("documentId") == document_id:
            changed = enrich_visual_routing(cached)
            changed |= enrich_image_regions(cached, source)
            changed |= enrich_layout_regions(cached, source)
            changed |= ensure_region_catalog(cached)
            if changed:
                write_json(cache_file, cached)
            emit("complete", cached=True, path=str(cache_file), pages=len(cached["pages"]))
            return cached
    legacy_fingerprints = []
    if cache_file.exists():
        old = json.loads(cache_file.read_text(encoding="utf-8"))
        if old.get("documentId") == document_id:
            legacy_fingerprints = list(dict.fromkeys([old.get("fingerprint", ""), *old.get("legacySourceFingerprints", [])]))
            backup = folder / "legacy-extraction" / (hashlib.sha256(old.get("fingerprint", "").encode()).hexdigest()+".json")
            if not backup.exists():
                write_json(backup, old)
    reader = PdfReader(source)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("암호로 보호된 PDF입니다. 암호를 해제한 사본을 사용하세요.")
    pages = []
    labels = reader.page_labels
    (folder / "pages").mkdir(exist_ok=True)
    with pdfplumber.open(source) as pdf:
        for index, page in enumerate(pdf.pages):
            check_cancel(folder)
            emit("progress", page=index+1, total=len(pdf.pages), stage="PDF 글자 직접 추출")
            page_file = folder / "pages" / f"{index+1:05}.json"
            cached = json.loads(page_file.read_text(encoding="utf-8")) if page_file.exists() else None
            if cached and cached.get("fingerprint") == fingerprint and cached.get("documentId") == document_id and cached.get("status") == "ready":
                if "tableRegions" not in cached or "textRegions" not in cached:
                    if "tableRegions" not in cached:
                        cached["tableRegions"] = table_regions(page)
                    if "textRegions" not in cached:
                        cached["textRegions"] = text_regions(page, repaired_textmap(page)[0])
                    write_json(page_file, cached)
                pages.append(cached)
                continue
            data = {"number": index+1, "documentId": document_id, "fingerprint": fingerprint,
                "label": labels[index], "printedPageNumber": None, "width": page.width,
                "height": page.height, "nativeText": "", "markdown": "", "ocrBlocks": [],
                "words": [], "warnings": [], "status": "ready"}
            try:
                textmap, chars, repair = repaired_textmap(page)
                data["nativeText"] = (textmap.as_string if textmap is not None
                                      else page.extract_text()) or ""
                if repair["replacedGlyphs"] or repair["unresolvedGlyphs"] or repair["deduplicatedGlyphs"]:
                    data["fontRepair"] = repair
                if repair["unresolvedGlyphs"]:
                    data["warnings"].append("수식 폰트 일부 글자를 복원하지 못했습니다 · 원본 대조 필요")
                # The preview is direct extraction. The MarkItDown comparison runs only
                # after the user approves the two paid analysis/generation passes.
                data["markdown"] = data["nativeText"]
                data["imageRegions"] = image_regions(page)
                data["tableRegions"] = table_regions(page)
                data["textRegions"] = text_regions(page, textmap)
                words = (page.extract_words() if textmap is None
                         else pdfplumber.utils.extract_words(chars))
                data["words"] = [{"text": w["text"], "bbox": [w["x0"]/page.width,
                    w["top"]/page.height, w["x1"]/page.width, w["bottom"]/page.height]}
                    for w in words]
                # Flag obvious side-by-side text; this is a warning, not a column reconstruction algorithm.
                rows = {}
                for word in data["words"]:
                    rows.setdefault(round(word["bbox"][1]*page.height/5), []).append(word["bbox"])
                gap_rows = 0
                for row in rows.values():
                    ordered = sorted(row)
                    if any(b[0]-a[2] > .12 for a,b in zip(ordered,ordered[1:])):
                        gap_rows += 1
                if gap_rows >= 2:
                    data["warnings"].append("다단/표 배치 가능성 · 추출된 읽기 순서와 열 관계 확인 필요")
                data["ocrNeeded"] = False
            except InterruptedError:
                raise
            except Exception:
                data["status"] = "failed"
                data["warnings"].append("페이지 추출 실패 · PDF 원본은 계속 볼 수 있습니다")
            write_json(page_file, data)
            pages.append(data)
            page.close()  # Release pdfminer layout caches between pages of long documents.
    chunks = make_chunks(document_id, pages)
    result = {"schemaVersion": 1, "fingerprint": fingerprint, "documentId": document_id,
        "pages": pages, "chunks": chunks, "incompletePages": [p["number"] for p in pages if p["status"] != "ready"],
        "pageAnalysisStates": [{"page": p["number"], "state": "pending", "analyzed": 0, "complete": 0} for p in pages],
        "pageAnalysisIncompletePages": [p["number"] for p in pages],
        "qualityReviewPages": [p["number"] for p in pages if p["warnings"]],
        "lectureLinks": [], "generated": False, "legacySourceFingerprints": legacy_fingerprints}
    enrich_visual_routing(result)
    enrich_image_regions(result, source)
    result["tableRegionsVersion"] = 1
    result["textRegionsVersion"] = 1
    ensure_region_catalog(result)
    write_json(cache_file, result)
    md = []
    for page in pages:
        md.append(f"\n## PDF page {page['number']} (label: {page['label']})\n\n{page['markdown']}")
    (folder / "document.md").write_text("\n".join(md), encoding="utf-8")
    emit("complete", cached=False, path=str(cache_file), pages=len(pages))
    return result


STOP = {"설명", "설명해줘", "알려줘", "무엇", "뭐야", "이거", "그거", "하는", "대한", "어떻게", "왜", "the", "what", "is", "explain", "please"}

# Apply the same normalization to questions and PDF text. Keep this independent
# of any provider: retrieval and intent planning must never incur API charges.
SEARCH_FILLER = {"필요", "있어", "있나요", "있을까", "있다", "없어", "알", "알아야", "알려", "좀",
                 "해줘", "해주세요", "해봐", "검색", "검색해", "검색해줘", "찾아줘", "뭐지", "뭘까",
                 "무슨", "어떤", "대해", "관해", "그리고", "그럼", "그러면", "여기", "여기서"}
SEARCH_SUFFIXES = ("에서는", "으로는", "에서", "으로", "에게", "까지", "부터", "이란", "라는",
                   "을", "를", "은", "는", "이", "가", "의", "도")


def search_words(text):
    for word in re.findall(r"[가-힣]+|[a-z0-9_+]+", text.lower()):
        if word in STOP or word in SEARCH_FILLER or len(word) < 2:
            continue
        # Question endings can be attached without spaces: 의의는뭐지?
        word = re.sub(r"(?:은|는|이|가)?(?:뭐지|뭐야|뭘까|무엇인가요|무엇인지)$", "", word)
        for suffix in SEARCH_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 2:
                word = word[:-len(suffix)]
                break
        if len(word) >= 2 and word not in STOP and word not in SEARCH_FILLER:
            yield word


def terms(text):
    result = []
    for word in search_words(text):
        result.append(word)
        if re.search(r"[가-힣]", word) and len(word) > 2:
            result.extend(word[i:i+2] for i in range(len(word)-1))
    return result


def query_terms(question):
    """Favor the subject over common words and Korean question endings."""
    weighted = {}
    subject_index = 0
    for word in search_words(question):
        emphasis = 2.5 if subject_index == 0 else 1.0
        subject_index += 1
        variants = [word]
        for term in variants:
            weighted[term] = max(weighted.get(term, 0), emphasis * (1.0 + min(len(term), 6) * .35))
            if re.search(r"[가-힣]", term) and len(term) > 2:
                for offset in range(len(term)-1):
                    bigram = term[offset:offset+2]
                    weighted[bigram] = max(weighted.get(bigram, 0), .18 * emphasis)
    return weighted


def retrieve(document, question, limit=8, context_bytes=MAX_CONTEXT_BYTES):
    query = query_terms(question)
    if not query:
        return []
    chunks = [c for c in document["chunks"] if c.get("source") != "ocr"]
    termsets = [Counter(terms(c["text"])) for c in chunks]
    average = sum(sum(c.values()) for c in termsets) / max(1,len(termsets))
    frequencies = Counter(t for values in termsets for t in values)
    scored = []
    for chunk, values in zip(chunks, termsets):
        size = sum(values.values())
        score = 0.0
        for term, weight in query.items():
            tf = values[term]
            idf = math.log(1 + (len(chunks)-frequencies[term]+.5)/(frequencies[term]+.5))
            score += weight * idf * tf * 2.2 / (tf + 1.2*(.25+.75*size/max(1,average)))
        if score > 0:
            scored.append((score, chunk))
    results, used, spans = [], 0, []
    for score, chunk in sorted(scored, key=lambda x:x[0], reverse=True):
        if any(c["page"]==chunk["page"] and c["field"]==chunk["field"] and
               min(c["end"],chunk["end"])-max(c["start"],chunk["start"]) > min(c["end"]-c["start"],chunk["end"]-chunk["start"])*.5 for c in spans):
            continue
        result = {**chunk, "score": round(score, 4)}
        cost = len(json.dumps(result, ensure_ascii=False).encode("utf-8")) + 2
        if used + cost > context_bytes:
            continue
        results.append(result)
        spans.append(chunk)
        used += cost
        if len(results) >= limit:
            break
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "search"])
    parser.add_argument("--folder", required=True, type=io_path)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--question-file", type=io_path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.folder.resolve(), args.retry)
    else:
        document = json.loads((args.folder / "document.json").read_text(encoding="utf-8"))
        request = json.loads(args.question_file.read_text(encoding="utf-8"))
        emit("search", hits=retrieve(document, request["question"]))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except InterruptedError as error:
        emit("cancelled", message=str(error))
        sys.exit(2)
    except Exception as error:
        emit("error", message="PDF 처리 실패: " + type(error).__name__)
        sys.exit(1)
