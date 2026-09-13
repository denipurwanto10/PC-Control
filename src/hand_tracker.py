"""Hand tracking berbasis MediaPipe Tasks (HandLandmarker, VIDEO mode)."""
from __future__ import annotations

import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.core import base_options as mp_base_options

# Koneksi skeleton tangan standar MediaPipe (21 titik).
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # ibu jari
    (0, 5), (5, 6), (6, 7), (7, 8),          # telunjuk
    (5, 9), (9, 10), (10, 11), (11, 12),     # jari tengah
    (9, 13), (13, 14), (14, 15), (15, 16),   # jari manis
    (13, 17), (17, 18), (18, 19), (19, 20),  # kelingking
    (0, 17),                                 # telapak
)


class HandTracker:
    """Membungkus MediaPipe HandLandmarker (Tasks API) dengan API sederhana.

    `process()` mengembalikan daftar tangan, masing-masing berupa list dari
    21 landmark ternormalisasi (objek dengan atribut .x/.y/.z). Daftar kosong
    berarti tidak ada tangan terdeteksi.
    """

    # Indeks landmark yang dipakai di seluruh aplikasi.
    THUMB_TIP = 4
    INDEX_TIP = 8
    INDEX_PIP = 6
    MIDDLE_TIP = 12
    MIDDLE_PIP = 10
    RING_TIP = 16
    RING_PIP = 14
    PINKY_TIP = 20
    PINKY_PIP = 18

    def __init__(
        self,
        model_asset_path: str = "assets/hand_landmarker.task",
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
    ) -> None:
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_base_options.BaseOptions(
                model_asset_path=model_asset_path
            ),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=max_num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = 0

    def process(self, frame_bgr):
        """Proses satu frame BGR, kembalikan list tangan (kosong bila tak ada)."""
        try:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        except Exception:
            return []
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        # VIDEO mode mewajibkan timestamp monoton naik (ms).
        ts = int(time.monotonic() * 1000)
        if ts <= self._last_timestamp_ms:
            ts = self._last_timestamp_ms + 1
        self._last_timestamp_ms = ts
        try:
            result = self._landmarker.detect_for_video(mp_image, ts)
        except Exception:
            return []
        if not result or not result.hand_landmarks:
            return []
        return list(result.hand_landmarks)

    def landmarks_to_pixels(self, hand_landmarks, frame_w: int, frame_h: int) -> np.ndarray:
        """Ubah 21 landmark ternormalisasi menjadi array piksel (21, 2)."""
        pts = np.zeros((21, 2), dtype=np.float32)
        for i, lm in enumerate(hand_landmarks[:21]):
            pts[i, 0] = lm.x * frame_w
            pts[i, 1] = lm.y * frame_h
        return pts

    def draw(self, frame_bgr, pts) -> None:
        """Gambar skeleton tangan + titik dari array piksel (21, 2)."""
        h, w = frame_bgr.shape[:2]
        for a, b in HAND_CONNECTIONS:
            xa, ya = int(pts[a, 0]), int(pts[a, 1])
            xb, yb = int(pts[b, 0]), int(pts[b, 1])
            if 0 <= xa < w and 0 <= ya < h and 0 <= xb < w and 0 <= yb < h:
                cv2.line(frame_bgr, (xa, ya), (xb, yb), (0, 255, 0), 2)
        for x, y in pts.astype(int):
            if 0 <= x < w and 0 <= y < h:
                cv2.circle(frame_bgr, (x, y), 4, (0, 0, 255), -1)

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:
            pass
