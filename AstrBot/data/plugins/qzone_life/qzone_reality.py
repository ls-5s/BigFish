"""把「刷B站日报」变成她今天真的经历过的事，喂给发说说。

日报在 C:\\Users\\86177\\.dsh\\bili-duty\\out\\YYYY-MM-DD.md，
每条视频都有标题 + 一句话点评。只取标题和一句话，不搬运长文。
"""
from __future__ import annotations

import random
import re
from datetime import date
from pathlib import Path

REPORT_DIR = Path(r"C:\Users\86177\.dsh\bili-duty\out")


def _read(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def today_videos(day: date | None = None) -> list[dict]:
    day = day or date.today()
    path = REPORT_DIR / f"{day:%Y-%m-%d}.md"
    if not path.exists():
        return []
    text = _read(path)
    out: list[dict] = []
    blocks = re.split(r"^### (BV\w+)\s*$", text, flags=re.M)
    for i in range(1, len(blocks) - 1, 2):
        bvid, body = blocks[i], blocks[i + 1]

        def grab(key: str) -> str:
            m = re.search(rf"^-\s*{key}[：:]\s*(.+)$", body, flags=re.M)
            return m.group(1).strip() if m else ""

        title = grab("标题")
        one = grab("一句话")
        if not title:
            continue
        out.append({"bvid": bvid, "title": title, "one": one})
    return out


def pick_video(day: date | None = None, exclude: set[str] | None = None) -> dict:
    """随机挑一条今天看过的，优先有「一句话」的；可以排除发过的。"""
    vids = today_videos(day)
    if not vids:
        return {}
    skip = exclude or set()
    fresh = [v for v in vids if v.get("bvid") not in skip]
    pool = fresh or vids
    with_one = [v for v in pool if v.get("one")]
    return random.choice(with_one or pool)


def video_facts(v: dict) -> str:
    title = (v.get("title") or "").strip()
    one = (v.get("one") or "").strip()
    lines = [f"- 今天刷到一个视频，标题是《{title}》"]
    if one:
        lines.append(f"- 看完的感想：{one}")
    lines.append("- 她可以就这个视频的想法/吐槽写一条说说；别提「B站」「视频」这些平台词，也别复述标题。")
    return "\n".join(lines)
