"""Clipboard control: copy/paste/cut/select-all/clear/open via pyautogui + pyperclip.

pyperclip diimpor lazy agar aplikasi tetap jalan bila belum terinstal.
"""
from __future__ import annotations

import pyautogui


def _pyperclip():
    try:
        import pyperclip

        return pyperclip
    except ImportError:
        return None


def copy() -> tuple[bool, str]:
    try:
        pyautogui.hotkey("ctrl", "c")
        return True, "Copy (Ctrl+C)."
    except Exception as exc:
        return False, f"Gagal copy: {exc}"


def paste() -> tuple[bool, str]:
    try:
        pyautogui.hotkey("ctrl", "v")
        return True, "Paste (Ctrl+V)."
    except Exception as exc:
        return False, f"Gagal paste: {exc}"


def cut() -> tuple[bool, str]:
    try:
        pyautogui.hotkey("ctrl", "x")
        return True, "Cut (Ctrl+X)."
    except Exception as exc:
        return False, f"Gagal cut: {exc}"


def select_all() -> tuple[bool, str]:
    try:
        pyautogui.hotkey("ctrl", "a")
        return True, "Select all (Ctrl+A)."
    except Exception as exc:
        return False, f"Gagal select all: {exc}"


def clear() -> tuple[bool, str]:
    pc = _pyperclip()
    if pc is None:
        return False, "pyperclip belum terinstal (pip install pyperclip)."
    try:
        pc.copy("")
        return True, "Clipboard dikosongkan."
    except Exception as exc:
        return False, f"Gagal mengosongkan clipboard: {exc}"


def show() -> tuple[bool, str]:
    """Buka clipboard Windows (Win+V) agar isi terlihat."""
    try:
        pyautogui.hotkey("win", "v")
        return True, "Membuka riwayat clipboard (Win+V)."
    except Exception as exc:
        return False, f"Gagal membuka clipboard: {exc}"


def read_text() -> str:
    pc = _pyperclip()
    if pc is None:
        return ""
    try:
        return str(pc.paste() or "")
    except Exception:
        return ""
