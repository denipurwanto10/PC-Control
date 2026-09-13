"""Screenshot kanonis: full / active-window / region (Windows).

Modul ini SATU-SATUNYA implementasi screenshot; `screenshot_tools.py`
hanya delegasi kompatibel (API lama dipertahankan).

Penamaan file sesuai standar: `Screenshot_YYYY-MM-DD_HH-MM-SS.png`
di `Pictures/Screenshots`. Semua kegagalan -> (False, pesan), tidak
pernah raise.
"""
from __future__ import annotations

import datetime
from pathlib import Path


def dest_dir() -> Path:
    d = Path.home() / "Pictures" / "Screenshots"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def take_full() -> tuple[bool, str]:
    """Screenshot seluruh layar."""
    try:
        import pyautogui

        dest = dest_dir() / f"Screenshot_{stamp()}.png"
        pyautogui.screenshot(str(dest))
        return True, f"Screenshot tersimpan: {dest}"
    except Exception as exc:
        return False, f"Gagal screenshot: {exc}"


def take_active_window() -> tuple[bool, str]:
    """Screenshot window aktif; fallback full bila gagal baca geometri."""
    try:
        from . import window_manager as wm

        w, err = wm.find_window_obj(None)
        if w is not None:
            try:
                import pyautogui

                box = (w.left, w.top, w.width, w.height)
                if w.width > 10 and w.height > 10:
                    dest = dest_dir() / f"Screenshot_window_{stamp()}.png"
                    pyautogui.screenshot(str(dest), region=box)
                    title = (w.title or "")[:40]
                    return True, f"Screenshot window tersimpan: {dest.name} ({title})"
            except Exception:
                pass
        ok, msg = take_full()
        return ok, f"{msg} (fallback full{', ' + err if err else ''})"
    except Exception as exc:
        ok, msg = take_full()
        return ok, f"{msg} (fallback full: {exc})"


def take_region() -> tuple[bool, str]:
    """Screenshot area pilihan user (rubber-band picker); ESC batal."""
    try:
        import tkinter as tk

        sel: dict = {}

        def _pick() -> None:
            root = tk.Tk()
            root.attributes("-fullscreen", True)
            root.attributes("-alpha", 0.35)
            root.configure(bg="black", cursor="crosshair")
            c = tk.Canvas(root, highlightthickness=0, cursor="crosshair")
            c.pack(fill="both", expand=True)
            start: dict = {}

            def down(e):
                start["x"], start["y"] = e.x, e.y
                c.delete("box")

            def drag(e):
                c.delete("box")
                c.create_rectangle(start["x"], start["y"], e.x, e.y,
                                   outline="red", width=2, tags="box")

            def up(e):
                sel["box"] = (min(start["x"], e.x), min(start["y"], e.y),
                              max(start["x"], e.x), max(start["y"], e.y))
                root.destroy()

            def cancel(_e=None):
                root.destroy()

            c.bind("<ButtonPress-1>", down)
            c.bind("<B1-Motion>", drag)
            c.bind("<ButtonRelease-1>", up)
            root.bind("<Escape>", cancel)
            root.mainloop()

        # Picker harus jalan di main thread; command processor sudah di sana.
        _pick()
        box = sel.get("box")
        if not box or (box[2] - box[0]) < 5 or (box[3] - box[1]) < 5:
            return False, "Area dibatalkan."
        import pyautogui

        dest = dest_dir() / f"Screenshot_area_{stamp()}.png"
        pyautogui.screenshot(str(dest), region=box)
        return True, f"Screenshot area tersimpan: {dest}"
    except Exception as exc:
        ok, msg = take_full()
        return ok, f"{msg} (fallback full, area gagal: {exc})"
