"""Exact repetition in short JSON fields; no output repair or API retries.

The caller opts in per engine. Long explanations, code and formulas are not
short fields. Source-exact strings are exempt only up to their actual length.
"""
from __future__ import annotations

import json

MIN_CHARS = 1024
MIN_CYCLES = 64
MAX_PERIOD = 32
CHECK_EVERY = 64
SHORT_FIELDS = frozenset(('title', 'name'))


def source_spellings(body, minimum_chars=MIN_CHARS):
    """Collect long source strings from user text, excluding prompts and images.

    Payload JSON is unpacked so its serialization is not itself treated as a
    source. Exact raw JSON spellings support Unicode and escaped source text.
    These values are in-memory only and must not be written to diagnostics.
    """
    found = set()

    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str):
            for ascii_only in (False, True):
                raw = json.dumps(value, ensure_ascii=ascii_only)[1:-1]
                if len(raw) >= minimum_chars:
                    found.add(raw)

    for item in body.get('input', ()):
        if not isinstance(item, dict) or item.get('role') != 'user':
            continue
        content = item.get('content', ())
        if isinstance(content, str):
            content = [{'type': 'input_text', 'text': content}]
        for part in content if isinstance(content, list) else ():
            if not isinstance(part, dict) or part.get('type') not in ('input_text', 'text'):
                continue
            text = part.get('text')
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
            except ValueError:
                payload = text
            collect(payload)
    return tuple(found)


class ShortFieldRepetition:
    """Incrementally inspect raw JSON string values, including split escapes.

    A match requires at least 1,024 uninterrupted periodic characters and 64
    cycles, with periods of at most 32 characters. Only title/name values can
    match; repeated separate fields or source-coverage entries cannot combine.
    """
    def __init__(self, sources=()):
        self.sources = tuple(sources)
        self.source_limit = max(map(len, self.sources), default=0)
        self.in_string = False
        self.escaped = False
        self.last_sig = None
        self.pending_key = None
        self.last_string = None
        self.field = None
        self.key_text = ''
        self.tail = ''
        self.source_prefix = ''
        self.string_chars = 0
        self.next_check = MIN_CHARS
        self.offset = 0
        self.match = None
        self.source_exempt_checks = 0

    @property
    def detected(self):
        return self.match is not None

    def feed(self, chunk):
        if self.detected:
            return True
        for char in chunk:
            self.offset += 1
            if not self.in_string:
                if char == '"':
                    self.in_string = True
                    self.escaped = False
                    self.key_text = self.tail = self.source_prefix = ''
                    self.string_chars = 0
                    self.next_check = MIN_CHARS
                    self.field = self.pending_key if self.last_sig == ':' else None
                elif not char.isspace():
                    if char == ':':
                        self.pending_key = self.last_string
                    self.last_sig = char
                continue
            if char == '"' and not self.escaped:
                self.in_string = False
                self.last_sig = '"'
                try:
                    self.last_string = (json.loads('"' + self.key_text + '"')
                                        if self.string_chars < 256 else None)
                except (ValueError, TypeError):
                    self.last_string = None
                continue
            self.string_chars += 1
            if self.string_chars < 256:
                self.key_text += char
            if self.escaped:
                self.escaped = False
            elif char == '\\':
                self.escaped = True
            if self.field not in SHORT_FIELDS:
                continue
            self.tail = (self.tail + char)[-max(MIN_CHARS, MAX_PERIOD * MIN_CYCLES):]
            if self.string_chars <= self.source_limit:
                self.source_prefix += char
            if self.string_chars < self.next_check:
                continue
            self.next_check = self.string_chars + CHECK_EVERY
            for period in range(1, MAX_PERIOD + 1):
                required = max(MIN_CHARS, period * MIN_CYCLES)
                if len(self.tail) < required:
                    continue
                value = self.tail[-required:]
                if value[period:] != value[:-period]:
                    continue
                # An exemption cannot permit an unbounded loop just because a
                # short repeated pattern appeared somewhere in the PDF.
                if (self.string_chars <= self.source_limit and
                        any(self.source_prefix in source for source in self.sources)):
                    self.source_exempt_checks += 1
                    break
                self.match = {'field': self.field, 'offsetChars': self.offset,
                              'stringChars': self.string_chars, 'period': period,
                              'repeatedChars': required,
                              'minimumCycles': required // period}
                return True
        return False
