"""Status aplikasi terpusat yang aman diakses lintas thread.

Voice thread menulis status voice; hand/GUI loop menulis status gesture;
tombol GUI dan voice command mengubah flag kontrol. Semua akses dijaga
dengan satu Lock agar tidak ada race condition.
"""
from __future__ import annotations

import threading
import time


class AppState:
    """Single source of truth untuk seluruh status aplikasi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Flag kontrol (bisa diubah dari GUI maupun voice command).
        self.mouse_enabled = True
        self.hand_enabled = True      # False -> hand tracking diskip total
        self.voice_listening = True   # voice loop berjalan & memproses suara
        self.voice_available = False  # True bila mic + SR berhasil init
        self.running = True           # False -> semua loop berhenti
        self.camera_on = True         # False -> frame diskip (hemat CPU)
        self.presentation_mode = False
        self.typing_mode = False      # True -> ucapan diketik, bukan command

        # Status real-time (ditampilkan di GUI).
        self.gesture = "NO_HAND"
        self.gesture_action = "—"
        self.fps = 0.0
        self.active_window = "—"
        self.active_app = "—"
        self.intent = "—"
        self.intent_detail = ""
        self.voice_status = "STOPPED"  # LISTENING | STOPPED | ERROR | UNAVAILABLE
        self.last_voice: str = "—"
        self.last_command_status: str = "—"
        self.voice_error: str = ""

        # Event agar aksi command dieksekusi di main thread (wajib untuk
        # pyautogui/GUI di Windows — tidak aman dari worker thread).
        self._pending: list[str] = []
        self.updated_at = time.time()

        # Telegram Remote Controller (§Telegram): receiver thread hanya
        # memvalidasi + mengantre; eksekusi SELALU di main thread via
        # antrean di bawah (pola sama seperti voice queue).
        self.telegram_enabled = True     # False -> receiver dimatikan (GUI)
        self.telegram_connected = False  # True setelah getMe/polling OK
        self.telegram_user = "—"         # username terakhir yang authorized
        self.telegram_last_cmd = "—"     # command/button terakhir
        self._tg_pending: list[dict] = []
        self.boot_time = time.time()     # untuk uptime di /status

    # ---------- flag kontrol ----------

    def set_mouse(self, enabled: bool) -> None:
        with self._lock:
            self.mouse_enabled = bool(enabled)

    def toggle_mouse(self) -> bool:
        with self._lock:
            self.mouse_enabled = not self.mouse_enabled
            return self.mouse_enabled

    def set_hand(self, enabled: bool) -> None:
        with self._lock:
            self.hand_enabled = bool(enabled)

    def toggle_hand(self) -> bool:
        with self._lock:
            self.hand_enabled = not self.hand_enabled
            return self.hand_enabled

    def is_hand_enabled(self) -> bool:
        with self._lock:
            return self.hand_enabled

    def set_listening(self, listening: bool) -> None:
        with self._lock:
            self.voice_listening = bool(listening)

    def set_camera(self, on: bool) -> None:
        with self._lock:
            self.camera_on = bool(on)

    def is_camera_on(self) -> bool:
        with self._lock:
            return self.camera_on

    def set_presentation(self, on: bool) -> None:
        with self._lock:
            self.presentation_mode = bool(on)

    def is_presentation(self) -> bool:
        with self._lock:
            return self.presentation_mode

    def set_typing(self, on: bool) -> None:
        with self._lock:
            self.typing_mode = bool(on)

    def is_typing(self) -> bool:
        with self._lock:
            return self.typing_mode

    def stop(self) -> None:
        with self._lock:
            self.running = False

    def is_running(self) -> bool:
        with self._lock:
            return self.running

    def is_mouse_enabled(self) -> bool:
        with self._lock:
            return self.mouse_enabled

    def is_listening(self) -> bool:
        with self._lock:
            return self.voice_listening

    # ---------- status real-time ----------

    def set_gesture(self, gesture: str, action: str, fps: float) -> None:
        with self._lock:
            self.gesture = gesture
            self.gesture_action = action
            self.fps = float(fps)
            self.updated_at = time.time()

    def set_voice_status(self, status: str, error: str = "") -> None:
        with self._lock:
            self.voice_status = status
            self.voice_error = error

    def set_voice_available(self, available: bool) -> None:
        with self._lock:
            self.voice_available = bool(available)

    def set_active_window(self, title: str, app: str = "") -> None:
        with self._lock:
            self.active_window = (title or "—")[:60]
            if app:
                self.active_app = app[:40]

    def set_intent(self, intent: str, detail: str = "") -> None:
        with self._lock:
            self.intent = (intent or "—")[:40]
            self.intent_detail = (detail or "")[:60]

    # ---------- command queue (voice thread -> main thread) ----------

    def queue_command(self, text: str) -> None:
        """Voice thread memanggil ini; main thread mengeksekusinya.

        Antrean FIFO dibatasi 5 agar chaining yang cepat + perintah
        beruntun tidak menumpuk dan dieksekusi berulang.
        """
        with self._lock:
            text = (text or "").strip()
            if not text:
                return
            # Anti-duplikat: abaikan teks sama yang masih antre/belum lama.
            if self._pending and self._pending[-1] == text:
                return
            self._pending.append(text)
            self._pending = self._pending[-5:]
            self.last_voice = text

    def take_command(self) -> str | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pending.pop(0)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def set_command_result(self, status: str) -> None:
        with self._lock:
            self.last_command_status = status

    # ---------- telegram queue (receiver thread -> main thread) ----------

    def set_telegram_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.telegram_enabled = bool(enabled)

    def is_telegram_enabled(self) -> bool:
        with self._lock:
            return self.telegram_enabled

    def set_telegram_status(self, connected: bool, user: str = "") -> None:
        with self._lock:
            self.telegram_connected = bool(connected)
            if user:
                self.telegram_user = user[:40]

    def is_telegram_connected(self) -> bool:
        with self._lock:
            return self.telegram_connected

    def queue_telegram(self, kind: str, payload: dict) -> None:
        """Receiver Telegram memanggil ini; MAIN thread mengeksekusinya.

        kind: 'command' (frasa voice utk processor) | 'screenshot'
              | 'status' | 'window' | 'notify_*' | 'control_*'.
        """
        with self._lock:
            if not self.telegram_enabled or not self.running:
                return
            item = {"kind": kind, "payload": dict(payload or {})}
            self._tg_pending.append(item)
            self._tg_pending = self._tg_pending[-10:]
            label = payload.get("label") or payload.get("text", "")
            if label:
                self.telegram_last_cmd = str(label)[:60]

    def take_telegram(self) -> dict | None:
        with self._lock:
            if not self._tg_pending:
                return None
            return self._tg_pending.pop(0)

    def telegram_pending_count(self) -> int:
        with self._lock:
            return len(self._tg_pending)

    # ---------- snapshot sekali baca untuk GUI ----------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mouse_enabled": self.mouse_enabled,
                "hand_enabled": self.hand_enabled,
                "voice_listening": self.voice_listening,
                "voice_available": self.voice_available,
                "running": self.running,
                "camera_on": self.camera_on,
                "presentation_mode": self.presentation_mode,
                "typing_mode": self.typing_mode,
                "gesture": self.gesture,
                "gesture_action": self.gesture_action,
                "fps": self.fps,
                "active_window": self.active_window,
                "active_app": self.active_app,
                "intent": self.intent,
                "intent_detail": self.intent_detail,
                "voice_status": self.voice_status,
                "last_voice": self.last_voice,
                "last_command_status": self.last_command_status,
                "voice_error": self.voice_error,
                "pending": len(self._pending),
                "telegram_enabled": self.telegram_enabled,
                "telegram_connected": self.telegram_connected,
                "telegram_user": self.telegram_user,
                "telegram_last_cmd": self.telegram_last_cmd,
                "uptime_sec": time.time() - self.boot_time,
            }
