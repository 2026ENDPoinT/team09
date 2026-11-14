"""Frozen ver.99 local output gates. No network/reviewer and no batch-wide abort.

Only narrow, decidable mathematical forms are checked. Unsupported expressions
are left alone, not marked correct. Diagnostics never become learner prose.
"""
from __future__ import annotations
import ast
import copy
import math
import re
from fractions import Fraction

VERSION='ver.99-local-checks-19-balanced-esc-math-envelope'

FIELDS=('title','definition','explanation','easyExplanation')

def repair_prose_serialization(text):
    """Repair delimiters/paragraph escapes only outside code and existing math."""
    protected=re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2|'
        r'(?m:^[ \t]{4}[^\n]*(?:\n|$))|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|'
        r'(?P<wrapped_math>\x1c(?:\\\([^\x00-\x1f]*?\\\)|\\\[[^\x00-\x1f]*?\\\])\x1d)')
    def prose(value):
        value=value.replace(r'\n\n','\n\n')
        # Observed SOH pairs are damaged delimiters around otherwise intact
        # math. Preserve the expression; unmatched controls remain rejected.
        def soh_math(match):
            content=match[1]
            if (not re.search(r'[가-힣\x00-\x1f]',content)
                and re.fullmatch(r'[A-Za-z0-9α-ωΑ-Ω\\{}()\[\]^_+*/=.,;:| <≥≤>−-]+',content)
                and (re.search(r'\\[A-Za-z]+|[=^_+*/]',content)
                     or re.fullmatch(r'[A-Za-zα-ωΑ-Ω]',content.strip()))):
                return r'\('+content+r'\)'
            return match[0]
        value=re.sub('\x01([^\x01]{1,1200})\x01',soh_math,value)
        # The spelled-out quantity already identifies the complete unit. A
        # damaged redundant abbreviation can be omitted without guessing µ or
        # a missing symbol. Do not repair an unlabelled/standalone corrupt unit.
        value=re.sub(r'(\d+(?:\.\d+)?\s*마이크로리터)\('
            r'(?=[^()\n]{0,16}[\x00-\x08\x0b\x0c\x0e-\x1f])'
            r'[\x00-\x1f0-9 .µμuL]{1,20}\)',r'\1',value)
        def inline(match):
            content=match[1]
            probe=re.sub(r'\\(?:text|mathrm|operatorname|begin|end)\{[^{}]*\}','',content)
            probe=re.sub(r'\\[A-Za-z]+','',probe)
            if re.search(r'[가-힣]',probe) or (re.search(r'\b[A-Za-z]{3,}\b',probe)
                    and not ('=' in probe and re.fullmatch(r'[A-Za-z0-9_{}^+*/=()., \-]+',probe))):
                return match[0]
            if (re.search(r'\\[A-Za-z]+|[=^_+*/]',content)
                or re.fullmatch(r'[A-Za-zα-ωΑ-Ω]',content.strip())):
                return r'\('+content+r'\)'
            return match[0]
        # Some replies put a line break immediately after a single-dollar
        # delimiter. A balanced pair still carries the same intact expression.
        value=re.sub(r'(?<![\\$])\$(?!\$)([^$]{1,2000})(?<!\\)\$(?!\$)',inline,value)
        # Tabs occasionally stand in for both inline-math delimiters. Require
        # an explicit TeX/subscript/operator expression; ordinary tabs, table
        # cells, prose and code indentation must remain whitespace.
        def tab_math(match):
            content=match[1]
            if (content!=content.strip() or re.search(r'[가-힣\x00-\x1f;]',content)
                    or not re.search(r'\\[A-Za-z]+|[_^=]',content)
                    or any(content.count(a)!=content.count(b) for a,b in (('(',')'),('{','}'),('[',']')))):
                return match[0]
            fixed=inline(match)
            return fixed if fixed!=match[0] else match[0]
        return re.sub(r'\t([^\t\n]{1,1200})\t',tab_math,value)
    parts=[];cursor=0
    for match in protected.finditer(text):
        # FS/GS wrapping an already delimited expression carries no math.
        # Remove only that observed matched wrapper, preserving the expression.
        span=match[0][1:-1] if match.group('wrapped_math') else match[0]
        # Markdown quote prefixes can leak inside a whole display equation.
        # Remove only unanimous quote prefixes, including an empty quoted
        # line containing just '>'. Preserve actual relational operators,
        # partially quoted expressions, inline math and fenced code.
        delimiters=next(((left,right) for left,right in (('$$','$$'),(r'\[',r'\]'))
                         if span.startswith(left) and span.endswith(right)),None)
        if delimiters:
            left,right=delimiters;inside=span[len(left):-len(right)]
            lines=inside.splitlines(keepends=True);nonempty=[line for line in lines if line.strip()]
            if nonempty and all(re.match(r'^[ \t]*>[ \t]+',line)
                                or re.fullmatch(r'[ \t]*>[ \t]*(?:\r?\n)?',line)
                                for line in nonempty):
                span=left+''.join(re.sub(r'^([ \t]*)>[ \t]?',r'\1',line,count=1)
                                   if line.strip() else line for line in lines)+right
        parts.extend((prose(text[cursor:match.start()]),span));cursor=match.end()
    return ''.join(parts)+prose(text[cursor:])
# Match source/production limitations, not a transition word or subject conditions.
_SOURCE=re.compile(r'(?:이\s*(?:자료|이미지|그림|페이지|원문|조각)|(?:자료|원문|본문|텍스트|이미지|그림|조각)(?:에는|에서는|에서|에|만으로|가|이)|사진에 나온|예시 이미지|판독|읽히|읽을 수|제공된|제시된\s*정보)')
_LIMIT=re.compile(r'(?:없(?:어|으|다|어요|습니다)|않(?:아|으|다|아요|습니다)|어렵|부족|불분명|희미|불가능|확정.{0,15}(?:못|어려)|확인.{0,15}(?:못|어려)|알 수 없|추가 정보.{0,10}필요)')
# A paragraph that merely names items and then says there is no explanation
# cannot serve as their explanation. Do not mistake subject/data limitations
# or a source-supported relationship followed by a caveat for such filler.
_PRODUCTION_LIMIT=re.compile(r'(?:자료|원문|본문|페이지)는\s*(?:두|세|이|해당)\s*'
    r'(?:기법|항목|명칭)(?:을|만|들을).{0,40}소개하지만.{0,120}(?:설명|제시)하지(?:는)?\s*않')
_BOUNDARY_DATUM=re.compile(r'수치|비율|(?:예측|측정|추정)값|상관관계|관찰|발표|보도|주장')
_BOUNDARY_NEGATION=re.compile(
    r'(?:뜻하|의미하|입증하|증명하|보장하)지(?:는)?\s*않'
    r'|(?:확정|단정|입증|증명)(?:할|될).{0,12}(?:수(?:는|가)?\s*없|못|어려)')
_SOURCE_GAP=re.compile(
    r'(?:판독|식별).{0,12}(?:않|못|불가|어렵)'
    r'|읽.{0,8}(?:없|못|않)'
    r'|(?:설명|정보|내용|근거|수치|숫자|본문|텍스트|원문)'
    r'(?:\s*(?:가|이|는|도|를|을))?\s*(?:없|부족|누락|제공되지)'
    r'|(?:제목|명칭|이름)만.{0,8}(?:있|제시|나열)')

_PRODUCTION_GAP=re.compile(
    r'판독|읽(?:히|을\s*수)|불분명|희미|추가\s*정보|정보.{0,12}부족'
    r'|(?:수치|숫자|내용|설명|텍스트|정보|근거).{0,12}(?:없|누락|부족)'
    r'|(?:제목|명칭|이름)만.{0,8}(?:있|제시|나열)'
    r'|(?:설명|제시|제공)(?:되어|돼|되|하지).{0,12}(?:않|못)')


def interpretation_boundary(text):
    """An observed datum not implying an outcome is teaching, not missing prose.

    This only preserves the sentence; ordinary source-uncertainty and math gates
    still decide whether its paragraph may be published. Explicit missing or
    unreadable source information remains production filler.
    """
    return bool(_BOUNDARY_DATUM.search(text) and _BOUNDARY_NEGATION.search(text)
                and not _SOURCE_GAP.search(text))


def learner_text(text, *, preserve_boundaries=True):
    # Sentence boundaries are prose punctuation followed by whitespace. Decimal
    # points and TeX blocks are preserved; no keyword-to-end truncation.
    parts=re.split(r'(?<=[.!?])(?=\s|$)|(?<=요)(?=\n)|\n\n',text)
    kept=[];removed=[]
    for part in parts:
        if ((_SOURCE.search(part) and _LIMIT.search(part)
                and (not preserve_boundaries or _PRODUCTION_GAP.search(part))
                and not (preserve_boundaries and interpretation_boundary(part)))
                or _PRODUCTION_LIMIT.search(part)):removed.append(part.strip())
        else:kept.append(part)
    return (text if not removed else '\n\n'.join(p.strip() for p in kept if p.strip())),removed


def tex_expression(text):
    text=text.strip().replace(r'\left','').replace(r'\right','')
    text=re.sub(r'\\(?:,|;|!|quad|qquad|displaystyle)\s*','',text)
    text=text.replace(r'\cdot','*').replace(r'\times','*').replace(r'\pi','pi')
    text=text.replace('−','-').replace('π','pi')
    # Nested fractions are reduced inside-out. Unsupported TeX stays unparsed.
    for _ in range(8):
        newer=re.sub(r'\\(?:d?frac|tfrac)\{([^{}]+)\}\{([^{}]+)\}',r'((\1)/(\2))',text)
        if newer==text:break
        text=newer
    text=text.replace('{','(').replace('}',')').replace('^','**')
    text=re.sub(r'(?<=\d)(?=pi\b|[a-zA-Z(])','*',text)
    text=re.sub(r'(?<=\))(?=[\d(a-zA-Z])','*',text)
    text=re.sub(r'\bpi\s*(?=[(a-zA-Z])','pi*',text)
    return text


def numeric(expr):
    """Tiny expression interpreter, never eval/exec or arbitrary attribute calls."""
    node=ast.parse(tex_expression(expr),mode='eval')
    if len(list(ast.walk(node)))>60:raise ValueError('complex')
    def walk(n):
        if isinstance(n,ast.Expression):return walk(n.body)
        if isinstance(n,ast.Constant) and type(n.value) in (int,float):
            if abs(n.value)>1e12:raise ValueError('large')
            return float(n.value)
        if isinstance(n,ast.Name) and n.id=='pi':return math.pi
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):
            return (-1 if isinstance(n.op,ast.USub) else 1)*walk(n.operand)
        if isinstance(n,ast.BinOp):
            a,b=walk(n.left),walk(n.right)
            if isinstance(n.op,ast.Add):return a+b
            if isinstance(n.op,ast.Sub):return a-b
            if isinstance(n.op,ast.Mult):return a*b
            if isinstance(n.op,ast.Div):return a/b
            if isinstance(n.op,ast.Pow) and abs(b)<=12:return a**b
        raise ValueError('unsupported')
    v=walk(node)
    if not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('nonreal')
    return v


def math_semantics(text):
    issues=[]
    forms=re.findall(r'\$\$([\s\S]*?)\$\$|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]',text)
    for tup in forms:
        form=next((x for x in tup if x), '')
        # Corrupt serialization can leave empty delimiters after local cleanup.
        # Flag that paragraph; do not abort its otherwise valid paid unit.
        if not form.strip():
            issues.append('empty_math')
            continue
        # Check only complete numerical equalities, never rounded approximations.
        if '=' in form and not re.search(r'\\(?:approx|sim|leq|geq)|[≈<>]',form):
            for a,b in zip(form.split('='),form.split('=')[1:]):
                try:
                    left,right=numeric(a),numeric(b)
                    if not math.isclose(left,right,rel_tol=1e-7,abs_tol=1e-8):issues.append('numeric_equality')
                except (ValueError,SyntaxError,ZeroDivisionError,OverflowError,TypeError):pass
        # Deliberately narrow: constant * t^(rational exponent), numeric bounds.
        pattern=r'\\int_\{?(-?\d+)\}?\^\{?(-?\d+)\}?\s*(.*?)\s*(?:\\[,;!])?\s*d\s*([a-z])\s*=\s*(.+)'
        m=re.fullmatch(pattern,form.strip(),re.S)
        if not m:continue
        lo,hi,integrand,var,rhs=m.groups()
        try:
            term=tex_expression(integrand).replace(' ','')
            mm=re.fullmatch(r'(.*?)'+re.escape(var)+r'\*\*\(([-\d]+(?:/\d+)?)\)',term)
            if not mm:continue
            coefficient=numeric(mm[1].rstrip('*') or '1');power=float(Fraction(mm[2]));exponent=power+1
            if not exponent or float(lo)<0:continue
            expected=coefficient*(float(hi)**exponent-float(lo)**exponent)/exponent
            if not math.isclose(expected,numeric(rhs),rel_tol=1e-7,abs_tol=1e-8):issues.append('monomial_integral')
        except (ValueError,SyntaxError,ZeroDivisionError,OverflowError,TypeError):pass
    return sorted(set(issues))


def repair_paired_null_math(text):
    # A null *pair* surrounding intact non-Korean math is a known delimiter
    # serialization defect. Never erase an unmatched null or guess a missing symbol.
    text=text.replace(r'\u0000','\x00')
    def fix(m):
        inner=m[1]
        if not inner.strip() or re.search(r'[\x00-\x1f]',inner):return m[0]
        # Repeated unmatched prefixes must not turn intervening prose into math.
        prose=re.sub(r'\\text\{[^{}]*\}','',inner)
        prose=re.sub(r'\([가-힣 A-Za-z0-9]+[+*/−-][가-힣 A-Za-z0-9]+\)','',prose)
        if re.search(r'[가-힣]',prose):return m[0]
        if not re.fullmatch(r'[가-힣A-Za-z0-9\\{}()\[\]^_+*/=.,;:| <≥≤>−-]+',inner):return m[0]
        if r'\text{' not in inner:
            inner=re.sub(r'[가-힣]+(?: +[가-힣]+)*',lambda x:r'\text{'+x[0]+'}',inner)
        return r'\('+inner+r'\)'
    return re.sub('\x00([^\x00]{1,1200})\x00',fix,text)


def repair_repeated_math_span(text):
    """Restore a corrupt span only from an identical intact peer in this field.

    For example a,b between two control codes can reuse an already valid [a,b]
    interval in the same sentence. No matching peer means no guessed repair.
    """
    peers=re.findall(r'\\\(([^\n]*?)\\\)',text)
    def canonical(value):return re.sub(r'[\s\[\]{}()]','',value)
    def replace(m):
        options={p for p in peers if canonical(p)==canonical(m[1])}
        return r'\('+next(iter(options))+r'\)' if len(options)==1 else m[0]
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]([^\x00-\x1f]{1,200})[\x00-\x08\x0b\x0c\x0e-\x1f]',replace,text)


def repair_paired_code_controls(text):
    """Restore the observed FS-wrapped code spans; leave ambiguous controls for review."""
    def replace(match):
        code=match.group(1)
        if ('`' in code or code != code.strip() or
                not re.fullmatch(r'[A-Za-z0-9_&*;\[\]().=+\-<> ]{1,120}',code)):
            return match.group(0)
        return '`'+code+'`'
    return re.sub(r'\x1c([^\x00-\x1f\n]{1,120})\x1c',replace,text)


def repair_balanced_esc_math_envelopes(text):
    r"""Remove only a redundant ESC envelope around intact inline math.

    The observed form is ESC+[ + an already complete \\(...\\) + ESC+].
    Its contents survive byte-for-byte. An unmatched marker, missing symbol,
    prose span, display equation, or code example is deliberately left alone.
    Ordinary formula/source guards still run after this serialization repair.
    """
    code=re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:\1|\Z)|(`+)[^\n]*?\2|'
                    r'(?m:^[ \t]{4}[^\n]*(?:\n|$))')
    envelope=re.compile(r'\x1b\[(\\\([^\x00-\x1f]*?\\\))\x1b\]')
    def replace(match):
        inner=match[1]
        content=inner[2:-2]
        if not content.strip() or any(mark in content for mark in (r'\(',r'\)',r'\[',r'\]','$$')):
            return match[0]
        return inner
    output=[];cursor=0
    for match in code.finditer(text):
        output.extend((envelope.sub(replace,text[cursor:match.start()]),match[0]));cursor=match.end()
    output.append(envelope.sub(replace,text[cursor:]))
    return ''.join(output)


def repair_paired_fs_gs_math(text):
    """Restore intact math inside the observed FS/GS delimiter pair only.

    The model occasionally serializes one endpoint as a literal JSON escape.
    No symbol, number or unmatched control is guessed or erased. Code remains
    verbatim, including examples that discuss these control characters.
    """
    text=repair_balanced_esc_math_envelopes(text)
    code=re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2')
    pair=re.compile(r'(?:\x1c|\\u001[cC])([^\x00-\x1f]{1,1200}?)(?:\x1d|\\u001[dD])')
    def replace(match):
        content=match[1]
        if (content!=content.strip() or not content or
                not re.fullmatch(r'[A-Za-z0-9α-ωΑ-Ω\\{}()\[\]^_+*/=.,;:| <≥≤>−-]+',content)):
            return match[0]
        if content.startswith(r'\(') and content.endswith(r'\)'):return content
        if content.startswith('$$') and content.endswith('$$'):return content
        if re.fullmatch(r'[A-Za-z]{4,}',content):return match[0]
        if re.search(r'(?<!\\)\b(?:int|char|float|double|void|new|delete|return|const|class|struct|std)\b|;|::|->',content):
            return match[0]
        return r'\('+content+r'\)'
    output=[];cursor=0
    for match in code.finditer(text):
        output.extend((pair.sub(replace,text[cursor:match.start()]),match[0]));cursor=match.end()
    output.append(pair.sub(replace,text[cursor:]))
    return ''.join(output)


def repair_plural_rule_from_examples(entry):
    """Correct only a directly contradicted regular plural rule with two matching examples."""
    definition=entry.get('definition','')
    explanation=entry.get('explanation','')
    if not (('복수형' in definition or '복수형' in entry.get('title','')) and '모음으로 끝나고' in definition
            and re.search(r'-s를\s*붙',definition)):
        return
    pairs=re.findall(r'([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)(?:은|는)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)',explanation)
    if len(pairs)<2 or not all(source[-1].lower() not in 'aeiouáéíóúü'
            and plural.lower()==source.lower()+'es' for source,plural in pairs):
        return
    entry['definition']=re.sub('모음으로 끝나고','자음으로 끝나고',definition,count=1)
    entry['definition']=re.sub(r'-s를\s*붙','-es를 붙',entry['definition'],count=1)


def prepare_learner_segment(text, *, preserve_boundaries=True, structured=False):
    """Share the exact serialization/math/prose transform with local replay."""
    from pdf_ai import repair_generated_math_controls
    from pdf_new_concept_v02_math import format_math
    text=repair_prose_serialization(repair_paired_fs_gs_math(text))
    text=repair_paired_code_controls(repair_repeated_math_span(
        repair_paired_null_math(repair_generated_math_controls(text))))
    text=format_math(text)
    return (text,[])if structured else learner_text(text,preserve_boundaries=preserve_boundaries)


def materialize_segments(value, *, preserve_boundaries=True, distinguish_supplements=False, review_policy=None):
    """Preserve supported paragraphs without publishing uncertain assertions.

    Legacy flat replies have no paragraph/source map and keep their conservative
    gate. New replies write each paragraph once with its own source IDs.
    """
    from pdf_ai import repair_generated_math_controls,study_math_issues
    from pdf_new_concept_v02_math import format_math
    from pdf_saved_teaching_compat import active, materialize
    if active(value):
        return materialize(value,lambda text:prepare_learner_segment(text,structured=True)[0],
                           lambda text:study_math_issues({'body':text})+math_semantics(text))
    uncertain={x.get('blockId') for x in value.get('uncertainBlocks',[]) if isinstance(x,dict)}
    optional_easy = review_policy is not None and review_policy.optional_easy
    result=[]
    for entry in value['concepts']:
        if isinstance(entry,dict):
            entry.pop('_paragraphScoped',None)
            entry.pop('_partialSupported',None)
        if not isinstance(entry,dict) or 'segments' not in entry:
            result.append(entry);continue
        if review_policy is not None: review_policy.select_segments(entry)
        fields={name:[] for name in FIELDS if name!='title'};ids=[]
        for segment in entry.get('segments',[]):
            if not isinstance(segment,dict):continue
            kind=segment.get('kind');refs=segment.get('blockIds',[]);text=segment.get('text')
            if kind=='uncertain' and refs:
                value['uncertainBlocks'] += [{'blockId':i,'reason':str(text or '일부 설명의 근거 확인이 필요해요.')}
                                            for i in refs]
                value.setdefault('processingDiagnostics',[]).append({'stage':'paragraph_check',
                    'conceptTitle':entry.get('title'),'kind':kind,'blockIds':refs,'reason':'uncertain_paragraph'})
                continue
            if kind not in fields or not isinstance(text,str) or not refs:continue
            if review_policy is not None: text=review_policy.prepare(text,refs)
            reason='uncertain_source' if uncertain.intersection(refs) else None
            if distinguish_supplements:
                from pdf_study_review import missing_expression_slot
                if missing_expression_slot(text):
                    reason=reason or 'missing_expression_in_supported_paragraph'
                    value['uncertainBlocks'] += [{'blockId':i,'reason':'local_output_check: '+reason} for i in refs]
            text,_=prepare_learner_segment(text,preserve_boundaries=preserve_boundaries)
            if review_policy is not None: text=review_policy.prepare(text,refs)
            semantics=(math_semantics(text) if review_policy is None else review_policy.math_issues(text,refs))
            if not text.strip() or study_math_issues({'body':text}) or semantics:
                reason=reason or 'invalid_or_empty_supported_paragraph'
                value['uncertainBlocks'] += [{'blockId':i,'reason':'local_output_check: '+reason} for i in refs]
            if reason:
                value.setdefault('processingDiagnostics',[]).append({'stage':'paragraph_check',
                    'conceptTitle':entry.get('title'),'kind':kind,'blockIds':refs,'reason':reason})
                continue
            fields[kind].append(text);ids.extend(refs)
        if all(parts for name,parts in fields.items() if not (optional_easy and name=='easyExplanation')):
            result.append({k:v for k,v in entry.items() if k!='segments'} |
                          {k:'\n\n'.join(parts) for k,parts in fields.items()} |
                          {'blockIds':list(dict.fromkeys(ids)),'_paragraphScoped':True})
        else:
            supplement=(distinguish_supplements and not fields['definition']
                and fields['explanation'] and (optional_easy or fields['easyExplanation'])
                and not any(i in uncertain for i in ids)
                and ((review_policy is not None and review_policy.permits_supplement(entry))
                     or ((review_policy is None or entry.get('sourceSetup',{}).get('teachingRole')
                          not in ('independent','continuation')) and
                         any(c.get('definition') and c.get('explanation') for c in result))))
            if supplement:
                value.setdefault('processingDiagnostics',[]).append({'stage':'format_check',
                    'conceptTitle':entry.get('title'),'blockIds':list(dict.fromkeys(ids)),
                    'reason':'supplement_without_repeated_definition'})
            else:
                value['uncertainBlocks'] += [{'blockId':i,'reason':'local_output_check: incomplete_supported_concept'}
                                            for i in dict.fromkeys(ids)]
            # A bad/missing explanation must not erase a supported definition
            # and diagram description. Keep only checked paragraphs, explicitly
            # pending review; never fabricate a replacement for a missing field.
            if ids and (fields['definition'] or fields['explanation']):
                result.append({k:v for k,v in entry.items() if k!='segments'} |
                    {k:'\n\n'.join(parts) for k,parts in fields.items()} |
                    {'blockIds':list(dict.fromkeys(ids)), '_paragraphScoped':True,
                     '_partialSupported':True})
    value['concepts']=result
    return value


def prepare_response(raw, *, preserve_boundaries=True, distinguish_supplements=False, review_policy=None):
    from pdf_ai import repair_generated_math_controls,study_math_issues
    from pdf_new_concept_v02_math import format_math
    if not isinstance(raw,dict) or not isinstance(raw.get('concepts'),list):return raw
    from pdf_saved_teaching_compat import active
    structured=active(raw)
    value=copy.deepcopy(raw);good=[]
    if distinguish_supplements:
        from pdf_study_review import repair_serialized_closer
        for entry in value['concepts']:
            if not isinstance(entry,dict):continue
            for segment in entry.get('segments',[]):
                if isinstance(segment,dict) and isinstance(segment.get('text'),str):
                    segment['text']=repair_serialized_closer(segment['text'])
            for field in FIELDS:
                if isinstance(entry.get(field),str):
                    entry[field]=repair_serialized_closer(entry[field])
    value.setdefault('uncertainBlocks',[])
    value=materialize_segments(value,preserve_boundaries=preserve_boundaries,
                               distinguish_supplements=distinguish_supplements,review_policy=review_policy)
    # A sentence continuing onto the next page does not make its visible,
    # correctly cited teaching uncertain; the next page is handled separately.
    cited={block_id for entry in value['concepts'] if isinstance(entry,dict)
           for block_id in entry.get('blockIds',[])}
    value['uncertainBlocks']=[item for item in value['uncertainBlocks']
        if not (isinstance(item,dict) and item.get('blockId') in cited
                and re.search(r'문장.{0,16}(?:다음|이어지)',str(item.get('reason',''))))]
    uncertain={r.get('blockId') for r in value['uncertainBlocks'] if isinstance(r,dict)}
    for entry in value['concepts']:
        if not isinstance(entry,dict):good.append(entry);continue
        repair_plural_rule_from_examples(entry)
        removed=[]
        for field in FIELDS:
            if isinstance(entry.get(field),str):
                if review_policy is not None:
                    entry[field]=review_policy.prepare(entry[field],entry.get('blockIds',[]))
                text=repair_prose_serialization(repair_paired_fs_gs_math(entry[field]))
                text=repair_paired_code_controls(repair_repeated_math_span(
                    repair_paired_null_math(repair_generated_math_controls(text))))
                entry[field],drop=((format_math(text),[])if structured else
                    learner_text(format_math(text),preserve_boundaries=preserve_boundaries));removed+=drop
        problems=study_math_issues(entry)
        # A partly readable region can support retained paragraphs while another
        # paragraph from that same region remains explicitly under review.
        paragraph_scoped=entry.pop('_paragraphScoped',False)
        if uncertain.intersection(entry.get('blockIds',[])) and not paragraph_scoped:
            problems.append('uncertain_source_cited_as_teaching')
        for field in FIELDS:
            text=entry.get(field,'') or ''
            problems+=(math_semantics(text) if review_policy is None else
                       review_policy.math_issues(text,entry.get('blockIds',[])))
        if not entry.get('title','').strip() or (not entry.get('_partialSupported') and not structured
                and any(not entry.get(k,'').strip() for k in FIELDS if not
                        (review_policy is not None and review_policy.optional_easy and k=='easyExplanation'))):
            problems.append('empty_supported_content')
        if problems:
            value['uncertainBlocks'] += [{'blockId':i,'reason':'local_output_check: '+','.join(sorted(set(problems)))} for i in entry.get('blockIds',[])]
        else:good.append(entry)
    value['concepts']=good
    return value
