"""Font-scoped source repair and evidence-backed cleanup of saved titles.

Never infer a bullet from ordinary Latin v. Saved learner prose stays intact;
only the exact symbol-font glyph and corroborated heading fields are repaired.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path


def _key(text):
    # Extraction may join the marker to its heading while generation inserts a
    # space. Only compare against independently font-verified source lines.
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def _wingdings(font):
    # Subset prefixes vary. Do not include Symbol, math fonts or Wingdings 2/3.
    return font.split('+')[-1].casefold() in ('wingdings', 'wingdings-regular')


def repair_symbol_chars(chars):
    """Wingdings code v draws a four-diamond bullet, never Latin/math v."""
    result, count = [], 0
    for char in chars:
        text = char.get('text', '')
        if _wingdings(str(char.get('fontname', ''))) and 'v' in text:
            count += text.count('v')
            char = {**char, 'text': text.replace('v', '❖')}
        result.append(char)
    return result, count


def verified_line(line):
    """A line-leading glyph is identified by its font, even with no gap."""
    text = line.get('text', '')
    if not isinstance(text, str) or not text.startswith('v') or not text[1:].strip():
        return None
    chars = [c for c in line.get('chars', []) if str(c.get('text', '')).strip()]
    if len(chars) < 2:
        return None
    first, following = chars[:2]
    if (first.get('text') != 'v' or not _wingdings(str(first.get('fontname', '')))
            or _wingdings(str(following.get('fontname', '')))):
        return None
    try:
        # Adjacent metrics are valid (the actual PDF has a 0.005pt gap).
        # Reject overlapping glyphs; do not infer from whitespace or prose.
        if float(following['x0']) - float(first['x1']) < -0.1:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return _key(text), text[1:].lstrip()


def title_fields(result):
    """Explicit heading/name fields only; never recurse into body/math/code."""
    def pages(item):
        found = {item['page']} if type(item.get('page')) is int else set()
        found.update(p for p in item.get('pages', []) if type(p) is int)
        found.update(e['page'] for e in item.get('evidence', [])
                     if isinstance(e, dict) and type(e.get('page')) is int)
        found.update(p for p in item.get('visualPages', []) if type(p) is int)
        return found

    hierarchy = result.get('hierarchy', result if 'nodes' in result else {})
    for node in hierarchy.get('nodes', []) if isinstance(hierarchy, dict) else []:
        if isinstance(node, dict):
            yield node, 'title', pages(node)
    for section in result.get('sections', []):
        if not isinstance(section, dict):
            continue
        yield section, 'title', pages(section)
        for part in section.get('parts', []):
            if isinstance(part, dict):
                yield part, 'title', pages(part)
    for concept in result.get('concepts', []):
        if isinstance(concept, dict):
            source_pages = pages(concept)
            for entry in concept.get('entries', []):
                if isinstance(entry, dict):
                    source_pages.update(pages(entry))
            yield concept, 'name', source_pages


def clean_titles(folder, result):
    """Fail closed on missing evidence. The caller's saved object stays intact."""
    candidates = [(item, field, pages) for item, field, pages in title_fields(result)
                  if isinstance(item.get(field), str) and item[field].startswith('v') and pages]
    if not candidates:
        return result
    source = Path(folder) / 'source.pdf'
    verified = {}
    try:
        import pdfplumber
        with pdfplumber.open(source) as pdf:
            for number in sorted({p for _, _, pages in candidates for p in pages}):
                if not 1 <= number <= len(pdf.pages):
                    continue
                approved, ambiguous = {}, set()
                for line in pdf.pages[number - 1].extract_text_lines(return_chars=True):
                    text = line.get('text', '')
                    if not isinstance(text, str) or not text.startswith('v'):
                        continue
                    pair = verified_line(line)
                    if pair:
                        approved[pair[0]] = pair[1]
                    else:
                        ambiguous.add(_key(text))
                # Identical ordinary-v and symbol-v lines on one page are ambiguous.
                verified[number] = {k: v for k, v in approved.items() if k not in ambiguous}
    except Exception:
        return result
    value = copy.deepcopy(result)
    for item, field, pages in title_fields(value):
        text = item.get(field)
        if not isinstance(text, str) or not text.startswith('v') or not pages:
            continue
        matches = [verified.get(p, {}).get(_key(text)) for p in pages]
        # Every cited page must corroborate the same line. No cross-page guessing.
        if matches and all(m is not None and m == matches[0] for m in matches):
            item[field] = text[1:].lstrip()
    return value
