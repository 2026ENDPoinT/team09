"""Render shared numeric bindings once. No model calls or question filtering.

This is an arithmetic interpreter, not a subject-matter validator. A wrong
equation remains a wrong equation. Never execute code supplied by the model.
"""
from __future__ import annotations

import ast
import copy
from decimal import Decimal, localcontext
from fractions import Fraction
from math import isqrt
import re

NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}\Z')
SLOT = re.compile(r'\{\{([^{}]*)\}\}')


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(value.numerator) / Decimal(value.denominator)


def _bounded(value):
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(value) > Decimal('1e100'):
            raise ValueError('계산값의 범위를 넘었어요.')
    elif max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > 2048:
        raise ValueError('계산값의 범위를 넘었어요.')
    return value


def evaluate(expression, values):
    if not isinstance(expression, str) or not 0 < len(expression) <= 512:
        raise ValueError('계산식 길이를 확인해 주세요.')
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 128:
        raise ValueError('계산식이 너무 복잡해요.')

    def visit(node, depth=0):
        if depth > 24:
            raise ValueError('계산식이 너무 깊어요.')
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            # Read the literal, not its binary floating point representation.
            literal = Decimal(ast.get_source_segment(expression, node).replace('_', ''))
            # Fraction expands decimal exponents into integers. Bound the
            # exponent before that expansion, including literals parsed as inf.
            if not literal.is_finite() or abs(literal.as_tuple().exponent) > 2048:
                raise ValueError('계산값의 범위를 넘었어요.')
            return _bounded(Fraction(literal))
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow):
                if b != int(b) or abs(b) > 16:
                    raise ValueError('지수는 -16~16의 정수만 지원해요.')
                return _bounded(a ** int(b))
            if isinstance(a, Decimal) or isinstance(b, Decimal):
                a, b = _decimal(a), _decimal(b)
            if isinstance(node.op, ast.Add): result = a + b
            elif isinstance(node.op, ast.Sub): result = a - b
            elif isinstance(node.op, ast.Mult): result = a * b
            elif isinstance(node.op, ast.Div): result = a / b
            else: raise ValueError('지원하지 않는 계산 연산이에요.')
            return _bounded(result)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ('sqrt', 'abs') and len(node.args) == 1 and not node.keywords):
            value = visit(node.args[0], depth + 1)
            if node.func.id == 'abs': return abs(value)
            if value < 0: raise ValueError('음수의 실수 제곱근은 없어요.')
            if isinstance(value, Fraction):
                n, d = isqrt(value.numerator), isqrt(value.denominator)
                if n*n == value.numerator and d*d == value.denominator:
                    return Fraction(n, d)
            return _bounded(_decimal(value).sqrt())
        raise ValueError('알 수 없는 이름이나 지원하지 않는 계산식이에요.')

    with localcontext() as ctx:
        ctx.prec = 32
        return visit(tree.body)


def display(value):
    if isinstance(value, Decimal):
        return '≈' + format(value, '.10g')
    if value.denominator == 1: return str(value.numerator)
    denominator = value.denominator
    factors = []
    for factor in (2, 5):
        count = 0
        while denominator % factor == 0:
            denominator //= factor
            count += 1
        factors.append(count)
    if denominator != 1:
        return f'{value.numerator}/{value.denominator}'
    # A 2048-bit denominator can need over 1400 significant decimal digits.
    # Construct the finite decimal with integers so it is never silently rounded.
    twos, fives = factors
    places = max(twos, fives)
    scaled = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    digits = str(scaled).rjust(places + 1, '0')
    sign = '-' if value < 0 else ''
    return sign + (digits[:-places] + '.' + digits[-places:]).rstrip('0').rstrip('.')


def render_calculations(raw):
    result = copy.deepcopy(raw)
    if not isinstance(result, dict) or not isinstance(result.get('questions'), list): return result
    for q in result['questions']:
        if not isinstance(q, dict): continue
        original = copy.deepcopy(q)
        has_bindings = 'calculations' in q
        entries, values, failures = q.get('calculations', []), {}, []
        inline_seen = False
        if not isinstance(entries, list) or len(entries) > 64:
            failures.append('계산 항목 형식을 확인하지 못했어요.')
            entries = []
        for entry in entries:
            try:
                if (not isinstance(entry, dict) or set(entry) != {'name', 'expression'}
                        or not isinstance(entry['name'], str) or not NAME.fullmatch(entry['name'])
                        or entry['name'] in values):
                    raise ValueError('계산 이름·항목 형식이 올바르지 않아요.')
                values[entry['name']] = evaluate(entry['expression'], values)
            except (ValueError, SyntaxError, ArithmeticError, RecursionError, OverflowError) as error:
                failures.append(str(error))
        rendered = {name: display(value) for name, value in values.items()}

        def replace(text):
            if not isinstance(text, str): return text
            def slot(match):
                nonlocal inline_seen
                name = match.group(1).strip()
                if name.startswith('='):
                    inline_seen = True
                    expression = name[1:].strip()
                    try:
                        return display(evaluate(expression, values))
                    except (ValueError, SyntaxError, ArithmeticError, RecursionError, OverflowError):
                        failures.append('계산식 ' + expression + '을 표시하지 못했어요.')
                        return match.group(0)
                # Ordinary LaTeX doubled braces are not an arithmetic request.
                # Named bindings remain readable in the established contract.
                if not has_bindings:
                    return match.group(0)
                if name in rendered: return rendered[name]
                # Preserve the historical expression fallback for old callers
                # that already supplied a calculations array.
                try:
                    return display(evaluate(name, values))
                except (ValueError, SyntaxError, ArithmeticError, RecursionError, OverflowError):
                    pass
                failures.append('계산값 ' + name + '을 표시하지 못했어요.')
                return match.group(0)
            return SLOT.sub(slot, text)

        for key in ('passage', 'stem', 'answer', 'explanation'):
            if key in q: q[key] = replace(q[key])
        for key in ('options', 'distractors'):
            for option in q.get(key, []) if isinstance(q.get(key), list) else []:
                if isinstance(option, dict):
                    for field in ('text', 'explanation'):
                        if field in option: option[field] = replace(option[field])
        if isinstance(q.get('keyPoints'), list): q['keyPoints'] = [replace(p) for p in q['keyPoints']]
        if has_bindings or inline_seen:
            q['calculationValues'] = rendered
        if failures:
            q['rawQuestion'] = original
            prior = [w for w in q.get('warnings', []) if isinstance(w, str)] if isinstance(q.get('warnings'), list) else []
            q['warnings'] = list(dict.fromkeys(prior + ['계산식 표시 안내: ' + f for f in failures]))
    return result
