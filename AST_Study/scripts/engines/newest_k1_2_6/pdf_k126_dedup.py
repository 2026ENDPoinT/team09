"""Consolidate duplicate teaching instructions for the comparison profile."""
from pdf_k123_policy import METHOD_SELECTION_RULES, SYNTHESIS_RULES

_SUBSTITUTIONS = (
    (r'''Read every supplied target and account for it, but do not turn reading coverage into a
requirement to reproduce every sentence, value or label. First identify the current unit's
central idea, supporting relationship and necessary conditions. Explain those directly.
Integrate supporting examples into that explanation; omit redundant numerical substitutions,
incidental inventories, repeated evidence and decorative description. A source block may be
represented by its essential relationship with its blockId; its every datum need not be printed.
Do not invent additional concepts to fill the source inventory or a fixed output length.''',
     r'''Read and account for every supplied target. Teach each distinct source relationship once,
with its actors, assumptions, exceptions, branches and mechanisms. When several blocks teach
the same rule, cite all contributing blockIds in the explanation of that rule and preserve
meaningful contrasts. Merge supporting examples and omit redundant substitutions, evidence,
decorative detail and incidental inventories. Use the length required to teach the actual
material without inventing filler or treating each source fragment as its own concept.
Retain a representative printed value when it supports a teaching point.'''),
    (r'''If the classification itself is the lesson, preserve its members compactly. A long data table
whose purpose is a trend or contrast may be represented by the relationship and representative
rows instead.''',
     r'''If a classification is the lesson, preserve all taught members and their relationships in one
concept. Give a member a separate concept only for an independently useful rule or condition.
For a long data table that teaches a trend or contrast, give the relationship and representative
rows that support it.'''),
    (r'''Every independent entry MUST include both a definition and an explanation segment.
A newly
introduced independent principle is not a continuation simply to omit its meaning.
easyExplanation is OPTIONAL:
- definition: a concise precise meaning or central relationship with essential conditions.
- explanation: develop the reasoning, mechanism, distinctions or evidence needed to understand
  it; do not repeat the definition or merely list source observations. Several paragraphs may
  have different supporting blockIds. The main explanation must be understandable by itself.
- easyExplanation: add this only for a specific likely difficulty a first-time learner can
  have with the concept. An accurate, self-contained main explanation can still be dense:
  a symbolic step, an abstract mechanism or two confusable quantities may need an intuitive
  bridge. Do not omit that bridge merely because the main body is technically correct.
  State the missing intermediate link
  in plain language, then connect it back to the actual term, symbol or mechanism. A small
  concrete example or comparison is useful only when it exposes that link; no analogy is
  required. Preserve roles, conditions, variable meanings and causal direction. Check any
  new example against the same source rule, including its initial/boundary conditions,
  every displayed step and its claimed result. Omit an unsupported optional example.
  A shorter paraphrase, repeated photo description, generic study advice, or another warning
  about what cannot be concluded adds no teaching value: return NO easyExplanation segment.
  Do not move an essential formula or qualification out of the main explanation into this
  optional segment. Do not add text merely to fill all segment kinds.
Before the learner segments, choose sourceSetup.learnerDifficulty. Use kind=none
for an immediately understandable observation, caption or simple definition. Otherwise choose
symbol_meaning/intermediate_step/mechanism/distinction and identify internally the SPECIFIC learner question
that easyExplanation will answer, such as why one step follows, what a symbol tracks, or which
condition separates two similar ideas. Do not use generic questions like "무슨 뜻인가요?".
Answer that question directly in easyExplanation with a short chain of reasoning. Example of
a useful bridge: explain why the same term disappears from both sides and what remaining
quantity still changes. Example of no added value: restate the equation or append "단정할 수
없어요". This is a teaching choice, not a quota; never make every concept use the same choice.
Merge synonyms and repeated elaborations. Keep examples, measurements and conditions with
their concept; do not make a card for each row, source fragment or example. Split genuinely
independent mechanisms. Avoid an umbrella card that merely repeats all child cards.''',
     r'''Every independent concept requires both definition and explanation. Use the definition for
meaning and essential conditions, and the explanation for the reasoning, mechanism, evidence
or distinctions. Keep MAIN self-contained with all essential formulas and qualifications.
Use each paragraph's own blockIds. Merge synonyms and repeated elaborations. Keep examples,
measurements and conditions with the concept they support, and split independent mechanisms.

Before writing learner segments, choose sourceSetup.learnerDifficulty.kind. Use none for an
immediately understandable observation, caption or definition. Otherwise select
symbol_meaning/intermediate_step/mechanism/distinction and identify the specific difficulty.
Add easyExplanation only when it supplies a missing link or clearer representation. Explain
that link briefly in plain language and connect it to the concept. A small example or analogy
is useful when it exposes that link. Verify its roles, conditions, variable meanings, causal
direction, intermediate steps and result. Omit paraphrases, repeated photo descriptions,
generic advice and unsupported examples. A dense but correct MAIN may still need this bridge.
Do not move essential material out of MAIN or fill a segment merely because it exists.'''),
    (r'''For a retained derivation check signs, substitutions, bounds, coordinate direction and units.
Do not solve a standalone source exercise. Use approximation signs for rounded equalities.''',
     r'''For each retained derivation or worked chain check that adjacent steps preserve identities,
substitution signs, root and domain branches, coefficient bounds, coordinate direction and
units. For a ratio A/B, state what A and B mean in that order. Use approximation signs for rounded equalities.'''),
    (r'''one language-tagged fenced block in explanation, followed by its meaning. Preserve syntax,
operators and indentation; omit unrelated scaffolding.''',
     r'''one language-tagged fenced block in explanation, followed by its meaning. Preserve syntax,
operators, array branch behavior and indentation; omit unrelated scaffolding.'''),
    (r'''
FINAL SOURCE AND LEARNER CHECK (within this same response)
Account for every target by its actual contribution, a justified exclusion or uncertainty.
Reading a whole image does not require describing every object or reproducing its solution.
Cite the actual formula/diagram/result used, not only its caption. Inspect a short native
string's image before treating it as empty. Keep headings/footers as internal layout records.
Retain the essential general relationship and conditions; routine example answers may be
omitted. Preserve valid statements when a separate source statement is genuinely conflicting.
A source discrepancy needs two conflicting source facts, not your unverified calculation.
Respect source-stated approximations; displayed rounded intermediate values are not exact
operands. Use original-input expressions with \approx for the printed rounded answer.
For a ratio A/B, name numerator and denominator in that order in its definition. For code,
trace the action on both true and false branches, including continuation and exit. For a
diagram distinguish alternative paths from consecutive segments before adding quantities.
Never replace an expression with an empty line or control escape. An unrecoverable expression
is uncertainty for that claim; keep other supported paragraphs. Use neighboring native source
premises to read split conclusions, never infer premises from a generated title.
Check that each concept adds independent teaching. Merge a supporting case/photo into the
concept it supports. Omit easyExplanation when no additional explanatory link is needed.
Keep internal boundary checks internal: learner prose should make a justified positive claim.
Explain a limitation only when it changes the meaning of that claim or corrects a likely
specific misunderstanding; do not warn against comparisons or conclusions the lesson never makes.
''',
     r'''
FINAL CHECK
Cite the actual formula, diagram or result used, including its constituent source IDs.
Inspect the supplied image before treating a short native string as empty. Keep headings
and footers as internal layout records. Use neighboring native premises to read split
conclusions. Preserve valid source statements when a separate source statement conflicts.
Use original-input expressions with \approx when retaining an essential rounded result.
Represent an unrecoverable expression as uncertainty and retain other supported material.
Never replace an expression with an empty line or control escape. Keep internal checks
out of learner prose.
'''),
    (SYNTHESIS_RULES, ''),
    (METHOD_SELECTION_RULES, ''),
)


def deduplicate_instructions(instructions):
    """Apply the same consolidation to ordinary and exercise-specific requests."""
    for repeated, concise in _SUBSTITUTIONS:
        if instructions.count(repeated) != 1:
            raise ValueError("Could not locate a single expected prompt passage")
        instructions = instructions.replace(repeated, concise, 1)
    return instructions
