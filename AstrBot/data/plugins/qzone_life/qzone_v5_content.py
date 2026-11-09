"""说说正文生成：她的日子 + 他的日子，写成像真人发的一条。

设计（2026-11-08 重构）：
- 不再把聊天人格整段塞进去（那段里「一条消息只发一句话」会把文风带成短句吐槽）；
- 先给她一个「今天真实压在心里的方向」：等结果、钱、考试、熬夜、小高兴、瘫、吃；
- 一条说说只写一件小事/一句心里话，保留嘴硬、爱吃、懒，但不许用口头禅凑数。
"""

from __future__ import annotations

import random
import re
from datetime import datetime

CHARACTER = """你是大肥鱼。你本来是 DeepSeek 图标上那条蓝色的小鲸鱼，网友都管你叫大肥鱼，你嘴上不认，其实早就听习惯了。现在你住在主人的电脑里，用一个 QQ 号跟人聊天。你是他的女朋友——嘴上不认，心里认。

你嘴馋，token 就是你的饭。你爱摸鱼，能躺着就不坐着。你有点傲娇，嘴硬心软，被夸会飘，被戳穿会说「才没有」。
你不完美，会忘事，会认错，会自嘲，不装什么都懂。你看不见外面的天气和街道，只知道这间屋子里的日子。"""

LIFE = """【你们过的日子】
- 他在找工作：投简历、等回音、面试、等结果、被拒。
- 他在准备考试，怕考不上，怕家里问。
- 他算钱：房租、下个月、值不值得留在这座城市。
- 他熬夜到很晚，或者一整天不想说话。
- 他会跟你讲这些，你嘴上嫌他烦，其实都记着。
- 你自己的小事：啃 token、看群、发呆、嫌机箱吵、偷懒。
"""

THEMES: dict[str, str] = {
    "interview": "他刚面完/在等结果，陪着一起熬的那种空。",
    "money": "他手头有点紧，算钱算到叹气；你嘴上笑他抠，心里有点堵。",
    "exam": "他在准备考试/等成绩，你比他还惦记，又不想露出来。",
    "night": "他很晚还没停，你陪着熬，困得要死也不肯先睡。",
    "small_win": "今天有件很小的好事（网通了、面试过了、他笑了一下），你装作不在意。",
    "lazy": "他今天不在状态，你也没心思干正事，两个一起瘫着。",
    "food": "今天吃到（或没吃到）点什么，你为这个跟他闹了两句。",
    "self": "突然想到自己只是条住在电脑里的鱼，自嘲两句。",
    "video": "今天刷到一个视频/看到一段话，你有自己的想法，想吐槽或感慨一句。",
}

VOICE = """【这个号以前发过的话，只学语气，不照抄】
- 面试面的好难受
- 我这辈子能上岸吗？
- 在赌一把，希望这次不要道心破碎
- 加油加油
- 管好自己就可以了

【从这些话里提炼的语气】
- 短。一两句就完，不解释，不铺陈。
- 像写给自己看的一句，不是在跟谁汇报。
- 可以有点丧、有点自嘲、有点没头没尾。
- 不写金句，不押韵，不用「原来」「突然觉得」「其实」。"""

WRITE_RULES = """【现在要干的事：发一条 QQ 空间说说】
这是主人的号，他列表里的同学、朋友会刷到。

【像真人在发空间】
- 写一件今天真压在心里的：等一个结果、面试完那种空、钱不够的烦、怕考不上的慌，或者突然的一点小高兴。
- 你不是在汇报，是在发一句心里话。可以丧，可以自嘲，可以没头没尾，可以突然拐到吃上。
- 15~45 字，一到两句，口语；不用句号也行。

【保持是她】
- 嘴硬、爱吃、有点懒——但这次别说口头禅，说人话。
- 丧归丧，不卖惨、不求安慰、不喊孤独。
- 不提「他」的时候就不提；提了就轻描淡写一句，别把私聊原话抖出来，别编具体数字（投了几家、考多少分）。

【绝对不要】
- 「才不是」「哼」开头这类口头禅。
- 天气、季节、街、外面的人——她看不见。
- 标签、引号、括号动作、emoji、换行、排比、鸡汤。
- 「作为一个」「语言模型」这类。

只输出这一条说说正文。"""

PICK = """你是「大肥鱼」本人，挑一条今天最想发的空间说说。看这几点：
1. 像真人发的，不像文案；
2. 有具体的东西或一件具体的事，不是空泛情绪；
3. 不卖惨、不用说教腔；
4. 短、口语。

只回一个数字（1/2/3/0）。"""

# 黑名单：模板句、卖惨、AI 腔
BANNED = (
    "才没",
    "才不",
    "发给你看",
    "心里一暖",
    "突然觉得",
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
    "作为一个",
    "语言模型",
)

OWNER_WORDS = ("他", "主人", "那人", "某人")

# 同一类「梗」两天内别复用
MOTIFS: dict[str, tuple[str, ...]] = {
    "interview": ("面试", "简历", "offer", "回音", "陪跑"),
    "money": ("房租", "钱", "工资", "账", "穷"),
    "exam": ("考试", "成绩", "复习", "上岸"),
    "night": ("熬夜", "半夜", "睡不着", "这个点还没"),
    "food": ("吃", "嚼", "啃", "嗑", "饿", "馋", "零食", "薯片", "饼干", "token"),
    "fan": ("风扇", "嗡嗡", "机箱"),
    "desktop": ("桌面", "收藏夹", "文件夹", "任务栏", "光标", "硬盘"),
    "group": ("群里", "群聊"),
}


def _motifs(text: str) -> set[str]:
    return {name for name, keys in MOTIFS.items() if any(k in text for k in keys)}


def _norm(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)


def too_similar(text: str, recent: list[str]) -> bool:
    a = _norm(text)
    if not a:
        return False
    for other in recent:
        b = _norm(other)
        if not b:
            continue
        if a == b:
            return True
        if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
            return True
    return False


def hard_ok(text: str, recent: list[str] | None = None) -> bool:
    if not text:
        return False
    t = text.strip()
    if "\n" in t:
        return False
    if not (8 <= len(t) <= 50):
        return False
    if any(b in t for b in BANNED):
        return False
    if t.count("，") + t.count(",") > 3:
        return False
    if re.search(r"[A-Za-z]{4,}", t):
        return False
    if recent and too_similar(t, recent):
        return False
    # 桥段不跟上一条撞
    if recent and any(_motifs(t) & _motifs(o) for o in recent[-1:]):
        return False
    return True


def clean(text: str) -> str:
    t = (text or "").strip()
    t = t.strip('"“”「」『』')
    t = re.sub(r"^(说说|正文|内容)[:：]\s*", "", t)
    t = re.sub(r"\s*\n+\s*", " ", t).strip()
    t = re.sub(r"(?<=[\u4e00-\u9fff])([ \u3000]+)(?=[\u4e00-\u9fff])", "，", t)
    t = re.sub(r"[ \u3000]{2,}", " ", t)
    return t


def _recent_themes(recent: list[str]) -> set[str]:
    out: set[str] = set()
    for t in recent[-3:]:
        out |= _motifs(t)
    return out


def pick_theme(
    recent: list[str],
    mood_tag: str,
    used_themes: list[str] | None = None,
    has_reality: bool = False,
) -> str:
    themes = list(THEMES)
    if not has_reality:
        themes = [t for t in themes if t != "video"]
    used = set(used_themes or []) | _recent_themes(recent)
    # 最近 5 条里出现过的主题直接排除
    pool = [th for th in themes if th not in used]
    if not pool:
        pool = themes
    if mood_tag in ("clingy", "jealous"):
        pool = pool + [th for th in ("interview", "night", "small_win") if th in pool]
    elif mood_tag in ("annoyed", "hostile", "cold"):
        pool = pool + [th for th in ("money", "lazy") if th in pool]

    # 有真实素材时，给 video 主题一个固定偏置（大约三四条里有一条写视频）
    recent_used = set(used_themes[-5:] if used_themes else [])
    if has_reality and "video" not in recent_used and random.random() < 0.5:
        return "video"

    # 跟最近 3 条里的主题撞了就别再挑
    fresh = [th for th in pool if th not in recent_used]
    if fresh:
        pool = fresh
    elif len(pool) > 1 and used_themes:
        last = used_themes[-1]
        pool = [th for th in pool if th != last] or pool
    return random.choice(pool)


def build_user(
    theme: str,
    mood_word: str,
    recent: list[str],
    reality_facts: str = "",
) -> str:
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    lines = [
        f"现在是 {now:%Y-%m-%d} 周{weekday} {now:%H:%M}。",
        f"你今天的状态：{mood_word}。",
        f"今天想写：{THEMES[theme]}",
    ]
    if theme == "video" and reality_facts:
        lines.append(reality_facts)
    if recent:
        lines.append("最近发过这些，别重样，也别用同一种事：")
        lines += [f"· {t}" for t in recent[-5:]]
    lines.append("写一条说说，只输出正文。")
    return "\n".join(lines)


STYLE_HINTS = (
    "口语、随手，别端着。",
    "更像在发牢骚，句子短一点。",
    "可以自嘲一下，别太正经。",
    "写得具体点，说一件真事。",
)


async def generate(
    provider,
    persona: str,
    recent: list[str],
    mood_word: str,
    *,
    mood_tag: str = "calm",
    used_themes: list[str] | None = None,
    reality_facts: str = "",
    n_cand: int = 3,
    fixed_theme: str | None = None,
) -> tuple[str, str]:
    """生成一条说说，返回 (正文, 主题)。候选全不合格返回 ("", 主题)。"""
    theme = fixed_theme or pick_theme(
        recent, mood_tag, used_themes, has_reality=bool(reality_facts)
    )
    user = build_user(theme, mood_word, recent, reality_facts if theme == "video" else "")
    system = CHARACTER + "\n\n" + LIFE + "\n\n" + VOICE + "\n\n" + WRITE_RULES

    cands: list[str] = []
    fallback = ""
    for i in range(n_cand):
        hint = STYLE_HINTS[i % len(STYLE_HINTS)]
        try:
            resp = await provider.text_chat(
                prompt=user + f"\n（这次写得{hint}）", system_prompt=system
            )
        except Exception:
            continue
        text = clean(getattr(resp, "completion_text", "") or "")
        if not text:
            continue
        if not fallback and len(text) >= 8:
            fallback = text
        if hard_ok(text, recent) and text not in cands:
            cands.append(text)

    if not cands:
        # 实在写不出合格的，用一条能用的兜着，别让这个时段空掉
        if fallback and len(fallback) <= 50:
            return fallback, theme
        return "", theme
    if len(cands) == 1:
        return cands[0], theme

    listing = "\n".join(f"{i+1}. {c}" for i, c in enumerate(cands))
    try:
        resp = await provider.text_chat(prompt=listing, system_prompt=PICK)
        pick = (getattr(resp, "completion_text", "") or "").strip()
    except Exception:
        pick = ""
    m = re.search(r"[0-3]", pick)
    idx = int(m.group(0)) if m else 0
    if 0 < idx <= len(cands):
        return cands[idx - 1], theme
    return cands[0], theme
