"""Local-only removal of repeated contact/copyright margins from AI input copies."""
from collections import defaultdict
import math
import re


def margin_policy(document):
    groups = defaultdict(list)
    pages = document.get("pages", [])
    for number, page in enumerate(pages, 1):
        rows = []
        for word in sorted(page.get("words", []), key=lambda w: (w.get("bbox", [0, 0])[1], w.get("bbox", [0])[0])):
            box = word.get("bbox", [])
            if len(box) != 4 or not word.get("text"):
                continue
            edge = "bottom" if box[1] >= .9 else "top" if box[3] <= .1 else None
            if edge is None:
                continue
            row = next((r for r in rows if r["edge"] == edge and abs(r["y"]-box[1]) <= .008), None)
            if row is None:
                row = {"edge": edge, "y": box[1], "words": []}
                rows.append(row)
            row["words"].append(word)
        for row in rows:
            words = sorted(row["words"], key=lambda w: w["bbox"][0])
            # A changing page number should not prevent recognition of a fixed contact line.
            tokens = [w["text"] for w in words]
            if tokens and tokens[0] == str(number):
                tokens = tokens[1:]
            if tokens and tokens[-1] == str(number):
                tokens = tokens[:-1]
            text = " ".join(tokens).strip()
            # Do not remove repeated formulas, code, headings or ordinary course content.
            if not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|www\.|©|copyright|all rights reserved", text, re.I):
                continue
            if len(text) > 240:
                continue
            key = (row["edge"], re.sub(r"\s+", "", text).casefold())
            groups[key].append((number, row["y"], text))
    result = defaultdict(list)
    threshold = max(2, math.ceil(len(pages) * .5))
    for (edge, _), occurrences in groups.items():
        if len({n for n, _, _ in occurrences}) < threshold:
            continue
        anchor = occurrences[0][1]
        if any(abs(y-anchor) > .015 for _, y, _ in occurrences):
            continue
        for number, _, text in occurrences:
            result[number].append({"edge": edge, "text": text})
    return dict(result)


def excluded_ranges(text, entries):
    ranges = []
    for entry in entries:
        # MarkItDown can insert table separators between words. Match the exact
        # known margin wording, allowing only whitespace/Markdown separators.
        tokens = entry["text"].split()
        if not tokens:
            continue
        pattern = r"[\s|*_`\\]*".join(re.escape(t) for t in tokens)
        matches = list(re.finditer(pattern, text, re.I))
        if not matches:
            continue
        match = matches[-1] if entry["edge"] == "bottom" else matches[0]
        outside = text[match.end():] if entry["edge"] == "bottom" else text[:match.start()]
        # Only an occurrence at the actual text boundary is a margin. The same
        # address used as an example inside the body stays available to the model.
        if not re.sub(r"[\s|*_`\\\-\d./]+", "", outside):
            ranges.append(match.span())
    return sorted(set(ranges))


def clean_text(text, entries):
    for start, end in reversed(excluded_ranges(text, entries)):
        text = text[:start] + text[end:]
    return text


def clean_chunk(chunk, document, policy):
    number = chunk.get("page", 0)
    if not 1 <= number <= len(document.get("pages", [])):
        return chunk["text"]
    page = document["pages"][number-1]
    full = page.get(chunk.get("field", ""))
    start, end = chunk.get("start"), chunk.get("end")
    if not isinstance(full, str) or not isinstance(start, int) or not isinstance(end, int) or full[start:end] != chunk["text"]:
        # Without exact offsets, do not risk stripping a matching example in a body chunk.
        return chunk["text"]
    text = chunk["text"]
    for left, right in reversed(excluded_ranges(full, policy.get(number, []))):
        left, right = max(left, start)-start, min(right, end)-start
        if left < right:
            # Preserve character alignment for recursive model-request splitting.
            text = text[:left] + " " * (right-left) + text[right:]
    return text
