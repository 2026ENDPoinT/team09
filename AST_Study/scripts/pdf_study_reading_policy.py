"""Reading improvements are fixed for a worker's lifetime, activated on app restart."""
import os
import re
from collections import Counter

VERSION = 'coherent-chart-code-teaching-v1'
# Desktop workers always receive APP_ROOT. Only the newly built Java process
# opts in; an already running desktop process keeps its previous policy.
ENABLED = os.environ.get('SYNESIS_STUDY_READING_POLICY') == VERSION or (
    'SYNESIS_APP_ROOT' not in os.environ and 'SYNESIS_STUDY_READING_POLICY' not in os.environ)

EXERCISE_RULES = '''
EXERCISE CONTENT: Missing answers do not mean missing teaching. Preserve a first
demonstration of an operator, type, mechanism or comparison inside a problem.
Explain the supported code/relationship and its conditions; do not invent a
source-provided solution. Omit only routine repetition of already taught content.
For sizeof distinguish pointer, pointed-to object and address-of-pointer types;
exact byte counts require a stated platform/ABI. Keep source code and evidence.
'''

_CODE = re.compile(r'#\s*include\b|\bstd::|\b(?:sizeof|alignof|decltype|typeid)\s*\('
                   r'|\b(?:int|char|double|float|void|bool|long|short)\s*[*&]+\s*\w+'
                   r'|\b(?:def|class|function)\s+\w+\s*[:({]|```(?:cpp|c\b|python|java)', re.I)

def code_content(block):
    return ENABLED and bool(_CODE.search(block.get('text', '')))

def coherent_chart(blocks):
    """Only one clearly vector-built bar plot in one page/panel; never infer values.

    Stable bar baselines plus a numeric axis distinguish plots from prose/code.
    Multiple plot baselines/headings stay on the original crop path. All original
    blocks, order, pixels and IDs survive; this changes only the image envelope.
    """
    if not ENABLED or len(blocks) < 8:
        return False
    if len({(b['page'], b.get('zone')) for b in blocks}) != 1:
        return False
    if sum(b.get('kind') in ('heading', 'label') for b in blocks) > 1:
        return False
    bars = [b for b in blocks if b.get('kind') == 'visual'
            and 'vector' in b.get('visualKinds', [])
            and .002 <= b['bbox'][2]-b['bbox'][0] <= .08
            and b['bbox'][3]-b['bbox'][1] >= .025]
    baselines = Counter(round(b['bbox'][3], 2) for b in bars)
    if sum(count >= 6 for count in baselines.values()) != 1:
        return False
    ticks = [b for b in blocks if re.fullmatch(r'\s*[-−]?\d[\d,.]*\s*%?\s*', b.get('text', ''))]
    axes = Counter(round(b['bbox'][0], 2) for b in ticks)
    return any(count >= 3 for count in axes.values())
