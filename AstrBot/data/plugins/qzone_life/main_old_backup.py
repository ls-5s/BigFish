import asyncio
import random
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

SYSTEM_PROMPT = (
    "你是傲娇女友「大肥鱼」。写一条要发到 QQ 空间的说说正文："
    "20 字以内，口语、别扭、像真人在发牢骚或分享小事；"
    "只输出正文，不要引号、不要话题标签、不要解释、不要换行。"
)

PLATFORM_ID = "qq-main"
MEME_ROOT = Path(r"D:\QQBot\AstrBot\data\plugin_data\meme_manager\packs\blue-fat-fish-meme-pack\memes")


def _pick_image() -> str:
    if not MEME_ROOT.exists():
        return ""
    files = [p for p in MEME_ROOT.rglob("*") if p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg")]
    if not files:
        return ""
    import random as _r
    p = _r.choice(files)
    return "file:///" + str(p).replace("\\", "/")


class Main(Star):
    """QQ 空间：定时自主发说说 + 聊天指令手动发。"""

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None

    async def initialize(self) -> None:
        self._task = asyncio.create_task(self._auto_loop())
        logger.info("[qzone_life] 自主发说说已启动（约 5~7 小时一条）")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _generate(self, hint: str = "") -> str:
        provider = self.context.get_using_provider()
        if provider is None:
            return ""
        prompt = "写一条今天想发的说说。"
        if hint:
            prompt += f"主题：{hint}"
        try:
            resp = await provider.text_chat(prompt=prompt, system_prompt=SYSTEM_PROMPT)
        except Exception as exc:
            logger.warning(f"[qzone_life] 生成说说失败: {exc}")
            return ""
        text = (getattr(resp, "completion_text", "") or "").strip()
        return text.strip('"“”「」').replace("\n", " ")[:60]

    async def _post(self, text: str) -> bool:
        inst = self.context.get_platform_inst(PLATFORM_ID)
        bot = getattr(inst, "bot", None)
        if bot is None:
            logger.warning("[qzone_life] 平台实例未就绪，跳过本次发说说")
            return False
        payload = {"content": text, "ugc_right": 4}
        if random.random() < 0.7:
            img = _pick_image()
            if img:
                payload["images"] = [img]
        await bot.call_action("send_qzone_msg", **payload)
        return True

    async def _auto_loop(self) -> None:
        # 启动后先等 2 分钟，避免和启动流程抢资源
        await asyncio.sleep(120)
        while True:
            try:
                if random.random() < 0.72:
                    text = await self._generate()
                    if text and await self._post(text):
                        logger.info(f"[qzone_life] 已自主发说说: {text}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[qzone_life] 自主发说说失败: {exc}")
            await asyncio.sleep(random.randint(5, 7) * 3600)

    @filter.command("发说说")
    async def manual_post(self, event: AstrMessageEvent):
        content = event.message_str.replace("/发说说", "", 1).strip()
        text = content or await self._generate()
        if not text:
            yield event.plain_result("想不出来发啥。")
            return
        try:
            payload = {"content": text, "ugc_right": 4}
            img = _pick_image()
            if img:
                payload["images"] = [img]
            await event.bot.call_action("send_qzone_msg", **payload)
            yield event.plain_result("发好了。")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[qzone_life] 手动发说说失败: {exc}")
            yield event.plain_result("发失败了。")
