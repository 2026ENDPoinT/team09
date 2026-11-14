"""Same-request example selection and bounded, source-only sibling context.

The image-reading model decides. Assembly applies its explicit disposition to
the cited learner text before that text is combined into cards.
"""
from collections import Counter
import copy

VERSION = 'k124-source-example-selection-v32'

WORKED_METHODS_FIELD = 'workedMethods'
EQUATION_KIND = 'equation'
METHOD_PRINCIPLE = 'principle'
CONTENT_ROLE = 'contentRole'
VISIBLE_ROLES = ('instruction', 'evidence')
HIDDEN_ROLES = ('instance', 'hypothesis')

VISUAL_WORKSHEET_RULES = '''
The owned pages may be independent exercises. Account for every page on its own
evidence before excluding it. Do not assume a method was already taught because
it is standard coursework. If a solved page shows a numerical rule's grid and
weights, a zero-error criterion, a transformed differential/bound, or a new
reduction technique, keep that reusable relation even when the printed result
is optional. Repeat only one general principle where the same method was
actually demonstrated on another supplied page.

In every equation learned from a worked solution, replace the problem's bound,
chosen exponent, exact numerator, sample interval width or sample threshold
with a variable and state its needed condition. An identity valid at all inputs,
such as a half-angle factor, stays as written. An evaluated tail or antiderivative
for the assigned example is never a teaching equation. Show the general
operation or reduction instead. Preserve the choice and why it works, including
any partial-fraction form, quadrature weights, change of limits or endpoint
offset actually shown. Keep one coordinate throughout the prose and formula.
Use complete equations and well-delimited inline math. Keep the Korean prose
readable and do not introduce a new example to replace an omitted one.
'''

SOURCE_SELECTION = '''
Select by the source's instructional contribution before writing prose.
• Theory and evidence: retain every distinct definition, factual observation,
  mechanism, graph operation, code branch and condition in the owned targets.
  Unit titles guide organization only; teach independently headed theory too.
• Worked instruction: put a method demonstrated in the source and absent from
  surrounding theory in workedMethods. Give the symbolic setup and why it
  works, with essential conditions, using variables for the exercise's givens.
• Application only: the task, exact givens, instances of an existing formula,
  and answers do not belong in learner text. A final answer can be an expression,
  a graph reading, a requested product, or a hypothetical decision.

A nontrivial substitution with its transformed measure/domain, or building a
new model's varying factor from a diagram, teaches a construction. Rearranging
or combining already taught equations to get the requested unknown, tracing one
execution or graph, and comparing invented input/output values do not. A worked
solution must show the method itself, not just state an answer. Do not derive a
method from an unanswered prompt. Retain real data and explicit theory, even if
it appears on a question, learning-objective or worked-example page.

Before excluding a worked region, mentally remove its particular givens and
outcome. If the rest defines a named mechanism or explains who gives what to
whom and what a difference measures, keep those relationships in MAIN with the
region's own IDs. A heading or nearby definition without the relationship does
not replace it. Drop the scenario's specific names, amounts, sample periods
and decision. Keep the names of actual mechanisms and institutions. For reported
data, link each comparison to its own printed category, units and period and
preserve exceptions. For hypothetical outputs, keep the underlying relationship.
Do not omit an explicit definition on an optional-looking slide.
Before excluding a named example or small secondary heading, identify whether it
defines a category, its members or their distinct roles. Actual institution or
protocol types and their separate sources, actions and limits belong in MAIN.
'''

WORKED_METHODS_RULES = r'''
WORKED SOLUTION → REUSABLE INSTRUCTION
First read the worked steps, including images whose native text only contains a
title. Before writing the regular concepts, fill workedMethods with the actual
learner-facing concepts supported by worked solutions. For each worked method,
read the source and record its decisive relations in sourceSetup before writing
the principle. For a spatial setup, verify which physical endpoint has zero
coordinate, what depth/width is present at that endpoint, and whether each
increases or decreases toward the other endpoint. For an error bound, retain
the source-demonstrated reason the bound is zero, when the source supports it.
Each entry has a principle with text and blockIds. That text is the learner's
definition: state the reusable method and when it applies in one or two connected
Korean sentences on one line, before giving steps. Put longer derivations and
displayed formulas in segments.
In segments, give the method's explanation and equations without repeating the
principle. Both arrays appear in the same lecture. Do not repeat a workedMethods
entry in concepts. Write [] when no solution introduces something to teach.

Imagine erasing the particular givens and final result from each worked source.
What still teaches how to approach the next problem? Keep any source-demonstrated
choice of method, transformation, validity condition, symbolic construction,
geometric relation, derivation or error criterion in MAIN. Include how to recognize
when to use it, the decisive operations, the equivalent general unevaluated
expression and the conditions needed to use it, as applicable. Use the actual
nontrivial technique shown, even when the heading is a question and the source
introduces it only through the worked steps. A problem followed by a bare answer
does not demonstrate a method, even if you can infer one from the question.
Applying a rule already taught with the same construction and changing only
operands, or rearranging a previously taught equation, does not demonstrate a
new one. A common topic or presumed prior coursework does not establish that
repetition. If this method is independently explained in the supplied theory,
write it once there. A title hint can never exclude owned theory: explain a
separate definition, model or graph relation even if it falls outside the title.

Check each owned worked region for a concrete transferable step before deciding
it is pure_practice. For example, retain the substitution, transformed differential
and limits together; retain the surface radius and arc-length factor together;
retain the definition of the coordinate with its bounds and any sign/domain
condition. For an algorithm retain the branches and their effects. These are
examples of what to inspect, not a checklist of content to invent.

Stop at the general setup, even if the printed answer is a function or a proof's
exercise-specific result. Preserve an identity or intermediate reduction when
it is the transferable technique, but do not finish the individual exercise.
Read the exact givens in the source; in learner text replace arbitrary functions,
input numbers, lengths, rates, and bounds with named parameters or functions.
For example, an offset-axis volume setup needs radii measured from the axis,
not the actual axis value or the problem's curves; show the shell/washer setup
using boundary functions and an axis parameter. A hypothetical table of numeric
outputs is just repeated substitution. Teach its comparison and who does what
in general terms; do not reproduce the rows, example participants, price range,
or conclusion about the particular transaction. A general explanation cannot
end with a sentence that restores the exact givens. These boundaries apply to
BOTH arrays, tables, sequences and Easy. Keep real observations and numerical
constants intrinsic to the method. Real data, empirical cases, protocol examples
that define actual fields, and factual comparisons retain their useful detail.

For a geometry model use ONE coordinate for the origin/direction, occupied
interval, varying width/radius and travel/depth. Check at both physical endpoints
in sourceSetup that these quantities agree with the drawing and formula. For a
nested code operation distinguish the returned object from the outer operation's
destination; the return expression supplies the outer input where it appears.
Leave out unrelated hypothetical execution. A block cited for a workedMethods
entry is not pure_practice.

Never copy hypothetical input/output pairs as representative evidence, including
in otherwise factual paragraphs. Keep the comparative mechanism and remove the
hypothetical names and values. For a factual classification, connect each item
to its OWN reference entity and condition; do not copy the preceding item's place
or condition. When comparing a graph's slope and area, state the axes and each
distinct operation explicitly with its physical meaning.

For the method, write the necessary algebraic relation directly, with its
limits, differential or intermediate identity when it determines the result.
Write any formula a sentence introduces immediately and completely. Use one
complete display for multi-factor expressions. Keep units/conditions attached.
Use an approximation for a finite expression after dropping a small nonzero
term. When checking a diagram, preserve the original physical endpoints in
sourceSetup and verify the symbolic generalization there. Omit checks of the
individual exercise answer and omit speculative cases absent from source code.
If a domain boundary is part of the lesson, substitute each boundary into the
actual retained expression before asserting its status; even powers give the
same terms at opposite points. For a geometry/axis setup retain the side and
intersection assumptions under which its slices do not overlap.

In either learner array, use a segment of kind equation for each central displayed
formula. Its text is only complete TeX without dollar signs or outer math delimiters.
Place it immediately next to its meaning and conditions in the learner segments,
with the source IDs that actually demonstrate it. Do not omit a promised formula
or leave it only in sourceSetup. Inline symbols may remain in ordinary prose.
Do not place the exercise's evaluated or special-case expression in any segment.
If an equation uses a depth or distance measured from another location, name
its origin and positive direction exactly once, and state the offset needed to
obtain the absolute depth or travel. Do not give an alternate origin later.
Write a precise inequality with its original symbols, and do not duplicate it
with a prose comparison that may reverse the terms. Make a claim about every
country, class or series only if the corresponding row or formula supports it.
For a finite approximation after dropping a term, write \approx, not equality.
For a substitution retain the next reusable operation after the change of variable
as well, such as the form of a decomposition or identity. For a question whose
steps only rearrange known laws, exclude its symbolic solution too. If a new
condition for choosing a root is genuinely taught, keep the condition and the
general relation it constrains, never the solved root of that problem.
For graph panels, link each depicted axis pair to both taught operations, even
if its derivative or integral was taught separately. A signed area giving a
change is not an accumulated magnitude unless the relevant sign is fixed.
Treat a demonstrated exactness property, a proof across classes of inputs, or
why a term vanishes in an improper limit as a method contribution if it is
established by the source. Extract the reason and scope, not the result for the
particular polynomial, function or starting value. A repeated technique means
the actual method was shown in the supplied theory, not merely that the
calculation is routine for someone who already knows it.
Keep a reusable short derivation when shown, including the reason for a series
to converge and what each factor or parameter represents. Verify a description
of a factor against the formula, so prose does not introduce a discount, a
direction, or a condition that the formula lacks. Explain using cohesive prose;
do not put line breaks around single inline symbols.

Selection contrasts (illustrations of the policy, not source facts):
- A meeting problem formed by equating two previously taught position laws is
  routine. A positive root, an elapsed time, a distance or a requested product
  obtained from those laws is still the answer, even if written only in letters.
  Keep a new coordinate method or physical law only if the source teaches one.
- A solved numerical approximation that exhibits a previously untaught weighting
  rule, choice of grid or exactness condition contributes that rule and scope.
  Write the symbolic weighting/setup; omit the particular integrand and result.
- If a program's inner call returns a reference used in another expression,
  name the actual consuming operand and its separate destination in MAIN.
  Do not add a hypothetical aliasing hazard, error, fix or extra trace unless
  the source explicitly discusses that input or failure mode.
- For a perpendicular slice around an offset axis, derive the inner and outer
  radii from the two boundary distances and state when the annulus applies.
  Do not exchange the side of the axis in the prose and equation; use a single
  explicitly declared case or an absolute-distance expression with its scope.

Use each distinct definition's own source wording for a name, geographic
criterion, or boundary condition. In a list of similar categories, make the
different entity or location explicit on each row instead of reusing a neighbor's
criterion. A generalized claim learned only from a worked source still cites
that source: a nearby heading or another example does not demonstrate it.

For code that deletes or reassigns a member, track values in execution order.
If two references denote the same object, changing its member through one
reference changes what the other reference reads. A subsequent read through the
new pointer is not a read through the original released pointer. If the source
does not actually teach the hypothetical scenario, omit that scenario entirely.

For a reusable calculation retain the unevaluated symbolic form of the method.
Replace example-only bounds, coefficients and integrands with parameters. Stop
before an evaluated antiderivative, tail or root for the supplied problem, even
if the exercise prints it symbolically. Use the standard LaTeX name of each
function intact; prefer the spelled-out Korean term to broken inline symbols.

Earlier teaching fragments are incomplete original source text for checking
repetition only. They are not targets and have no citable IDs. If the worked
steps merely combine those laws to compute the requested instance, omit them.
Where the example introduces a business or legal mechanism, keep how the parties
interact, what changes hands, and the general meaning of a difference or rate.
The scenario's names, figures and verdict do not establish that mechanism.

For each segment, table and sequence, classify contentRole before writing its
text. Use instruction for a reusable principle, its demonstrated method and
actual source conditions. Use evidence for actual observations, historical cases
and factual category mappings. A specific exercise setup/solution/answer or a
row of invented input and output values is instance, even if it uses letters.
An extra scenario or warning about an input not taught by the source is hypothesis.
Only instruction and evidence are rendered. Normally omit instance and hypothesis
altogether. Never mix them into a teaching paragraph: split off the useful lesson.
A source's shown code is instruction; a conjecture about a same-object input
that it does not discuss is hypothesis. An uncertainty marker is instruction
when it is needed to report unreadable owned teaching. Keep a citation for
the exact region that demonstrates the retained rule.
'''


def encode_worked_methods(request):
    """Expose a method-first learner channel without changing the stored contract."""
    root = request['response_format']['json_schema']['schema']
    properties = root['properties']
    segment_schema = properties['concepts']['items']['properties']['segments']['items']
    for schema in (segment_schema, properties['tables']['items'], properties['sequences']['items']):
        schema['properties'] = {CONTENT_ROLE: {'type': 'string', 'enum': list(VISIBLE_ROLES + HIDDEN_ROLES)},
                                **schema['properties']}
        schema['required'].insert(0, CONTENT_ROLE)
    segment_kinds = segment_schema['properties']['kind']
    segment_kinds['enum'].append(EQUATION_KIND)
    methods = copy.deepcopy(properties['concepts'])
    item = methods['items']
    segment = item['properties']['segments']['items']
    segment['properties']['kind']['enum'].remove('definition')
    from pdf_response_schema import _object
    from pdf_k124_method_templates import METHOD_TEMPLATE, NO_TEMPLATE, TEMPLATES, TEMPLATE_RULES
    principle = _object({
        'text': {'type': 'string', 'pattern': r'^[^\u0000-\u001f\u007f]{1,450}$'},
        'blockIds': copy.deepcopy(segment['properties']['blockIds']),
    })
    props = item['properties']
    blocks = request['job']['blocks']
    worksheet = provisional_application(blocks) and len({block['page'] for block in blocks}) >= 4 and all(
        block.get('hasVisual') for block in blocks)
    if worksheet:
        props = {'title': props['title'], 'sourceSetup': props['sourceSetup'],
                 METHOD_TEMPLATE: {'type': 'string', 'enum': [NO_TEMPLATE, *TEMPLATES]}, **props}
        item['required'].append(METHOD_TEMPLATE)
        request['_checkedWorksheetOutput'] = True
    item['properties'] = {'title': props['title'], 'sourceSetup': props['sourceSetup'],
                          **({METHOD_TEMPLATE: props[METHOD_TEMPLATE]} if worksheet else {}),
                          METHOD_PRINCIPLE: principle, **props}
    item['required'].insert(item['required'].index('sourceSetup') + 1, METHOD_PRINCIPLE)
    root['properties'] = {WORKED_METHODS_FIELD: methods, **properties}
    root['required'].insert(0, WORKED_METHODS_FIELD)
    request['instructions'] += WORKED_METHODS_RULES
    if worksheet:
        request['instructions'] += VISUAL_WORKSHEET_RULES + TEMPLATE_RULES
    return request


def display_equation(text):
    tex = text.strip()
    for start, end in (('$$', '$$'), (r'\[', r'\]'), (r'\(', r'\)')):
        if tex.startswith(start) and tex.endswith(end) and len(tex) > len(start) + len(end):
            tex = tex[len(start):-len(end)].strip()
            break
    return '$$' + tex + '$$' if tex else ''


def merge_worked_methods(raw, exact):
    """Normalize both wire channels before citation indexing and ownership checks."""
    if not isinstance(raw, dict) or WORKED_METHODS_FIELD not in raw:
        return raw
    value = dict(raw)
    methods = value.pop(WORKED_METHODS_FIELD)
    from pdf_k124_method_templates import render_method_template

    def learner_records(records):
        for record in records:
            if record.get(CONTENT_ROLE) in HIDDEN_ROLES:
                continue
            yield {key: item for key, item in record.items() if key != CONTENT_ROLE}

    def learner_concept(concept):
        segments = list(learner_records(concept['segments']))
        for segment in segments:
            if segment['kind'] == EQUATION_KIND:
                segment.update(kind='explanation', text=display_equation(segment['text']))
        if len(segments) < len(concept['segments']) and METHOD_PRINCIPLE not in concept and not any(
                s['kind'] in ('definition', 'explanation', 'uncertain') for s in segments):
            return None
        return {**concept, 'segments': segments}

    concepts = [record for concept in value['concepts'] if (record := learner_concept(concept)) is not None]
    value['concepts'] = concepts
    for field in ('tables', 'sequences'):
        if field in value:
            value[field] = list(learner_records(value[field]))
    if not methods:
        return value
    methods = [record for method in methods
               if (record := learner_concept(render_method_template(dict(method)))) is not None]
    for method in methods:
        principle = method.pop(METHOD_PRINCIPLE, None)
        if principle is not None:
            method['segments'].insert(0, {'kind': 'definition', **principle})
    ids = exact['json_schema']['schema']['$defs']['studySourceId']['enum']
    position = {key: index for index, key in enumerate(ids)}

    def main_ids(concept):
        return {key for segment in concept['segments']
                if segment['kind'] in ('definition', 'explanation') and segment['text'].strip()
                for key in segment['blockIds']}

    def first_source(concept):
        return min((position.get(key, len(ids)) for key in main_ids(concept)), default=len(ids))

    # Insert each method at its source position without reordering the normal concepts.
    for method in sorted(methods, key=first_source):
        first = first_source(method)
        index = next((i for i, concept in enumerate(concepts) if first_source(concept) > first), len(concepts))
        concepts.insert(index, method)
    value['concepts'] = concepts
    # A source region can hold both practice and teaching. In case of a
    # contradictory whole-region decision, the explicit, visible method wins.
    method_ids = set().union(*(main_ids(method) for method in methods))
    value['excludedBlocks'] = [item for item in value['excludedBlocks']
        if item['blockId'] not in method_ids or (item['sourceDisposition'] or {}).get('kind') != 'pure_practice']
    return value


def provisional_application(blocks):
    return bool(blocks) and all(block.get('planRoleBeforeVisualGuard') == 'exercise'
        or block.get('planRole') in ('exercise', 'illustration', 'uncertain') for block in blocks)


def earlier_teaching(job, groups, *, limit=1000):
    """Bounded original source background for classifying a possible application."""
    if not any(block.get('planRoleBeforeVisualGuard') == 'exercise'
               or block.get('planRole') in ('exercise', 'illustration') for block in job['blocks']):
        return []
    first_page = min(block['page'] for block in job['blocks'])
    pages = {}
    preceding = groups[max(0, job['topicIndex'] - 4):job['topicIndex']]
    for group in reversed(preceding):
        for block in group['blocks']:
            text = block.get('text', '').strip()
            page = block['page']
            if (first_page - 5 <= page < first_page and block.get('planRole') == 'teaching'
                    and text and len(text) <= 300):
                pages.setdefault(page, []).append(text)
        if pages:
            break
    selected = []
    for page in sorted(pages, reverse=True):
        fragments = []
        page_limit = min(500, limit)
        for fragment in pages[page]:
            if len(fragment) <= page_limit:
                fragments.append(fragment)
                page_limit -= len(fragment)
                limit -= len(fragment)
        if fragments:
            selected.append({'page': page, 'nativeFragments': fragments})
    return list(reversed(selected))

RULES = r'''
EXAMPLE REMOVAL: SOURCE ROLE BEFORE WRITING
Distinguish a source's SUBJECT from its FUNCTION. A worked question about a
principle is not automatically a new lesson about that principle. Read the actual
question, task-specific setup and worked continuation in supplied images, even
when native text is empty or the heading repeats the theory heading. No particular
word, exam label or numbering is needed to recognize an application task.
planRoleBeforeVisualGuard is a provisional planning hint. Confirm the role from
the owned text and image before omitting anything.

Do not narrate, solve or reproduce the numerical answers of practice questions or
worked examples. Do not relabel such an answer as a source_case, a graph trend or
a fresh independent concept to retain it. Historical evidence, an informative
real case, a conceptual comparison, a new derivation and a diagram teaching a
mechanism are not practice merely because they are concrete or contain numbers.
When a passage supposes people, prices or quantities to demonstrate a mechanism,
explain the mechanism using general roles. The invented names, transaction
terms and arithmetic add no evidence, even if the same page teaches the rule.
This applies to the given formula and input values before substitution as well as
the answer. Mark a separate, wholly illustrative story as pure_practice even
when it is declarative and asks no question. If a separate theory block supports
the same rule, cite the theory alone. Do not join the story and rule in one paragraph.

Identify any genuinely NEW rule, condition, method or conceptual distinction in
the example. Teach that contribution generally, with its essential reasoning and
source citations, without the individual question's numerical walkthrough or final
answer. Keep each separately taught relationship even when two share a heading.
Applying a familiar law may teach a new MODEL: deriving a quantity or geometric
factor from physical conditions, relating several factors, or establishing the
valid range is new instruction even if the law is familiar. Treat a setup as
repeated only when the same construction was supplied, not just the same topic
or starting law. Identify these contributions before recording omissions.
In a mixed region keep the first complete unevaluated model, including the source
variable, physical endpoints, limits, factors and conditions. Replace interchangeable
exercise givens with symbols without changing those relationships. Once the general
unevaluated equation is complete, stop; do not follow it with the original numbers.
For each teaching graph preserve every distinct operation and meaning, including
signs. Present each axis pair with every operation taught for it, even when
another plot uses the same quantities. Keep signed and unsigned readings distinct.
Put each independently taught equation and each member of an explicit classification
with its own condition in MAIN. A reference to an equation must include the actual
expression in learner prose, even if sourceSetup already contains it. For each named
category preserve its own exact object, reference place and qualifying condition.
Use the source's short defining wording verbatim when it is clear. Do not borrow a
condition from the previous list member. A broad category rule does not replace its
expressly named distinctions.
If no new learning remains, concepts=[] is valid. Do not make a new card for a
routine rearrangement, task setup, or review of an already-taught definition.

semanticSourceContext, when present, contains ONLY original native-text fragments
from other parts of this SAME semantic unit. It is bounded, possibly incomplete
background, not a generated answer or proof anything was already taught. Use it
to distinguish source theory from repeated application across transport splits.
Its fragments are not current targets or citation IDs. Do not copy their theory
back into a practice-only current part to make an artificial lesson. The current
targets still take precedence if they introduce a real new point.

Only mark a whole region as routine when it adds no independent teaching. Cite a
mixed region only for its retained teaching. Write distinct paragraphs with their
own actual source IDs rather than mixing exercise work with the new explanation.
This applies to MAIN, easy explanations, tables, and flow steps. A confirmed
routine-only source cannot support a learner paragraph or display module.
For each whole routine practice/worked region use an excludedBlocks record with
sourceDisposition.kind=pure_practice, concrete observations of the actual
question/worked operation, independentLearningPoint="", and exerciseSelection
containing kind=practice/worked_example and a short exact visible sourceQuote.
For an image, quote readable text from the image, not just its generic heading.
This applies to its supporting graph, diagram and every calculation continuation
as well as its question region. The SAME identifying question quote may anchor
those related image regions when that question is supplied in this request. For
pure_practice, keptConceptTitle must be "" in both records. A mixed region is not
an exclusion record. A current concept is not required for a wholly routine
exercise part. Reading and excluding all current targets is
successful coverage, not an error. Do not label an unreadable region routine:
use uncertainty instead. Never report both teaching and omission of the same
source contribution. Account for repeated heading targets too, using the existing
structure disposition; do not leave them unassigned. These decisions belong to
this existing response only.
'''


def sibling_context(job, group, *, limit=3600, page_limit=900):
    owned={b['id'] for b in job['blocks']}
    pages={b['page'] for b in job['blocks']}
    others=[b for b in group['blocks'] if b['id'] not in owned]
    if not others:return None
    by_page={}
    for b in others:by_page.setdefault(b['page'],[]).append(b)
    # First source panels establish the unit; nearby panels resolve continuity.
    # This selects source location, never an inferred example/theory role.
    ordered=sorted(by_page)
    priority=list(dict.fromkeys(ordered[:2]+sorted(ordered,key=lambda p:min(abs(p-q) for q in pages))))
    selected=[];used=0;count=0
    for page in priority[:8]:
        texts=[];size=0
        for b in by_page[page]:
            text=b.get('text','').strip()
            if not text or size+len(text)>page_limit or used+len(text)>limit:continue
            texts.append(text);size+=len(text);used+=len(text);count+=1
        if texts:selected.append({'page':page,'nativeFragments':texts})
    if not selected:return None
    return {'policy':VERSION,'backgroundOnly':True,
            'notProofOfPriorTeaching':True,'pages':sorted(selected,key=lambda x:x['page']),
            'omittedSourceFragments':len(others)-count}


def _routine_receipt(item, block):
    d=item.get('sourceDisposition');e=item.get('exerciseSelection')
    if not isinstance(d,dict) or d.get('kind') not in ('routine_exercise','pure_practice'):return None
    learning_point=d.get('independentLearningPoint','' if d['kind']=='routine_exercise' else None)
    if not isinstance(learning_point,str) or learning_point.strip():return None
    if d['kind']=='pure_practice' and item.get('referenceContext') is not None:return None
    observations=d.get('observations')
    if not isinstance(observations,list) or not observations or any(
            not isinstance(x,str) or not x.strip() for x in observations):return None
    if not isinstance(e,dict) or e.get('kind') not in ('practice','worked_example'):return None
    quote=e.get('sourceQuote','')
    if not isinstance(quote,str) or len(''.join(quote.split()))<8:return None
    title=d.get('keptConceptTitle')
    if not isinstance(title,str) or title!=e.get('keptConceptTitle'):return None
    if d['kind']=='pure_practice' and title:return None
    # Native-only material has a checkable literal anchor. An actual visual
    # target is instead grounded in the model's same-response reading receipt.
    if not block.get('hasVisual'):
        native=block.get('text','')
        if block.get('additionalNativeProof') == 'k123-unicode-styled-prose-v1':
            from pdf_k123_native_prose import normalized
            native=normalized(native) or native
            quote_for_match=normalized(quote) or quote
        else:
            quote_for_match=quote
        if ''.join(quote_for_match.split()) not in ''.join(native.split()):return None
    return {'kind':d['kind'],'observations':observations,
            'sourceQuote':quote,'exerciseKind':e['kind'],'keptConceptTitle':title}


def routine_disposition(item, block, blocks, parts):
    """Accept explicit image-read selection, not a local guess from captions."""
    receipt = _routine_receipt(item, block)
    if receipt is None:
        return None
    title = receipt['keptConceptTitle']
    if title and not any(p.get('title') == title and p.get('body', '').strip() for p in parts):
        return None
    return receipt


def _source_ids(item):
    ids = item.get('blockIds') if isinstance(item, dict) else None
    return set(ids) if isinstance(ids, list) and all(isinstance(i, str) for i in ids) else set()


def apply_example_dispositions(raw, blocks):
    """Remove only content supported exclusively by a confirmed routine region.

    A mixed or uncertain region can still supply teaching. Never guess which
    words of a paragraph belong to each of several cited sources.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get('concepts'), list):
        return raw
    exclusions = [row for row in raw.get('excludedBlocks', [])
                  if isinstance(row, dict) and isinstance(row.get('blockId'), str)]
    counts = Counter(row['blockId'] for row in exclusions)
    owned = {b['id']: b for b in blocks}
    uncertain = {row.get('blockId') for row in raw.get('uncertainBlocks', [])
                 if isinstance(row, dict) and isinstance(row.get('blockId'), str)}
    for concept in raw['concepts']:
        if not isinstance(concept, dict):
            continue
        for segment in concept.get('segments', []):
            if not isinstance(segment, dict):
                continue
            if segment.get('kind') == 'uncertain':
                uncertain.update(_source_ids(segment))
    for record in raw.get('diagnostics', []):
        if isinstance(record, dict) and record.get('kind') in ('reading_gap', 'unsupported_inference'):
            uncertain.update(_source_ids(record))

    routine = set()
    for item in exclusions:
        key = item['blockId']
        if key in owned and key not in uncertain and counts[key] == 1:
            receipt = _routine_receipt(item, owned[key])
            # Older routine_exercise receipts were also used for mixed content.
            if receipt is not None and receipt['kind'] == 'pure_practice':
                routine.add(key)
    if not routine:
        return raw

    value = copy.deepcopy(raw)
    removed = []

    def routine_only(item):
        ids = _source_ids(item)
        return bool(ids and ids <= routine)

    def omit(channel, title, refs):
        removed.append({'stage': 'exercise_selection', 'kind': 'routine_content_omitted',
                        'channel': channel, 'conceptTitle': title, 'blockIds': sorted(refs)})

    remaining = []
    deleted_titles = set()
    for concept in value['concepts']:
        if not isinstance(concept, dict) or 'segments' not in concept:
            remaining.append(concept)
            continue
        title = concept.get('title', '')
        kept = []
        for segment in concept['segments']:
            if routine_only(segment):
                omit(segment.get('kind', 'segment'), title, _source_ids(segment))
            else:
                kept.append(segment)
        if len(kept) == len(concept['segments']):
            remaining.append(concept)
            continue
        if any(isinstance(segment, dict) and segment.get('kind') != 'easyExplanation' for segment in kept):
            concept['segments'] = kept
            remaining.append(concept)
        elif isinstance(title, str):
            deleted_titles.add(title)
    value['concepts'] = remaining
    deleted_titles.difference_update(concept.get('title') for concept in remaining
                                     if isinstance(concept, dict) and isinstance(concept.get('title'), str))

    for field in ('tables', 'sequences'):
        if field not in value:
            continue
        modules = []
        for item in value[field]:
            if not isinstance(item, dict):
                modules.append(item)
                continue
            refs = _source_ids(item) & routine
            if field == 'sequences':
                # A flow with a removed step cannot be displayed as that flow.
                for step in item.get('steps', []) + item.get('transitions', []):
                    if routine_only(step):
                        refs.update(_source_ids(step))
            if refs and (field == 'sequences' or routine_only(item)):
                omit(field, item.get('conceptTitle', ''), refs)
            else:
                modules.append(item)
        value[field] = modules

    if 'lectureUnits' in value:
        value['lectureUnits'] = [group for group in value['lectureUnits'] if not isinstance(group, dict)
                                 or not deleted_titles.intersection(group.get('conceptTitles', []))]
        for group in value['lectureUnits']:
            if isinstance(group, dict) and routine_only(group.get('bridge')):
                omit('bridge', group.get('title', ''), _source_ids(group.pop('bridge')))
    for row in value.get('sourceCoverage', []):
        if isinstance(row, dict) and row.get('blockId') in routine and 'quote' in row:
            row.update(conceptTitle='', quote='')
    if removed:
        value.setdefault('processingDiagnostics', []).extend(removed)
    return value
