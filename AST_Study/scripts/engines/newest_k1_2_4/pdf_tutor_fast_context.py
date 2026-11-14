"""Reuse an unambiguous conversational task for retrieval, not for answering it.

The answer model still receives the original question, actual dialogue roles and
all selected conditions. No assistant claim is promoted to a learner topic, and
unknown vocabulary or an older-task reference keeps the semantic planner.
"""
import re


_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|[가-힣]+|[0-9]+')
_GRAMMAR = re.compile(
    r'(?:그|이|저|그거|그것|그건|그게|그걸|이거|이것|이건|이게|이걸|'
    r'그럼|그러면|그래서|그래도|그렇다면|그렇|그런|그렇게|이렇게|'
    r'거기|여기|쪽|한쪽|그쪽|이쪽|양쪽|둘|둘다|둘은|둘이|각각|서로|'
    r'더|좀|조금|다시|쉽게|자세히|상세히|간단히|구체적으로|정확히|짧게|길게|'
    r'왜|어떻게|어떤|무슨|뭐|뭔|뭐야|뭔데|누가|누구|어디|뜻|의미|이유|원리|차이|비교|'
    r'설명|정리|요약|예시|예제|비유|사례|예를|들어|한번|하나|두|세|번|배|절반|'
    r'내용|부분|경우|상황|조건|상태|반대|반대로|같은|다른|그대로|계속|아직|'
    r'처음|나중|뒤|앞|안쪽|바깥쪽|원래|기존|전부|모두|무조건|꼭|항상|'
    r'것|건|걸|거|수|때|도|만|에|은|는|이|가|을|를|의|로|면|요|'
    r'안|못|잘|더라도|아니|맞아|맞지|맞는|필요|어디에|어디서|어디다|'
    r'(?:설명|정리|요약|비교|계산|보여|알려|말|표현|해)(?:해|해줘|줘|주세요|해줄래|봐|해봐|줘요)|'
    r'(?:그러|그렇|같|다르|달라|바꾸|바뀌|뒤집|변하|변해|달라지|'
    r'바꿨|되|돼|하|해|있|없|않|맞|아니|포함|필요|필요하|쓰|써|이해|헷갈|모르겠|계산하)'
    r'(?:다|야|어|아|면|다면|려면|냐|지|네|나|는|은|을|는데|어도|아도|을까|을까요|'
    r'는거야|다는|다는거야|다는거지|한다고|한|할|해|해도|하고|하면|하나|해요|하죠|'
    r'해줘|주세요|기|거야|거지|겠네|겠지|었|았|지면|진|지만){0,2})'
    r'(?:은|는|이|가|을|를|의|에|에서|도|만|로|으로|이면|면|이니까|야|요|거야|거지|라는|라는거야){0,2}$')
_SUFFIXES = ('으로는','에서는','에게는','이라고','이라는','이라면','이라서','이라니',
             '인거야','이라는거야','이야','이니까','으로','에서','에게','처럼','까지','부터','이면','라면',
             '은','는','이','가','을','를','의','도','만','로','면')
_LEAD = re.compile(r'^\s*(?:그럼|그러면|그래서|그래도|그렇|그|이|저|거기|여기|'
                   r'반대로|한쪽|양쪽|둘|각각|서로|같은|처음|다시|더|왜|어떻게)')
_SPECIAL = re.compile(
    r'아까|앞서|이전|지난|돌아가|되돌|물어본|물었던|질문했던|말고|대신|정정|새로운?|다른\s*주제|'
    r'오늘|내일|어제|언제|현재|지금|최근|올해|실시간|최신|인터넷|외부|웹|온라인|검색|출처|검증|확인해|'
    r'실제로|현실|실무|페이지|쪽\s*\d|\d\s*쪽|\d\s*번|pdf|원문|문서|자료|선택|첨부|'
    r'사진|이미지|그림|표에서|도표|첫\s*번째|두\s*번째|전자|후자|마지막|^\s*저|[\n\r]|https?://', re.I)
_CLARIFY = re.compile(r'(?:어느|어떤|무엇|어디).{0,25}(?:말하|말씀|가리키|알려\s*주)|'
                      r'(?:대상|조건|기호).{0,15}(?:알려\s*주|확인해\s*주)')


def _grammar_word(token):
    # Bounded inflections avoid backtracking through long code/name tokens.
    return len(token)<=32 and _GRAMMAR.fullmatch(token)


def _content(text):
    return [token for token in _TOKEN.findall(text.lower())
            if not token.isdigit() and not _grammar_word(token)]


def _seen(token, text):
    """Particle variants only affect eligibility, never rewrite the question."""
    if token.isascii():
        return bool(re.search(r'(?<![a-z0-9_])'+re.escape(token)+r'(?![a-z0-9_])', text))
    if token in text:
        return True
    return any(len(token)-len(suffix) >= 2 and token.endswith(suffix)
               and token[:-len(suffix)] in text for suffix in _SUFFIXES)


def fast_followup_plan(payload):
    """Skip duplicate interpretation only for a bounded, grounded continuation."""
    if (payload.get('mentorContext') is not True or payload.get('operation') != 'query_plan'
            or 'sourceTask' in payload or 'selectionLocation' in payload):
        return None
    question, recent, focus = payload.get('question'), payload.get('recent'), payload.get('focus')
    if (not isinstance(question,str) or not 1 <= len(question) <= 160 or _SPECIAL.search(question)
            or not re.search(r'[가-힣A-Za-z]',question)
            or not isinstance(recent,list) or not recent or not isinstance(focus,dict)
            or focus.get('page') is not None):
        return None
    subject = focus.get('subject')
    if not isinstance(subject,str) or not subject.strip() or len(subject)>240 or _SPECIAL.search(subject):
        return None
    if any(not isinstance(t,dict) or not all(isinstance(t.get(k),str) for k in ('question','answer'))
           for t in recent[-6:]):
        return None
    last = recent[-1]
    if not last['answer'].strip() or _SPECIAL.search(last['question']) or _CLARIFY.search(last['answer']):
        return None
    # Find the nearest learner-owned target; a generic rephrase is not a topic.
    anchor = next((t['question'] for t in reversed(recent[-6:]) if _content(t['question'])), None)
    if not anchor or _SPECIAL.search(anchor):
        return None
    anchor_lower = anchor.lower()
    subject_words = _content(subject)
    if subject_words and not any(_seen(word,anchor_lower) for word in subject_words):
        return None  # A stale/mistaken machine focus must not authorize a skip.
    if not subject_words:
        subject = anchor
    words = _content(question)
    learner_target = (subject+' '+anchor).lower()
    if words and not _LEAD.search(question) and not _seen(words[0],learner_target):
        return None
    # A newly named topic after "then" still owns its own task. Incidental
    # vocabulary in the assistant's answer cannot authorize that topic here.
    head = re.sub(r'^\s*(?:그럼|그러면|그래서|그래도|그렇다면)\s*','',question)
    named = re.match(r'([가-힣A-Za-z_][가-힣A-Za-z0-9_]*?)(?:은|는|이|가|이면|라면)(?=\s|[?.!]|$)',head)
    if named and not _grammar_word(named[0]) and not _seen(named[1].lower(),learner_target):
        return None
    if words and re.search(r'뭐야|뭔데|뭐임|무엇|뜻|정의',question):
        return None
    nearby_text = ' '.join(t['question']+' '+t['answer'] for t in recent[-3:])+' '+subject+' '+anchor
    # Code identifiers are case-sensitive even though Korean lexical matching
    # is normalized. Changing a to A must not qualify as an unchanged referent.
    for token in _TOKEN.findall(question):
        if token.isascii() and not token.isdigit() and not re.search(
                r'(?<![A-Za-z0-9_])'+re.escape(token)+r'(?![A-Za-z0-9_])',nearby_text):
            return None
    nearby = nearby_text.lower()
    if any(not _seen(word,nearby) for word in words):
        return None
    query = (subject+' '+anchor).strip()[:160]
    intent = ('illustrate' if re.search(r'예시|예제|예를|비유|사례',question) else
              'compare' if re.search(r'차이|비교',question) else
              'learning_relevance' if re.search(r'필요|어디.{0,5}(?:쓰|써)',question) else
              'interpret' if re.search(r'뜻|의미',question) else 'explain')
    return {'subject':subject[:160], 'query':query, 'intent':intent, 'followup':True,
            'page':None, 'artifact':bool(re.search(r'작품|소설|영화',subject+' '+anchor)),
            'web':'none', 'ask':False, 'scope':'general', 'missingConditions':[]}
