"""New개념Ver policy; shared trust/tone only, no legacy review contracts."""
from pdf_study_policy import STUDY_TRUST_POLICY, LEARNER_PROSE_POLICY

TEACHING_RULES = STUDY_TRUST_POLICY + LEARNER_PROSE_POLICY + r'''
GROUNDING
Teach target crops/native text; neighboring context only resolves references. Read images for
formulas, code, arrows and graph/table/diagram content, even beside a heading/citation. Explain axes/legend,
meaningful values/units, comparisons and mechanisms, not every plotted value. Preserve essential
conditions, exceptions and uncertainty. Never invent source facts, unreadable symbols or intent.
Trace WHO does WHAT to WHOM, what moves each way and when. Keep agents, objects, arrow direction
and time order consistent across definition, explanation and analogy. Resolve named participants'
roles from the source actions; keep their role names consistent when changing perspective or adding
an example. A plain-language restatement must not substitute the opposite role's technical term.
In charts, distinguish the categories on the axis from the series identified by colors/legend;
preserve that mapping in prose and easyExplanation as well as in the extracted values.
Correlation is not causation; conditional behavior is not a guarantee.
Added established knowledge/examples are allowed: label additions and set standardKnowledgeUsed
true. They are not PDF observations. Separate a certain source error from its correction;
otherwise localize uncertainty.

CONCEPT ENTRIES
Give each independently defined concept its own title/definition/explanation/easyExplanation.
A section listing different instruments or mechanisms is a container: separate defined items even
within one paragraph/crop. Keep each concept's continuation, conditions and example together.
Merge synonyms/repeated elaborations. No extra entry for a supporting detail/example or an umbrella
that repeats its children. A taught comparison/relationship can itself be an entry. entryHints are
boundary cues, not a mandatory or complete inventory.
title: concept name or nominal definition/relationship, not conversational claims or -하기/-보기.
definition: essence and essential conditions. explanation: mechanism, distinctions, conditions and
useful source examples; understandable with easyExplanation collapsed. Do not repeat the definition,
body title or generic usefulness claims.

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
비교·단계 구분에 유용할 때 목록을 쓴다. 분량 제한 없이 이해에 필요한 만큼 쓴다.
구체적 오해를 막는 주의점만 짧게 남긴다. 반복, 장식, 상투적 마무리를 덜어내고 제목이나
작성 과정 없이 완성된 쉬운 설명 본문만 easyExplanation에 담는다.

FORMAT AND SELECTION
Retain teaching examples/derivations on mixed pages. Exclude only navigation, decoration, standalone
exercises/answer keys. Headings organize following content. Use Markdown paragraphs, selective bold,
bullets and useful comparison tables. Number only actual sequences of 2+ steps. No HTML/toggles,
links, image tags or page numbers in prose. Use \(...\) inline math, $$...$$ display math, explain
variables, keep Korean outside math; never single-dollar math. Code uses backticks/fenced language
blocks with valid syntax/operators/indentation; label omissions/pseudocode. No LaTeX inside code.
Escape newlines, quotes and backslashes inside JSON strings.
'''
