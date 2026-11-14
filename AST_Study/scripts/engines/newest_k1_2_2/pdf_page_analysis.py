"""Page-scoped visual reading. One request per uncached page; no OCR engines."""
from __future__ import annotations
import base64
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import math
import re
import threading
from pathlib import Path

from pdf_guard import SECURITY_POLICY
from pdf_output_language import STRICT_KOREAN_RETRY, analysis_issues
from pdf_pipeline import check_cancel, emit, write_json, CHUNK_CHARS

VERSION = "page-vision-v1"
VALIDATION_VERSION = 4
MAX_OUTPUT = 40000  # ~14% of GPT-6 Luna's 128K maximum output.
MAX_SIDE = 2800
VISION_WORKERS = 15
_RENDER_LOCK = threading.Lock()
KINDS = {"text", "formula", "table", "diagram", "graph", "code", "example", "problem", "solution", "contents", "decoration", "other"}
LENS_REASONS = {"none", "diagram_relation", "layout", "annotation", "unreadable"}
SYSTEM = SECURITY_POLICY + r"""
You inspect ONE complete university lecture page, returning Korean JSON. No OCR engine is used.
The image is the current source; nativeText and previousContext are aids, not unquestionable truth.
Find ALL educational elements, including unnumbered examples, conditions, formulas, diagrams,
tables, code and spatial text layouts. First inventory elements, then analyze every inventory key.
Classify navigation-only tables of contents and lists of upcoming topics as kind=contents.
Classify an example embedded in concept teaching as kind=example; classify standalone practice
questions and their answer walkthroughs as kind=problem or kind=solution.
Do not spend the answer on one prominent element and omit others. Two elements called A and B
are only an example: this rule applies to every count and labeling style, including no labels.
Group raster fragments and vector lines into semantic units. Local image boxes are hints, not
boundaries. Decorative logos may be omitted from teaching content but not from inventory.
Every supplied native anchor must appear in an inventory entry's anchorIds. This is a coverage
check, not a claim that all image-only elements have been independently verified.
Keep each element's own conditions, numbers, variables and conclusions. Copy missing or damaged
text without translating it in transcription. For clean native text, transcription can be empty;
use anchorIds to link it. Describe visual relationships in description/relationships. Purpose is
an inference, never the professor's confirmed intention. Previous-page claims are background only.
Read ALL formulas as LaTeX preserving subscripts, powers, signs, units and derivation steps.
Do not silently repair source errors, invent illegible symbols or replace a formula by a screenshot.
Return each formula separately, even when mathematically equivalent steps occur in a derivation.
Code transcription preserves case, punctuation and indentation. Unreadable elements still need
an entry with status=unreadable and specific uncertainDetails; set coverage=partial.
Check inventory against elements before answering. Do not drop elements to shorten the response.
Include axes, legends, labels and connectors in a semantic region. All bbox coordinates are
fractions [left,top,right,bottom] in the supplied full-page image, origin at its top left. Use null
if uncertain about location. A valid box is not proof of accuracy.
Return this JSON shape (keys are temporary identifiers, not page numbers):
{inventory:[{key:string,kind:string,label:string,anchorIds:[string]}],
 elements:[{key:string,title:string,kind:string,bbox:[number,number,number,number]|null,
 transcription:string,formulas:[{latex:string,uncertainSymbols:string}],description:string,
  relationships:[string],purpose:string,uncertainDetails:[string],status:"complete"|"unreadable"}],
 coverage:"complete"|"partial",contextSummary:string}
kind is text, formula, table, diagram, graph, code, example, problem, solution, contents, decoration or other.
No HTML or external links. Use empty arrays where appropriate. Do not output a study summary.
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def native(page):
    return page.get("markdown") or page.get("nativeText") or ""


def anchors(page):
    return [{"id": f"t{i}", "bbox": r["bbox"], "text": r.get("text", "")}
            for i, r in enumerate(page.get("textRegions", [])) if r.get("text", "").strip()]


def key_for(document, number):
    # Includes preceding native context; cached partial pages are immutable until explicit reanalysis.
    return digest([VERSION, SYSTEM, MAX_SIDE, MAX_OUTPUT, document["documentId"], number,
                   [(native(p), anchors(p)) for p in document["pages"][max(0, number-4):number]]])


def summary_cache(folder, document, model, scope, page, targets, prompt_version):
    return Path(folder) / "generated" / digest([prompt_version, model, scope, page,
                                               [key_for(document, n) for n in targets]])


def cache_path(folder, document, number):
    return Path(folder) / "generated" / "page-analysis" / (key_for(document, number) + ".json")


def read_cached(folder, document, number):
    try:
        value = json.loads(cache_path(folder, document, number).read_text(encoding="utf-8"))
        if (isinstance(value, dict) and isinstance(value.get("elements"), list)
                and all(isinstance(e, dict) for e in value["elements"])
                and isinstance(value.get("inventory"), list)
                and value.get("inputKey") == key_for(document, number) and value.get("page") == number
                and not analysis_issues(value, native(document["pages"][number-1]))):
            return value
    except (OSError, ValueError, TypeError):
        pass
    return None


def valid_box(box):
    return (isinstance(box, list) and len(box) == 4 and
            all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)


def padded_box(box, words=()):
    if not valid_box(box):
        return [0., 0., 1., 1.], "full_page"
    expanded = [max(0., box[0]-.01), max(0., box[1]-.01), min(1., box[2]+.01), min(1., box[3]+.01)]
    # Only snap nearby native words, never large backgrounds or arbitrarily distant objects.
    for word in words:
        b = word.get("bbox")
        if not valid_box(b) or (b[2]-b[0])*(b[3]-b[1]) > .025:
            continue
        if b[0] < expanded[2] and b[2] > expanded[0] and b[1] < expanded[3] and b[3] > expanded[1]:
            if all(abs(x-y) <= .025 for x, y in zip(
                    [min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3])], box)):
                expanded = [min(expanded[0], b[0]), min(expanded[1], b[1]),
                            max(expanded[2], b[2]), max(expanded[3], b[3])]
    return expanded, "padded"


def refine_box(box, regions):
    """Include partially cut small objects near an already padded semantic boundary.
    Call only after confirming unrotated, zero-origin MediaBox==CropBox geometry.
    Never grow transitively along chains of neighboring objects or include backgrounds.
    """
    expanded = list(box)
    for region in regions:
        b = region.get("bbox")
        if not valid_box(b):
            continue
        area=(b[2]-b[0])*(b[3]-b[1])
        overlap=max(0,min(b[2],box[2])-max(b[0],box[0]))*max(0,min(b[3],box[3])-max(b[1],box[1]))
        union=[min(box[0],b[0]),min(box[1],b[1]),max(box[2],b[2]),max(box[3],b[3])]
        if area<=.12 and overlap>=area*.5 and all(abs(x-y)<=.04 for x,y in zip(union,box)):
            expanded=[min(expanded[0],b[0]),min(expanded[1],b[1]),max(expanded[2],b[2]),max(expanded[3],b[3])]
    if expanded!=box:
        expanded=[max(0,expanded[0]-.005),max(0,expanded[1]-.005),min(1,expanded[2]+.005),min(1,expanded[3]+.005)]
    return expanded


def frame_compatible(folder, number):
    # This also calls PDFium and can overlap an in-flight page render.
    with _RENDER_LOCK:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(Path(folder)/"source.pdf") as pdf:
            page=pdf[number-1]
            try:
                media=page.get_mediabox();crop=page.get_cropbox()
                return page.get_rotation()==0 and abs(media[0])+abs(media[1])<.01 and all(abs(a-b)<.01 for a,b in zip(media,crop))
            finally:page.close()


def benign_native_anchor(anchor, elements):
    """A missed PDF text fragment is not proof that the image was read partially."""
    box = anchor.get("bbox")
    if not valid_box(box):
        return False
    text = anchor.get("text", "").strip()
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    narrow_line = box[3] - box[1] < .035
    # Two-up slides have headers and footers at the physical page's midpoint too.
    if narrow_line and box[2] - box[0] > .6 and (center[1] < .07 or center[1] > .93 or .45 < center[1] < .55):
        return True
    if re.fullmatch(r"\([^)]{1,20}\)", text):
        # A short parenthesized section label such as "(다른 풀이)" can sit just
        # above the formula it introduces. It is layout, not a missing rule.
        if any(e["kind"] != "decoration" and e["status"] == "complete" and
               abs(e["bbox"][1] - box[3]) <= .05 and
               e["bbox"][0] - .05 <= center[0] <= e["bbox"][2] + .05
               for e in elements):
            return True
    for element in elements:
        if element["kind"] == "decoration" or element["status"] != "complete":
            continue
        area = element["bbox"]
        if not (area[0] <= center[0] <= area[2] and area[1] <= center[1] <= area[3]):
            continue
        content = " ".join([element["title"], element["transcription"], element["description"],
                            *(formula["latex"] for formula in element["formulas"])])
        if not content.strip():
            continue
        if re.search(r"[가-힣]", text):
            compact = re.sub(r"\s+", "", text)
            if len(compact) >= 4 and compact in re.sub(r"\s+", "", content):
                return True
            continue
        math_name = re.match(r"(?:sin|cos|tan|sec|csc|cot)[mn]?\b", text, re.I)
        if len(text) <= 80 and (not re.search(r"[A-Za-z]{4,}", text) or math_name):
            return True
    # Tiny formula glyphs can sit just beyond a model's semantic box.
    if not re.search(r"[가-힣]", text) and len(text) <= 12 and (
            re.search(r"[∫√/±=+−^²³]", text) or
            re.match(r"(?:sin|cos|tan|sec|csc|cot)[mn]?\b", text, re.I)):
        return any(e["kind"] != "decoration" and e["status"] == "complete" and
                   e["bbox"][0] - .08 <= center[0] <= e["bbox"][2] + .08 and
                   e["bbox"][1] - .08 <= center[1] <= e["bbox"][3] + .08
                   for e in elements)
    return False


def validate(value, page, input_key):
    if not isinstance(value, dict) or not isinstance(value.get("inventory"), list) or not isinstance(value.get("elements"), list):
        raise ValueError("페이지 요소 목록의 형식을 확인할 수 없습니다.")
    if value.get("coverage") not in {"complete", "partial"} or not isinstance(value.get("contextSummary"), str):
        raise ValueError("페이지 분석 완료 상태가 없습니다.")
    inventory, positions, records, issues, warnings = {}, {}, {}, [], []
    available = {a["id"]: a for a in anchors(page)}
    covered = set()
    for position, item in enumerate(value["inventory"]):
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"] or item["key"] in inventory:
            issues.append(f"inventory:{position}:invalid_key")
            continue
        if item.get("kind") not in KINDS or not isinstance(item.get("label"), str) or not isinstance(item.get("anchorIds"), list):
            issues.append(f"inventory:{position}:invalid_shape")
            continue
        ids = item["anchorIds"]
        if any(not isinstance(a, str) or a not in available for a in ids):
            issues.append(f"inventory:{position}:invalid_anchor")
            continue
        covered.update(ids)
        inventory[item["key"]] = {**item, "anchorIds": list(ids)}
        positions[item["key"]] = position
    for position, element in enumerate(value["elements"]):
        if not isinstance(element, dict) or element.get("key") not in inventory or element["key"] in records:
            issues.append(f"element:{position}:invalid_key")
            continue
        listed = inventory[element["key"]]
        listed_kind, detail_kind = listed["kind"], element.get("kind")
        if detail_kind != listed_kind:
            box = element.get("bbox")
            # A numbered footer is page furniture even if the model called it
            # text in the inventory. This narrow layout check avoids discarding
            # every teaching element over a harmless classification slip.
            numbered_footer = (set((listed_kind, detail_kind)) == {"text", "decoration"}
                and not listed["anchorIds"] and valid_box(box) and box[1] >= .85
                and box[2] - box[0] <= .15
                and isinstance(element.get("transcription"), str)
                and re.fullmatch(r"\d{1,6}", element["transcription"].strip()))
            if (listed.get("role") == "teaching" and
                    listed_kind not in {"contents", "problem", "solution", "decoration"} and
                    detail_kind in KINDS - {"contents", "problem", "solution", "decoration"}):
                resolved_kind = detail_kind
                warnings.append(f"inventory:{element['key']}:teaching_kind_resolved")
            elif {listed_kind, detail_kind} == {"code", "example"}:
                # A worked code snippet can be inventoried as code and then
                # described as an example without losing any source content.
                resolved_kind = "code"
            elif numbered_footer:
                resolved_kind = "decoration"
            else:
                issues.append(f"inventory:{element['key']}:kind_mismatch")
                # When the disagreement could hide teaching material as navigation
                # or practice, retain it for review instead of silently excluding it.
                excluded = {"contents", "problem", "solution", "decoration"}
                resolved_kind = (listed_kind if listed_kind not in excluded else detail_kind
                                 if detail_kind in KINDS and detail_kind not in excluded else
                                 detail_kind if detail_kind in KINDS else listed_kind)
            listed["kind"] = resolved_kind
        if any(not isinstance(element.get(k), str) for k in ("title", "transcription", "description", "purpose")):
            issues.append(f"element:{position}:invalid_text")
            continue
        if any(not isinstance(element.get(k), list) or any(not isinstance(x, str) for x in element[k])
               for k in ("relationships", "uncertainDetails")):
            issues.append(f"element:{position}:invalid_relations")
            continue
        if not isinstance(element.get("formulas"), list) or any(not isinstance(f, dict) or
                not isinstance(f.get("latex"), str) or not isinstance(f.get("uncertainSymbols"), str) for f in element["formulas"]):
            issues.append(f"element:{position}:invalid_formulas")
            continue
        if element.get("status") not in {"complete", "unreadable"}:
            issues.append(f"element:{position}:invalid_status")
            continue
        item = {k: element[k] for k in ("title", "transcription", "description", "purpose", "relationships", "uncertainDetails", "formulas", "status")}
        item["kind"] = listed["kind"]
        # Keep the stored SlideLens contract compatible without requesting it from Luna.
        item["lensReason"] = element.get("lensReason", "none") if element.get("lensReason") in LENS_REASONS else "none"
        # IDs use the immutable input + inventory position; bbox refinements do not change identity.
        pos = positions[element["key"]]
        item["elementId"] = f"pv1-p{page['number']}-{input_key[:12]}-e{pos}"
        item["anchorIds"] = listed["anchorIds"]
        # Native geometry can use a different crop frame. Padding is safe; snapping is opt-in only.
        item["bbox"], item["locationState"] = padded_box(element.get("bbox"))
        if item["kind"] == "formula" and item["lensReason"] not in {"annotation", "unreadable"}:
            item["lensReason"] = "none"
        if item["kind"] in {"text", "code", "decoration"} and item["lensReason"] not in {"annotation", "layout", "unreadable"}:
            item["lensReason"] = "none"
        if item["status"] == "unreadable":
            target = warnings if item["kind"] in {"problem", "solution", "contents", "decoration"} else issues
            target.append(f"element:{item['elementId']}:unreadable")
        elif any(f["uncertainSymbols"] for f in item["formulas"]):
            # A fully read slide can still contain an ambiguous or inconsistent
            # printed expression. Preserve that qualification without calling
            # the whole page unread.
            warnings.append(f"element:{item['elementId']}:formula_uncertain")
        if item["status"] == "complete" and item["uncertainDetails"]:
            warnings.append(f"element:{item['elementId']}:source_uncertain")
        if item["kind"] == "formula" and not item["formulas"]:
            issues.append(f"element:{item['elementId']}:missing_formula")
        if item["kind"] != "decoration" and not any((item["transcription"], item["description"], item["formulas"], item["anchorIds"])):
            issues.append(f"element:{item['elementId']}:empty")
        records[element["key"]] = item
    for key, listed in inventory.items():
        if key in records:
            continue
        if listed.get("role") == "decoration" or listed["kind"] == "decoration":
            boxes = [available[a]["bbox"] for a in listed["anchorIds"] if valid_box(available[a]["bbox"])]
            box = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None)
            padded, location = padded_box(box)
            records[key] = {"elementId": f"pv1-p{page['number']}-{input_key[:12]}-e{positions[key]}",
                            "title": listed["label"], "kind": "decoration", "bbox": padded,
                            "locationState": location, "lensReason": "none", "anchorIds": listed["anchorIds"],
                            "transcription": "", "description": "", "purpose": "", "relationships": [],
                            "uncertainDetails": [], "formulas": [], "status": "complete"}
            warnings.append(f"inventory:{key}:decorative_detail_inferred")
        else:
            issues.append(f"inventory:{key}:missing")
    # Native extraction sometimes splits tiny axis labels from the diagram that
    # the visual reader already described. Associate only short labels whose
    # tokens are all stated by one nearby, complete diagram; keep every other
    # missing anchor as a real coverage issue.
    for anchor_id, anchor in available.items():
        if anchor_id in covered:
            continue
        label = anchor.get("text", "").strip()
        tokens = re.findall(r"[A-Za-z0-9]+", label)
        box = anchor.get("bbox")
        if len(label) > 8 or not 1 <= len(tokens) <= 3 or not valid_box(box):
            continue
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        matches = []
        for key, element in records.items():
            region = element["bbox"]
            if element["kind"] not in {"diagram", "graph"} or element["status"] != "complete":
                continue
            if not (region[0] - .12 <= center[0] <= region[2] + .12 and
                    region[1] - .12 <= center[1] <= region[3] + .12):
                continue
            description = (element["title"] + " " + element["description"] + " " + element["transcription"]).lower()
            if all(re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", description)
                   for token in tokens):
                matches.append(key)
        if len(matches) == 1:
            inventory[matches[0]]["anchorIds"].append(anchor_id)
            covered.add(anchor_id)
    for anchor_id, anchor in available.items():
        if anchor_id not in covered:
            target = warnings if benign_native_anchor(anchor, records.values()) else issues
            target.append(f"anchor:{anchor_id}:missing")
    if not inventory:
        issues.append("empty_inventory")
    if value["coverage"] == "partial":
        unreadable = [element for element in records.values() if element["status"] == "unreadable"]
        if (unreadable and not issues and
                all(element["kind"] in {"problem", "solution", "contents", "decoration"}
                    for element in unreadable)):
            warnings.append("practice_or_navigation_unreadable")
        else:
            issues.append("model_reported_partial")
    return {"inventory": list(inventory.values()), "elements": list(records.values()),
            "contextSummary": value["contextSummary"], "issues": issues, "warnings": warnings,
            "status": "partial" if issues else "ready"}


def render_page(folder, number):
    # PDFium's native renderer may terminate the whole Python process when
    # several documents are rendered concurrently. Keep API I/O parallel, but
    # serialize this short local rendering step.
    with _RENDER_LOCK:
        return _render_page_locked(folder, number)


def _render_page_locked(folder, number):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(Path(folder) / "source.pdf") as pdf:
        page = pdf[number-1]
        try:
            width, height = page.get_size()
            bitmap = page.render(scale=min(4., MAX_SIDE/max(width, height)))
            try:
                picture = bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            page.close()
    try:
        with io.BytesIO() as out:
            picture.save(out, format="PNG")
            raw = out.getvalue()
        return {"data": "data:image/png;base64,"+base64.b64encode(raw).decode("ascii"),
                "width": picture.width, "height": picture.height, "bytes": len(raw), "detail": "high"}
    finally:
        picture.close()


def element_text(element):
    parts = [element["transcription"]]
    for formula in element["formulas"]:
        parts.append("$$\n"+formula["latex"]+"\n$$")
        if formula["uncertainSymbols"]:
            parts.append("판독 확인 필요: "+formula["uncertainSymbols"])
    return "\n\n".join(p for p in parts if p.strip())


def analysis_states(document):
    """Report the reading stored with this PDF, even after a prompt update.

    inputKey also hashes the current prompt. Changing that prompt must not turn
    an already stored reading into a fictitious pending page in the UI.
    """
    states = []
    for number, page in enumerate(document["pages"], 1):
        result = page.get("pageAnalysis", {})
        if not isinstance(result, dict):
            result = {}
        valid = (result.get("version") == VERSION and
                 result.get("documentId") == document["documentId"] and
                 result.get("page") == number)
        state = result.get("status") if valid and result.get("status") in {"ready", "partial"} else "pending"
        states.append({"page": number, "state": state, "analyzed": int(state != "pending"),
                       "complete": int(state == "ready")})
    return states


def apply_result(document, result, compatible_frame=False):
    number = result["page"]
    page = document["pages"][number-1]
    page["pageAnalysis"] = result
    regions = [r for r in page.get("slideLensRegions", []) if r.get("origin") != VERSION]
    document["chunks"] = [c for c in document.get("chunks", []) if c.get("source") != "ocr" and
                          not (c["page"] == number and c.get("pageVision"))]
    for e in result.get("elements", []):
        if e["kind"] == "decoration":
            continue
        anchor_texts = ["".join(a["text"].split()) for a in anchors(page) if a["id"] in e["anchorIds"]]
        native_support = [c["id"] for c in document["chunks"] if c["page"] == number and c.get("source") == "native"
                          and any(t and t in "".join(c["text"].split()) for t in anchor_texts)]
        refined = refine_box(e["bbox"], [*page.get("imageRegions", []), *page.get("words", [])]) if compatible_frame else e["bbox"]
        regions.append({"regionId": e["elementId"], "kind": e["kind"], "bbox": refined,
                        "origin": VERSION, "lensReason": e["lensReason"], "text": e["title"],
                        "locationState": e["locationState"], "paddingApplied": True, "boundaryRefined": refined!=e["bbox"]})
        fields = [("ai_transcription", "transcription", element_text(e)),
                  ("ai_visual_observation", "observation", "\n".join([e["description"], *e["relationships"]]))]
        for source, field, content in fields:
            if not content.strip():
                continue
            for start in range(0, len(content), CHUNK_CHARS-160):
                end = min(len(content), start+CHUNK_CHARS)
                document["chunks"].append({"id": f"{e['elementId']}-{field}-{start}", "documentId": document["documentId"],
                    "page": number, "pageLabel": page.get("label"), "source": source, "field": f"pageAnalysis.{e['elementId']}.{field}",
                    "start": start, "end": end, "text": content[start:end], "bbox": e["bbox"], "pageVision": True,
                    "elementId": e["elementId"], "elementTitle": e["title"], "elementKind": e["kind"],
                    "nativeSupportSourceIds": native_support,
                    "formulas": e["formulas"] if start == 0 and field == "transcription" else []})
                if end == len(content):
                    break
        # Clean native elements still need coverage IDs, without re-transcribing the whole page.
        if not any(c.get("elementId") == e["elementId"] for c in document["chunks"]):
            text = "\n".join(a["text"] for a in anchors(page) if a["id"] in e["anchorIds"])
            if text:
                document["chunks"].append({"id": e["elementId"]+"-native", "documentId": document["documentId"],
                    "page": number, "source": "ai_visual_observation", "field": "pageAnalysis.anchoredText", "start": 0, "end": len(text),
                    "text": text, "bbox": e["bbox"], "pageVision": True, "elementId": e["elementId"], "elementTitle": e["title"], "elementKind": e["kind"], "formulas": [], "nativeSupportSourceIds": native_support})
    page["slideLensRegions"] = regions
    document["pageAnalysisVersion"] = VERSION
    document["pageAnalysisStates"] = analysis_states(document)
    document["pageAnalysisIncompletePages"] = [entry["page"] for entry in document["pageAnalysisStates"] if not entry["complete"]]


def request_page(folder, document, number, provider):
    """Read one page without changing the shared document; safe to run in parallel."""
    check_cancel(Path(folder))
    saved = read_cached(folder, document, number)
    repair_cached = (saved is not None and saved.get("status") == "partial" and
                     (saved.get("validationVersion", 0) < VALIDATION_VERSION or
                      "요소 종류가 목록과 일치하지 않습니다." in saved.get("issues", [])))
    if saved is not None and not repair_cached:
        return saved, False, None
    if provider.model != "gpt-6-luna":
        raise ValueError("페이지 시각 분석은 GPT-6 Luna를 사용합니다.")
    previous = []
    for n in range(max(1, number-3), number):
        p = document["pages"][n-1]
        # Prior AI responses would depend on which parallel request finished first.
        # Native text is stable; the summary stage receives the completed prior visual result.
        previous.append({"page": n, "nativeText": native(p)[:2200], "excerpted": len(native(p)) > 2200,
                         "analysis": "", "status": "native_only"})
    page = document["pages"][number-1]
    image = render_page(folder, number)
    provider.context = {"kind": "page_visual", "page": number, "pageKey": key_for(document, number)}
    from pdf_ai import AiResponseError
    transport_failure = None
    try:
        payload={"task": "Inventory, read and relate every learning element on this entire page.",
        "page": number, "nativeText": native(page), "anchors": anchors(page), "previousContext": previous,
        "imageDimensions": [image["width"], image["height"]], "coordinates": "full rendered page, top-left origin, normalized 0..1"}
        value = provider.complete(payload,
            max_output=MAX_OUTPUT, image=image, system_prompt=SYSTEM,
            cache_only=repair_cached)
        if analysis_issues(value, native(page)) and not repair_cached:
            value = provider.complete(payload, max_output=MAX_OUTPUT, image=image,
                                      system_prompt=SYSTEM+STRICT_KOREAN_RETRY)
        if issues := analysis_issues(value, native(page)):
            raise ValueError("페이지 판독 설명이 한국어가 아닙니다: " + ", ".join(issues[:3]))
        result = validate(value, page, key_for(document, number))
    except (ValueError, AiResponseError) as failure:
        if repair_cached:
            # A cache-only repair must never turn a previous page result into a
            # new charge or overwrite it when the paid response is unavailable.
            return saved, False, None
        # The provider preserves the paid response. Persist an attempt to prevent automatic rebilling.
        result = {"status": "partial", "inventory": [], "elements": [], "contextSummary": "", "issues": [str(failure)]}
        if isinstance(failure, AiResponseError) and failure.__cause__ is not None and not isinstance(failure.__cause__, (ValueError, KeyError, TypeError)):
            transport_failure = failure
    result.update(version=VERSION, validationVersion=VALIDATION_VERSION,
                  inputKey=key_for(document, number), documentId=document["documentId"], page=number,
                  imageDimensions=[image["width"], image["height"]])
    write_json(cache_path(folder, document, number), result)
    return result, True, transport_failure


def commit_page(folder, document, result, newly_analyzed):
    """Apply and persist one completed page in the coordinator thread."""
    number = result["page"]
    apply_result(document, result, frame_compatible(folder,number))
    write_json(Path(folder)/"document.json", document)
    if newly_analyzed:
        emit("page_analysis_ready", page=number, status=result["status"], path=str(cache_path(folder, document, number)))


def analyze_page(folder, document, number, provider):
    result, newly_analyzed, transport_failure = request_page(folder, document, number, provider)
    commit_page(folder, document, result, newly_analyzed)
    if transport_failure is not None:
        raise transport_failure
    return result


def selected_pages(document, pages=None):
    pages = list(range(1, len(document["pages"])+1)) if pages is None else pages
    if not isinstance(pages, list) or not pages or any(type(n) is not int or not 1 <= n <= len(document["pages"]) for n in pages):
        raise ValueError("분석 페이지 범위를 확인하세요.")
    return sorted(set(pages))


def uncertain_previous_pages(folder, document, pages):
    """Expose unfinished paid image attempts before the next cost confirmation."""
    keys = {key_for(document, n): n for n in pages}
    uncertain = set()
    for path in (Path(folder) / "usage").glob("*.json"):
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
            if ledger.get("model") != "gpt-6-luna":
                continue
            for entry in ledger.get("requests", []):
                if (entry.get("kind") == "page_visual" and
                    entry.get("state") in {"reserved", "failed_or_uncertain"} and
                    entry.get("pageKey") in keys):
                    uncertain.add(keys[entry["pageKey"]])
        except (OSError, ValueError, TypeError):
            continue
    return sorted(uncertain)


def plan(folder, document, rates=(.1, .5), pages=None):
    pages = selected_pages(document, pages)
    saved = [read_cached(folder, document, n) for n in pages]
    pending = sum(r is None for r in saved)
    uncertain = uncertain_previous_pages(folder, document,
        [n for n, result in zip(pages, saved) if result is None])
    # Conservative reservation estimate, not a claim about actual model image tokenization.
    estimate = pending * (96000*rates[0]+MAX_OUTPUT*rates[1])/1_000_000
    # Typical completed page readings use roughly 14k input and 1.8k output
    # tokens. This is a display forecast; Provider keeps the budget guard.
    expected = pending * (14000*rates[0]+1800*rates[1])/1_000_000
    return {"kind": "page_analysis_plan", "total": len(pages), "completed": sum(r is not None and r["status"] == "ready" for r in saved),
            "cached": len(pages)-pending, "partial": sum(r is not None and r["status"] != "ready" for r in saved),
            "pending": pending, "uncertainPreviousPages": uncertain,
            "requestUpperBound": pending, "costUpperEstimateUsd": estimate,
            "costEstimateUsd": expected, "pages": pages}


def analyze_pages(folder, document, provider, pages=None):
    pages = selected_pages(document, pages)
    snapshot = copy.deepcopy(document)
    failures = []
    with ThreadPoolExecutor(max_workers=min(VISION_WORKERS, len(pages))) as pool:
        futures = {pool.submit(request_page, folder, snapshot, n, provider): n for n in pages}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                result, newly_analyzed, transport_failure = future.result()
                commit_page(folder, document, result, newly_analyzed)
                if transport_failure is not None:
                    failures.append(transport_failure)
            except Exception as failure:
                failures.append(failure)
            emit("progress", page=index, total=len(pages), stage="Luna · 페이지 전체의 글자·수식·시각 요소 분석")
    write_json(Path(folder)/"document.json", document)
    if failures:
        raise failures[0]
    return plan(folder, document, pages=pages) | {"kind": "page_analysis_batch", "model": provider.model}


def hydrate(folder, document):
    for number in range(1, len(document["pages"])+1):
        cached = read_cached(folder, document, number)
        if cached:
            apply_result(document, cached, frame_compatible(folder,number))
    document["pageAnalysisStates"] = analysis_states(document)
    document["pageAnalysisIncompletePages"] = [entry["page"] for entry in document["pageAnalysisStates"] if not entry["complete"]]


def visual_notes(document, pages):
    return [{"page": n, "kind": e["kind"], "description": e["description"], "visibleRelationships": e["relationships"],
             "uncertainDetails": e["uncertainDetails"], "regionId": e["elementId"], "selectedRegion": e["bbox"],
             "roleReason": e["purpose"], "importance": 2, "purposes": ["understanding_aid"]}
            for n in sorted(set(pages)) for e in document["pages"][n-1].get("pageAnalysis", {}).get("elements", [])
            if e["kind"] != "decoration" and (e["description"] or e["relationships"])]


SUMMARY_POLICY = r"""
requiredElements lists the teaching elements in this source range after navigation,
practice and example elements have been removed. Examples remain available as optional source
material when they uniquely clarify a new concept. Cover every remaining ID in summary parts using
coveredElementIds, keeping each element's own conditions, quantities and conclusions. For any
remaining ID that actually belongs to excluded contents or post-teaching practice, list it in
summary.excludedElementIds instead of covering or explaining it.
Keep central formulas as Markdown math in the body, with variables and conditions.
Return coveredElementIds:[string] on each summary part, not just on the entire response.
For each covered element, cite a sourceId from that element's sourceIds in that part's evidence.
An unrelated page citation alone does not verify a diagram or formula. A part can cite multiple
elements. Group headings and labels with the corresponding teaching content, not separate prose.
"""


def required_elements(unit):
    grouped = {}
    sources_by_element = {}
    for c in unit:
        if c.get("elementId") and c.get("elementKind") not in {"contents", "problem", "solution", "example"}:
            item = grouped.setdefault(c["elementId"], {"elementId": c["elementId"], "title": c["elementTitle"], "kind": c.get("elementKind", "other"), "formulas": [], "sourceIds": []})
            item["formulas"].extend(c.get("formulas", []))
            item["sourceIds"].append(c["id"])
            sources_by_element.setdefault(c["elementId"], []).append(c)
    def layout_heading(item):
        sources=sources_by_element[item["elementId"]]
        observations = [c.get("text", "") for c in sources if c.get("source") == "ai_visual_observation"]
        transcriptions = [c.get("text", "") for c in sources if c.get("source") == "ai_visual_transcription"]
        return (item["kind"] == "text" and not item["formulas"] and len(item["title"]) < 80
                and observations and all(re.search(r"(?:title|heading|제목|표제)", t, re.I) for t in observations)
                and all(len(t.strip()) < 120 for t in transcriptions)
                and all(len(t) < 160 for t in observations))
    return [item for item in grouped.values() if not layout_heading(item)]


def _source_flows(text):
    """Return explicit three-stage arrows, ignoring prose around the diagram."""
    pattern = r"[\w가-힣]+(?:\s+[\w가-힣]+)?(?:\s*→\s*[\w가-힣]+(?:\s+[\w가-힣]+)?){2,}"
    return {re.sub(r"\s+", "", flow) for flow in re.findall(pattern, text)}


def _covered_duplicate_flow(identity, sources, unit, parts):
    """Recognize a repeated source flow only when another element prints it too."""
    page = sources[0]["page"]
    flows = set().union(*(_source_flows(c.get("text", "")) for c in sources))
    other_flows = set().union(*(_source_flows(c.get("text", "")) for c in unit
        if c.get("elementId") != identity and c.get("page") == page
        and c.get("source") == "ai_transcription"))
    repeated = {flow for flow in other_flows if any(flow in own for own in flows)}
    return next((part for part in parts if any(flow in rendered for flow in repeated
                 for rendered in _source_flows(part.get("body", "")))
                 and any(e.get("page") == page for e in part.get("evidence", []))), None)


def preserve_summary_elements(summary, unit, review_evidence):
    """Check element coverage without putting unreviewed source text in study prose."""
    excluded = set(summary.get("excludedElementIds") or [])
    required = [entry for entry in required_elements(unit) if entry["elementId"] not in excluded]
    if not required:
        return
    if not summary.get("parts"):
        summary["parts"] = [{"title": summary.get("title", ""), "body": summary.get("body", ""),
            "evidence": summary.get("evidence", []), "easyExplanation": "", "visualPages": []}]
    parts = summary["parts"]
    unverified = []
    for entry in required:
        identity = entry["elementId"]
        sources = [c for c in unit if c.get("elementId") == identity]
        # Native quotes are valid support when this element's actual native anchors occur in
        # the cited chunk. Do not require duplicate AI quotations of the very same passage.
        support = {c["id"] for c in sources} | {sid for c in sources for sid in c.get("nativeSupportSourceIds", [])}
        source_pages = {c["page"] for c in sources}
        matching = []
        for part in parts:
            if identity not in part.get("coveredElementIds", []):
                continue
            direct = any(e.get("sourceId") in support for e in part.get("evidence", []))
            # A cited native paragraph can explain several adjacent formulas/figures. Require
            # a verified same-page source plus explicit coverage ID, not duplicate quotes for
            # each heading/label. This checks coverage declarations, not semantic truth.
            page_supported = any(e.get("page") in source_pages for e in part.get("evidence", [])) or bool(source_pages & set(part.get("visualPages", [])))
            if direct or page_supported:
                matching.append(part)
                if not direct:
                    part["coverageLinkedByPage"] = True
        if not matching:
            duplicate_part = _covered_duplicate_flow(identity, sources, unit, parts)
            if duplicate_part is not None:
                duplicate_part.setdefault("coveredElementIds", []).append(identity)
                duplicate_part["coverageLinkedByPage"] = True
                continue
            # A missing coverage ID is not proof that the prose omitted the topic.
            # Keep the uncertainty as metadata; raw source transcription is not a summary.
            unverified.append(identity)
            continue
        # Coverage verifies the selected teaching idea, not every intermediate equation.
        # Appending all source formulas here reproduced entire exercise calculations after
        # the model had already chosen a concise explanation.
    summary["coverageUnverifiedElementIds"] = unverified
    if unverified:
        summary["contentIncomplete"] = True
    summary["body"] = "\n\n".join(p.get("body", "") for p in parts)
    summary["evidence"] = [e for p in parts for e in p.get("evidence", [])]
