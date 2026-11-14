"""Cheap, conservative checks for generated quiz text.

These checks reject observable output defects, not scientific claims. Logical
solvability, unique answers and difficulty still need independent review. The
input is read-only; source quotations are deliberately not inspected or changed.
"""
from __future__ import annotations

from fractions import Fraction
from html import unescape
import re
import unicodedata


def quality_text(value: object) -> str:
    """Normalize visible text for exact comparisons, without changing words."""
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()


def _fields(question):
    for key in ('stem', 'answer', 'explanation'):
        value = question.get(key)
        if isinstance(value, str):
            yield key, value
    options = question.get('options')
    for index, option in enumerate(options if isinstance(options, list) else []):
        if isinstance(option, dict):
            for key in ('text', 'explanation'):
                value = option.get(key)
                if isinstance(value, str):
                    yield f'options[{index}].{key}', value
    points = question.get('keyPoints')
    for index, value in enumerate(points if isinstance(points, list) else []):
        if isinstance(value, str):
            yield f'keyPoints[{index}]', value


def _bad_controls(value):
    # A real TAB, LF or CR can be ordinary formatting. Other C0/C1 controls are
    # not useful in a question and commonly result from a decoded LaTeX escape.
    controls = {ord(c) for c in value
                if (ord(c) < 32 and c not in '\t\n\r') or 127 <= ord(c) <= 159}
    # JSON "\text{...}" decodes to TAB + "ext{...}" if the slash was not escaped.
    # Keep normal indentation/tables, and only recognize distinctive remnants.
    if re.search(r'\t(?:ext(?:bf|it|rm)?\s*\{|imes\b|heta\b|riangle\b)', value):
        controls.add(9)
    if re.search(r'\r(?:ho\b|ight(?:\b|[\[({|])|angle\b)', value):
        controls.add(13)
    return sorted(controls)


_PARTICLES = (
    '으로부터', '에서부터', '이라고는', '이라고도', '이라는', '이라고',
    '이라면', '이라서', '에서는', '에서도', '에서', '으로', '로서', '로써',
    '처럼', '보다', '이며', '이고', '이라', '이다', '라고', '라는',
    '은', '는', '이', '가', '을', '를', '에', '와', '과', '의', '도', '만', '로',
)
_TERM_SUFFIX = r'(?:$|(?=[^\w])|(?=(?:' + '|'.join(_PARTICLES) + r')(?!\w)))'


def _term(answer):
    answer = quality_text(answer).strip(' *`\"\'“”‘’〈〉《》「」『』.。')
    # For "name (acronym/alias)", only the principal name is unambiguously the
    # answer. A parenthetical definition must not be mistaken for a leaked name.
    if '(' in answer and answer.endswith(')'):
        answer = answer[:answer.index('(')].strip()
    if not 2 <= len(answer.replace(' ', '')) <= 60:
        return ''
    # Multiple required names, numbers, formulas and code are left to review.
    # Letter-based terms may contain digits or a hyphen, e.g. "제1형 당뇨병".
    if (not any(unicodedata.category(c).startswith('L') for c in answer)
            or any(not (c.isalnum() or c.isspace() or c in '-·') for c in answer)):
        return ''
    return answer


def _term_is_visible(stem, answer):
    term = _term(answer)
    if not term:
        return False
    # Korean spacing differs naturally ("탄동 진자" / "탄동진자"). Do not erase
    # all boundaries: "탄성 충돌" is not exposed by the word "비탄성 충돌".
    units = re.findall(r'[가-힣]|[^가-힣\s]+', term)
    pattern = r'(?<!\w)' + r'\s*'.join(re.escape(unit) for unit in units) + _TERM_SUFFIX
    return re.search(pattern, unicodedata.normalize('NFKC', stem), re.IGNORECASE) is not None


_ADMISSION = re.compile(
    r'(?:문항|문제)의\s*정답(?:이|은)\s*유일하지\s*않(?:다|습니다|아요)'
    r'|(?:이|해당|현재|본)\s*(?:문항|문제)(?:은|는|에서|에는)?\s*'
    r'(?:정답이\s*(?:두|2)\s*개(?:이다|다|입니다|예요)|'
    r'복수\s*정답(?:이다|이\s*발생한다)|정답이\s*없(?:다|습니다|어요))'
)
_CONDITIONAL = re.compile(
    r'만약|(?:라면|다면|한다면|였으면|했으면|않으면)|'
    r'(?:생략|제거|누락|무시|빼|바꾸|변경)[^.!?。]{0,16}(?:면|경우)'
)
_WRONG_OPTION_ADMISSION = re.compile(
    r'^(?:(?:이|해당)\s*선지(?:는|가)\s*)?'
    r'(?:정답(?:이다|입니다|이에요|예요)|정답인\s*선지(?:이다|입니다))(?=[.!。\s]|$)'
)
_REVIEWING_AN_ITEM = re.compile(
    r'(?:제시된|다음|잘못된|오류가\s*있는)\s*(?:문항|문제)[^.!?。]{0,60}'
    r'(?:문제점|오류|수정|평가|검토|분석)'
)


def _admits_invalid_question(explanation):
    for sentence in re.split(r'(?<=[.!?。])\s+', explanation):
        match = _ADMISSION.search(sentence)
        if match and not _CONDITIONAL.search(sentence[:match.end()]):
            return True
    return False


def _math_width(value):
    # NFKC would turn x² into x2 and erase the mathematical distinction. Fold
    # fullwidth ASCII only; retain superscripts/subscripts until parsed.
    return ''.join(chr(ord(c)-0xFEE0) if '\uff01' <= c <= '\uff5e' else
                   ' ' if c == '\u3000' else c for c in unicodedata.normalize('NFC', value))


def _option_key(value):
    return re.sub(r'\s+', ' ', _math_width(value)).strip() if isinstance(value, str) else ''


def _option_prose(value):
    """Ignore presentation markup and repeated spaces, retaining word spaces."""
    if not isinstance(value, str):
        return ''
    value = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', value)
    value = re.sub(r'</?[A-Za-z][A-Za-z0-9]*(?:\s+[^<>]*)?/?>', '', value)
    value = re.sub(r'[*_`~]', '', unescape(value))
    return quality_text(value)


_PROSE_MATH = re.compile(
    r'\\[\[(A-Za-z]|\$|[∫∑√Α-Ωα-ω=^±×÷≤≥≠\u2070-\u209f]'
    r'|\b[A-Za-z]\s*[-+*/]\s*[A-Za-z0-9]|[0-9]\s*[+*/]\s*[0-9]')


def _uneven_option_detail(options):
    """Answer-blind policy: balance long Korean prose, not shorten a key.

    Only four prose options with at least 20 Hangul syllables each and 60%
    Hangul among visible non-space characters qualify. Formula/term options
    remain outside this deliberately conservative length heuristic.
    """
    if len(options) != 4:
        return False
    texts = [_option_prose(option.get('text')) for option in options]
    for option, text in zip(options, texts):
        # Check original superscripts before NFKC folds them into plain digits.
        if re.search(r'[\u2070-\u209f]', str(option.get('text', ''))) or _PROSE_MATH.search(text):
            return False
        hangul = len(re.findall(r'[가-힣]', text))
        visible = len(re.sub(r'\s', '', text))
        if hangul < 20 or hangul*5 < visible*3:
            return False
    longest, runner_up = sorted((len(text) for text in texts), reverse=True)[:2]
    return longest > runner_up and 4*longest >= 5*runner_up and longest-runner_up >= 18


_SUPERSCRIPT = dict(zip('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻', '0123456789+-'))
_SUBSCRIPT = dict(zip('₀₁₂₃₄₅₆₇₈₉₊₋', '0123456789+-'))
_MATH_TOKEN = re.compile(
    r'\s+|\\[A-Za-z]+|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)|'
    r'[A-Za-z][A-Za-z0-9]*|[Α-Ωα-ω∞]|[+\-*/^_(){}\[\],!|]')
_FUNCTIONS = {'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'arcsin', 'arccos',
              'arctan', 'sinh', 'cosh', 'tanh', 'exp', 'ln', 'log', 'sqrt', 'abs', 'min', 'max'}
_MATH_COMMANDS = _FUNCTIONS | {'frac', 'dfrac', 'tfrac', 'pi', 'infty', 'alpha', 'beta',
    'gamma', 'delta', 'epsilon', 'theta', 'lambda', 'mu', 'sigma', 'phi', 'omega'}
_LAYOUT = re.compile(r'\\(?:displaystyle|textstyle|left|right|bigl|bigr|Bigl|Bigr|big|Big|limits)(?![A-Za-z])|\\[,!;:]')


def _math_tokens(value, variable=None):
    """Lexical comparison only: no algebra, function evaluation or integration."""
    value = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+',
                   lambda m: '^{' + ''.join(_SUPERSCRIPT[c] for c in m[0]) + '}', value)
    value = re.sub(r'[₀₁₂₃₄₅₆₇₈₉₊₋]+',
                   lambda m: '_{' + ''.join(_SUBSCRIPT[c] for c in m[0]) + '}', value)
    tokens, position = [], 0
    while position < len(value):
        token = _MATH_TOKEN.match(value, position)
        if token is None:
            return None
        position = token.end()
        if not token[0].isspace():
            tokens.append(token[0])
    if not tokens:
        return None
    result, brackets = [], []
    for index, token in enumerate(tokens):
        following = tokens[index+1] if index+1 < len(tokens) else ''
        if token.startswith('\\'):
            if token[1:] not in _MATH_COMMANDS:
                return None
        elif re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', token):
            if token == variable:
                if following == '(':
                    return None  # x(x+1) can denote a product or a function x.
                token = '@bound'
            elif len(token) > 1 and token not in _FUNCTIONS and following != '(':
                return None  # Do not reinterpret "xy"/English words as products.
        if token in ('(', '{', '['):
            brackets.append(token)
        elif token in (')', '}', ']'):
            if not brackets or brackets.pop() != {')': '(', '}': '{', ']': '['}[token]:
                return None
        # x^2 and x^{2} differ only by harmless single-atom TeX grouping. Preserve
        # braces on compound exponents, and leave unbraced multi-digit ambiguity.
        if index and tokens[index-1] in ('^', '_') and token != '{':
            if len(token) != 1 and token != '@bound' and not token.startswith('\\'):
                return None
            result.extend(('{', token, '}'))
        else:
            result.append(token)
    return tuple(result) if not brackets else None


def _integral_limit(value, position):
    while position < len(value) and value[position].isspace():
        position += 1
    if position >= len(value):
        return None
    marker = value[position]
    if marker in _SUBSCRIPT or marker in _SUPERSCRIPT:
        table = _SUBSCRIPT if marker in _SUBSCRIPT else _SUPERSCRIPT
        end = position
        while end < len(value) and value[end] in table:
            end += 1
        return ('_' if table is _SUBSCRIPT else '^',
                ''.join(table[c] for c in value[position:end]), end)
    if marker not in '_^':
        return None
    position += 1
    while position < len(value) and value[position].isspace():
        position += 1
    if position >= len(value):
        return None
    if value[position] == '{':
        end, depth = position+1, 1
        while end < len(value) and depth:
            depth += (value[end] == '{') - (value[end] == '}')
            end += 1
        return (marker, value[position+1:end-1], end) if not depth else None
    atom = re.match(r'\\[A-Za-z]+|[A-Za-z0-9Α-Ωα-ω∞]', value[position:])
    return (marker, atom[0], position+len(atom[0])) if atom else None


def _integral_key(value):
    if not isinstance(value, str):
        return None
    value = _math_width(value).strip().replace('−', '-')
    for left, right in ((r'\(', r'\)'), (r'\[', r'\]'), ('$$', '$$'), ('$', '$')):
        if value.startswith(left) and value.endswith(right):
            value = value[len(left):-len(right)].strip()
            break
    value = _LAYOUT.sub(' ', value).strip()
    integral = re.match(r'\\int(?![A-Za-z])|∫', value)
    if integral is None:
        return None
    position, limits = integral.end(), {}
    for _ in range(2):
        part = _integral_limit(value, position)
        if part is None or part[0] in limits:
            return None
        marker, text, position = part
        limits[marker] = _math_tokens(text)
    if set(limits) != {'_', '^'} or any(v is None for v in limits.values()):
        return None
    # The complete option must be one definite integral. No Korean explanation,
    # prefactor, equality, second integral or trailing calculation is accepted.
    differential = re.fullmatch(r'(.+?)(?:\\mathrm\s*\{\s*d\s*\}|d)\s*([xytu])\s*',
                                value[position:].strip(), re.DOTALL)
    if differential is None:
        return None
    body, variable = differential.groups()
    if any(variable in bound for bound in limits.values()):
        return None  # Renaming a variable occurring in its own bounds is unsafe.
    integrand = _math_tokens(body, variable)
    return (limits['_'], limits['^'], integrand) if integrand is not None else None


def _equivalent_integral_pairs(options):
    seen, pairs = {}, []
    for option in options:
        key = _integral_key(option.get('text'))
        if key is None:
            continue
        if key in seen:
            pairs.append((seen[key], str(option.get('id', '?'))))
        else:
            seen[key] = str(option.get('id', '?'))
    return pairs


class _RationalPolynomial:
    """Bounded arithmetic in Q[x, pi]; unsupported syntax is never evaluated."""
    _OPEN = {'(': ')', '[': ']', '{': '}'}

    def __init__(self, tokens):
        if not tokens or len(tokens) > 256:
            raise ValueError('unsupported expression size')
        self.tokens, self.position, self.depth, self.remaining = tokens, 0, 0, 4096

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def checked(self, value):
        self.remaining -= max(1, len(value))
        if (self.remaining < 0 or len(value) > 64 or any(x > 32 or p > 4
                or c.numerator.bit_length() > 1024 or c.denominator.bit_length() > 1024
                for (x, p), c in value.items())):
            raise ValueError('unsupported arithmetic size')
        return {key: c for key, c in value.items() if c}

    def add(self, left, right, sign=1):
        result = dict(left)
        for key, coefficient in right.items():
            result[key] = result.get(key, Fraction(0)) + sign*coefficient
        return self.checked(result)

    def multiply(self, left, right):
        self.remaining -= len(left)*len(right)
        if self.remaining < 0:
            raise ValueError('unsupported arithmetic size')
        result = {}
        for (x, p), a in left.items():
            for (y, q), b in right.items():
                key = (x+y, p+q)
                result[key] = result.get(key, Fraction(0)) + a*b
        return self.checked(result)

    @staticmethod
    def scalar(value):
        if any(key != (0, 0) for key in value):
            raise ValueError('not a rational constant')
        return value.get((0, 0), Fraction(0))

    def divide(self, left, right):
        divisor = self.scalar(right)
        if not divisor:
            raise ValueError('zero denominator')
        return self.checked({key: value/divisor for key, value in left.items()})

    def parse(self):
        value = self.expression()
        if self.peek() is not None:
            raise ValueError('unsupported trailing tokens')
        return value

    def expression(self):
        value = self.product()
        while self.peek() in ('+', '-'):
            sign = 1 if self.peek() == '+' else -1
            self.position += 1
            value = self.add(value, self.product(), sign)
        return value

    def product(self):
        value = self.factor()
        while True:
            token = self.peek()
            if token in ('*', '/'):
                self.position += 1
                other = self.factor()
                value = self.multiply(value, other) if token == '*' else self.divide(value, other)
            elif token is not None and (token in self._OPEN or token in
                    ('@bound', r'\pi', 'π', r'\frac', r'\dfrac', r'\tfrac')
                    or re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)', token)):
                value = self.multiply(value, self.factor())
            else:
                return value

    def factor(self):
        self.depth += 1
        try:
            if self.depth > 20:
                raise ValueError('unsupported nesting')
            if self.peek() in ('+', '-'):
                sign = 1 if self.peek() == '+' else -1
                self.position += 1
                return self.checked({key: sign*c for key, c in self.factor().items()})
            value = self.atom()
            if self.peek() == '^':
                self.position += 1
                exponent = self.scalar(self.atom())
                if exponent.denominator != 1 or not 0 <= exponent <= 32:
                    raise ValueError('unsupported exponent')
                result, power = {(0, 0): Fraction(1)}, int(exponent)
                while power:
                    if power & 1:
                        result = self.multiply(result, value)
                    power //= 2
                    if power:
                        value = self.multiply(value, value)
                return result
            return value
        finally:
            self.depth -= 1

    def atom(self):
        token = self.peek()
        if token is None:
            raise ValueError('missing atom')
        self.position += 1
        if token in self._OPEN:
            result = self.expression()
            if self.peek() != self._OPEN[token]:
                raise ValueError('unmatched group')
            self.position += 1
            return result
        if token in (r'\frac', r'\dfrac', r'\tfrac'):
            if self.peek() != '{':
                raise ValueError('unsupported fraction')
            numerator = self.atom()
            if self.peek() != '{':
                raise ValueError('unsupported fraction')
            return self.divide(numerator, self.atom())
        if token == '@bound':
            return {(1, 0): Fraction(1)}
        if token in (r'\pi', 'π'):
            return {(0, 1): Fraction(1)}
        if len(token) <= 24 and re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)', token):
            return self.checked({(0, 0): Fraction(token)})
        raise ValueError('unsupported atom')


def _integral_value(value):
    """Exact numeric bounds and rational polynomial integrands with pi only.

    The finite tuple stores rational coefficients of pi powers; no floats,
    external algebra library, eval or user-defined function is involved.
    """
    if not isinstance(value, str) or len(value) > 4096:
        return None
    key = _integral_key(value)
    if key is None:
        return None
    try:
        lower, upper = (_RationalPolynomial.scalar(_RationalPolynomial(t).parse()) for t in key[:2])
        polynomial = _RationalPolynomial(key[2]).parse()
        result = {}
        for (degree, pi_power), coefficient in polynomial.items():
            moment = (upper**(degree+1)-lower**(degree+1))/Fraction(degree+1)
            result[pi_power] = result.get(pi_power, Fraction(0)) + coefficient*moment
        if any(c.numerator.bit_length() > 1024 or c.denominator.bit_length() > 1024 for c in result.values()):
            return None
        return tuple(sorted((power, coefficient) for power, coefficient in result.items() if coefficient))
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def _equal_value_integral_pairs(options):
    """Conservative option policy even when the stem asks for a physical model.

    Equal values trigger a review, without claiming that both models are valid.
    """
    seen, pairs = {}, []
    for option in options:
        value = _integral_value(option.get('text'))
        if value is None:
            continue
        if value in seen:
            pairs.append((seen[value], str(option.get('id', '?'))))
        else:
            seen[value] = str(option.get('id', '?'))
    return pairs


def local_issues(question: object) -> list[dict[str, str]]:
    """Return deterministic quality failures as ``{code, message}`` records.

    It does not mutate the candidate. Malformed container/schema data is handled
    by the caller's existing schema validator; this helper is safe on partial
    dictionaries and emits only text-quality findings.
    """
    if not isinstance(question, dict):
        return []
    issues = []
    for field, value in _fields(question):
        controls = _bad_controls(value)
        if controls:
            labels = ', '.join(f'U+{code:04X}' for code in controls)
            issues.append({'code': 'invalid_control_character',
                           'message': f'{field}에 표시할 수 없는 제어문자 또는 깨진 수식 이스케이프가 있어요 ({labels}).'})
    kind = question.get('type')
    if kind == 'word' and re.search(r'[∫∑=]|\\(?:int|frac|sum)(?![A-Za-z])|\$\$', str(question.get('answer') or '')):
        issues.append({'code': 'word_answer_is_formula',
                       'message': '서답형의 모범답안이 짧은 명칭이 아니라 수식이에요.'})
    if kind == 'word' and _term_is_visible(str(question.get('stem') or ''),
                                         str(question.get('answer') or '')):
        issues.append({'code': 'answer_in_stem',
                       'message': '서답형에서 답으로 요구한 명칭이 문제 지문에 그대로 제시되어 있어요.'})
    if kind == 'mcq':
        raw_options = question.get('options')
        options = [o for o in raw_options if isinstance(o, dict)] if isinstance(raw_options, list) else []
        normalized = [_option_key(o.get('text')) for o in options]
        if len([v for v in normalized if v]) != len(set(v for v in normalized if v)):
            issues.append({'code': 'duplicate_option_text',
                           'message': '문자 너비와 공백을 정리하면 내용이 같은 선택지가 있어요.'})
        if _uneven_option_detail(options):
            issues.append({'code': 'uneven_option_detail',
                           'message': '한 선택지의 설명이 다른 보기보다 유독 길어요. 보기의 정보량과 문장 길이를 맞춰 재검토해야 해요.'})
        equivalent = _equivalent_integral_pairs(options)
        if equivalent:
            pairs = ', '.join(f'{left}·{right}' for left, right in equivalent)
            issues.append({'code': 'equivalent_integral_options',
                           'message': f'적분 변수 이름을 제외하면 같은 정적분인 선택지가 있어요 ({pairs}).'})
        equal_value = _equal_value_integral_pairs(options)
        if equal_value:
            pairs = ', '.join(f'{left}·{right}' for left, right in equal_value)
            issues.append({'code': 'equal_value_integral_options',
                           'message': f'값이 같아 복수정답으로 해석할 여지가 있는 정적분 선택지가 있어 선지를 재검토해야 해요 ({pairs}).'})
        # An item can legitimately ask the learner to diagnose a quoted flawed
        # item. Do not confuse an explicit diagnosis with this item's defect.
        if (not _REVIEWING_AN_ITEM.search(quality_text(question.get('stem')))
                and _admits_invalid_question(quality_text(question.get('explanation')))):
            issues.append({'code': 'explanation_admits_invalid_question',
                           'message': '문제 해설이 이 문항의 복수정답 또는 정답 부재를 명시하고 있어요.'})
        if any(o.get('id') != question.get('answer')
               and _WRONG_OPTION_ADMISSION.search(quality_text(o.get('explanation')))
               for o in options):
            issues.append({'code': 'distractor_marked_correct',
                           'message': '정답으로 지정하지 않은 선택지의 해설이 해당 선지를 정답이라고 명시하고 있어요.'})
    return issues
