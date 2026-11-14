"""Recover visible characters from Hancom's legacy equation font.

HyhwpEQ's PDF ToUnicode map points many ordinary math glyphs at Private Use
Area code points. The mapping below was checked against the actual glyphs in
HYHWPEQ.TTF; it is deliberately scoped to that font, not arbitrary PUA text.
It restores characters, not two-dimensional fraction/superscript structure.
"""
from __future__ import annotations

from collections import Counter


HYHWPEQ_GLYPHS = {
    0xE000: "A", 0xE001: "B", 0xE002: "C", 0xE003: "D", 0xE004: "E",
    0xE005: "F", 0xE006: "G", 0xE007: "H", 0xE008: "I", 0xE009: "J",
    0xE00A: "K", 0xE00B: "L", 0xE00C: "M", 0xE00F: "P", 0xE010: "Q",
    0xE011: "R", 0xE012: "S", 0xE013: "T",
    0xE034: "1", 0xE035: "2", 0xE036: "3", 0xE037: "4", 0xE038: "5",
    0xE039: "6", 0xE03A: "7", 0xE03B: "8", 0xE03C: "9", 0xE03D: "0",
    0xE043: "*", 0xE044: "(", 0xE045: ")", 0xE046: "−", 0xE047: "=",
    0xE048: "+", 0xE049: "[", 0xE04A: "]", 0xE04B: "{", 0xE04C: "}",
    0xE04D: "|", 0xE04F: ":", 0xE052: ",", 0xE053: ".", 0xE054: "/",
    0xE055: "<", 0xE056: ">", 0xE057: "?", 0xE059: "−", 0xE05A: "→",
    0xE05B: "∫", 0xE05C: "√", 0xE05F: ".", 0xE067: "∑", 0xE06D: "/",
    0xE070: "=", 0xE071: "⇒", 0xE078: "(", 0xE079: "{", 0xE07A: "(",
    0xE07B: "|", 0xE088: "Δ", 0xE0A4: "θ", 0xE0AC: "π",
    0xE0E5: "a", 0xE0E6: "b", 0xE0E7: "c", 0xE0E8: "d", 0xE0E9: "e",
    0xE0EA: "f", 0xE0EB: "g", 0xE0EC: "h", 0xE0ED: "i", 0xE0EF: "k",
    0xE0F1: "m", 0xE0F2: "n", 0xE0F3: "o", 0xE0F4: "p", 0xE0F6: "r",
    0xE0F7: "s", 0xE0F8: "t", 0xE0F9: "u", 0xE0FA: "v", 0xE0FC: "x",
    0xE0FD: "y",
    # Pieces of extensible brackets. A plain bracket/bar is readable, but the
    # exact vertical grouping still has to be checked against the PDF image.
    0xE100: "[", 0xE101: "|", 0xE102: "]", 0xE103: "[", 0xE104: "]",
    0xE105: "|",
}


def _is_hyhwpeq(fontname):
    return str(fontname or "").split("+")[-1].casefold() == "hyhwpeq"


def repair_chars(chars):
    """Return font-scoped corrected pdfplumber chars and repair statistics."""
    repaired = []
    replaced = 0
    unresolved = Counter()
    other_private_use = 0
    for char in chars:
        original = char.get("text", "")
        if _is_hyhwpeq(char.get("fontname")):
            corrected = "".join(HYHWPEQ_GLYPHS.get(ord(glyph), glyph) for glyph in original)
            unresolved.update(glyph for glyph in corrected if 0xE000 <= ord(glyph) <= 0xF8FF)
            if corrected != original:
                char = {**char, "text": corrected}
                replaced += sum(a != b for a, b in zip(original, corrected))
        else:
            other_private_use += sum(0xE000 <= ord(glyph) <= 0xF8FF for glyph in original)
        repaired.append(char)
    return repaired, {"method": "hyhwpeq-v1", "replacedGlyphs": replaced,
                      "unresolvedGlyphs": sum(unresolved.values()),
                      "otherPrivateUseGlyphs": other_private_use,
                      "unresolvedCodes": [f"U+{ord(glyph):04X}" for glyph in sorted(unresolved)]}
