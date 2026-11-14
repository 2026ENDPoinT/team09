"""Preserve readable one-line source cells in GFM tables without changing TeX.

There is no arbitrary text-length limit: the paid response is already bounded.
The only serialization change is one added backslash before every pipe. The GFM
table reader removes exactly that escape before rendering prose/code; the study
renderer performs the same lossless unwrapping before typesetting table math.
"""
from __future__ import annotations

import re

VERSION = 'source-table-cells-gfm-pipes-v1'
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]')
_SOURCE_ID = re.compile(r'\bv2p\d+f\d+\b')
# A tag printed inside an explicit code/math literal is source text, not HTML.
_LITERAL = re.compile(r'(`+)[^\n]*?\1|\\\([^\n]*?\\\)|\\\[[^\n]*?\\\]|'
                      r'\$\$[^\n]*?\$\$|(?<![\\$])\$(?!\$)[^\n$]*?(?<!\\)\$(?!\$)')
_HTML = re.compile(r'<\s*(?:!--[^<>]*--|!DOCTYPE\b[^<>]*|\?[^<>]*\?|'
                   r'/?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*?)?/?\s*)>', re.I)


def valid_cell(value):
    """Accept complete readable text; reject structural/control/HTML/ID leaks."""
    return (isinstance(value, str) and bool(value.strip())
            and not _CONTROL.search(value) and not _SOURCE_ID.search(value)
            and not _HTML.search(_LITERAL.sub('', value)))


def markdown_cell(value):
    """Protect every original pipe once, including a pipe after a backslash.

    Do not call this on already-serialized Markdown cells: the input is the raw
    model/source cell. Re-escaping an existing source backslash is intentional;
    removing exactly one escape at display recovers the original code/TeX bytes.
    Neither TeX delimiters (|, \\|, \\lvert, ...) nor code operators are substituted.
    """
    if not valid_cell(value):
        raise ValueError('The table cell is not safe readable one-line text.')
    return value.replace('|', r'\|')
