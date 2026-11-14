"""SlideLens v1: a small, source-bound contract for cropped lecture material."""
from __future__ import annotations
import hashlib
import json


MODULE_ID = "synesis.slide-lens"
SCHEMA_VERSION = 1
REGION_CATALOG_VERSION = 1
PLACEMENT_MARKER = "[[SLIDE_LENS]]"


def normalize_placement(fields, selected):
    """Keep one standalone placement marker only for a validated crop."""
    placed = False
    cleaned = {}
    for name, value in fields.items():
        in_fence = False
        lines = []
        for line in value.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
            if PLACEMENT_MARKER in line:
                if selected and not placed and not in_fence and stripped == PLACEMENT_MARKER:
                    placed = True
                    lines.append(line)
                else:
                    lines.append(line.replace(PLACEMENT_MARKER, ""))
            else:
                lines.append(line)
        cleaned[name] = "".join(lines)
    return cleaned


def _valid_box(value):
    return (isinstance(value, list) and len(value) == 4 and
            all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in value) and
            0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1)


def ensure_region_catalog(document):
    """Persist IDs with source geometry, independent of later visual classification."""
    changed = document.get("slideLensRegionCatalogVersion") != REGION_CATALOG_VERSION
    for number, page in enumerate(document["pages"], 1):
        regions = page.get("slideLensRegions")
        if not isinstance(regions, list):
            regions = []
            page["slideLensRegions"] = regions
            changed = True
        seen = {(item.get("kind"), tuple(round(value, 5) for value in item["bbox"]))
                for item in regions if isinstance(item, dict) and _valid_box(item.get("bbox"))}
        legacy_ids = {item.get("legacyId") for item in regions if isinstance(item, dict)}
        for kind, field in (("image", "imageRegions"), ("table", "tableRegions"),
                            ("text", "textRegions")):
            for source_index, item in enumerate(page.get(field, [])):
                box = item.get("bbox") if isinstance(item, dict) else None
                if not _valid_box(box):
                    continue
                key = (kind, tuple(round(value, 5) for value in box))
                if key in seen:
                    continue
                seen.add(key)
                digest = hashlib.sha256(json.dumps([number, kind, key[1]],
                    separators=(",", ":")).encode()).hexdigest()[:12]
                region = {"regionId": f"sl1-p{number}-{kind}-{digest}",
                          "kind": kind, "bbox": box, "sourceIndex": source_index}
                legacy_id = f"p{number}-{kind}-{source_index}"
                if legacy_id not in legacy_ids:
                    region["legacyId"] = legacy_id
                    legacy_ids.add(legacy_id)
                if kind == "text":
                    region["text"] = item.get("text", "")
                regions.append(region)
                changed = True
    document["slideLensRegionCatalogVersion"] = REGION_CATALOG_VERSION
    return changed


def ignored_visual_regions(folder, document, pages):
    """Honor existing local importance-0 decisions without another model call."""
    if folder is None:
        return set()
    from pdf_visual import candidates as image_candidates, read_cached
    target = set(pages)
    ignored = set()
    for item in image_candidates(document):
        if item["page"] not in target:
            continue
        saved = read_cached(folder, document, item)
        if saved and saved.get("importance") == 0:
            ignored.add((item["page"], tuple(item["selectedRegion"])))
    return ignored


def candidates(document, pages, visual_notes=(), ignored_images=()):
    """Only locally detected PDF regions are selectable; the AI never writes coordinates."""
    ensure_region_catalog(document)
    notes = {(note.get("page"), tuple(note.get("selectedRegion") or [])): note
             for note in visual_notes}
    result = []
    for number in sorted(set(pages)):
        if not isinstance(number, int) or not 1 <= number <= len(document["pages"]):
            continue
        page = document["pages"][number - 1]
        for region in page["slideLensRegions"]:
            if page.get("pageAnalysis"):
                # A semantic ID is provenance, never an instruction to display a crop.
                if region.get("origin") != "page-vision-v1" or region.get("lensReason", "none") == "none":
                    continue
                if region.get("kind") == "formula" and region.get("lensReason") not in {"annotation", "unreadable"}:
                    continue
                result.append({"regionId": region["regionId"], "page": number, "kind": region["kind"],
                               "bbox": region["bbox"], "cue": region.get("text", ""), "nearbyText": "",
                               "lensReason": region["lensReason"], "locationState": region.get("locationState", "padded"),
                               "paddingApplied": True})
                continue
            kind, box = region["kind"], region["bbox"]
            if kind == "image" and (number, tuple(box)) in ignored_images:
                continue
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area < (.0015 if kind == "text" else .015) or (box[1] > .88 and area < .12):
                continue  # Tiny decorations and recurring footer material.
            note = notes.get((number, tuple(box)))
            if kind == "image" and note and note.get("importance") == 0:
                continue
            cue = region.get("text", "") if kind == "text" else (note.get("description", "") if note else "")
            nearby = "" if kind == "text" else " ".join(
                str(word.get("text", "")) for word in page.get("words", [])
                if _valid_box(word.get("bbox")) and
                word["bbox"][1] < min(1, box[3] + .035) and
                word["bbox"][3] > max(0, box[1] - .035))
            result.append({"regionId": region["regionId"], "page": number,
                           "kind": kind, "bbox": box, "cue": cue[:150],
                           "nearbyText": nearby[:160]})
    return result


def prompt_catalog(catalog, target_bytes=24000):
    """Expose every selectable ID while shrinking descriptions on unusually dense pages."""
    for cue_limit, nearby_limit, include_box in ((150, 160, True), (80, 60, True),
                                                  (65, 0, False), (0, 0, False)):
        entries = []
        for item in catalog:
            entry = {"regionId": item["regionId"], "page": item["page"], "kind": item["kind"]}
            if "lensReason" in item:
                entry["lensReason"] = item["lensReason"]
            if include_box:
                entry["bbox"] = [round(value, 3) for value in item["bbox"]]
            if cue_limit and item["cue"]:
                entry["cue"] = item["cue"][:cue_limit]
            if nearby_limit and item["nearbyText"]:
                entry["nearbyText"] = item["nearbyText"][:nearby_limit]
            entries.append(entry)
        if len(json.dumps(entries, ensure_ascii=False).encode("utf-8")) <= target_bytes:
            return entries
    return entries  # Even in an extreme case, IDs remain visible rather than being silently omitted.


def validate_selection(region_id, catalog, supported_pages):
    """Resolve an AI-selected ID to trusted page coordinates and a fixed module schema."""
    if not isinstance(region_id, str) or not region_id:
        return None
    allowed = {item["regionId"]: item for item in catalog}
    selected = allowed.get(region_id)
    if selected is None or selected["page"] not in supported_pages:
        return None
    return {"moduleId": MODULE_ID, "schemaVersion": SCHEMA_VERSION,
            "regionId": selected["regionId"], "page": selected["page"],
            "kind": selected["kind"], "bbox": selected["bbox"],
            **({"paddingApplied": True, "locationState": selected.get("locationState", "padded")}
               if selected.get("paddingApplied") else {})}
