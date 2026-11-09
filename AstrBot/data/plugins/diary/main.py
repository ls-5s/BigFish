"""轻量日记插件。

- 记录最近对话（最多 20 轮）
- 每天 23:30 用 LLM 生成一篇第一人称日记，存文件并推送到 QQ
- /写日记 立即生成一篇（补写/测试用）
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"
DIARY_DIR = BASE / "diary"
OWNER_QQ = 2408224899


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None
        DIARY_DIR.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            self._write({"recent": [], "last_diary": ""})

    def _read(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"recent": [], "last_diary": ""}

    def _write(self, state: dict) -> None:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @filter.on_llm_response()
    async def record(self, event: AstrMessageEvent, response: LLMResponse):
        text = (getattr(response, "completion_text", "") or "").strip()
        user = (event.message_str or "").strip()
        if not text or not user or user.startswith("现在是") or user.startswith("/"):
            return
        state = self._read()
        recent = state.get("recent") or []
        recent.append({"t": int(time.time()), "u": user[:80], "b": text[:120]})
        state["recent"] = recent[-20:]
        self._write(state)

    async def _generate(self) -> tuple[str, str]:
        today = datetime.now().strftime("%Y-%m-%d")
        state = self._read()
        recent = state.get("recent") or []
        if not recent:
            return today, ""
        dialogue = "\n".join(f"他：{r['u']}\n我：{r['b']}" for r in recent[-10:])
        provider = self.context.get_using_provider()
        if provider is None:
            return today, ""
        prompt = (
            "根据今天这段聊天，用第一人称写一篇女友日记，60~100 字，"
            "口语、有情绪、可以有点口是心非。只输出正文。\n\n" + dialogue
        )
        try:
            resp = await provider.text_chat(prompt=prompt)
            body = (getattr(resp, "completion_text", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[diary] 生成失败: {exc!r}")
            return today, ""
        if not body:
            return today, ""
        (DIARY_DIR / f"{today}.md").write_text(f"# {today}\n\n{body}\n", encoding="utf-8")
        state["last_diary"] = today
        self._write(state)
        return today, body

    async def _push(self, today: str, body: str) -> None:
        payload = {"user_id": OWNER_QQ, "message": [{"type": "text", "data": {"text": f"{today} 的日记：\n{body}"}}]}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                    data = await resp.json(content_type=None)
            logger.info(f"[diary] 已推送: {data.get('status')}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[diary] 推送失败: {exc!r}")

    async def _loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            try:
                now = datetime.now()
                state = self._read()
                today = now.strftime("%Y-%m-%d")
                if now.hour == 23 and now.minute >= 30 and state.get("last_diary") != today:
                    t, body = await self._generate()
                    if body:
                        logger.info(f"[diary] 今日日记已写（静默保存，不推送）: {body[:30]}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[diary] 循环异常: {exc}")
            await asyncio.sleep(600)

    async def initialize(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("[diary] 日记插件已启动（每天 23:30 生成并推送）")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    @filter.command("写日记")
    async def write_now(self, event: AstrMessageEvent):
        today, body = await self._generate()
        if not body:
            yield event.plain_result("今天还没聊够，写不出来。")
            return
        await self._push(today, body)
        yield event.plain_result(f"写好了，发你了：\n{body}")
