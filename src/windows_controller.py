"""Windows controller: aksi OS terpusat & aman (tanpa shell/os.system).

Semua fungsi mengembalikan tuple[bool, str] = (sukses, pesan status).
Aturan keamanan:
- TANPA `os.system()` / `shell=True` untuk input apa pun.
- Argumen proses selalu list argv tetap; input suara hanya memilih kunci
  aksi atau mengisi parameter jinak (query cari, nama file) yang tidak
  pernah dieksekusi sebagai perintah.
- Ketergantungan opsional (pygetwindow/pyperclip) diimpor lazy dengan
  pesan fallback yang ramah bila belum terinstal.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

import pyautogui

# ---------- util ----------

Result = tuple[bool, str]


def _run(argv: list[str], verb: str = "Membuka") -> Result:
    try:
        subprocess.Popen(argv, close_fds=False)  # noqa: S603 — argv tetap
        return True, f"{verb} {Path(argv[0]).stem}..."
    except FileNotFoundError:
        return False, f"Aplikasi tidak ditemukan: {argv[0]}"
    except Exception as exc:
        return False, f"Gagal: {exc}"


def _gw():
    """Import pygetwindow lazy; None bila belum terinstal."""
    try:
        import pygetwindow as gw

        return gw
    except ImportError:
        return None


# ---------- aplikasi ----------

_APP_PATHS: dict[str, list[str]] = {
    "chrome": [
        "%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe",
        "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe",
        "%LocalAppData%\\Google\\Chrome\\Application\\chrome.exe",
    ],
    "vscode": [
        "%LocalAppData%\\Programs\\Microsoft VS Code\\Code.exe",
        "%ProgramFiles%\\Microsoft VS Code\\Code.exe",
    ],
    "whatsapp": [
        "%LocalAppData%\\WhatsApp\\WhatsApp.exe",
        "%ProgramFiles%\\WhatsApp\\WhatsApp.exe",
    ],
    "powerpoint": [
        "%ProgramFiles%\\Microsoft Office\\root\\Office16\\POWERPNT.EXE",
        "%ProgramFiles(x86)%\\Microsoft Office\\root\\Office16\\POWERPNT.EXE",
    ],
}

_APP_TITLES: dict[str, list[str]] = {
    "chrome": ["chrome"],
    "vscode": ["visual studio code", "vs code", "vscode"],
    "whatsapp": ["whatsapp"],
    "powerpoint": ["powerpoint"],
}


def _app_config_paths(app: str) -> list[str]:
    """Baca config/apps.json (user override); [] bila kosong/rusak."""
    try:
        import json
        from pathlib import Path as _P

        cfg = _P("config/apps.json")
        if not cfg.exists():
            return []
        data = json.loads(cfg.read_text(encoding="utf-8"))
        val = (data or {}).get(app, "")
        if isinstance(val, list):
            return [str(v) for v in val if v]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
    except Exception:
        pass
    return []


def open_app(app: str) -> Result:
    """Buka aplikasi whitelist (chrome|vscode|whatsapp|powerpoint).

    Urutan: config/apps.json -> lokasi umum Windows -> PATH.
    """
    app = (app or "").lower()
    if app in ("vs_code", "vs code"):
        app = "vscode"
    # 1. Override user dari config/apps.json (hanya kunci whitelist!).
    for raw in _app_config_paths(app):
        path = os.path.expandvars(raw)
        if Path(path).exists():
            return _run([path])
        return False, (f"Path '{app}' di config/apps.json tidak ditemukan: "
                       f"{raw}")
    paths = _APP_PATHS.get(app)
    if not paths:
        return False, f"Aplikasi '{app}' tidak didukung."
    for raw in paths:
        path = os.path.expandvars(raw)
        if Path(path).exists():
            return _run([path])
    which = {"chrome": "chrome", "vscode": "code"}.get(app)
    if which and shutil.which(which):
        return _run([shutil.which(which)])
    return False, f"{app.title()} tidak ditemukan di PC ini."


def close_app(app: str) -> Result:
    images = {"chrome": "chrome.exe", "vscode": "Code.exe",
              "whatsapp": "WhatsApp.exe", "powerpoint": "POWERPNT.EXE"}
    image = images.get((app or "").lower())
    if not image:
        return False, f"Aplikasi '{app}' tidak didukung."
    try:
        proc = subprocess.run(  # noqa: S603 — argv tetap
            ["taskkill", "/IM", image], capture_output=True,
            text=True, timeout=10)
        if proc.returncode == 0:
            return True, f"Menutup {app}..."
        return False, f"{app.title()} tidak sedang berjalan."
    except Exception as exc:
        return False, f"Gagal menutup {app}: {exc}"


# ---------- window management (didelegasikan ke window_manager) ----------

from . import window_manager as _wm


def _find_window(app: str | None = None):
    """Kompat: kembalikan objek window lama bila ada."""
    return _wm.find_window_obj(app)


def active_window_title() -> str:
    return _wm.get_active_title()


def minimize_window(app: str | None = None) -> Result:
    return _wm.minimize_window(app)


def maximize_window(app: str | None = None) -> Result:
    return _wm.maximize_window(app)


def restore_window(app: str | None = None) -> Result:
    return _wm.restore_window(app)


def focus_window(app: str) -> Result:
    return _wm.focus_window(app)


def close_active_window() -> Result:
    return _wm.close_window(None)


def tile_side_by_side() -> Result:
    """Susun 2 window teratas berdampingan (untuk workflow coding)."""
    gw = _gw()
    if gw is None:
        return False, "pygetwindow belum terinstal."
    try:
        wins = [w for w in gw.getAllWindows()
                if w.title and w.visible and not w.isMinimized]
        if len(wins) < 2:
            return False, "Butuh minimal 2 window terbuka."
        sw, sh = pyautogui.size()
        a, b = wins[0], wins[1]
        a.restore()
        b.restore()
        a.moveTo(0, 0)
        a.resizeTo(sw // 2, sh)
        b.moveTo(sw // 2, 0)
        b.resizeTo(sw - sw // 2, sh)
        return True, f"Window disusun: {a.title[:20]} | {b.title[:20]}"
    except Exception as exc:
        return False, f"Gagal menyusun window: {exc}"


# ---------- website & pencarian ----------

_SITES = {
    "youtube": ("https://www.youtube.com", "YouTube"),
    "google": ("https://www.google.com", "Google"),
    "github": ("https://github.com", "GitHub"),
    "gmail": ("https://mail.google.com", "Gmail"),
}


def open_site(site: str) -> Result:
    entry = _SITES.get((site or "").lower())
    if not entry:
        return False, f"Situs '{site}' tidak didukung."
    url, label = entry
    try:
        webbrowser.open(url)
        return True, f"Membuka {label}..."
    except Exception as exc:
        return False, f"Gagal membuka {label}: {exc}"


def search_google(query: str) -> Result:
    query = (query or "").strip()
    if not query:
        return False, "Kata kunci pencarian kosong."
    # Query di-URL-encode; tidak pernah jadi perintah shell.
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    try:
        webbrowser.open(url)
        return True, f"Mencari di Google: {query[:50]}"
    except Exception as exc:
        return False, f"Gagal mencari: {exc}"


def search_youtube(query: str) -> Result:
    query = (query or "").strip()
    if not query:
        try:
            webbrowser.open("https://www.youtube.com")
            return True, "Membuka YouTube..."
        except Exception as exc:
            return False, f"Gagal membuka YouTube: {exc}"
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote_plus(query))
    try:
        webbrowser.open(url)
        return True, f"Mencari di YouTube: {query[:50]}"
    except Exception as exc:
        return False, f"Gagal mencari: {exc}"


# ---------- folder & file ----------

_FOLDERS = {
    "downloads": ("Downloads", "Downloads"),
    "documents": ("Documents", "Documents"),
    "desktop": ("Desktop", "Desktop"),
    "pictures": ("Pictures", "Pictures"),
    "project": ("Documents", "Documents"),  # fallback bila project dir tak ada
}

SEARCHABLE_DIRS = ["Downloads", "Documents", "Desktop", "Pictures"]


def open_folder(name: str) -> Result:
    key = (name or "").lower()
    if key == "project":
        from . import workflows as _wf

        proj = _wf.project_dir()
        if proj:
            try:
                subprocess.Popen(["explorer", str(proj)])  # noqa: S603
                return True, f"Membuka folder project: {proj.name}"
            except Exception as exc:
                return False, f"Gagal membuka folder project: {exc}"
    entry = _FOLDERS.get(key)
    if not entry:
        return False, f"Folder '{name}' tidak didukung."
    target = Path.home() / entry[0]
    if not target.exists():
        return False, f"Folder {entry[1]} tidak ditemukan."
    try:
        subprocess.Popen(["explorer", str(target)])  # noqa: S603 — argv tetap
        return True, f"Membuka folder {entry[1]}..."
    except Exception as exc:
        return False, f"Gagal membuka folder: {exc}"


def find_file(name: str) -> Result:
    """Cari file di Downloads/Documents/Desktop (nama mengandung query)."""
    query = (name or "").strip().lower()
    if not query:
        return False, "Nama file kosong."
    hits: list[Path] = []
    for dirname in SEARCHABLE_DIRS:
        root = Path.home() / dirname
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if len(hits) >= 5:
                    break
                try:
                    if p.is_file() and query in p.name.lower():
                        hits.append(p)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue
    if not hits:
        return False, f"File '{name}' tidak ditemukan."
    names = ", ".join(h.name for h in hits[:5])
    return True, f"Ditemukan: {names}"


def open_found_file(name: str) -> Result:
    ok, msg = find_file(name)
    if not ok:
        return ok, msg
    # Buka hasil pertama via pencarian ulang yang mengembalikan path.
    query = name.strip().lower()
    for dirname in SEARCHABLE_DIRS:
        root = Path.home() / dirname
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                try:
                    if p.is_file() and query in p.name.lower():
                        os.startfile(str(p))  # Windows: buka dgn app default
                        return True, f"Membuka file: {p.name}"
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue
    return False, f"File '{name}' tidak ditemukan."


def make_folder_here() -> Result:
    """Buat folder baru di Desktop (nama unik otomatis)."""
    try:
        import datetime

        base = Path.home() / "Desktop"
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for i in range(100):
            suffix = f"_{i}" if i else ""
            target = base / f"Folder Baru {stamp}{suffix}"
            if not target.exists():
                target.mkdir()
                return True, f"Folder dibuat: {target.name}"
        return False, "Gagal membuat folder (nama bentrok)."
    except Exception as exc:
        return False, f"Gagal membuat folder: {exc}"


# ---------- volume / brightness / media ----------

def _press(key: str, label: str) -> Result:
    try:
        pyautogui.press(key)
        return True, label
    except Exception as exc:
        return False, f"Gagal: {exc}"


def volume_up() -> Result:
    return _press("volumeup", "Volume naik.")


def volume_down() -> Result:
    return _press("volumedown", "Volume turun.")


def volume_mute() -> Result:
    return _press("volumemute", "Mute/unmute volume.")


def volume_set(percent: int) -> Result:
    """Set volume ~persen via N press (mute dulu agar deterministik)."""
    try:
        percent = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return False, "Persen volume tidak valid."
    try:
        pyautogui.press("volumemute")  # pastikan mulai dari unmute path
        pyautogui.press("volumemute")  # toggle balik (stabil)
        steps = round(percent / 2)  # tiap press ~2%
        for _ in range(50):
            pyautogui.press("volumedown")
        for _ in range(steps):
            pyautogui.press("volumeup")
        return True, f"Volume {percent}%."
    except Exception as exc:
        return False, f"Gagal mengatur volume: {exc}"


def brightness(up: bool) -> Result:
    # Laptop Windows umumnya merespons tombol Fn brightness via key ini;
    # fallback: buka Settings > Display bila gagal.
    try:
        import ctypes

        # Coba WMI (laptop fisik). Gagal di VM/desktop -> fallback pesan.
        import subprocess as sp

        delta = "+" if up else "-"
        _ = delta
        try:
            import wmi  # type: ignore  # opsional, jarang terinstal
        except ImportError:
            wmi = None
        if wmi is not None:
            svc = wmi.WMI(namespace="wmi")
            methods = svc.WmiMonitorBrightnessMethods()[0]
            cur = svc.WmiMonitorBrightness()[0].CurrentBrightness
            target = max(0, min(100, cur + (10 if up else -10)))
            methods.WmiSetBrightness(target, 0)
            return True, f"Brightness {target}%."
        # Tanpa modul wmi: kirim tombol brightness via keybd (best-effort).
        VK_BRIGHT_UP, VK_BRIGHT_DOWN = 0x87, 0x86
        code = VK_BRIGHT_UP if up else VK_BRIGHT_DOWN
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)
        return True, f"Brightness {'naik' if up else 'turun'}."
    except Exception as exc:
        return False, f"Brightness tidak didukung di perangkat ini: {exc}"


def media(action: str) -> Result:
    keys = {"play": "playpause", "pause": "playpause",
            "next": "nexttrack", "previous": "prevtrack"}
    key = keys.get((action or "").lower())
    if not key:
        return False, f"Aksi media '{action}' tidak didukung."
    labels = {"play": "Play.", "pause": "Pause.",
              "next": "Track berikutnya.", "previous": "Track sebelumnya."}
    return _press(key, labels[action.lower()])


# ---------- mouse via suara ----------

def voice_click(kind: str = "left") -> Result:
    try:
        if kind == "double":
            pyautogui.doubleClick()
            return True, "Double click."
        button = "right" if kind == "right" else "left"
        pyautogui.click(button=button)
        return True, f"Klik {'kanan' if button == 'right' else 'kiri'}."
    except Exception as exc:
        return False, f"Gagal klik: {exc}"


def voice_scroll(direction: str, amount: int = 500) -> Result:
    try:
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return True, ("Scroll ke atas." if direction == "up"
                      else "Scroll ke bawah.")
    except Exception as exc:
        return False, f"Gagal scroll: {exc}"


# ---------- keyboard automation ----------

_KEY_ALIASES = {
    "enter": "enter", "escape": "esc", "esc": "esc", "tab": "tab",
    "spasi": "space", "space": "space", "hapus": "backspace",
    "backspace": "backspace", "delete": "delete",
    "atas": "up", "bawah": "down", "kiri": "left", "kanan": "right",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "f5": "f5",
}


def press_key(name: str) -> Result:
    key = _KEY_ALIASES.get((name or "").lower(), (name or "").lower())
    try:
        pyautogui.press(key)
        return True, f"Menekan {name}."
    except Exception as exc:
        return False, f"Tombol '{name}' gagal: {exc}"


def hotkey(*keys: str) -> Result:
    try:
        pyautogui.hotkey(*keys)
        return True, f"Shortcut {'+'.join(keys)}."
    except Exception as exc:
        return False, f"Shortcut gagal: {exc}"


def copy() -> Result:
    return hotkey("ctrl", "c")


def paste() -> Result:
    return hotkey("ctrl", "v")


def cut() -> Result:
    return hotkey("ctrl", "x")


def select_all() -> Result:
    return hotkey("ctrl", "a")


# ---------- voice typing ----------

def type_text(text: str, delay_sec: float = 0.05) -> Result:
    """Ketik teks ke window aktif (dipakai mode voice typing)."""
    text = text or ""
    if not text.strip():
        return False, "Tidak ada teks untuk diketik."
    # Potong agar satu ucapan tak membanjiri (maks 500 char).
    chunk = text[:500]
    try:
        import time as _t

        _t.sleep(delay_sec)
        pyautogui.write(chunk, interval=0.01)
        return True, f"Diketik ({len(chunk)} char)."
    except Exception as exc:
        return False, f"Gagal mengetik: {exc}"


# ---------- presentasi ----------

def slide_next() -> Result:
    return press_key("right") if False else _slide("right", "Slide berikutnya.")


def slide_prev() -> Result:
    return _slide("left", "Slide sebelumnya.")


def _slide(key: str, label: str) -> Result:
    try:
        pyautogui.press(key)
        return True, label
    except Exception as exc:
        return False, f"Gagal pindah slide: {exc}"


def presentation_fullscreen() -> Result:
    """Mulai slideshow PowerPoint bila memungkinkan (F5)."""
    try:
        pyautogui.press("f5")
        return True, "Mode fullscreen presentasi (F5)."
    except Exception as exc:
        return False, f"Gagal fullscreen: {exc}"


# ---------- query angka (volume 50 persen) ----------

_ID_WORDS = {
    "nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "sebelas": 11, "seratus": 100,
}


def parse_percent(text: str) -> int | None:
    """Ekstrak 0..100 dari teks ('volume 50 persen' / 'lima puluh')."""
    norm = (text or "").lower()
    m = re.search(r"(\d{1,3})\s*(persen|%|percent)?", norm)
    if m:
        try:
            v = int(m.group(1))
            return v if 0 <= v <= 100 else None
        except ValueError:
            return None
    # Kata bilangan sederhana: "lima puluh" -> 50.
    total, current = 0, 0
    found = False
    for tok in re.findall(r"[a-z]+", norm):
        if tok in ("puluh",):
            current = (current or 1) * 10
            found = True
        elif tok in ("belas",):
            current = (current or 1) + 10
            found = True
        elif tok in _ID_WORDS:
            current += _ID_WORDS[tok]
            found = True
    total += current
    if found and 0 <= total <= 100:
        return total
    return None
