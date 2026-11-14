"""Associate lower chart titles with a same-page plot using source geometry."""
import re
from collections import Counter, defaultdict


_TICK = re.compile(r'[-−]?\d[\d,.]*\s*%?')
_PERIOD = re.compile(r'\b(?:18|19|20)\d{2}\s*(?:[-–—~～]|to)\s*(?:18|19|20)\d{2}\b', re.I)
_MEASURE = re.compile(r'비율|비중|추이|추세|변화|(?:개|인|업체|학교)\s*수\b|\b(?:share|rate|trend|number|change)\b', re.I)
_CHART = re.compile(r'그래프|도표|\b(?:plot|graph|chart)\b', re.I)
_SKIPPED = {'decoration', 'navigation', 'exercise'}


def _active(block):
    return not _SKIPPED.intersection((block.get('localRole'), block.get('planRole')))


def _plot_body(block, ticks):
    if (block.get('kind') != 'visual' or 'vector' not in block.get('visualKinds', ())
            or block.get('geometryFallback') or not _active(block)):
        return False
    x0, y0, x1, y1 = block['bbox']
    if x1 - x0 < .28 or y1 - y0 < .14:
        return False
    axes = Counter()
    for tick in ticks:
        left, top, right, bottom = tick['bbox']
        if min(bottom, y1) <= max(top, y0):
            continue
        if -.01 <= x0 - right <= .12:
            axes[('left', round(right, 2))] += 1
        if -.01 <= left - x1 <= .12:
            axes[('right', round(left, 2))] += 1
    return max(axes.values(), default=0) >= 3


def chart_spans(blocks):
    """Find a plot, its preceding axis ticks, and its unambiguous lower title."""
    pages = defaultdict(list)
    for block in blocks:
        pages[block['page']].append(block)
    matches = []
    for page in pages.values():
        ticks = [b for b in page if _TICK.fullmatch(b.get('text', '').strip())]
        if len(ticks) < 3:
            continue
        plots = [(i, b) for i, b in enumerate(page) if _plot_body(b, ticks)]
        for index, title in enumerate(page):
            if title.get('kind') not in {'heading', 'label', 'caption', 'text'} or not _active(title):
                continue
            label = title.get('text', '').strip()
            if ('\n' in label or len(label) > 110
                    or not (_CHART.search(label) or _PERIOD.search(label) and _MEASURE.search(label))):
                continue
            left, top, right, bottom = title['bbox']
            if bottom - top > .06:
                continue
            candidates = []
            for body_index, plot in plots:
                x0, y0, x1, y1 = plot['bbox']
                overlap = min(right, x1) - max(left, x0)
                if (body_index >= index or top < y1
                        or overlap < .65 * min(right - left, x1 - x0)):
                    continue
                intervening = page[body_index + 1:index]
                # Axis text and short legend labels can follow a plot. A
                # paragraph or a different figure title breaks the association.
                if any(_prose_or_title(b) for b in intervening):
                    continue
                # A chart may be split into aligned vector strips by page
                # zoning. A strip cannot anchor its own title without axes.
                end = y1
                for strip in intervening:
                    a, t, c, b = strip['bbox']
                    if ('vector' in strip.get('visualKinds', ())
                            and abs(a - x0) < .02 and abs(c - x1) < .02
                            and 0 <= t - end <= .09 and b <= top):
                        end = b
                if top - end > .27:
                    continue
                first = body_index
                while first and _TICK.fullmatch(page[first - 1].get('text', '').strip()):
                    a, t, c, b = page[first - 1]['bbox']
                    if not (y0 - b <= .13 and
                            (-.01 <= x0 - c <= .12 or -.01 <= a - x1 <= .12)):
                        break
                    first -= 1
                candidates.append((plot['id'], tuple(b['id'] for b in page[first:index + 1])))
            if len(candidates) == 1:
                body, members = candidates[0]
                matches.append((title['id'], body, members))
    return matches


def chart_title_owners(blocks):
    return {title: body for title, body, _ in chart_spans(blocks)}


def chart_panels(blocks):
    """Return non-overlapping contiguous plot runs ready for one image crop."""
    positions = {block['id']: i for i, block in enumerate(blocks)}
    panels = []
    end = -1
    for _, _, members in chart_spans(blocks):
        start, stop = positions[members[0]], positions[members[-1]]
        if start <= end or stop - start + 1 != len(members):
            continue
        panels.append((start, stop + 1))
        end = stop
    return panels


def _prose_or_title(block):
    text = block.get('text', '').strip()
    if not text or not re.search(r'[a-z가-힣]', text, re.I):
        return False
    return (len(text) > 36 or bool(_CHART.search(text))
            or bool(_PERIOD.search(text) and _MEASURE.search(text)))


def repair_chart_groups(blocks, groups):
    """Apply the same rule to an existing paid plan, preserving its other owners."""
    attachments = chart_title_owners(blocks)
    labels = {b['id']: i for i, group in enumerate(groups) for b in group['blocks']}
    moves = {title: labels[body] for title, body in attachments.items()
             if title in labels and body in labels and labels[title] != labels[body]}
    if not moves:
        return groups
    assigned = [[] for group in groups]
    grouped_blocks = {b['id']: b for group in groups for b in group['blocks']}
    for block in blocks:
        key = block['id']
        assigned[moves.get(key, labels[key])].append(grouped_blocks[key])
    return [{**group, 'blocks': members} for group, members in zip(groups, assigned) if members]
