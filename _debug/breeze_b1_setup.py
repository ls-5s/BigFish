import json
import time
import uuid
import wave
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8137"
TEXT = "行了，别磨蹭。把话说完，我听着呢。"
REF = Path(r"C:\Users\86177\Desktop\dafyue\.tmp\dy_voice\breeze0.wav")
NAME = "b1yujie"


def save_voice():
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("ref_text", TEXT), ("name", NAME), ("description", "低沉御姐，气息偏冷，语速偏慢，尾音下沉")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"ref_audio\"; filename=\"ref.wav\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode()
    body = b"".join(parts) + head + REF.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    r = requests.post(BASE + "/v1/voices", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=300)
    print("save:", r.status_code, r.text[:200])


def synth(text, payload_extra):
    payload = {"input": text, "response_format": "pcm", **payload_extra}
    t0 = time.time()
    r = requests.post(BASE + "/v1/audio/speech", json=payload, timeout=300)
    dt = time.time() - t0
    print("synth:", r.status_code, "bytes=", len(r.content), "secs=", round(dt, 1), "extra=", payload_extra)
    return r.content, dt


save_voice()

# measure three cases
short = "在的，你回来了？"
mid = "行，那我今晚不黏你，你早点睡，明天上班别迟到。"
for label, txt, extra in [
    ("voice-id short", short, {"voice": NAME}),
    ("voice-id mid", mid, {"voice": NAME}),
    ("instructions short", short, {"instructions": "低沉御姐，气息偏冷，语速偏慢，尾音下沉"}),
]:
    pcm, dt = synth(txt, extra)
    out = Path(r"C:\Users\86177\Desktop\dafyue\.tmp\dy_voice") / f"test_{label.replace(' ', '_')}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(pcm)
    print("saved", out.name)
