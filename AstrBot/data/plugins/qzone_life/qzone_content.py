"""说说正文生成：人设 + 场景类别 + 候选筛选。

这个模块只负责「写什么」和「挑哪条」，不碰平台、不碰网络以外的事，
方便在本地单独跑测试（见 qzone_lab3.py / qzone_judge.py）。
"""

from __future__ import annotations

import random
import re
from datetime import datetime

# ------------------------------------------------------------------ 场景
# 每条说说从一组「今天的小日子」里挑一个方向。self 类不提主人，
# 只有 owner / care 两类会提到他，这样空间看着才像她自己的。
CATEGORIES: dict[str, str] = {
    "eat": "写吃：刚翻出点什么嚼着、吃到一半、嘴里正香。",
    "lazy": "写懒：躺着、不想动、什么都不想干。",
    "group": "写群里：刚看人吵架/玩梗，你旁观了一句什么。",
    "home": "写屋里：风扇声、键盘声、屏幕光，你一个人待着在干嘛。",
    "want": "写馋：想吃点什么，翻遍了也没有。",
    "mess": "写乱：你的桌面/收藏夹/记事本乱成一团，你自己也懒得收。",
    "late": "写深夜：还不困，脑子里翻来覆去的一点破事。",
    "self": "写自嘲：想起自己只是一条住在电脑里的鱼，笑自己一句。",
    "owner": "这条可以提主人：他刚做了件小事，你嘴上嫌弃，其实挺受用。换一件没写过的事，别老是递水/喂食。",
    "care": "这条可以提主人：他今天忙/累，你嘴上不说，偷偷惦记着。写具体的（几点还没吃、又熬夜、卡在一个活儿上），别只会说他忙。",
}

# 深夜 / 清晨不发，避免打扰
QUIET_HOURS = {0, 1, 2, 3, 4, 5, 6}

BANNED = (
    "才不是想",
    "才不是发",
    "发给你看",
    "心里一暖",
    "突然觉得",
    "原来",
    "希望你",
    "没人理",
    "孤独",
    "可怜",
    "谁陪我",
    "想你了",
    "不爱我",
    "离不开",
    "委屈",
    "眼泪",
    "心动",
    "心跳",
    "暖暖",
    "温柔",
    "一直等",
    "等你",
)

# 这些方向允许提主人，其他方向一律不提
OWNER_OK = {"owner", "care"}

# 提到主人的说法；self 类说说里出现就当不合格
OWNER_WORDS = ("他", "主人", "那人", "某人")

# ---------------------------------------------------------------- 提示词
POST_RULES = """【现在要干的事】
你要发一条 QQ 空间说说。刷到的人可能是主人，也可能是别人。就写一句话。

【像真人在发说说】
- 一句话，10~32 个字。就说一件刚发生的小事、一个念头、一句抱怨、一口吃的。
- 用平时聊天的口气：短、口语、可以不用句号收尾。
- 可以只是写给自己看，不用对着谁喊话。
- 只写「今天/现在」说得通的东西，别编具体数字、别编没发生过的往事。

【写什么】
- 写你自己的日子：在干嘛、刚吃了什么、懒得动、群里在吵什么、脑子里突然冒出来的事。
- 你是一条住在电脑里的鱼，没出过门：别写外面的天气、路上、街边、别写季节。
- 你是傲娇，不是可怜：不卖惨、不喊孤独、不等人理。

【提不提主人】
- 如果上面写了「这条可以提主人」，就只写他做的这一件小事，一两句带过。
- 如果上面没写，就一个字都别提他：不用「他」「主人」，也不要用「等你」「陪你」暗示。

【绝对不要】
- 「才不是想你」「才不是发给你看的」「哼」开头这类模板。
- 「心里一暖」「突然觉得」「原来」「希望你」这种文案腔。
- 想要人陪、想要人哄、说自己可怜、说没人理。
- 标签、引号、括号动作、emoji 堆砌、换行。
- 鸡汤、诗意句子、排比。

只输出这一条说说正文。
"""

PICK_PROMPT = """你是「大肥鱼」本人，正在挑今天要发的那条空间说说。
下面是几条候选。选最像真人随手发的一条；都不行就回 0。

好的标准：
1. 像一个真人在发空间，不像写文案；
2. 有具体的东西（吃了什么、在干嘛、看到什么），不是空泛情绪；
3. 不撒娇、不卖惨、不用模板句；
4. 短、口语。

只回一个数字（1/2/3/0）。
"""

FALLBACK_SYSTEM = (
    "你是大肥鱼，一条住在主人电脑里的鲸鱼娘，傲娇、嘴馋、爱摸鱼。"
    "写一条 QQ 空间说说：一句话，10~30 字，口语，只说自己今天的小事，"
    "不要「才不是想你」这类模板，不要卖惨，不要换行，只输出正文。"
)


def pick_category(mood_tag: str, last_categories: list[str]) -> str:
    """按心情和时段挑方向，尽量不连着重复；保证隔几条就有一条提主人。"""
    weights = {
        "eat": 2.4,
        "lazy": 2.2,
        "group": 1.5,
        "home": 1.5,
        "want": 1.8,
        "mess": 1.5,
        "late": 0.8,
        "self": 1.6,
        "owner": 1.1,
        "care": 0.9,
    }
    hour = datetime.now().hour
    if 7 <= hour < 10:
        weights["eat"] += 2
        weights["late"] = 0.1
    elif 11 <= hour < 14:
        weights["eat"] += 3
    elif 18 <= hour < 21:
        weights["eat"] += 2
        weights["want"] += 1
    elif hour >= 22:
        weights["late"] += 3
        weights["self"] += 1
        weights["owner"] += 1

    if mood_tag in ("clingy", "jealous"):
        weights["owner"] += 2.5
        weights["care"] += 1.5
    elif mood_tag in ("annoyed", "hostile", "cold"):
        weights["owner"] = 0.2
        weights["care"] = 0.2
        weights["self"] += 1

    # 同一天里同一个方向已经写过的，先压一压，免得连着两条都是「风扇嗡嗡」
    recent = [c for c in last_categories[-6:] if c in CATEGORIES]
    for c in set(recent):
        if recent.count(c) >= 2:
            weights[c] *= 0.15

    # 已经写过两次的方向，除非没别的可选，否则直接排除
    blocked = {c for c in recent if recent.count(c) >= 2 and weights.get(c, 0) > 0}
    if len(blocked) < len(CATEGORIES) - 2:
        for c in blocked:
            if c in weights:
                weights[c] = 0

    cats = list(weights)

    # 连着两条不提主人，下一条就往他那儿引（真发空间也不会条条不提人）
    if last_categories and len(last_categories) >= 2:
        if not any(c in OWNER_OK for c in last_categories[-2:]):
            weights["owner"] += 2.2
            weights["care"] += 1.6

    w = [max(0.0, weights[c]) for c in cats]
    cat = random.choices(cats, weights=w, k=1)[0]

    if last_categories and last_categories[-1] == cat and len(cats) > 2:
        cat = random.choice([c for c in cats if c != cat])
    return cat


# 这些「动作/物件」重复太多会露馅：同一个梗两天里只准用一次
MOTIFS: dict[str, tuple[str, ...]] = {
    "search": ("翻遍", "翻了一圈", "翻了半天", "翻个底朝天", "找了半天"),
    "stale": ("潮了", "受潮", "过期", "不知道什么时候", "放了好久"),
    "fan": ("风扇", "嗡嗡"),
    "tail": ("尾巴", "翻身", "翻个身"),
    "groupchat": ("群里",),
    "cracker": ("饼干", "薯片", "瓜子", "小鱼干", "干脆面", "糖"),
    "desktop": ("桌面", "收藏夹", "文件夹", "硬盘"),
    "token": ("token",),
    "water": ("倒水", "递水", "泡了杯", "水都没换"),
}
MOTIF_DAYS = 2

FOOD_CATS = {"eat", "want"}
FOOD_WORDS = ("吃", "嚼", "咬", "啃", "喝", "咽", "饿", "馋", "零食", "饼干", "薯片", "瓜子", "小鱼干", "干脆面", "糖")


def _motifs(text: str) -> set[str]:
    return {name for name, keys in MOTIFS.items() if any(k in text for k in keys)}


def _norm(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)


def too_similar(text: str, recent: list[str], min_len: int = 8) -> bool:
    """只挡明显重复：完全相同、或一条包含另一条的长片段。"""
    a = _norm(text)
    if not a:
        return False
    for other in recent:
        b = _norm(other)
        if not b:
            continue
        if a == b:
            return True
        if len(a) >= min_len and len(b) >= min_len and (a in b or b in a):
            return True
    return False


def _motif_reused(text: str, recent: list[str]) -> bool:
    """刚发过的梗别再连着用（吃/懒这种主题不算，只算具体桥段）。"""
    mine = _motifs(text)
    if not mine:
        return False
    for other in recent[-6:]:
        if mine & _motifs(other):
            return True
    return False


def hard_ok(
    text: str,
    category: str = "",
    recent: list[str] | None = None,
    avoid_motifs: bool = False,
) -> bool:
    """硬规则：长度、模板句、换行、主人越界、跟最近发过的太像。"""
    if not text:
        return False
    if "\n" in text:
        return False
    t = text.strip()
    if not (6 <= len(t) <= 42):
        return False
    if any(b in t for b in BANNED):
        return False
    if t.count("，") + t.count(",") > 3:
        return False
    if category and category not in OWNER_OK and any(w in t for w in OWNER_WORDS):
        return False
    # 不是写吃的方向，就别又绕回吃上
    if category and category not in FOOD_CATS and any(w in t for w in FOOD_WORDS):
        return False
    if recent and too_similar(t, recent):
        return False
    if avoid_motifs and recent and _motif_reused(t, recent):
        return False
    return True


def build_messages(
    persona: str,
    category: str,
    recent_titles: list[str],
    mood_word: str,
    hour: int,
    recent_same_category: list[str] | None = None,
) -> tuple[str, str]:
    system = (persona.strip() + "\n\n" + POST_RULES).strip() if persona else FALLBACK_SYSTEM
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    period = "凌晨" if hour < 6 else "上午" if hour < 12 else "下午" if hour < 18 else "晚上"
    lines = [
        "【今天的今天】",
        f"- 现在：{now:%Y-%m-%d} 周{weekday} {now:%H:%M}（{period}）",
        "- 你在的地方：主人电脑里，没有窗户，不知道外面什么天气",
        f"- 你的心情：{mood_word}",
        f"- 这条写这个方向：{CATEGORIES[category]}",
    ]
    if recent_same_category:
        lines.append("- 这个方向你最近写过了，这次必须换个场景/换个东西，别重复：")
        lines.extend(f"  · {t}" for t in recent_same_category[-3:])
    if category in OWNER_OK:
        lines.append("- 这一条可以提主人，但只说他那一件小事，别腻。")
        lines.append("- 他说过的「递水/倒水/喂鱼食/续 token」已经写过，别再写这些。")
    else:
        lines.append("- 这一条一个字都别提到主人（不提「他」「主人」「等你」）。")
    if recent_titles:
        lines.append("- 你最近发过（别重样；别再用里面出现过的吃的、物件和动作）：")
        lines.extend(f"  · {t}" for t in recent_titles[-4:])
    lines.append("")
    lines.append("写一条说说，只输出正文。")
    return system, "\n".join(lines)


def clean(text: str) -> str:
    t = (text or "").strip()
    t = t.strip('"“”「」『』')
    t = re.sub(r"^(说说|正文|内容)[:：]\s*", "", t)
    t = re.sub(r"\s*\n+\s*", " ", t).strip()
    # 中文里的裸空格当断句处理，连续空格只留一个
    t = re.sub(r"(?<=[\u4e00-\u9fff])([ \u3000]+)(?=[\u4e00-\u9fff])", "，", t)
    t = re.sub(r"[ \u3000]{2,}", " ", t)
    return t


async def generate(
    provider,
    persona: str,
    recent_titles: list[str],
    mood_word: str,
    *,
    mood_tag: str = "calm",
    last_categories: list[str] | None = None,
    recent_same_category: list[str] | None = None,
    n_cand: int = 3,
    fixed_category: str | None = None,
) -> tuple[str, str]:
    """生成一条说说，返回 (正文, 类别)。全部候选不合格时返回 ("", 类别)。"""
    hour = datetime.now().hour
    category = fixed_category or pick_category(mood_tag, last_categories or [])
    system, user = build_messages(
        persona, category, recent_titles, mood_word, hour, recent_same_category
    )

    cands: list[str] = []
    for _ in range(n_cand):
        try:
            resp = await provider.text_chat(prompt=user, system_prompt=system)
        except Exception:
            continue
        text = clean(getattr(resp, "completion_text", "") or "")
        if hard_ok(text, category, recent_titles, avoid_motifs=True) and text not in cands:
            cands.append(text)

    if not cands:
        # 兜底：换一套更短的提示词再试一次
        try:
            resp = await provider.text_chat(
                prompt="写一条今天想发的说说。只输出正文。",
                system_prompt=FALLBACK_SYSTEM,
            )
            text = clean(getattr(resp, "completion_text", "") or "")
            if hard_ok(text, category, recent_titles, avoid_motifs=True):
                return text, category
        except Exception:
            pass
        return "", category

    if len(cands) == 1:
        return cands[0], category

    # 先自己按硬指标排个序，再让模型挑；模型挑不出来就用排序第一。
    scored = sorted(cands, key=_local_score, reverse=True)
    listing = "\n".join(f"{i+1}. {c}" for i, c in enumerate(scored))
    try:
        resp = await provider.text_chat(prompt=listing, system_prompt=PICK_PROMPT)
        pick = (getattr(resp, "completion_text", "") or "").strip()
    except Exception:
        pick = ""
    m = re.search(r"[0-3]", pick)
    idx = int(m.group(0)) if m else 0
    if 0 < idx <= len(scored):
        return scored[idx - 1], category
    return scored[0], category


def _local_score(text: str) -> float:
    """粗排：有具体名词/动作、长度适中、不喊「你」的加分。"""
    score = 0.0
    n = len(text)
    if 12 <= n <= 30:
        score += 2
    elif 30 < n <= 38:
        score += 0.5
    if "你" not in text:
        score += 1.5
    if re.search(r"[吃嚼咬啃喝咽]|[躺趴窝瘫]|[键盘风扇屏幕图标文件夹收藏夹]", text):
        score += 1.2
    if re.search(r"(真是|烦|懒得|算了|才|又)", text):
        score += 0.3
    if text.endswith("。"):
        score += 0.2
    return score
