import asyncio, json, subprocess, tempfile
from pathlib import Path

import aiohttp
import edge_tts

TEXT = "急什么，我又不会跑。你先把饭吃了，再慢慢跟我说。"
VARIANTS = [
    ("1 御姐轻熟：晓晓 -15Hz，-3%", "zh-CN-XiaoxiaoNeural", "-15Hz", "-3%"),
    ("2 御姐低音：晓晓 -30Hz，-8%", "zh-CN-XiaoxiaoNeural", "-30Hz", "-8%"),
    ("3 御姐镇定：晓晓 -25Hz，+0%", "zh-CN-XiaoxiaoNeural", "-25Hz", "+0%"),
    ("4 台腔温柔：晓萱 -10Hz，-5%", "zh-TW-HsiaoChenNeural", "-10Hz", "-5%"),
]
FFMPEG = r"C:\Users\86177\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe"
OUT = Path(tempfile.gettempdir()) / "voice_yujie"


async def say(text, voice, pitch, rate, idx):
    OUT.mkdir(exist_ok=True)
    mp3 = OUT / f"y{idx}.mp3"
    wav = OUT / f"y{idx}.wav"
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(mp3))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "24000", str(wav)], check=True)
    return wav


async def post(session, payload):
    async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as r:
        return await r.json(content_type=None)


async def main():
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, (label, voice, pitch, rate) in enumerate(VARIANTS):
            await post(session, {"user_id": 2408224899, "message": [{"type": "text", "data": {"text": label}}]})
            wav = await say(TEXT, voice, pitch, rate, i)
            await post(session, {"user_id": 2408224899, "message": [{"type": "record", "data": {"file": "file:///" + str(wav).replace("\\", "/")}}]})
            await asyncio.sleep(1)
    print("sent", len(VARIANTS))


asyncio.run(main())
