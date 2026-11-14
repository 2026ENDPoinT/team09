"""Reject uninterrupted blank-line generation, including split JSON escapes.

Only opted-in teaching delivery uses this meter. Meaningful long explanations,
code, and formulas have no length limit. Exact blank runs present in supplied
source strings raise the threshold, but cannot exempt an unbounded overrun.
"""
import json
import re

MIN_LINES = 128
REASON = 'repeated_blank_lines'
_BLANKS = re.compile(r'[ \t\r\n]+')


class BlankLineRepetition:
    def __init__(self, sources=()):
        self.limit = MIN_LINES
        for raw in sources:
            try:
                text = json.loads('"' + raw + '"')
            except (ValueError, TypeError):
                continue
            for run in _BLANKS.finditer(text):
                lines = run.group().count('\n') + run.group().count('\r')
                self.limit = max(self.limit, lines + 1)
        self.in_string = False
        self.escaped = False
        self.unicode_digits = None
        self.lines = 0
        self.offset = 0
        self.match = None

    @property
    def detected(self):
        return self.match is not None

    def _decoded(self, char):
        if char in '\r\n':
            self.lines += 1
            if self.lines >= self.limit:
                self.match = {'blankLines': self.lines, 'offsetChars': self.offset,
                              'limit': self.limit}
        elif char not in ' \t':
            self.lines = 0

    def feed(self, chunk):
        if self.detected:
            return True
        for char in chunk:
            self.offset += 1
            if not self.in_string:
                if char == '"':
                    self.in_string = True
                    self.lines = 0
                continue
            if self.unicode_digits is not None:
                if char not in '0123456789abcdefABCDEF':
                    self.unicode_digits = None
                    self.lines = 0
                    continue
                self.unicode_digits += char
                if len(self.unicode_digits) == 4:
                    self._decoded(chr(int(self.unicode_digits, 16)))
                    self.unicode_digits = None
            elif self.escaped:
                self.escaped = False
                if char == 'u':
                    self.unicode_digits = ''
                else:
                    self._decoded({'n': '\n', 'r': '\r', 't': '\t'}.get(char, char))
            elif char == '\\':
                self.escaped = True
            elif char == '"':
                self.in_string = False
                self.lines = 0
            else:
                self._decoded(char)
            if self.detected:
                return True
        return False
