import asyncio, subprocess, tempfile
from pathlib import Path

import aiohttp
import edge_tts

TEXT = "行了，别磨蹭。把话说完，我听着呢。"
VARIANTS = [
    ("5 更低：晓晓 -40Hz，-8%", "zh-CN-XiaoxiaoNeural", "-40Hz", "-8%"),
    ("6 低沉不拖：晓晓 -35Hz，-3%", "zh-CN-XiaoxiaoNeural", "-35Hz", "-3%"),
    ("7 换底音：晓伊 -30Hz，-5%", "zh-CN-XiaoyiNeural", "-30Hz", "-5%"),
    ("8 温柔御姐：台腔晓萱 -25Hz，-5%", "zh-TW-HsiaoChenNeural", "-25Hz", "-5%"),
]
FFMPEG = r"C:\Users\86177\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe"
OUT = Path(tempfile.gettempdir()) / "voice_yujie2"


async def say(text, voice, pitch, rate, idx):
    OUT.mkdir(exist_ok=True)
    mp3 = OUT / f"z{idx}.mp3"
    wav = OUT / f"z{idx}.wav"
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
