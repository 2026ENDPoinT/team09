"""Local routing guards: text-only classification cannot inspect image content.

Keep meaningful image regions in the existing teaching request. Tiny icons and
thin slide rules stay on the cheap path; no separate reviewer API is introduced.
"""
from __future__ import annotations
import re
from pdf_study_reading_policy import ENABLED, VERSION as READING_VERSION, code_content

VERSION = 'visual-selection-v3-confirmed-nonteaching-only'
if ENABLED:VERSION += ':'+READING_VERSION
SKIPPED = {'decoration', 'navigation', 'exercise'}


def substantive_visual(block):
    if not block.get('hasVisual') or block.get('localRole') == 'decoration' or (
            block.get('localRole') == 'exercise' and not code_content(block)):
        return False
    if block.get('geometryFallback') or block.get('kind') == 'page':
        return True
    box=block.get('bbox',[])
    if len(box)!=4:return False
    width,height=box[2]-box[0],box[3]-box[1]
    # A few pixels of rule or a speaker icon do not justify another image call.
    return width>=.06 and height>=.025 and width*height>=.006


def locally_skipped(block):
    role=block.get('localRole')
    if role=='exercise' and code_content(block):return False
    return role in SKIPPED and not (role=='navigation' and substantive_visual(block))


def protect_visual_groups(groups):
    """Retain each source/group once, including old confirmed plans."""
    for group in groups:
        for block in group['blocks']:
            if not (substantive_visual(block) or code_content(block)):continue
            block['visualReadingRequired']=True
            if block.get('planRole') in {'navigation','exercise'}:
                block['planRoleBeforeVisualGuard']=block['planRole']
                block['planRole']='uncertain'
    return groups


def unjustified_visual_exclusion(block, reason):
    """Do not silently drop a source-bearing image after a partial topic read.

    Geometry cannot prove that a figure contains teaching, but neither a planner
    title nor a model's claim of irrelevance proves the opposite. Keep uncertain
    substantive images pending unless the existing image read identified an
    actual cover/contents page or unanswered exercise. This is local bookkeeping;
    it neither invents content nor requests another API review.
    """
    # A readable code example teaches behavior even without a printed answer.
    # A reason string alone cannot prove the code is redundant with prior teaching.
    if code_content(block):return True
    return substantive_visual(block) and not verified_non_teaching_reason(reason)


def verified_non_teaching_reason(reason):
    """Used after image reading only, never to skip the initial image call."""
    reason=re.sub(r'\s+', ' ', str(reason))
    # An exclusion reason that also admits taught workings/content is not a
    # confirmed empty quiz/cover, even if it happens to mention those words.
    taught = re.finditer(
        r'(?:풀이|해설|개념\s*설명|원리).{0,18}(?:있|포함|제공|제시(?:돼|되|됨))|'
        r'\b(?:contains?|includes?|provides?)\b.{0,30}'
        r'\b(?:worked|solution|explanation|principle)\b|'
        r'\b(?:worked\s+solutions?|explanations?)\s+(?:are\s+)?present\b',
        reason,re.I)
    for match in taught:
        before = reason[max(0,match.start()-20):match.start()]
        after = reason[match.end():match.end()+18]
        if (re.search(r'\b(?:not|no|without)\s*$',before,re.I) or
                re.search(r'\b(?:no|without)\b',match.group(),re.I) or
                re.match(r'(?:(?:하|되|돼)?지(?:는)?)\s*(?:않|못)',after)):
            continue
        return False
    quiz = re.search(r'퀴즈|(?:OX|O/X).{0,20}문항|빈칸.{0,20}문항|'
        r'연습\s*문제|평가\s*문항|문제\s*제시|'
        r'\b(?:quiz|exercises?|practice\s+(?:questions?|problems?)|'
        r'problem\s+statements?|multiple[- ]choice|true/false|fill[- ]in[- ]the[- ]blank)\b',
        reason,re.I)
    only_questions = re.search(r'(?:문항(?:들)?|문제|질문)(?:만|뿐)|'
        r'\b(?:only\s+(?:questions?|problems?|exercises?)|'
        r'(?:questions?|problems?|exercises?)\s+only|unanswered|unsolved)\b', reason,re.I)
    negated_only = re.search(r'(?:문항(?:들)?|문제|질문)만(?:이)?\s*(?:아니|아닌)',reason)
    no_solution = re.search(r'(?:풀이|정답|해설).{0,25}(?:없|않|미제공)|'
        r'\b(?:no|without)\b.{0,30}\b(?:solutions?|answers?|worked\s+steps)\b',reason,re.I)
    if quiz and ((only_questions and not negated_only) or no_solution):return True
    return bool((re.search(r'표지|목차|안내\s*슬라이드',reason)
            and re.search(r'강의명|(?:강의|수업|교재)\s*자료|강사|소속|제목|주차|주제|이름|장·절',reason)) or
        (re.search(r'\b(?:cover\s+(?:page|information)|title\s+slide|table\s+of\s+contents|agenda)\b',reason,re.I)
            and re.search(r'\b(?:title|course|instructor|institution|chapter|headings?)\b',reason,re.I)))
