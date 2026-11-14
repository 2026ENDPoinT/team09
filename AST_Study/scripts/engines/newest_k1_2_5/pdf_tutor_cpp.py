"""Bounded arithmetic/iostream traces, never a compiler or an arbitrary code runner.

Accept a complete, straight-line int/double main only. Unsupported syntax, undefined
operations and extra requested tasks fall through to the normal mentor. No partial
trace is presented as the result of a program we did not understand.
"""
import ast
from dataclasses import dataclass
import math
import re


class Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class Value:
    number: object
    kind: str


def checked(number, kind):
    if kind == 'int' and not -2147483648 <= number <= 2147483647:
        raise Unsupported('integer overflow or unsupported literal type')
    if kind == 'double' and not math.isfinite(number):
        raise Unsupported('non-finite arithmetic')
    return Value(number, kind)


TOKEN = re.compile(r'\s*(static_cast\s*<\s*(?:int|double)\s*>|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|[A-Za-z_]\w*|[()+*/%\-])')


def evaluate(text, variables):
    tokens, pos = [], 0
    while pos < len(text.rstrip()):
        match = TOKEN.match(text, pos)
        if not match:
            raise Unsupported('expression syntax')
        tokens.append(match.group(1));pos = match.end()
    if len(tokens) > 128 or tokens.count('(') > 24:
        raise Unsupported('expression size')
    index, work = 0, []

    def expression(level=0):
        nonlocal index
        if index >= len(tokens):
            raise Unsupported('expression nesting')
        token = tokens[index];index += 1
        if token in ('+', '-'):
            value = expression(30)
            value = checked(value.number if token == '+' else -value.number, value.kind)
        elif token.startswith('static_cast'):
            kind = 'double' if 'double' in token else 'int'
            if index >= len(tokens) or tokens[index] != '(':
                raise Unsupported('cast syntax')
            index += 1;before = expression()
            if index >= len(tokens) or tokens[index] != ')':
                raise Unsupported('cast syntax')
            index += 1
            value = checked(float(before.number) if kind == 'double' else int(before.number), kind)
            work.append(f'형 변환: {before.number} → {value.number} ({kind})')
        elif token == '(':
            value = expression()
            if index >= len(tokens) or tokens[index] != ')':
                raise Unsupported('parentheses')
            index += 1
        elif token in variables:
            value = variables[token]
        elif re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', token):
            kind = 'double' if any(c in token for c in '.eE') else 'int'
            if kind == 'int' and len(token) > 1 and token.startswith('0'):
                raise Unsupported('octal literal')
            value = checked(float(token) if kind == 'double' else int(token), kind)
        else:
            raise Unsupported('unknown name')
        while index < len(tokens):
            op = tokens[index];precedence = {'+': 10, '-': 10, '*': 20, '/': 20, '%': 20}.get(op, -1)
            if precedence < level:
                break
            index += 1;right = expression(precedence + 1)
            kind = 'double' if 'double' in (value.kind, right.kind) else 'int'
            left = value.number;rhs = right.number
            if op in ('/', '%') and rhs == 0:
                raise Unsupported('division by zero')
            if op == '%':
                if kind != 'int':raise Unsupported('floating remainder')
                result = left - math.trunc(left / rhs) * rhs
            elif op == '/':result = left / rhs if kind == 'double' else math.trunc(left / rhs)
            elif op == '+':result = left + rhs
            elif op == '-':result = left - rhs
            else:result = left * rhs
            value = checked(result, kind)
            work.append(f'{left} {op} {rhs} = {value.number} ({kind})')
        return value

    value = expression()
    if index != len(tokens):raise Unsupported('unconsumed expression')
    return value, work


def split_outside(text, separator):
    # Only split outside C++ strings; parentheses are needed for declarations.
    result, start, depth, quoted, escaped, i = [], 0, 0, False, False, 0
    while i < len(text):
        char = text[i]
        if quoted:
            if escaped:escaped = False
            elif char == '\\':escaped = True
            elif char == '"':quoted = False
        elif char == '"':quoted = True
        elif char == '(':depth += 1
        elif char == ')':depth -= 1
        elif depth == 0 and text.startswith(separator, i):
            result.append(text[start:i].strip());i += len(separator);start = i;continue
        if depth < 0:raise Unsupported('parentheses')
        i += 1
    if quoted or depth:raise Unsupported('unclosed expression')
    result.append(text[start:].strip());return result


def trace_program(code):
    if len(code) > 5000 or re.search(r'//|/\*|\*/', code):
        raise Unsupported('comments or size')
    code = re.sub(r'^\s*#include\s*<(?:iostream|iomanip)>\s*$', '', code, flags=re.M)
    match = re.fullmatch(r'\s*int\s+main\s*\(\s*\)\s*\{([^{}]*)\}\s*', code)
    if not match:raise Unsupported('not a supported complete main')
    statements = split_outside(match[1], ';')
    if statements[-1]:raise Unsupported('missing semicolon')
    variables, outputs, events = {}, [], []
    precision, notation, showpoint, returned = 6, 'g', False, False
    for statement in statements[:-1]:
        if not statement:continue
        if returned:raise Unsupported('statements after return')
        if re.fullmatch(r'return\s+0', statement):returned = True;continue
        declaration = re.fullmatch(r'(int|double)\s+(.+)', statement, re.S)
        if declaration:
            for item in split_outside(declaration[2], ','):
                assignment = re.fullmatch(r'([A-Za-z_]\w*)\s*=\s*(.+)', item, re.S)
                if not assignment or assignment[1] in variables:raise Unsupported('declaration')
                keywords = set(('alignas alignof and and_eq asm auto bitand bitor bool break case '
                    'catch char char8_t char16_t char32_t class compl concept const consteval constexpr '
                    'constinit const_cast continue co_await co_return co_yield decltype default delete '
                    'do double dynamic_cast else enum explicit export extern false float for friend '
                    'goto if inline int long mutable namespace new noexcept not not_eq nullptr operator '
                    'or or_eq private protected public register reinterpret_cast requires return short '
                    'signed sizeof static static_assert static_cast struct switch template this '
                    'thread_local throw true try typedef typeid typename union unsigned using '
                    'virtual void volatile wchar_t while xor xor_eq std').split())
                if assignment[1] in keywords or assignment[1].startswith('__'):
                    raise Unsupported('reserved or special name')
                val, _ = evaluate(assignment[2], variables);kind = declaration[1]
                variables[assignment[1]] = checked(float(val.number) if kind == 'double' else int(val.number), kind)
            continue
        if not statement.startswith('std::cout'):raise Unsupported('statement')
        pieces = split_outside(statement, '<<')
        if pieces.pop(0) != 'std::cout':raise Unsupported('output expression')
        for piece in pieces:
            if piece in ('std::fixed', 'std::scientific', 'std::defaultfloat'):
                notation = {'std::fixed': 'f', 'std::scientific': 'e', 'std::defaultfloat': 'g'}[piece];continue
            if piece in ('std::showpoint', 'std::noshowpoint'):
                showpoint = piece == 'std::showpoint';continue
            digits = re.fullmatch(r'std::setprecision\(\s*(\d+)\s*\)', piece)
            if digits:
                precision = int(digits[1])
                if precision > 12:raise Unsupported('precision')
                continue
            if piece == 'std::endl':outputs.append('\n');continue
            if piece.startswith('"'):
                if not re.fullmatch(r'"(?:[^"\\\n]|\\[ntr\\"])*"', piece):raise Unsupported('string escape')
                text = ast.literal_eval(piece);outputs.append(text);continue
            val, work = evaluate(piece, variables)
            fmt = ('#' if showpoint else '') + '.' + str(precision) + notation
            text = str(val.number) if val.kind == 'int' else format(val.number, fmt)
            outputs.append(text)
            events.append({'expression': piece, 'value': str(val.number), 'type': val.kind,
                           'printed': text, 'working': work, 'format': fmt})
    if not outputs or len(events) > 24:raise Unsupported('empty or large output')
    return {'stdout': ''.join(outputs), 'events': events}


def _simple_output_request(text):
    """Use the shortcut only for a complete, understood output request."""
    if len(text) > 240:return False
    compact = re.sub(r'\s+', '', text).rstrip('.!?。？！')
    detail = r'(?:간단히|간단하게|자세히|자세하게|상세히|상세하게|쉽게)?'
    ending = r'(?:줘(?:요)?|주세요|줄래(?:요)?)?'
    korean = (detail + r'(?:(?:이|아래|다음|위|해당))?'
              r'(?:(?:C\+\+)?(?:코드|프로그램|소스코드|소스)(?:의|에서)?)?'
              r'(?:출력(?:결과)?|실행결과)(?:를|을|이|은|는|가)?' + detail +
              r'(?:(?:설명|예측|계산|구)?해' + ending + r'|알려' + ending +
              r'|뭐(?:야|예요|인가요)|무엇(?:이야|인가요)|어떻게(?:돼|나와)(?:요)?)?')
    if re.fullmatch(korean, compact, re.I):return True
    normalized = re.sub(r'\s+', ' ', text).strip().rstrip('.!?')
    target = (r'(?:the\s+)?output(?:\s+(?:of|for|from)\s+'
              r'(?:(?:the|this|following|below)\s+)?(?:c\+\+\s+)?(?:code|program))?')
    english = (r'(?:please\s+)?(?:(?:briefly|simply)\s+)?'
               r'(?:(?:explain|describe|show|predict|tell\s+me)\s+)?' + target +
               r'(?:\s+(?:briefly|simply|in\s+detail))?|what(?:\s+is|\x27s)\s+' + target)
    return bool(re.fullmatch(english, normalized, re.I))


def local_code_answer(question, mode):
    if not re.search(r'출력|실행.*결과|output', question, re.I):return None
    # Avoid answering only one part of a combined request or changing an existing
    # user's program. These requests continue through the ordinary mentor.
    if re.search(r'고쳐|수정|바꿔|변경|오류.*찾|추가로|비교해|rewrite|modify', question, re.I):return None
    fenced = re.findall(r'```(?:cpp|c\+\+)?\s*\n([\s\S]*?)```', question)
    if fenced:
        if len(fenced) != 1:return None
        code = fenced[0]
        rest = re.sub(r'```[\s\S]*?```', '', question)
    else:
        start = question.find('#include')
        if start < 0:return None
        code, rest = question[start:], question[:start]
    # Unknown wording and extra presentation intent belong to the ordinary mentor.
    if not _simple_output_request(rest):return None
    try:trace = trace_program(code)
    except (Unsupported, ValueError, OverflowError, ZeroDivisionError):return None
    stdout = trace['stdout']
    fence = '`' * max(3, 1 + max((len(s)for s in re.findall(r'`+', code+'\n'+stdout)), default=0))
    if trace['events']:
        answer = '계산한 값을 화면에 표시하는 코드예요. 계산값의 자료형과 화면에 보이는 표기를 나눠서 보면 이해하기 쉬워요.\n\n'
    else:
        answer = '문자열과 줄바꿈을 적힌 순서대로 화면에 표시하는 코드예요.\n\n'
    answer += '출력은 다음과 같아요.\n\n' + fence + 'text\n' + stdout + ('' if stdout.endswith('\n') else '\n') + fence + '\n'
    # Reuse supported source statements, including each output's input declarations.
    # Keep comma declarations intact and follow their dependencies without evaluating
    # again. The already-traced source is bounded to 5000 characters.
    body = re.search(r'\{([^{}]*)\}', code)[1]
    pending, event_index, definitions, declarations = {}, 0, {}, {}
    format_state, formatting_sources = {}, {}
    excerpt_context_shown = False
    for index, statement in enumerate(split_outside(body, ';')[:-1]):
        declaration = re.fullmatch(r'(int|double)\s+(.+)', statement, re.S)
        if declaration:
            names, dependencies = [], set()
            for item in split_outside(declaration[2], ','):
                assignment = re.fullmatch(r'([A-Za-z_]\w*)\s*=\s*(.+)', item, re.S)
                names.append(assignment[1])
                dependencies.update(definitions[token] for token in TOKEN.findall(assignment[2])
                                    if token in definitions)
            declarations[index] = (statement + ';', dependencies)
            definitions.update((name, index) for name in names)
            continue
        if not statement.startswith('std::cout'):continue
        pieces = split_outside(statement, '<<')[1:]
        events, inherited_formats, formatting_only = [], {}, True
        for piece in pieces:
            format_key = None
            if piece in ('std::fixed', 'std::scientific', 'std::defaultfloat'):format_key = 'notation'
            elif piece in ('std::showpoint', 'std::noshowpoint'):format_key = 'showpoint'
            elif re.fullmatch(r'std::setprecision\(\s*\d+\s*\)', piece):format_key = 'precision'
            if format_key:
                format_state[format_key] = (index, piece)
            else:
                formatting_only = False
            if event_index < len(trace['events']) and piece == trace['events'][event_index]['expression']:
                event = trace['events'][event_index]
                events.append(event);event_index += 1
                if event['type'] == 'double':
                    for origin, setting in format_state.values():
                        if origin != index and origin not in pending:
                            inherited_formats[(origin, setting)] = None
        formatting_sources[index] = statement + ';' if formatting_only else None
        pending[index] = statement + ';'
        if not events and not any(piece == 'std::endl' or piece.startswith('"') for piece in pieces):continue
        needed = [definitions[token] for event in events for token in TOKEN.findall(event['expression'])
                  if token in definitions]
        excerpt = dict(pending)
        while needed:
            declaration_index = needed.pop()
            if declaration_index in excerpt:continue
            original, dependencies = declarations[declaration_index]
            excerpt[declaration_index] = original
            needed.extend(dependencies)
        if inherited_formats and all(formatting_sources[origin] is not None for origin, _ in inherited_formats):
            for origin, _ in inherited_formats:
                excerpt[origin] = formatting_sources[origin]
        elif inherited_formats:
            settings = ', '.join('`' + setting + '`' for _, setting in sorted(inherited_formats))
            answer += '\n앞에서 적용한 출력 형식(' + settings + ')은 새 설정이 나올 때까지 유지돼요.\n'
        if not excerpt_context_shown:
            answer += '\n아래 코드는 `main` 내부에서 각 출력에 필요한 부분만 발췌한 거예요.\n'
            excerpt_context_shown = True
        answer += '\n' + fence + 'cpp\n' + '\n'.join(excerpt[key] for key in sorted(excerpt)) + '\n' + fence + '\n'
        pending = {}
        if not events:
            answer += '\n이 부분은 문자열과 줄바꿈을 그대로 이어서 출력해요.\n'
        for number, event in enumerate(events, 1):
            answer += '\n- ' + (f'{number}번째 식: ' if len(events) > 1 else '')
            if mode == 'deep' and event['working']:
                answer += ' → '.join('`' + x + '`' for x in event['working']) + '. '
            answer += f"계산값은 `{event['value']}`인 `{event['type']}`형이고, 출력 형식을 적용한 표기는 `{event['printed']}`예요.\n"
    return {'answer': answer.strip(), 'computedCode': trace,
            'method': 'local_cpp_arithmetic_trace', 'executed': False}
