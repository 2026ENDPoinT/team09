"""User-visible work updates from existing model turns and actual host results."""
import time


def text(value, maximum=320):
    return ' '.join(str(value or '').split())[:maximum]


LABELS = {
    'profile.get': '계정 정보를 확인할게요.', 'memory.read': '저장된 선호를 확인할게요.',
    'memory.update': '요청한 선호를 반영할게요.', 'planner.query': '일정을 조회할게요.',
    'planner.apply': '요청한 일정 변경을 적용할게요.', 'planner.scheduleBatch': '요청한 일정을 등록할게요.',
    'actions.undo': '직전 작업을 되돌릴게요.', 'library.query': '자료함의 항목을 확인할게요.',
    'library.open': '요청한 항목을 열게요.', 'library.createFolder': '폴더를 만들게요.',
    'library.rename': '요청한 이름 변경을 적용할게요.', 'library.trash': '요청한 항목을 휴지통으로 옮길게요.',
    'library.proposeMove': '파일 이동 대상과 목적지를 확인할게요.',
    'library.confirmMove': '확인한 이동안을 적용할게요.'}


def count(data, key, rows=None):
    value = data.get(key)
    if type(value) is int and value >= 0:
        return value
    return len(data[rows]) if rows and isinstance(data.get(rows), list) else None


def result_text(tool, result):
    if not isinstance(result, dict):
        return '작업 결과를 확인하지 못했어요.'
    if not result.get('ok'):
        return '작업을 완료하지 못했어요. ' + text(result.get('error') or '처리 결과를 확인해 주세요.')
    data = result.get('data', {})
    if not isinstance(data, dict):
        return '처리 결과를 받았어요.'
    if tool in ('library.query', 'planner.query'):
        label = '자료함 항목' if tool == 'library.query' else '일정 항목'
        n = count(data, '', 'items')
        return label + (f' {n}개를 조회했어요.' if n is not None else '을 조회했어요.') + (' 남은 항목을 더 확인할게요.' if data.get('hasMore') else '')
    if tool in ('library.proposeMove', 'library.confirmMove'):
        if data.get('alreadyThere'):
            return '대상 항목은 이미 지정한 폴더에 있어요.'
        n = count(data, 'movedCount', 'moved')
        if data.get('applied') is True or n is not None and n > 0:
            destination = text(data.get('destinationPath'), 120)
            return (f'{n}개 항목을' if n is not None else '대상 항목을') + (' “' + destination + '” 폴더로' if destination else '') + ' 옮겼어요.'
        return '이동안을 준비했어요. 아직 항목을 옮기지 않았어요.'
    if tool == 'library.rename':
        n = count(data, 'renamedCount', 'renamed')
        return (f'{n}개 항목의 이름을 변경했어요.' if n else '새로 이름을 변경한 항목은 없어요.') if n is not None else '이름 변경 결과를 확인했어요.'
    if tool == 'library.trash':
        n = count(data, 'trashedCount', 'moved')
        return (f'{n}개 항목을' if n is not None else '대상 항목을') + ' 휴지통으로 옮겼어요.'
    if tool == 'library.createFolder':
        folder = data.get('folder', {})
        name = text(data.get('path') or data.get('name') or (folder.get('path') or folder.get('name') if isinstance(folder, dict) else ''), 120)
        return ('“' + name + '” 폴더를' if name else '폴더를') + ' 만들었어요.'
    if tool == 'library.open':
        if data.get('animationCompleted') is False:
            return '열기 요청을 전달했어요. 화면 전환 결과는 확인 중이에요.'
        return '대상 항목이 이미 열려 있어요.' if data.get('alreadyOpen') or data.get('status') == 'already_open' else '요청한 항목을 열었어요.'
    if tool == 'planner.scheduleBatch':
        added = count(data, 'addedCount')
        if added is None:
            return '일정 등록 결과를 받았어요.'
        message = f'{added}개 일정을 등록했어요.'
        if data.get('alreadyPresentCount'):
            message += f' {data["alreadyPresentCount"]}개는 이미 등록돼 있어요.'
        if data.get('skippedCount'):
            message += f' 시간이 겹친 {data["skippedCount"]}개는 제외했어요.'
        return message
    return {'planner.apply': '요청한 일정 변경을 적용했어요.', 'memory.update': '요청한 선호를 저장했어요.',
            'memory.read': '저장된 선호를 확인했어요.', 'profile.get': '계정 정보를 확인했어요.',
            'actions.undo': '직전 작업을 되돌렸어요.'}.get(tool, '처리 결과를 확인했어요.')


class Activity:
    def __init__(self, callback=None, streamlined=False):
        self.callback = callback
        self.streamlined = streamlined
        self.note = ''
        self.sequence = 0
        self.previous = None
        self.tone = 'polite'

    def style(self, message):
        if self.tone == 'casual':
            pairs = [('할게요.', '할게.'), ('열게요.', '열게.'), ('만들게요.', '만들게.'),
                     ('옮길게요.', '옮길게.'), ('되돌릴게요.', '되돌릴게.'), ('중이에요.', '중이야.'),
                     ('했어요.', '했어.'), ('있어요.', '있어.'), ('없어요.', '없어.'),
                     ('않았어요.', '않았어.'), ('받았어요.', '받았어.'), ('옮겼어요.', '옮겼어.'),
                     ('열었어요.', '열었어.'), ('만들었어요.', '만들었어.'), ('주세요.', '줘.')]
        elif self.tone == 'formal':
            pairs = [('할게요.', '하겠습니다.'), ('열게요.', '열겠습니다.'), ('만들게요.', '만들겠습니다.'),
                     ('옮길게요.', '옮기겠습니다.'), ('되돌릴게요.', '되돌리겠습니다.'), ('중이에요.', '중입니다.'),
                     ('했어요.', '했습니다.'), ('있어요.', '있습니다.'), ('없어요.', '없습니다.'),
                     ('않았어요.', '않았습니다.'), ('받았어요.', '받았습니다.'), ('옮겼어요.', '옮겼습니다.'),
                     ('열었어요.', '열었습니다.'), ('만들었어요.', '만들었습니다.')]
        else:
            return message
        for source, target in pairs:
            message = message.replace(source, target)
        return message

    def plan(self, note):
        self.note = text(note, 240)

    def emit(self, phase, tool, message):
        message = text(message)
        key = (phase, tool, message)
        if not self.callback or not message or key == self.previous:
            return
        self.sequence += 1
        self.previous = key
        self.callback({'id': self.sequence, 'phase': phase, 'tool': tool,
                       'text': message, 'timestampMs': int(time.time() * 1000)})

    def wrap(self, local):
        def invoke(tool, arguments, authorization):
            if tool not in LABELS:
                result = local(tool, arguments, authorization)
                if tool == 'context.get' and result.get('ok'):
                    self.tone = result.get('data', {}).get('personalization', {}).get('values', {}).get('tone', 'polite')
                return result
            self.emit('status' if self.streamlined else 'plan', tool, self.note or self.style(LABELS[tool]))
            self.note = ''
            try:
                result = local(tool, arguments, authorization)
            except Exception:
                if not self.streamlined:
                    self.emit('error', tool, self.style('작업 결과를 확인하지 못했어요. 완료 여부를 확인한 뒤 이어서 진행해 주세요.'))
                raise
            ok = isinstance(result, dict) and result.get('ok')
            if not self.streamlined:
                self.emit('result' if ok else 'error', tool, self.style(result_text(tool, result)))
            elif ok and tool not in ('planner.query', 'library.query', 'memory.read', 'profile.get'):
                # The host keeps confirmed outcomes for an interrupted turn.
                self.emit('result', tool, self.style(result_text(tool, result)))
            return result
        return invoke
