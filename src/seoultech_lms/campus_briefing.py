from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, get_args
from zoneinfo import ZoneInfo

import httpx

from .campus_notices import CampusBoard, CampusNoticeClient

_BOARDS = get_args(CampusBoard)
_READ_ERRORS = (httpx.HTTPError, RuntimeError, ValueError)


async def get_campus_briefing() -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    first_day = (now.date() - timedelta(days=6)).isoformat()
    today = now.date().isoformat()
    board_slots = asyncio.Semaphore(2)

    async with CampusNoticeClient() as client:
        async def read_board(board: CampusBoard) -> tuple[list[dict[str, Any]], bool]:
            recent: dict[tuple[str, str], dict[str, Any]] = {}
            complete = False
            async with board_slots:
                try:
                    async with asyncio.timeout(25):
                        page = 1
                        for _ in range(3):
                            result = await client.list_notices(board, start_page=page, pages=3)
                            for notice in result["notices"]:
                                published = notice["published_at"]
                                if published and first_day <= published <= today:
                                    recent.setdefault((notice["board_id"], notice["id"]), notice)

                            ordinary = [notice for notice in result["notices"] if not notice["pinned"]]
                            tail = ordinary[-20:]
                            page = result["next_page"]
                            if page is None or (
                                tail and all(notice["published_at"] and notice["published_at"] < first_day for notice in tail)
                            ):
                                complete = True
                                break
                except (*_READ_ERRORS, TimeoutError):
                    pass

                notices = sorted(recent.values(), key=lambda item: item["published_at"], reverse=True)
                try:
                    async with asyncio.timeout(6):
                        for notice in notices[:2]:
                            if notice.get("preview"):
                                continue
                            try:
                                detail = await client.get_notice(board, notice["board_id"], notice["id"])
                            except _READ_ERRORS:
                                continue
                            text = " ".join(detail["content"].split())
                            notice["preview"] = text[:160] + ("…" if len(text) > 160 else "") if text else None
                except TimeoutError:
                    pass
                return notices, complete

        results = await asyncio.gather(*(read_board(board) for board in _BOARDS))

    notices: dict[tuple[str, str], dict[str, Any]] = {}
    unavailable = []
    for board, (items, complete) in zip(_BOARDS, results, strict=True):
        if not complete:
            unavailable.append(board)
        for notice in items:
            notices.setdefault((notice["board_id"], notice["id"]), notice)
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "notices": sorted(notices.values(), key=lambda item: item["published_at"], reverse=True),
        "unavailable": unavailable,
    }
