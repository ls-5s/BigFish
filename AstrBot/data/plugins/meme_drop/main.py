"""情绪表情：按当前情绪标签，偶尔在回复后补一张对应表情包。"""

import asyncio
import json
import random
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star

MEME_ROOT = Path(r"D:\QQBot\AstrBot\data\plugin_data\meme_manager\packs\blue-fat-fish-meme-pack\memes")
OWNER_QQ = 2408224899

# 情绪 -> 表情目录
CATEGORY = {
    "clingy": ["affection", "shy"],
    "jealous": ["angry", "confused"],
    "friendly": ["happy", "greeting"],
    "calm": ["reply", "greeting", "teasing"],
    "annoyed": ["angry", "confused"],
    "cold": ["reply", "sad"],
    "hostile": ["angry"],
    "self_doubt": ["sad"],
    "self_destructive": ["sad"],
}


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._tag = "calm"

    @filter.on_llm_request()
    async def grab_tag(self, event: AstrMessageEvent, req: ProviderRequest):
        # 从注入的提示里找不到标签时留空，交给 emotion_link 的标签
        text = req.system_prompt or ""
        for tag in CATEGORY:
            if f"情绪标签】{tag}" in text or f"情绪标签：{tag}" in text:
                self._tag = tag
                break

    def _pick(self) -> str:
        cats = CATEGORY.get(self._tag, ["reply"])
        files = []
        for c in cats:
            d = MEME_ROOT / c
            if d.exists():
                files.extend(p for p in d.iterdir() if p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg"))
        if not files:
            files = [p for p in MEME_ROOT.rglob("*") if p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg")]
        if not files:
            return ""
        return "file:///" + str(random.choice(files)).replace("\\", "/")

    async def _send(self, file: str) -> None:
        payload = {"user_id": OWNER_QQ, "message": [{"type": "image", "data": {"file": file}}]}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                data = await resp.json(content_type=None)
        logger.info(f"[meme_drop] 表情 {self._tag}: {data.get('status')}")

    @filter.on_llm_response()
    async def maybe_meme(self, event: AstrMessageEvent, response: LLMResponse):
        if event.get_group_id():
            return
        if random.random() > 0.15:
            return
        file = self._pick()
        if not file:
            return
        try:
            await self._send(file)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[meme_drop] 发送失败: {exc!r}")

    async def initialize(self) -> None:
        logger.info("[meme_drop] 情绪表情已启动（约 15% 回复补一张）")
