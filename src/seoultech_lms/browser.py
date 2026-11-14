from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
from contextlib import suppress
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, unquote_plus, urlparse

from playwright.async_api import Browser, BrowserType, Error, Page, Route, TimeoutError as PlaywrightTimeout, async_playwright

from .auth import AuthenticationRequired, ensure_private_directory, harden_auth_state, normalize_login_id, write_auth_state_secure
from .endpoints import BASE_URL, MAIN_FORM


LMS_URL = f"{BASE_URL}/"
LOGIN_TIMEOUT_SECONDS = 10 * 60
_LMS_HOST = "eclass.seoultech.ac.kr"
_LOGIN_GET_PATHS = frozenset({"/", "/ilos/index.jsp", "/ilos/index.acl", "/ilos/main/member/login_form.acl", MAIN_FORM})
_LOGIN_POST_PATHS = frozenset({
    "/ilos/lo/login.acl",
    "/ilos/main/member/login_notice_view.acl",
    "/ilos/main/member/notice_view_pop.acl",
    "/ilos/main/related_sites.acl",
})
_LOGIN_ASSET_PREFIXES = ("/ilos/css/", "/ilos/js/", "/ilos/images/", "/ext/ilos/images/", "/ilos/favicon")
_LOGIN_ASSET_SUFFIXES = frozenset({".css", ".js", ".woff", ".woff2", ".ttf", ".png", ".gif", ".jpg", ".jpeg", ".svg", ".ico", ".webp"})


async def _launch(
    browser_type: BrowserType, *, headless: bool, prefer_chrome: bool = True, timeout: float | None = None,
) -> Browser:
    primary, fallback = ("chrome", None) if prefer_chrome else (None, "chrome")
    try:
        return await browser_type.launch(channel=primary, headless=headless, timeout=timeout)
    except (Error, OSError):
        return await browser_type.launch(channel=fallback, headless=headless, timeout=timeout)


def _is_authenticated_lms_url(url: str) -> bool:
    parsed = urlparse(url)
    return _is_lms_origin(parsed) and parsed.path == MAIN_FORM


def _is_lms_origin(parsed: ParseResult) -> bool:
    return (
        parsed.scheme == "https"
        and parsed.hostname == _LMS_HOST
        and parsed.port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def _allowed_login_request(method: str, url: str, resource_type: str) -> bool:
    parsed = urlparse(url)
    if not _is_lms_origin(parsed):
        return False
    if method == "POST":
        return parsed.path in _LOGIN_POST_PATHS and not parsed.query
    if method != "GET":
        return False
    return parsed.path in _LOGIN_GET_PATHS or (
        resource_type in {"stylesheet", "script", "font", "image"}
        and parsed.path.startswith(_LOGIN_ASSET_PREFIXES)
        and Path(parsed.path).suffix in _LOGIN_ASSET_SUFFIXES
    )


async def _guard_login_request(route: Route) -> None:
    request = route.request
    if _allowed_login_request(request.method, request.url, request.resource_type):
        await route.continue_()
    else:
        await route.abort("blockedbyclient")


def _submitted_login_id(body: str | None) -> str | None:
    if not body:
        return None
    fields = [value for field in body.split("&") for name, _, value in [field.partition("=")] if name == "usr_id"]
    return normalize_login_id(unquote_plus(fields[0])) if len(fields) == 1 else None


async def _open_login_page(browser: Browser, on_account: Callable[[str | None], None] | None = None) -> Page:
    context = await browser.new_context(service_workers="block", accept_downloads=False)
    page = await context.new_page()

    async def guard(route: Route) -> None:
        request = route.request
        url = urlparse(request.url)
        # The official form submits into a hidden frame of the login page.
        if (on_account and request.method == "POST" and _is_lms_origin(url)
                and url.path == "/ilos/lo/login.acl" and not url.query
                and request.is_navigation_request() and request.frame.page == page):
            on_account(_submitted_login_id(request.post_data))
        await _guard_login_request(route)

    await context.route("**/*", guard)
    await page.goto(LMS_URL, wait_until="domcontentloaded", timeout=20_000)
    return page


@dataclass(frozen=True)
class _LoginCapture:
    state: dict[str, Any] | None
    message: str
    login_id: str | None = None


class DesktopLogin:
    """Keep a completed browser login in memory until the app confirms it."""

    def __init__(self) -> None:
        self._attempt: asyncio.Task[_LoginCapture] | None = None
        self._page: Page | None = None
        self._capture_requested = asyncio.Event()

    async def open(self) -> dict[str, str]:
        if self._attempt is not None and not self._attempt.done():
            return {"status": "already_open", "message": "열려 있는 브라우저에서 e-Class 로그인을 계속해 주세요."}

        opened: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._capture_requested = asyncio.Event()
        self._attempt = asyncio.create_task(self._capture(opened))
        if not await asyncio.shield(opened):
            return {"status": "error", "message": (await self._attempt).message}
        return {"status": "opened", "message": "열린 브라우저에서 e-Class에 로그인해 주세요."}

    async def status(self, *, recheck: bool = False) -> dict[str, str]:
        attempt = self._attempt
        if attempt is None:
            return {"status": "idle", "message": "e-Class 로그인 창이 열려 있지 않아요."}
        page = self._page
        if recheck and not attempt.done() and page is not None and _is_authenticated_lms_url(page.url):
            self._capture_requested.set()
            await asyncio.wait((attempt,), timeout=2)
        if not attempt.done():
            return {"status": "pending", "message": "열린 창에서 ASTRA 로그인을 완료해 주세요."}
        if attempt.cancelled():
            return {"status": "closed", "message": "로그인 창이 닫혔어요. 다시 로그인해 주세요."}
        result = attempt.result()
        if result.state is not None:
            return {"status": "captured", "message": "ASTRA 로그인 정보를 확인하고 있어요."}
        return {"status": "closed", "message": result.message}

    def candidate(self) -> dict[str, Any] | None:
        if self._attempt is None:
            return None
        if not self._attempt.done():
            raise AuthenticationRequired("아직 로그인이 완료되지 않았어요. 열린 브라우저에서 로그인한 뒤 다시 확인해 주세요.")
        result = self._attempt.result()
        if result.state is None:
            raise AuthenticationRequired(result.message)
        return result.state

    def clear(self) -> None:
        if self._attempt is not None and not self._attempt.done():
            self._attempt.cancel()
        self._attempt = None
        self._page = None

    def login_id(self) -> str | None:
        attempt = self._attempt
        return attempt.result().login_id if attempt and attempt.done() and not attempt.cancelled() else None

    async def _capture(self, opened: asyncio.Future[bool]) -> _LoginCapture:
        capture_requested = self._capture_requested
        login_id = None

        def remember_account(value: str | None) -> None:
            nonlocal login_id
            login_id = value
        try:
            async with async_playwright() as playwright:
                try:
                    browser = await _launch(playwright.chromium, headless=False, prefer_chrome=False, timeout=10_000)
                except (Error, OSError):
                    return _LoginCapture(None, "Chromium과 Chrome을 모두 열지 못했어요. Google Chrome이 설치되어 있고 직접 열리는지 확인해 주세요.")
                try:
                    page = await _open_login_page(browser, remember_account)
                    self._page = page
                    opened.set_result(True)
                    navigation = asyncio.create_task(page.wait_for_url(
                        _is_authenticated_lms_url, wait_until="commit", timeout=LOGIN_TIMEOUT_SECONDS * 1000,
                    ))
                    manual_check = asyncio.create_task(capture_requested.wait())
                    try:
                        done, _ = await asyncio.wait((navigation, manual_check), return_when=asyncio.FIRST_COMPLETED)
                        if navigation in done:
                            await navigation
                    finally:
                        for waiter in (navigation, manual_check):
                            if not waiter.done():
                                waiter.cancel()
                        await asyncio.gather(navigation, manual_check, return_exceptions=True)
                    if not _is_authenticated_lms_url(page.url):
                        return _LoginCapture(None, "공식 e-Class 로그인 화면을 확인하지 못했어요. 다시 로그인해 주세요.")
                    cookies = [cookie for cookie in await page.context.cookies() if cookie["domain"].lstrip(".") == _LMS_HOST]
                    if cookies:
                        return _LoginCapture({"cookies": cookies, "origins": []}, "", login_id)
                    return _LoginCapture(None, "e-Class 세션을 확인하지 못했어요. 로그인 버튼으로 다시 시도해 주세요.")
                finally:
                    if browser.is_connected():
                        with suppress(Error):
                            await browser.close()
        except PlaywrightTimeout:
            return _LoginCapture(None, "e-Class 접속 또는 로그인 대기 시간이 지났어요. 다시 시도해 주세요.")
        except (Error, OSError):
            if opened.done():
                return _LoginCapture(None, "로그인이 완료되기 전에 브라우저가 닫혔어요. 로그인 버튼으로 다시 시도해 주세요.")
            return _LoginCapture(None, "e-Class 로그인 화면을 열지 못했어요. e-Class 연결을 확인하고 다시 시도해 주세요.")
        finally:
            if capture_requested is self._capture_requested:
                self._page = None
            if not opened.done():
                opened.set_result(False)


def _persist_authenticated_state(
    state_path: Path,
    current_url: str,
    state: dict[str, Any],
) -> None:
    if not _is_authenticated_lms_url(current_url):
        raise RuntimeError(
            "LMS 로그인이 확인되지 않았습니다. e-Class 메인 화면까지 이동한 뒤 다시 시도해주세요."
        )
    write_auth_state_secure(state_path, state)


async def interactive_login(
    state_path: Path,
    *,
    wait_for_enter: bool = True,
    timeout_seconds: int = LOGIN_TIMEOUT_SECONDS,
) -> None:
    """Open LMS; the user completes any authentication personally in Chromium."""
    ensure_private_directory(state_path.parent)
    async with async_playwright() as playwright:
        browser = await _launch(playwright.chromium, headless=False)
        try:
            page = await _open_login_page(browser)
            if wait_for_enter:
                print("브라우저에서 직접 로그인한 뒤 LMS 메인 화면이 보이면 여기 터미널에서 Enter를 누르세요.")
                input()
            else:
                deadline = asyncio.get_running_loop().time() + timeout_seconds
                while not _is_authenticated_lms_url(page.url):
                    if page.is_closed():
                        raise RuntimeError("로그인 창이 완료 전에 닫혔습니다.")
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("LMS 로그인 대기 시간이 만료되었습니다.")
                    await page.wait_for_timeout(500)
                await page.wait_for_timeout(1000)
            state = await page.context.storage_state()
            _persist_authenticated_state(state_path, page.url, state)
        finally:
            await browser.close()


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def start_login_browser(state_path: Path) -> dict[str, str]:
    """Start a detached login helper so MCP stdio remains available."""
    ensure_private_directory(state_path.parent)
    pid_path = state_path.with_name("login_process.pid")
    try:
        existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        existing_pid = 0
    if _process_is_running(existing_pid):
        return {
            "status": "already_open",
            "message": "이미 LMS 로그인 창이 열려 있습니다. 열린 창에서 직접 로그인해주세요.",
        }

    popen_options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(  # noqa: S603 - fixed local module invocation
        [sys.executable, "-m", "seoultech_lms.login_window"],
        **popen_options,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {
        "status": "started",
        "message": (
            "LMS 로그인용 Chrome 창을 열었습니다. 브라우저에서 직접 로그인하세요. "
            "LMS 메인 화면이 확인되면 세션이 저장되고 창이 자동으로 닫힙니다."
        ),
    }


async def session_is_valid(state_path: Path) -> bool:
    """Conservative check: an expired state must be renewed interactively."""
    if not state_path.is_file():
        return False
    harden_auth_state(state_path)
    async with async_playwright() as playwright:
        browser = await _launch(playwright.chromium, headless=True)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            response = await page.goto(LMS_URL, wait_until="domcontentloaded")
            valid = bool(response and response.ok and _is_authenticated_lms_url(page.url))
        finally:
            await browser.close()
    return valid
