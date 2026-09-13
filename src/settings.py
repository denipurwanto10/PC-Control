"""Settings persisten: preferensi user tersimpan lokal (JSON).

File: config/settings.json. Semua I/O aman (gagal baca -> default,
gagal tulis -> diabaikan). Thread-safe via Lock.

Catatan diterapkannya nilai (dilakukan main.py):
- smoothing/sensitivity/cooldown/threshold -> MouseController + classify
- camera_index  -> buka ulang kamera
- mic_backend / voice_language -> restart voice thread
- mouse/hand/voice_enabled -> AppState
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

SETTINGS_FILE = Path("config/settings.json")

DEFAULTS: dict = {
    "sensitivity": 1.0,        # 0.5 - 2.0 pengali kecepatan kursor
    "smoothing": 0.7,          # 0.0 - 0.95 kehalusan kursor
    "click_threshold_px": 40,  # jarak pinch (px frame)
    "gesture_cooldown_sec": 0.6,  # jeda antar klik (detik)
    "camera_index": 0,         # 0 / 1 / 2
    "camera_flip": 1,          # 1 = cermin (normal), 0 = tanpa balik,
                               # -1 = putar 180 (kamera terbalik atas-bawah)
    "mic_backend": "auto",     # auto | pyaudio | sounddevice
    "voice_language": "id-ID",  # id-ID | en-US
    "mouse_enabled": True,
    "hand_enabled": True,
    "voice_enabled": True,
}


class SettingsStore:
    def __init__(self, file: str | Path = SETTINGS_FILE) -> None:
        self._file = Path(file)
        self._lock = threading.Lock()
        self._data: dict = dict(DEFAULTS)
        self.load()

    def load(self) -> dict:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if k in DEFAULTS:
                            self._data[k] = v
        except Exception:
            pass
        return dict(self._data)

    def save(self) -> bool:
        try:
            with self._lock:
                self._file.parent.mkdir(parents=True, exist_ok=True)
                self._file.write_text(
                    json.dumps(self._data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
            return True
        except Exception:
            return False

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            return
        with self._lock:
            self._data[key] = value

    def update(self, values: dict) -> None:
        with self._lock:
            for k, v in (values or {}).items():
                if k in DEFAULTS:
                    self._data[k] = v

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data = dict(DEFAULTS)
        self.save()
