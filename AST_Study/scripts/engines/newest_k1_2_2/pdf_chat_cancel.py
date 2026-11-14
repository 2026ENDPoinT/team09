"""Cooperative termination for a single chat worker, never the desktop app."""
import signal


class ChatCancelled(InterruptedError):
    pass


_sealed = False


def start():
    global _sealed
    _sealed = False
    signal.signal(signal.SIGTERM, _terminate)


def _terminate(signum, frame):
    if not _sealed:
        raise ChatCancelled('답변 생성이 중지됐어요.')


def seal():
    """Once an answer exists, finish settlement and publication despite a late stop."""
    global _sealed
    _sealed = True
