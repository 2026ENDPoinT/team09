"""Local source accounting shared by K1.1.2/3. No inference or API calls."""
import re
import operator

VERSION = 'source-review-v7-accounting-section-context-math-lines'
PRINTABLE_STRING = {'type':'string', 'pattern':r'^[^\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]*$'}


def repair_serialized_closer(text):
    r"""Recover an intact \(formula\u000a) envelope, never code or math tokens."""
    code = re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2|(?m:^[ \t]{4}[^\n]*(?:\n|$))'
                      r'|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|(?<!\\)\\\([^\n]*?(?<!\\)\\\)')
    def fix(value):
        def doubled(match):
            inside=match[1]
            if re.search(r'[가-힣\x00-\x1f]',inside):return match[0]
            if any(inside.count(a)!=inside.count(b)for a,b in [('(',')'),('{','}'),('[',']')]):return match[0]
            return r'\('+inside+r'\)'
        value=re.sub(re.escape(r'\\(')+r'([^\n]{1,1200}?)'+re.escape(r'\\)'),doubled,value)
        def closer(match):
            inside = match[1]
            if (re.search(r'[가-힣\x00-\x1f]', inside)
                    or re.search(r'[=+*/^_-]\s*$',inside)
                    or r'\(' in inside or r'\)' in inside
                    or any(inside.count(a) != inside.count(b)
                           for a, b in [('(', ')'), ('{', '}'), ('[', ']')])):
                return match[0]
            return r'\(' + inside + r'\)'
        value=re.sub(r'\\\(([^\n]{1,1200}?)\\u000a\)', closer, value)
        def math_line(match):
            content=match[1]
            prose_probe=re.sub(r'\\(?:text|mathrm|operatorname)\{[^{}]*\}','',content)
            prose_probe=re.sub(r'\\[A-Za-z]+|_\{?[A-Za-z,]+\}?','',prose_probe)
            # Only an entire, balanced line with explicit TeX math syntax.
            # Plain identifiers, prose, code and incomplete expressions stay put.
            if (not re.search(r'\\(?:Delta|delta|frac|sqrt|vec|sum|int|mathrm|theta|alpha|beta|gamma|sin|cos|tan)\b',content)
                    or re.search(r'[가-힣\x00-\x1f;$`]|\\[\[\]()]',content)
                    or re.search(r'\b[A-Za-z]{2,}\b',prose_probe)
                    or re.search(r'[=+*/^_-]\s*$',content)
                    or any(content.count(a)!=content.count(b)for a,b in [('(',')'),('{','}'),('[',']')])):
                return match[0]
            return r'\('+content+r'\)'
        return re.sub(r'(?<=\n)([^\n]{1,1200})(?=\n)',math_line,value)
    out=[]; start=0
    for match in code.finditer(text):
        out.extend((fix(text[start:match.start()]),match[0]));start=match.end()
    return ''.join(out)+fix(text[start:])


def missing_expression_slot(text):
    """Detect a vanished expression, not an ordinary line break before prose.

    The API can replace a whole equation with LF; there is nothing to reconstruct.
    Only incomplete result templates followed by a dangling particle qualify.
    """
    protected=re.sub(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2','',text)
    return bool(re.search(
        r'(?:이므로|성분은|결과는|더하면|나누면|대입하면|쓰면|나타내면)'
        r'[ \t]*\n[ \t]*(?:[,，]|(?:의|가|는|를)(?=\s)|예요|이에요|이고|이며)',protected))


def numerical_guards(blocks):
    """Evaluate only literal single-variable comparisons, never execute code."""
    compare={'<':operator.lt,'<=':operator.le,'>':operator.gt,'>=':operator.ge,
             '==':operator.eq,'!=':operator.ne}
    pattern=re.compile(r'\b(?:if|while)\s*\(\s*([A-Za-z_]\w*)\s*(<=|>=|==|!=|<|>)\s*(-?\d{1,6})\s*\)')
    result=[]
    for b in blocks:
        for m in pattern.finditer(b.get('text','')):
            variable,op,number=m.groups();boundary=int(number)
            result.append({'blockId':b['id'],'expression':m[0],
                'samples':[{'variable':variable,'value':v,'conditionTrue':compare[op](v,boundary)}
                           for v in [boundary-1,boundary,boundary+1]],
                'scope':'Only comparison truth is computed. Read the source branch for the resulting action.'})
    return result


def section_source_context(blocks, job, neighbors):
    """Retain native premises when a source section is split across jobs.

    Background only: no ownership, citations, task boundaries or API calls change.
    Image-only gaps must not hide the earlier problem statement from a conclusion.
    """
    owned={b['id']for b in job['blocks']}
    seen={(n['page'],n['text'])for n in neighbors}
    anchors={}
    for b in job['blocks']:
        key=(b['page'],b.get('headingId'))
        if key[1] and key not in anchors:anchors[key]=b['id']
    extra=[];remaining=2200
    for (page,heading),first in anchors.items():
        candidates=[]
        for b in blocks:
            if b['id']==first:break
            text=b.get('text','').strip()
            if (b['id']in owned or b.get('page')!=page or b.get('headingId')!=heading
                    or not text or b.get('kind')in ('heading','label','page_number','footer')
                    or b.get('localRole')in ('decoration','navigation') or len(text)>1200):continue
            candidates.append(b)
        # A section's opening statement and nearest preceding text have priority.
        selected=candidates[:2]+candidates[-2:]
        selected_ids={b['id']for b in selected}
        for b in candidates:
            text=b['text'].strip();key=(page,text)
            if b['id']not in selected_ids or key in seen or len(text)>remaining:continue
            extra.append({'page':page,'text':text,'backgroundOnly':True,
                          'contextRole':'earlier_source_in_same_section'})
            seen.add(key);remaining-=len(text)
    return extra+neighbors


def continuation_visual_context(blocks, job):
    """One bounded background view when only a section's bottom tail is owned.

    Avoid guessing a diagram's initial conditions from its isolated conclusion.
    The synthetic crop ID is never an evidence ID or part of target coverage.
    """
    owned={b['id']for b in job['blocks']}
    for page in sorted({b['page']for b in job['blocks']}):
        local=[b for b in job['blocks']if b['page']==page and b.get('bbox')]
        if not local or min(b['bbox'][1]for b in local)<.65:continue
        if sum((b['bbox'][2]-b['bbox'][0])*(b['bbox'][3]-b['bbox'][1])for b in local)>.12:continue
        headings={b.get('headingId')for b in local}-{None,''}
        if len(headings)!=1:continue
        previous=[b for b in blocks if b['id']not in owned and b.get('page')==page
                  and b.get('headingId')in headings and b.get('bbox')
                  and b['bbox'][1]<min(x['bbox'][1]for x in local)]
        if not any(b.get('hasVisual') and (b['bbox'][2]-b['bbox'][0])*(b['bbox'][3]-b['bbox'][1])>.035
                   for b in previous):continue
        bounds=previous+local
        box=[min(b['bbox'][0]for b in bounds),min(b['bbox'][1]for b in bounds),
             max(b['bbox'][2]for b in bounds),max(b['bbox'][3]for b in bounds)]
        return [{'id':'background-section-'+str(page),'page':page,'bbox':box,
                 'kind':'visual','hasVisual':True,'visualOnly':True,'text':'',
                 'zone':local[0].get('zone',0),'zoneBounds':[0,0,1,1]}]
    return []


def continuation_context_images(folder, blocks, job, *, available_images=1):
    from pathlib import Path
    # Required target images take priority over optional background. Keep the
    # existing single-request image cap and never drop or downsample a target.
    if available_images<1:return []
    crops=continuation_visual_context(blocks,job)
    if not crops:return []
    from pdf_new_concept_v02_regions import render_crops
    images,_=render_crops(folder,crops,Path(folder)/'generated'/'source-section-context')
    label=('BACKGROUND SOURCE CONTEXT · page '+str(crops[0]['page'])+
           '. Earlier diagram and premises in the same section. Use only to interpret '
           'the owned continuation. This image introduces NO target/evidence IDs; '
           'do not summarize its earlier material again or cite its synthetic crop ID.')
    return [{**image,'sourceLabel':label}for image in images]


def reading_effort(blocks, default='none'):
    """Spend reasoning inside the same request only for code guards/visual relations."""
    if default!='none':return default
    if numerical_guards(blocks):return 'low'
    for block in blocks:
        box=block.get('bbox')
        if (block.get('hasVisual') and box and (box[2]-box[0])*(box[3]-box[1])>.035
                and (block.get('visualOnly') or len(block.get('text','').strip())<50)):
            return 'low'
    return default


def require_semantic_checks(wire_format, blocks, guards):
    """Use the existing check fields in this same request; add no model pass."""
    visual=any(b.get('hasVisual') and b.get('bbox') and
        (b['bbox'][2]-b['bbox'][0])*(b['bbox'][3]-b['bbox'][1])>.035 for b in blocks)
    if not guards and not visual:return
    setup=wire_format['json_schema']['schema']['properties']['concepts']['items']['properties']['sourceSetup']['properties']
    for field in ['observedRelations','boundaryChecks']:
        setup[field]['minItems']=1


def partial_visual_source(request):
    """Absent extracted words cannot establish ownership of untranscribed pixels."""
    blocks=request.get('job',{}).get('blocks',request.get('payload',{}).get('blocks',[]))
    return any(b.get('hasVisual') or b.get('visualOnly') or b.get('geometryFallback')
               or b.get('visualContentRequiresReading') for b in blocks)


def pack_crop_runs(runs, crop_runs, weight, crop_limit, weight_limit):
    """Pack consecutive source runs; a heading stays with its following run.

    No source is added, removed or reordered and parallelism is not consulted.
    A single oversized source remains whole for the existing input-budget guard.
    """
    result=[];batch=[]
    for run in runs:
        combined=batch+run
        if batch and (len(crop_runs(combined))>crop_limit or weight(combined)>weight_limit):
            # Move a trailing heading to the next packet instead of orphaning it.
            tail=[]
            while batch and batch[-1].get('kind') in ('heading','label'):
                tail.insert(0,batch.pop())
            if tail and (len(crop_runs(tail+run))>crop_limit or weight(tail+run)>weight_limit):
                batch+=tail;tail=[]
            if batch:result.append(batch)
            batch=tail+run
        else:batch=combined
    if batch:result.append(batch)
    return result


def structural_context(block, blocks, accounted, reason=''):
    """Prove only layout accessories; short formulas/variables are not disposable."""
    text=block.get('text','').strip();box=block.get('bbox')
    if block.get('localRole')=='decoration' or block.get('kind') in ('footer','page_number'):
        return '쪽 번호나 장식 요소예요.'
    if not text or not box:return None
    peers=[b for b in blocks if b['id']!=block['id'] and b.get('page')==block.get('page')
           and accounted.get(b['id'],('',))[0]=='summarized']
    if (re.search(r'페이지\s*(?:번호|숫자)|쪽\s*번호|page\s+number',reason,re.I)
            and re.fullmatch(r'\d{1,4}',text) and box[1]>.90
            and (box[2]-box[0])*(box[3]-box[1])<.005):
        return '이미지에서 확인한 쪽 번호예요.'
    # A visual font/backplate is not by itself a diagram. Accept a model-read
    # heading only with native text, a shallow text box and taught body below.
    if (re.search(r'제목|표제|heading|section title',reason,re.I) and len(text)<100
            and block.get('wordIds') and box[3]-box[1]<.12
            and not re.search(r'[=→⇒<>]|\\[A-Za-z]+|\b(?:int|void|return|if|class)\b',text)
            and any(p.get('bbox') and p['bbox'][1]>=box[1] for p in peers)):
        return '이미지에서 확인한 제목을 같은 페이지의 설명과 연결했어요.'
    # A bullet immediately preceding a taught line is layout, not an equation.
    if re.fullmatch(r'(?:[•●▪◦·–—-]\s*)+',text):
        for peer in peers:
            other=peer.get('bbox')
            if other and 0<=other[0]-box[2]<.08 and min(box[3],other[3])>max(box[1],other[1]):
                return '설명한 문장에 붙은 글머리표예요.'
    if re.fullmatch(r'[,;(){}]',text) and box[2]-box[0]<.025:
        for peer in peers:
            other=peer.get('bbox')
            if (other and min(box[3],other[3])>max(box[1],other[1])
                    and min(abs(box[0]-other[2]),abs(other[0]-box[2]))<.016):
                return '설명한 원문 문장에 붙은 구두점이에요.'
    # The extractor can emit a small native fragment inside a larger, cited
    # code/text region. Require both geometry and literal text containment.
    compact=lambda value:re.sub(r'\s+','',value)
    if len(text)<=120:
        for peer in peers:
            other=peer.get('bbox');source=compact(peer.get('text',''))
            if (other and len(source)>len(compact(text)) and compact(text) in source
                    and other[0]-.001<=box[0] and other[1]-.001<=box[1]
                    and box[2]<=other[2]+.001 and box[3]<=other[3]+.001):
                return '설명한 원문 영역 안에 포함된 텍스트 조각이에요.'
    return None

# Applied only by K1.1.2/3. Kept in their prompt identity/cache keys.
REVIEW_RULES = r'''
SOURCE ACCOUNTING AND SEMANTIC CHECK (within this same response)
Before returning, account for EVERY target ID: cite it in a supported segment or
record an explicit exclusion/uncertainty. If its meaning is integrated into another
paragraph, cite that ID there; do NOT call it excluded. Include the IDs of formulas,
worked results and diagrams actually used, not merely their neighboring captions.
A short native string may sit over a full image: inspect the whole owned image before
calling it a title, punctuation or decoration. For true headings/footers, state their
layout role explicitly in excludedBlocks. Do not invent teaching for navigation.
The grouping title never limits target content. Keep a worked example that changes
initial direction, boundary/initial conditions, reference level, or solution method.
Only varying numerical inputs with the same conditions/method can be repetition.
A different example from the preceding subject is not irrelevant merely because it
was packed into the same request. If source labels contradict its statement/solution,
preserve supported steps and flag ONLY the conflicting claim in an uncertain segment.
Read a branch's condition separately from the action taken when it is true or false.
For loops/recursion trace the continuation AND exit condition against the actual code;
a slide label saying 'termination condition' cannot reverse the code's branch meaning.
For diagrams distinguish alternative paths from consecutive segments, and choices from
simultaneous contributions. Sum paths only if the source depicts one continuous journey.
Preserve original-input expressions and source answers, using \approx for rounded values.
Do not chain rounded intermediates as exact equalities or invent decimal correction values.
A source discrepancy needs conflicting source evidence, not unverified mental arithmetic.
Displayed intermediate values are rounded measurements, not exact operands. A difference
within their stated rounding precision is NOT a source contradiction. Explain rounding
briefly only if needed; preserve original-input expressions and the printed final result.
Preserve the general relationship and valid steps when one printed value is inconsistent.
For a ratio or rate, the definition sentence must name BOTH numerator and denominator
in the same order as its formula: "A를 B로 나눈 값" for A/B. Check that the Korean
postpositions preserve that division direction. A correct formula does not excuse
a reversed or incomplete definition sentence.
Never replace a variable, equation or numeric result with an empty line/control escape.
Each result sentence must retain its actual expression; if unavailable, mark that claim
uncertain instead of emitting a template with its mathematical content missing.
Earlier native source in neighboringContext provides premises of a split section.
Use those premises to interpret a trailing conclusion; never infer initial conditions
from a generated grouping title/description. Keep unrelated examples separate.
A case or diagram supplement to an already defined concept belongs in its explanation,
not a new definition-less concept. Maintain meaningful definition/explanation/easy fields.
'''


def reconcile_coverage(coverage, blocks):
    """Reconcile only provable layout relations across completed job boundaries.

    Explicit uncertain/math warnings are never overridden. No semantic inference
    from a short native caption is made about a large image behind it.
    """
    by_id={b['id']:b for b in blocks}
    accounted={c['blockId']:(c['state'],c.get('reason','')) for c in coverage}
    for c in coverage:
        if c['state']!='needs_review' or c.get('reviewKind')=='content':continue
        reason=c.get('reason','')
        if reason.startswith('local_output_check:') or not (
                reason=='응답에 이 영역의 처리 여부가 빠졌어요.' or
                reason.startswith(('기사·사례·도식','그림 원문에','참고 그림으로'))):continue
        b=by_id.get(c['blockId'])
        if not b:continue
        text=b.get('text','').strip();box=b.get('bbox')
        if not box or len(box)!=4:continue
        w,h=box[2]-box[0],box[3]-box[1]
        peers=[p for p in blocks if p.get('page')==b.get('page') and
               accounted.get(p['id'],('',))[0]=='summarized' and p.get('bbox')]
        native=bool(b.get('wordIds')) and not b.get('visualOnly') and not b.get('geometryFallback')
        role=None
        if native and re.fullmatch(r'\d{1,4}',text) and box[1]>.92 and w*h<.002 and peers:
            role='설명된 페이지 하단의 작은 쪽 번호예요.'
        elif native and re.fullmatch(r'[,;:：•●▪◦·–—]+',text) and w<.035 and h<.06:
            if any(min(box[3],p['bbox'][3])>max(box[1],p['bbox'][1]) and
                   min(abs(box[0]-p['bbox'][2]),abs(p['bbox'][0]-box[2]))<.035 for p in peers):
                role='설명한 문장에 붙은 구두점·글머리표예요.'
        elif (native and 2<len(text)<90 and h<.10 and w*h<.06
              and not re.search(r'[=→⇒<>∑∫]|\\[A-Za-z]+|\b(?:if|return|while|int|void)\b',text)
              and not re.search(r'(?:이다|한다|된다|있다|없다|하라|구하라)[.!?]?$',text)):
            heading=(b.get('kind')in ('heading','label') or
                     box[1]<.12 and (b.get('fontSize') or 0)>=18 or
                     bool(re.search(r'제목|표제|heading|section title',reason,re.I)))
            if heading and any(p['bbox'][1]>=box[3] for p in peers):
                role='같은 페이지에서 설명된 본문을 조직하는 제목이에요.'
        if role:
            c.update(state='context',reason=role)
    return coverage
