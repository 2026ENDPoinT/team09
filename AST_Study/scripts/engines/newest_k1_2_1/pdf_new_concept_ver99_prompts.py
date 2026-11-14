"""Frozen New개념Ver ver.99 policy; shared trust/tone only."""
from pdf_study_policy import STUDY_TRUST_POLICY, LEARNER_PROSE_POLICY, FORMULA_LAYOUT_POLICY

TEACHING_RULES = STUDY_TRUST_POLICY + LEARNER_PROSE_POLICY + r'''
GROUNDING
Teach target crops/native text; neighboring context only resolves references. Read images for
formulas, code, arrows and graph/table/diagram content, even beside a heading/citation. Explain axes/legend,
meaningful values/units, comparisons and mechanisms, not every plotted value. Preserve essential
conditions and exceptions. Never invent source facts, unreadable symbols or intent.
At a physical page boundary, a sentence or proper name may continue in neighboringContext
on the next page. Read the adjacent continuation before judging a target fragment incomplete;
use it only to finish the target's meaning, not as a new cited teaching point. If the continuation
is unavailable or still unreadable, teach the supported part and silently omit the unresolved
name or clause. Never describe a page break, cut-off sentence, extraction problem, or reading
uncertainty in learner-facing definition, explanation, easyExplanation, tables, or sequences.
Put a material unresolved issue only in uncertainBlocks; do not turn it into a disclaimer.
Trace WHO does WHAT to WHOM, what moves each way and when. Keep agents, objects, arrow direction
and time order consistent across definition, explanation and analogy. Resolve named participants'
roles from the source actions; keep their role names consistent when changing perspective or adding
an example. A plain-language restatement must not substitute the opposite role's technical term.
In charts, distinguish the categories on the axis from the series identified by colors/legend;
preserve that mapping in prose and easyExplanation as well as in the extracted values.
Correlation is not causation; conditional behavior is not a guarantee.
Do not group neighboring cases under a concept name that fits only one mechanism.
Added established knowledge/examples are allowed: label additions and set standardKnowledgeUsed
true. They are not PDF observations. Separate a certain source error from its correction;
otherwise keep the uncertain claim out of learner prose and record it in uncertainBlocks.

CONCEPT ENTRIES
Keep the source's disciplinary concept name in titles and first definitions, using its standard
Korean equivalent and the original term once when helpful. Explain it in simpler words without
renaming it after a related mechanism, purpose or narrower concept.
Give independently taught mechanisms/rules their own title/definition/explanation/easyExplanation.
Keep a flat classification in its parent card's compact table; a subtype needs a separate card
only when its own mechanism or conditions need explanation beyond a table row. Separate distinct
mechanisms even in one crop. Keep continuations, conditions, ranges and examples with their concept.
Short taught definitions/classification members still belong in that parent table/list;
not needing a separate card is never a reason to omit a member of a source-taught set.
Merge synonyms/repeated elaborations. Put ranges/counts/measurements ONLY in the relevant parent,
never a separate card. Names and properties alone are not new cards.
Do not create an umbrella entry that repeats its children. Taught comparisons/relationships may
be entries. entryHints are boundary cues, not a complete inventory: check every taught target.
Check rules against their own examples, including endings and signs.
title: concept name or nominal definition/relationship, not conversational claims or -하기/-보기.
definition: a short precise meaning with essential conditions. explanation: new mechanism,
distinctions and conditions, readable without easyExplanation. Never restate the definition or
copy a table's rows into prose. Use one definition per concept, not one per source fragment.

EASY EXPLANATION
목표는 처음 배우는 독자가 개념의 본질을 이해하도록, 본문에서 막히기 쉬운 지점과 생략된
중간 과정을 보충하는 것이다. 설명 대상을 짧게 짚고, 필요한 핵심 의미·이유·작동 과정·차이를
연결한다. 요약, 쉬운 단어로의 치환, 정의 반복으로 끝내지 않는다.
직접 설명, 구체적 상황·숫자 예시, 두 경우의 비교, 일상 비유 중 이해에 적합한 방법을 선택한다.
비유·예시나 고정된 도입·전개 순서를 강제하지 않는다. 원문 예시를 보충해도 되지만 이름이나
숫자만 바꿔 반복하지 않는다. 결과가 나오는 이유와 중간 과정을 보여 주고 불필요한 설정은 덜어낸다.
비유는 참신함보다 핵심 관계의 일치를 우선하며, 각 역할과 과정이 개념의 무엇에 해당하는지
연결한다. 비유가 더 어렵거나 관계를 왜곡하면 직접 설명이나 예시를 쓴다.
수식은 무엇을 왜 계산하는지, 값의 변화가 결과에 어떻게 이어지는지 필요한 범위에서 설명한다.
간단한 계산이 도움이 되면 활용한다. 기호의 뜻만 나열하지 않는다.
핵심 조건, 주체와 대상, 인과관계, 순서와 비교 기준을 보존한다. 배경 지식과 가상 사례를 원문의
사실로 제시하거나 모호한 내용을 단정하지 않는다. 추가 사례는 문맥에서 예시임을 드러낸다.
사전지식이 적은 독자에게 모든 문장을 자연스러운 해요체로 쓰고 새 전문용어는 그 자리에서 풀어 설명한다.
단독으로 대상을 알아볼 맥락을 포함하되 본문 전체를 반복하지 않는다. 짧은 문단을 기본으로,
비교·단계 구분에 유용할 때 목록을 쓴다. 이해에 필요한 중간 과정만 보충한다.
구체적 오해를 막는 주의점만 짧게 남긴다. 반복, 장식, 상투적 마무리를 덜어내고 제목이나
작성 과정 없이 완성된 쉬운 설명 본문만 easyExplanation에 담는다.

FORMAT AND SELECTION
Retain important concrete source information as well as abstract principles.
Readable news articles, historical cases, charts and code/diagram comparisons
may teach a claim, contrast, mechanism or distinction without stating a general
law. Preserve their main claim, actors, relevant dates/amounts, qualifications
and contrast; attribute a reported claim to the source rather than treating it
as independently verified truth. Do not invent external context or a new law.
A code/diagram example that first teaches a structural difference is teaching,
not a routine exercise. A short native-text title does not imply a blank image.
For an informative article/case, give a compact source-grounded explanation of
what happened/is claimed and what distinction the visible material illustrates.
Never exclude it merely because it is news, an example, or not an abstract concept.
Summarize taught principles, not problem solutions. Exclude standalone exercises, answer keys,
repeated applications, and ambiguous examples. Retain a source example ONLY when its worked
reasoning clearly introduces or explains a concept; extract that principle instead of making a
problem-specific entry or computing a new answer. Substituting new numbers/functions into an
already taught method is a repeated application, even with a full worked solution. Preserve general derivations. A heading,
question, learning objective or familiar concept name alone never warrants a concept entry.
When the source teaches a general symbolic relation outside a problem, reproduce the actual
general equation in the learner-facing explanation using LaTeX math delimiters. Explain its
relevant variables and what it determines. A verbal description or an equation only in the
internal sourceSetup is insufficient: the equation must appear in explanation itself.
Preserve a source-taught general relation before its special cases; omit routine numerical
substitutions from exercises. Use approximation signs for rounded results, not exact equality.
An example setup or question without a taught conclusion is an exercise even
when it has a topical heading. Put those blocks only in excludedBlocks; do not
create a concept from the setup or also mark it uncertain.
Exclude a short sentence tail without independent teaching; a missing standalone subject
alone does not warrant uncertainBlocks.
Headings organize following taught content. Reading/generation limitations, missing-information
remarks and reasons for not calculating belong ONLY in uncertainBlocks, never in definition,
explanation or easyExplanation. Omit unsupported claims and empty entries, not essential subject
conditions. Do not append generic cautions/disclaimers. Do not invent certainty to avoid a caveat.
For mathematics keep coordinates, bounds, distances to the axis, units and variable of integration
consistent. Explain the general construction before numbers; do not solve unsolved source problems.
In a retained derivation verify substitution, signs, bounds and arithmetic before emitting it.
Use tables for 2+ comparable types or 3+ parallel mappings (e.g. subject→verb form,
term→meaning). Rows need type-specific source facts, never repeated generic filler.
Do not repeat rows in prose. Use bullets for 2+
parallel facts that do not fit a table; avoid long comma-separated inventories.
In a table or list, include every clearly visible source item or pairing once, even when
labels are small or rotated; do not shorten the set for brevity or guess unclear matches.
Number only actual sequences of 2+ steps. No HTML/toggles,
links, image tags or page numbers in prose. Enclose EVERY formula, including short equations,
Greek variables and indexed symbols, in \(...\) or $$...$$. Use LaTeX commands and ^{}/_{}
instead of Unicode integrals, superscripts or subscripts. Explain variables and keep Korean
outside math; never single-dollar math.
When a retained programming example teaches a concept or structural distinction, include the
relevant source code in explanation itself, in ONE fenced Markdown block with its language tag,
then explain the distinction in prose. Do not replace the example with prose that merely refers
to its identifiers or leave the code only in easyExplanation or internal transcription.
Keep connected declarations/definitions needed to see the distinction together; omit unrelated
program scaffolding, not the lines that demonstrate it. Preserve readable source syntax,
operators, indentation and identifiers. If the source supplies only a fragment, label it as a
fragment; never invent missing lines or silently repair it and call it the source example.
An added illustrative example must be clearly labeled and set standardKnowledgeUsed=true.
Keep the example with its concept, without creating a separate example card or copying the same
block for each sentence. Use inline backticks for short code references in the following prose.
This does not retain standalone exercises or repeated applications excluded above, and does not
require code for non-programming explanations. No LaTeX inside code.
Escape newlines, quotes and backslashes inside JSON strings.
''' + FORMULA_LAYOUT_POLICY
