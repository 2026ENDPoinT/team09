"""Conservative, source-cited admission for optional ordered-process cards.

The model's relationship description is not an independent semantic review.  This
gate checks its source anchors and general order signals; uncertainty belongs in
ordinary prose, where callers must preserve the complete rejected step content.
No source or generated learner text is changed here.
"""
import re
import unicodedata

VERSION = 'ordered-process-v2'
KINDS = frozenset(('process', 'procedure', 'derivation', 'cycle'))

_PREFIX = re.compile(r'^\s*(?:(?:step|stage|phase|단계)\s*\d+\s*[:.)\-–—]?\s*|'
    r'\d+\s*단계\s*[:.)\-–—]?\s*|(?:\(\d+\)|\[\d+\]|\d+\))\s*|'
    r'\d+[.．:：]\s+)', re.I)
_TOKENS = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*|[가-힣]{2,}|\d+(?:\.\d+)?')
_GENERIC = frozenset(('step', 'stage', 'phase', 'first', 'next', 'previous',
    'then', 'must', 'before', 'after', 'order', 'result', 'output', 'input',
    '단계', '과정', '순서', '먼저', '다음', '이전', '결과', '입력', '출력',
    '앞에서', '뒤에서', '이후', '진행', '여기서', '이것을', '그것을',
    '현재', '기초', '기본', '모든', '전체', '실제', '내용', '상태'))
_SUFFIXES = tuple(sorted(('합니다', '하세요', '해요', '한다', '된다', '돼요',
    '이에요', '예요', '이다', '하는', '하면', '하여', '해서', '으로', '에서',
    '까지', '에게', '된다', '되어', '해', '한', '인', '은', '는', '이', '가',
    '을', '를', '의', '에', '로'), key=len, reverse=True))

# These are grammatical/relationship cues, not a course or concept dictionary.
# Temporal adverbs, numbering and imperative verbs alone are deliberately absent.
_RELATION = re.compile(
    r'(?:때문|(?:으)?로\s*인(?:해|한)|에\s*의(?:해|한)|그\s*결과|따라서|그러므로|'
    r'이로\s*인해|초래|유발|일으키|이어[지져]|'
    r'(?:에서|을|를|이|가).{0,40}(?:으로|로).{0,20}(?:전이|전환|변환|변하|바뀌)|'
    r'에서.{0,50}(?:으로|로).{0,25}(?:이동|전달|흐르|변하)|'
    r'(?:결과|출력|생성물).{0,60}(?:입력|사용|전달|받아)|'
    r'에서\s*(?:얻은|나온|생긴).{1,80}(?:입력|사용|전달)|'
    r'(?:결과|출력|생성물)인\s+.{1,60}(?:을|를)\s*.{1,40}'
    r'(?:한다|하다|해요|된다|돼요|하였다|했다|한다면|하면)|'
    r'(?:이전|앞)\s*단계.{0,60}(?:사용|필요|전달|받아)|'
    r'(?:완료|종료|생성|확보|얻은|구한).{0,30}(?:후|다음|뒤|되면|하면).{0,60}\S|'
    r'(?:대입|소거|양변|재배열|정리하|유도하|도출하)|'
    r'\b(?:causes?|leads?\s+to|results?\s+in|produces?|becomes?|'
    r'transforms?\s+into|converted?\s+(?:to|into)|changes?\s+(?:to|into)|'
    r'transitions?\s+(?:from|to)|therefore|hence|consequently|'
    r'substitut\w*|rearrang\w*|deriv\w*)\b|'
    r'\b(?:output|result|product)\b.{0,70}\b(?:input|used|feeds?|passed)\b|'
    r'\b(?:completed?|finished?|obtained?|generated?)\b.{0,30}'
    r'\b(?:before|after|then)\b.{0,60}\w)', re.I | re.S)
_ARROW = re.compile(r'(?:→|⇒|⟶|⟹|->|=>|\\(?:Long)?[Rr]ightarrow|\\implies|\\to)')
_LISTING = re.compile(
    r'(?:종류|유형|범주|특성|특징|비교|분류|포함\s*관계|상위|하위|성숙도|서열|등급|'
    r'\b(?:types?|categories|classification|characteristics|properties|comparison|hierarchy|'
    r'maturity|ranks?|ratings?)\b)', re.I)
_SENTENCE_END = re.compile(r'\n|[;；!?。！？]|(?<!\d)\.|\.(?!\d)')


def _presentation_text(value):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'^\s*[①-⑳⑴-⒇]\s*', '', value)
    value = unicodedata.normalize('NFKC', value).strip()
    # Number-only presentation prefixes must not disguise repeated stages.
    return _PREFIX.sub('', value)


def _normal(value):
    value = _presentation_text(value).casefold()
    return ''.join(c for c in value if c.isalnum())


def _body_key(value):
    value = _presentation_text(value)
    # A paired outer emphasis wrapper is presentation; pointer/code operators
    # and all internal signs/case remain content, including final punctuation.
    while True:
        wrapper = next((mark for mark in ('**', '__', '*', '_')
                        if len(value) > 2*len(mark) and value.startswith(mark)
                        and value.endswith(mark)), None)
        if wrapper is None:
            break
        value = value[len(wrapper):-len(wrapper)].strip()
    return ''.join(value.split())


def _valid_steps(steps):
    if not isinstance(steps, list) or len(steps) < 3:
        return False
    for key in ('title', 'body'):
        normalize = _normal if key == 'title' else _body_key
        values = [normalize(step.get(key)) if isinstance(step, dict) else '' for step in steps]
        if not all(values) or len(set(values)) != len(values):
            return False
    return True


def _ids(step):
    evidence = step.get('evidence')
    if not isinstance(evidence, list):
        return set()
    return {item['sourceId'] for item in evidence if isinstance(item, dict)
            and isinstance(item.get('sourceId'), str)}


def _words(text):
    result = set()
    for token in _TOKENS.findall(unicodedata.normalize('NFKC', text).casefold()):
        if re.fullmatch(r'[가-힣]+', token):
            for suffix in _SUFFIXES:
                if token.endswith(suffix) and len(token)-len(suffix) >= 2:
                    token = token[:-len(suffix)]
                    break
        result.add(token)
    return result


def _mentions_step(text, step, other=None, *, shared_body=False):
    """Require actual labels/content, not merely 'step 1 precedes step 2'."""
    normalized = _normal(text)
    title = _normal(step.get('title'))
    if title and title in normalized:
        return True
    text_words = _words(text)
    title_words = _words(step.get('title', ''))
    other_titles = _words(other.get('title', '')) if other else set()
    # A multiword source label may be cited through its distinctive component,
    # e.g. a postposition/verb ending differs while the actual label is retained.
    if len(title_words) >= 2 and (title_words-other_titles-_GENERIC) & text_words:
        return True
    body = _body_key(step.get('body'))
    if body and body in _body_key(text):
        return True
    shared = _words(other.get('body', '')) if other and not shared_body else set()
    content = {word for word in _words(step.get('body', ''))-_GENERIC-shared
               if not word.isnumeric()}
    return bool(content & text_words)


def _arrow_relation(text, left, right):
    # Each edge must connect its own endpoint contents.  Three independent
    # A→meaning mappings are not a chain merely because arrows exist somewhere.
    for line in text.splitlines():
        pieces = _ARROW.split(line)
        for start, end in zip(pieces, pieces[1:]):
            if (_mentions_step(start, left, right) and _mentions_step(end, right, left)
                    and _normal(start) != _normal(end)):
                return True
    return False


def _native_relation(quote, left, right):
    # A labelled diagram/formal implication can state the relation without prose.
    # A hierarchy or comparison arrow is insufficient on its own.
    if not _LISTING.search(quote) and _arrow_relation(quote, left, right):
        return True
    # An unrelated causal verb somewhere in a long common quote is insufficient.
    # Both endpoint contents and their relation must occur in one source clause.
    for clause in _SENTENCE_END.split(quote):
        if (_RELATION.search(clause)
                and _mentions_step(clause, left, right, shared_body=True)
                and _mentions_step(clause, right, left, shared_body=True)):
            return True
    return False


def _sentence_contexts(text, quote):
    """Return every exact occurrence's own original sentence, never a neighbor."""
    boundaries = [(match.start(), match.end()) for match in _SENTENCE_END.finditer(text)]
    contexts = []
    start = text.find(quote)
    while start >= 0:
        finish = start+len(quote)
        previous = max((end for _, end in boundaries if end <= start), default=0)
        following = next(((pos, end) for pos, end in boundaries if pos >= start), None)
        end = following[1] if following else len(text)
        # A quote crossing independent sentence/list boundaries cannot borrow
        # adjacent source material to manufacture one relationship.
        contexts.append(text[previous:end] if end >= finish else None)
        start = text.find(quote, start+1)
    return contexts


def _grounded_native_relation(quote, sources, left, right):
    if _native_relation(quote, left, right):
        return True
    contexts = [context for source in sources
                for context in _sentence_contexts(source['text'], quote)]
    # If a short phrase occurs in different contexts, do not choose whichever
    # occurrence is most favorable. Every occurrence must attest the same edge.
    return bool(contexts) and all(context is not None and _native_relation(context, left, right)
                                  for context in contexts)


def _visual_source(source):
    return isinstance(source, dict) and (source.get('hasVisual') is True
        or source.get('kind') == 'visual')


def assess_sequence(item, steps, allowed):
    """Return a structural/source eligibility stamp, or None for plain fallback.

    ``allowed`` is the caller's already restricted canonical concept source map.
    Step text/evidence must first pass the caller's existing ordinary validators.
    Native quotes must occur exactly in a referenced source. Empty quotes are
    accepted only for explicitly visual sources, with a concrete model-observed
    link. That path is marked inferredFromVisual, not independently verified.
    """
    if not isinstance(item, dict) or not _valid_steps(steps) or not isinstance(allowed, dict):
        return None
    kind = item.get('orderKind')
    transitions = item.get('transitions')
    if (not isinstance(kind, str) or kind not in KINDS
            or not isinstance(transitions, list) or len(transitions) != len(steps)-1):
        return None
    by_pair = {}
    visual = False
    for transition in transitions:
        if not isinstance(transition, dict):
            return None
        start, end = transition.get('fromStep'), transition.get('toStep')
        if (type(start) is not int or type(end) is not int or end != start+1
                or not 0 <= start < len(steps)-1 or (start, end) in by_pair):
            return None
        relation, ids, quote = (transition.get('relation'), transition.get('blockIds'),
                                transition.get('sourceQuote'))
        if (not isinstance(relation, str) or len(relation.strip()) < 8
                or not isinstance(ids, list) or not ids or not isinstance(quote, str)
                or any(not isinstance(key, str) or key not in allowed for key in ids)):
            return None
        ids = set(ids)
        left, right = steps[start], steps[end]
        if not ids.intersection(_ids(left)) or not ids.intersection(_ids(right)):
            return None
        if not _mentions_step(relation, left, right) or not _mentions_step(relation, right, left):
            return None
        if quote:
            native = [allowed[key] for key in ids if isinstance(allowed[key], dict)
                      and isinstance(allowed[key].get('text'), str)
                      and quote in allowed[key]['text']]
            if not native or not _grounded_native_relation(quote, native, left, right):
                return None
        else:
            # No textual quote is fabricated for a picture. The relation is the
            # model's same-call observation, with source ownership checked here.
            visual_ids = {key for key in ids if _visual_source(allowed[key])}
            if (not visual_ids or not visual_ids.intersection(_ids(left))
                    or not visual_ids.intersection(_ids(right))
                    or not (_RELATION.search(relation) or _arrow_relation(relation, left, right))):
                return None
            visual = True
        by_pair[start, end] = True
    if set(by_pair) != {(i, i+1) for i in range(len(steps)-1)}:
        return None
    result = {'policyVersion': VERSION, 'kind': kind, 'sourceGrounded': True,
              'transitionCount': len(steps)-1}
    if visual:
        result['inferredFromVisual'] = True
    return result


def is_eligible_module(module):
    """Check an already approved stamp for display; do not rejudge its sources."""
    if (not isinstance(module, dict) or module.get('moduleId') != 'synesis.step-flow'
            or type(module.get('schemaVersion')) is not int or module['schemaVersion'] != 1
            or not _valid_steps(module.get('steps'))):
        return False
    stamp = module.get('eligibility')
    return (isinstance(stamp, dict) and stamp.get('policyVersion') == VERSION
        and isinstance(stamp.get('kind'), str) and stamp['kind'] in KINDS
        and stamp.get('sourceGrounded') is True
        and type(stamp.get('transitionCount')) is int
        and stamp['transitionCount'] == len(module['steps'])-1)
