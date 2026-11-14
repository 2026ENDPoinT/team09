"""Lossless math delimiters for learner prose; no source/semantic rewriting."""
from __future__ import annotations
import re

# Protect existing math and code before looking for a missing delimiter. In
# particular an integral in a programming string must remain a code sample.
PROTECTED=re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2|'
                     r'(?m:^[ \t]{4}[^\n]*(?:\n|$))|'
                     r'\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)')
TOKEN=re.compile(r'(?<![A-Za-z0-9\\:/])(?:\\[A-Za-z]+|\\[,;:!]|'
                 r'[A-Za-z0-9_+*/=^{}()\[\].,|<>−\-α-ωΑ-Ω∫∑√∞≈≤≥×·₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇ⁺⁻⁽⁾₊₋₍₎])+')
ANCHOR=re.compile(r'\\(?:int|sum|frac|dfrac|tfrac|sqrt|pi|Delta|alpha|beta|theta|rho|sigma|times|cdot|lim|sin|cos|tan|infty)\b|'
                  r'[=∫∑√₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇ]|[α-ωΑ-Ω]')


def _math_token(value):
    # Long prose words/paths are not a mathematical factor. TeX command names
    # and names inside text/unit commands may themselves be longer.
    plain=re.sub(r'\\(?:text|mathrm|operatorname)\{[^{}]*\}', '', value)
    plain=re.sub(r'\\[A-Za-z]+', '', plain)
    return not re.search(r'[A-Za-z]{3,}|://|^[=.,]+$', plain)


def _format_prose(text):
    groups=[]
    for m in TOKEN.finditer(text):
        if not _math_token(m[0]):continue
        if groups and text[groups[-1][1]:m.start()] and text[groups[-1][1]:m.start()].strip(' \t')=='':
            groups[-1][1]=m.end()
        else:groups.append([m.start(),m.end()])
    for start,end in reversed(groups):
        value=text[start:end]
        if not ANCHOR.search(value):continue
        # Prose sentence marks are outside math; a decimal point is retained.
        while value.endswith(('.',',')):value=value[:-1];end-=1
        if not value or value.count('(')!=value.count(')') or value.count('{')!=value.count('}'):
            continue  # Never invent a delimiter or missing mathematical symbol.
        text=text[:start]+r'\('+value+r'\)'+text[end:]
    return text


MODULO=re.compile(r'(?<![\w\\])(?:[A-Za-z_]\w*|\d+)\s*%\s*(?:[A-Za-z_]\w*|\d+)'
                  r'(?:\s*(?:==|!=|=)\s*(?:[A-Za-z_]\w*|\d+))?')


def _format_plain(text):
    # % is a programming operator, not a boundary before an unrelated equality.
    out=[];position=0
    for match in MODULO.finditer(text):
        out.extend((_format_prose(text[position:match.start()]),'`'+match[0]+'`'))
        position=match.end()
    out.append(_format_prose(text[position:]))
    return ''.join(out)


def format_math(text):
    # Collapse redundant, complete envelopes only; never repair a missing symbol.
    code=re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2')
    def envelopes(value):
        value=re.sub(r'\$(\\\([^\n]*?\\\))\$',lambda m:m[1],value)
        for _ in range(4):
            fixed=re.sub(r'\\\(\s*(\\\([^\n]*?\\\))\s*\\\)',lambda m:m[1],value)
            if fixed==value:break
            value=fixed
        return value
    spans=[];position=0
    for match in code.finditer(text):
        spans.extend((envelopes(text[position:match.start()]),match[0]));position=match.end()
    spans.append(envelopes(text[position:]));text=''.join(spans)
    out=[];position=0
    for m in PROTECTED.finditer(text):
        out.extend((_format_plain(text[position:m.start()]),m[0]));position=m.end()
    out.append(_format_plain(text[position:]))
    return ''.join(out)
