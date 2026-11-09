"""qzone_life：让「大肥鱼」有自己的空间说说。

设计：
- 一天几个随机时段（8:00–23:30，至少隔 3 小时），到点写一条，深夜不发。
- 正文 = 人格（从 AstrBot 人格库读「大肥鱼」）+ 今天的小事方向 + 心情；
  一次写 3 条候选，硬规则筛掉模板句，再挑一条。
- 图片按内容配：吃的配吃的、懒的配睡/工作，转成静态 jpg 再传，免得 gif 传坏。
- 状态落盘：发过的记录（防重样、防重启后补发一整天）。
"""

from __future__ import annotations

import asyncio
import io
import json
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from . import qzone_v5_content as content

PLATFORM_ID = "qq-main"
OWNER_QQ = "2408224899"
AFFECTION_ROOT = Path(r"D:\QQBot\AstrBot\data\plugin_data\astrbot_plugin_affection\1138563945")
ASTRBOT_DB = Path(r"D:\QQBot\AstrBot\data\data_v4.db")
MEME_ROOT = Path(
    r"D:\QQBot\AstrBot\data\plugin_data\meme_manager\packs\blue-fat-fish-meme-pack\memes"
)
BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"
IMG_CACHE = BASE / "img_cache"

PERSONA_FALLBACK = (
    "你是大肥鱼，一条住在主人电脑里的鲸鱼娘：嘴馋、爱摸鱼、傲娇但心软，"
    "有自己的小日子，说话短、口语，不卖惨。"
)

# 每天从这些时段里随机挑几条发，实际时间前后浮动 ±45 分钟
SLOT_HOURS = (9, 11, 13, 15, 17, 19, 21, 22)
POSTS_PER_DAY = (2, 3)   # 每天 2~3 条，偶尔 4 条
JITTER_MIN = 45          # 每个时段前后浮动 ±45 分钟
MIN_GAP = 150            # 两条之间至少隔 150 分钟
MAX_PER_DAY = 4
QUIET = (23, 7)          # 23:00–07:00 不发
CATCHUP_MIN = 90         # 重启后，错过 90 分钟内的时段可以补发
HISTORY = 12

CATEGORY_FOLDERS = {
    # v5 的主题名 → 表情包目录（按情绪走，别配得驴唇不对马嘴）
    "interview": ["affection", "confused"],
    "money": ["teasing", "money", "sad"],
    "exam": ["work", "confused", "sad"],
    "night": ["sleep", "teasing"],
    "small_win": ["happy", "affection"],
    "lazy": ["sleep", "work"],
    "food": ["food", "happy"],
    "self": ["teasing", "confused", "happy"],
    # 旧分类兜底
    "eat": ["food", "happy"],
    "care": ["affection", "happy", "reply"],
    "owner": ["affection", "shy", "happy"],
    "group": ["teasing", "entertainment", "confused"],
    "desk": ["work", "confused", "entertainment"],
    "weird": ["confused", "teasing", "surprised"],
}

MOOD_TAGS = {
    "clingy": "黏人，想贴着人",
    "jealous": "有点吃醋",
    "annoyed": "有点烦",
    "hostile": "不高兴",
    "cold": "冷淡",
    "self_doubt": "有点低落",
    "self_destructive": "心里乱",
    "friendly": "心情不错",
    "calm": "平静",
}


# ------------------------------------------------------------------ 人格 / 心情
def load_persona() -> str:
    try:
        con = sqlite3.connect(f"file:{ASTRBOT_DB}?mode=ro", uri=True, timeout=3)
        row = con.execute(
            "select system_prompt from personas where persona_id='大肥鱼' "
            "order by updated_at desc limit 1"
        ).fetchone()
        con.close()
        if row and row[0] and len(row[0]) > 80:
            return row[0]
    except Exception as exc:  # noqa: BLE001
        logger.info(f"[qzone_life] 读人格失败，用兜底: {exc!r}")
    return PERSONA_FALLBACK


def read_mood() -> tuple[str, str]:
    """返回 (情绪标签, 给提示词用的一句心情)。读不到就当平静。"""
    try:
        users = json.loads((AFFECTION_ROOT / "user_data.json").read_text(encoding="utf-8"))
        me = json.loads((AFFECTION_ROOT / "self_data.json").read_text(encoding="utf-8"))
        u = users.get(OWNER_QQ, {})
        aff = float(u.get("affection", 50))
        lib = float(u.get("current_libido_other", 25)) - float(u.get("base_libido_other", 25))
        agg = float(u.get("current_aggression_other", 25)) - float(u.get("base_aggression_other", 25))
        s_lib = float(me.get("current_libido_self", 25))
        s_agg = float(me.get("current_aggression_self", 25))

        if s_agg >= 37.5 and s_lib <= 12.5:
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
        elif s_lib < 15:
            tag = "self_doubt"
        else:
            tag = "calm"
        return tag, MOOD_TAGS.get(tag, "平静")
    except Exception:
        return "calm", "平静"


# ------------------------------------------------------------------ 配图
def _cached_jpg(src: Path) -> Path | None:
    try:
        IMG_CACHE.mkdir(parents=True, exist_ok=True)
        dst = IMG_CACHE / (src.stem.replace(" ", "_") + ".jpg")
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        from PIL import Image

        img = Image.open(src)
        img.seek(0)
        frame = img.convert("RGBA")
        bg = Image.new("RGB", frame.size, (255, 255, 255))
        bg.paste(frame, mask=frame.split()[-1])
        bg.thumbnail((760, 760))
        bg.save(dst, "JPEG", quality=88)
        return dst
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[qzone_life] 转图失败 {src.name}: {exc!r}")
        return None


# 这些图不适合单独发在空间：通知条、红包、梗图文字（会被当成广告/图不对文）
IMG_SKIP_WORDS = (
    "复活节", "通知", "提示", "Popcat", "Raid", "Bits", "红包", "刷卡", "钱",
    "要米", "拿走我的钱", "按钮", "胶带", "记录", "坐牢", "死亡", "舔舔", "自我安慰",
)


def _img_ok(p: Path) -> bool:
    name = p.stem
    return not any(w in name for w in IMG_SKIP_WORDS)


def pick_image(category: str, text: str = "", recent: list[str] | None = None) -> str:
    folders = CATEGORY_FOLDERS.get(category, ["happy"])
    files: list[Path] = []
    for folder in folders:
        d = MEME_ROOT / folder
        if not d.is_dir():
            continue
        files.extend(
            p
            for p in d.iterdir()
            if p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg") and _img_ok(p)
        )
    if not files and MEME_ROOT.is_dir():
        files = [
            p
            for p in MEME_ROOT.rglob("*")
            if p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg") and _img_ok(p)
        ]
    if not files:
        return ""

    # 只在这个主题的目录里按正文关键词挑，避免配到完全不搭的图
    try:
        from . import qzone_image_match as matcher

        src = matcher.choose(text, files, recent)
    except Exception:
        src = random.choice(files)
    if src is None:
        return ""
    out = _cached_jpg(src)
    return str(out) if out else ""


# ------------------------------------------------------------------ 状态
def load_state() -> dict:
    try:
        st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("posts", [])        # [{t, text, category, slot}]
    st.setdefault("fired", [])        # 已触发过的时段 ISO 字符串
    st.setdefault("last_check", 0)    # epoch
    st.setdefault("last_post", 0)     # epoch
    st.setdefault("retry", None)      # 发布失败时留个重试：{slot, count}
    return st


def save_state(st: dict) -> None:
    st["posts"] = st.get("posts", [])[-40:]
    st["fired"] = st.get("fired", [])[-80:]
    try:
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[qzone_life] 状态写盘失败: {exc!r}")


def _slots_for_day(day: datetime) -> list[datetime]:
    n = random.randint(*POSTS_PER_DAY)
    hours = sorted(random.sample(SLOT_HOURS, n))
    out = []
    for h in hours:
        jitter = random.randint(-JITTER_MIN, JITTER_MIN)
        out.append(
            day.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(minutes=jitter)
        )
    return sorted(out)


def _evening_refill(st: dict, day: datetime, now: datetime) -> list[datetime]:
    """如果当天只剩很少的时间、又还没发够，就补一个今晚的时段。

    场景：重启/改配置导致既有 slots 全落在过去，结果一整天不再发。
    """
    if now.hour < 19 or now.hour >= QUIET[0]:
        return []
    slots = st.get(f"slots:{day:%Y-%m-%d}") or []
    future = [s for s in slots if datetime.fromisoformat(s) > now]
    if future:
        return []
    if _posts_today(st, day) >= MAX_PER_DAY:
        return []
    # 20~40 分钟后，给生成留点时间
    refill = now + timedelta(minutes=random.randint(20, 40))
    st.setdefault(f"slots:{day:%Y-%m-%d}", []).append(refill.isoformat())
    return [refill]


def _ensure_slots(st: dict, day: datetime) -> list[datetime]:
    key = f"slots:{day:%Y-%m-%d}"
    raw = st.get(key)
    if isinstance(raw, list) and raw:
        try:
            return [datetime.fromisoformat(x) for x in raw]
        except Exception:
            pass
    slots = _slots_for_day(day)
    st[key] = [s.isoformat() for s in slots]
    # 只留最近两天的
    today_key = f"{day:%Y-%m-%d}"
    for k in list(st):
        if k.startswith("slots:") and k != key and k[-10:] < today_key:
            st.pop(k, None)
    return slots


def _posts_today(st: dict, day: datetime) -> int:
    prefix = f"{day:%Y-%m-%d}"
    return sum(
        1
        for p in st.get("posts", [])
        if str(p.get("t", ""))[:10] == prefix and p.get("category") != "legacy"
    )


# ------------------------------------------------------------------ 插件
class Main(Star):
    """QQ 空间：定时自主发说说 + 聊天指令手动发。"""

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._task = None
        self._persona = ""
        self._last_bvid = ""

    async def initialize(self) -> None:
        self._persona = load_persona()
        self._task = asyncio.create_task(self._auto_loop())
        st = load_state()
        logger.info(
            f"[qzone_life] 说说循环已启动（每天最多 {MAX_PER_DAY} 条，"
            f"已发 {len(st.get('posts', []))} 条历史）"
        )

    async def terminate(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ---------- 写 ----------
    async def craft(self, fixed_theme: str | None = None) -> tuple[str, str]:
        provider = self.context.get_using_provider()
        if provider is None:
            return "", ""
        tag, word = read_mood()
        st = load_state()
        posts = [p for p in st.get("posts", []) if p.get("text")]
        recent = [p.get("text", "") for p in posts][-4:]
        used_themes = [p.get("category", "") for p in posts][-5:]

        # 她今天真看过的东西（刷B站日报），当作真实素材
        reality = ""
        picked_bvid = ""
        try:
            from . import qzone_reality as reality_mod

            seen = {str(p.get("bvid") or "") for p in st.get("posts", [])}
            video = reality_mod.pick_video(exclude=seen)
            if video:
                picked_bvid = str(video.get("bvid") or "")
                reality = reality_mod.video_facts(video)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[qzone_life] 读 B 站日报失败（不影响发说说）: {exc!r}")

        try:
            text, theme = await content.generate(
                provider,
                "",
                recent,
                word,
                mood_tag=tag,
                used_themes=used_themes,
                reality_facts=reality,
                n_cand=3,
                fixed_theme=fixed_theme,
            )
            self._last_bvid = picked_bvid
            return text, theme
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[qzone_life] 生成失败: {exc!r}")
            return "", ""

    # ---------- 发 ----------
    async def _post(self, text: str, category: str) -> bool:
        img = pick_image(category, text) if random.random() < 0.85 else ""

        # 刚启动时 OneBot 连接可能还没稳住，多等几次
        last_exc: Exception | None = None
        for attempt in range(3):
            inst = self.context.get_platform_inst(PLATFORM_ID)
            bot = getattr(inst, "bot", None)
            if bot is None:
                last_exc = RuntimeError("平台实例未就绪")
                await asyncio.sleep(20)
                continue
            try:
                payload = {"content": text, "ugc_right": 4}
                if img:
                    payload["images"] = [img]
                await bot.call_action("send_qzone_msg", **payload)
                return True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if img:
                    # 带图失败先去掉图再试一次
                    logger.warning(f"[qzone_life] 带图发送失败，去图重试: {exc!r}")
                    img = ""
                    continue
                logger.warning(f"[qzone_life] 发送失败（第 {attempt + 1} 次）: {exc!r}")
                await asyncio.sleep(20)
        logger.warning(f"[qzone_life] 放弃发送: {last_exc!r}")
        return False

    # ---------- 主循环 ----------
    async def _auto_loop(self) -> None:
        await asyncio.sleep(45)  # 等平台加载完
        while True:
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[qzone_life] 循环异常: {exc!r}")
            await asyncio.sleep(120)

    async def _tick(self) -> None:
        now = datetime.now()
        st = load_state()

        # 上次发布失败留下的重试
        retry = st.get("retry")
        if isinstance(retry, dict) and float(retry.get("at") or 0) <= time.time():
            text = str(retry.get("text") or "")
            category = str(retry.get("category") or "")
            st["retry"] = None
            if text and await self._post(text, category):
                st.setdefault("posts", []).append(
                    {
                        "t": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "text": text,
                        "category": category,
                        "slot": retry.get("slot", "retry"),
                    }
                )
                st["last_post"] = time.time()
                logger.info(f"[qzone_life] 重试成功（{category}）: {text}")
            else:
                logger.warning("[qzone_life] 重试仍失败，今天这条就算了")
            st["last_check"] = time.time()
            save_state(st)
            return

        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        slots = _ensure_slots(st, day)
        if slots:
            slots = list(slots) + _evening_refill(st, day, now)

        last_check = float(st.get("last_check") or 0)
        if last_check <= 0 or time.time() - last_check > 2 * 86400:
            last_check = time.time() - CATCHUP_MIN * 60

        quiet = now.hour >= QUIET[0] or now.hour < QUIET[1]
        if quiet:
            st["last_check"] = time.time()
            save_state(st)
            return

        fired = set(st.get("fired", []))
        # 同一个时段如果已经有点在排队，只补最近的一个
        due = [
            s
            for s in slots
            if s.timestamp() > last_check and s <= now and s.isoformat() not in fired
        ]
        if not due:
            st["last_check"] = time.time()
            save_state(st)
            return

        slot = due[-1]
        for s in due:
            if s.isoformat() not in fired:
                fired.add(s.isoformat())

        gap_ok = time.time() - float(st.get("last_post") or 0) >= MIN_GAP * 60
        cap_ok = _posts_today(st, day) < MAX_PER_DAY
        if not (gap_ok and cap_ok):
            logger.info(f"[qzone_life] 到点但跳过（gap={gap_ok} cap={cap_ok}）")
            st["fired"] = sorted(fired)
            st["last_check"] = time.time()
            save_state(st)
            return

        text, category = await self.craft()
        if not text:
            logger.info("[qzone_life] 这次没写出合格的说说")
            st["fired"] = sorted(fired)
            st["last_check"] = time.time()
            save_state(st)
            return

        ok = await self._post(text, category)
        if ok:
            st.setdefault("posts", []).append(
                {
                    "t": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "text": text,
                    "category": category,
                    "slot": slot.isoformat(),
                    "bvid": self._last_bvid,
                }
            )
            st["last_post"] = time.time()
            st["retry"] = None
            logger.info(f"[qzone_life] 已自主发说说（{category}）: {text}")
        else:
            logger.warning("[qzone_life] 发说说失败，10 分钟后重试一次")
            st["retry"] = {
                "slot": slot.isoformat(),
                "at": time.time() + 600,
                "text": text,
                "category": category,
                "count": 1,
            }
        st["fired"] = sorted(fired)
        st["last_check"] = time.time()
        save_state(st)

    # ---------- 指令 ----------
    @filter.command("发说说")
    async def manual_post(self, event: AstrMessageEvent):
        raw = (event.message_str or "").replace("/发说说", "", 1).strip()
        if raw:
            text, category = raw, "manual"
        else:
            text, category = await self.craft()
        if not text:
            yield event.plain_result("想不出来发啥。")
            return
        try:
            await self._post(text, category)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[qzone_life] 手动发说说失败: {exc!r}")
            yield event.plain_result("发失败了。")
            return
        st = load_state()
        st.setdefault("posts", []).append(
            {
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "category": category,
                "slot": "manual",
                "bvid": self._last_bvid,
            }
        )
        st["last_post"] = time.time()
        save_state(st)
        yield event.plain_result(f"发好了：{text}")

    @filter.command("说说预览")
    async def preview(self, event: AstrMessageEvent):
        """不发送，先生成几条看看效果（含配图文件名）。"""
        tag, word = read_mood()
        lines = [f"当前心情：{word}（{tag}）"]
        for _ in range(3):
            text, cat = await self.craft()
            if not text:
                continue
            img = pick_image(cat)
            img_name = Path(img).name if img else "无图"
            lines.append(f"[{cat}·{len(text)}字] {text}\n   配图：{img_name}")
        yield event.plain_result("\n".join(lines) if len(lines) > 1 else "这次没写出来。")

    @filter.command("说说自检")
    async def selftest(self, event: AstrMessageEvent):
        """跑一次完整链路（生成→配图→发布→删除），只发仅自己可见，验证不快。"""
        text, cat = await self.craft()
        if not text:
            yield event.plain_result("生成失败，没东西可测。")
            return
        img = pick_image(cat)
        inst = self.context.get_platform_inst(PLATFORM_ID)
        bot = getattr(inst, "bot", None)
        if bot is None:
            yield event.plain_result("平台还没就绪。")
            return
        payload = {"content": text, "ugc_right": 64}
        if img:
            payload["images"] = [img]
        try:
            resp = await bot.call_action("send_qzone_msg", **payload)
            tid = (resp or {}).get("data", {}).get("tid")
            if tid:
                await bot.call_action("delete_qzone_msg", tid=tid)
            yield event.plain_result(
                f"自检通过：{text}\n配图：{Path(img).name if img else '无'}\n"
                f"发布 tid={tid}（已删）"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[qzone_life] 自检失败: {exc!r}")
            yield event.plain_result(f"自检失败：{exc!r}")
