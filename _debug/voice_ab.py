import asyncio, json, os, subprocess, tempfile
from pathlib import Path

import aiohttp
import edge_tts

TEXT = "你今天不是说想吃番茄牛肉面吗？我记着呢，不许放香菜。"
VARIANTS = [
    ("A 现在这版：+8% 语速，+18Hz", "+8%", "+18Hz"),
    ("B 自然一点：+0% 语速，+8Hz", "+0%", "+8Hz"),
    ("C 活泼一点：+12% 语速，+25Hz", "+12%", "+25Hz"),
    ("D 温柔一点：-5% 语速，+10Hz", "-5%", "+10Hz"),
]
FFMPEG = r"C:\Users\86177\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe"
OUT = Path(tempfile.gettempdir()) / "voice_ab"


async def say(text: str, rate: str, pitch: str, idx: int) -> Path:
    OUT.mkdir(exist_ok=True)
    mp3 = OUT / f"v{idx}.mp3"
    wav = OUT / f"v{idx}.wav"
    await edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate=rate, pitch=pitch).save(str(mp3))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "24000", str(wav)], check=True)
    return wav


async def post(session, payload):
    async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as r:
        return await r.json(content_type=None)


async def main():
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, (label, rate, pitch) in enumerate(VARIANTS):
            await post(session, {"user_id": 2408224899, "message": [{"type": "text", "data": {"text": label}}]})
            wav = await say(TEXT, rate, pitch, i)
            await post(session, {"user_id": 2408224899, "message": [{"type": "record", "data": {"file": "file:///" + str(wav).replace("\\", "/")}}]})
            await asyncio.sleep(1)
    print("sent", len(VARIANTS))


asyncio.run(main())
