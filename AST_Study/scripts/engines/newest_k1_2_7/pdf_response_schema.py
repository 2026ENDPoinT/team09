"""Strict JSON contract for a paid page-summary response.

Keep this schema limited to fields consumed by the map stage. Legacy paid JSON
responses remain readable from their existing cache without another API call.
"""


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


_STRING = {"type": "string"}
_BOOL = {"type": "boolean"}
_STRINGS = {"type": "array", "items": _STRING}
_PAGES = {"type": "array", "items": {"type": "integer"}}
_EVIDENCE = {"type": "array", "items": {"$ref": "#/$defs/evidence"}}
_SEQUENCE = {"anyOf": [{"$ref": "#/$defs/sequence"}, {"type": "null"}]}


def sequence_order_fields():
    # Shared by the native-region and legacy summary contracts. These are
    # witnesses produced in the same request, not a paid review stage.
    return {"orderKind":{"type":"string","enum":["process","procedure","derivation","cycle"]},
            "transitions":{"type":"array","items":_object({
                "fromStep":{"type":"integer"},"toStep":{"type":"integer"},
                "relation":{"type":"string"},"blockIds":{"type":"array","items":{"type":"string"}},
                "sourceQuote":{"type":"string"}})}}

PAGE_MAP_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "synesis_page_map_v1",
        "strict": True,
        "schema": {
            **_object({
                "summary": {"$ref": "#/$defs/summary"},
                "concepts": {"type": "array", "items": {"$ref": "#/$defs/concept"}},
                "processingNotes": _STRINGS,
            }),
            "$defs": {
                "evidence": _object({"sourceId": _STRING, "quote": _STRING}),
                "step": _object({"title": _STRING, "body": _STRING,
                                 "context": _STRING, "insight": _STRING,
                                 "evidence": _EVIDENCE}),
                "sequence": _object({"title": _STRING, **sequence_order_fields(),
                                     "steps": {"type": "array", "items": {"$ref": "#/$defs/step"}}}),
                "part": _object({"title": _STRING, "body": _STRING,
                                 "easyExplanation": _STRING, "standardKnowledgeUsed": _BOOL,
                                 "evidence": _EVIDENCE, "visualPages": _PAGES,
                                 "coveredElementIds": _STRINGS, "sequence": _SEQUENCE}),
                "summary": _object({"title": _STRING,
                                    "parts": {"type": "array", "items": {"$ref": "#/$defs/part"}},
                                    "excludedElementIds": _STRINGS,
                                    "easyExplanation": _STRING,
                                    "standardKnowledgeUsed": _BOOL,
                                    "visualPages": _PAGES}),
                "concept": _object({"name": _STRING, "aliases": _STRINGS,
                                    "definition": _STRING, "explanation": _STRING,
                                    "easyExplanation": _STRING, "example": _STRING,
                                    "confusion": _STRING, "standardKnowledgeUsed": _BOOL,
                                    "evidence": _EVIDENCE, "visualPages": _PAGES,
                                    "sequence": _SEQUENCE}),
            },
        },
    },
}
