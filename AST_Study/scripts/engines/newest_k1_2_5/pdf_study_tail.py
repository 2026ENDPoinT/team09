"""Conservative, version-scoped slow-response policy; no source/model changes."""
import re
AFTER_SECONDS = 45.0
WINDOW_SECONDS = 10.0
MIN_WINDOW_CHARS = 200
STATUS_FRESH_SECONDS = 10.0
OUTPUT_LOOP_AFTER_SECONDS = 10.0


class ControlSequenceLoop:
    """Detect a continuous ANSI reset/color loop, including split JSON escapes.

    Ordinary repeated words, formulas, code and separated terminal colors are
    not considered broken output. This signal never edits or accepts the text.
    """
    pattern = re.compile(r'(?:(?:\\{1,4}u001[bB]|\x1b)\[[0-9;]{0,30}m){16,}')

    def __init__(self):
        self.tail = ''
        self.detected = False

    def feed(self, text):
        self.tail = (self.tail + text)[-2048:]
        self.detected = self.detected or self.pattern.search(self.tail) is not None
        return self.detected


def enabled(context, payload, options):
    # A replacement may have different wording. A streamed preview must support
    # reset before publishing another attempt, or it could concatenate answers.
    return (context.get('strategy') == 'newest-k1-1-1'
            and payload.get('task') == 'region_teaching'
            and context.get('kind') == 'region_study'
            and (options.get('on_study_delta') is None
                 or callable(options.get('on_delivery_reset'))))


def native_timings(value):
    """Server lifecycle is not model compute time; preserve that distinction."""
    created, completed = value.get('created_at'), value.get('completed_at')
    fields = {}
    if type(created) in (int, float) and 0 < created < 1e11:
        fields['serverCreatedAtMs'] = int(created * 1000)
        if type(completed) in (int, float) and created <= completed < 1e11:
            fields['serverCompletedAtMs'] = int(completed * 1000)
            fields['serverLifecycleSeconds'] = round(completed-created, 4)
    return fields
