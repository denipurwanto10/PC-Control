"""Telegram Remote Controller: kendali jarak jauh via Telegram Bot API.

Arsitektur (tidak merusak gesture/voice yang sudah ada)::

    Telegram
       v
    Telegram Controller (receiver thread: validasi + antre SAJA)
       v
    AppState telegram queue  (take_telegram di MAIN thread)
       v
    Command Processor (whitelist yang SAMA dengan voice)
       v
    Windows Controller
       v
    Windows

Keamanan:
- HANYA chat/user ID di whitelist (``TELEGRAM_ALLOWED_USER_ID``) yang
  diterima; selain itu dibalas "Unauthorized user" dan DIABAIKAN.
- HANYA command pada tabel whitelist + ``config/telegram_commands.json``
  yang diteruskan ke Command Processor. TIDAK PERNAH ada
  ``subprocess``/``os.system``/eksekusi path arbitrer dari pesan.
- Token HANYA dibaca dari environment/``.env``; tidak pernah di-hardcode,
  tidak pernah di-log, tidak pernah dikirim ke chat/GUI.

Threading:
- Satu receiver thread ("telegram-bot", daemon). Semua aksi Windows
  dieksekusi di MAIN thread via ``AppState.queue_telegram`` /
  ``take_telegram`` (pola sama seperti voice queue).
- Balasan teks/foto dikirim lewat outbox yang dikonsumsi bot thread,
  sehingga main loop (webcam/GUI/voice) tidak pernah ter-block polling
  maupun upload jaringan.
- Engine ganda: ``python-telegram-bot`` (v21+) bila terinstal, jika
  tidak memakai engine HTTP stdlib (urllib long-polling) — tanpa
  dependensi tambahan. Satu instance bot saja (guard ``start``).
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path

from .app_state import AppState

logger = logging.getLogger("telegram")

TELEGRAM_CONFIG_FILE = Path("config/telegram_commands.json")
_DOTENV_LOADED = False


def _load_env() -> None:
    """Muat .env sekali (python-dotenv bila ada; fallback parser mini)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
        return
    except ImportError:
        pass
    try:
        env_file = Path(".env")
        if not env_file.exists():
            return
        import os

        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def load_telegram_env() -> tuple[str, list[int]]:
    """(token, allowed_ids) dari environment. Token TIDAK PERNAH di-log."""
    import os

    _load_env()
    token = (os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    raw = (os.environ.get("TELEGRAM_ALLOWED_USER_ID", "") or "").strip()
    allowed: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.append(int(part))
        except ValueError:
            print(f"[TELEGRAM] Abaikan user ID tidak valid: {part!r}")
    return token, allowed


def load_custom_telegram() -> dict[str, str]:
    """/nama -> frasa voice. {} bila file hilang/rusak."""
    try:
        if not TELEGRAM_CONFIG_FILE.exists():
            return {}
        data = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str) and k and v:
                out[k.strip().lower().lstrip("/")] = v.strip()
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tabel command -> frasa voice (frasa yang SAMA dipahami voice command,
# sehingga Telegram/GUI/voice menghasilkan aksi yang sama persis).
# ---------------------------------------------------------------------------
# key: nama command telegram (tanpa '/'), value: (frasa_voice, label_tombol)
COMMAND_TABLE: dict[str, tuple[str, str]] = {
    "buka_chrome": ("buka chrome", "🌐 Chrome"),
    "buka_vscode": ("buka vs code", "💻 VS Code"),
    "buka_youtube": ("buka youtube", "📺 YouTube"),
    "screenshot": ("screenshot", "📸 Screenshot"),
    "volume_up": ("volume naik", "🔊 Vol +"),
    "volume_down": ("volume turun", "🔉 Vol -"),
    "mute": ("mute", "🔇 Mute"),
    "play": ("play", "▶️ Play"),
    "pause": ("pause", "⏸ Pause"),
    "next": ("next", "⏭ Next"),
    "previous": ("previous", "⏮ Previous"),
    "downloads": ("buka downloads", "📁 Downloads"),
    "desktop": ("buka desktop", "🖥 Desktop"),
    "documents": ("buka dokumen", "📄 Documents"),
    "minimize": ("minimize ini", "🔽 Minimize"),
    "maximize": ("maximize ini", "🔼 Maximize"),
    "mouse_on": ("aktifkan mouse", "🖱 Mouse ON"),
    "mouse_off": ("matikan mouse", "🖱 Mouse OFF"),
    "voice_on": ("mulai mendengarkan", "🎤 Voice ON"),
    "voice_off": ("berhenti mendengarkan", "🎤 Voice OFF"),
}

# Callback tombol inline -> aksi internal.
BUTTON_ACTIONS: dict[str, str] = {
    "cmd:buka_chrome": "buka_chrome",
    "cmd:buka_vscode": "buka_vscode",
    "cmd:play": "play",
    "cmd:pause": "pause",
    "cmd:volume_up": "volume_up",
    "cmd:volume_down": "volume_down",
    "cmd:previous": "previous",
    "cmd:next": "next",
    "shot": "screenshot",
    "cmd:downloads": "downloads",
    "cmd:desktop": "desktop",
    "tgl_mouse": "__toggle_mouse__",
    "tgl_voice": "__toggle_voice__",
    "status": "__status__",
    "menu": "__menu__",
}

HELP_TEXT = (
    "🤖 *LAPTOP CONTROLLER* — perintah yang tersedia:\n\n"
    "🌐 Aplikasi & Web\n"
    "/buka_chrome — buka Chrome\n"
    "/buka_vscode — buka VS Code\n"
    "/buka_youtube — buka YouTube\n\n"
    "📸 Tangkapan layar\n"
    "/screenshot — kirim screenshot ke chat ini\n\n"
    "🎵 Media & suara\n"
    "/play /pause /next /previous\n"
    "/volume_up /volume_down /mute\n\n"
    "📁 Folder & window\n"
    "/downloads /desktop /documents\n"
    "/minimize /maximize /window\n\n"
    "🖱🎤 Kontrol\n"
    "/mouse_on /mouse_off\n"
    "/voice_on /voice_off\n\n"
    "⚙️ Workflow & status\n"
    "/coding /presentasi\n"
    "/status — info CPU/RAM/uptime laptop\n"
    "/help — bantuan ini"
)


def build_main_menu() -> dict:
    """Inline keyboard utama (format dict; dikonversi per engine)."""
    return {
        "inline_keyboard": [
            [{"text": "🌐 Chrome", "callback_data": "cmd:buka_chrome"},
             {"text": "💻 VS Code", "callback_data": "cmd:buka_vscode"}],
            [{"text": "▶️ Play", "callback_data": "cmd:play"},
             {"text": "⏸ Pause", "callback_data": "cmd:pause"}],
            [{"text": "🔊 Vol +", "callback_data": "cmd:volume_up"},
             {"text": "🔉 Vol -", "callback_data": "cmd:volume_down"}],
            [{"text": "⏮ Previous", "callback_data": "cmd:previous"},
             {"text": "⏭ Next", "callback_data": "cmd:next"}],
            [{"text": "📸 Screenshot", "callback_data": "shot"}],
            [{"text": "📁 Downloads", "callback_data": "cmd:downloads"},
             {"text": "🖥 Desktop", "callback_data": "cmd:desktop"}],
            [{"text": "🖱 Mouse ON/OFF", "callback_data": "tgl_mouse"}],
            [{"text": "🎤 Voice ON/OFF", "callback_data": "tgl_voice"}],
            [{"text": "📊 Status", "callback_data": "status"}],
        ]
    }


def laptop_status_text(state: AppState) -> str:
    """Teks /status: hand/voice/window aktif/CPU/RAM/uptime."""
    snap = state.snapshot()
    hand = "ON" if snap.get("hand_enabled") else "OFF"
    voice = ("ON" if snap.get("voice_listening") else "OFF")
    typing = "ON" if snap.get("typing_mode") else "OFF"
    active = (snap.get("active_app") or "—").strip() or "—"

    cpu_txt, ram_txt = "n/a", "n/a"
    try:
        import psutil  # type: ignore

        cpu_txt = f"{psutil.cpu_percent(interval=0.3):.0f}%"
        ram_txt = f"{psutil.virtual_memory().percent:.0f}%"
    except ImportError:
        cpu_txt, ram_txt = "n/a (pip install psutil)", "n/a"
    except Exception:
        pass

    uptime = float(snap.get("uptime_sec", 0.0))
    hrs, rem = divmod(int(uptime), 3600)
    mins = rem // 60
    uptime_txt = f"{hrs}h {mins}m" if hrs else f"{mins}m"

    mic = "Available" if snap.get("voice_available") else "Unavailable"
    return (
        "💻 LAPTOP STATUS\n\n"
        "🟢 Online\n\n"
        f"Hand Gesture: {hand}\n"
        f"Voice Control: {voice}\n"
        f"Voice Typing: {typing}\n\n"
        f"Active Window:\n{active}\n\n"
        "Camera:\nAvailable\n\n"
        f"Microphone:\n{mic}\n\n"
        f"CPU:\n{cpu_txt}\n\n"
        f"RAM:\n{ram_txt}\n\n"
        f"Uptime:\n{uptime_txt}"
    )


class TelegramController:
    """Satu-satunya pintu Telegram. Non-blocking, tahan-gagal, satu instance."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._token, self._allowed = load_telegram_env()
        self._custom = load_custom_telegram()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._outbox: queue.Queue = queue.Queue()  # (kind, chat_id, payload)
        self._engine = "none"  # ptb | http | none
        self._running = False
        self._lock = threading.Lock()
        self._last_error_log = 0.0

    # ---------- info / lifecycle ----------

    @property
    def configured(self) -> bool:
        return bool(self._token and self._allowed)

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def engine(self) -> str:
        return self._engine

    def reload_custom(self) -> int:
        self._custom = load_custom_telegram()
        return len(self._custom)

    def start(self) -> bool:
        """Jalankan receiver thread. False bila tak terkonfigurasi/gagal.

        TIDAK PERNAH raise — aplikasi utama wajib tetap jalan.
        """
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return True  # jangan buat instance kedua
        if not self._token:
            print("[TELEGRAM] Token tidak ditemukan di .env "
                  "(TELEGRAM_BOT_TOKEN). Telegram control disabled.")
            print("[HAND] Hand gesture still running")
            print("[VOICE] Voice control still running")
            self._state.set_telegram_status(False)
            return False
        if not self._allowed:
            print("[TELEGRAM] TELEGRAM_ALLOWED_USER_ID kosong. "
                  "Telegram control disabled.")
            self._state.set_telegram_status(False)
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-bot",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._running = False
        self._state.set_telegram_status(False)
        # Jangan join dari dalam thread itu sendiri.
        if (self._thread and self._thread.is_alive()
                and threading.current_thread() is not self._thread):
            self._thread.join(timeout=5.0)
        print("[TELEGRAM] Telegram control stopped "
              "(hand + voice tetap berjalan).")

    # ---------- API untuk main thread ----------

    def send_message(self, chat_id: int, text: str,
                     reply_markup: dict | None = None) -> None:
        """Antrekan balasan teks (dikirim bot thread; non-blocking)."""
        try:
            self._outbox.put_nowait(("message", int(chat_id), text,
                                     reply_markup))
        except Exception:
            pass

    def send_photo(self, chat_id: int, photo_path: str,
                   caption: str = "") -> None:
        """Antrekan kirim foto screenshot (upload di bot thread)."""
        try:
            self._outbox.put_nowait(("photo", int(chat_id), photo_path,
                                     caption))
        except Exception:
            pass

    def notify(self, text: str) -> None:
        """Notifikasi ke SEMUA user whitelist (secukupnya, anti-spam)."""
        for uid in self._allowed:
            self.send_message(uid, text)

    def notify_result(self, chat_id: int, ok: bool, message: str) -> None:
        icon = "✅" if ok else "❌"
        self.send_message(chat_id, f"{icon} Command executed\n\n{message}")

    # ---------- validasi (pipeline: input -> cek -> antre) ----------

    def is_authorized(self, user_id: int | None) -> bool:
        try:
            return user_id is not None and int(user_id) in self._allowed
        except (TypeError, ValueError):
            return False

    def _display_name(self, user: dict) -> str:
        name = (user or {}).get("username") or (user or {}).get("first_name")
        return str(name or "authorized-user")[:40]

    def resolve_command(self, text: str) -> dict:
        """Validasi pesan -> rencana aksi. 'allowed=False' = tolak.

        Kembalian: dict(action=..., phrase=..., label=..., reply=...).
        action: command | screenshot | status | window | menu | help |
                start | unknown | custom:<frasa>
        """
        raw = (text or "").strip()
        if not raw:
            return {"action": "unknown", "allowed": False}
        name = raw.lstrip("/").strip().lower().split()[0]
        if name in ("start",):
            return {"action": "start", "allowed": True}
        if name in ("help", "bantuan"):
            return {"action": "help", "allowed": True}
        if name in ("status",):
            return {"action": "status", "allowed": True}
        if name in ("window", "windows"):
            return {"action": "window", "allowed": True}
        if name in ("menu", "panel", "tombol"):
            return {"action": "menu", "allowed": True}
        if name in COMMAND_TABLE:
            phrase = COMMAND_TABLE[name][0]
            return {"action": "command", "phrase": phrase, "label": "/" + name,
                    "allowed": True}
        if name in self._custom:
            return {"action": "command", "phrase": self._custom[name],
                    "label": "/" + name, "allowed": True}
        # Teks bebas (tanpa '/'): hanya teruskan bila cocok whitelist
        # intent processor — selain itu tolak (anti eksekusi arbitrer).
        if not raw.startswith("/"):
            try:
                from . import intent_detector as intent

                norm = intent._norm(raw)
                if norm:
                    ir = intent.detect(norm)
                    if ir.key is not None:
                        return {"action": "command", "phrase": raw,
                                "label": raw[:40], "allowed": True}
            except Exception:
                pass
        return {"action": "unknown", "allowed": False}

    def handle_update(self, user_id: int, user: dict, text: str,
                      chat_id: int, reply_fn) -> None:
        """Satu pintu validasi utk SEMUA engine (pesan teks)."""
        if not self.is_authorized(user_id):
            print(f"[TELEGRAM] Unauthorized user: {user_id}")
            reply_fn(chat_id, "⛔ Unauthorized user.")
            return
        if not self._state.is_telegram_enabled():
            reply_fn(chat_id, "⏸ Telegram control dimatikan dari laptop.")
            return
        plan = self.resolve_command(text)
        self._state.set_telegram_status(True, self._display_name(user))
        name = (text or "").strip().split()[0][:40] or "—"
        print(f"[TELEGRAM] Command received: {name}")
        action = plan["action"]
        if not plan.get("allowed"):
            reply_fn(chat_id,
                     f"❓ Perintah tidak dikenal: {name}\nKetik /help.")
            return
        if action == "start":
            reply_fn(chat_id,
                     "💻 *LAPTOP CONTROLLER*\n\n"
                     "Laptop terhubung. Ketik /help atau pakai tombol:",
                     reply_markup=build_main_menu())
        elif action == "help":
            reply_fn(chat_id, HELP_TEXT)
        elif action == "menu":
            reply_fn(chat_id, "💻 *LAPTOP CONTROLLER*",
                     reply_markup=build_main_menu())
        elif action in ("status", "window", "screenshot"):
            reply_fn(chat_id, {"status": "⏳ Membaca status laptop...",
                               "window": "⏳ Membaca window aktif...",
                               "screenshot": "📸 Mengambil screenshot...",
                               }[action])
            self._state.queue_telegram(action, {"chat_id": chat_id,
                                                "label": name})
        else:  # command -> Command Processor di main thread
            reply_fn(chat_id, f"⏳ Menjalankan `{name}` ...")
            self._state.queue_telegram("command",
                                       {"chat_id": chat_id,
                                        "phrase": plan["phrase"],
                                        "label": name})
        print(f"[TELEGRAM] Action executed: {action}"
              f" ({plan.get('phrase', plan.get('action'))})")

    def handle_callback(self, user_id: int, user: dict, data: str,
                        chat_id: int, reply_fn, answer_fn) -> None:
        """Satu pintu validasi utk SEMUA tombol inline."""
        if not self.is_authorized(user_id):
            print(f"[TELEGRAM] Unauthorized user: {user_id}")
            answer_fn("⛔ Unauthorized user.")
            return
        if not self._state.is_telegram_enabled():
            answer_fn("⏸ Telegram control dimatikan.")
            return
        key = (data or "").strip()
        mapped = BUTTON_ACTIONS.get(key)
        self._state.set_telegram_status(True, self._display_name(user))
        print(f"[TELEGRAM] Command received: [button {key}]")
        if mapped is None or mapped == "__menu__":
            reply_fn(chat_id, "💻 *LAPTOP CONTROLLER*",
                     reply_markup=build_main_menu())
            answer_fn("OK")
            return
        if mapped == "__status__":
            answer_fn("⏳ Membaca status...")
            self._state.queue_telegram("status", {"chat_id": chat_id,
                                                  "label": "[📊 Status]"})
        elif mapped == "__toggle_mouse__":
            answer_fn("⏳ Mengubah mouse...")
            self._state.queue_telegram(
                "toggle", {"chat_id": chat_id, "target": "mouse",
                           "label": "[🖱 Mouse ON/OFF]"})
        elif mapped == "__toggle_voice__":
            answer_fn("⏳ Mengubah voice...")
            self._state.queue_telegram(
                "toggle", {"chat_id": chat_id, "target": "voice",
                           "label": "[🎤 Voice ON/OFF]"})
        elif mapped == "screenshot":
            answer_fn("📸 Mengambil screenshot...")
            self._state.queue_telegram("screenshot",
                                       {"chat_id": chat_id,
                                        "label": "[📸 Screenshot]"})
        else:
            phrase = COMMAND_TABLE.get(mapped, (mapped, ""))[0]
            answer_fn("⏳ Menjalankan...")
            self._state.queue_telegram("command",
                                       {"chat_id": chat_id, "phrase": phrase,
                                        "label": f"[{mapped}]"})
        print(f"[TELEGRAM] Action executed: button {key}")

    # ---------- receiver thread ----------

    def _run(self) -> None:
        try:
            import telegram as _tg  # python-telegram-bot

            _ = getattr(_tg, "__version__", "?")
            self._engine = "ptb"
            self._run_ptb()
        except ImportError:
            self._engine = "http"
            self._run_http()
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        # Jangan pernah tampilkan token; pesan ramah + app tetap jalan.
        with self._lock:
            self._running = False
        self._state.set_telegram_status(False)
        print("[TELEGRAM] Connection failed")
        print("[TELEGRAM] Telegram control disabled")
        print("[HAND] Hand gesture still running")
        print("[VOICE] Voice control still running")
        now = time.time()
        if now - self._last_error_log > 60:
            self._last_error_log = now
            logger.warning("telegram disabled: %s", type(exc).__name__)

    def _mark_connected(self) -> None:
        with self._lock:
            self._running = True
        self._state.set_telegram_status(True)
        print("[TELEGRAM] Bot connected")
        print("[TELEGRAM] Waiting for commands...")
        try:
            self.notify("💻 Laptop Controller\n\n"
                        "Application started successfully.")
        except Exception:
            pass

    # ----- engine 1: python-telegram-bot (v21+, asyncio di thread ini) -----

    def _run_ptb(self) -> None:
        import asyncio

        asyncio.run(self._ptb_main())

    async def _ptb_main(self) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
        from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                                  CommandHandler, MessageHandler, filters)

        app = (ApplicationBuilder().token(self._token)
               .concurrent_updates(True).build())
        loop = asyncio.get_running_loop() if hasattr(asyncio, "get_running_loop") else None
        _ = loop

        def _reply(chat_id: int, text: str,
                   reply_markup: dict | None = None) -> None:
            markup = None
            if reply_markup:
                rows = [[InlineKeyboardButton(b["text"],
                                              callback_data=b["callback_data"])
                         for b in row]
                        for row in reply_markup.get("inline_keyboard", [])]
                markup = InlineKeyboardMarkup(rows)
            self._outbox.put(("send", chat_id, text, markup))

        async def _on_text(update: Update, _ctx) -> None:
            try:
                msg = update.effective_message
                user = update.effective_user
                self.handle_update(
                    user.id if user else None,
                    {"username": user.username if user else "",
                     "first_name": user.first_name if user else ""},
                    msg.text or "", msg.chat_id, _reply)
            except Exception as exc:
                logger.warning("ptb text handler: %s", exc)

        async def _on_button(update: Update, _ctx) -> None:
            try:
                q = update.callback_query
                user = update.effective_user
                answers: list[str] = []

                def _answer(t: str) -> None:
                    answers.append(t)

                assert q is not None
                self.handle_callback(
                    user.id if user else None,
                    {"username": user.username if user else "",
                     "first_name": user.first_name if user else ""},
                    q.data or "", q.message.chat_id if q.message else 0,
                    _reply, _answer)
                try:
                    await q.answer(text=answers[0] if answers else None)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("ptb button handler: %s", exc)

        async def _sender() -> None:
            while not self._stop.is_set():
                try:
                    item = self._outbox.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    await self._ptb_send(app, item)
                except Exception as exc:
                    logger.warning("ptb send: %s", type(exc).__name__)

        app.add_handler(CommandHandler(
            ["start", "help", "menu", "status", "window", "screenshot",
             "buka_chrome", "buka_vscode", "buka_youtube", "volume_up",
             "volume_down", "mute", "play", "pause", "next", "previous",
             "downloads", "desktop", "documents", "minimize", "maximize",
             "mouse_on", "mouse_off", "voice_on", "voice_off", "coding",
             "kerja", "presentasi", "santai"],
            _on_text))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                        _on_text))
        app.add_handler(CallbackQueryHandler(_on_button))

        try:
            await app.initialize()
            await app.start()
            # Verifikasi token sebelum polling (getMe gagal = token salah).
            me = await app.bot.get_me()
            logger.info("bot @%s connected", getattr(me, "username", "?"))
            self._mark_connected()
            sender_task = asyncio.create_task(_sender())
            await app.updater.start_polling(drop_pending_updates=True)
            while not self._stop.is_set() and self._state.is_running():
                await asyncio.sleep(0.3)
        except Exception as exc:
            raise exc
        finally:
            try:
                sender_task.cancel()  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                await app.updater.stop()
            except Exception:
                pass
            try:
                await app.stop()
                await app.shutdown()
            except Exception:
                pass
            with self._lock:
                self._running = False
            self._state.set_telegram_status(False)

    async def _ptb_send(self, app, item) -> None:
        kind = item[0]
        if kind == "send":
            _, chat_id, text, markup = item
            await app.bot.send_message(chat_id=chat_id, text=text,
                                       parse_mode="Markdown",
                                       reply_markup=markup)
        elif kind == "message":
            _, chat_id, text, markup_dict = item
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            markup = None
            if markup_dict:
                rows = [[InlineKeyboardButton(b["text"],
                                              callback_data=b["callback_data"])
                         for b in row]
                        for row in markup_dict.get("inline_keyboard", [])]
                markup = InlineKeyboardMarkup(rows)
            await app.bot.send_message(chat_id=chat_id, text=text,
                                       parse_mode="Markdown",
                                       reply_markup=markup)
        elif kind == "photo":
            _, chat_id, path, caption = item
            from telegram import InputFile

            try:
                with open(path, "rb") as fh:
                    await app.bot.send_photo(
                        chat_id=chat_id, photo=InputFile(fh),
                        caption=caption[:200] if caption else None)
            except FileNotFoundError:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Screenshot gagal: file tidak ditemukan.")

    # ----- engine 2: HTTP stdlib (urllib long-polling, tanpa dep baru) -----

    def _api(self, method: str, payload: dict | None = None,
             files: dict | None = None, timeout: int = 40) -> dict:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{self._token}/{method}"
        data: bytes | None = None
        headers: dict[str, str] = {}
        if files:
            boundary = "----tg%d" % int(time.time() * 1000)
            headers["Content-Type"] = (
                "multipart/form-data; boundary=" + boundary)
            body = bytearray()
            for k, v in (payload or {}).items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                         f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
            for field, (fname, content, ctype) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                         f"name=\"{field}\"; filename=\"{fname}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n").encode() + content
                body += f"\r\n--{boundary}--\r\n".encode()
            data = bytes(body)
        elif payload is not None:
            data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _http_reply(self, chat_id: int, text: str,
                    reply_markup: dict | None = None) -> None:
        payload: dict = {"chat_id": chat_id, "text": text,
                         "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup,
                                                 ensure_ascii=False)
        try:
            self._api("sendMessage", payload, timeout=20)
        except Exception as exc:
            logger.warning("http send: %s", type(exc).__name__)

    def _http_answer(self, callback_id: str, text: str = "") -> None:
        try:
            self._api("answerCallbackQuery",
                      {"callback_query_id": callback_id, "text": text[:180]},
                      timeout=15)
        except Exception:
            pass

    def _run_http(self) -> None:
        try:
            me = self._api("getMe", {}, timeout=20)
            if not me.get("ok"):
                raise RuntimeError("getMe not ok (token salah?)")
        except Exception as exc:
            self._fail(exc)
            return
        with self._lock:
            self._running = True
        self._mark_connected()
        offset = 0
        try:
            while not self._stop.is_set() and self._state.is_running():
                # 1. Kirim antrean balasan dulu (non-blocking utk main app).
                while True:
                    try:
                        item = self._outbox.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._http_drain(item)
                    except Exception as exc:
                        logger.warning("http drain: %s",
                                       type(exc).__name__)
                # 2. Long-poll update.
                try:
                    res = self._api("getUpdates",
                                    {"offset": offset, "timeout": 25,
                                     "allowed_updates": json.dumps(
                                         ["message", "callback_query"])},
                                    timeout=40)
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    time.sleep(3.0)
                    logger.warning("poll: %s", type(exc).__name__)
                    continue
                for upd in res.get("result", []):
                    offset = max(offset, int(upd.get("update_id", 0)) + 1)
                    self._dispatch_http(upd)
        finally:
            with self._lock:
                self._running = False
            self._state.set_telegram_status(False)

    def _http_drain(self, item) -> None:
        kind = item[0]
        if kind in ("message", "send"):
            _, chat_id, text = item[0], item[1], item[2]
            markup = item[3] if len(item) > 3 else None
            self._http_reply(chat_id, text, markup)
        elif kind == "photo":
            _, chat_id, path, caption = item
            try:
                with open(path, "rb") as fh:
                    content = fh.read()
            except FileNotFoundError:
                self._http_reply(chat_id, "❌ Screenshot gagal: "
                                          "file tidak ditemukan.")
                return
            import os as _os

            self._api("sendPhoto",
                      {"chat_id": chat_id,
                       "caption": (caption or "")[:200]},
                      files={"photo": (_os.path.basename(path), content,
                                       "image/png")},
                      timeout=60)

    def _dispatch_http(self, upd: dict) -> None:
        try:
            if "callback_query" in upd:
                cq = upd["callback_query"]
                user = cq.get("from", {})
                msg = cq.get("message") or {}
                chat = msg.get("chat") or {}
                cb_id = cq.get("id", "")
                self.handle_callback(
                    user.get("id"), user, cq.get("data", ""),
                    chat.get("id", 0),
                    lambda cid, txt, reply_markup=None: self._http_reply(
                        cid, txt, reply_markup),
                    lambda txt="": self._http_answer(cb_id, txt))
            elif "message" in upd:
                msg = upd["message"]
                user = msg.get("from", {})
                chat = msg.get("chat") or {}
                self.handle_update(
                    user.get("id"), user, msg.get("text", ""),
                    chat.get("id", 0),
                    lambda cid, txt, reply_markup=None: self._http_reply(
                        cid, txt, reply_markup))
        except Exception as exc:
            logger.warning("dispatch: %s", exc)
