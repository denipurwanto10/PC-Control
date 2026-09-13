"""Konfigurasi global aplikasi computer-controller (hand + voice)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VoiceConfig:
    """Parameter voice recognition."""

    enabled: bool = True
    language: str = "id-ID"          # bahasa utama; fallback otomatis ke en-US
    energy_threshold: int = 4000     # ambang volume mic (naikkan bila berisik)
    pause_threshold: float = 0.8     # jeda akhir kalimat (detik)
    phrase_time_limit: float = 6.0   # batas panjang satu perintah (detik)
    listen_timeout: float = 1.0      # timeout tunggu suara per iterasi (detik)
    ambient_duration: float = 0.5    # kalibrasi noise awal (detik)
    sample_rate: int = 16000         # sample rate rekam (Hz, hemat CPU)
    silence_margin: float = 0.5      # jeda hening penutup kalimat (detik)
    backend: str = "auto"            # auto | pyaudio | sounddevice
    mic_device: int = -1             # index input sounddevice, -1 = default


@dataclass(frozen=True)
class GuiConfig:
    """Parameter tampilan GUI."""

    title: str = "Multimodal Desktop Controller"
    subtitle: str = "Air Mouse + Voice Assistant + Windows Controller"
    video_width: int = 640
    video_height: int = 480
    refresh_ms: int = 30             # interval update frame GUI (ms)
    theme: str = "dark"              # dark | light
    accent: str = "#38bdf8"          # warna aksen (biru langit)


@dataclass(frozen=True)
class AppConfig:
    # --- Kamera ---
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480

    # --- MediaPipe HandLandmarker (Tasks API) ---
    model_asset_path: str = "assets/hand_landmarker.task"
    max_num_hands: int = 1
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.7

    # --- Mapping kamera -> layar ---
    # Margin ROI agar kursor tidak "lompat" di tepi frame.
    frame_margin: int = 100

    # --- Smoothing (0.0 - 0.95). Makin besar makin halus tapi makin "berat". ---
    smoothing: float = 0.7
    # --- Sensitivitas kursor (0.5 - 2.0). Pengali respons gerak. ---
    sensitivity: float = 1.0

    # --- Gesture (jarak pinch dalam piksel pada frame kamera) ---
    pinch_threshold_px: int = 40
    # Pinch cepat (< detik ini) + lepas = klik kiri.
    click_max_hold_sec: float = 0.4
    # Jeda minimum antar klik agar tidak double-click tak disengaja.
    click_cooldown_sec: float = 0.6
    # Pinch ditahan lebih lama dari ini = mulai drag.
    drag_hold_sec: float = 0.4

    # --- Scroll ---
    # Jarak vertikal jari tengah (piksel/frame) untuk memicu 1 langkah scroll.
    scroll_step_px: int = 15
    scroll_cooldown_sec: float = 0.05
    scroll_amount: int = 120

    # --- Zoom (gesture ZOOM: jempol + kelingking, gerak vertikal) ---
    zoom_step_px: int = 20
    zoom_cooldown_sec: float = 0.15

    # --- Mode presentasi ---
    presentation_next_cooldown_sec: float = 1.0  # cegah slide lompat 2x

    # --- Voice typing (diketik ke window aktif saat mode typing ON) ---
    typing_chunk_delay_sec: float = 0.05

    # --- Command chaining ---
    chain_separators: tuple = (" lalu ", " kemudian ", ", ", " dan ", " terus ",
                               " habis itu ", " setelah itu ")
    chain_max_commands: int = 5

    # --- History ---
    history_max: int = 50
    history_file: str = "data/command_history.json"

    # --- Tampilan ---
    window_name: str = "Hand Mouse Control"
    show_help: bool = True

    # --- Voice + GUI ---
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    gui: GuiConfig = field(default_factory=GuiConfig)


CONFIG = AppConfig()
