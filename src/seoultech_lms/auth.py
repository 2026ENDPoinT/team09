from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any


class AuthenticationRequired(RuntimeError):
    """Raised when the locally saved browser session is absent or expired."""


_ACCOUNT_KEY = re.compile(r"[a-f0-9]{64}")
_LAST_SESSION_FILE = ".last-session.json"


def normalize_login_id(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.@-]{1,100}", value.strip()):
        return value.strip()
    return None


def account_storage_root() -> Path | None:
    directory = os.environ.get("AST_LMS_ACCOUNT_DIR")
    return Path(directory) if directory else None


def account_session_path(root: Path, key: str) -> Path:
    return root / key / "lms" / "auth_state.json"


def _account_session_paths(root: Path):
    if root.is_dir():
        for directory in root.iterdir():
            if _ACCOUNT_KEY.fullmatch(directory.name) and not directory.is_symlink() and not (directory / "lms").is_symlink():
                yield account_session_path(root, directory.name)


def last_session_account(root: Path) -> str | None:
    try:
        saved = json.loads((root / _LAST_SESSION_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Older versions only wrote account sessions after a successful verification.
        sessions = [(path.stat().st_mtime_ns, path.parent.parent.name)
                    for path in _account_session_paths(root) if path.is_file()]
        return max(sessions)[1] if sessions else None
    key = saved.get("account_key") if isinstance(saved, dict) else None
    return key if isinstance(key, str) and _ACCOUNT_KEY.fullmatch(key) else None


def clear_account_sessions(root: Path) -> None:
    for path in _account_session_paths(root):
        path.unlink(missing_ok=True)
    (root / _LAST_SESSION_FILE).unlink(missing_ok=True)


def save_account_session(root: Path, login_id: str, state: dict[str, Any]) -> str:
    secret_file = root / ".account-key.json"
    try:
        stored = json.loads(secret_file.read_text(encoding="utf-8"))
        secret = bytes.fromhex(stored["secret"])
        if len(secret) != 32:
            raise ValueError("Invalid account key")
    except FileNotFoundError:
        secret = secrets.token_bytes(32)
        write_auth_state_secure(secret_file, {"secret": secret.hex()})
    key = hmac.new(secret, login_id.encode("utf-8"), hashlib.sha256).hexdigest()
    ensure_private_directory(root / key)
    write_auth_state_secure(account_session_path(root, key), state)
    write_auth_state_secure(root / _LAST_SESSION_FILE, {"account_key": key})
    return key


def user_data_dir() -> Path:
    if app_data_dir := os.environ.get("AST_LMS_DATA_DIR"):
        return Path(app_data_dir)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Agent for SeoulTech" / "lms"
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "Agent for SeoulTech" / "lms"
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "agent-for-seoultech" / "lms"
    return Path.home() / ".local" / "share" / "agent-for-seoultech" / "lms"


def auth_state_path(project_root: Path | None = None) -> Path:
    return (project_root / "data" if project_root else user_data_dir()) / "auth_state.json"


def ensure_private_directory(path: Path) -> None:
    """Create a user-only directory on POSIX without weakening other platforms."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)


def harden_auth_state(path: Path) -> None:
    """Restrict an existing authentication state file to its owner on POSIX."""
    if os.name == "posix" and path.is_file():
        path.chmod(0o600)


def write_auth_state_secure(path: Path, state: dict[str, Any]) -> None:
    """Atomically persist browser state with user-only POSIX permissions."""
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        harden_auth_state(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def require_auth_state(project_root: Path | None = None) -> Path:
    path = auth_state_path(project_root)
    if not path.is_file():
        raise AuthenticationRequired(
            "LMS 로그인 세션이 없습니다. start_login 도구를 호출해 로그인 창을 열어주세요. "
            "터미널에서는 'seoultech-lms login'을 사용할 수 있습니다."
        )
    harden_auth_state(path)
    return path
