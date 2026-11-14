"""Local ver.02 output gates. No network/reviewer and no batch-wide abort.

Only narrow, decidable mathematical forms are checked. Unsupported expressions
are left alone, not marked correct. Diagnostics never become learner prose.
"""
from __future__ import annotations
import ast
import copy
import math
import re
from fractions import Fraction

VERSION='ver.02-local-checks-3'

FIELDS=('title','definition','explanation','easyExplanation')
# Match source/production limitations, not a transition word or subject conditions.
_SOURCE=re.compile(r'(?:이\s*(?:자료|이미지|그림|페이지|원문)|(?:자료|원문|본문|텍스트|이미지|그림)(?:에는|에서는|에서|에|만으로|가|이)|판독|읽히|읽을 수|제공된|제시된\s*정보)')
_LIMIT=re.compile(r'(?:없(?:어|으|다|어요|습니다)|않(?:아|으|다|아요|습니다)|어렵|부족|불분명|희미|불가능|확정.{0,15}(?:못|어려)|확인.{0,15}(?:못|어려)|알 수 없|추가 정보.{0,10}필요)')

def learner_text(text):
    # Sentence boundaries are prose punctuation followed by whitespace. Decimal
    # points and TeX blocks are preserved; no keyword-to-end truncation.
    parts=re.split(r'(?<=[.!?])(?=\s|$)|(?<=요)(?=\n)|\n\n',text)
    kept=[];removed=[]
    for part in parts:
        if _SOURCE.search(part) and _LIMIT.search(part):removed.append(part.strip())
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
        form=next(x for x in tup if x)
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


def prepare_response(raw):
    from pdf_ai import repair_generated_math_controls,study_math_issues
    from pdf_new_concept_v02_math import format_math
    if not isinstance(raw,dict) or not isinstance(raw.get('concepts'),list):return raw
    value=copy.deepcopy(raw);good=[]
    value.setdefault('uncertainBlocks',[])
    uncertain={r.get('blockId') for r in value['uncertainBlocks'] if isinstance(r,dict)}
    for entry in value['concepts']:
        if not isinstance(entry,dict):good.append(entry);continue
        removed=[]
        for field in FIELDS:
            if isinstance(entry.get(field),str):
                text=repair_repeated_math_span(repair_paired_null_math(repair_generated_math_controls(entry[field])))
                entry[field],drop=learner_text(format_math(text));removed+=drop
        problems=study_math_issues(entry)
        if uncertain.intersection(entry.get('blockIds',[])):problems.append('uncertain_source_cited_as_teaching')
        for field in FIELDS:problems+=math_semantics(entry.get(field,'') or '')
        if any(not entry.get(k,'').strip() for k in FIELDS):problems.append('empty_supported_content')
        if problems:
            value['uncertainBlocks'] += [{'blockId':i,'reason':'local_output_check: '+','.join(sorted(set(problems)))} for i in entry.get('blockIds',[])]
        else:good.append(entry)
    value['concepts']=good
    return value
