"""Window manager kanonis: info & kontrol window aktif (Windows).

Modul ini SATU-SATUNYA tempat logika pygetwindow berada;
`windows_controller.py` mendelegasikan fungsi window-nya ke sini
(anti-duplikasi). Semua kegagalan dikembalikan sebagai pesan ramah,
tidak pernah raise — cocok untuk voice command & GUI polling.

API:
- get_active_title() / get_active_app_name() / get_active_window()
- list_windows(limit)
- focus_window(name) / minimize_window(name=None)
- maximize_window(name=None) / restore_window(name=None)
- close_window(name=None)   # None = window aktif
"""
from __future__ import annotations


def _gw():
    try:
        import pygetwindow as gw

        return gw
    except ImportError:
        return None


def find_window_obj(name: str | None):
    """(obj, err): cari window by nama app/judul; None = window aktif."""
    gw = _gw()
    if gw is None:
        return None, "pygetwindow belum terinstal (pip install pygetwindow)."
    try:
        if name:
            from .windows_controller import _APP_TITLES as _titles

            keys = _titles.get(name.lower(), [name.lower()])
            for w in gw.getAllWindows():
                title = (w.title or "").lower()
                if title and any(k in title for k in keys):
                    return w, ""
            return None, f"Window '{name}' tidak ditemukan."
        w = gw.getActiveWindow()
        if w is None:
            return None, "Tidak ada window aktif."
        return w, ""
    except Exception as exc:
        return None, f"Gagal membaca window: {exc}"


def get_active_title() -> str:
    w, _ = find_window_obj(None)
    try:
        title = (w.title if w else "") or "—"
    except Exception:
        title = "—"
    return title[:60]


_APP_KEYWORDS: list[tuple[str, str]] = [
    ("visual studio code", "Visual Studio Code"),
    ("vs code", "Visual Studio Code"),
    ("whatsapp", "WhatsApp"),
    ("powerpoint", "PowerPoint"),
    ("chrome", "Google Chrome"),
    ("firefox", "Firefox"),
    ("msedge", "Edge"),
    ("edge", "Edge"),
    ("file explorer", "File Explorer"),
    ("explorer", "File Explorer"),
    ("notepad", "Notepad"),
    ("word", "Word"),
    ("excel", "Excel"),
    ("youtube", "Browser — YouTube"),
    ("gmail", "Browser — Gmail"),
    ("github", "Browser — GitHub"),
]


def guess_app_name(title: str) -> str:
    t = (title or "").lower()
    for keyword, label in _APP_KEYWORDS:
        if keyword in t:
            return label
    if not t or t == "—":
        return "—"
    # Fallback: potong judul lazim "dokumen - Aplikasi".
    if " - " in title:
        return title.split(" - ")[-1].strip()[:40]
    return title[:40]


def get_active_app_name() -> str:
    return guess_app_name(get_active_title())


def get_active_window() -> dict:
    title = get_active_title()
    return {"title": title, "app": guess_app_name(title)}


def list_windows(limit: int = 20) -> list[dict]:
    gw = _gw()
    if gw is None:
        return []
    try:
        out = []
        for w in gw.getAllWindows():
            if w.title and w.visible:
                out.append({"title": w.title[:60],
                            "app": guess_app_name(w.title)})
            if len(out) >= max(1, limit):
                break
        return out
    except Exception:
        return []


def _act(name: str | None, op: str) -> tuple[bool, str]:
    w, err = find_window_obj(name)
    if w is None:
        return False, err
    try:
        label = (w.title or "")[:40]
        if op == "focus":
            if w.isMinimized:
                w.restore()
            w.activate()
            return True, f"Fokus ke: {label}"
        if op == "minimize":
            w.minimize()
            return True, f"Minimize: {label}"
        if op == "maximize":
            w.maximize()
            return True, f"Maximize: {label}"
        if op == "restore":
            w.restore()
            return True, f"Restore: {label}"
        if op == "close":
            w.close()
            return True, f"Menutup: {label}"
        return False, f"Operasi '{op}' tidak dikenal."
    except Exception as exc:
        if op == "close":
            try:
                import pyautogui

                pyautogui.hotkey("alt", "f4")
                return True, "Menutup window aktif (Alt+F4)."
            except Exception as exc2:
                return False, f"Gagal menutup window: {exc2}"
        return False, f"Gagal {op}: {exc}"


def focus_window(name: str) -> tuple[bool, str]:
    return _act(name, "focus")


def minimize_window(name: str | None = None) -> tuple[bool, str]:
    return _act(name, "minimize")


def maximize_window(name: str | None = None) -> tuple[bool, str]:
    return _act(name, "maximize")


def restore_window(name: str | None = None) -> tuple[bool, str]:
    return _act(name, "restore")


def close_window(name: str | None = None) -> tuple[bool, str]:
    return _act(name, "close")
