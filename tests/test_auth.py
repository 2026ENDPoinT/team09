import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from seoultech_lms.auth import account_session_path, ensure_private_directory, last_session_account, save_account_session, user_data_dir, write_auth_state_secure


class AuthPathTests(unittest.TestCase):
    def test_macos_uses_application_support(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("seoultech_lms.auth.sys.platform", "darwin"),
            patch("seoultech_lms.auth.Path.home", return_value=Path("/Users/test")),
        ):
            self.assertEqual(
                user_data_dir(),
                Path("/Users/test/Library/Application Support/Agent for SeoulTech/lms"),
            )

    def test_auth_state_is_written_atomically_as_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "auth_state.json"
            state = {"cookies": [{"name": "session", "value": "secret"}]}
            write_auth_state_secure(path, state)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), state)
            self.assertEqual(list(path.parent.glob(".auth_state.json.*.tmp")), [])

    @patch("seoultech_lms.auth.Path.chmod")
    def test_private_directory_uses_owner_only_mode_on_posix(self, chmod):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private"
            with patch("seoultech_lms.auth.os.name", "posix"):
                ensure_private_directory(path)
            chmod.assert_called_once_with(0o700)

    def test_startup_uses_latest_verified_session_from_an_older_app_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "accounts"
            first = save_account_session(root, "fixture-one", {"cookies": []})
            latest = save_account_session(root, "fixture-two", {"cookies": []})
            os.utime(account_session_path(root, first), (1, 1))
            os.utime(account_session_path(root, latest), (2, 2))
            (root / ".last-session.json").unlink()
            self.assertEqual(last_session_account(root), latest)

    def test_account_key_is_stable_and_sessions_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "accounts"
            first = save_account_session(root, "20260001", {"cookies": ["first"]})
            second = save_account_session(root, "20260002", {"cookies": ["second"]})
            self.assertNotEqual(first, second)
            self.assertRegex(first, r"^[a-f0-9]{64}$")
            self.assertEqual(save_account_session(root, "20260001", {"cookies": ["updated"]}), first)
            for key, cookie in [(first, "updated"), (second, "second")]:
                path = root / key / "lms" / "auth_state.json"
                self.assertEqual(json.loads(path.read_text()), {"cookies": [cookie]})


if __name__ == "__main__":
    unittest.main()
