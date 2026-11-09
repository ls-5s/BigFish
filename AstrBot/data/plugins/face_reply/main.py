"""纯表情/贴纸回应。

只处理「只有表情、没有文字和图片」的消息：
- 60% 概率回一句短的（大肥鱼语气）
- 其余放行（不回复）

带图片的消息不拦，交给多模态模型看图。
"""

import random

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Face, Image, Plain
from astrbot.api.star import Context, Star

REPLIES = ["？", "干嘛", "发这个干嘛", "……", "幼稚", "看得我一脸问号", "哦。"]


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_face(self, event: AstrMessageEvent):
        message = getattr(getattr(event, "message_obj", None), "message", None) or []
        comps = list(message)
        if not comps:
            return
        has_face = any(isinstance(c, Face) for c in comps)
        has_meaningful = any(isinstance(c, (Plain, Image)) for c in comps)
        text = (event.message_str or "").strip()
        if not has_face or has_meaningful or text:
            return
        if random.random() < 0.6:
            event.stop_event()
            yield event.plain_result(random.choice(REPLIES))
