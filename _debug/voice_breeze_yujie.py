import asyncio, json, subprocess, tempfile, uuid
from pathlib import Path

import aiohttp
import edge_tts

TEXT = "行了，别磨蹭。把话说完，我听着呢。"
DESIGNS = [
    ("B1 御姐低音：冷一点、尾音下沉", "成熟女性，低沉御姐音，气息偏冷，语速偏慢，尾音下沉，带一点慵懒"),
    ("B2 御姐沙哑：慵懒一点", "成熟女性，略沙哑，慵懒，咬字清晰，中低音，像在耳边说话"),
]
FFMPEG = r"C:\Users\86177\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe"
OUT = Path(r"C:\Users\86177\Desktop\dafyue\.tmp\dy_voice")


async def breeze_speech(desc: str, out_wav: Path, seed: int):
    payload = {"input": TEXT, "instructions": desc, "cfg_scale": 4, "seed": seed, "response_format": "pcm"}
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post("http://127.0.0.1:8137/v1/audio/speech", json=payload) as r:
            pcm = await r.read()
    import wave
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(pcm)


async def post(session, payload):
    async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as r:
        return await r.json(content_type=None)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, (label, desc) in enumerate(DESIGNS):
            await post(session, {"user_id": 2408224899, "message": [{"type": "text", "data": {"text": label}}]})
            wav = OUT / f"breeze{i}.wav"
            await breeze_speech(desc, wav, seed=1000 + i)
            await post(session, {"user_id": 2408224899, "message": [{"type": "record", "data": {"file": "file:///" + str(wav).replace("\\", "/")}}]})
            await asyncio.sleep(1)
    print("sent breeze samples")


asyncio.run(main())
