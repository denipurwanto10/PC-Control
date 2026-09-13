"""Voice controller: dengarkan mic di background thread, antrekan perintah.

Backend mic (dipilih otomatis):
1. `sr.Microphone` (PyAudio) bila tersedia — jalur standar.
2. `src.mic_input.SoundDeviceMic` bila PyAudio absen (umum di
   Python 3.13 Windows yang tak punya wheel PyAudio resmi).

Desain:
- Satu daemon thread menjalankan loop listen -> recognize -> queue.
- Thread TIDAK mengeksekusi aksi; ia hanya memanggil
  `state.queue_command(text)` agar dieksekusi di main thread.
- "berhenti mendengarkan" hanya mematikan pemrosesan (loop tetap hidup
  agar "mulai mendengarkan" bisa membangunkan tanpa restart).
- Semua kegagalan (mic sibuk/tak ada, internet putus, suara tak jelas)
  dilaporkan via AppState, tidak pernah crash.
"""
from __future__ import annotations

import threading
import time

from .app_state import AppState
from .config import VoiceConfig


class VoiceController:
    def __init__(self, config: VoiceConfig, state: AppState) -> None:
        self._cfg = config
        self._state = state
        self._sr = None          # modul speech_recognition (lazy import)
        self._recognizer = None
        self._mic = None
        self._backend = "none"   # pyaudio | sounddevice | none
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._unavailable_reason = ""

    # ---------- lifecycle ----------

    @property
    def available(self) -> bool:
        return self._mic is not None and self._recognizer is not None

    @property
    def backend(self) -> str:
        return self._backend

    def start(self) -> bool:
        """Init mic + jalankan listener thread. False bila mic tak tersedia."""
        if self._thread and self._thread.is_alive():
            return self.available
        if not self._init_backend():
            self._state.set_voice_available(False)
            self._state.set_voice_status("UNAVAILABLE", self._unavailable_reason)
            return False
        self._state.set_voice_available(True)
        self._state.set_voice_status(
            "LISTENING" if self._state.is_listening() else "STOPPED")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="voice-listener", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Hentikan thread dengan aman (dipanggil saat aplikasi ditutup)."""
        self._stop_event.set()
        # Jangan join dari dalam thread itu sendiri.
        if (self._thread and self._thread.is_alive()
                and threading.current_thread() is not self._thread):
            self._thread.join(timeout=3.0)
        self._release_backend()

    # ---------- backend ----------

    def _init_backend(self) -> bool:
        try:
            import speech_recognition as sr
        except ImportError:
            self._unavailable_reason = (
                "Paket 'SpeechRecognition' belum terinstal. "
                "Jalankan: pip install SpeechRecognition")
            print(f"[VOICE] {self._unavailable_reason}")
            return False
        self._sr = sr
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = self._cfg.energy_threshold
        self._recognizer.pause_threshold = self._cfg.pause_threshold

        want = (self._cfg.backend or "auto").lower()
        if want in ("auto", "pyaudio") and self._try_pyaudio(sr):
            return True
        if want in ("auto", "sounddevice") and self._try_sounddevice():
            return True
        if not self._unavailable_reason:
            self._unavailable_reason = (
                "Microphone tidak tersedia. Periksa izin mic Windows & "
                "tutup aplikasi yang memakai mic.")
        print(f"[VOICE] {self._unavailable_reason}")
        self._mic = None
        return False

    def _try_pyaudio(self, sr) -> bool:
        try:
            self._mic = sr.Microphone()
        except OSError as exc:
            self._unavailable_reason = (
                f"PyAudio mic gagal: {exc}. Mencoba backend sounddevice...")
            print(f"[VOICE] {self._unavailable_reason}")
            self._mic = None
            return False
        except Exception as exc:
            self._unavailable_reason = (
                f"Gagal membuka microphone (PyAudio): {exc}. "
                "Mencoba backend sounddevice...")
            print(f"[VOICE] {self._unavailable_reason}")
            self._mic = None
            return False
        try:
            with self._mic as source:
                self._recognizer.adjust_for_ambient_noise(
                    source, duration=self._cfg.ambient_duration)
            self._backend = "pyaudio"
            print("[VOICE] Microphone siap (PyAudio). Listening...")
            return True
        except OSError as exc:
            self._unavailable_reason = f"Microphone sibuk: {exc}."
            print(f"[VOICE] {self._unavailable_reason}")
            self._mic = None
            return False
        except Exception as exc:
            self._unavailable_reason = f"Kalibrasi mic gagal: {exc}"
            print(f"[VOICE] {self._unavailable_reason}")
            self._mic = None
            return False

    def _try_sounddevice(self) -> bool:
        try:
            from .mic_input import SoundDeviceMic
        except ImportError as exc:
            self._unavailable_reason = (
                f"Backend sounddevice tidak tersedia: {exc}. "
                "Jalankan: pip install sounddevice soundfile numpy")
            return False
        try:
            self._mic = SoundDeviceMic(sample_rate=self._cfg.sample_rate)
        except OSError as exc:
            self._unavailable_reason = (
                f"Microphone tidak tersedia: {exc}. Periksa izin mic "
                "Windows & tutup aplikasi yang memakai mic.")
            self._mic = None
            return False
        except Exception as exc:
            self._unavailable_reason = (
                f"Gagal membuka microphone (sounddevice): {exc}")
            self._mic = None
            return False
        try:
            floor = self._mic.calibrate(duration=self._cfg.ambient_duration)
            # Auto-gain: ambang = 2x noise lantai (min 300, max setting user).
            auto_thr = min(max(floor * 2.0, 300.0),
                           float(self._cfg.energy_threshold))
            self._recognizer.energy_threshold = auto_thr
            self._recognizer.dynamic_energy_threshold = False
            self._backend = "sounddevice"
            print(f"[VOICE] Microphone siap (sounddevice, noise={floor:.0f}, "
                  f"thr={auto_thr:.0f}). Listening...")
            return True
        except Exception as exc:
            self._unavailable_reason = f"Kalibrasi mic gagal: {exc}"
            self._mic = None
            return False

    def _release_backend(self) -> None:
        self._mic = None
        self._recognizer = None
        self._backend = "none"

    # ---------- loop utama ----------

    def _loop(self) -> None:
        consecutive_errors = 0
        while not self._stop_event.is_set() and self._state.is_running():
            try:
                if not self._state.is_listening():
                    self._state.set_voice_status("STOPPED")
                    time.sleep(0.2)
                    continue
                self._state.set_voice_status("LISTENING")
                audio = self._listen_once()
            except Exception as exc:
                if self._is_wait_timeout(exc):
                    continue  # sunyi — iterasi lagi, bukan error
                consecutive_errors += 1
                self._state.set_voice_status("ERROR", f"Mic error: {exc}")
                print(f"[VOICE] Mic error: {exc}. Mencoba lagi...")
                time.sleep(1.0 if "OSError" in type(exc).__name__ else 0.5)
                if consecutive_errors > 20:
                    print("[VOICE] Terlalu banyak error, voice dihentikan.")
                    self._state.set_listening(False)
                    self._state.set_voice_status("ERROR",
                                                 "Terlalu banyak error")
                    return
                continue

            if audio is None:
                continue  # timeout sunyi
            text = self._recognize(audio)
            if text:
                consecutive_errors = 0
                self._state.queue_command(text)

        self._state.set_voice_status("STOPPED")

    def _is_wait_timeout(self, exc: Exception) -> bool:
        wt = getattr(self._sr, "WaitTimeoutError", None)
        return wt is not None and isinstance(exc, wt)

    def _listen_once(self):
        if self._backend == "pyaudio":
            with self._mic as source:
                return self._recognizer.listen(
                    source,
                    timeout=self._cfg.listen_timeout,
                    phrase_time_limit=self._cfg.phrase_time_limit,
                )
        # sounddevice: VAD sendiri, kembalikan AudioData / None.
        return self._mic.record_phrase(
            self._recognizer,
            energy_threshold=self._recognizer.energy_threshold,
            pause_threshold=self._cfg.pause_threshold
            + self._cfg.silence_margin,
            phrase_time_limit=self._cfg.phrase_time_limit,
            listen_timeout=self._cfg.listen_timeout,
        )

    def _recognize(self, audio) -> str | None:
        """Ubah audio -> teks (Google ID, fallback EN). None bila gagal."""
        sr = self._sr
        for lang in (self._cfg.language, "en-US"):
            try:
                text = self._recognizer.recognize_google(audio, language=lang)
            except sr.UnknownValueError:
                return None  # suara tak jelas — diam saja
            except sr.RequestError as exc:
                # Internet putus / API tak terjangkau.
                self._state.set_voice_status("ERROR", f"Jaringan: {exc}")
                print(f"[VOICE] Butuh internet untuk speech recognition: {exc}")
                time.sleep(2.0)
                return None
            except Exception as exc:
                print(f"[VOICE] Recognize error ({lang}): {exc}")
                continue
            if text and text.strip():
                print(f"[VOICE] Terdengar ({lang}): {text.strip()}")
                return text.strip()
        return None
