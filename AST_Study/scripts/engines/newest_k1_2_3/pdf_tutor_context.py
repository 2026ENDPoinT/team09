"""Local source-task references, separate from the concept discussed in follow-ups.

Only explicit user identifiers/locations are retained, never an assistant's claim
about what the PDF contains. No model calls, PDF mutation, or generated answers.
"""
import re

ITEM = re.compile(r'(?<!\d)(\d{1,4})\s*번(?:\s*문제)?')
PAGE = re.compile(r'\d+\s*(?:페이지|쪽)|\b(?:page\s*|p\.\s*)\d+', re.I)
STOP = re.compile(r'말고|제외|빼고|하지\s*마|풀지|새\s*주제|다른\s*주제|새로운?\s*문제|만들|삭제')


def numbered_request(question, state, explicit_page, current_page, page_count):
    """Resolve a bare numbered item as a new source target, not the old concept.

    It is a candidate on the viewer page when no location was stated. Requiring
    full consumption prevents conceptual questions/ranges from being rewritten.
    """
    matches = list(ITEM.finditer(question))
    if len(matches) != 1 or STOP.search(question):
        return None
    rest = ITEM.sub('', PAGE.sub('', question))
    if not re.fullmatch(r'(?:\s|[?.!,~]|그럼|그러면|이번엔|이번에는|다음은|문제|'
                        r'부탁해요|부탁할게|부탁해|부탁|ㄱㄱ|해줘|해주세요|해줄래|'
                        r'문제|풀이|풀어줘|풀어|해설해줘|해설|설명해줘|설명|'
                        r'도|은|는|을|를|요)*', rest):
        return None
    page = explicit_page if explicit_page is not None else current_page
    if page is None:
        page = state.get('focus', {}).get('page')
    if type(page) is not int or not 1 <= page <= page_count:
        return None
    item = int(matches[0][1])
    if item < 1:
        return None
    action = ('solve' if re.search(r'풀|풀이', question) else
              state.get('sourceTask', {}).get('action', 'explain'))
    action = action if action in ('solve', 'explain') else 'explain'
    label = '문제 풀이와 해설' if action == 'solve' else '문항 해설'
    return {'page': page, 'item': item, 'action': action,
            'request': f'{page}페이지 {item}번 {label}',
            'candidate': explicit_page is None, 'newTarget': True}


def source_task(question, page, inherited=None):
    if type(page) is not int or page < 1 or STOP.search(question):
        return None
    if inherited and inherited.get('newTarget'):
        return {k: inherited[k] for k in ('page', 'item', 'action')}
    items = list(ITEM.finditer(question))
    if len(items) == 1 and re.search(r'풀|풀이|해설|설명|구해|계산', question):
        return {'page': page, 'item': int(items[0][1]),
                'action': 'solve' if re.search(r'풀|풀이|구해|계산', question) else 'explain'}
    return None


def prior_source_reference(state, plan, *, new_item=False, selected=False):
    """Keep a previous location as context, never as the new task or PDF proof."""
    if (new_item or selected or plan.get('followup') is not True or plan.get('pageChanged') or
            plan.get('scope') not in ('pdf','mixed')):
        return None
    source=state.get('sourceTask')
    if not isinstance(source,dict):return None
    page,item=source.get('page'),source.get('item')
    if type(page) is not int or page<1 or type(item) is not int or item<1:return None
    if plan.get('page') is not None and plan['page']!=page:return None
    return {'page':page,'item':item}
