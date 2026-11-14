"""Recover intact math envelopes without changing a formula or touching code."""
import re

_PROTECTED = re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2|'
                        r'\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)')


def protect_calls(text):
    """Quote intact code calls with string arguments before prose/math repair.

    A format string's percent signs and literal backslash-n are code, even if
    the model forgot Markdown ticks. Do not guess unmatched or nested syntax.
    """
    call=re.compile(r'\b[A-Za-z_]\w*\(\s*"(?:\\.|[^"\\\n])*"[^()\n`]*\)')
    out=[];start=0
    def protect(value):
        return call.sub(lambda m:'`'+m[0]+'`' if not re.search(r'[가-힣]',
            re.sub(r'"(?:\\.|[^"\\])*"','',m[0])) else m[0],value)
    for m in _PROTECTED.finditer(text):
        out.extend((protect(text[start:m.start()]),m[0]));start=m.end()
    return ''.join(out)+protect(text[start:])


def intact(value):
    value=value.strip()
    if not value or re.search(r'[가-힣\x00-\x1f`;$]|\\[\[\]()]',value):return False
    stack=[];pairs={')':'(',']':'[','}':'{'}
    for char in value:
        if char in '([{':stack.append(char)
        elif char in pairs:
            if not stack or stack.pop()!=pairs[char]:return False
    if stack or re.search(r'[=+*/^_-]\s*[)}\]]*\s*$',value):return False
    if re.search(r'\b(?:int|char|void|return|new|delete|class|const)\b|::|->',value):return False
    probe=re.sub(r'\\(?:text|mathrm|operatorname)\{[^{}]*\}','',value)
    probe=re.sub(r'\\[A-Za-z]+|_\{[A-Za-z,]+\}','',probe)
    if re.search(r'\b[A-Za-z]{4,}\b',probe):return False
    return bool(re.search(r'\\[A-Za-z]+|[=^_]|[α-ωΑ-Ω]',value) or
                re.fullmatch(r'[A-Za-z](?:[,/]\s*[A-Za-z])*',value))


def restore(text):
    text=protect_calls(text)
    def fix(value):
        # Repair escaped prose line breaks/doubled TeX only in unprotected spans.
        value=re.sub(r'(?<!\\)\\n(?![A-Za-z])','\n',value)
        value=re.sub(r'\\\\(?=[A-Za-z])',lambda m:'\\',value)
        # A bare parenthesized math island bounded by line breaks. Nested math
        # parentheses remain inside; balancing forbids partial reconstruction.
        def island(m):
            content=re.sub(r'\s+',' ',m[1]).strip()
            return '\\('+content+'\\)' if intact(content) else m[0]
        value=re.sub(r'(?<=\n)\(([^가-힣`;$]{1,2400}?)\)(?=\n|[ \t]*[가-힣])',island,value)
        return re.sub(r'(?<=\n)([^\n]{1,2400})(?=\n)',
                      lambda m:'\\('+m[1].strip()+'\\)' if intact(m[1]) else m[0],value)
    out=[];start=0
    for m in _PROTECTED.finditer(text):
        out.extend((fix(text[start:m.start()]),m[0]));start=m.end()
    return ''.join(out)+fix(text[start:])
