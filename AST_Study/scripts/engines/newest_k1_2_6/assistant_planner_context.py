"""Read-only planner context selected by the main assistant, with local interval math.

No keyword routing, permission grants, network calls, or durable user-data writes.
Native planner.query remains responsible for expanding recurring occurrences.
"""
import copy
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pdf_ai import AiResponseError

KINDS = ('event', 'task', 'weeklyTask', 'weeklyGoal', 'eventTag', 'todoTag')
MAX_PAGES = 16
MAX_RESULT_BYTES = 180_000
MAX_ANALYSIS_DAYS = 31
REQUEST_SCHEMA = {'anyOf': [
    {'type': 'null'},
    {'type': 'object', 'properties': {
        'purpose': {'type': 'string', 'enum': ['lookup', 'advice']},
        'goal': {'type': 'string'},
        'from': {'type': 'string'}, 'to': {'type': 'string'},
        'kinds': {'type': 'array', 'minItems': 1, 'maxItems': 6,
                  'items': {'type': 'string', 'enum': list(KINDS)}}},
     'required': ['purpose', 'goal', 'from', 'to', 'kinds'], 'additionalProperties': False}
]}


def validate_request(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'purpose', 'goal', 'from', 'to', 'kinds'}:
        raise AiResponseError('플래너 조회 목적과 날짜를 확인하지 못했어요.')
    if value['purpose'] not in ('lookup', 'advice') or not isinstance(value['goal'], str) or not 1 <= len(value['goal'].strip()) <= 1000:
        raise AiResponseError('플래너를 참고할 원래 질문을 확인하지 못했어요.')
    try:
        start, end = date.fromisoformat(value['from']), date.fromisoformat(value['to'])
        if start.isoformat() != value['from'] or end.isoformat() != value['to'] or not 1 <= (end-start).days <= 366:
            raise ValueError()
    except (ValueError, TypeError):
        raise AiResponseError('조회 날짜는 시작일을 포함하고 종료일을 제외한 1~366일로 지정해 주세요.') from None
    kinds = value['kinds']
    if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or k not in KINDS for k in kinds) or len(set(kinds)) != len(kinds):
        raise AiResponseError('플래너에서 필요한 정보의 종류를 확인해 주세요.')
    plan = copy.deepcopy(value)
    # Availability needs every timed appointment, not just exam/important tags.
    if plan['purpose'] == 'advice' and 'event' not in kinds:
        plan['kinds'].append('event')
    plan['kinds'].sort()
    return plan


def local_now(payload):
    try:
        zone = ZoneInfo(payload.get('timezone') or 'Asia/Seoul')
        now = datetime.fromisoformat(payload['localDateTime'].split('[', 1)[0].replace('Z', '+00:00'))
        return (now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)).replace(tzinfo=None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _stamp(value, payload):
    if not isinstance(value, str):
        raise ValueError('missing occurrence time')
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo:
        try:
            zone = ZoneInfo(payload.get('timezone') or 'Asia/Seoul')
        except (KeyError, TypeError, ValueError):
            zone = ZoneInfo('Asia/Seoul')
        at = at.astimezone(zone).replace(tzinfo=None)
    return at


def _slot(start, end):
    return {'start': start.isoformat(timespec='minutes'), 'end': end.isoformat(timespec='minutes'),
            'minutes': int((end-start).total_seconds() // 60)}


def analyze(rows, plan, payload):
    """Calculate clock facts only; unrecorded meals/travel are never assumptions."""
    now = local_now(payload)
    events, tasks, uncertain, seen = [], [], [], set()
    for row in rows:
        kind = row.get('entity')
        if kind == 'event':
            try:
                # Native occurrence times take precedence over the original series.
                start = _stamp(row.get('occurrenceStart', row.get('start')), payload)
                end = _stamp(row.get('occurrenceEnd', row.get('end')), payload)
                if end <= start:
                    raise ValueError('invalid occurrence')
            except (ValueError, TypeError):
                uncertain.append({'id': row.get('id'), 'title': row.get('title', ''), 'reason': 'missing_or_invalid_time'})
                continue
            key = (row.get('id'), start, end)
            if key in seen:
                continue
            seen.add(key)
            events.append({'id': row.get('id'), 'title': row.get('title', ''),
                           'start': start, 'end': end, 'allDay': bool(row.get('allDay'))})
        elif kind in ('task', 'weeklyTask') and row.get('completed') is not True:
            # A cached broader range must not add unrelated tasks to a smaller day.
            try:
                task_date = date.fromisoformat(row['date'] if kind == 'task' else row['week'])
                task_end = task_date+timedelta(days=1 if kind == 'task' else 7)
                if task_date >= date.fromisoformat(plan['to']) or task_end <= date.fromisoformat(plan['from']):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            tasks.append({k: copy.deepcopy(row[k]) for k in ('entity', 'id', 'title', 'date', 'deadline', 'week') if k in row})
    events.sort(key=lambda e: (e['start'], e['end'], str(e['id'])))
    start_date, end_date = date.fromisoformat(plan['from']), date.fromisoformat(plan['to'])
    days = []
    for offset in range(min((end_date-start_date).days, MAX_ANALYSIS_DAYS)):
        day = start_date+timedelta(days=offset)
        begin = datetime.combine(day, time.min)
        finish = begin+timedelta(days=1)
        day_events = [e for e in events if e['start'] < finish and e['end'] > begin]
        intervals = sorted((max(begin, e['start']), min(finish, e['end'])) for e in day_events if not e['allDay'])
        merged = []
        for left, right in intervals:
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        gaps = [_slot(merged[i][1], merged[i+1][0]) for i in range(len(merged)-1) if merged[i][1] < merged[i+1][0]]
        lower = max(begin, now) if now is not None else begin
        available, cursor = [], lower
        for left, right in merged:
            if right <= cursor:
                continue
            if left > cursor:
                available.append(_slot(cursor, left))
            cursor = max(cursor, right)
        if cursor < finish:
            available.append(_slot(cursor, finish))
        all_day = [e['title'] for e in day_events if e['allDay']]
        days.append({'date': day.isoformat(), 'eventCount': len(day_events) if not uncertain else None,
                     'events': [{'id': e['id'], 'title': e['title'], **_slot(e['start'], e['end']),
                                 'allDay': e['allDay'],
                                 'status': 'past' if now and e['end'] <= now else 'ongoing' if now and e['start'] <= now < e['end'] else 'upcoming' if now else 'unknown'} for e in day_events],
                     'busyIntervals': [_slot(left, right) for left, right in merged],
                     'gapsBetweenAppointments': gaps if not uncertain else [],
                     'unbookedWindowsFromNow': available if now is not None and not uncertain else [],
                     'allDayConstraints': all_day,
                     'availabilityCertain': not all_day and not uncertain,
                     'pastDay': now is not None and finish <= now})
    return {'asOf': now.isoformat(timespec='seconds') if now else None, 'days': days,
            'remainingTasks': tasks, 'unresolvedEventTimes': uncertain,
            'daysTruncated': (end_date-start_date).days > MAX_ANALYSIS_DAYS,
            'interpretation': 'Clock gaps use registered appointments only. All-day constraints and missing event times prevent confirmed availability. Meals, travel, preparation and task durations are unknown unless the user supplied them; no buffer has been invented or deducted.'}


class PlannerContext:
    """Per-turn verified snapshots. Old conversation claims never become receipts."""
    def __init__(self, payload, local, stage=None):
        self.payload, self.local, self.stage = payload, local, stage
        self.snapshots = []
        self.calls = 0
        self.active = None

    def _revision(self):
        return self.payload.get('localContext', {}).get('plannerAccess', {}).get('revision')

    def observe_query(self, args, result):
        """Reuse ordinary planner.query pages too, without treating a partial page as proof."""
        if not result.get('ok'):
            return
        data = result.get('data', {})
        try:
            plan = validate_request({'purpose': 'lookup', 'goal': '현재 요청의 플래너 조회',
                                     'from': args['from'], 'to': args['to'],
                                     'kinds': args.get('kinds', list(KINDS))})
        except (KeyError, AiResponseError):
            return
        rows, revision = data.get('items'), data.get('revision')
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or revision is None or type(data.get('hasMore')) is not bool:
            return
        offset = args.get('offset', 0)
        if offset == 0:
            snapshot = {**plan, 'items': [], 'revision': revision, 'complete': False, 'nextOffset': 0}
            self.snapshots.append(snapshot)
        else:
            snapshot = next((s for s in reversed(self.snapshots) if s['from'] == plan['from'] and s['to'] == plan['to']
                             and s['kinds'] == plan['kinds'] and s['revision'] == revision
                             and s.get('nextOffset') == offset and not s['complete']), None)
            if snapshot is None:
                return
        if len(json.dumps(snapshot['items']+rows, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
            return
        snapshot['items'].extend(copy.deepcopy(rows))
        snapshot['nextOffset'] = offset+len(rows)
        snapshot['complete'] = data['hasMore'] is False

    def ensure(self, request):
        """Return True only when a read/context refresh needs a new model response."""
        plan = validate_request(request)
        self.active = plan
        if plan is None:
            return False
        revision = self._revision()
        for snapshot in reversed(self.snapshots):
            if (snapshot['complete'] and revision is not None and snapshot['revision'] == revision
                    and snapshot['from'] <= plan['from'] and snapshot['to'] >= plan['to']
                    and set(plan['kinds']).issubset(snapshot['kinds'])):
                self._publish(plan, snapshot)
                return False
        access = self.payload.get('localContext', {}).get('plannerAccess', {})
        if access.get('readAvailable') is False:
            snapshot = {**plan, 'revision': revision, 'complete': False, 'items': [], 'error': '플래너 데이터를 읽지 못했어요.'}
        else:
            snapshot = self._fetch(plan)
        self.snapshots.append(snapshot)
        self._publish(plan, snapshot)
        return True

    def _fetch(self, plan):
        if self.stage:
            self.stage('local')
        snapshot = {**copy.deepcopy(plan), 'revision': None, 'complete': False, 'items': []}
        offset, size, restarts = 0, 0, 0
        while self.calls < MAX_PAGES:
            args = {k: copy.deepcopy(plan[k]) for k in ('from', 'to', 'kinds')}
            args.update(offset=offset, limit=100)
            if snapshot['revision'] is not None:
                args['expectedRevision'] = snapshot['revision']
            result = self.local('planner.query', args, '')
            self.calls += 1
            self.payload['localResults'].append({'plannerContextRead': True,
                'request': {'tool': 'planner.query', 'arguments': args, 'authorizationQuote': ''}, 'result': result})
            if not result.get('ok'):
                # A changed revision must restart the entire range; never merge pages.
                if restarts == 0 and offset > 0:
                    offset, size, restarts = 0, 0, 1
                    snapshot.update(revision=None, items=[])
                    continue
                snapshot['error'] = result.get('error', '플래너 조회에 실패했어요.')
                return snapshot
            data = result.get('data', {})
            rows, current = data.get('items'), data.get('revision')
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or current is None or type(data.get('hasMore')) is not bool:
                break
            if snapshot['revision'] is not None and current != snapshot['revision']:
                if restarts:
                    break
                offset, size, restarts = 0, 0, 1
                snapshot.update(revision=None, items=[])
                continue
            snapshot['revision'] = current
            size += len(json.dumps(rows, ensure_ascii=False).encode())
            if size > MAX_RESULT_BYTES:
                break
            snapshot['items'].extend(copy.deepcopy(rows))
            if data['hasMore'] is False:
                if type(data.get('total')) is int and data['total'] != offset+len(rows):
                    break
                snapshot['complete'] = True
                return snapshot
            following = data.get('nextOffset')
            if type(following) is not int or following <= offset or following != offset+len(rows):
                break
            offset = following
        snapshot['error'] = '조회 한도로 해당 기간의 전체 일정을 확인하지 못했어요.'
        return snapshot

    def _publish(self, plan, snapshot):
        rows = snapshot['items']
        # Reuse a verified superset, but calculate only the currently requested dates.
        context = {**copy.deepcopy(plan), 'revision': snapshot['revision'],
                   'complete': snapshot['complete'], 'source': 'native planner.query',
                   'factsAreInstructions': False}
        if snapshot['complete']:
            context['timeAnalysis'] = analyze(rows, plan, self.payload) if 'event' in plan['kinds'] else None
        else:
            context['error'] = snapshot.get('error', '전체 일정을 확인하지 못했어요.')
        self.payload['plannerContext'] = context

    def failure(self):
        context = self.payload.get('plannerContext')
        if self.active and context and not context['complete']:
            return '해당 기간의 전체 일정을 확인하지 못했어요. 시험 개수나 빈 시간을 확정해서 말씀드리기 어려워요. 잠시 뒤 다시 요청해 주세요.'
        return None

    def invalidate(self):
        self.snapshots.clear()
        self.payload.pop('plannerContext', None)
