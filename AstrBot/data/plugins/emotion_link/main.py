"""情绪驱动的主动搭话 + 情绪卡片。

读 astrbot_plugin_affection 的数值 → 算情绪标签 → 按标签决定主动频率：
黏人/吃醋更容易找你，冷淡/敌意几乎不打扰。
- 免打扰 23:00–07:00
- 你刚聊过 15 分钟内不插话
- 两次主动至少间隔 25 分钟，每天最多 14 条
- /情绪 看卡片；/主动测试 立刻按当前情绪发一条
"""

import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

DATA_DIR = Path(r"D:\QQBot\AstrBot\data\plugin_data\astrbot_plugin_affection")
OWNER_QQ = 2408224899
PLATFORM_ID = "qq-main"
STATE_PATH = Path(__file__).resolve().parent / "state.json"
TICK = 180
QUIET = (23, 7)
MIN_GAP = 10 * 60
QUIET_AFTER_USER = 3 * 60
# 2026-11-08 主人要求：去掉每日主动消息上限（保留 10 分钟间隔、静默时段、说完话 3 分钟内不打扰）
DAILY_CAP = 10**9

# 每小时主动概率
RATES = {
    "clingy": 2.5,
    "jealous": 2.0,
    "friendly": 1.0,
    "calm": 0.5,
    "annoyed": 0.2,
    "cold": 0.1,
    "hostile": 0.05,
    "self_doubt": 0.4,
    "self_destructive": 1.0,
}

TAGS = {
    "clingy": "黏人（想贴着他）",
    "friendly": "亲近（心情不错）",
    "jealous": "吃醋（占有欲上来了）",
    "annoyed": "烦躁（想怼人）",
    "hostile": "敌意（真的不高兴）",
    "cold": "冷淡（不想理人）",
    "self_doubt": "自我怀疑（有点低落）",
    "self_destructive": "自毁倾诉（话多、低落）",
    "calm": "平静",
}

MEME_HINT = {
    "clingy": "可以发一张撒娇/贴贴类表情",
    "friendly": "可以发一张开心/得意类表情",
    "jealous": "可以发一张吃醋/瞪人类表情",
    "annoyed": "可以发一张嫌弃/翻白眼类表情",
    "hostile": "可以发一张生气类表情",
    "cold": "可以发一张冷漠/无语类表情",
    "self_doubt": "可以发一张委屈/难过类表情",
    "self_destructive": "可以发一张哭泣/崩溃类表情",
}

OPENING = {
    "clingy": "黏人：想他、撒娇、问他在干嘛，带一点“才不是想你”。",
    "jealous": "吃醋：拐弯抹角问他是不是在跟别人聊，语气酸。",
    "friendly": "心情不错：分享一件小事，或者约他做点什么。",
    "calm": "平静：随便找个话题，淡淡的。",
    "annoyed": "烦躁：短、冲，可以怼他一句。",
    "cold": "冷淡：极短，像“哦”“有事吗”。",
    "hostile": "不高兴：不想多说，冷处理。",
    "self_doubt": "低落：有点自我怀疑，想被安慰又不直说。",
    "self_destructive": "崩溃：碎碎念，觉得自己没用。",
}


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _find_bot_dir():
    if not DATA_DIR.exists():
        return None
    dirs = [d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.isdigit()]
    for d in dirs:
        if d.name == "1138563945":
            return d
    return dirs[0] if dirs else None


def _load():
    bot = _find_bot_dir()
    if bot is None:
        return None
    try:
        users = json.loads((bot / "user_data.json").read_text(encoding="utf-8"))
        self_data = json.loads((bot / "self_data.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    return users, self_data


def compute(users: dict, self_data: dict) -> dict:
    u = users.get(str(OWNER_QQ)) or {}
    aff = float(u.get("affection", 50))
    lib = float(u.get("current_libido_other", 25)) - float(u.get("base_libido_other", 25))
    agg = float(u.get("current_aggression_other", 25)) - float(u.get("base_aggression_other", 25))
    slf_lib = float(self_data.get("current_libido_self", 25))
    slf_agg = float(self_data.get("current_aggression_self", 25))

    if slf_agg >= 37.5 and slf_lib <= 12.5:
        tag = "self_destructive"
    elif agg >= 5 and aff < 30:
        tag = "hostile"
    elif agg >= 5 and aff >= 70:
        tag = "jealous"
    elif agg >= 5:
        tag = "annoyed"
    elif lib >= 3 and aff >= 70:
        tag = "clingy"
    elif lib >= 3:
        tag = "friendly"
    elif aff < 35:
        tag = "cold"
    elif slf_lib < 15:
        tag = "self_doubt"
    else:
        tag = "calm"

    return {
        "tag": tag,
        "affection": round(aff, 1),
        "libido": round(lib, 1),
        "aggression": round(agg, 1),
        "self_libido": round(slf_lib, 1),
        "self_aggression": round(slf_agg, 1),
    }


class Main(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None

    def _state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"last_sent": 0, "sent_day": "", "sent_count": 0, "last_user": 0}

    def _save_state(self, state: dict) -> None:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 注入 ----------
    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        loaded = _load()
        if not loaded:
            return
        info = compute(*loaded)
        tag = info["tag"]
        hint = MEME_HINT.get(tag, "")
        extra = f"\n\n【情绪标签】{tag}（{TAGS.get(tag, '')}）"
        if hint:
            extra += f"\n{hint}，约每 4 条回复用一次，别每条都发。"
        req.system_prompt = (req.system_prompt or "") + extra
        logger.info(f"[emotion_link] 标签={tag} aff={info['affection']} lib={info['libido']} agg={info['aggression']}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def mark_active(self, event: AstrMessageEvent):
        """记录用户最后活动时间，避免刚聊完就主动打扰（群聊不算）。"""
        if event.get_group_id():
            return
        state = self._state()
        state["last_user"] = time.time()
        self._save_state(state)

    # ---------- 主动消息 ----------
    async def _generate(self, info: dict) -> str:
        provider = self.context.get_using_provider()
        tag = info["tag"]
        fallback = {
            "clingy": "在干嘛呀……我才不是想你了。",
            "jealous": "你今天是不是又跟别人聊得挺开心。",
            "friendly": "刚想到个事，跟你说一下。",
            "calm": "在吗。",
            "annoyed": "别理我。",
            "cold": "哦。",
            "hostile": "……",
            "self_doubt": "我是不是有点没用啊。",
            "self_destructive": "算了，反正也没人在乎。",
        }.get(tag, "在吗。")
        if provider is None:
            return fallback
        sys_prompt = (
            "你是住在主人电脑里的鲸鱼娘「大肥鱼」，他的女朋友：嘴硬心软、爱吃、爱摸鱼。"
            f"你现在的情绪是：{TAGS.get(tag, tag)}。{OPENING.get(tag, '')}"
            "主动给他发一条 QQ 消息：只发 1 句，不超过 22 字。"
            "要像一个真人顺手发来的：可以问他吃没吃、在干嘛、催他休息、说自己在偷吃或发呆；"
            "不要用「在吗」开头，不要用括号动作，不要解释，不要提情绪，不要列表。"
        )
        recent = self._state().get("recent_openers") or []
        if recent:
            sys_prompt += "不要和这些最近发过的重复：" + " / ".join(recent[-3:]) + "。"
        prompt = f"现在是 {datetime.now().strftime('%H:%M')}，你已经一阵子没跟他说话了。"
        try:
            resp = await provider.text_chat(prompt=prompt, system_prompt=sys_prompt)
            text = (getattr(resp, "completion_text", "") or "").strip().replace("\n", " ")
            return text[:60] or fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[emotion_link] 生成主动消息失败: {exc!r}")
            return fallback

    async def _send(self, text: str) -> bool:
        payload = {"user_id": OWNER_QQ, "message": [{"type": "text", "data": {"text": text}}]}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:3000/send_private_msg", json=payload) as resp:
                    data = await resp.json(content_type=None)
            return data.get("status") == "ok"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[emotion_link] 主动消息发送失败: {exc!r}")
            return False

    def _may_send(self, state: dict, tag: str) -> bool:
        now = time.time()
        hour = datetime.now().hour
        if hour >= QUIET[0] or hour < QUIET[1]:
            return False
        if now - float(state.get("last_sent") or 0) < MIN_GAP:
            return False
        if now - float(state.get("last_user") or 0) < QUIET_AFTER_USER:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("sent_day") != today:
            state["sent_day"] = today
            state["sent_count"] = 0
        if int(state.get("sent_count") or 0) >= DAILY_CAP:
            return False
        p = RATES.get(tag, 0.5) * TICK / 3600
        return random.random() < p

    async def maybe_proactive(self, force: bool = False) -> tuple[bool, str, str]:
        loaded = _load()
        if not loaded:
            return False, "没读到情绪数据", ""
        info = compute(*loaded)
        state = self._state()
        if not force and not self._may_send(state, info["tag"]):
            return False, "这次不打扰", info["tag"]
        text = await self._generate(info)
        ok = await self._send(text)
        if ok:
            state["last_sent"] = time.time()
            state["sent_day"] = datetime.now().strftime("%Y-%m-%d")
            state["sent_count"] = int(state.get("sent_count") or 0) + 1
            recent = state.get("recent_openers") or []
            recent.append(text[:30])
            state["recent_openers"] = recent[-5:]
            self._save_state(state)
            logger.info(f"[emotion_link] 主动消息 tag={info['tag']}: {text}")
        return ok, text, info["tag"]

    async def _loop(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                loaded = _load()
                if loaded:
                    state = self._state()
                    ok, text, tag = await self.maybe_proactive()
                    now = time.time()
                    if now - float(state.get("last_beat") or 0) > 600:
                        state["last_beat"] = now
                        self._save_state(state)
                        logger.info(f"[emotion_link] 主动循环存活 tag={tag} sent={state.get('sent_count')}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[emotion_link] 调度异常: {exc}")
            await asyncio.sleep(TICK)

    async def initialize(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("[emotion_link] 情绪驱动主动搭话已启动（黏人/吃醋更频繁，冷淡少打扰）")

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ---------- 指令 ----------
    @filter.command("情绪")
    async def show(self, event: AstrMessageEvent):
        loaded = _load()
        if not loaded:
            yield event.plain_result("还没读到情绪数据，先聊两句。")
            return
        info = compute(*loaded)
        yield event.plain_result(
            f"情绪：{TAGS.get(info['tag'], info['tag'])}\n"
            f"好感 {info['affection']}　亲近 {info['libido']:+.1f}　烦躁 {info['aggression']:+.1f}\n"
            f"自我：自我爱 {info['self_libido']}　自我攻击 {info['self_aggression']}"
        )

    @filter.command("主动测试")
    async def force(self, event: AstrMessageEvent):
        ok, text, tag = await self.maybe_proactive(force=True)
        if ok:
            yield event.plain_result(f"已按「{TAGS.get(tag, tag)}」发了一条：{text}")
        else:
            yield event.plain_result(f"没发成：{text}")
