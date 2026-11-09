"""B 站刷视频 + 主动分享。

- 定时（每天 12:40 / 21:40）抓 B 站热门，挑一条没分享过的，用大肥鱼的语气点评后私聊发给主人
- 私聊指令 /刷b站 立即分享一条
- 状态文件 state.json 记录已分享的 bvid，避免重复
"""

import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"

OWNER_QQ = 2408224899
PLATFORM_ID = "qq-main"
SLOTS = [(12, 40), (21, 40)]
API_POPULAR = "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

STYLE_PROMPT = (
    "你是住在主人电脑里的鲸鱼娘「大肥鱼」：嘴馋、爱摸鱼、有点傲娇、说话短。"
    "现在你在刷 B 站，看到一条视频想转给主人。"
    "写 1~2 句话：像随手转发，可以说这视频哪里有意思、或者吐槽 UP 主。"
    "不要提“AI”“推荐算法”，不要列表，不要链接（链接会另外发），总共不超过 40 字。"
)


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None
        self._lock = asyncio.Lock()
        if not STATE_PATH.exists():
            self._write_state({"shared": [], "slots": {}})

    # ---------- 状态 ----------
    def _read_state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"shared": [], "slots": {}}

    def _write_state(self, state: dict) -> None:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- B 站 ----------
    async def _fetch_popular(self) -> list[dict]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_POPULAR, headers=HEADERS) as resp:
                data = await resp.json(content_type=None)
        if data.get("code") != 0:
            raise RuntimeError(f"bilibili code={data.get('code')}")
        return data["data"]["list"]

    def _pick(self, items: list[dict], shared: list[str]) -> dict | None:
        pool = []
        for v in items:
            bvid = v.get("bvid")
            duration = int(v.get("duration") or 0)
            if not bvid or bvid in shared:
                continue
            if duration < 45 or duration > 1800:
                continue
            pool.append(v)
        return random.choice(pool) if pool else None

    async def _comment(self, video: dict) -> str:
        provider = self.context.get_using_provider()
        if provider is None:
            return "这个有点意思，你看看。"
        prompt = (
            f"视频标题：{video.get('title')}\n"
            f"UP主：{video.get('owner', {}).get('name')}\n"
            f"简介：{(video.get('desc') or '')[:120]}\n"
            f"播放：{video.get('stat', {}).get('view')}"
        )
        try:
            resp = await provider.text_chat(prompt=prompt, system_prompt=STYLE_PROMPT)
            text = (getattr(resp, "completion_text", "") or "").strip()
            text = text.replace("\n", " ").strip('"“”「」')
            return text[:80] or "你看看这个。"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[bili_share] 生成点评失败: {exc}")
            return "刚刷到的，感觉你会喜欢。"

    async def _send(self, text: str, bvid: str) -> bool:
        payload = {
            "user_id": OWNER_QQ,
            "message": [{"type": "text", "data": {"text": f"{text}\nhttps://b23.tv/{bvid}"}}],
        }
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                    data = await resp.json(content_type=None)
            if data.get("status") == "ok":
                return True
            logger.warning(f"[bili_share] 发送失败: {data}")
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[bili_share] 发送异常: {exc!r}")
            return False
    async def share_one(self, manual: bool = False) -> tuple[bool, str]:
        async with self._lock:
            state = self._read_state()
            try:
                items = await self._fetch_popular()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[bili_share] 拉取 B 站热门失败: {exc}")
                return False, "B站没连上"
            shared = state.get("shared") or []
            video = self._pick(items, shared)
            if not video:
                return False, "今天热门里没挑到合适的"
            text = await self._comment(video)
            ok = await self._send(text, video["bvid"])
            if ok:
                shared.append(video["bvid"])
                state["shared"] = shared[-200:]
                self._write_state(state)
                logger.info(f"[bili_share] 已分享 {video['bvid']} {video.get('title')}")
            return ok, text

    # ---------- 调度 ----------
    async def _loop(self) -> None:
        await asyncio.sleep(180)
        while True:
            try:
                now = datetime.now()
                state = self._read_state()
                slots = state.get("slots") or {}
                today = now.strftime("%Y-%m-%d")
                for hour, minute in SLOTS:
                    key = f"{today}-{hour:02d}:{minute:02d}"
                    if now.hour == hour and minute <= now.minute < minute + 10 and key not in slots:
                        slots[key] = True
                        state["slots"] = slots
                        self._write_state(state)
                        ok, _ = await self.share_one()
                        if ok:
                            break
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[bili_share] 调度异常: {exc}")
            await asyncio.sleep(60)

    async def initialize(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("[bili_share] 自主刷 B 站已启动（12:40 / 21:40）")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    @filter.command("刷b站")
    async def manual(self, event: AstrMessageEvent):
        ok, text = await self.share_one(manual=True)
        if ok:
            yield event.plain_result("发你了，去看看。")
        else:
            yield event.plain_result(f"没刷成：{text}")
