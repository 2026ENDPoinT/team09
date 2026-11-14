"""Selective K1.1.3 teaching; old engines retain their original validators."""
import math
import re

VERSION = 'selective-source-resolution-v3:k123-source-case-v3'
_CODE = re.compile(r'(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1|(`+)[^\n]*?\2')
_MATH = re.compile(r'\$\$([\s\S]*?)\$\$|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]')
_QUESTION = re.compile(r'예제|연습\s*문제|기출|\b(?:example|exercise|problem)\b',re.I)
_EXAMPLE_HEADING = re.compile(r'^\s*(?:\[[^\]\n]{0,40}기출[^\]\n]*\]|예제(?:\s|\d|[.:：]|$)|'
                              r'연습\s*문제|(?:example|exercise|problem)\b)',re.I)


def outside_code(text, transform):
    out=[];start=0
    for m in _CODE.finditer(text):
        out.extend((transform(text[start:m.start()]),m[0]));start=m.end()
    return ''.join(out)+transform(text[start:])


class ReviewPolicy:
    optional_easy = True

    def __init__(self, blocks):
        self.blocks={b['id']:b for b in blocks}

    def select_segments(self, entry):
        decision=entry.get('sourceSetup',{}).get('learnerDifficulty',{})
        if decision.get('kind')=='none':
            entry['segments']=[s for s in entry.get('segments',[]) if not
                               (isinstance(s,dict) and s.get('kind')=='easyExplanation')]

    def source_example(self, refs):
        # Native example/problem markers anchor only their own following source
        # span. A later real heading resets it. Course names, numeric answers and
        # generated titles never establish this proof.
        remaining=set(refs);anchored=False
        example=re.compile(r'^\s*(?:예제(?:\s|\d|[:：.]|$)|예\s+|문제(?:\s|\d|[:：.]|$)|'
                           r'(?:example|exercise|problem)\b)',re.I)
        has_example=any(example.match(b.get('text',''))for b in self.blocks.values())
        part=re.compile(r'^\s*\((?:[a-z]|\d+)\)\s*',re.I)
        continuation=re.compile(r'^(?:구하|구하여|계산하|설명하|조사하|증명하).{0,30}$')
        for block in self.blocks.values():
            text=block.get('text','').strip()
            if example.match(text):
                anchored=True
            elif block.get('kind')=='heading'and text:
                if has_example and part.match(text):anchored=True
                elif not(anchored and continuation.fullmatch(text)):anchored=False
            if block['id']in remaining:
                if not anchored:return False
                remaining.remove(block['id'])
        return not remaining

    def permits_supplement(self, entry):
        setup=entry.get('sourceSetup',{})
        if setup.get('teachingRole')=='source_case':
            # A concrete sourced account is not a dictionary definition. Require
            # actual MAIN teaching plus source observations; never promote an
            # empty/easy-only response or an abstract technical method this way.
            main=[s for s in entry.get('segments',[])if isinstance(s,dict)
                  and s.get('kind')=='explanation'and isinstance(s.get('text'),str)
                  and s['text'].strip()and s.get('blockIds')]
            refs={i for s in main for i in s['blockIds']}
            if not main or not refs or any(i not in self.blocks for i in refs):return False
            from pdf_k121_exact_checks import kinds
            symbolic,lifetime=kinds([self.blocks[i]for i in refs])
            if lifetime:return False
            # A printed application of an already taught method need not invent
            # another dictionary definition. A new symbolic rule without native
            # example proof cannot use this path; all normal technical checks
            # and MAIN citation checks still run downstream.
            if symbolic and not self.source_example(refs):return False
            return bool(setup.get('sourceQuotes')or setup.get('observedRelations'))
        if setup.get('teachingRole')=='continuation':
            return bool(setup.get('sourceQuotes') or setup.get('observedRelations'))
        if setup.get('teachingRole')=='independent':return False
        # Compatibility for paid replies before roles were explicit. Require a
        # literal native connective/qualification, not the generated title.
        refs={i for s in entry.get('segments',[]) for i in s.get('blockIds',[])}
        native=[self.blocks[i].get('text','') for i in refs if i in self.blocks]
        return any(re.search(r'^\s*(?:단[,， ]|다만|따라서|그러므로|즉[,， ])|임을 이용|같으므로',s)
                   for s in native)

    def constants(self, refs):
        # Only literal source assumptions in this same cited page, never a
        # generated title/setup or an assumption borrowed from another example.
        selected=[self.blocks[i] for i in refs if i in self.blocks]
        texts='\n'.join(b.get('text','') for b in selected)
        values=set(re.findall(r'(?:π|\\pi)\s*(?:=|≈|≒)\s*(\d+(?:\.\d+)?)',texts))
        return {'pi':float(next(iter(values)))} if len(values)==1 else {}

    def prepare(self, text, refs):
        from pdf_k113_math import restore
        text=restore(text)
        def fix(value):
            def intact(content):
                return (bool(re.search(r'\\[a-zA-Z]+|[=^_]',content))
                    and not re.search(r'[가-힣\x00-\x1f`]',content)
                    and all(content.count(a)==content.count(b) for a,b in [('(',')'),('{','}'),('[',']')])
                    and not re.search(r'[=+*/^_-]\s*$',content))
            def envelope(m):
                content=m[1]
                if not intact(content):return m[0]
                return r'\('+content+r'\)'
            # Repair only a balanced, intact envelope. Missing formulas remain
            # missing; unmatched delimiters and code/currency are not guessed.
            value=re.sub(r'(?<![\\$])\$(?!\$)([^$\n]{1,8000})\$(?!\$)',envelope,value)
            # Observed wire corruption replaces ONLY a closing delimiter with
            # a newline (sometimes serialized literally) and a standalone "i?".
            # Recover a complete balanced expression; never fill a lost term.
            value=re.sub(r'\\\(([^\n`]{1,8000}?)(?:\\u000a)?[ \t]*\n[ \t]*\n?'
                         r'[ \t]*i\?[ \t]*(?:\n|$)',envelope,value)
            from pdf_new_concept_ver99_checks import numeric
            constants=self.constants(refs)
            def rounding(m):
                form=next((x for x in m.groups() if x is not None),'')
                pieces=form.split('=')
                # Just one computed equality with a decimal literal result.
                # No blanket tolerance or repairs to incorrect integer answers.
                if len(pieces)!=2 or not re.fullmatch(r'\s*[+-]?\d+\.\d+\s*',pieces[1]):return m[0]
                expr=pieces[0]
                if not re.search(r'\\frac|[+*/^-]',expr):return m[0]
                if 'pi' in constants:expr=expr.replace(r'\pi','('+str(constants['pi'])+')')
                try:
                    exact,printed=numeric(expr),float(pieces[1])
                    precision=len(pieces[1].strip().split('.')[1])
                    if (not math.isclose(exact,printed,rel_tol=1e-7,abs_tol=1e-8)
                            and abs(exact-printed)<=.5*10**(-precision)+1e-12):
                        return m[0].replace('=',r'\approx',1)
                except (ValueError,SyntaxError,ZeroDivisionError,OverflowError,TypeError):pass
                return m[0]
            return _MATH.sub(rounding,value)
        return outside_code(text,fix)

    def math_issues(self, text, refs):
        from pdf_new_concept_ver99_checks import math_semantics
        constants=self.constants(refs)
        if 'pi' in constants:
            # Validation only. Keep the printed expression/source assumption.
            text=outside_code(text,lambda s:_MATH.sub(
                lambda m:m[0].replace(r'\pi','('+str(constants['pi'])+')'),s))
        issues=math_semantics(text)
        prose=_CODE.sub('',text)
        if (prose.count(r'\(')!=prose.count(r'\)') or prose.count(r'\[')!=prose.count(r'\]')
                or re.search(r'(?m)^\s*i\?\s*$',prose)):
            issues.append('unrecovered_math_envelope')
        return issues


def exercise_exclusion(item, block, blocks, parts):
    """Require a source-identified example and retain any claimed new principle.

    A model's generic 'unnecessary' reason is not sufficient to hide a diagram.
    No subject-specific keyword list or extra reviewer request is involved.
    """
    from pdf_study_reading_policy import code_content
    decision=item.get('exerciseSelection')
    if not isinstance(decision,dict) or decision.get('kind') not in ('practice','worked_example'):return False
    if code_content(block):return False
    quote=decision.get('sourceQuote','')
    normalize=lambda s:re.sub(r'\s+','',str(s)).lower()
    page=[b for b in blocks if b.get('page')==block.get('page')]
    if len(normalize(quote))<3:return False
    literal=(any(_QUESTION.search(b.get('text','')) for b in page) and any(
        normalize(quote) in normalize(b.get('text','')) for b in page))
    # A screenshot's question/answer cannot be string-matched to pdfplumber's
    # empty native text. A visible native example heading can still anchor that
    # image, up to (but not across) the next independent source heading.
    anchored=False
    for peer in page:
        text=peer.get('text','').strip()
        if _EXAMPLE_HEADING.search(text) and len(text)<90:anchored=True
        elif peer.get('kind')=='heading' and text:anchored=False
        if peer['id']==block['id']:break
    visual_example=(anchored and block.get('hasVisual') and len(block.get('text',''))<90)
    if not literal and not visual_example:return False
    role=block.get('planRoleBeforeVisualGuard',block.get('planRole'))
    # An ordinary teaching block must not be excluded merely because another
    # exercise appears on the page. Uncertain image-only targets need a review.
    if role not in ('exercise','illustration') and not visual_example:return False
    if re.search(r'정의|정리\s*[:：]|일반식|\b(?:theorem|definition)\b',block.get('text',''),re.I):return False
    title=decision.get('keptConceptTitle','')
    if title:
        return any(p.get('title')==title and p.get('body','').strip() for p in parts)
    return True
