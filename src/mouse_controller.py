"""Mapping kamera -> layar, smoothing, dan aksi mouse (klik/drag/scroll)."""
from __future__ import annotations

import time

import numpy as np
import pyautogui

from .config import AppConfig


class MouseController:
    """Stateful controller: smoothing + state machine pinch (klik vs drag).

    API lama dipertahankan (move/map_to_screen/update_pinch/update_scroll/
    reset_*/force_release/dragging/last_action). Tambahan: klik kanan,
    double click (dengan cooldown masing-masing), zoom, dan kalibrasi ROI.
    """

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        pyautogui.FAILSAFE = False  # kursor boleh ke pojok tanpa exception
        try:
            pyautogui.PAUSE = 0
        except Exception:
            pass
        self.screen_w, self.screen_h = pyautogui.size()

        self.smooth_x = 0.0
        self.smooth_y = 0.0
        self._has_smooth = False

        # ROI kalibrasi (fraksi frame 0..1). None = pakai frame_margin lama.
        self._roi: tuple | None = None

        # State pinch
        self._pinch_active = False
        self._pinch_start = 0.0
        self._dragging = False
        self._last_click = 0.0

        # Cooldown aksi sekali-tembak (gesture edge-triggered).
        self._last_rclick = 0.0
        self._last_dclick = 0.0
        self._zoom_prev_y: float | None = None
        self._last_zoom = 0.0

        # State scroll
        self._prev_middle_y: float | None = None
        self._last_scroll = 0.0

        self.last_action = "—"

    # ---------- kalibrasi ROI ----------

    def calibrate(self, frame_w: int, frame_h: int, margin_ratio: float = 0.15) -> None:
        """Set ROI sebagai fraksi frame (lebih presisi dari margin piksel)."""
        m = max(0.0, min(0.4, margin_ratio))
        self._roi = (m, m, 1.0 - m, 1.0 - m)
        self.reset_smoothing()

    def clear_calibration(self) -> None:
        self._roi = None
        self.reset_smoothing()

    # ---------- mapping + smoothing ----------

    def map_to_screen(self, cam_x: float, cam_y: float, frame_w: int, frame_h: int):
        if self._roi is not None:
            rx1, ry1, rx2, ry2 = self._roi
            x1, x2 = rx1 * frame_w, max(rx1 * frame_w + 1, rx2 * frame_w)
            y1, y2 = ry1 * frame_h, max(ry1 * frame_h + 1, ry2 * frame_h)
        else:
            m = self.cfg.frame_margin
            x1, x2 = float(m), float(max(m + 1, frame_w - m))
            y1, y2 = float(m), float(max(m + 1, frame_h - m))
        cx = float(np.clip(cam_x, x1, x2))
        cy = float(np.clip(cam_y, y1, y2))
        sx = (cx - x1) / (x2 - x1) * self.screen_w
        sy = (cy - y1) / (y2 - y1) * self.screen_h
        return sx, sy

    def _smooth(self, x: float, y: float):
        a = float(np.clip(self.cfg.smoothing, 0.0, 0.95))
        if not self._has_smooth:
            self.smooth_x, self.smooth_y = x, y
            self._has_smooth = True
            return x, y
        sens = float(getattr(self.cfg, "sensitivity", 1.0) or 1.0)
        sens = float(np.clip(sens, 0.5, 2.0))
        self.smooth_x = a * self.smooth_x + (1.0 - a) * x
        self.smooth_y = a * self.smooth_y + (1.0 - a) * y
        if sens != 1.0:
            # Sensitivitas: dorong dari titik anchor terakhir.
            self.smooth_x += (x - self.smooth_x) * (sens - 1.0) * 0.5
            self.smooth_y += (y - self.smooth_y) * (sens - 1.0) * 0.5
        return self.smooth_x, self.smooth_y

    def move(self, cam_x: float, cam_y: float, frame_w: int, frame_h: int) -> tuple:
        sx, sy = self.map_to_screen(cam_x, cam_y, frame_w, frame_h)
        sx, sy = self._smooth(sx, sy)
        try:
            pyautogui.moveTo(sx, sy, duration=0)
        except Exception:
            pass
        return sx, sy

    def reset_smoothing(self) -> None:
        self._has_smooth = False

    def reset_scroll(self) -> None:
        self._prev_middle_y = None

    # ---------- pinch: klik vs drag ----------

    def update_pinch(
        self,
        pinched: bool,
        cam_x: float,
        cam_y: float,
        frame_w: int,
        frame_h: int,
        now: float | None = None,
    ) -> str:
        """Dipanggil tiap frame saat gesture PINCH / bukan. Kembalikan aksi."""
        now = time.time() if now is None else now

        if pinched and not self._pinch_active:
            # Pinch baru dimulai.
            self._pinch_active = True
            self._pinch_start = now
            self._dragging = False
            self.move(cam_x, cam_y, frame_w, frame_h)
            self.last_action = "Pinch mulai..."
            return self.last_action

        if pinched and self._pinch_active:
            held = now - self._pinch_start
            # Tetap gerakkan kursor selama pinch agar bisa drag.
            self.move(cam_x, cam_y, frame_w, frame_h)
            if not self._dragging and held >= self.cfg.drag_hold_sec:
                try:
                    pyautogui.mouseDown(button="left")
                except Exception:
                    pass
                self._dragging = True
                self.last_action = "Dragging..."
            elif not self._dragging:
                self.last_action = "Pinch mulai..."
            return self.last_action

        if not pinched and self._pinch_active:
            # Pinch dilepas: tentukan klik atau akhir drag.
            held = now - self._pinch_start
            self._pinch_active = False
            if self._dragging:
                try:
                    pyautogui.mouseUp(button="left")
                except Exception:
                    pass
                self._dragging = False
                self.last_action = "Drag selesai"
                return self.last_action
            # Pinch cepat = klik kiri (dengan cooldown).
            if held <= self.cfg.click_max_hold_sec and (
                now - self._last_click
            ) >= self.cfg.click_cooldown_sec:
                try:
                    pyautogui.click(button="left")
                except Exception:
                    pass
                self._last_click = now
                self.last_action = "Klik kiri"
            else:
                self.last_action = "—"
            return self.last_action

        return self.last_action

    def force_release(self) -> None:
        """Lepaskan drag jika aplikasi berhenti saat drag aktif."""
        if self._dragging:
            try:
                pyautogui.mouseUp(button="left")
            except Exception:
                pass
            self._dragging = False
        self._pinch_active = False

    @property
    def dragging(self) -> bool:
        return self._dragging

    # ---------- scroll ----------

    def update_scroll(self, middle_y: float, now: float | None = None) -> str:
        now = time.time() if now is None else now
        if self._prev_middle_y is None:
            self._prev_middle_y = middle_y
            return "Mode scroll"
        dy = middle_y - self._prev_middle_y
        if abs(dy) >= self.cfg.scroll_step_px and (
            now - self._last_scroll
        ) >= self.cfg.scroll_cooldown_sec:
            # Jari bergerak ke atas (dy negatif) = scroll ke atas.
            amount = self.cfg.scroll_amount if dy < 0 else -self.cfg.scroll_amount
            try:
                pyautogui.scroll(amount)
            except Exception:
                pass
            self._last_scroll = now
            self._prev_middle_y = middle_y
            self.last_action = "Scroll ↑" if dy < 0 else "Scroll ↓"
            return self.last_action
        return "Mode scroll"

    # ---------- aksi sekali-tembak (edge-triggered + cooldown) ----------

    def _cooldown_ok(self, last: float, now: float) -> bool:
        return (now - last) >= self.cfg.click_cooldown_sec

    def trigger_right_click(self, now: float | None = None) -> str:
        """Klik kanan sekali (dipanggil saat gesture R_CLICK muncul)."""
        now = time.time() if now is None else now
        if self._cooldown_ok(self._last_rclick, now):
            try:
                pyautogui.click(button="right")
            except Exception:
                pass
            self._last_rclick = now
            self.last_action = "Klik kanan"
        return self.last_action

    def trigger_double_click(self, now: float | None = None) -> str:
        """Double click sekali (dipanggil saat gesture DOUBLE muncul)."""
        now = time.time() if now is None else now
        if self._cooldown_ok(self._last_dclick, now):
            try:
                pyautogui.doubleClick(button="left")
            except Exception:
                pass
            self._last_dclick = now
            self.last_action = "Double click"
        return self.last_action

    def reset_zoom(self) -> None:
        self._zoom_prev_y = None

    def update_zoom(self, hand_y: float, now: float | None = None) -> str:
        """Zoom in/out via Ctrl+scroll mengikuti gerak vertikal tangan."""
        now = time.time() if now is None else now
        if self._zoom_prev_y is None:
            self._zoom_prev_y = hand_y
            return "Mode zoom"
        dy = hand_y - self._zoom_prev_y
        if abs(dy) >= self.cfg.zoom_step_px and (
            now - self._last_zoom
        ) >= self.cfg.zoom_cooldown_sec:
            try:
                if dy < 0:
                    pyautogui.hotkey("ctrl", "+")  # zoom in
                    self.last_action = "Zoom in (+)"
                else:
                    pyautogui.hotkey("ctrl", "-")  # zoom out
                    self.last_action = "Zoom out (-)"
            except Exception:
                pass
            self._last_zoom = now
            self._zoom_prev_y = hand_y
            return self.last_action
        return "Mode zoom"

    def reset_gesture_states(self) -> None:
        """Reset state sekali-tembak saat gesture berganti (anti double-fire)."""
        self._zoom_prev_y = None
