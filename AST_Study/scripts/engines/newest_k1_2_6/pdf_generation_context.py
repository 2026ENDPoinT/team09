"""Local planning for long study documents; source text is never truncated."""
import json
import re

from pdf_study_policy import _page_texts, clip_utf8

GENERATION_UNIT_MAX_BYTES = 24000
GENERATION_UNIT_MAX_CHUNKS = 12


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def chapter_starts(document):
    """Use explicit headings only; ordinary sentences/numbers are not boundaries."""
    starts = set()
    previous_number = None
    for page, text in sorted(_page_texts(document).items()):
        for line in text.splitlines()[:4]:
            line = line.strip()
            if re.match(r"^(?:#{1,2}\s+|(?:chapter|part|unit)\s+\d+\b|제?\s*\d+\s*장\b)", line, re.I):
                starts.add(page)
                break
            numbered = re.match(r"^(\d+)(?:\.\d+)*[.\s]+\s*[^\d\s].{1,80}$", line)
            if numbered:
                number = numbered.group(1)
                if previous_number is not None and number != previous_number:
                    starts.add(page)
                previous_number = number
                break
    return starts


def generation_units(chunks, document, max_bytes=GENERATION_UNIT_MAX_BYTES,
                     max_chunks=GENERATION_UNIT_MAX_CHUNKS):
    """Prefer chapter/page boundaries; an oversized single chunk reaches adaptive splitting."""
    starts = chapter_starts(document)
    sizes = [json_bytes({"sourceId": c["id"], "text": c.get("aiText", c["text"])}) for c in chunks]
    begin = 0
    while begin < len(chunks):
        end, size = begin, 0
        while end < len(chunks) and (end == begin or
                (size + sizes[end] <= max_bytes and end - begin < max_chunks)):
            size += sizes[end]
            end += 1
        if end < len(chunks):
            boundaries = [i for i in range(begin + 1, end + 1)
                          if i < len(chunks) and chunks[i]["page"] != chunks[i-1]["page"]]
            chapters = [i for i in boundaries if chunks[i]["page"] in starts]
            if chapters:
                end = chapters[-1]
            elif boundaries:
                end = boundaries[-1]
        yield chunks[begin:end]
        begin = end


def previous_context(document, unit):
    """Previous three pages, background only. Excerpts do not replace target sources."""
    first = min(c["page"] for c in unit)
    texts = _page_texts(document)
    result = []
    for number in range(max(1, first - 3), first):
        if number not in texts:
            continue
        text = texts[number]
        # Only optional background is excerpted; all target text is handled in its own unit.
        excerpt = text if len(text.encode("utf-8")) <= 4000 else (
            clip_utf8(text, 1800) + "\n[…]\n" + text.encode("utf-8")[-2200:].decode("utf-8", errors="ignore"))
        result.append({"page": number, "text": excerpt, "backgroundOnly": True,
                       "excerpted": excerpt != text})
    return result


def relevant_concept_names(names, unit, limit_bytes=6000):
    """Match against the entire registry, including concepts introduced early in a long PDF."""
    text = " ".join(c.get("aiText", c["text"]) for c in unit).lower()
    names = list(dict.fromkeys(names))
    ranked = sorted(enumerate(names), key=lambda pair: (
        pair[1].lower() in text, sum(t.lower() in text for t in re.findall(r"\w+", pair[1])), pair[0]), reverse=True)
    result = []
    for _, name in ranked:
        if json_bytes(result + [name]) <= limit_bytes:
            result.append(name)
    return result
