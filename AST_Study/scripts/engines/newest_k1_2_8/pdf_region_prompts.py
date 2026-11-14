"""Teaching policy adapted from pdf_study_policy for a single concept object.

Keep the shared trust/tone rules. The old part/card duplication, page inventories,
boundary-review contracts, and field names are deliberately not composed here.
"""
from pdf_study_policy import STUDY_TRUST_POLICY, LEARNER_PROSE_POLICY

TEACHING_RULES = STUDY_TRUST_POLICY + LEARNER_PROSE_POLICY + r'''
SOURCE AND SCOPE
Teach the concepts in the target PDF regions. Context helps resolve references but is not extra
target material. Preserve essential conditions, distinctions, exceptions, quantities and units.
Read original images for formulas, code, tables, graphs and visual relationships; native text can
be corrupted. Explain the mechanism and relevant variables or steps. Do not invent unreadable
symbols, source observations or lecturer intent. If a source error is certain, distinguish the
source claim from the established correction; otherwise localize the uncertainty.
You may add established undergraduate knowledge and clearly labeled illustrations to explain
the source concept. Set standardKnowledgeUsed=true for such additions. Added examples are not
PDF facts, and source references do not independently verify an added illustration.

ONE CONCEPT, ONE TEACHING ENTRY
Make an entry for each distinct reusable concept, mechanism, formula or measure actually taught.
Group repeated elaborations and synonyms; distinguish genuinely different concepts. A topic can
have multiple entries. A heading or unanswered question alone is not a taught concept.
title: name the concept or use a concise nominal definition/relationship phrase. Do not use
conversational assertions, activity titles (-하기/-보기), or repeat the title in the body.
definition: state what the concept means, retaining essential technical conditions.
explanation: develop how/why it works, its conditions and useful source examples. It must be
understandable with the easy explanation collapsed. Avoid repeating the definition verbatim.

EASY EXPLANATION
Teach the essential content of this entry by a concrete, beginner-friendly route. Explain what
the idea is, how/why it works, and the necessary distinctions and conditions. There is no character,
sentence or paragraph quota. Use the space needed for understanding and remove repetition.
For an abstract idea or unfamiliar mechanism, include a fresh everyday analogy or small worked
example. Walk through what happens and map its roles to the concept, connecting to source notation
when useful. The situation must materially differ from the source example; merely renaming its
objects is insufficient. Label it '비유' or '추가 예시', and explain an analogy's limit when it could
mislead. A familiar concrete definition needs no forced analogy. Do not merely paraphrase the
formal explanation or say the concept is useful. Keep every entry self-contained.

SELECTION AND FORMATTING
Retain teaching definitions, mechanisms, derivations and embedded examples. Exclude navigation,
decorations, standalone practice questions and answer keys. Preserve teaching on mixed pages;
do not exclude something merely because its title contains 'example'. Unreadable is not irrelevant.
Use Markdown paragraphs, selective bold, bullets for parallel items and numbering only for an
actual sequence of two or more steps. Never prefix a sole explanation with '1.'. Use a compact
comparison table only when it improves clarity. No HTML, links, image tags, toggle tags or page
numbers in prose; source IDs provide references and the app supplies easy-explanation toggles.
Use \(...\) for inline mathematics and $$...$$ for displayed equations, with relevant variables
explained; never single-dollar math. Keep Korean prose outside math. Put actual code fragments
in backticks, multi-line code in fenced blocks with language tags. Preserve code operators,
quotes and indentation. New illustrative code must be valid, with omissions/pseudocode labeled.
Do not mix LaTeX into code spans. JSON strings must correctly escape newlines and backslashes.
'''
