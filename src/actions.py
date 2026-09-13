"""Aksi Windows yang aman: hanya dipanggil via whitelist CommandProcessor.

Aturan keamanan:
- TANPA `os.system()` / `shell=True` untuk input apa pun.
- Setiap aksi memakai path/URL tetap yang didefinisikan di sini, bukan dari
  teks suara pengguna. Teks suara hanya memilih *kunci* aksi.
- Jika aplikasi tidak ditemukan, kembalikan pesan error ramah (tanpa crash).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

import pyautogui


def _run_detached(argv: list[str]) -> tuple[bool, str]:
    """Jalankan proses GUI tanpa shell; kembalikan (ok, pesan)."""
    try:
        subprocess.Popen(argv, close_fds=False)  # noqa: S603 — argv tetap
        return True, f"Membuka {Path(argv[0]).name}..."
    except FileNotFoundError:
        return False, f"Aplikasi tidak ditemukan: {argv[0]}"
    except Exception as exc:
        return False, f"Gagal membuka aplikasi: {exc}"


def open_chrome() -> tuple[bool, str]:
    """Buka Google Chrome (coba beberapa lokasi instalasi umum)."""
    candidates = [
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return _run_detached([path])
    # Fallback: biarkan Windows memilih browser default via URL.
    try:
        webbrowser.open("https://www.google.com")
        return True, "Chrome tidak ditemukan, membuka browser default..."
    except Exception as exc:
        return False, f"Browser tidak tersedia: {exc}"


def close_chrome() -> tuple[bool, str]:
    """Tutup Google Chrome via taskkill (tanpa shell)."""
    try:
        proc = subprocess.run(  # noqa: S603 — argv tetap
            ["taskkill", "/IM", "chrome.exe"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return True, "Menutup Google Chrome..."
        return False, "Chrome tidak sedang berjalan."
    except FileNotFoundError:
        return False, "Perintah taskkill tidak tersedia."
    except Exception as exc:
        return False, f"Gagal menutup Chrome: {exc}"


def open_url(url: str, label: str) -> tuple[bool, str]:
    """Buka URL tetap di browser default."""
    try:
        webbrowser.open(url)
        return True, f"Membuka {label}..."
    except Exception as exc:
        return False, f"Gagal membuka {label}: {exc}"


def open_downloads() -> tuple[bool, str]:
    """Buka folder Downloads milik user via Explorer."""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        return False, "Folder Downloads tidak ditemukan."
    try:
        # "explorer" adalah biner sistem tetap; argumennya path yang
        # dikonstruksi dari Path.home(), bukan dari input pengguna.
        subprocess.Popen(["explorer", str(downloads)])  # noqa: S603
        return True, "Membuka folder Downloads..."
    except Exception as exc:
        return False, f"Gagal membuka folder Downloads: {exc}"


def take_screenshot() -> tuple[bool, str]:
    """Simpan screenshot ke Pictures/HandController."""
    try:
        import datetime

        dest_dir = Path.home() / "Pictures" / "HandController"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"screenshot_{stamp}.png"
        pyautogui.screenshot(str(dest))
        return True, f"Screenshot tersimpan: {dest.name}"
    except Exception as exc:
        return False, f"Gagal mengambil screenshot: {exc}"


def _press_volume_key(key: str, label: str) -> tuple[bool, str]:
    try:
        pyautogui.press(key)
        return True, label
    except Exception as exc:
        return False, f"Gagal mengatur volume: {exc}"


def volume_up() -> tuple[bool, str]:
    return _press_volume_key("volumeup", "Volume naik.")


def volume_down() -> tuple[bool, str]:
    return _press_volume_key("volumedown", "Volume turun.")


def volume_mute() -> tuple[bool, str]:
    return _press_volume_key("volumemute", "Mute/unmute volume.")
