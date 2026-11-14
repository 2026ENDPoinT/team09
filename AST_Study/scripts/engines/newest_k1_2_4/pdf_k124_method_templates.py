"""Source-selected general forms for worked mathematical methods."""

METHOD_TEMPLATE = 'methodTemplate'
NO_TEMPLATE = 'freeform'

# The reader selects a method from the owned source. These cards use parameters
# for the exercise's inputs and preserve the corresponding theorem conditions.
TEMPLATES = {
    'exponential_rational_substitution': (
        '지수 치환과 부분분수 분해',
        '적분함수가 지수식의 유리함수로 주어지면 지수식을 새 변수로 두고, 미분량과 양쪽 경계를 함께 바꿔요.',
        r'피적분함수가 연속인 구간의 하한을 \(a\), 유한한 상한을 \(T\)로 두어요. 상한이 무한대인 이상적분은 치환한 적분에서 \(T\to\infty\)의 극한을 취해요.',
        r'$$u=e^x,\qquad dx=\frac{du}{u},\qquad \int_a^T R(e^x)\,dx=\int_{e^a}^{e^T}\frac{R(u)}{u}\,du$$',
        r'치환 뒤 분모가 \(u(u^2+\lambda)\)이고 \(\lambda>0\)이면, 일차 인수에는 상수 분자를, 더 분해되지 않는 이차 인수에는 일차 이하 분자를 놓아요. 분자의 차수가 분모 이상이면 먼저 다항식 나눗셈을 해요. 양변에 공통분모를 곱해 계수를 비교하면 분해 계수를 정할 수 있어요.',
        r'$$\frac{P(u)}{u(u^2+\lambda)}=\frac{A}{u}+\frac{Bu+C}{u^2+\lambda},\qquad \deg P<3$$',
    ),
    'integral_remainder_log_power': (
        '적분으로 급수의 나머지 오차 제한하기',
        r'연속이고 양수이며 감소하는 함수 \(f\)의 정수값으로 이루어진 수렴급수에서는, 마지막으로 더한 항 이후의 합을 꼬리 적분으로 제한할 수 있어요.',
        r'첫 항의 인덱스를 \(m\), 더한 항의 개수를 \(N\)이라 하면 마지막으로 포함한 인덱스는 \(L=m+N-1\)이에요. 적분으로 구한 위쪽 상한이 허용 오차 \(\varepsilon\)보다 작아지도록 \(L\)을 골라요.',
        r'$$R_L=\sum_{k=L+1}^{\infty}f(k)\le\int_L^{\infty}f(x)\,dx<\varepsilon$$',
        r'항을 나타내는 함수가 \(1/[x(\ln x)^p]\) 꼴이면 \(u=\ln x\)로 치환해 \(dx/x\)를 \(du\)로 바꾸어요. \(p>1\)이면 다음 일반식으로 상한을 구할 수 있어요.',
        r'$$\int_L^{\infty}\frac{dx}{x(\ln x)^p}=\int_{\ln L}^{\infty}u^{-p}\,du=\frac{1}{(p-1)(\ln L)^{p-1}},\qquad L>1,\ p>1$$',
    ),
    'alternating_magnitude_comparison': (
        '교대급수와 절대수렴 판정',
        r'교대급수의 양의 항 크기 \(b_n\)가 충분히 큰 \(n\)부터 감소하고 \(0\)으로 수렴하면 교대급수는 수렴해요.',
        r'\(b_n\)를 미분 가능한 함수의 정수값으로 표현할 수 있다면 도함수의 부호로 감소를 확인하고, 극한으로 항의 크기가 \(0\)에 가까워지는지 확인해요.',
        r'그다음 절댓값 급수 \(\sum b_n\)의 수렴 여부를 따로 검사해요. 예를 들어 충분히 큰 \(n\)에서 \(b_n\ge c/n\)인 양의 상수 \(c\)가 있으면 조화급수와의 비교로 절댓값 급수가 발산해요. 교대급수는 수렴하고 절댓값 급수는 발산할 때 조건부수렴이라고 해요.',
    ),
    'simpson_zero_error': (
        '복합 심프슨 공식과 오차 상한',
        r'복합 심프슨 공식은 적분 구간을 짝수 개의 같은 길이 구간으로 나누고, 각 두 구간에서 포물선으로 함수를 근사해요.',
        r'\(N\)을 짝수, \(h=(b-a)/N\), \(x_j=a+jh\)로 두면 양 끝점의 가중치는 1, 홀수 인덱스의 가중치는 4, 내부 짝수 인덱스의 가중치는 2예요.',
        r'$$S_N=\frac{h}{3}\left[f(x_0)+4\sum_{j=1}^{N/2} f(x_{2j-1})+2\sum_{j=1}^{N/2-1} f(x_{2j})+f(x_N)\right]$$',
        r'3차 이하 다항식은 4계 도함수가 0이라 오차 상한도 0이에요. 적분의 참값을 \(I\)라 하면 \(|I-S_N|\le 0\)에서 \(S_N=I\)가 성립해요.',
    ),
    'polynomial_exponential_parts': (
        '지수 감쇠 이상적분과 반복 부분적분',
        r'다항식과 감쇠 지수함수의 곱은 부분적분을 할 때마다 다항식의 차수가 낮아져요. 무한 상한은 먼저 유한한 상한으로 두고 마지막에 극한을 취해요.',
        r'$$\int_a^T P(x)e^{-\lambda x}\,dx=\left[-\frac{P(x)e^{-\lambda x}}{\lambda}\right]_a^T+\frac{1}{\lambda}\int_a^T P^{\prime}(x)e^{-\lambda x}\,dx,\qquad \lambda>0$$',
        r'부분적분을 반복한 뒤 \(T\to\infty\)로 보내요. \(\lambda>0\)일 때 다항식과 \(e^{-\lambda T}\)의 곱은 0으로 수렴하므로, 무한 상한의 경계항은 사라져요.',
    ),
    'hydrostatic_triangle_apex_up': (
        '위로 꼭짓점이 향한 삼각형 끝면의 정수압',
        r'삼각형 끝면을 수평 띠로 나누고, 각 띠의 수심에서 받는 압력과 띠의 면적을 곱해 적분해요.',
        r'수면에서 위 꼭짓점까지의 깊이를 \(d\ge 0\), 삼각형의 높이를 \(h\), 아래 밑변의 폭을 \(s\)로 두어요. 위 꼭짓점에서 아래로 잰 거리 \(y\)는 \(0\le y\le h\)이고 띠의 수심은 \(d+y\)예요.',
        r'닮은 삼각형을 쓰면 띠의 폭은 \(w(y)=sy/h\)예요. 꼭짓점에서 폭은 0이고, 아래 밑변에서 폭은 \(s\)예요. 한쪽 수직 끝면에 작용하는 힘은 물의 밀도 \(\rho\)와 중력가속도 \(g\)를 사용해 다음과 같이 구해요.',
        r'$$F=\int_0^h \rho g(d+y)\frac{s}{h}y\,dy$$',
    ),
}

TEMPLATE_RULES = '''
Choose methodTemplate by the actual mathematical construction in the owned
source. Use the listed template when it represents the main demonstrated method:
- exponential_rational_substitution: u=exp(x) changes both bounds and the
  differential, then partial fractions have denominator u(u^2+lambda),
  lambda>0, up to a constant factor. Other factorizations use freeform.
- integral_remainder_log_power: the integral-test remainder for the kernel
  1/[x(log x)^p], p>1, with logarithm substitution and the last-index convention.
- alternating_magnitude_comparison: the alternating-series test via eventual
  decrease and zero limit, with a separate lower bound c/n for absolute values.
- simpson_zero_error: composite Simpson weights and a demonstrated zero error
  bound. The zero bound proves exactness and is a teaching point to retain.
- polynomial_exponential_parts: finite-endpoint integration by parts for a
  polynomial times a decaying exponential, followed by the endpoint limit.
- hydrostatic_triangle_apex_up: submerged vertical triangular end, horizontal
  base below the upper vertex. Source shows depth and width both increase down
  from that vertex. A triangle with its vertex below the base uses freeform.
The template supplies the generic steps and formulas. Give a short principle
with the actual source IDs, and leave segments empty for a matched template.
Do not repeat the worked solution in concepts, tables, or an easy explanation.
When the same source also teaches a separate rule, give it its own entry with
the appropriate template or freeform. Keep distinct quadrature methods and
the reason for any exactness or error bound, without evaluating the example.
'''


def render_method_template(method):
    template = TEMPLATES.get(method.pop(METHOD_TEMPLATE, None))
    if template is None:
        return method
    title, definition, *paragraphs = template
    ids = method['principle']['blockIds']
    if not ids:
        return method
    return {**method, 'title': title,
            'principle': {'text': definition, 'blockIds': ids},
            'segments': [{'kind': 'explanation', 'text': text, 'blockIds': ids}
                         for text in paragraphs]}
