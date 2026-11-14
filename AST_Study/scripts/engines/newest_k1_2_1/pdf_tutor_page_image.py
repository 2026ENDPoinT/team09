"""Conservative local PDF-image routing. Never calls a model or changes study data."""
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
import threading

EXERCISE = re.compile(r'문제|예제|기출|연습|\b(?:problem|exercise|example)\b', re.I)
SOLVE = re.compile(r'풀|풀이|해결|계산|구해|구하|설명|해설|\b(?:solve|explain|calculate)\b', re.I)
DIRECT_SOLVE = re.compile(r'풀이|풀어|풀자|풀고|풀\s*수|해결|계산해|계산하|\b(?:solve|calculate)\b', re.I)
VISUAL = re.compile(r'(?:그림|이미지|작품|그래프|도표|도형|사진|수식|표의|표에|표를|\b(?:image|artwork|figure|graph|diagram|table|equation)\b)', re.I)
INSPECT = re.compile(r'보여|봐|보면|읽|설명|해석|확인|축|색|곡선|모양|배치|위치|어떻게|어떤|\b(?:read|explain|look|axis|color)\b', re.I)
POSITION = re.compile(r'왼쪽|오른쪽|가운데|중앙|위쪽|아래쪽|상단|하단|(?:맨|제일)\s*(?:위|아래)|저기|거기|전체적')
VISIBLE_DETAIL = re.compile(r'색|숫자|합계|금액|생겼|생김새|모양|눈에\s*띄|뭐야|무엇|읽어|비교')
CONCEPT_ONLY = re.compile(r'(?:개념|뜻|정의|원리)만|(?:그림|이미지|사진)(?:은|는|을|를)?\s*(?:말고|제외|빼고|보지)')
NEW = re.compile(r'(?:새로운?|다른|가상).{0,12}(?:문제|예제|예시)|(?:문제|예제|예시).{0,12}(?:만들|지어)|\b(?:invent|create a new)\b', re.I)
_RENDER_LOCK = threading.RLock()


PAGE_REFERENCE = re.compile(r'\d+\s*(?:페이지|쪽)|\b(?:page\s*|p\.\s*)\d+', re.I)
ACTION_STOP = re.compile(r'말고|제외|빼고|하지\s*마|풀지|계산하지|다른\s*주제|새\s*주제')


def source_action(text):
    """Only concrete source tasks can supply an omitted action, not a topic."""
    if NEW.search(text) or CONCEPT_ONLY.search(text) or ACTION_STOP.search(text):
        return False
    return bool((SOLVE.search(text) and
                 (EXERCISE.search(text) or re.search(r'\d+\s*번', text))) or
                (DIRECT_SOLVE.search(text) and PAGE_REFERENCE.search(text)) or
                (VISUAL.search(text) and INSPECT.search(text)))


def planned_source_request(question, plan):
    """Reuse the existing planner's source target; never request another plan."""
    return (plan.get('scope') == 'pdf' and type(plan.get('page')) is int and plan['page'] > 0
            and source_action(question) and not re.search(r'개념|정의|원리|뜻', question))


def location_reply(text):
    """A location and optional referent, with no new subject or action.

    Full consumption prevents a named conceptual topic or a negated location
    from silently inheriting an earlier solving task.
    """
    if not PAGE_REFERENCE.search(text):
        return False
    rest = PAGE_REFERENCE.sub('', text)
    return bool(re.fullmatch(
        r'(?:\s|[?!.~,]|\d+\s*번|그림|문제|예제|표|그래프|사진|이미지|작품|수식|'
        r'왼쪽|오른쪽|가운데|상단|하단|위쪽|아래쪽|맨\s*위|맨\s*아래|'
        r'거기|여기|그거|이거|해당|아니요|아니|정확히|바로|에|의|은|는|이|가|을|를|'
        r'있어요|있어|있습니다|있는거야|있는\s*거야|나와요|나와|나옵니다|'
        r'입니다|예요|이에요|이야|야|요|쪽|부분|에서)*', rest, re.I))


def located_page_request(question, state, explicit_page, current_page, page_count):
    """Resolve a concrete request + supplied location using bounded user turns.

    Assistant claims about missing evidence are deliberately not used. An
    unspecified viewer page is a search candidate, never a problem-number map.
    """
    if explicit_page is not None and not 1 <= explicit_page <= page_count:
        return None
    if location_reply(question) and explicit_page is not None:
        for turn in reversed(state.get('turns', [])[-4:]):
            previous = turn.get('question', '')
            if location_reply(previous):
                continue
            if source_action(previous):
                action = PAGE_REFERENCE.sub('', previous).strip()
                return {'page': explicit_page,
                        'request': f'{explicit_page}페이지에서 {action}. 위치 안내: {question}',
                        'candidate': False}
            break  # A new topic/cancellation closes the previous task.
    concrete_target = bool(re.search(r'\d+\s*번', question) or EXERCISE.search(question))
    if (explicit_page is None and concrete_target and source_action(question) and
            type(current_page) is int and 1 <= current_page <= page_count):
        return {'page': current_page, 'request': question, 'candidate': True}
    return None


def elliptical_page_request(question, state, explicit_page, current_page, page_count):
    """Carry a recent user's action, never an old problem's content, to a page."""
    def elliptical(text):
        text = re.sub(r'\d+\s*(?:페이지|쪽)|(?:다음|이전|현재|이|그|해당)\s*(?:페이지|쪽)', '', text)
        text = re.sub(r'그럼|그러면|이번엔|이번에는|여기도|이것도|이거도|이것|이거|그것도|그거도|그거|'
                      r'부탁할게|부탁해요|부탁해|부탁|설명해줘|알려줘|해주세요|해줄래|해줘|똑같이|마찬가지로|'
                      r'좀|더|자세히|다시|계속|이어서|설명해줘|알려줘|ㄱㄱ|도|는|은|을|를', '', text)
        return not re.sub(r'[\s?.!,~]+', '', text)

    if not question.strip() or not elliptical(question):
        return None
    turns = state.get('turns', [])
    action = None
    for turn in reversed(turns[-4:]):
        previous = turn.get('question', '')
        if elliptical(previous) or location_reply(previous):
            continue
        if NEW.search(previous) or re.search(r'말고|제외|풀지|하지\s*마|개념만|뜻만', previous):
            break
        if DIRECT_SOLVE.search(previous):
            action = '문제 풀이'
        elif VISUAL.search(previous) and INSPECT.search(previous):
            action = '그림 설명'
        break  # Never search past an intervening named topic.
    relative_page = bool(re.search(r'(?:다음|이전)\s*(?:페이지|쪽)', question))
    # A newly opened page can have been solved without an explicit "solve" in
    # the user's last message. Continue to its neighbour without reviving an
    # older task across a topic change; the answer call has the conversation.
    if not action and relative_page and type(state.get('focus', {}).get('page')) is int:
        action = '내용 설명'
    if not action:
        return None
    focus = state.get('focus', {})
    page = explicit_page
    if page is None:
        page = current_page if type(current_page) is int and current_page != focus.get('viewerPage') else focus.get('page')
        if page is None:
            page = current_page
        if type(page) is int and re.search(r'다음\s*(?:페이지|쪽)', question):
            page += 1
        elif type(page) is int and re.search(r'이전\s*(?:페이지|쪽)', question):
            page -= 1
    if type(page) is not int or not 1 <= page <= page_count:
        return None
    return {'page': page, 'request': f'{page}페이지 {action}: {question}'}


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box)==4 and
            all(isinstance(v,(int,float)) and math.isfinite(v) for v in box) and
            0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1)


def mixed_code_layout(page):
    """Number labels in distinct columns plus code: row text can interleave programs."""
    native = page.get('nativeText', '') or ''
    if not re.search(r'#include|\b(?:int main|cout|printf|def |public class)\b', native):
        return False
    starts = [w['bbox'][0] for w in page.get('words', [])
              if valid_box(w.get('bbox')) and re.fullmatch(r'\d{1,3}[.)]', w.get('text', ''))]
    return len(starts) > 1 and max(starts)-min(starts) > .2


def image_request(document, question, page, *, page_bound=False):
    """Return at most one image location, only for a question tied to this page.

    Page content alone never turns an ordinary conceptual question into an
    exercise request. Missing native text is a fallback, not a semantic judge.
    """
    if not page_bound or type(page) is not int or not 1<=page<=len(document.get('pages',[])) or NEW.search(question):return None
    # An explicit exclusion is not a request to inspect the excluded exercise.
    intent=re.sub(r'(?:문제|예제|그림|그래프)(?:는|은|를|을)?\s*(?:말고|제외하고|빼고)', '', question)
    if CONCEPT_ONLY.search(question):return None
    exercise=bool((EXERCISE.search(intent) or re.search(r'\d+\s*번',intent)) and SOLVE.search(intent))
    # A page-bound "풀이 ㄱㄱ" is already a solving request even without "문제".
    if not re.search(r'개념만|뜻만|말고|제외|빼고|하지\s*마|풀지|계산하지', intent):
        exercise = exercise or bool(DIRECT_SOLVE.search(intent))
    visual=bool(VISUAL.search(intent) and INSPECT.search(intent))
    spatial_detail=bool(POSITION.search(intent) and VISIBLE_DETAIL.search(intent))
    target=document['pages'][page-1]
    native='\n'.join(c.get('text','') for c in document.get('chunks',[]) if c.get('page')==page and c.get('source')=='native')
    if not native:native=target.get('nativeText','') or ''
    boxes=[r['bbox'] for r in target.get('imageRegions',[]) if valid_box(r.get('bbox'))
           and (r['bbox'][2]-r['bbox'][0])*(r['bbox'][3]-r['bbox'][1])>=.002]
    damaged=bool(re.search(r'\(cid:\d+\)|\ufffd',native))
    sparse=len(re.sub(r'\s','',native))<100
    formula=bool(re.search(r'[∫∑Σ√=]|[\U0001d400-\U0001d7ff]|\\(?:frac|int)',native))
    # A named page with only "please" still needs its source, even after a
    # topic change. Do not infer an old task or broaden ordinary concept queries.
    remainder = re.sub(r'\d+\s*(?:페이지|쪽)|\b(?:page\s*|p\.\s*)\d+', '', intent, flags=re.I)
    vague_page = (remainder != intent and bool(re.fullmatch(
        r'(?:\s|[?!.,~]|그럼|그러면|이번엔|부탁할게|부탁해요|부탁해|부탁|해줘|해주세요|'
        r'봐줘|보여줘|알려줘|설명해줘|좀|도|은|는|을|를|please)*', remainder, re.I)))
    if exercise and mixed_code_layout(target):reason='numbered_code_layout'
    elif exercise and (boxes or formula or damaged):reason='exercise_visual_or_formula'
    elif visual:reason='explicit_visual_inspection'
    elif spatial_detail and boxes:reason='page_spatial_detail'
    elif boxes and sparse and INSPECT.search(intent):reason='sparse_page_text'
    elif vague_page and ((boxes and sparse) or damaged):reason='named_page_missing_text'
    else:return None
    # A single isolated raster on a sparse page (e.g. a scanned question) can
    # be cropped safely. Mixed text/diagrams and uncertain regions use the page.
    box=[0,0,1,1]
    if len(boxes)==1 and sparse and not re.search(r'전체|전부|whole|entire',intent,re.I):
        x0,y0,x1,y1=boxes[0]
        box=[max(0,x0-.025),max(0,y0-.04),min(1,x1+.025),min(1,y1+.04)]
    identity=hashlib.sha256(repr((document.get('fingerprint'),page,box)).encode()).hexdigest()[:24]
    return {'page':page,'regionId':'tutor-page-'+identity,'selectedRegion':box,'reason':reason}


@lru_cache(maxsize=8)
def _render(source_path, fingerprint, mtime_ns, size, page, box):
    from pdf_visual import render_region
    with _RENDER_LOCK:
        return render_region(Path(source_path).parent,{'page':page,'selectedRegion':box})


def prepare(folder, document, question, page, *, page_bound=False):
    location=image_request(document,question,page,page_bound=page_bound)
    if location is None or folder is None:return [],[]
    source=Path(folder)/'source.pdf'
    try:
        stat=source.stat()
        image=_render(str(source.resolve()),document.get('fingerprint',''),stat.st_mtime_ns,stat.st_size,
                      location['page'],tuple(location['selectedRegion']))
    except Exception:
        # Rendering failure must not claim an unseen image was attached.
        return [],[]
    return [dict(image)],[location]
