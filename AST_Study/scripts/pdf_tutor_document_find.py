"""Count literal mentions in original PDF text and requested image text locally.

Only an explicit, single-term document count is handled here. A search miss is
never promoted to document-wide absence when a page still needs visual reading.
Generated study notes and overlapping search chunks are not counted as original.
"""
import re
import unicodedata
from pathlib import Path

_COUNT = re.compile(r'몇\s*(?:번|회|차례|군데)|(?:언급|등장)\s*(?:횟수|수)|how\s+many\s+times',re.I)
_SCOPE = re.compile(r'pdf|피디에프|문서|자료|원문|여기|이\s*강의|전체\s*내용',re.I)
_PAGE = re.compile(r'\d+\s*(?:페이지|쪽)|\b(?:page|p)\.?\s*\d+',re.I)
_QUOTE = re.compile(r'[“‘「『"\']([^“”‘’「」『』"\'\n]{1,80})[”’」』"\']')
_NAMED = re.compile(r'([가-힣A-Za-z][가-힣A-Za-z0-9_.·+-]{0,59}?)(?:이라는|라는|란)\s*'
                    r'(?:사람|인물|이름|용어|단어|표현|문구|개념|글자|텍스트|말(?=$|\s|[이가은는을를]))')
_SIMPLE = re.compile(r'(?<!\S)([가-힣A-Za-z][가-힣A-Za-z0-9_.·+-]{1,59}?)(?:은|는|이|가|을|를)\s*'
                     r'(?:(?:총|모두|전체에서|문서에서)\s*)?(?:몇\s*(?:번|회|차례)|언급|등장)')
_MULTIPART = re.compile(r'설명|해설|해석|요약|정리|비교|풀이|계산|번역|뜻|의미|원리|왜|어떻게')
_EXTERNAL = re.compile(r'(?:웹|인터넷|위키|구글|온라인)|외부\s*(?:검색|자료)|다른\s*(?:pdf|문서|자료)',re.I)
_IMAGE = r'(?:이미지|그림|사진|도표|삽화|스캔본)'
_IMAGE_SCOPE = re.compile(_IMAGE + r'(?:들)?\s*(?:(?:속|안|내부|내)(?:에서|에|의)?|에서|에|의)(?:만|는|도)?(?!\w)' +
                          r'|\b(?:in|inside|within)\s+(?:the\s+)?(?:images?|figures?|pictures?)\b',re.I)
_ALL_SCOPE = re.compile(r'(?:본문|원문|텍스트)\s*(?:과|와|및|그리고)\s*' + _IMAGE +
                        '|' + _IMAGE + r'\s*(?:과|와|및|그리고)\s*(?:본문|원문|텍스트)' +
                        '|' + _IMAGE + r'\s*(?:까지|도\s*포함|를?\s*포함)')
_TEXT_CUE = re.compile(r'글자|텍스트|표기|문구|단어|언급|문자')
_TERM_JOIN_LEFT = re.compile(r'(?:[가-힣A-Za-z0-9](?:과|와|이랑|랑|하고|이나)|\b(?:또는|혹은|그리고|및))\s+$')
_TERM_JOIN_RIGHT = re.compile(r'^\s*(?:과|와|이랑|랑|하고|이나|또는|혹은|그리고|및)(?=\s|$)')
_BEFORE_IMAGE_TERM = re.compile(r'\s*(?:(?:적힌|쓰인|써\s*있는|나오는|보이는|들어\s*있는|있는)\s+)?'
                                r'(?:(?:글자|텍스트|문구|단어|문자)\s*(?:중|에서)\s*)?')


def request(question):
    if not _COUNT.search(question) or not _SCOPE.search(question) or _PAGE.search(question):
        return None
    if re.search(r'몇\s*번\s*(?:문제|문항)|(?:문제|문항|그림|표)\s*번호',question):
        return None
    if re.search(r'말고|아니라|제외|빼고|대신',question) or len(list(_NAMED.finditer(question)))>1:
        return None
    quoted = list(_QUOTE.finditer(question))
    if len(quoted)>1:
        return None
    named = _NAMED.search(question)
    match = quoted[0] if quoted else named or _SIMPLE.search(question)
    if match is None:
        return None
    term=match[1].strip()
    if not term or len(term)>80:
        return None
    if not quoted and not named and term in (
            '전체','내용','자료','문서','여기','언급','등장','사람','그사람','인물','이름','개념','용어','주제'):
        return None
    prefix, suffix = question[:match.start()], question[match.end():]
    rest = prefix + suffix
    if _MULTIPART.search(rest) or _EXTERNAL.search(rest):
        return None
    if (_TERM_JOIN_LEFT.search(prefix) or _TERM_JOIN_RIGHT.search(suffix)
            or re.search(r'각각|둘\s*(?:다|중)',rest)):
        return None
    if not quoted and re.fullmatch(r'(?:이|그|해당)?(?:문서|자료|PDF)(?:에|에서)?|전체\s*내용|그것|이것|그거|여기서|'
                                   r'(?:이|그|저|해당)(?:분|사람|인물|단어|표현|이름)',term,re.I):
        return None
    person=bool(re.search(r'(?:이라는|라는|란)\s*(?:사람|인물|이름)',match[0]))
    lookup = {'term':term,'kind':'person_name' if person else 'literal_mentions'}
    if _ALL_SCOPE.search(rest):
        lookup['scope'] = 'all'
    elif _IMAGE_SCOPE.search(rest):
        if not (quoted or named or _TEXT_CUE.search(rest)):
            return None  # An unmarked object may be depicted rather than written.
        earlier_scopes = list(_IMAGE_SCOPE.finditer(prefix))
        if not quoted and earlier_scopes and not _BEFORE_IMAGE_TERM.fullmatch(prefix[earlier_scopes[-1].end():]):
            return None  # The single-word matcher may have captured a compound's last word.
        lookup['scope'] = 'images'
    elif re.search(_IMAGE, rest):
        return None  # Do not turn an unresolved visual scope into a text-only scan.
    return lookup


def _text(value):
    return unicodedata.normalize('NFKC',str(value)).replace('\u00ad','')


def _pattern(term,kind='literal_mentions'):
    # Tolerate a PDF line wrap inside Korean words, preserving their letter
    # order. Multiword terms still require actual whitespace between words.
    words=[]
    for word in _text(term).split():
        words.append(r'\s*'.join(map(re.escape,word)) if re.fullmatch(r'[가-힣]+',word) else re.escape(word))
    expression=r'\s+'.join(words)
    if kind=='person_name':
        # A Korean grammatical particle is not part of the name; a longer
        # different name is. English possessives remain punctuation boundaries.
        particles=r'(?:이라는|라는|이라고|라고|이란|란|에게|께서|씨|님|은|는|이|가|을|를|의|과|와|도|만){1,2}'
        expression=r'(?<![가-힣A-Za-z0-9_])'+expression+r'(?=$|[^\w]|'+particles+r'(?=$|[^\w]))'
    return re.compile(expression,re.I)


def source_text(folder, count):
    """Read the connected original locally, independently of search/chunk layout."""
    if folder is None or not (Path(folder)/'source.pdf').is_file():
        return None
    try:
        import pypdfium2 as pdfium
        values=[]
        with pdfium.PdfDocument(Path(folder)/'source.pdf') as pdf:
            if len(pdf)!=count:return None
            for page in pdf:
                textpage=page.get_textpage()
                try:values.append(textpage.get_text_range())
                finally:textpage.close();page.close()
        return values
    except InterruptedError:
        raise
    except Exception:
        # Failed local access cannot turn a search miss into proven absence.
        return None


def scan(document, lookup, folder=None):
    pattern=_pattern(lookup['term'],lookup.get('kind'))
    pages=document.get('pages',[])
    scope=lookup.get('scope','text')
    image_only=scope=='images'
    visual_requested=scope in ('images','all')
    original=source_text(folder,len(pages))
    visual=None
    if visual_requested:
        from pdf_tutor_image_ocr import scan as scan_images
        native_pages=original if original is not None else [page.get('nativeText','') for page in pages]
        full_page_candidates=[number for number,native in enumerate(native_pages,1)
                              if not isinstance(native,str) or not native.strip()]
        visual=scan_images(folder,document,full_page_candidates=full_page_candidates,term=lookup['term'])
    visual_counts={number:sum(len(pattern.findall(_text(text))) for text in texts)
                   for number,texts in visual['textsByPage'].items()} if visual is not None else {}
    visually_checked=set(visual['checkedPages'])-set(visual['unreadablePages']) if visual is not None else set()
    counts=[];incomplete=[];overlap=[]
    for number,page in enumerate(pages,1):
        # Count each original page exactly once, including headers/footers.
        # Cached paraphrases, visual descriptions and chunk overlap cannot add
        # imaginary or duplicate occurrences.
        native=original[number-1] if original is not None else page.get('nativeText','')
        native=native if isinstance(native,str) else ''
        native_count=0 if image_only else len(pattern.findall(_text(native)))
        visual_count=visual_counts.get(number,0)
        # A scanned image can have a hidden text layer. If both sources match
        # on the same page, the larger count is a lower bound on their union.
        count=max(native_count,visual_count)
        if count:counts.append({'page':number,'count':count})
        native_incomplete=(folder is not None and original is None) or (original is None and (
            page.get('status')=='failed' or page.get('textState')=='failed'
            or any('다단/표' in str(w) for w in page.get('warnings',[]))))
        if visual_requested:
            if native_count and visual_count:
                overlap.append(number)
            if number not in visually_checked or (not image_only and native_incomplete):
                incomplete.append(number)
        elif not native.strip() or page.get('imageRegions') or page.get('ocrNeeded') or native_incomplete:
            incomplete.append(number)
    evidence=[]
    for item in (counts[:8] if not image_only else []):
        candidate=next((c for c in document.get('chunks',[]) if c.get('page')==item['page']
                        and c.get('source')=='native' and pattern.search(_text(c.get('text','')))),None)
        if candidate:
            evidence.append({'sourceId':candidate['id'],'documentId':document.get('documentId',''),
                'page':item['page'],'source':'native','quote':candidate['text'][:1200],
                'field':candidate.get('field','nativeText'),'start':candidate.get('start',0),
                'end':min(candidate.get('end',len(candidate['text'])),candidate.get('start',0)+1200)})
    result={'term':lookup['term'],'count':sum(p['count'] for p in counts),'pageCounts':counts,
            'pageCount':len(pages),'searchedPages':list(range(1,len(pages)+1)),
            'fullTextChecked':bool(pages) and not incomplete and not overlap,'unreadablePages':incomplete,
            'basis':'source_pdf_text' if original is not None else 'original_page_text','evidence':evidence}
    if visual_requested:
        result.update(scope=scope,basis='source_pdf_images' if image_only else 'source_pdf_text_and_images',
                      visualPages=sorted(page for page,count in visual_counts.items() if count),
                      searchedPages=sorted(visually_checked),overlapPages=overlap)
    return result


def answer(result):
    term=result['term'];count=result['count'];pages=result['pageCount']
    scope=result.get('scope','text')
    scope_label={'images':'이미지 속 글자','all':'본문과 이미지 속 글자'}.get(scope)
    if result['fullTextChecked']:
        if scope=='images':
            where=f'PDF {pages}쪽 전체에 포함된 이미지에서'
        elif scope=='all':
            where=f'PDF {pages}쪽 전체의 본문과 이미지에서'
        else:
            where=f'연결된 PDF {pages}페이지 전체를 검색한 결과,'
        if count and scope_label:
            text=f'{where} ‘{term}’ 표기를 **{count}회** 찾았어요.'
        elif count:
            text=f'{where} ‘{term}’ 표기는 **{count}회** 나와요.'
        elif scope_label:
            text=f'{where} ‘{term}’ 표기를 찾지 못했어요. 검색 결과는 **0회**예요.'
        else:
            text=f'{where} ‘{term}’은 나오지 않아요. 언급 횟수는 **0회**예요.'
    else:
        if scope_label:
            text=(f'{scope_label}에서 확인된 ‘{term}’ 표기는 **{count}회**예요.' if count else
                  f'확인한 범위에서 ‘{term}’ 표기를 찾지 못했어요.')
        else:
            text=f'현재 확인된 ‘{term}’ 표기는 **{count}회**예요.'
    locations=result['pageCounts']
    if locations:
        text+=' '+', '.join(f'{p["page"]}쪽 {p["count"]}회' for p in locations[:10])+'예요.'
        if len(locations)>10:text+=f' 그 밖의 {len(locations)-10}개 페이지에도 나와요.'
    if not result['fullTextChecked']:
        missing=result['unreadablePages']
        overlap=result.get('overlapPages',[])
        if missing:
            where=', '.join(str(p) for p in missing[:8])+'쪽'
            if len(missing)>8:where+=f' 등 {len(missing)}개 페이지'
            limitation='이미지 속 글자를 모두 읽지 못해' if scope=='images' else '일부 내용을 확인하지 못해'
            text+=f' {where}의 {limitation} 전체 횟수는 확정할 수 없어요.'
        elif overlap:
            text+=' 같은 표기가 본문과 이미지 양쪽에서 검색돼 중복을 제외한 전체 횟수는 확정할 수 없어요.'
        else:text+=' 문서 내용을 아직 확인할 수 없어 전체 횟수는 확정할 수 없어요.'
    return text
