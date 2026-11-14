# SlideLens AI prompt archive

Preserved from the active PDF prompts on 2026-10-01. This file is not loaded into AI requests. The SlideLens implementation and display code remain available for previously generated content and future use.

## Page image analysis (`pdf_page_analysis.py`)

```text
For SlideLens, select only regions whose ORIGINAL VISUAL APPEARANCE adds understanding after
the formulas and explanation have been rendered in the summary. A formula's importance or ID
does NOT justify a lens. Formula-only regions use lensReason=none, except unreadable originals
or meaningful spatial annotations. A diagram linked to a formula can use diagram_relation.
```

The former location instruction ended with: `Use null if uncertain about location: the app will offer the full page. A valid box is not proof of accuracy.`

The former element schema included:

```text
lensReason:"none"|"diagram_relation"|"layout"|"annotation"|"unreadable"
```

## Shared summary policy (`pdf_page_analysis.py`)

```text
A lens ID or importance never replaces a formula. Do not use formula-only crops when the body can express the formula.
Keep the summary useful with every lens closed. Select a lens only for additional visual value.
```

## Page summary and concept generation (`pdf_ai.py`)

The former output schema included these two contiguous prompt fragments. The request payload also included `regionCatalog: prompt_catalog(region_catalog)`.

```text
Return {summary:{title,parts:[{title,body,easyExplanation,standardKnowledgeUsed:boolean,evidence:[{sourceId,quote}],visualPages:[int],slideLensRegionId:string,sequence:null|{title,steps:[{title,body,context,insight,evidence:[{sourceId,quote}]}]}}],easyExplanation,standardKnowledgeUsed:boolean,visualPages:[int]}, concepts:[{name,aliases:[string],
definition,explanation,easyExplanation,example,confusion,standardKnowledgeUsed:boolean,evidence:[{sourceId,quote}],visualPages:[int],slideLensRegionId:string,sequence:null|{title,steps:[{title,body,context,insight,evidence:[{sourceId,quote}]}]}}],processingNotes:[string]}.
```

```text
SlideLens unfolds a source crop with surrounding padding, or the full page when location is uncertain. regionCatalog lists approved semantic regions (legacy documents may have local object regions). Choose one listed regionId in slideLensRegionId ONLY when its original visual appearance adds understanding beyond the body formulas and explanation, and its page is supported by evidence or visualPages. A tracking ID never requires a lens. Use an empty string otherwise. Place the standalone line [[SLIDE_LENS]] once after the related paragraph in the summary part body or concept explanation, between Markdown blocks, never inside code or a table. Keep formulas and essential explanations in the body even with the lens closed. Do not invent IDs, coordinates or claims of inspecting unavailable visuals.
```
