"""群里让大肥鱼分享 B 站视频。

群友 @ 她 或者喊她名字、并且说了「刷B站 / 来条视频 / 分享个视频」时：
1. 先从 B 站热门里挑一条（避开最近发过的），把封面下到本地；
2. 给这一轮的回复加一句提示，让她自然地"带去看了"；
3. 回复发出去之前，把封面 + 标题/UP/链接追加到消息链末尾。

私聊不处理（那边有 bili_share 的定时分享）。
"""

import json
import random
import re
import time
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Image, Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
STATE = BASE / "state.json"

POPULAR = "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

TRIGGER = re.compile(
    r"(刷.{0,3}[bB]站|[bB]站.{0,6}(视频|刷)|来(一)?[条个].{0,3}视频|分享.{0,6}视频|推荐.{0,5}视频|找.{0,3}[条个]视频)"
)
NAME = re.compile(r"(大肥鱼|肥鱼|小鲸鱼|鲸鱼娘)")

GROUP_COOLDOWN = 240      # 同一个群 4 分钟最多一次
USER_COOLDOWN = 900       # 同一个人 15 分钟最多一次
MAX_SEEN = 300


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        CACHE.mkdir(parents=True, exist_ok=True)

    # ---------- 状态 ----------
    def _read_state(self) -> dict:
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {"seen": [], "groups": {}, "users": {}}

    def _write_state(self, state: dict) -> None:
        try:
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[group_bili] 状态写不进去: {exc!r}")

    def _cooling(self, state: dict, group_id: str, user_id: str) -> str:
        now = time.time()
        g = state.get("groups") or {}
        u = state.get("users") or {}
        if now - float(g.get(group_id, 0)) < GROUP_COOLDOWN:
            return "群里刚发过"
        if now - float(u.get(user_id, 0)) < USER_COOLDOWN:
            return "你今天点过太多次"
        return ""

    # ---------- B 站 ----------
    async def _fetch_popular(self) -> list[dict]:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(POPULAR, headers=HEADERS) as resp:
                data = await resp.json(content_type=None)
        if data.get("code") != 0:
            raise RuntimeError(f"bilibili code={data.get('code')}")
        return data["data"]["list"]

    def _pick(self, items: list[dict], seen: list[str]) -> dict | None:
        pool = []
        for v in items:
            bvid = v.get("bvid")
            if not bvid or bvid in seen:
                continue
            try:
                dur = int(v.get("duration") or 0)
            except Exception:
                dur = 0
            if dur < 40 or dur > 1800:
                continue
            if not v.get("pic"):
                continue
            pool.append(v)
        return random.choice(pool) if pool else None

    async def _download_cover(self, video: dict) -> str:
        url = video.get("pic") or ""
        if url.startswith("//"):
            url = "https:" + url
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / f"{video['bvid']}.jpg"
        if path.exists() and path.stat().st_size > 1024:
            return str(path)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status != 200:
                    return ""
                blob = await resp.read()
        if len(blob) < 1024:
            return ""
        path.write_bytes(blob)
        return str(path)

    async def _prepare(self, state: dict) -> dict | None:
        try:
            items = await self._fetch_popular()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[group_bili] 拉热门失败: {exc!r}")
            return None
        video = self._pick(items, state.get("seen") or [])
        if not video:
            return None
        cover = await self._download_cover(video)
        if not cover:
            return None
        stat = video.get("stat") or {}
        return {
            "bvid": video["bvid"],
            "title": (video.get("title") or "").strip(),
            "author": ((video.get("owner") or {}).get("name") or "").strip(),
            "url": f"https://b23.tv/{video['bvid']}",
            "cover": cover,
            "view": stat.get("view") or 0,
        }

    # ---------- 判定 ----------
    def _at_me(self, event: AstrMessageEvent) -> bool:
        me = str(event.get_self_id() or "")
        try:
            comps = event.get_messages() or []
        except Exception:
            comps = []
        for c in comps:
            if isinstance(c, At) and str(getattr(c, "qq", "")) == me:
                return True
        return False

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def catch(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text or not TRIGGER.search(text):
            return
        if not (NAME.search(text) or self._at_me(event)):
            return
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        state = self._read_state()
        why = self._cooling(state, group_id, user_id)
        if why:
            logger.info(f"[group_bili] 跳过：{why}")
            return
        video = await self._prepare(state)
        if not video:
            logger.info("[group_bili] 没挑到合适的视频")
            return
        state.setdefault("groups", {})[group_id] = time.time()
        state.setdefault("users", {})[user_id] = time.time()
        state["seen"] = ((state.get("seen") or []) + [video["bvid"]])[-MAX_SEEN:]
        self._write_state(state)
        event.set_extra("group_bili_video", video)
        logger.info(f"[group_bili] 已备好 {video['bvid']} {video['title'][:30]}")

    @filter.on_llm_request()
    async def hint(self, event: AstrMessageEvent, req: ProviderRequest):
        video = event.get_extra("group_bili_video")
        if not video:
            return
        tip = (
            f"\n【本次任务】对方要你分享 B 站视频，你已经挑好了《{video['title']}》"
            f"（UP：{video['author']}）。用一句话把封面带过去，比如说「就这个，随手刷到的」；"
            "不要说做不到、不要说自己去截图、不要念标题、不要贴链接（封面和链接会自动跟上）。"
        )
        req.prompt = (req.prompt or "") + tip

    @filter.on_decorating_result()
    async def attach(self, event: AstrMessageEvent):
        video = event.get_extra("group_bili_video")
        if not video:
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        try:
            result.chain.append(Image.fromFileSystem(video["cover"]))
            result.chain.append(Plain(
                f"《{video['title']}》 UP：{video['author']}\n{video['url']}"
            ))
            event.set_extra("group_bili_video", None)
            logger.info(f"[group_bili] 已附加封面 {video['bvid']}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[group_bili] 附加封面失败: {exc!r}")

    async def initialize(self) -> None:
        logger.info("[group_bili] 群聊 B 站分享已启动（被点名说「刷B站/来条视频」才触发）")
