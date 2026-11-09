"""抖音刷视频 + 主动分享（她自己的节奏，不定时）。

- 没有固定时间表：每 14~30 分钟冒一个「要不要刷会儿」的念头，按当时心情、空闲程度、
  时间段掷骰子；想刷了就拉推荐流，挑一条，用大肥鱼的语气点评后私聊发：
  一句话 + 封面 + 标题/作者/链接
- 也会在聊天中自己调用 share_douyin_video（比如主人说“好无聊”“去刷会儿抖音”）
- 私聊指令 /刷抖音 是主人的强制入口
- state.json 记录已分享的 aweme_id / 上次分享时间 / 今日条数；cache/ 存封面

数据源是抖音 App 端推荐流接口（aweme.snssdk.com），不需要登录、不需要签名。
"""

import asyncio
import base64
import io
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"
CACHE = BASE / "cache"

OWNER_QQ = 2408224899

# —— 自主性参数：她自己的节奏，不是时间表 ——
QUIET = (2, 8)                  # 02:00–08:00 不刷（她也要睡）
CHECK_GAP = (14 * 60, 30 * 60)  # 每 14–30 分钟冒一次「要不要刷」的念头
MIN_GAP = 50 * 60               # 刚发过一条，至少隔 50 分钟才会再刷
BASE_URGE = 0.055               # 每个念头的基准概率，再按时间和空闲程度加权
SOFT_DAILY = 5                  # 一天超过 5 条后，念头明显变淡（不是硬上限）

FEED_URL = "https://aweme.snssdk.com/aweme/v1/feed/"
FEED_PARAMS = {
    "count": "12",
    "device_platform": "android",
    "version_code": "300904",
    "version_name": "30.9.4",
    "aid": "1128",
    "channel": "googleplay",
    "device_type": "Pixel 5",
    "os_version": "12",
    "ssmix": "a",
    "region": "CN",
    "carrier_region": "CN",
}
HEADERS = {
    "User-Agent": "com.ss.android.ugc.aweme/300904 (Linux; U; Android 12; zh_CN; Pixel 5)",
    "Accept": "application/json",
}

# 不转的内容：时政/新闻/长剧/带货/直播切片之类
SKIP_WORDS = re.compile(
    r"(新闻联播|央视|外交部|国防部|军事|导弹|战争|时政|省委|市委|政府|"
    r"直播回放|直播切片|带货|小黄车|下单|优惠券|广告|"
    r"全集|第\d+集|大结局|完整版|电影解说)"
)
TAG = re.compile(r"[#＃][^#＃\s]{1,30}")

STYLE_PROMPT = (
    "你是住在主人电脑里的鲸鱼娘「大肥鱼」：嘴馋、爱摸鱼、有点傲娇、说话短。"
    "现在你在刷抖音，刷到一条想转给主人。"
    "写 1~2 句话：像随手转发，可以说这视频哪里好笑/好看/离谱，或者吐槽一下博主。"
    "不要提“AI”“推荐算法”“本视频”，不要列表，不要念标题，不要贴链接"
    "（链接和封面会另外发），总共不超过 40 字。"
)

MIN_MS = 6_000
MAX_MS = 180_000
MIN_DIGG = 2_000
MAX_SEEN = 400


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None
        self._lock = asyncio.Lock()
        self._last_user_ts = 0.0
        CACHE.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            self._write_state(self._default_state())
        else:
            self._last_user_ts = float(self._read_state().get("last_user_ts") or 0)

    @staticmethod
    def _default_state() -> dict:
        return {
            "seen": [],
            "last_share": 0.0,
            "sent_day": "",
            "sent_today": 0,
            "next_check": 0.0,
            "last_user_ts": 0.0,
        }

    # ---------- 状态 ----------
    def _read_state(self) -> dict:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        merged = self._default_state()
        if isinstance(state, dict):
            merged.update(state)
        return merged

    def _write_state(self, state: dict) -> None:
        try:
            STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 状态写不进去: {exc!r}")

    # ---------- 抖音 ----------
    async def _fetch_feed(self) -> list[dict]:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                FEED_URL, params=FEED_PARAMS, headers=HEADERS
            ) as resp:
                data = await resp.json(content_type=None)
        if data.get("status_code") not in (0, None):
            raise RuntimeError(f"douyin status_code={data.get('status_code')}")
        return data.get("aweme_list") or []

    def _eligible(self, aweme: dict, seen: set[str]) -> bool:
        aweme_id = str(aweme.get("aweme_id") or "")
        if not aweme_id or aweme_id in seen:
            return False
        if aweme.get("is_ads") or aweme.get("aweme_type") != 0:
            return False
        if aweme.get("images"):
            return False
        video = aweme.get("video") or {}
        cover = ((video.get("cover") or {}).get("url_list") or [None])[0]
        if not cover:
            return False
        try:
            duration = int(video.get("duration") or aweme.get("duration") or 0)
        except Exception:
            duration = 0
        if duration < MIN_MS or duration > MAX_MS:
            return False
        desc = str(aweme.get("desc") or "").strip()
        if len(TAG.sub("", desc).strip()) < 2:
            return False
        try:
            digg = int((aweme.get("statistics") or {}).get("digg_count") or 0)
        except Exception:
            digg = 0
        if digg < MIN_DIGG:
            return False
        if SKIP_WORDS.search(desc):
            return False
        author = str((aweme.get("author") or {}).get("nickname") or "")
        if not author:
            return False
        return True

    def _pick(self, items: list[dict], seen: list[str]) -> dict | None:
        seen_set = {str(x) for x in seen}
        pool = [a for a in items if self._eligible(a, seen_set)]
        if not pool:
            return None
        # 点赞多的优先，但只在最高的 6 条里随机，避免每次都推同一批爆款
        pool.sort(key=lambda a: int((a.get("statistics") or {}).get("digg_count") or 0))
        top = pool[max(0, len(pool) - 6):]
        return random.choice(top)

    async def _download_cover(self, aweme: dict) -> bytes:
        url = (((aweme.get("video") or {}).get("cover") or {}).get("url_list") or [""])[0]
        if not url:
            return b""
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status != 200:
                    logger.warning(f"[douyin_share] 封面下载 HTTP {resp.status}")
                    return b""
                return await resp.read()

    @staticmethod
    def _to_jpeg(blob: bytes) -> bytes:
        """webp → jpg，QQ 那边最稳。失败就原样发。"""
        if not blob:
            return b""
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(blob))
            if image.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image.convert("RGBA"), mask=image.convert("RGBA").split()[-1])
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            if image.width > 720:
                ratio = 720 / image.width
                image = image.resize((720, max(1, int(image.height * ratio))))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=86)
            return out.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 封面转码失败，发原图: {exc!r}")
            return blob

    def _cache_cover(self, aweme_id: str, blob: bytes) -> None:
        if not blob:
            return
        try:
            (CACHE / f"{aweme_id}.jpg").write_bytes(blob)
            files = sorted(CACHE.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
            for old in files[:-120]:
                old.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 封面缓存失败: {exc!r}")

    async def _comment(self, aweme: dict) -> str:
        provider = self.context.get_using_provider()
        if provider is None:
            return "这个有点意思，你看看。"
        desc = str(aweme.get("desc") or "").strip()
        stat = aweme.get("statistics") or {}
        prompt = (
            f"视频文案：{desc[:200]}\n"
            f"博主：{(aweme.get('author') or {}).get('nickname')}\n"
            f"点赞：{stat.get('digg_count')}　评论：{stat.get('comment_count')}\n"
            f"时长：{int((aweme.get('video') or {}).get('duration') or 0) // 1000} 秒"
        )
        try:
            resp = await provider.text_chat(prompt=prompt, system_prompt=STYLE_PROMPT)
            text = (getattr(resp, "completion_text", "") or "").strip()
            text = text.replace("\n", " ").strip('"“”「」')
            return text[:80] or "刚刷到的，你看看。"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 生成点评失败: {exc}")
            return "刚刷到的，感觉你会喜欢。"

    # ---------- 发送 ----------
    @staticmethod
    def _ok(data: dict) -> bool:
        return data.get("status") == "ok" or (data.get("retcode") == 0 and not data.get("status"))

    async def _post(self, session: aiohttp.ClientSession, message: list) -> bool:
        try:
            async with session.post(
                "http://127.0.0.1:3000/send_private_msg",
                json={"user_id": OWNER_QQ, "message": message},
            ) as resp:
                data = await resp.json(content_type=None)
            if self._ok(data):
                return True
            logger.warning(f"[douyin_share] 发送失败: {data}")
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 发送异常: {exc!r}")
            return False

    async def _send(self, comment: str, caption: str, cover: bytes) -> bool:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if not await self._post(
                session, [{"type": "text", "data": {"text": comment}}]
            ):
                return False
            pieces: list[dict] = []
            if cover:
                pieces.append(
                    {
                        "type": "image",
                        "data": {
                            "file": "base64://" + base64.b64encode(cover).decode(),
                        },
                    }
                )
            pieces.append({"type": "text", "data": {"text": caption}})
            if await self._post(session, pieces):
                return True
            # 图发不出去就退回纯文字，别整条丢了
            logger.warning("[douyin_share] 图片消息失败，退回纯文字")
            await asyncio.sleep(0.8)
            return await self._post(
                session, [{"type": "text", "data": {"text": caption}}]
            )

    async def share_one(self, manual: bool = False) -> tuple[bool, str]:
        async with self._lock:
            state = self._read_state()
            items: list[dict] = []
            merged: dict[str, dict] = {}
            for _ in range(2):
                try:
                    for aweme in await self._fetch_feed():
                        merged[str(aweme.get("aweme_id") or "")] = aweme
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[douyin_share] 拉推荐流失败: {exc!r}")
            items = [a for k, a in merged.items() if k]
            if not items:
                return False, "抖音没连上"
            aweme = self._pick(items, state.get("seen") or [])
            if not aweme:
                return False, "今天没刷到什么合适的"
            cover = self._to_jpeg(await self._download_cover(aweme))
            self._cache_cover(str(aweme["aweme_id"]), cover)
            comment = await self._comment(aweme)
            desc = str(aweme.get("desc") or "").strip()
            desc = TAG.sub("", desc).strip() or desc
            desc = desc[:60]
            author = (aweme.get("author") or {}).get("nickname") or ""
            link = f"https://www.douyin.com/video/{aweme['aweme_id']}"
            caption = f"《{desc}》 @{author}\n{link}"
            ok = await self._send(comment, caption, cover)
            if ok:
                state["seen"] = ((state.get("seen") or []) + [str(aweme["aweme_id"])])[-MAX_SEEN:]
                state["last_share"] = time.time()
                self._bump_today(state)
                self._write_state(state)
                logger.info(
                    f"[douyin_share] 已分享 {aweme['aweme_id']} {desc[:30]}"
                )
            return ok, comment

    def _bump_today(self, state: dict) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("sent_day") != today:
            state["sent_day"] = today
            state["sent_today"] = 0
        state["sent_today"] = int(state.get("sent_today") or 0) + 1

    # ---------- 她自己的节奏 ----------
    @staticmethod
    def _quiet_hour(hour: int) -> bool:
        start, end = QUIET
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    @staticmethod
    def _tod_factor(hour: int) -> float:
        if 8 <= hour < 11:
            return 0.8
        if 11 <= hour < 14:
            return 1.2
        if 14 <= hour < 18:
            return 0.9
        if 18 <= hour < 23:
            return 1.4
        return 0.7

    def _urge(self, now: float, state: dict) -> float:
        """这一刻「想刷」的概率；0 表示现在不刷。"""
        hour = datetime.now().hour
        if self._quiet_hour(hour):
            return 0.0
        if now - float(state.get("last_share") or 0) < MIN_GAP:
            return 0.0
        if self._last_user_ts:
            idle_h = (now - self._last_user_ts) / 3600
        else:
            idle_h = 3.0
        if idle_h < 0.3:
            idle_factor = 0.25      # 正聊着，顾不上
        elif idle_h < 1:
            idle_factor = 0.7
        elif idle_h < 3:
            idle_factor = 1.0
        else:
            idle_factor = 1.3       # 主人半天没理她，自己找点乐子
        p = BASE_URGE * self._tod_factor(hour) * idle_factor
        sent_today = int(state.get("sent_today") or 0)
        if sent_today >= SOFT_DAILY + 3:
            return 0.0
        if sent_today >= SOFT_DAILY:
            p *= 0.2
        return p

    async def _impulse(self) -> None:
        now = time.time()
        async with self._lock:
            state = self._read_state()
            today = datetime.now().strftime("%Y-%m-%d")
            if state.get("sent_day") != today:
                state["sent_day"] = today
                state["sent_today"] = 0
            if now < float(state.get("next_check") or 0):
                return
            state["next_check"] = now + random.randint(*CHECK_GAP)
            if self._last_user_ts:
                state["last_user_ts"] = self._last_user_ts
            self._write_state(state)
            p = self._urge(now, state)
        if p <= 0 or random.random() >= p:
            return
        idle_h = (now - self._last_user_ts) / 3600 if self._last_user_ts else 3.0
        logger.info(f"[douyin_share] 自己想刷了（空闲 {idle_h:.1f}h，概率 {p:.3f}）")
        ok, _ = await self.share_one()
        if not ok:
            logger.info("[douyin_share] 刷了但没转成")

    async def _loop(self) -> None:
        await asyncio.sleep(90)
        while True:
            try:
                await self._impulse()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[douyin_share] 念头处理异常: {exc!r}")
            await asyncio.sleep(45)

    async def initialize(self) -> None:
        state = self._read_state()
        now = time.time()
        if float(state.get("next_check") or 0) <= now:
            state["next_check"] = now + random.randint(10 * 60, 25 * 60)
            self._write_state(state)
        self._task = asyncio.create_task(self._loop())
        logger.info("[douyin_share] 抖音自主刷已启动（想刷就刷，没有时间表）")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def _note_activity(self, event: AstrMessageEvent):
        try:
            if str(event.get_sender_id()) != str(OWNER_QQ):
                return
            self._last_user_ts = time.time()
        except Exception:
            pass

    @filter.llm_tool(name="share_douyin_video")
    async def share_douyin_tool(self, event: AstrMessageEvent, reason: str = ""):
        '''刷一会儿抖音，挑一条视频发给主人。

        你自己突然想刷了，或者主人说「去刷会儿抖音」「刷个视频」「好无聊」时调用。
        刚发过一条就先别连着发；别人（不是主人）让你刷，不要调用。

        Args:
            reason(string): 为什么想刷，几个字，比如「自己手痒」「主人让刷」
        '''
        try:
            if event.get_group_id():
                return "群里不刷。"
            if str(event.get_sender_id()) != str(OWNER_QQ):
                return "只有主人能让你刷。"
            state = self._read_state()
            if time.time() - float(state.get("last_share") or 0) < 20 * 60:
                return "刚发过一条，先不刷了。跟主人说等会儿。"
            ok, text = await self.share_one()
            if ok:
                return "已经刷好并发给主人了（点评、封面、链接都发了）。随口提一句就行，别复述标题和链接。"
            return f"这次没刷成：{text}。跟主人说一声。"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[douyin_share] 工具调用异常: {exc!r}")
            return "刷失败了，跟主人说一声。"

    @filter.command("刷抖音")
    async def manual(self, event: AstrMessageEvent):
        if str(event.get_sender_id()) != str(OWNER_QQ):
            yield event.plain_result("这个只给主人刷。")
            return
        ok, text = await self.share_one(manual=True)
        if ok:
            yield event.plain_result("发你了，去看看。")
        else:
            yield event.plain_result(f"没刷成：{text}")
