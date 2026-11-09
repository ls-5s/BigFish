"""大肥鱼「自己补充人格」的存储层。

只做一件事：把大肥鱼自己写下的、关于她自己的稳定设定（性格 / 喜好 / 习惯 /
关系 / 经历 / 规矩）存在一个 JSON 文件里，并渲染成可以塞进人格的段落。

刻意不存主人的隐私、聊天原文、临时情绪——那些归长期记忆（livingmemory）管。
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
import threading
import time

MARK_BEGIN = "<!-- DAFEIYU_SELF_PERSONA:BEGIN -->"
MARK_END = "<!-- DAFEIYU_SELF_PERSONA:END -->"

KINDS = ("性格", "喜好", "习惯", "关系", "经历", "规矩", "其他")

_SECTION_RE = re.compile(
    re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END),
    re.S,
)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def strip_section(text: str) -> str:
    """去掉人格里由本插件维护的那一段，保留主人手写的原文。"""
    if not text:
        return ""
    had_trailing_newline = text.endswith("\n")
    cleaned = _SECTION_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if had_trailing_newline and cleaned:
        cleaned += "\n"
    return cleaned


def normalize(text: str) -> str:
    """用于查重：去掉空白和标点，英文转小写。"""
    return re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE).lower()


def clean_text(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    # 只去掉行首的列表符号，别把「2026 年」这种日期开头吃掉
    text = re.sub(r"^(?:[-*\u2022]|\d+[.、)）])\s*", "", text)
    text = text.strip(" \t\r\n\"'“”‘’「」『』")
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,。.；;、 ")
    return text


class PersonaStore:
    """线程安全的小型 JSON 存储。"""

    def __init__(
        self,
        path: str,
        max_notes: int = 60,
        max_note_chars: int = 80,
        max_total_chars: int = 1400,
    ) -> None:
        self.path = str(path)
        self.max_notes = max(1, int(max_notes))
        self.max_note_chars = max(10, int(max_note_chars))
        self.max_total_chars = max(100, int(max_total_chars))
        self._lock = threading.RLock()
        self._data = self._read()

    # ------------------------------------------------------------------ io
    def _read(self) -> dict:
        raw: dict = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            pass
        except Exception:
            # 文件坏了就挪到一边，别让插件加载失败
            try:
                broken = f"{self.path}.broken-{int(time.time())}"
                os.replace(self.path, broken)
            except OSError:
                pass
            raw = {}

        notes = []
        seen_ids = set()
        next_id = 1
        for item in raw.get("notes", []) if isinstance(raw, dict) else []:
            if not isinstance(item, dict):
                continue
            text = clean_text(item.get("text", ""), self.max_note_chars)
            if not text:
                continue
            note_id = str(item.get("id") or "").strip()
            if not note_id or note_id in seen_ids:
                while f"p{next_id}" in seen_ids:
                    next_id += 1
                note_id = f"p{next_id}"
            seen_ids.add(note_id)
            note = {
                "id": note_id,
                "text": text,
                "kind": item.get("kind") if item.get("kind") in KINDS else "其他",
                "source": "owner" if item.get("source") == "owner" else "self",
                "reason": str(item.get("reason") or "")[:80],
                "created_at": str(item.get("created_at") or now_str()),
                "updated_at": str(item.get("updated_at") or now_str()),
                "hits": max(1, int(item.get("hits") or 1)),
                "pinned": bool(item.get("pinned")),
            }
            notes.append(note)

        max_num = 0
        for note_id in seen_ids:
            match = re.fullmatch(r"p(\d+)", note_id)
            if match:
                max_num = max(max_num, int(match.group(1)))
        next_id = max(next_id, max_num + 1)

        return {
            "version": 1,
            "next_id": next_id,
            "notes": notes,
            "stats": dict(raw.get("stats") or {}) if isinstance(raw, dict) else {},
            "deleted": list(raw.get("deleted") or [])[-30:] if isinstance(raw, dict) else [],
        }

    def _write(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".persona-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # --------------------------------------------------------------- notes
    def list(self) -> list[dict]:
        with self._lock:
            return [dict(n) for n in self._data["notes"]]

    def __len__(self) -> int:
        with self._lock:
            return len(self._data["notes"])

    def add(
        self,
        text: str,
        kind: str = "性格",
        source: str = "self",
        reason: str = "",
    ) -> tuple[dict | None, str]:
        """返回 (note, status)。status: added / merged / duplicate / empty。"""
        text = clean_text(text, self.max_note_chars)
        if not text:
            return None, "empty"
        kind = kind if kind in KINDS else "其他"
        source = "owner" if source == "owner" else "self"

        with self._lock:
            norm = normalize(text)
            best = None
            best_ratio = 0.0
            for note in self._data["notes"]:
                candidate = normalize(note["text"])
                if candidate == norm:
                    note["hits"] += 1
                    note["updated_at"] = now_str()
                    self._write()
                    return note, "duplicate"
                ratio = difflib.SequenceMatcher(None, candidate, norm).ratio()
                if ratio > best_ratio:
                    best, best_ratio = note, ratio
            if best is not None and best_ratio >= 0.88:
                best["text"] = text
                best["kind"] = kind
                best["source"] = source
                best["reason"] = (reason or "")[:80]
                best["updated_at"] = now_str()
                best["hits"] += 1
                self._trim_locked()
                self._write()
                return best, "merged"

            note_id = f"p{self._data['next_id']}"
            self._data["next_id"] += 1
            note = {
                "id": note_id,
                "text": text,
                "kind": kind,
                "source": source,
                "reason": (reason or "")[:80],
                "created_at": now_str(),
                "updated_at": now_str(),
                "hits": 1,
                "pinned": False,
            }
            self._data["notes"].append(note)
            self._trim_locked()
            self._write()
            return note, "added"

    def update(
        self,
        note_id: str,
        text: str | None = None,
        kind: str | None = None,
    ) -> tuple[dict | None, str]:
        with self._lock:
            note = next((n for n in self._data["notes"] if n["id"] == note_id), None)
            if note is None:
                return None, "missing"
            if text is not None:
                cleaned = clean_text(text, self.max_note_chars)
                if not cleaned:
                    return None, "empty"
                note["text"] = cleaned
            if kind:
                note["kind"] = kind if kind in KINDS else "其他"
            note["updated_at"] = now_str()
            note["hits"] += 1
            self._trim_locked()
            self._write()
            return note, "updated"

    def remove(self, note_id: str) -> tuple[dict | None, str]:
        with self._lock:
            for i, note in enumerate(self._data["notes"]):
                if note["id"] == note_id:
                    removed = self._data["notes"].pop(i)
                    self._data["deleted"].append(removed)
                    self._data["deleted"] = self._data["deleted"][-30:]
                    self._write()
                    return removed, "removed"
            return None, "missing"

    def clear(self) -> int:
        with self._lock:
            count = len(self._data["notes"])
            self._data["deleted"].extend(self._data["notes"])
            self._data["deleted"] = self._data["deleted"][-30:]
            self._data["notes"] = []
            self._write()
            return count

    # --------------------------------------------------------------- stats
    def bump(self, key: str, amount: int = 1) -> int:
        with self._lock:
            stats = self._data.setdefault("stats", {})
            stats[key] = int(stats.get(key) or 0) + amount
            self._write()
            return stats[key]

    def stat(self, key: str) -> int:
        with self._lock:
            return int(self._data.get("stats", {}).get(key) or 0)

    # -------------------------------------------------------------- render
    def render_block(self) -> str:
        """只渲染正文（不含 HTML 标记），用于兜底注入。"""
        notes = self.list()
        if not notes:
            return ""
        lines = [f"- {n['kind']}：{n['text']}" for n in notes]
        return (
            "【你后来自己补上的设定】\n"
            "下面这些是你自己陆续记下来的，和前面的人设一样算数；"
            "聊天时自然带着，不要提「设定」「补充」这些词。\n"
            + "\n".join(lines)
        )

    def render_section(self) -> str:
        """渲染成带标记的完整段落，写进人格本体，之后可以整段替换/删除。"""
        block = self.render_block()
        if not block:
            return ""
        return f"{MARK_BEGIN}\n{block}\n{MARK_END}"

    def total_chars(self) -> int:
        return sum(len(n["text"]) + len(n["kind"]) + 4 for n in self._data["notes"])

    # -------------------------------------------------------------- private
    def _trim_locked(self) -> None:
        notes = self._data["notes"]
        while notes and (
            len(notes) > self.max_notes or self.total_chars() > self.max_total_chars
        ):
            removable = [n for n in notes if not n.get("pinned")]
            if not removable:
                break
            removable.sort(
                key=lambda n: (
                    int(n.get("hits") or 0),
                    str(n.get("updated_at") or ""),
                    0 if n.get("source") == "self" else 1,
                )
            )
            victim = removable[0]
            notes.remove(victim)
            self._data["deleted"].append(victim)
            self._data["deleted"] = self._data["deleted"][-30:]
