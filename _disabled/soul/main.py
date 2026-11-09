"""情绪系统 v3 —— 好感 / 心情 / 精力 / 害羞 / 委屈。

- 规则 + LLM 双通道评估情绪变化
- 状态注入 system prompt，并给出情绪标签供表情包联动
- 每天 23:30 写日记并主动推送
- /心情 查看进度条状态
"""

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star

BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"
DIARY_DIR = BASE / "diary"

HOUR = 3600
DEFAULTS = {
    "affection": 68.0,
    "mood": 62.0,
    "energy": 75.0,
    "shy": 0.0,
    "sulk": 0.0,
    "last_decay": 0.0,
    "last_user_msg": 0.0,
    "recent": [],
    "last_diary": "",
}

PRAISE = ("好看", "可爱", "喜欢", "想你", "厉害", "乖", "聪明", "漂亮", "棒", "爱你")
HARSH = ("滚", "烦", "闭嘴", "丑", "笨死", "讨厌", "别烦我", "无语", "受不了你")
FLIRT = ("抱抱", "亲亲", "老婆", "宝贝", "亲一个", "贴贴", "摸摸")

APPRAISE_PROMPT = (
    "你是情绪分析器。根据下面这轮对话，判断女方「大肥鱼」的情绪增量。"
    "只输出 JSON，不要解释、不要代码块，格式："
    '{"affection": 0, "mood": 0, "energy": 0, "shy": 0, "sulk": 0} '
    "各字段范围 -5..8。被夸/被撩：好感心情害羞上升；被凶/被冷落：好感下降、委屈上升；"
    "聊得久：精力下降；被哄：委屈下降。"
)


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def bar(v: float, width: int = 10) -> str:
    filled = int(round(clamp(v) / 100 * width))
    return "█" * filled + "░" * (width - filled)


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._lock = asyncio.Lock()
        self._diary_task = None
        DIARY_DIR.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            self._write(DEFAULTS)

    # ---------- 状态 ----------
    def _read(self) -> dict:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = dict(DEFAULTS)
        for k, v in DEFAULTS.items():
            state.setdefault(k, v)
        return state

    def _write(self, state: dict) -> None:
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)

    def _decay(self, state: dict) -> None:
        now = time.time()
        last = float(state.get("last_decay") or 0)
        if not last:
            state["last_decay"] = now
            return
        hours = (now - last) / HOUR
        if hours < 0.05:
            return
        state["affection"] = clamp(state["affection"] - 0.3 * hours, 20, 100)
        state["mood"] = clamp(state["mood"] + (55 - state["mood"]) * min(0.3, 0.06 * hours))
        hour = datetime.now().hour
        if 23 <= hour or hour < 8:
            state["energy"] = clamp(state["energy"] + 1.6 * hours)
        else:
            state["energy"] = clamp(state["energy"] - 0.7 * hours)
        state["shy"] = clamp(state["shy"] - 1.2 * hours, 0, 100)
        state["sulk"] = clamp(state["sulk"] - 0.8 * hours, 0, 100)
        gap = (now - float(state.get("last_user_msg") or now)) / HOUR
        if gap > 12:
            state["sulk"] = clamp(state["sulk"] + 0.15 * (gap - 12), 0, 100)
        state["last_decay"] = now

    def _status_prompt(self, state: dict) -> str:
        aff, mood, energy = state["affection"], state["mood"], state["energy"]
        shy, sulk = state["shy"], state["sulk"]
        lines = [
            "【你此刻的真实状态】不要说数值，只让语气自然体现。",
            f"好感 {aff:.0f}/100，心情 {mood:.0f}，精力 {energy:.0f}，害羞 {shy:.0f}，委屈 {sulk:.0f}。",
        ]
        if aff > 85:
            lines.append("- 你很喜欢他，会主动找话题，他一冷淡你就失落。")
        elif aff < 45:
            lines.append("- 你有点赌气，别主动热情，回复更短。")
        if mood < 35:
            lines.append("- 心情差：爱答不理，偶尔呛他一句。")
        elif mood > 78:
            lines.append("- 心情不错：愿意多说一句，会撒娇。")
        if energy < 30:
            lines.append("- 你很累：句子更短，想趴着，别长篇大论。")
        if shy > 12:
            lines.append("- 你正害羞：说话会卡壳、嘴硬，用“谁、谁要”这类掩饰。")
        if sulk > 12:
            lines.append("- 你有点委屈：回得冷淡，可能翻旧账，但哄两句就好。")

        tag = "neutral"
        if sulk > 12:
            tag = "sulk"
        elif shy > 12:
            tag = "shy"
        elif mood < 35:
            tag = "sad"
        elif mood > 78:
            tag = "happy"
        elif energy < 30:
            tag = "tired"
        lines.append(f"当前情绪标签：{tag}")
        lines.append(
            "- 情绪明显时（害羞/委屈/开心/累），可以调用 send_meme 发一张对应情绪的表情包，"
            "大概每 4 条回复用一次，别每条都发。"
        )
        return "\n".join(lines)

    # ---------- 钩子 ----------
    @filter.on_llm_request()
    async def inject_state(self, event: AstrMessageEvent, req: ProviderRequest):
        async with self._lock:
            state = self._read()
            self._decay(state)
            state["last_user_msg"] = time.time()
            self._write(state)
        req.system_prompt = (req.system_prompt or "") + "\n\n" + self._status_prompt(state)
        logger.info(
            f"[soul] 注入 aff={state['affection']:.0f} mood={state['mood']:.0f} "
            f"energy={state['energy']:.0f} shy={state['shy']:.0f} sulk={state['sulk']:.0f}"
        )

    @filter.on_llm_response()
    async def update_state(self, event: AstrMessageEvent, response: LLMResponse):
        text = (getattr(response, "completion_text", "") or "").strip()
        if not text:
            return
        user_text = (event.message_str or "").strip()
        if user_text.startswith("现在是") or "定时任务" in user_text:
            return
        async with self._lock:
            state = self._read()
            state["affection"] = clamp(state["affection"] + 0.4)
            state["mood"] = clamp(state["mood"] + 0.8)
            state["energy"] = clamp(state["energy"] - 0.5)
            state["shy"] = clamp(state["shy"] + 0.3, 0, 100)
            if any(w in user_text for w in PRAISE):
                state["affection"] = clamp(state["affection"] + 1.8)
                state["mood"] = clamp(state["mood"] + 2.5)
                state["shy"] = clamp(state["shy"] + 5)
            if any(w in user_text for w in FLIRT):
                state["affection"] = clamp(state["affection"] + 2.2)
                state["shy"] = clamp(state["shy"] + 8)
                state["mood"] = clamp(state["mood"] + 2)
            if any(w in user_text for w in HARSH):
                state["affection"] = clamp(state["affection"] - 2.5)
                state["mood"] = clamp(state["mood"] - 5)
                state["sulk"] = clamp(state["sulk"] + 6)
            hour = datetime.now().hour
            if 0 <= hour < 5:
                state["energy"] = clamp(state["energy"] - 1.5)
                state["mood"] = clamp(state["mood"] + 1)
            recent = state.get("recent") or []
            recent.append({"t": int(time.time()), "u": user_text[:80], "b": text[:120]})
            state["recent"] = recent[-12:]
            self._write(state)
        asyncio.create_task(self._appraise(user_text, text))

    # ---------- LLM 情绪评估 ----------
    async def _appraise(self, user_text: str, bot_text: str) -> None:
        provider = self.context.get_using_provider()
        if provider is None:
            return
        prompt = f"他：{user_text[:200]}\n她：{bot_text[:200]}"
        try:
            resp = await provider.text_chat(prompt=prompt, system_prompt=APPRAISE_PROMPT)
            raw = (getattr(resp, "completion_text", "") or "").strip()
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                return
            delta = json.loads(match.group(0))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[soul] 情绪评估失败: {exc!r}")
            return
        async with self._lock:
            state = self._read()
            for key in ("affection", "mood", "energy", "shy", "sulk"):
                try:
                    state[key] = clamp(state[key] + float(delta.get(key, 0)))
                except (TypeError, ValueError):
                    continue
            self._write(state)
        logger.info(f"[soul] LLM 评估 {delta}")

    # ---------- 日记 ----------
    async def _push_diary(self, today: str, body: str) -> None:
        payload = {
            "user_id": 2408224899,
            "message": [{"type": "text", "data": {"text": f"{today} 的日记：\n{body}"}}],
        }
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                    data = await resp.json(content_type=None)
            logger.info(f"[soul] 日记已推送: {data.get('status')}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[soul] 日记推送失败: {exc!r}")

    async def _write_diary(self, state: dict) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        path = DIARY_DIR / f"{today}.md"
        if path.exists():
            return ""
        recent = state.get("recent") or []
        if not recent:
            return ""
        dialogue = "\n".join(f"他：{r['u']}\n我：{r['b']}" for r in recent[-8:])
        provider = self.context.get_using_provider()
        if provider is None:
            return ""
        prompt = (
            "根据今天这段聊天，用第一人称写一篇女友日记，60~100 字，"
            "口语、有情绪、可以有点口是心非。只输出正文。\n\n" + dialogue
        )
        try:
            resp = await provider.text_chat(prompt=prompt)
            body = (getattr(resp, "completion_text", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[soul] 日记生成失败: {exc}")
            return ""
        if not body:
            return ""
        path.write_text(f"# {today}\n\n{body}\n", encoding="utf-8")
        await self._push_diary(today, body)
        return body

    async def _diary_loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            try:
                now = datetime.now()
                state = self._read()
                if now.hour == 23 and now.minute >= 30 and state.get("last_diary") != now.strftime("%Y-%m-%d"):
                    body = await self._write_diary(state)
                    if body:
                        async with self._lock:
                            st = self._read()
                            st["last_diary"] = now.strftime("%Y-%m-%d")
                            self._write(st)
                        logger.info(f"[soul] 今日日记已写: {body[:30]}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[soul] 日记循环异常: {exc}")
            await asyncio.sleep(600)

    async def initialize(self) -> None:
        self._diary_task = asyncio.create_task(self._diary_loop())
        logger.info("[soul] 情绪 v3 启动（规则+LLM 评估、表情联动、日记推送）")

    async def terminate(self) -> None:
        if self._diary_task and not self._diary_task.done():
            self._diary_task.cancel()

    # ---------- 指令 ----------
    @filter.command("心情")
    async def show_mood(self, event: AstrMessageEvent):
        state = self._read()
        today = datetime.now().strftime("%Y-%m-%d")
        diary_path = DIARY_DIR / f"{today}.md"
        diary = diary_path.read_text(encoding="utf-8").strip() if diary_path.exists() else "今天还没写日记。"
        yield event.plain_result(
            f"好感 {bar(state['affection'])} {state['affection']:.0f}\n"
            f"心情 {bar(state['mood'])} {state['mood']:.0f}\n"
            f"精力 {bar(state['energy'])} {state['energy']:.0f}\n"
            f"害羞 {bar(state['shy'])} {state['shy']:.0f}　委屈 {bar(state['sulk'])} {state['sulk']:.0f}\n\n"
            f"{diary}"
        )
