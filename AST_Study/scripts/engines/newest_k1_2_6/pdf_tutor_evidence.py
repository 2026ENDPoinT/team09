"""Local tutor citation binding. No network, fuzzy matching or model calls."""
from __future__ import annotations
import copy
import re
import unicodedata


def canonical_map(text):
    """Normalize typography/whitespace while mapping to ORIGINAL character spans.

    Operators, signs, decimal points, negation and word order are preserved.
    """
    raw = []
    for match in re.finditer(r'.(?:[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff]*)', text, re.S):
        first = match.group()[0]
        # Decimal digit fonts/width and Latin ligatures are typographic. Keep
        # exponents, subscripts, fractions and vector/set letter styles intact.
        compatible = (unicodedata.category(first) == 'Nd' or
                      '\ufb00' <= first <= '\ufb06' or '\uff00' <= first <= '\uffef')
        for char in unicodedata.normalize('NFKC' if compatible else 'NFC', match.group()):
            if char != '\u00ad':
                raw.append((char, (match.start(), match.end())))
    next_char, following_chars = '', [''] * len(raw)
    for index in range(len(raw) - 1, -1, -1):
        following_chars[index] = next_char
        if not raw[index][0].isspace():
            next_char = raw[index][0]
    chars, spans = [], []
    for index, (char, span) in enumerate(raw):
        if char.isspace():
            previous = raw[index - 1][0] if index else ''
            following = following_chars[index]
            if not (previous.isdecimal() and following.isdecimal()):
                continue  # Never turn two separate numeric tokens into one.
            char = ' '
        chars.append(char)
        spans.append(span)
    return ''.join(chars), spans


def original_quote(quote, original):
    if not isinstance(quote, str) or not 4 <= len(quote) <= 1200:
        return None
    wanted, _ = canonical_map(quote)
    haystack, spans = canonical_map(original)
    if len(wanted) < 4:
        return None
    start = haystack.find(wanted)
    if start < 0:
        return None
    return original[spans[start][0]:spans[start + len(wanted) - 1][1]]


def citation_sources(sources, max_chars=650):
    """Partition supplied text into selectable exact passages; send text only once."""
    packed, catalog = [], {}
    for source in sources:
        text = source.get('text', '')
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                boundary = max(text.rfind('\n', start + max_chars // 2, end),
                               text.rfind('. ', start + max_chars // 2, end))
                if boundary >= 0:
                    end = boundary + 1
            part = text[start:end]
            if part.strip():
                key = f'Q{len(catalog) + 1}'
                catalog[key] = {'sourceId': source['sourceId'], 'quote': part,
                                'start': start, 'end': end}
                packed.append({**source, 'text': part, 'quoteId': key})
            start = end
    return packed, catalog


def bind_citations(value, catalog):
    """Resolve only IDs supplied now; never attach a default retrieved passage."""
    result = copy.deepcopy(value)
    evidence = result.get('evidence')
    if not isinstance(evidence, list):
        return result
    resolved = []
    for item in evidence:
        if not isinstance(item, dict):
            resolved.append(item)
            continue
        key = item.get('quoteId')
        if key is None:
            resolved.append(item)
            continue
        found = catalog.get(key) if isinstance(key, str) else None
        if found and item.get('sourceId') in (None, found['sourceId']):
            resolved.append({'sourceId': found['sourceId'], 'quote': found['quote'], 'quoteId': key})
        else:
            resolved.append({'sourceId': item.get('sourceId'), 'quote': ''})
    result['evidence'] = resolved
    return result
