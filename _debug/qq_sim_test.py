"""模拟 OneBot 客户端向 AstrBot 注入私聊事件，走完整回复链路。"""
import asyncio
import json
import time
import uuid

import websockets

URI = "ws://127.0.0.1:6199/ws"
SELF_ID = 999999          # 用一个独立的 self_id，避免影响 SnowLuma 的真实连接
USER_ID = 2408224899      # 主人号
NICK = "李洋"

REPLIES = []


async def handler(ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if "action" in msg:
            action = msg["action"]
            params = msg.get("params") or {}
            echo = msg.get("echo")
            if action in ("send_msg", "send_private_msg", "send_group_msg"):
                segs = params.get("message")
                text = ""
                if isinstance(segs, str):
                    text = segs
                elif isinstance(segs, list):
                    for s in segs:
                        if s.get("type") == "text":
                            text += s.get("data", {}).get("text", "")
                        elif s.get("type") == "image":
                            text += "[图片]"
                        elif s.get("type") == "record":
                            text += "[语音]"
                        elif s.get("type") == "face":
                            text += "[表情]"
                REPLIES.append((action, text))
                print(f"REPLY[{action}]: {text}", flush=True)
                await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": 1}, "echo": echo}))
            else:
                await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": None, "echo": echo}))


def event(text: str, mid: int) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": mid,
        "user_id": USER_ID,
        "self_id": SELF_ID,
        "time": int(time.time()),
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": USER_ID, "nickname": NICK},
    }


async def main():
    async with websockets.connect(
        URI,
        additional_headers={"X-Self-ID": str(SELF_ID), "X-Client-Role": "Universal"},
        max_size=None,
    ) as ws:
        task = asyncio.create_task(handler(ws))
        await asyncio.sleep(1.5)
        texts = ["/reset", "在吗", "今天好累", "还记得我上次说面试的事吗"]
        for i, t in enumerate(texts):
            REPLIES.clear()
            print(f"\n>>> 发送: {t}", flush=True)
            await ws.send(json.dumps(event(t, 1000 + i), ensure_ascii=False))
            await asyncio.sleep(12 if t != "/reset" else 4)
            if not REPLIES:
                print("(无回复)", flush=True)
        task.cancel()


asyncio.run(main())
