"""Screenshot & screen tools (modul kompatibilitas).

Implementasi kanonis ada di `src/screenshot.py` (full/active/region).
Modul ini dipertahankan agar import lama tetap jalan; semua fungsi
screenshot didelegasikan. Recording tetap di sini (thread daemon
opsional, butuh `mss`).
"""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

from .screenshot import (  # noqa: F401
    dest_dir as _dest_dir,
    take_active_window,
    take_full,
    take_region,
)


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def screenshot_full() -> tuple[bool, str]:
    return take_full()


def screenshot_region() -> tuple[bool, str]:
    return take_region()


def screenshot_active() -> tuple[bool, str]:
    return take_active_window()


# ---------- screen recording (opsional) ----------

_rec_state: dict = {"active": False, "thread": None, "stop": None, "file": ""}


def _mss_cv2():
    try:
        import mss  # type: ignore
        import cv2  # noqa: F401

        return mss
    except ImportError:
        return None


def _video_dir() -> Path:
    d = Path.home() / "Videos"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def start_recording(fps: int = 15) -> tuple[bool, str]:
    if _rec_state["active"]:
        return False, "Recording sudah berjalan."
    if _mss_cv2() is None:
        return False, ("Screen recording butuh 'mss' "
                       "(pip install mss). Fitur opsional.")
    import threading

    import cv2
    import mss

    dest = _video_dir() / f"Recording_{_stamp()}.mp4"
    stop = threading.Event()
    state = {"file": str(dest)}

    def _run() -> None:
        try:
            import numpy as np

            with mss.mss() as sct:
                mon = sct.monitors[1]
                w, h = mon["width"], mon["height"]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out = cv2.VideoWriter(state["file"], fourcc, fps, (w, h))
                while not stop.is_set():
                    img = sct.grab(mon)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    out.write(frame)
                out.release()
        except Exception:
            pass

    t = threading.Thread(target=_run, name="screen-rec", daemon=True)
    t.start()
    _rec_state.update(active=True, thread=t, stop=stop,
                      file=str(dest))
    return True, f"Recording dimulai: {dest.name} (ucapkan 'stop recording')."


def stop_recording() -> tuple[bool, str]:
    if not _rec_state["active"]:
        return False, "Tidak ada recording berjalan."
    try:
        _rec_state["stop"].set()
        _rec_state["thread"].join(timeout=5.0)
    except Exception:
        pass
    _rec_state["active"] = False
    return True, f"Recording berhenti: {_rec_state['file']}"


def recording_active() -> bool:
    return bool(_rec_state["active"])
