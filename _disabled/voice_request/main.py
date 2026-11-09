"""按需发语音：默认只发文字；他说“发语音/说句话/唱”时才把回复合成语音。"""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path

import aiohttp
import edge_tts

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star

VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "-8%"
PITCH = "-30Hz"
OWNER_QQ = 2408224899
ASK = re.compile(r"(发.{0,4}语音|语音(条|消息)|说句话|说一句|唱(一|个|首)|听听你的?声音)")


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def _say(self, text: str) -> bool:
        ff = shutil.which("ffmpeg")
        if not ff:
            logger.warning("[voice_request] 没有 ffmpeg")
            return False
        tmp = Path(tempfile.gettempdir())
        mp3 = tmp / "voice_request.mp3"
        wav = tmp / "voice_request.wav"
        await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(mp3))
        proc = await asyncio.create_subprocess_exec(
            ff, "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "24000", str(wav),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False
        payload = {"user_id": OWNER_QQ, "message": [{"type": "record", "data": {"file": "file:///" + str(wav).replace("\\", "/")}}]}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                data = await resp.json(content_type=None)
        return data.get("status") == "ok"

    @filter.on_decorating_result()
    async def voice_on_request(self, event: AstrMessageEvent):
        if event.get_group_id():
            return
        if not ASK.search(event.message_str or ""):
            return
        if str(event.get_sender_id()) != str(OWNER_QQ):
            return
        result = event.get_result()
        if result is None:
            return
        text = "".join(c.text for c in result.chain if isinstance(c, Plain) and c.text).strip()
        if not text:
            return
        try:
            ok = await self._say(text)
            logger.info(f"[voice_request] 按需语音: {ok}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[voice_request] 失败: {exc!r}")

    async def initialize(self) -> None:
        logger.info("[voice_request] 按需语音已启动")
