"""按文案关键词挑表情包：从「主题目录」里优先选跟正文对得上的，避开最近用过的。"""
from __future__ import annotations

import random
import re
from pathlib import Path

# 文案里的词 → 表情包文件名里的词
SYNONYMS: dict[str, tuple[str, ...]] = {
    "吃": ("吃", "馋", "干杯", "蛋糕", "爆米花", "甜甜圈", "西瓜", "饮料", "勺子", "筷子"),
    "嚼": ("吃", "馋", "爆米花"),
    "饿": ("馋", "吃", "饿"),
    "馋": ("馋", "吃", "蛋糕", "甜甜圈"),
    "睡": ("睡觉", "疲倦", "小睡", "电风扇"),
    "困": ("睡觉", "疲倦", "小睡"),
    "累": ("疲倦", "停止工作", "睡觉"),
    "瘫": ("睡觉", "停止工作", "小睡"),
    "懒": ("睡觉", "停止工作"),
    "笑": ("笑", "点赞", "庆祝", "开心", "期待"),
    "高兴": ("笑", "庆祝", "开心"),
    "烦": ("生气", "嫌弃", "翻白眼", "摇头"),
    "气": ("生气", "拖鞋", "敲头", "烧"),
    "哭": ("哭", "委屈", "被击中"),
    "难过": ("哭", "委屈", "sad"),
    "怕": ("害怕", "紧张", "惊吓"),
    "慌": ("害怕", "紧张", "汗"),
    "想": ("期待", "思考", "呆"),
    "等": ("期待", "思考", "呆"),
    "钱": ("钱", "红包", "刷卡", "要米", "期待"),
    "穷": ("钱", "红包", "拿走我的钱"),
    "面试": ("紧张", "期待", "思考", "汗"),
    "考试": ("工作", "思考", "紧张"),
    "熬夜": ("睡觉", "疲倦", "工作"),
    "夜": ("睡觉", "疲倦"),
    "黏": ("爱心", "贴", "摸头", "舔舔"),
    "贴": ("爱心", "摸头", "贴"),
    "抱": ("爱心", "摸头"),
    "喜欢": ("爱心", "害羞", "情书", "玫瑰"),
    "爱": ("爱心", "害羞", "玫瑰"),
    "鱼": ("呆", "冒泡", "游泳", "复活节"),
    "胖": ("吃", "馋", "呆"),
    "键盘": ("打字", "工作"),
    "风扇": ("电风扇", "睡觉"),
    "屏幕": ("屏幕", "抓拍"),
    "群": ("聊天", "扩音器", "打招呼"),
}


def _text_words(text: str) -> set[str]:
    out: set[str] = set()
    for k in SYNONYMS:
        if k in text:
            out.add(k)
    return out


def _img_terms(p: Path) -> set[str]:
    name = p.stem
    return {k for k in SYNONYMS if k in name} | {name}


def rank_images(text: str, files: list[Path]) -> list[Path]:
    """按「跟正文的贴合度」排序；贴合的排前面，随机打散同分的。"""
    words = _text_words(text)
    if not words:
        return list(files)

    def score(p: Path) -> int:
        name = p.stem
        hit = 0
        for w in words:
            for syn in SYNONYMS[w]:
                if syn in name:
                    hit += 2
        return hit

    scored = [(score(p), p) for p in files]
    good = [p for s, p in scored if s > 0]
    rest = [p for s, p in scored if s <= 0]
    random.shuffle(good)
    random.shuffle(rest)
    # 贴合的权重高一些，但也不是死死只用它们
    return good * 3 + rest


def choose(text: str, files: list[Path], recent: list[str] | None = None) -> Path | None:
    if not files:
        return None

    words = _text_words(text)
    good: list[Path] = []
    for p in files:
        name = p.stem
        hit = sum(1 for w in words for syn in SYNONYMS[w] if syn in name)
        if hit >= 2:
            good.append(p)

    # 有明确贴合的就在里面挑（并避开最近用过的），否则在主题目录里随便挑
    pool = good or files
    if recent:
        recent_names = {Path(x).stem for x in recent if x}
        fresh = [p for p in pool if p.stem not in recent_names]
        if fresh:
            pool = fresh
    return random.choice(pool) if pool else None
