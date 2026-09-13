"""Backend perekaman mic via sounddevice (tanpa PyAudio).

Dipakai bila `sr.Microphone` gagal karena PyAudio tidak tersedia
(kasus umum di Python 3.13 Windows). Algoritme:
- Kalibrasi noise lantai sesaat saat init.
- Tiap iterasi: tunggu suara melewati ambang (timeout), rekam sampai
  kalimat selesai (hening >= pause_threshold) atau phrase_time_limit.
- Hasil dikemas sebagai `sr.AudioData` agar bisa langsung dikenali
  dengan `recognizer.recognize_google()`.

Mengembalikan exception OSError bila tidak ada input device.
"""
from __future__ import annotations

import time


class SoundDeviceMic:
    """Antarmuka minimal mirip sr.Microphone untuk kebutuhan voice loop."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = [i for i, d in enumerate(devices)
                  if d.get("max_input_channels", 0) > 0]
        if not inputs:
            raise OSError("Tidak ada input microphone yang terdeteksi.")
        self._sd = sd
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = sd.default.device[0]
        if self.device is None or self.device < 0:
            self.device = inputs[0]

    def calibrate(self, duration: float = 0.5) -> float:
        """Rekam noise sesaat; kembalikan level RMS lantai."""
        import numpy as np

        n = int(self.sample_rate * max(duration, 0.1))
        rec = self._sd.rec(n, samplerate=self.sample_rate,
                           channels=self.channels, dtype="int16",
                           device=self.device, blocking=True)
        rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
        return max(rms, 1.0)

    def record_phrase(self, recognizer, energy_threshold: float,
                      pause_threshold: float, phrase_time_limit: float,
                      listen_timeout: float):
        """Rekam satu frasa; kembalikan sr.AudioData atau None (timeout)."""
        import numpy as np

        sr = recognizer.__class__.__module__  # hanya untuk pesan error
        _ = sr
        import speech_recognition as sr_mod

        block = 0.1  # detik per potongan baca
        frames: list = []
        started_at: float | None = None
        last_loud_at: float | None = None
        waited = 0.0

        deadline = time.monotonic() + phrase_time_limit + listen_timeout
        while time.monotonic() < deadline:
            chunk = self._sd.rec(int(self.sample_rate * block),
                                 samplerate=self.sample_rate,
                                 channels=self.channels, dtype="int16",
                                 device=self.device, blocking=True)
            mono = chunk[:, 0] if chunk.ndim > 1 else chunk
            rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
            loud = rms >= energy_threshold

            if started_at is None:
                if loud:
                    started_at = time.monotonic()
                    last_loud_at = started_at
                    frames.append(mono.copy())
                else:
                    waited += block
                    if waited >= listen_timeout:
                        return None  # sunyi — bukan error
                continue

            frames.append(mono.copy())
            if loud:
                last_loud_at = time.monotonic()
            elapsed = time.monotonic() - started_at
            silent_for = time.monotonic() - (last_loud_at or started_at)
            if silent_for >= pause_threshold and elapsed > 0.3:
                break  # kalimat selesai
            if elapsed >= phrase_time_limit:
                break

        if not frames:
            return None
        pcm = np.concatenate(frames).tobytes()
        return sr_mod.AudioData(pcm, self.sample_rate, 2)
