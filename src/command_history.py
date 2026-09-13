"""Riwayat command: simpan lokal (JSON) + format tampilan GUI.

Entri: {time, command, intent, action, ok, error}. Disimpan di
data/command_history.json (maks N entri terakhir). Semua I/O dibungkus
try/except agar tidak crash. Field intent/error opsional agar file
lama tetap terbaca (backward compatible).
"""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path


class CommandHistory:
    def __init__(self, file: str = "data/command_history.json",
                 max_entries: int = 50) -> None:
        self._file = Path(file)
        self._max = max(1, max_entries)
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self.load()

    def load(self) -> None:
        try:
            if self._file.exists():
                data = json.loads(self._file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._items = [d for d in data if isinstance(d, dict)][-self._max:]
        except Exception:
            self._items = []

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._items, ensure_ascii=False,
                                             indent=1), encoding="utf-8")
        except Exception:
            pass

    def add(self, command: str, action: str, ok: bool,
              intent: str = "", error: str = "") -> None:
        with self._lock:
            entry = {
                "time": datetime.datetime.now().strftime("%H:%M"),
                "command": (command or "")[:60],
                "action": (action or "")[:80],
                "ok": bool(ok),
            }
            if intent:
                entry["intent"] = intent[:40]
            if error and not ok:
                entry["error"] = error[:120]
            self._items.append(entry)
            self._items = self._items[-self._max:]
            self._save()

    def recent(self, n: int = 15) -> list[dict]:
        with self._lock:
            return list(self._items[-n:])[::-1]

    def formatted(self, n: int = 15) -> str:
        rows = self.recent(n)
        if not rows:
            return "Belum ada riwayat."
        lines = ["VOICE HISTORY", ""]
        for r in rows:
            mark = "✓" if r.get("ok") else "✗"
            lines.append(f"{r.get('time','--:--')}  "
                         f"{r.get('command','')[:28]:28}  {mark}")
        return "\n".join(lines)
