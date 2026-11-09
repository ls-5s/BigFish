import asyncio
import random
import uuid
from pathlib import Path

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

TRIGGERS = (
    "自拍",
    "照片",
    "看看你",
    "长什么样",
    "发张图",
    "发个图",
    "来张图",
    "图片",
)

CAPTIONS = [
    "哼，就、就这一次哦，别得寸进尺。",
    "……给你看就是了，不许一直盯着看！",
    "才不是特意拍给你的，刚好有而已。",
    "笨蛋，看到就快点说句话啊。",
    "就这表情……还行吧？别、别误会。",
    "下次可没有这么容易了。",
]

API_URL = "https://nekos.best/api/v2/neko"
CACHE_SIZE = 3
USER_AGENT = "AstrBot/tsundere-selfie"

CACHE_DIR = Path(__file__).resolve().parent / "cache"


class Main(Star):
    """傲娇女友自拍插件：命中关键词时发送本机缓存的二次元图片。"""

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._lock = asyncio.Lock()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def _download_one(self) -> bool:
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(API_URL, headers={"User-Agent": USER_AGENT}) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                url = data["results"][0]["url"]
                async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                    resp.raise_for_status()
                    content = await resp.read()
                if len(content) < 1024:
                    return False
                suffix = Path(url).suffix or ".png"
                (CACHE_DIR / f"{uuid.uuid4().hex}{suffix}").write_bytes(content)
                return True
        except Exception as exc:
            logger.warning(f"[tsundere_selfie] 预缓存图片失败: {exc}")
            return False

    def _cached_files(self) -> list[Path]:
        return sorted(
            p
            for p in CACHE_DIR.glob("*")
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        )

    async def _refill(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            missing = CACHE_SIZE - len(self._cached_files())
            for _ in range(max(0, missing)):
                if not await self._download_one():
                    break

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_selfie_request(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text or not any(key in text for key in TRIGGERS):
            return

        files = self._cached_files()
        if not files:
            await self._refill()
            files = self._cached_files()
        if not files:
            # 预缓存失败就退回在线 URL，交给适配器下载
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(API_URL, headers={"User-Agent": USER_AGENT}) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                image = Comp.Image.fromURL(data["results"][0]["url"])
            except Exception as exc:
                logger.warning(f"[tsundere_selfie] 获取图片失败: {exc}")
                return
        else:
            image = Comp.Image.fromFileSystem(random.choice(files))

        asyncio.create_task(self._refill())
        caption = random.choice(CAPTIONS)
        event.stop_event()
        yield event.chain_result([image, Comp.Plain("\n" + caption)])
