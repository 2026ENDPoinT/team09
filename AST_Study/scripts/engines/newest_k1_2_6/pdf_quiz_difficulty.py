"""Compile only the selected quiz difficulty; no grading or response mutation."""

POLICIES = {
    '중': '구체적 사례에서 핵심 조건을 적용하거나 흔한 오개념을 구분하게 한다. 필요한 원리가 무엇인지 알 수 있는 단서를 준다.',
    '중상': '비슷한 조건이나 설명 중 사례에 맞는 것을 선택한 뒤 결론을 구하게 한다. 비교해야 할 차이와 결론을 지문에서 설명하지 않는다.',
    '상': '사례의 관측·조건에서 적용할 관계를 선택하고, 주어지지 않은 중간 결론을 구해 최종 판단에 사용하게 한다. 관계의 이름·풀이 순서·중간 결론은 알려주지 않는다. 독립된 질문 두 개나 공식 직접 대입으로 끝내지 않는다.',
    '최상': '여러 관측·제약을 함께 사용해 가능한 조건이나 설명을 좁힌 뒤 변경·경계 상황의 결론을 판단하게 한다. 어떤 가능성을 왜 배제할지 학습자가 결정해야 한다. 후보 제거 이유나 적용 방법을 미리 알려주지 않는다.',
}

RECALL_POLICIES = {
    '중': '정의·설명에 충분한 단서를 주고 핵심 용어·구성 요소·기본 순서를 정확히 떠올리게 한다.',
    '중상': '유사한 용어나 구성 사이에서 구별되는 단서를 주고 정확한 명칭·특징·순서를 회상하게 한다.',
    '상': '대상을 특정할 수 있는 단서만 주고 혼동하기 쉬운 조건·예외·단계의 대응 관계를 정확히 복원하게 한다. 원자료의 핵심 구분을 기억해야 답할 수 있게 한다.',
    '최상': '서로 비슷한 조건·예외·순서의 핵심 차이를 함께 기억해 빠진 연결이나 바뀐 순서를 복원하게 한다. 단서는 적어도 대상을 특정할 수 있어야 하며 새로운 상황의 풀이를 요구하지 않는다.',
}


def difficulty_instruction(difficulty, allowed_types=(), theme=None):
    """Return one difficulty block, plus a short-answer clause only when needed."""
    if difficulty not in POLICIES:
        raise ValueError('지원하지 않는 문제 난이도이다.')
    policies = RECALL_POLICIES if theme == 'recall' else POLICIES
    text = f'선택 난이도: {difficulty}\n{policies[difficulty]}'
    if theme != 'recall' and difficulty in ('상', '최상') and 'word' in allowed_types:
        text += ('\nword는 관측된 결과에서 숨은 조건·상태를 알아내고, 그 조건을 바꾼 상황의 결과 하나를 묻는다. '
                 '필요한 관계와 중간 판단은 알려주지 않는다. 답은 최종 수치·표현식·수정한 한 문장·짧은 결론이다. '
                 '명칭 회상·표기 치환·독립된 물음의 나열로 대신하지 않는다.')
    return text
