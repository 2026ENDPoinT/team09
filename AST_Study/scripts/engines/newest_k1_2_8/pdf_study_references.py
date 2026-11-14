"""Image-read reference bookkeeping and exact, reversible saved-display overrides.

The text-only planner cannot use this channel. Source pixels, paid responses and
canonical learner caches remain intact; context still owns its source evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

from pdf_response_schema import _object
from pdf_visual_selection import substantive_visual

VERSION = 'study-reference-context-v1'
OVERRIDE_FILE = 'reference-context-overrides.json'
KINDS = ('location_map', 'scene_photo', 'decoration')
SIGNALS = ('definition', 'mechanism', 'quantitative_comparison', 'labelled_structure',
           'code', 'reported_claim', 'historical_event', 'classification',
           'interpretation_boundary')
REFERENCE_SCHEMA = {'anyOf': [_object({
    'kind': {'type': 'string', 'enum': list(KINDS)},
    'observations': {'type': 'array', 'items': {'type': 'string'}},
    'learningSignals': {'type': 'array', 'items': {'type': 'string', 'enum': list(SIGNALS)}},
    'readable': {'type': 'boolean'}}), {'type': 'null'}]}

# The semantic policy/validator/schema are unchanged by the shorter wire wording.
# Retain the original identity text locally so already paid work remains reusable.
CACHE_IDENTITY_RULES = '''
INSTRUCTIONAL ROLE AFTER IMAGE READING
Reading an image and publishing a new concept are separate decisions. First read
every supplied substantial figure, including all labels and relationships. Never
skip it based on titleHint, empty native text or the text-only planner's role.
Teach every substantive claim, mechanism, distinction, labelled structure, route,
comparison, code example, classification and meaningful number/condition. A figure
supporting an existing concept belongs with that concept, with its own blockIds;
do not manufacture a second concept just to describe the picture. Preserve its
unique teaching and source evidence even when adjacent text covers the same topic.
Only a plainly readable location-only map, scene photo or decorative image with
NO independent teaching signal may be recorded in excludedBlocks.referenceContext.
For that record supply kind, concrete visible observations, learningSignals=[] and
readable=true, plus a short internal reason describing its reference role. It is
accounted for as source context, not unreadable/missing teaching. Do not create a
definition, explanation or easyExplanation just to fill a reference image's slot.
For every other excludedBlocks record use referenceContext=null.
Never downgrade a graph, table, anatomical/technical diagram, quantitative or
historical map, news/article claim, historical evidence, taught classification,
formula/code or an interpretation boundary to reference context. Matching the
topic hint is not a prerequisite for teaching. If a learning signal exists, teach
it even without a caption or nearby explanation. If reading or role is uncertain,
retain the supported teaching and use the existing uncertainty channel; uncertainty
is not permission to mark an image as context. The reference channel cannot hide
an unreadable source. All usual source ID, coverage and grounding checks apply.
Learner prose should explain what the source teaches, not inventory incidental
place names, colors or visible objects. Mention those only when they explain the
concept or a meaningful relation. Do not append what an ordinary reference picture
cannot prove or compare. Keep source-taught limitations and concrete cautions that
actually prevent a likely misconception, including bounds and correlation/causation.
Never delete negation/conditions just because they are cautions. Internal selection
or reading reasons belong in metadata only, never learner text.
'''

RULES = '''
REFERENCE IMAGES
Read every substantial image, regardless of titleHint or native-text availability.
Preserve source claims, mechanisms, data, conditions, interpretation boundaries,
structures/routes, classifications, diagrams, graphs/tables, quantitative/historical
maps and code with their blockIds. Attach supporting figures to their concept
without duplication.
Only readable location-only maps, scene photos or decoration with no learning
signal may use excludedBlocks.referenceContext (kind, visible observations,
learningSignals=[], readable=true, internal reason); omit their concept paragraphs.
Otherwise use null. Uncertain reading/role uses the existing uncertainty channel,
retaining supported teaching.
Omit incidental inventories/generic cautions, not meaningful labels, limitations
or negation. Keep selection/reading reasons internal.
'''
_CACHE_EQUIVALENT_COMPRESSION = '66f1e7494e38942b5f2f9007924c66dd39438b95cc30dd8f8e2779ce3a5a3a0e'


def identity_prompt(prompt):
    """Normalize only this semantics-preserving compression, never other rules."""
    if (prompt.endswith(RULES)
            and hashlib.sha256(RULES.encode()).hexdigest()==_CACHE_EQUIVALENT_COMPRESSION):
        return prompt[:-len(RULES)]+CACHE_IDENTITY_RULES
    return prompt

# A second conservative guard for visible information that contradicts a context
# classification. Absence of these tokens does NOT classify a source as context.
_SIGNAL_TEXT = re.compile(
    r'\d|[%=∑∫→↔]|\\(?:frac|int|sum)|```|'
    r'상관|인과|메커니즘|작동\s*원리|분류|통계|범례|추세|분포|수치|좌표|'
    r'위도|경도|거리|경로|교역|무역|전쟁|식민|전선|신경|혈관|포인터|방정식|'
    r'\b(?:graph|chart|table|legend|axis|axes|mechanism|classification|'
    r'pointers?|equation|causation|correlation|war|trade\s+route|nerves?|'
    r'vessels?|anatomy|anatomical|code|distribution|battle|historical)\b', re.I)
_SCOPE_REASON = re.compile(r'무관|범위\s*밖|주제.{0,12}(?:아니|해당하지)|'
                           r'\b(?:unrelated|out.of.scope|topic\s+hint)\b', re.I)


def reference_context(record, block):
    """Admit an explicit, readable image assessment, never an arbitrary exclusion."""
    context = record.get('referenceContext')
    if not isinstance(context, dict) or set(context) != {
            'kind', 'observations', 'learningSignals', 'readable'}:
        return None
    observations = context.get('observations')
    box=block.get('bbox')
    if (not isinstance(box,list) or len(box)!=4 or any(type(n) not in (int,float)
            or not math.isfinite(n) or not 0<=n<=1 for n in box)
            or box[2]<=box[0] or box[3]<=box[1]
            or type(block.get('page')) is not int or block['page']<1):
        return None
    if (not substantive_visual(block) or context.get('kind') not in KINDS
            or context.get('readable') is not True or context.get('learningSignals') != []
            or not isinstance(observations, list) or not observations
            or any(not isinstance(s, str) or not s.strip() for s in observations)
            or not isinstance(record.get('reason'), str) or not record['reason'].strip()
            or _SCOPE_REASON.search(record['reason'])):
        return None
    text=block.get('text','')
    if not isinstance(text,str) or _SIGNAL_TEXT.search(text+'\n'+'\n'.join(observations)):
        return None
    return copy.deepcopy(context)


def content_hash(part, entry):
    """Bind a display decision to exact prose AND canonical evidence, not a title."""
    fields = ({k: part.get(k) for k in ('title', 'body', 'easyExplanation', 'evidence')},
              {k: entry.get(k) for k in ('name', 'definition', 'explanation',
                                         'easyExplanation', 'evidence')})
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _ids(value):
    return {e.get('sourceId') for e in value.get('evidence', []) if isinstance(e, dict)}


def project_saved_references(folder, document, result):
    """Apply only exact approved display decisions; a changed source/prose fails closed.

    Existing results have no reliable semantic role flags. They are never guessed
    from keywords and never regenerated automatically to acquire such flags.
    """
    if not isinstance(result, dict):
        return result
    try:
        policy = json.loads((Path(folder)/'generated'/OVERRIDE_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return result
    if (not isinstance(policy,dict) or policy.get('version') != VERSION or not isinstance(policy.get('items'), list)
            or policy.get('documentId') != document.get('documentId')
            or policy.get('sourceFingerprint') != document.get('fingerprint')
            or result.get('documentId') != document.get('documentId')
            or result.get('sourceFingerprint') != document.get('fingerprint')):
        return result
    value = copy.deepcopy(result)
    contexts = []
    for record in policy['items']:
        if not isinstance(record, dict):
            continue
        source = record.get('blockId')
        block = record.get('sourceBlock')
        if not isinstance(block, dict) or block.get('id') != source:
            continue
        context = reference_context(record, block)
        if context is None:
            continue
        parts = [(s, p) for s in value.get('sections', []) for p in s.get('parts', [])
                 if _ids(p) == {source}]
        entries = [(g, e) for g in value.get('concepts', []) for e in g.get('entries', [])
                   if _ids(e) == {source}]
        if len(parts) != 1 or len(entries) != 1:
            continue
        section, part = parts[0];group, entry = entries[0]
        if (content_hash(part, entry) != record.get('contentHash') or not part.get('body')
                or not isinstance(section.get('body'), str)
                or section['body'].count(part['body']) != 1
                or any(k in part or k in entry for k in ('comparisonTable', 'stepFlow'))
                or not part.get('evidence') or any(
                    e.get('page') != block.get('page') or e.get('bbox') != block.get('bbox')
                    for e in part['evidence'])):
            continue
        prose='\n'.join(str(part.get(k,'')) for k in ('title','body','easyExplanation'))
        prose+='\n'+'\n'.join(str(entry.get(k,'')) for k in
                              ('name','definition','explanation','easyExplanation'))
        if _SIGNAL_TEXT.search(prose):
            continue
        coverage = [c for c in value.get('coverage', []) if c.get('blockId') == source]
        if len(coverage) != 1 or coverage[0].get('state') != 'summarized':
            continue
        section['body'] = section['body'].replace(part['body'], '', 1).strip()
        section['parts'].remove(part);group['entries'].remove(entry)
        coverage[0].update(state='context', reason=record['reason'],
                           referenceContext=context, evidence=copy.deepcopy(part['evidence']))
        contexts.append({'blockId': source, 'page': block['page'],
                         'reason': record['reason'], 'referenceContext': context,
                         'evidence': copy.deepcopy(part['evidence'])})
    if not contexts:
        return result
    value['sections'] = [s for s in value['sections'] if s.get('parts') or s.get('body', '').strip()]
    value['concepts'] = [g for g in value['concepts'] if g.get('entries')]
    value.setdefault('referenceContexts', []).extend(contexts)
    value['referenceContextVersion'] = VERSION
    # Source hierarchy is reprojected from the retained parts, never from the old
    # generated node that described the removed reference-only concept.
    value.pop('hierarchy', None)
    return value
