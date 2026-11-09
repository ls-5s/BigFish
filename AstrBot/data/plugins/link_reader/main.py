"""链接补全：消息里出现 B 站链接时，抓标题/简介塞进上下文，避免它装看不见。"""

import re

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

URL = re.compile(r"https?://[^\s，。！？、]+")
BV = re.compile(r"(BV[0-9A-Za-z]{10})")


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def _bili_meta(self, bvid: str) -> str:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json(content_type=None)
        if data.get("code") != 0:
            return ""
        d = data.get("data") or {}
        title = (d.get("title") or "").strip()
        desc = (d.get("desc") or "").strip().replace("\n", " ")[:80]
        owner = ((d.get("owner") or {}).get("name") or "").strip()
        return f"【链接内容】B站视频《{title}》UP:{owner} 简介:{desc}"

    async def _subtitle(self, bvid: str) -> str:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": f"https://www.bilibili.com/video/{bvid}"}
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}", headers=headers) as resp:
                    pages = await resp.json(content_type=None)
                cid = ((pages.get("data") or [{}])[0] or {}).get("cid")
                if not cid:
                    return ""
                url = f"https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}"
                async with session.get(url, headers=headers) as resp:
                    info = await resp.json(content_type=None)
                subs = (((info.get("data") or {}).get("subtitle") or {}).get("subtitles") or [])
                if not subs:
                    return ""
                sub_url = subs[0].get("subtitle_url") or ""
                if sub_url.startswith("//"):
                    sub_url = "https:" + sub_url
                if not sub_url:
                    return ""
                async with session.get(sub_url, headers=headers) as resp:
                    data = await resp.json(content_type=None)
                body = (data.get("body") or [])
                text = "".join((x.get("content") or "") for x in body)
                text = re.sub(r"\s+", " ", text).strip()
                return text[:1200]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[link_reader] 字幕失败: {exc!r}")
            return ""

    @filter.on_llm_request()
    async def add_link_context(self, event: AstrMessageEvent, req: ProviderRequest):
        text = event.message_str or ""
        if "b23.tv" not in text and "bilibili.com" not in text:
            return
        bvid = ""
        m = BV.search(text)
        if m:
            bvid = m.group(1)
        else:
            for u in URL.findall(text):
                if "b23.tv" in u:
                    try:
                        timeout = aiohttp.ClientTimeout(total=10)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(u, allow_redirects=True) as resp:
                                final = str(resp.url)
                        m2 = BV.search(final)
                        if m2:
                            bvid = m2.group(1)
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[link_reader] 展开失败: {exc!r}")
        if not bvid:
            return
        try:
            meta = await self._bili_meta(bvid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[link_reader] 取标题失败: {exc!r}")
            return
        sub = await self._subtitle(bvid)
        if sub:
            meta += "\n【字幕节选】" + sub
        if meta:
            req.prompt = (req.prompt or "") + "\n" + meta
            logger.info(f"[link_reader] 已补链接信息 {bvid}")

    async def initialize(self) -> None:
        logger.info("[link_reader] B 站链接补全已启动")
