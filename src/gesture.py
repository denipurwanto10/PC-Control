"""Klasifikasi gesture dari landmark tangan.

Gesture lama dipertahankan (nama & perilaku identik):
  MOVE | PINCH (klik/drag) | SCROLL | PAUSE | NO_HAND

Gesture baru (tidak konflik dengan yang lama):
  R_CLICK   - jempol + jari tengah menyatu (klik kanan)
  DOUBLE    - jempol + telunjuk + tengah menyatu (double click)
  ZOOM      - jempol + kelingking menyatu (mode zoom, gerak vertikal)
  NEXT      - telunjuk menunjuk + 3 jari lain tegak, jempol terlipat (presentasi: next)
  PREV      - kepalan penuh (presentasi: previous)
  POINTER   - telunjuk + jempol membentuk L (presentasi: pointer, = MOVE)

Prioritas: PAUSE > NEXT/PREV (presentasi) > SCROLL > DOUBLE > R_CLICK
           > ZOOM > PINCH > POINTER/MOVE.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .hand_tracker import HandTracker


@dataclass
class GestureState:
    name: str  # MOVE | PINCH | SCROLL | PAUSE | NO_HAND | R_CLICK | DOUBLE
               # ZOOM | NEXT | PREV | POINTER
    pinch_distance: float = 9999.0
    index_tip: tuple = (0.0, 0.0)
    middle_tip: tuple = (0.0, 0.0)
    thumb_tip: tuple = (0.0, 0.0)
    pinky_tip: tuple = (0.0, 0.0)
    fingers_up_count: int = 0


def _finger_up(pts: np.ndarray, tip: int, pip: int, mcp: int) -> bool:
    # Jari tegak = ujung di atas sendi tengah (y lebih kecil) DAN jari
    # terbentang (jarak ujung-ke-pangkal cukup panjang). Syarat kedua
    # mencegah jari terlipat yang ujungnya "nongol" terbaca tegak.
    above = bool(pts[tip, 1] < pts[pip, 1])
    span = float(np.linalg.norm(pts[tip] - pts[mcp]))
    pip_span = float(np.linalg.norm(pts[pip] - pts[mcp]))
    return above and span > pip_span * 1.15


def _dist(pts: np.ndarray, a: int, b: int) -> float:
    return float(np.linalg.norm(pts[a] - pts[b]))


def classify(pts: np.ndarray | None, pinch_threshold_px: float) -> GestureState:
    """Klasifikasikan satu tangan menjadi gesture."""
    if pts is None:
        return GestureState(name="NO_HAND")

    index_tip = (float(pts[HandTracker.INDEX_TIP, 0]), float(pts[HandTracker.INDEX_TIP, 1]))
    middle_tip = (float(pts[HandTracker.MIDDLE_TIP, 0]), float(pts[HandTracker.MIDDLE_TIP, 1]))
    thumb_tip = (float(pts[HandTracker.THUMB_TIP, 0]), float(pts[HandTracker.THUMB_TIP, 1]))
    pinky_tip = (float(pts[HandTracker.PINKY_TIP, 0]), float(pts[HandTracker.PINKY_TIP, 1]))
    pinch_distance = _dist(pts, HandTracker.THUMB_TIP, HandTracker.INDEX_TIP)

    index_up = _finger_up(pts, HandTracker.INDEX_TIP, HandTracker.INDEX_PIP, 5)
    middle_up = _finger_up(pts, HandTracker.MIDDLE_TIP, HandTracker.MIDDLE_PIP, 9)
    ring_up = _finger_up(pts, HandTracker.RING_TIP, HandTracker.RING_PIP, 13)
    pinky_up = _finger_up(pts, HandTracker.PINKY_TIP, HandTracker.PINKY_PIP, 17)

    fingers_up = sum([index_up, middle_up, ring_up, pinky_up])
    thumb_index = pinch_distance
    thumb_middle = _dist(pts, HandTracker.THUMB_TIP, HandTracker.MIDDLE_TIP)
    thumb_pinky = _dist(pts, HandTracker.THUMB_TIP, HandTracker.PINKY_TIP)
    index_middle = _dist(pts, HandTracker.INDEX_TIP, HandTracker.MIDDLE_TIP)

    def make(name: str) -> GestureState:
        return GestureState(name, pinch_distance, index_tip, middle_tip,
                            thumb_tip, pinky_tip, fingers_up)

    # 1. Telapak terbuka (semua jari tegak + ibu jari jauh) = pause. [LAMA]
    if fingers_up == 4 and pinch_distance > pinch_threshold_px * 2.0:
        return make("PAUSE")

    # 2. Telunjuk+jari tengah+manis tegak, kelingking terlipat = NEXT.
    if index_up and middle_up and ring_up and not pinky_up:
        return make("NEXT")

    # 3. Kepalan penuh (tidak ada jari tegak, tidak ada pinch/zoom aktif)
    #    = PREV (presentasi). Dicek SETELAH gesture jarak agar cubit yang
    #    membuat semua jari terbaca "terlipat" tidak tertelan kepalan.
    if (fingers_up == 0
            and thumb_index >= pinch_threshold_px
            and thumb_middle >= pinch_threshold_px
            and thumb_pinky >= pinch_threshold_px * 1.3):
        return make("PREV")

    # 4. Jempol+telunjuk+tengah saling dekat, ring+kelingking terlipat
    #    = double click. Dicek SEBELUM scroll agar tak tertelan (saat
    #    double-click, telunjuk+tengah sering terbaca "tegak").
    if (thumb_index < pinch_threshold_px
            and thumb_middle < pinch_threshold_px
            and index_middle < pinch_threshold_px * 1.2
            and not ring_up and not pinky_up):
        return make("DOUBLE")

    # 5. Telunjuk + jari tengah tegak, dua jari lain terlipat = scroll. [LAMA]
    if index_up and middle_up and not ring_up and not pinky_up:
        return make("SCROLL")

    # 6. Jempol menyentuh jari tengah yang ditekuk (telunjuk & tengah
    #    terlipat, tengah PALING dekat ke jempol) = klik kanan.
    if (thumb_middle < pinch_threshold_px
            and thumb_middle < thumb_index
            and not middle_up and not index_up):
        return make("R_CLICK")

    # 7. Jempol + kelingking menyatu sementara telunjuk & tengah terlipat
    #    = mode zoom (gerak vertikal tangan = zoom in/out).
    if (thumb_pinky < pinch_threshold_px * 1.3
            and not index_up and not middle_up):
        return make("ZOOM")

    # 8. Ibu jari + telunjuk menyatu = pinch (klik / drag). [LAMA]
    if pinch_distance < pinch_threshold_px:
        return make("PINCH")

    # 9. Bentuk L (jempol jauh ke samping, hanya telunjuk tegak) = pointer.
    if index_up and not middle_up and not ring_up and not pinky_up:
        thumb_side = abs(float(pts[HandTracker.THUMB_TIP, 0])
                         - float(pts[HandTracker.INDEX_PIP, 0]))
        if thumb_side > pinch_threshold_px * 1.5:
            return make("POINTER")

    # 10. Default: ujung telunjuk menggerakkan kursor. [LAMA]
    return make("MOVE")
