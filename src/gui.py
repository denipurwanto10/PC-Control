"""GUI modern & responsif: dark theme, kartu status, video adaptif.

Fitur tampilan:
- Video webcam otomatis mengikuti ukuran window (jaga aspek rasio).
- Teks status wrap otomatis mengikuti lebar kolom.
- Layout proporsional (grid weight) + ukuran window minimum, aman
  dimaksimalkan.
- Kartu Status sesuai spek: Camera, Hand Tracking, Mouse Control,
  Voice Control, Voice Typing, Active Window, Gesture, Last Voice,
  Intent, Last Action, FPS.
- Pill status global beranimasi saat LISTENING, warna nilai mengikuti
  state (gesture, FPS, hand, voice).
- Tombol: Camera, Hand Gesture, Mouse, Voice, Voice Typing,
  Presentation, Settings, Exit — berwarna dengan efek hover.
- Tab "Perintah" (daftar frasa suara, scroll) + tab "Riwayat"
  (voice history) + tab "Log" (riwayat aktivitas dengan timestamp).
- Dialog Settings (§15): sensitivitas, smoothing, click threshold,
  gesture cooldown, mic backend/device, kamera, bahasa, enable/disable.
- Toggle tema dark/light, footer berisi shortcut keyboard.
- Update StringVar hanya saat nilai berubah (anti-flicker, hemat CPU).

Semua perubahan state tetap lewat AppState; callback tombol hanya
memanggil handler main. Konstruktor menerima callback opsional agar
kompatibel dengan pemanggil lama maupun baru.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import cv2

from .app_state import AppState
from .command_processor import CommandProcessor
from .config import GuiConfig

# Palet dark profesional.
_DARK = {
    "bg": "#0f172a",        # slate-900
    "panel": "#1e293b",     # slate-800
    "panel2": "#16213a",
    "border": "#334155",    # slate-700
    "text": "#e2e8f0",      # slate-200
    "muted": "#94a3b8",     # slate-400
    "accent": "#38bdf8",    # sky-400
    "violet": "#a78bfa",
    "green": "#22c55e",
    "green_bg": "#14532d",
    "amber": "#f59e0b",
    "amber_bg": "#78350f",
    "red": "#ef4444",
    "red_bg": "#7f1d1d",
    "grey_bg": "#334155",
    "log_bg": "#0b1220",
}
_LIGHT = {
    "bg": "#f1f5f9",
    "panel": "#ffffff",
    "panel2": "#f8fafc",
    "border": "#cbd5e1",
    "text": "#0f172a",
    "muted": "#64748b",
    "accent": "#0284c7",
    "violet": "#7c3aed",
    "green": "#16a34a",
    "green_bg": "#dcfce7",
    "amber": "#b45309",
    "amber_bg": "#fef3c7",
    "red": "#dc2626",
    "red_bg": "#fee2e2",
    "grey_bg": "#e2e8f0",
    "log_bg": "#f8fafc",
}

_FONT_TITLE = ("Segoe UI", 15, "bold")
_FONT_SUB = ("Segoe UI", 9)
_FONT_SECTION = ("Segoe UI", 10, "bold")
_FONT_BODY = ("Segoe UI", 9)
_FONT_VALUE = ("Segoe UI", 9, "bold")
_FONT_MONO = ("Consolas", 9)
_FONT_LOG = ("Consolas", 8)

# Warna teks per gesture.
_GESTURE_COLORS = {
    "MOVE": "accent",
    "POINTER": "accent",
    "PINCH": "amber",
    "R_CLICK": "amber",
    "DOUBLE": "amber",
    "SCROLL": "violet",
    "ZOOM": "violet",
    "NEXT": "green",
    "PREV": "green",
    "PAUSE": "muted",
    "NO_HAND": "muted",
}


def _shade(hex_color: str, factor: float) -> str:
    """Gelapkan/terangkan warna hex (factor <1 gelap, >1 terang)."""
    try:
        c = hex_color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


class AppGui:
    def __init__(
        self,
        config: GuiConfig,
        state: AppState,
        processor: CommandProcessor,
        settings=None,
        on_toggle_mouse=None,
        on_toggle_voice=None,
        on_toggle_camera=None,
        on_toggle_hand=None,
        on_toggle_presentation=None,
        on_toggle_typing=None,
        on_toggle_telegram=None,
        on_open_settings=None,
        on_exit=None,
    ) -> None:
        self._cfg = config
        self._state = state
        self._processor = processor
        self._settings = settings
        self._on_toggle_mouse = on_toggle_mouse or (lambda: None)
        self._on_toggle_voice = on_toggle_voice or (lambda: None)
        self._on_toggle_camera = on_toggle_camera or (lambda: None)
        self._on_toggle_hand = on_toggle_hand or self._on_toggle_mouse
        self._on_toggle_presentation = on_toggle_presentation or (lambda: None)
        self._on_toggle_typing = on_toggle_typing or (lambda: None)
        self._on_toggle_telegram = on_toggle_telegram or (lambda: None)
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit or (lambda: None)

        self._theme = config.theme if config.theme in ("dark", "light") else "dark"
        self._pal = self._make_palette()

        self.root = tk.Tk()
        self.root.title(config.title)
        self.root.configure(bg=self._pal["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._enable_dpi_awareness()
        try:
            self.root.geometry("1180x740")
            self.root.minsize(920, 620)
        except Exception:
            pass

        try:
            from PIL import Image, ImageTk  # type: ignore

            self._Image, self._ImageTk = Image, ImageTk
            try:
                self._resample = Image.Resampling.BILINEAR
            except AttributeError:  # Pillow lama
                self._resample = Image.BILINEAR
        except ImportError:
            self._Image, self._ImageTk, self._resample = None, None, None

        self._style = ttk.Style(self.root)
        try:
            self._style.theme_use("clam")
        except Exception:
            pass

        # Cache anti-flicker + state internal.
        self._cache: dict[str, str] = {}
        self._video_target = (config.video_width, config.video_height)
        self._frame_aspect = config.video_width / max(1, config.video_height)
        self._dyn_labels: list[tk.Label] = []  # label nilai (recolor saat ganti tema)
        self._seen = {"voice": None, "cmd": None, "vstatus": None,
                      "mouse": None, "hand": None, "pres": None, "typing": None,
                      "cam": None, "hist": None, "tg": None, "tgcmd": None}
        self._closed = False

        self._apply_style()
        self._build()
        self._log_event("Aplikasi dimulai.")

    # ---------- tema & style ----------

    def _make_palette(self) -> dict:
        pal = dict(_LIGHT if self._theme == "light" else _DARK)
        if self._cfg.accent:
            pal["accent"] = self._cfg.accent
        return pal

    def _enable_dpi_awareness(self) -> None:
        """Teks tajam di layar HiDPI Windows (aman bila gagal)."""
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
            dpi = self.root.winfo_fpixels("1i")
            if dpi > 0:
                self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

    def _apply_style(self) -> None:
        p = self._pal
        s = self._style
        s.configure("App.TFrame", background=p["bg"])
        s.configure("Card.TFrame", background=p["panel"])
        s.configure("Card.TLabelframe", background=p["panel"],
                    bordercolor=p["border"])
        s.configure("Card.TLabelframe.Label", background=p["panel"],
                    foreground=p["accent"], font=_FONT_SECTION)
        s.configure("App.TLabel", background=p["panel"],
                    foreground=p["text"], font=_FONT_BODY)
        s.configure("Muted.TLabel", background=p["panel"],
                    foreground=p["muted"], font=_FONT_BODY)
        s.configure("Video.TLabel", background="#000000",
                    foreground="#ffffff", font=_FONT_BODY)
        s.configure("Card.TNotebook", background=p["panel"],
                    bordercolor=p["border"])
        s.configure("Card.TNotebook.Tab", padding=(10, 4),
                    font=("Segoe UI", 9, "bold"))
        try:
            s.configure("Card.Vertical.TScrollbar", background=p["panel"])
        except Exception:
            pass
        self._btn_style = {
            "font": ("Segoe UI", 10, "bold"),
            "bd": 0, "relief": "flat", "cursor": "hand2",
            "padx": 10, "pady": 9,
        }

    def _make_button(self, parent, text, command, kind="accent"):
        p = self._pal
        colors = {
            "accent": (p["accent"], "#0f172a"),
            "green": (p["green"], "#ffffff"),
            "amber": (p["amber"], "#ffffff"),
            "red": (p["red"], "#ffffff"),
            "grey": (p["grey_bg"], p["text"]),
        }
        bg, fg = colors.get(kind, colors["accent"])
        btn = tk.Button(parent, text=text, command=command,
                        bg=bg, fg=fg,
                        activebackground=_shade(bg, 0.82),
                        activeforeground=fg,
                        **self._btn_style)
        btn._kind = kind
        btn._base_bg = bg
        btn.bind("<Enter>", lambda e, b=btn: self._btn_hover(b, True))
        btn.bind("<Leave>", lambda e, b=btn: self._btn_hover(b, False))
        return btn

    def _btn_hover(self, btn: tk.Button, inside: bool) -> None:
        try:
            base = getattr(btn, "_base_bg", btn.cget("bg"))
            btn.configure(bg=_shade(base, 0.88) if inside else base)
        except Exception:
            pass

    def _paint_button(self, btn: tk.Button, text: str, kind: str) -> None:
        """Set ulang warna tombol (dipanggil saat state berubah)."""
        p = self._pal
        colors = {
            "accent": (p["accent"], "#0f172a"),
            "green": (p["green"], "#ffffff"),
            "amber": (p["amber"], "#ffffff"),
            "red": (p["red"], "#ffffff"),
            "grey": (p["grey_bg"], p["text"]),
        }
        bg, fg = colors.get(kind, (p["accent"], "#0f172a"))
        try:
            btn.configure(text=text, bg=bg, fg=fg,
                          activebackground=_shade(bg, 0.82),
                          activeforeground=fg)
            btn._kind = kind
            btn._base_bg = bg
        except Exception:
            pass

    def toggle_theme(self) -> None:
        """Ganti dark <-> light tanpa restart."""
        self._theme = "light" if self._theme == "dark" else "dark"
        self._pal = self._make_palette()
        p = self._pal
        self._apply_style()
        try:
            self.root.configure(bg=p["bg"])
            self._header.configure(bg=p["bg"])
            self._dot.configure(bg=p["bg"], fg=p["accent"])
            self._title_box.configure(bg=p["bg"])
            self._title_lbl.configure(bg=p["bg"], fg=p["text"])
            self._sub_lbl.configure(bg=p["bg"], fg=p["muted"])
            self._theme_btn.configure(bg=p["grey_bg"], fg=p["text"],
                                      activebackground=_shade(p["grey_bg"], 0.85))
            self._footer.configure(bg=p["bg"])
            self._footer_lbl.configure(bg=p["bg"], fg=p["muted"])
            for lbl in self._dyn_labels:
                lbl.configure(bg=p["panel"])
            self._cmd_canvas.configure(bg=p["panel"])
            self._log.configure(bg=p["log_bg"], fg=p["text"])
            self._hist.configure(bg=p["log_bg"], fg=p["text"])
            self._cache.clear()  # paksa refresh semua nilai + tombol
            self._log_event(f"Tema diganti ke {self._theme}.")
        except Exception:
            pass

    # ---------- layout ----------

    def _build(self) -> None:
        p = self._pal
        root = self.root

        # Header: [● judul + subjudul] ........ [tema] [pill status].
        self._header = tk.Frame(root, bg=p["bg"])
        self._header.pack(fill="x", padx=14, pady=(12, 4))
        self._dot = tk.Label(self._header, text="●", fg=p["accent"],
                             bg=p["bg"], font=("Segoe UI", 16))
        self._dot.pack(side="left", padx=(0, 8))
        self._title_box = tk.Frame(self._header, bg=p["bg"])
        self._title_box.pack(side="left", fill="x", expand=True)
        self._title_lbl = tk.Label(self._title_box, text=self._cfg.title,
                                   bg=p["bg"], fg=p["text"], font=_FONT_TITLE)
        self._title_lbl.pack(anchor="w")
        self._sub_lbl = tk.Label(self._title_box, text=self._cfg.subtitle,
                                 bg=p["bg"], fg=p["muted"], font=_FONT_SUB)
        self._sub_lbl.pack(anchor="w")
        self._theme_btn = tk.Button(
            self._header, text="🌙" if self._theme == "dark" else "☀",
            command=self.toggle_theme, bg=p["grey_bg"], fg=p["text"],
            font=("Segoe UI", 11), bd=0, relief="flat", cursor="hand2",
            padx=10, pady=4)
        self._theme_btn.pack(side="right", padx=(8, 0))
        self._pill = tk.Label(self._header, text="● STANDBY", bg=p["grey_bg"],
                              fg=p["text"], font=("Segoe UI", 9, "bold"),
                              padx=12, pady=6)
        self._pill.pack(side="right")

        # Konten responsif: kolom video (3) + kolom kanan (2, min 300px).
        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill="both", expand=True, padx=14, pady=8)
        content.grid_columnconfigure(0, weight=3, minsize=380)
        content.grid_columnconfigure(1, weight=2, minsize=300)
        content.grid_rowconfigure(0, weight=1)

        # --- Kartu video (kiri, mengembang) ---
        video_card = ttk.LabelFrame(content, text="  🎥 Webcam  ",
                                    style="Card.TLabelframe", padding=8)
        video_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        video_card.grid_rowconfigure(0, weight=1)
        video_card.grid_columnconfigure(0, weight=1)
        self._video_card = video_card
        self.video_label = ttk.Label(video_card, text="Memuat webcam...",
                                     style="Video.TLabel", anchor="center")
        self.video_label.grid(row=0, column=0, sticky="nsew")
        self.hud_var = tk.StringVar(value="")
        self._hud_lbl = ttk.Label(video_card, textvariable=self.hud_var,
                                  style="Muted.TLabel", font=_FONT_MONO)
        self._hud_lbl.grid(row=1, column=0, sticky="w", pady=(6, 0))
        video_card.bind("<Configure>", self._on_video_resize)

        # --- Kolom kanan (scroll vertikal bila window pendek) ---
        right_outer = ttk.Frame(content, style="App.TFrame")
        right_outer.grid(row=0, column=1, sticky="nsew")
        right_outer.grid_rowconfigure(0, weight=1)
        right_outer.grid_columnconfigure(0, weight=1)
        self._right_canvas = tk.Canvas(right_outer, bg=p["bg"],
                                       highlightthickness=0)
        right_scroll = ttk.Scrollbar(right_outer, orient="vertical",
                                     command=self._right_canvas.yview)
        self._right_inner = ttk.Frame(self._right_canvas, style="App.TFrame")
        self._right_inner.bind(
            "<Configure>",
            lambda e: self._right_canvas.configure(
                scrollregion=self._right_canvas.bbox("all")))
        self._right_win = self._right_canvas.create_window(
            (0, 0), window=self._right_inner, anchor="nw")
        self._right_canvas.configure(yscrollcommand=right_scroll.set)
        self._right_canvas.grid(row=0, column=0, sticky="nsew")
        right_scroll.grid(row=0, column=1, sticky="ns")
        self._right_canvas.bind("<Configure>", self._on_right_resize)
        # Scroll kanan hanya aktif saat konten lebih tinggi dari viewport.
        self._right_inner.bind("<Enter>", lambda e: self._bind_wheel(True))
        self._right_inner.bind("<Leave>", lambda e: self._bind_wheel(False))
        self._right_canvas.bind("<Enter>", lambda e: self._bind_wheel(True))
        self._right_canvas.bind("<Leave>", lambda e: self._bind_wheel(False))

        right = self._right_inner

        # Kartu status (§14 spek).
        status = ttk.LabelFrame(right, text="  📊 Status  ",
                                style="Card.TLabelframe", padding=8)
        status.pack(fill="x", pady=(0, 10))
        self._vars: dict[str, tk.StringVar] = {}
        rows = [
            ("camera", "📷 Camera"),
            ("hand", "🖐 Hand Tracking"),
            ("mouse", "🖱 Mouse Control"),
            ("voice", "🎤 Voice Control"),
            ("typing", "⌨ Voice Typing"),
            ("telegram", "🤖 Telegram Control"),
            ("tg_conn", "📡 Telegram Connection"),
            ("tg_user", "👤 Authorized User"),
            ("tg_last", "📨 Last Telegram Cmd"),
            ("active_app", "🪟 Active Window"),
            ("gesture", "👌 Gesture"),
            ("last_voice", "🎙 Last Voice"),
            ("intent", "🧠 Intent"),
            ("last_cmd", "⚙ Last Action"),
            ("fps", "⚡ FPS"),
        ]
        for i, (key, caption) in enumerate(rows):
            ttk.Label(status, text=caption,
                      style="Muted.TLabel").grid(row=i, column=0, sticky="w",
                                                 pady=2)
            var = tk.StringVar(value="—")
            self._vars[key] = var
            val = tk.Label(status, textvariable=var, bg=p["panel"],
                           fg=p["text"], font=_FONT_VALUE, anchor="e",
                           justify="right")
            val.grid(row=i, column=1, sticky="e", padx=(12, 0), pady=2)
            self._dyn_labels.append(val)
            setattr(self, f"_val_{key}", val)
        status.grid_columnconfigure(1, weight=1)

        # Kartu perintah terakhir (sorotan): voice + intent + action.
        voice_card = ttk.LabelFrame(right, text="  🗣 Perintah Terakhir  ",
                                    style="Card.TLabelframe", padding=8)
        voice_card.pack(fill="x", pady=(0, 10))
        self._wrap_labels: list[ttk.Label] = []
        for caption, key in (("Voice:", "last_voice"),
                             ("Intent:", "intent"),
                             ("Action:", "last_cmd")):
            ttk.Label(voice_card, text=caption,
                      style="Muted.TLabel").pack(anchor="w")
            lbl = ttk.Label(voice_card, textvariable=self._vars[key],
                            style="Muted.TLabel", font=_FONT_VALUE,
                            wraplength=320, justify="left")
            lbl.pack(anchor="w", fill="x", pady=(0, 4))
            self._wrap_labels.append(lbl)

        # Kartu kontrol (§14 spek: 8 tombol).
        ctrls = ttk.LabelFrame(right, text="  🎛 Kontrol  ",
                               style="Card.TLabelframe", padding=8)
        ctrls.pack(fill="x", pady=(0, 10))
        self.btn_camera = self._make_button(ctrls, "📷 Camera ON",
                                            self._on_toggle_camera, "green")
        self.btn_camera.pack(fill="x", pady=3)
        self.btn_hand = self._make_button(ctrls, "🖐 Hand Gesture ON",
                                          self._on_toggle_hand, "green")
        self.btn_hand.pack(fill="x", pady=3)
        self.btn_mouse = self._make_button(ctrls, "🖱 Mouse ON",
                                           self._on_toggle_mouse, "green")
        self.btn_mouse.pack(fill="x", pady=3)
        self.btn_voice = self._make_button(ctrls, "🎤 Voice ON",
                                           self._on_toggle_voice, "amber")
        self.btn_voice.pack(fill="x", pady=3)
        self.btn_typing = self._make_button(ctrls, "⌨ Voice Typing: OFF",
                                            self._on_toggle_typing, "grey")
        self.btn_typing.pack(fill="x", pady=3)
        self.btn_telegram = self._make_button(ctrls, "🤖 Telegram: OFF",
                                              self._on_toggle_telegram,
                                              "grey")
        self.btn_telegram.pack(fill="x", pady=3)
        btn_row = ttk.Frame(ctrls, style="Card.TFrame")
        btn_row.pack(fill="x", pady=3)
        self.btn_present = self._make_button(btn_row, "🎬 Presentasi",
                                             self._on_toggle_presentation,
                                             "grey")
        self.btn_present.pack(side="left", fill="x", expand=True, padx=(0, 3))
        settings_cmd = (self._open_settings_dialog if self._settings
                        is not None else None)
        self._make_button(btn_row, "⚙ Settings", settings_cmd,
                          "grey").pack(side="left", fill="x",
                                       expand=True, padx=(3, 0))
        self._make_button(ctrls, "⏻ Exit", self.close,
                          "red").pack(fill="x", pady=3)

        # Notebook: tab Perintah + tab Riwayat + tab Log.
        tabs = ttk.LabelFrame(right, text="  📚 Info  ",
                              style="Card.TLabelframe", padding=8)
        tabs.pack(fill="both", expand=True)
        nb = ttk.Notebook(tabs, style="Card.TNotebook")
        nb.pack(fill="both", expand=True)

        tab_cmd = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tab_cmd, text="📝 Perintah Suara")
        self._cmd_canvas = tk.Canvas(tab_cmd, bg=p["panel"],
                                     highlightthickness=0, height=150)
        cmd_scroll = ttk.Scrollbar(tab_cmd, orient="vertical",
                                   command=self._cmd_canvas.yview)
        cmd_inner = ttk.Frame(self._cmd_canvas, style="Card.TFrame")
        cmd_inner.bind("<Configure>", lambda e: self._cmd_canvas.configure(
            scrollregion=self._cmd_canvas.bbox("all")))
        self._cmd_canvas.create_window((0, 0), window=cmd_inner, anchor="nw")
        self._cmd_canvas.configure(yscrollcommand=cmd_scroll.set)
        self._cmd_canvas.pack(side="left", fill="both", expand=True)
        cmd_scroll.pack(side="right", fill="y")
        for phrase in self._processor.known_phrases:
            row = ttk.Frame(cmd_inner, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            ttk.Label(row, text="▸", style="Muted.TLabel",
                      foreground=p["accent"]).pack(side="left")
            ttk.Label(row, text=f"  {phrase}",
                      style="App.TLabel").pack(side="left")
        tab_cmd.bind("<Enter>", lambda e: self._bind_wheel_for(
            True, self._cmd_canvas))
        tab_cmd.bind("<Leave>", lambda e: self._bind_wheel_for(
            False, self._cmd_canvas))

        tab_hist = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tab_hist, text="📜 Riwayat")
        self._hist = tk.Text(tab_hist, bg=p["log_bg"], fg=p["text"],
                             font=_FONT_LOG, height=9, wrap="none",
                             relief="flat", padx=6, pady=6,
                             state="disabled")
        hist_scroll = ttk.Scrollbar(tab_hist, orient="vertical",
                                    command=self._hist.yview)
        self._hist.configure(yscrollcommand=hist_scroll.set)
        self._hist.pack(side="left", fill="both", expand=True)
        hist_scroll.pack(side="right", fill="y")

        tab_log = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tab_log, text="🕘 Log Aktivitas")
        self._log = tk.Text(tab_log, bg=p["log_bg"], fg=p["text"],
                            font=_FONT_LOG, height=9, wrap="word",
                            relief="flat", padx=6, pady=6,
                            state="disabled")
        log_scroll = ttk.Scrollbar(tab_log, orient="vertical",
                                   command=self._log.yview)
        self._log.configure(yscrollcommand=log_scroll.set)
        self._log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # Footer: shortcut keyboard.
        self._footer = tk.Frame(root, bg=p["bg"])
        self._footer.pack(fill="x", padx=14, pady=(0, 10))
        self._footer_lbl = tk.Label(
            self._footer,
            text="Shortcut:  M = mouse   •   V = voice   •   C = kalibrasi   •   "
                 "K = kamera   •   P = presentasi   •   T = typing   •   "
                 "Q / ESC = keluar",
            bg=p["bg"], fg=p["muted"], font=("Segoe UI", 8))
        self._footer_lbl.pack(anchor="w")

    # ---------- responsivitas ----------

    def _bind_wheel(self, on: bool) -> None:
        self._bind_wheel_for(on, self._right_canvas)

    def _bind_wheel_for(self, on: bool, canvas: tk.Canvas) -> None:
        try:
            if on:
                self.root.bind_all("<MouseWheel>", lambda e, c=canvas:
                                   c.yview_scroll(int(-e.delta / 120), "units"),
                                   add="+")
            else:
                self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_video_resize(self, event) -> None:
        """Hitung ulang target video agar pas di kartu (jaga aspek)."""
        try:
            card = self._video_card
            avail_w = max(200, card.winfo_width() - 24)
            hud_h = self._hud_lbl.winfo_height() or 24
            avail_h = max(150, card.winfo_height() - hud_h - 32)
            a = self._frame_aspect or (4 / 3)
            tw = min(avail_w, avail_h * a)
            th = min(avail_h, avail_w / a)
            tw, th = max(160, int(tw)), max(120, int(th))
            old = self._video_target
            if abs(tw - old[0]) > 6 or abs(th - old[1]) > 6:
                self._video_target = (tw, th)
        except Exception:
            pass

    def _on_right_resize(self, event) -> None:
        """Samakan lebar kolom kanan + wrap teks otomatis."""
        try:
            w = max(200, event.width - 4)
            self._right_canvas.itemconfigure(self._right_win, width=w)
            wrap = max(200, w - 110)
            for lbl in self._wrap_labels:
                lbl.configure(wraplength=wrap)
        except Exception:
            pass

    # ---------- log aktivitas ----------

    def _log_event(self, message: str) -> None:
        try:
            stamp = time.strftime("%H:%M:%S")
            self._log.configure(state="normal")
            self._log.insert("end", f"[{stamp}] {message}\n")
            lines = int(self._log.index("end-1c").split(".")[0])
            if lines > 80:  # batasi 80 baris terakhir
                self._log.delete("1.0", f"{lines - 80}.0")
            self._log.see("end")
            self._log.configure(state="disabled")
        except Exception:
            pass

    def _watch_log(self, snap: dict) -> None:
        """Catat perubahan penting ke tab Log (sekali per perubahan)."""
        s = self._seen
        if snap["last_voice"] != s["voice"] and snap["last_voice"] not in ("—", ""):
            s["voice"] = snap["last_voice"]
            self._log_event(f"🎤 \"{snap['last_voice']}\"")
        if (snap["last_command_status"] != s["cmd"]
                and snap["last_command_status"] not in ("—", "")):
            s["cmd"] = snap["last_command_status"]
            self._log_event(f"⚙ {snap['last_command_status']}")
        if snap["voice_status"] != s["vstatus"]:
            s["vstatus"] = snap["voice_status"]
            if snap["voice_status"] == "ERROR" and snap["voice_error"]:
                self._log_event(f"⚠ Voice error: {snap['voice_error']}")
            elif snap["voice_status"] == "UNAVAILABLE":
                self._log_event("⚠ Voice tidak tersedia (mode hand-only).")
        if snap["mouse_enabled"] != s["mouse"]:
            if s["mouse"] is not None:  # lewati status awal
                self._log_event("🖐 Mouse " + ("ON." if snap["mouse_enabled"]
                                              else "OFF."))
            s["mouse"] = snap["mouse_enabled"]
        if snap.get("hand_enabled", True) != s["hand"]:
            if s["hand"] is not None:
                self._log_event("🖐 Hand tracking " + (
                    "ON." if snap["hand_enabled"] else "OFF."))
            s["hand"] = snap.get("hand_enabled", True)
        if snap.get("presentation_mode") != s["pres"]:
            if s["pres"] is not None:
                self._log_event("🎬 Presentasi " + (
                    "ON." if snap["presentation_mode"] else "OFF."))
            s["pres"] = snap.get("presentation_mode")
        if snap.get("typing_mode") != s["typing"]:
            if s["typing"] is not None:
                self._log_event("⌨ Typing " + (
                    "ON." if snap["typing_mode"] else "OFF."))
            s["typing"] = snap.get("typing_mode")
        if snap.get("camera_on") != s["cam"]:
            if s["cam"] is not None:
                self._log_event("📷 Kamera " + (
                    "ON." if snap["camera_on"] else "OFF."))
            s["cam"] = snap.get("camera_on")
        tg_key = (snap.get("telegram_enabled"),
                  snap.get("telegram_connected"))
        if tg_key != s["tg"]:
            if s["tg"] is not None:
                self._log_event("🤖 Telegram " + (
                    "connected." if tg_key[1]
                    else "enabled (connecting)."
                    if tg_key[0] else "OFF."))
            s["tg"] = tg_key
        if (snap.get("telegram_last_cmd") != s["tgcmd"]
                and snap.get("telegram_last_cmd") not in ("—", "")):
            s["tgcmd"] = snap.get("telegram_last_cmd")
            self._log_event(f"📨 Telegram: {s['tgcmd']}")
        # Tab riwayat (§12 spek): refresh dari processor bila berubah.
        try:
            hist_txt = self._processor.history.formatted(15)
            if hist_txt != s["hist"]:
                s["hist"] = hist_txt
                self._hist.configure(state="normal")
                self._hist.delete("1.0", "end")
                self._hist.insert("end", hist_txt)
                self._hist.configure(state="disabled")
        except Exception:
            pass

    # ---------- dipanggil dari main loop ----------

    def has_video(self) -> bool:
        return self._Image is not None

    def update_frame(self, frame_bgr) -> None:
        if self._closed or self._Image is None:
            return
        try:
            h, w = frame_bgr.shape[:2]
            if w > 0 and h > 0:
                self._frame_aspect = w / h
            tw, th = self._video_target
            small = cv2.resize(frame_bgr, (tw, th),
                               interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            img = self._Image.fromarray(rgb)
            photo = self._ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo  # cegah garbage-collected
        except Exception:
            pass

    def _set_var(self, key: str, value: str) -> None:
        if self._cache.get(key) != value:
            self._cache[key] = value
            try:
                self._vars[key].set(value)
            except Exception:
                pass

    def _set_pill(self, text: str, kind: str) -> None:
        if self._cache.get("_pill") == text + kind:
            return
        self._cache["_pill"] = text + kind
        p = self._pal
        bg = {"green": p["green_bg"], "amber": p["amber_bg"],
              "red": p["red_bg"], "grey": p["grey_bg"]}.get(kind, p["grey_bg"])
        fg = {"green": p["green"], "amber": p["amber"],
              "red": p["red"], "grey": p["text"]}.get(kind, p["text"])
        try:
            self._pill.configure(text=text, bg=bg, fg=fg)
        except Exception:
            pass

    def _paint_value(self, attr: str, color_key: str) -> None:
        p = self._pal
        color = {"accent": p["accent"], "amber": p["amber"],
                 "violet": p["violet"], "green": p["green"],
                 "red": p["red"], "muted": p["muted"],
                 "text": p["text"]}.get(color_key, p["text"])
        try:
            getattr(self, attr).configure(fg=color)
        except Exception:
            pass

    def update_status(self, snap: dict) -> None:
        if self._closed:
            return

        # Nilai teks sesuai §14 spek (hanya update bila berubah).
        cam_txt = ("● ON" if snap.get("camera_on", True) else "○ OFF")
        hand_txt = ("● ON" if snap.get("hand_enabled", True) else "○ OFF")
        mouse_txt = ("● ON" if snap["mouse_enabled"] else "○ OFF")
        if snap["voice_available"]:
            voice_txt = ("● ON" if snap["voice_listening"] else "○ OFF")
        else:
            voice_txt = "⚠ UNAVAILABLE"
        typing_txt = ("● ON" if snap.get("typing_mode") else "○ OFF")
        app_name = (snap.get("active_app", "—") or "—").strip() or "—"
        intent_txt = snap.get("intent", "—") or "—"
        detail = (snap.get("intent_detail", "") or "").strip()
        self._set_var("camera", cam_txt)
        self._set_var("hand", hand_txt)
        self._set_var("mouse", mouse_txt)
        self._set_var("voice", voice_txt)
        self._set_var("typing", typing_txt)
        tg_on = snap.get("telegram_enabled", True)
        tg_conn = snap.get("telegram_connected", False)
        tg_txt = ("● ON" if tg_on and tg_conn
                  else "○ OFF" if not tg_on else "… CONNECTING")
        conn_txt = ("Connected" if tg_conn
                    else "Disabled" if not tg_on else "Connecting...")
        user_txt = (snap.get("telegram_user", "—") or "—")
        user_txt = ("Yes (%s)" % user_txt if tg_conn and user_txt != "—"
                    else user_txt)
        self._set_var("telegram", tg_txt)
        self._set_var("tg_conn", conn_txt)
        self._set_var("tg_user", user_txt[:40])
        self._set_var("tg_last",
                      (snap.get("telegram_last_cmd", "—") or "—")[:40])
        self._set_var("active_app", app_name[:40])
        self._set_var("gesture", snap["gesture"])
        self._set_var("last_voice",
                      (f"\"{snap['last_voice']}\""
                       if snap["last_voice"] not in ("—", "") else "—"))
        self._set_var("intent", (intent_txt
                                 + (f" ({detail})" if detail else ""))[:48])
        status = snap["last_command_status"]
        if snap["voice_error"] and snap["voice_status"] == "ERROR":
            status = (f"{status} | Voice error: {snap['voice_error']}"
                      if status and status != "—"
                      else f"Voice error: {snap['voice_error']}")
        self._set_var("last_cmd", status)
        self._set_var("fps", f"{snap['fps']:.1f}")
        self._set_var("hud",
                      f"Gesture: {snap['gesture']}   |   "
                      f"Aksi: {snap['gesture_action']}   |   "
                      f"{snap['fps']:.0f} FPS")
        try:
            self.hud_var.set(self._cache["hud"])
        except Exception:
            pass

        # Warna nilai mengikuti state.
        self._paint_value("_val_camera",
                          "green" if snap.get("camera_on", True) else "red")
        self._paint_value("_val_hand",
                          "green" if snap.get("hand_enabled", True)
                          else "red")
        self._paint_value("_val_mouse",
                          "green" if snap["mouse_enabled"] else "red")
        if not snap["voice_available"]:
            self._paint_value("_val_voice", "red")
        elif snap["voice_listening"]:
            self._paint_value("_val_voice", "green")
        else:
            self._paint_value("_val_voice", "amber")
        self._paint_value("_val_typing",
                          "accent" if snap.get("typing_mode") else "muted")
        self._paint_value("_val_telegram",
                          "green" if snap.get("telegram_enabled", True)
                          and snap.get("telegram_connected", False)
                          else "amber" if snap.get("telegram_enabled", True)
                          else "muted")
        self._paint_value("_val_gesture",
                          _GESTURE_COLORS.get(snap["gesture"], "text"))
        fps = snap["fps"]
        self._paint_value("_val_fps",
                          "green" if fps >= 20 else "amber" if fps >= 10 else "red")

        # Pill header + animasi pulse saat listening.
        if not snap["running"]:
            self._set_pill("● STOPPED", "grey")
        elif snap.get("presentation_mode"):
            self._set_pill("● PRESENTASI", "amber")
        elif snap.get("typing_mode"):
            self._set_pill("⌨ MENGETIK", "grey")
        elif snap["voice_available"] and snap["voice_listening"]:
            pulse = "●" if int(time.time() * 2) % 2 == 0 else "○"
            self._set_pill(f"{pulse} LISTENING", "green")
        elif not snap["mouse_enabled"] and not snap["voice_listening"]:
            self._set_pill("● PAUSED", "grey")
        elif snap["voice_status"] == "ERROR":
            self._set_pill("● VOICE ERROR", "amber")
        else:
            self._set_pill("● ACTIVE", "green")

        # Tombol mengikuti state.
        try:
            if snap.get("camera_on", True):
                self._paint_button(self.btn_camera, "📷 Camera ON", "green")
            else:
                self._paint_button(self.btn_camera, "📷 Camera OFF", "grey")
            if snap.get("hand_enabled", True):
                self._paint_button(self.btn_hand, "🖐 Hand Gesture ON",
                                   "green")
            else:
                self._paint_button(self.btn_hand, "🖐 Hand Gesture OFF",
                                   "grey")
            if snap["mouse_enabled"]:
                self._paint_button(self.btn_mouse, "🖱 Mouse ON", "green")
            else:
                self._paint_button(self.btn_mouse, "🖱 Mouse OFF", "grey")
            if snap["voice_listening"]:
                self._paint_button(self.btn_voice, "🎤 Voice ON", "amber")
            else:
                self._paint_button(self.btn_voice, "🎤 Voice OFF", "grey")
            if snap.get("presentation_mode"):
                self._paint_button(self.btn_present, "🎬 Presentasi ON",
                                   "amber")
            else:
                self._paint_button(self.btn_present, "🎬 Presentasi",
                                   "grey")
            if snap.get("typing_mode"):
                self._paint_button(self.btn_typing, "⌨ Voice Typing: ON",
                                   "accent")
            else:
                self._paint_button(self.btn_typing, "⌨ Voice Typing: OFF",
                                   "grey")
            if snap.get("telegram_enabled", True) and snap.get(
                    "telegram_connected", False):
                self._paint_button(self.btn_telegram, "🤖 Telegram: ON",
                                   "green")
            elif snap.get("telegram_enabled", True):
                self._paint_button(self.btn_telegram, "🤖 Telegram: ...",
                                   "amber")
            else:
                self._paint_button(self.btn_telegram, "🤖 Telegram: OFF",
                                   "grey")
        except Exception:
            pass

        self._watch_log(snap)

    # ---------- settings dialog (§15) ----------

    def _slider_row(self, parent, label, vmin, vmax, step, get, fmt):
        """Satu baris Scale + label nilai (ttk standar, tanpa dep baru)."""
        p = self._pal
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, style="Muted.TLabel",
                  width=20).pack(side="left")
        val_lbl = tk.Label(frame, text="", bg=p["panel"], fg=p["text"],
                           font=_FONT_VALUE, width=8)
        val_lbl.pack(side="right")
        var = tk.DoubleVar(value=float(get()))
        scale = tk.Scale(frame, from_=vmin, to=vmax, resolution=step,
                         orient="horizontal", variable=var, showvalue=False,
                         bg=p["panel"], fg=p["text"],
                         highlightthickness=0, length=160,
                         activebackground=p["accent"])
        scale.pack(side="right", fill="x", expand=True, padx=(8, 4))

        def _refresh(*_a):
            try:
                val_lbl.configure(text=fmt(var.get()))
            except Exception:
                pass
        var.trace_add("write", _refresh)
        _refresh()
        return var

    def _open_settings_dialog(self) -> None:
        """Dialog Settings §15 (tkinter standar; read-only bila no settings)."""
        if self._settings is None:
            self._log_event("⚠ Settings tidak tersedia.")
            return
        p = self._pal
        cur = self._settings.all()
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.configure(bg=p["bg"])
        try:
            dlg.geometry("420x560")
            dlg.transient(self.root)
            dlg.grab_set()
        except Exception:
            pass

        body = ttk.Frame(dlg, style="Card.TFrame", padding=10)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(body, text="⚙ Settings",
                  style="Card.TLabelframe.Label").pack(anchor="w",
                                                       pady=(0, 6))
        s_vars = {}
        s_vars["sensitivity"] = self._slider_row(
            body, "Sensitivitas", 0.5, 2.0, 0.1,
            lambda: cur.get("sensitivity", 1.0), lambda v: f"{v:.1f}x")
        s_vars["smoothing"] = self._slider_row(
            body, "Smoothing", 0.0, 0.95, 0.05,
            lambda: cur.get("smoothing", 0.7), lambda v: f"{v:.2f}")
        s_vars["click_threshold_px"] = self._slider_row(
            body, "Click threshold", 10, 100, 1,
            lambda: cur.get("click_threshold_px", 40),
            lambda v: f"{int(v)} px")
        s_vars["gesture_cooldown_sec"] = self._slider_row(
            body, "Gesture cooldown", 0.1, 2.0, 0.1,
            lambda: cur.get("gesture_cooldown_sec", 0.6),
            lambda v: f"{v:.1f} s")

        # Pilihan kamera.
        ttk.Label(body, text="Kamera", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 2))
        cam_var = tk.StringVar(value=str(cur.get("camera_index", 0)))
        cam_box = ttk.Combobox(body, textvariable=cam_var,
                               values=["0", "1", "2"], state="readonly",
                               width=10)
        cam_box.pack(anchor="w")

        ttk.Label(body, text="Orientasi kamera", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 2))
        _flip_options = ["Cermin (normal)", "Asli (tanpa balik)",
                         "Putar 180 (kamera terbalik)"]
        _flip_values = [1, 0, -1]
        try:
            _flip_idx = _flip_values.index(int(cur.get("camera_flip", 1)))
        except (TypeError, ValueError):
            _flip_idx = 0
        flip_var = tk.StringVar(value=_flip_options[_flip_idx])
        ttk.Combobox(body, textvariable=flip_var, values=_flip_options,
                     state="readonly").pack(anchor="w", fill="x")

        # Daftar mic (sounddevice; fallback: default saja).
        ttk.Label(body, text="Microphone", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 2))
        mic_names = ["Default"]
        mic_ids = [-1]
        try:
            import sounddevice as sd

            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    mic_names.append(f"{i}: {d.get('name', '?')}"[:48])
                    mic_ids.append(i)
        except Exception:
            pass
        mic_var = tk.StringVar(value=mic_names[0])
        try:
            cur_mic = int(cur.get("mic_device", -1))
            if cur_mic in mic_ids:
                mic_var.set(mic_names[mic_ids.index(cur_mic)])
        except Exception:
            pass
        ttk.Combobox(body, textvariable=mic_var, values=mic_names,
                     state="readonly").pack(anchor="w", fill="x")

        # Backend mic + bahasa.
        row2 = ttk.Frame(body, style="Card.TFrame")
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Mic backend",
                  style="Muted.TLabel").pack(side="left")
        backend_var = tk.StringVar(
            value=str(cur.get("mic_backend", "auto")))
        ttk.Combobox(row2, textvariable=backend_var,
                     values=["auto", "pyaudio", "sounddevice"],
                     state="readonly", width=12).pack(side="right")
        row3 = ttk.Frame(body, style="Card.TFrame")
        row3.pack(fill="x", pady=(4, 0))
        ttk.Label(row3, text="Bahasa voice",
                  style="Muted.TLabel").pack(side="left")
        lang_var = tk.StringVar(
            value=str(cur.get("voice_language", "id-ID")))
        ttk.Combobox(row3, textvariable=lang_var,
                     values=["id-ID", "en-US"],
                     state="readonly", width=12).pack(side="right")

        # Enable/disable.
        flags = ttk.Frame(body, style="Card.TFrame")
        flags.pack(fill="x", pady=(8, 0))
        mouse_v = tk.BooleanVar(value=bool(cur.get("mouse_enabled", True)))
        hand_v = tk.BooleanVar(value=bool(cur.get("hand_enabled", True)))
        voice_v = tk.BooleanVar(value=bool(cur.get("voice_enabled", True)))
        ttk.Checkbutton(flags, text="Mouse",
                        variable=mouse_v).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(flags, text="Hand",
                        variable=hand_v).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(flags, text="Voice",
                        variable=voice_v).pack(side="left")

        note = tk.Label(body, text="Catatan: kamera/mic/bahasa berlaku "
                                   "setelah restart aplikasi.",
                        bg=p["panel"], fg=p["muted"], font=("Segoe UI", 8),
                        wraplength=360, justify="left")
        note.pack(anchor="w", pady=(8, 0))

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=(10, 0))

        def _save() -> None:
            try:
                self._settings.set("sensitivity",
                                   round(float(s_vars["sensitivity"].get()), 2))
                self._settings.set("smoothing",
                                   round(float(s_vars["smoothing"].get()), 2))
                self._settings.set(
                    "click_threshold_px",
                    int(s_vars["click_threshold_px"].get()))
                self._settings.set(
                    "gesture_cooldown_sec",
                    round(float(s_vars["gesture_cooldown_sec"].get()), 2))
                try:
                    self._settings.set("camera_index", int(cam_var.get()))
                except ValueError:
                    pass
                try:
                    self._settings.set(
                        "camera_flip",
                        _flip_values[_flip_options.index(flip_var.get())])
                except (ValueError, IndexError):
                    pass
                try:
                    self._settings.set("mic_device",
                                       mic_ids[mic_names.index(mic_var.get())])
                except (ValueError, IndexError):
                    pass
                self._settings.set("mic_backend", backend_var.get())
                self._settings.set("voice_language", lang_var.get())
                self._settings.set("mouse_enabled", bool(mouse_v.get()))
                self._settings.set("hand_enabled", bool(hand_v.get()))
                self._settings.set("voice_enabled", bool(voice_v.get()))
                ok = self._settings.save()
                try:
                    if self._on_open_settings:
                        self._on_open_settings()
                except Exception:
                    pass
                self._log_event("⚙ Settings disimpan."
                                if ok else "⚠ Settings gagal disimpan.")
                dlg.destroy()
            except Exception as exc:
                self._log_event(f"⚠ Settings error: {exc}")

        self._make_button(btns, "💾 Simpan", _save,
                          "accent").pack(side="left", fill="x", expand=True,
                                         padx=(0, 4))
        self._make_button(btns, "↩ Reset", self._reset_settings,
                          "grey").pack(side="left", fill="x", expand=True,
                                       padx=(4, 0))

    def _reset_settings(self) -> None:
        try:
            if self._settings is not None:
                self._settings.reset()
                self._log_event("⚙ Settings dikembalikan ke default.")
        except Exception:
            pass

    def process_events(self) -> None:
        """Pompa event tkinter sekali (dipakai saat main loop jalan)."""
        if self._closed:
            return
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            self._on_exit()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        return self._closed
