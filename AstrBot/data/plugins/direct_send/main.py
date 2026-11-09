"""直发通道（纯文字）：

- 私聊主人的回复用 OneBot HTTP 直发，绕开会卡住的 WebSocket
- 发完清空 completion_text，避免 AstrBot 原通道重复发
- 2026-11-08 起彻底去掉语音：不再合成、不再发语音条
"""

import asyncio
import json
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

OWNER_QQ = 2408224899
STATE = Path(r"D:\QQBot\AstrBot\data\plugin_data\direct_send\state.json")


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    def _state(self) -> dict:
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, state: dict) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _post(self, session, payload) -> bool:
        async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
            data = await resp.json(content_type=None)
        return data.get("status") == "ok"

    async def _send_text(self, lines: list[str]) -> bool:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for i, line in enumerate(lines):
                if i:
                    await asyncio.sleep(0.6)
                if not await self._post(
                    session,
                    {"user_id": OWNER_QQ, "message": [{"type": "text", "data": {"text": line}}]},
                ):
                    return False
        return True

    @filter.on_llm_response()
    async def direct(self, event: AstrMessageEvent, response):
        try:
            if event.get_group_id():
                return
            if str(event.get_sender_id()) != str(OWNER_QQ):
                return
            text = (getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                return
            ok = await self._send_text(lines)
            if ok:
                response.completion_text = ""
                logger.info(f"[direct_send] 已直发 {len(lines)} 条")
            else:
                logger.warning("[direct_send] 直发失败，保留原回复")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[direct_send] 异常: {exc!r}")

    async def initialize(self) -> None:
        logger.info("[direct_send] 直发通道已启动（纯文字，无语音）")
