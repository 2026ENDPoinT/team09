"""Detect a model's accidental language switch in student-facing PDF explanations.

Source quotations and source-language transcription are intentionally excluded.
"""
import re

HANGUL = re.compile(r"[가-힣]")
HAN = re.compile(r"[\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
STUDY_FIELDS = {"title", "body", "name", "definition", "explanation",
                "easyExplanation", "example", "confusion", "context", "insight"}
ANALYSIS_FIELDS = {"label", "title", "description", "purpose", "contextSummary",
                   "relationships", "uncertainDetails"}
STRICT_KOREAN_RETRY = (
    "\nLANGUAGE CORRECTION REQUIRED: The prior response switched to Japanese or Chinese. "
    "Every interpretation, summary, heading, concept name, definition, explanation, "
    "diagram description and learning note MUST be written in natural Korean. "
    "Preserve exact source-language text only inside source transcription and direct "
    "quotes; never translate or invent source text. If the PDF itself is Korean, "
    "transcribe its visible Korean words in Korean. Keep code, formulas, proper names "
    "and established technical symbols unchanged. Check every JSON string before replying."
)


def foreign_prose(text):
    if not isinstance(text, str) or not text.strip():
        return False
    hangul = len(HANGUL.findall(text))
    han = len(HAN.findall(text))
    kana = len(KANA.findall(text))
    return (kana >= 2 or (kana >= 1 and han >= 2 and hangul == 0)
            or (han >= 8 and han > 2 * hangul))


def _issues(value, fields, path=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}" if path else key
            if key in fields:
                if isinstance(child, str) and foreign_prose(child):
                    found.append(location)
                elif isinstance(child, list):
                    found.extend(f"{location}[{i}]" for i, item in enumerate(child)
                                 if isinstance(item, str) and foreign_prose(item))
            if isinstance(child, (dict, list)):
                found.extend(_issues(child, fields, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                found.extend(_issues(child, fields, f"{path}[{index}]"))
    return found


def study_issues(value):
    """Check authored study prose while leaving evidence quotes in the source language."""
    if not isinstance(value, dict):
        return []
    return _issues(value, STUDY_FIELDS)


def analysis_issues(value, source_text=""):
    if not isinstance(value, dict):
        return []
    found = _issues(value, ANALYSIS_FIELDS)
    if len(HANGUL.findall(source_text)) >= 12:
        for index, element in enumerate(value.get("elements", [])):
            if isinstance(element, dict) and foreign_prose(element.get("transcription")):
                found.append(f"elements[{index}].transcription")
    return found


def generated_issues(value):
    """Check only visible generated content, including saved partial page results."""
    if not isinstance(value, dict):
        return []
    if "study" in value and isinstance(value["study"], dict):
        return study_issues(value["study"])
    selected = {key: value[key] for key in ("summary", "overview", "sections", "concepts") if key in value}
    return study_issues(selected)
