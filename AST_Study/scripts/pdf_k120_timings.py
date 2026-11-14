"""Separate wallet waiting, local slots and API time without adding hedge lanes."""
import math

from pdf_study_timings import unit_timings as legacy_timings


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _merged(intervals):
    output = []
    for start, end in sorted((a, b) for a, b in intervals if _number(a) and _number(b) and b >= a):
        if output and start <= output[-1][1]: output[-1][1] = max(output[-1][1], end)
        else: output.append([start, end])
    return output


def _seconds(intervals, exclude=()):
    merged, excluded = _merged(intervals), _merged(exclude)
    total = sum(b - a for a, b in merged)
    for a, b in merged:
        total -= sum(max(0, min(b, y) - max(a, x)) for x, y in excluded)
    return max(0, total / 1000)


def unit_timings(jobs, done, failures, ledger, *, local_units=(), admission_timings=None):
    rows = legacy_timings(jobs, done, failures, ledger, local_units=local_units)
    entries = list(ledger.get('requests', []))
    admissions = admission_timings if admission_timings is not None else ledger.get('admissionTimings', {})
    failed = {item.get('unitId'): item for item in failures}
    for row in rows:
        requests = [r for r in entries if r.get('kind') == 'region_study' and row['unitId'] in r.get('unitIds', [])]
        records = list((admissions.get(row['unitId']) or {}).values())
        intervals, queues, grouped = [], [], {}
        for request in requests:
            group = request.get('hedgeGroup') or request.get('requestId')
            grouped.setdefault(group, []).append(request)
        totals, network_complete = [], True
        for group in grouped.values():
            winner = next((r for r in group if r.get('hedgeWinner')), None)
            end = None
            if winner and _number(winner.get('sentAtMs')) and _number(winner.get('latencySeconds')):
                end = winner['sentAtMs'] + max(0, winner['latencySeconds'] - winner.get('queueSeconds', 0)) * 1000
            total = winner.get('hedgeResultSeconds') if winner else None
            if not _number(total) and len(group) == 1: total = group[0].get('latencySeconds')
            if _number(total): totals.append(total)
            for request in group:
                start, duration, queue = request.get('sentAtMs'), request.get('latencySeconds'), request.get('queueSeconds', 0)
                if not _number(queue): queue = 0
                if _number(start) and not _number(duration): network_complete = False
                if _number(start) and _number(duration):
                    stop = start + max(0, duration - queue) * 1000
                    if end is not None: stop = min(stop, end)
                    if stop >= start: intervals.append([start, stop])
                    queues.append([max(0, start - queue * 1000), start])
        if totals and len(totals) == len(grouped): row['totalSeconds'] = round(sum(totals), 3)
        elif records:
            start = min(r['startedAtMs'] for r in records)
            end = max(r.get('endedAtMs', r['startedAtMs']) for r in records)
            row['totalSeconds'] = round(max(0, end - start) / 1000, 3)
        if intervals:
            # A first-send-to-winner span can include a gap spent awaiting money
            # for a replacement. Count only measured, overlapping API intervals.
            if network_complete: row['apiSeconds'] = round(_seconds(intervals), 3)
            row['localQueueSeconds'] = round(_seconds(queues, intervals), 3)
        elif records and not requests:
            row['apiSeconds'] = 0.
            row['localQueueSeconds'] = 0.
        waits = [span for record in records for span in record.get('waitIntervals', [])]
        if waits:
            row['reservationWaitSeconds'] = round(_seconds(waits, intervals), 3)
        elif requests:
            # Historical records have no intervals. One winning lane's pre-send
            # wait is known; never sum parallel backup reservation waits.
            waits = [r.get('reservationWaitSeconds') for r in requests if r.get('hedgeWinner') or not r.get('hedgeGroup')]
            measured = [v for v in waits if _number(v)]
            if measured: row['reservationWaitSeconds'] = round(max(measured), 3)
        elif records:
            row['reservationWaitSeconds'] = 0.
        if row['status'] == 'failed':
            failure = failed.get(row['unitId'], {})
            reason = failure.get('detail') or next((r.get('failureReason') for r in records
                                                   if r.get('error') != 'InterruptedError' and r.get('failureReason')), None)
            row['failureReason'] = reason or failure.get('error') or '완료된 응답을 받지 못했어요.'
        # Keep the old field as overall elapsed time for existing consumers.
        if 'totalSeconds' in row: row['requestSeconds'] = row['totalSeconds']
    return rows
