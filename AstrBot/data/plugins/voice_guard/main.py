"""多段语音修正。

分段回复 + TTS 会把一条回复拆成多条 [语音]。
这里在发送前检查：如果消息链里有 2 条以上 Record，
就把它们还原成文字气泡（Record.text 是 TTS 前的原文），
保证一条回复最多一条语音。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
import re

from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    MARKER = re.compile(r"&{1,2}[A-Za-z0-9_\-]{1,32}&{1,2}")
    ENTITY = re.compile(r"&[A-Za-z]{2,10};")

    PAREN = re.compile(r"^[（(].{0,40}[）)]$")
    REPLACEMENTS = ["在呢", "怎么了", "我在听", "你说"]
    SCOLD = re.compile(r"([两三四五六七八九十几\d]+遍|说过几回|又说|又问|老问|重复|同一句|问这么多|杠上|刚说(过)?一?回|几回了)")

    @filter.on_llm_response()
    async def cap_lines(self, event: AstrMessageEvent, response):
        """把回复压到最多 3 行，避免气泡刷屏。"""
        text = (getattr(response, "completion_text", "") or "").strip()
        logger.info(f"[voice_guard] llm len={len(text)} text={text[:40]!r}")
        if not text:
            return
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        kept = [ln for ln in lines if not self.SCOLD.search(ln)]
        if kept:
            lines = kept
        if len(lines) > 3:
            lines = lines[:3]
            response.completion_text = "\n".join(lines)
            logger.info("[voice_guard] 回复超过 3 行，已截断")

    @filter.on_decorating_result()
    async def fix_multi_voice(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.chain:
            return

        # 清理漏出来的表情包标记 / HTML 实体
        cleaned = []
        for comp in result.chain:
            if isinstance(comp, Plain):
                text = self.ENTITY.sub("", self.MARKER.sub("", comp.text or "")).strip()
                if self.PAREN.match(text):
                    continue
                if self.SCOLD.search(text):
                    import random as _r
                    text = _r.choice(self.REPLACEMENTS)
                if text:
                    comp.text = text
                    cleaned.append(comp)
            else:
                cleaned.append(comp)
        if not cleaned:
            cleaned = [Plain("嗯？")]
        result.chain = cleaned
        # 最多 3 条气泡，多出来的并进第 3 条
        plain_idx = [i for i, c in enumerate(result.chain) if isinstance(c, Plain)]
        if len(plain_idx) > 3:
            keep = plain_idx[:2]
            tail_texts = [result.chain[i].text for i in plain_idx[2:] if getattr(result.chain[i], "text", "")]
            merged = "".join(tail_texts)
            new_chain = []
            for i, comp in enumerate(result.chain):
                if i in keep or not isinstance(comp, Plain):
                    new_chain.append(comp)
                elif i == plain_idx[2]:
                    comp.text = merged
                    new_chain.append(comp)
            result.chain = new_chain
            logger.info("[voice_guard] 气泡超过 3 条，已合并")

        # 群聊不发语音（本地文件在群里发不出去），转成文字
        if event.get_group_id() and any(isinstance(c, Record) for c in result.chain):
            result.chain = [Plain(c.text or "嗯") if isinstance(c, Record) else c for c in result.chain]
            logger.info("[voice_guard] 群聊语音转文字")
            return

        records = [c for c in result.chain if isinstance(c, Record)]
        if len(records) < 2:
            return
        new_chain = []
        for comp in result.chain:
            if isinstance(comp, Record):
                text = (getattr(comp, "text", "") or "").strip()
                if text:
                    new_chain.append(Plain(text))
            else:
                new_chain.append(comp)
        result.chain = new_chain
        logger.info(f"[voice_guard] {len(records)} 条语音已退回文字，避免轰炸")
