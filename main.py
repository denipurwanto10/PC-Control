"""Multimodal Desktop Controller: hand gesture + voice + keyboard + automation.

Arsitektur (§17):
- Main/GUI thread : loop webcam + hand tracking + eksekusi command + GUI.
- Voice thread     : listen + recognize saja, hasil diantrekan via AppState.
- Eksekusi command : SELALU di main thread (aman untuk pyautogui/GUI).
- Screen recording : thread daemon sendiri (start/stop via voice).

Gesture (§5):
- MOVE/POINTER: gerak | PINCH: klik/drag | R_CLICK: kanan | DOUBLE: 2x klik
- SCROLL: scroll | ZOOM: ctrl+/- | NEXT/PREV: slide (mode presentasi)
- PAUSE: pause | NO_HAND: diam.

Fallback berlapis (§18) agar aplikasi tidak crash:
- GUI tkinter gagal      -> mode klasik (jendela OpenCV).
- Mic/SR gagal           -> voice UNAVAILABLE, hand gesture tetap jalan.
- Webcam gagal           -> keluar dengan pesan ramah (exit 1).
- Model MediaPipe hilang -> keluar dengan pesan ramah (exit 1).

Kontrol (mode GUI maupun klasik):
- M: mouse | V: voice | C: kalibrasi kamera | K: kamera on/off
- G: hand tracking | P: presentasi | T: voice typing | H: bantuan
- Q/ESC: keluar.
"""
from __future__ import annotations

import time

import cv2

from src.app_state import AppState
from src.command_history import CommandHistory
from src.command_processor import CommandProcessor
from src.config import CONFIG
from src.gesture import GestureState, classify
from src.hand_tracker import HandTracker
from src.mouse_controller import MouseController
from src.settings import SettingsStore
from src.voice_controller import VoiceController
from src import window_manager as wm
from src import windows_controller as wc

try:
    from src.telegram_controller import TelegramController
except Exception:  # Telegram opsional: app tetap jalan tanpa modul ini
    TelegramController = None  # type: ignore

# Tombol overlay klasik (koordinat piksel frame).
BUTTON_RECT = (10, 10, 190, 52)       # x1, y1, x2, y2 (mouse)
BUTTON_VOICE_RECT = (200, 10, 390, 52)  # x1, y1, x2, y2 (voice)

# Gesture sekali-tembak: hanya fire saat gesture BARU muncul (edge-trigger).
EDGE_GESTURES = {"R_CLICK", "DOUBLE", "NEXT", "PREV"}


class App:
    def __init__(self) -> None:
        self.settings = SettingsStore()
        self.state = AppState()
        self._apply_settings_to_state()
        self.history = CommandHistory(file=CONFIG.history_file,
                                      max_entries=CONFIG.history_max)
        self.processor = CommandProcessor(self.state, history=self.history)
        self.voice = VoiceController(self._voice_config(), self.state)
        self.telegram = None  # TelegramController (opsional, non-blocking)
        self.tracker: HandTracker | None = None
        self.mouse: MouseController | None = None
        self.cap = None
        self.gui = None
        self.use_gui = False
        self.show_help = CONFIG.show_help
        self.gesture = GestureState(name="NO_HAND")
        self.action = "—"
        self.prev_t = time.time()
        self.no_hand_frames = 0
        self._prev_gesture = "NO_HAND"   # edge-trigger sekali-tembak
        self._last_slide = 0.0
        self._frame_count = 0

    # ---------- setup ----------

    def _voice_config(self):
        """VoiceConfig dari CONFIG + override settings (§15)."""
        from dataclasses import replace

        s = self.settings.all()
        return replace(
            CONFIG.voice,
            backend=str(s.get("mic_backend", CONFIG.voice.backend)),
            language=str(s.get("voice_language", CONFIG.voice.language)),
        )

    def _mouse_config(self):
        """AppConfig efektif: CONFIG + override settings (§15)."""
        from dataclasses import replace

        s = self.settings.all()
        try:
            smoothing = float(s.get("smoothing", CONFIG.smoothing))
        except (TypeError, ValueError):
            smoothing = CONFIG.smoothing
        try:
            sensitivity = float(s.get("sensitivity", CONFIG.sensitivity))
        except (TypeError, ValueError):
            sensitivity = CONFIG.sensitivity
        try:
            threshold = int(s.get("click_threshold_px",
                                  CONFIG.pinch_threshold_px))
        except (TypeError, ValueError):
            threshold = CONFIG.pinch_threshold_px
        try:
            cooldown = float(s.get("gesture_cooldown_sec",
                                   CONFIG.click_cooldown_sec))
        except (TypeError, ValueError):
            cooldown = CONFIG.click_cooldown_sec
        return replace(
            CONFIG,
            smoothing=min(0.95, max(0.0, smoothing)),
            sensitivity=min(2.0, max(0.5, sensitivity)),
            pinch_threshold_px=max(10, min(100, threshold)),
            click_cooldown_sec=max(0.1, min(2.0, cooldown)),
        )

    def _apply_settings_to_state(self) -> None:
        s = self.settings.all()
        self.state.set_mouse(bool(s.get("mouse_enabled", True)))
        self.state.set_hand(bool(s.get("hand_enabled", True)))
        if not bool(s.get("voice_enabled", True)):
            self.state.set_listening(False)

    def apply_settings(self) -> None:
        """Dipanggil dari dialog Settings: terapkan tanpa restart."""
        self._apply_settings_to_state()
        if self.mouse is not None:
            cfg = self._mouse_config()
            self.mouse.cfg = cfg
        print("[INFO] Settings diterapkan "
              "(kamera/mic/bahasa butuh restart).")

    def _camera_flip(self) -> int:
        """Mode orientasi kamera: 1=cermin, 0=asli, -1=putar 180."""
        try:
            mode = int(self.settings.get("camera_flip", 1))
        except (TypeError, ValueError):
            mode = 1
        return mode if mode in (1, 0, -1) else 1

    def _orient_frame(self, frame):
        """Terapkan orientasi kamera sesuai settings (F = ganti mode)."""
        mode = self._camera_flip()
        if mode == 0:
            return frame
        return cv2.flip(frame, mode)

    def cycle_camera_flip(self) -> None:
        """Ganti mode orientasi: cermin -> asli -> putar 180 -> cermin."""
        order = [1, 0, -1]
        labels = {1: "cermin (mirror)", 0: "asli (tanpa balik)",
                  -1: "putar 180 (kamera terbalik)"}
        try:
            cur = order.index(self._camera_flip())
        except ValueError:
            cur = 0
        nxt = order[(cur + 1) % len(order)]
        self.settings.set("camera_flip", nxt)
        self.settings.save()
        print(f"[INFO] Orientasi kamera: {labels[nxt]} (tersimpan).")

    def _camera_index(self) -> int:
        try:
            idx = int(self.settings.get("camera_index",
                                        CONFIG.camera_index))
            return idx if 0 <= idx <= 5 else CONFIG.camera_index
        except (TypeError, ValueError):
            return CONFIG.camera_index

    def open_camera(self) -> bool:
        idx = self._camera_index()
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)  # fallback backend
        if not cap.isOpened():
            print("[ERROR] Webcam tidak tersedia. Periksa kamera / izin "
                  "aplikasi / index kamera.")
            print("        Ubah 'camera_index' di Settings "
                  "(coba 0, 1, 2).")
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG.camera_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG.camera_height)
        self.cap = cap
        return True

    def open_tracker(self) -> bool:
        try:
            self.tracker = HandTracker(
                model_asset_path=CONFIG.model_asset_path,
                max_num_hands=CONFIG.max_num_hands,
                min_detection_confidence=CONFIG.min_detection_confidence,
                min_tracking_confidence=CONFIG.min_tracking_confidence,
            )
            return True
        except Exception as exc:
            print(f"[ERROR] Gagal memuat model MediaPipe: {exc}")
            print(f"        Pastikan file '{CONFIG.model_asset_path}' ada.")
            return False

    def open_gui(self) -> None:
        """Bangun GUI; bila gagal, pakai mode klasik OpenCV."""
        try:
            from src.gui import AppGui

            self.gui = AppGui(
                CONFIG.gui,
                self.state,
                self.processor,
                settings=self.settings,
                on_toggle_mouse=self.toggle_mouse,
                on_toggle_voice=self.toggle_voice,
                on_toggle_camera=self.toggle_camera,
                on_toggle_hand=self.toggle_hand,
                on_toggle_presentation=self.toggle_presentation,
                on_toggle_typing=self.toggle_typing,
                on_toggle_telegram=self.toggle_telegram,
                on_open_settings=self.apply_settings,
                on_exit=self.request_exit,
            )
            self.use_gui = True
        except Exception as exc:
            print(f"[WARNING] GUI tidak tersedia ({exc}). "
                  "Memakai mode klasik (jendela OpenCV).")
            self.gui = None
            self.use_gui = False
            cv2.namedWindow(CONFIG.window_name)
            cv2.setMouseCallback(CONFIG.window_name, self._on_classic_mouse)

    # ---------- kontrol (dipakai GUI, keyboard, & voice command) ----------

    def toggle_mouse(self) -> None:
        enabled = self.state.toggle_mouse()
        print(f"[INFO] Hand gesture mouse: {'ON' if enabled else 'OFF'}")

    def toggle_hand(self) -> None:
        enabled = self.state.toggle_hand()
        print(f"[INFO] Hand tracking: {'ON' if enabled else 'OFF'}")

    def toggle_camera(self) -> None:
        on = not self.state.is_camera_on()
        self.state.set_camera(on)
        print(f"[INFO] Kamera: {'ON' if on else 'OFF (hemat CPU)'}")

    def toggle_presentation(self) -> None:
        on = not self.state.is_presentation()
        self.state.set_presentation(on)
        print(f"[INFO] Mode presentasi: {'ON (NEXT/PREV aktif)' if on else 'OFF'}")

    def toggle_typing(self) -> None:
        on = not self.state.is_typing()
        self.state.set_typing(on)
        print(f"[INFO] Voice typing: {'ON (ucapan diketik)' if on else 'OFF'}")

    def toggle_voice(self) -> None:
        if not self.voice.available:
            print("[VOICE] Voice tidak tersedia (mic/SpeechRecognition).")
            return
        listening = not self.state.is_listening()
        self.state.set_listening(listening)
        print(f"[VOICE] {'Mendengarkan.' if listening else 'Berhenti.'}")

    # ---------- telegram (receiver non-blocking, eksekusi di main thread) --

    def start_telegram(self) -> None:
        """Nyalakan Telegram control (aman dipanggil ulang dari GUI)."""
        if TelegramController is None:
            print("[TELEGRAM] Modul telegram_controller tidak tersedia.")
            return
        if self.telegram is not None and self.telegram.running:
            print("[TELEGRAM] Bot sudah berjalan.")
            return
        try:
            if self.telegram is None:
                self.telegram = TelegramController(self.state)
            self.state.set_telegram_enabled(True)
            self.telegram.start()
            self.telegram.reload_custom()
        except Exception as exc:
            print(f"[TELEGRAM] Gagal start: {exc}")
            print("[TELEGRAM] Telegram control disabled")
            print("[HAND] Hand gesture still running")
            print("[VOICE] Voice control still running")

    def stop_telegram(self) -> None:
        """Matikan Telegram saja; gesture + voice tetap berjalan."""
        self.state.set_telegram_enabled(False)
        if self.telegram is not None:
            try:
                self.telegram.stop()
            except Exception:
                pass

    def toggle_telegram(self) -> None:
        if self.telegram is not None and self.telegram.running:
            self.stop_telegram()
        else:
            self.start_telegram()

    def _poll_telegram(self) -> None:
        """Eksekusi antrean Telegram di MAIN thread (pyautogui-safe)."""
        for _ in range(5):
            item = self.state.take_telegram()
            if not item:
                break
            kind = item.get("kind")
            payload = item.get("payload", {})
            chat_id = payload.get("chat_id", 0)
            try:
                if kind == "command":
                    phrase = payload.get("phrase", "")
                    ok, msg = self.processor.execute(phrase)
                    label = f"Telegram: {payload.get('label', phrase)} | {msg}"
                    self.state.set_command_result(label)
                    print(f"[TELEGRAM] {label}")
                    if self.telegram is not None and chat_id:
                        self.telegram.notify_result(chat_id, ok, msg)
                elif kind == "screenshot":
                    self._telegram_screenshot(chat_id)
                elif kind == "status":
                    from src.telegram_controller import laptop_status_text

                    if self.telegram is not None and chat_id:
                        self.telegram.send_message(
                            chat_id, laptop_status_text(self.state))
                elif kind == "window":
                    info = wm.get_active_window()
                    self.state.set_active_window(info["title"], info["app"])
                    if self.telegram is not None and chat_id:
                        self.telegram.send_message(
                            chat_id,
                            f"🪟 *Active Window*\n\n"
                            f"Aplikasi: {info['app']}\n"
                            f"Judul: {info['title'][:80]}")
                elif kind == "toggle":
                    target = payload.get("target")
                    if target == "mouse":
                        enabled = self.state.toggle_mouse()
                        msg = (f"Hand gesture mouse "
                               f"{'AKTIF' if enabled else 'NONAKTIF'}.")
                        print(f"[TELEGRAM] {msg}")
                        if self.telegram is not None and chat_id:
                            self.telegram.notify_result(chat_id, True, msg)
                    elif target == "voice":
                        if not self.voice.available:
                            msg = ("Voice tidak tersedia "
                                   "(mic/SpeechRecognition).")
                            print(f"[TELEGRAM] {msg}")
                            if self.telegram is not None and chat_id:
                                self.telegram.notify_result(
                                    chat_id, False, msg)
                        else:
                            listening = not self.state.is_listening()
                            self.state.set_listening(listening)
                            msg = ("Mendengarkan perintah."
                                   if listening else "Berhenti mendengarkan.")
                            print(f"[TELEGRAM] Voice: {msg}")
                            if self.telegram is not None and chat_id:
                                self.telegram.notify_result(
                                    chat_id, True, msg)
            except Exception as exc:
                print(f"[TELEGRAM] Gagal eksekusi antrean: {exc}")
                if self.telegram is not None and chat_id:
                    try:
                        self.telegram.notify_result(
                            chat_id, False, f"Gagal: {exc}")
                    except Exception:
                        pass

    def _telegram_screenshot(self, chat_id: int) -> None:
        """Screenshot di main thread, kirim file via bot thread."""
        from src import screenshot as shots

        ok, msg = shots.take_full()
        print(f"[TELEGRAM] Screenshot: {msg}")
        if self.telegram is None or not chat_id:
            return
        if ok:
            # Ambil path dari pesan "Screenshot tersimpan: <path>".
            path = msg.split("Screenshot tersimpan:")[-1].strip()
            self.telegram.send_photo(chat_id, path,
                                     caption="📸 Screenshot laptop")
        else:
            self.telegram.send_message(chat_id,
                                       f"❌ Screenshot gagal.\n\n{msg}")

    def request_exit(self) -> None:
        self.state.stop()

    # ---------- overlay klasik (fallback bila GUI gagal) ----------

    def _on_classic_mouse(self, event, x, y, flags, param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        x1, y1, x2, y2 = BUTTON_RECT
        vx1, vy1, vx2, vy2 = BUTTON_VOICE_RECT
        if x1 <= x <= x2 and y1 <= y <= y2:
            self.toggle_mouse()
        elif vx1 <= x <= vx2 and vy1 <= y <= vy2:
            self.toggle_voice()

    def _draw_classic(self, frame, fps: float) -> None:
        x1, y1, x2, y2 = BUTTON_RECT
        vx1, vy1, vx2, vy2 = BUTTON_VOICE_RECT
        snap = self.state.snapshot()
        color = (60, 180, 60) if snap["mouse_enabled"] else (60, 60, 220)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, -1)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
        cv2.putText(frame, "MOUSE: ON" if snap["mouse_enabled"] else "MOUSE: OFF",
                    (x1 + 12, y1 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
        vcolor = (60, 180, 60) if snap["voice_listening"] else (90, 90, 90)
        cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), vcolor, -1)
        cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 255, 255), 2)
        cv2.putText(frame, "VOICE: ON" if snap["voice_listening"] else "VOICE: OFF",
                    (vx1 + 12, vy1 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
        h, w = frame.shape[:2]
        cv2.putText(frame, f"Gesture: {self.gesture.name}", (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(frame, f"Aksi: {self.action}", (10, 108),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.putText(frame, f"Voice: {snap['last_voice']}", (10, 136),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 200), 2)
        cv2.putText(frame, f"Action: {snap['last_command_status']}"[:90],
                    (10, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (200, 255, 200), 1)
        cv2.putText(frame, f"FPS: {fps:.1f}", (w - 130, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        if self.show_help:
            lines = [
                "1 jari: gerak | Pinch cepat: klik kiri",
                "Pinch tahan+gerak: drag | 2 jari: scroll",
                "Telapak terbuka: pause | M: mouse V: voice Q: keluar",
            ]
            y = h - 20 - len(lines) * 22
            for line in lines:
                y += 22
                cv2.putText(frame, line, (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)

    # ---------- loop utama ----------

    def run(self) -> int:
        if not self.open_camera():
            return 1
        if not self.open_tracker():
            self.cap.release()
            return 1
        self.mouse = MouseController(self._mouse_config())
        self.open_gui()

        # Voice opsional: gagal init -> aplikasi tetap jalan tanpa voice.
        if CONFIG.voice.enabled:
            self.voice.start()
        else:
            self.state.set_voice_status("STOPPED")

        # Telegram opsional: gagal/kosong -> hand + voice tetap jalan.
        try:
            self.start_telegram()
        except Exception as exc:
            print(f"[TELEGRAM] Telegram control disabled ({exc})")

        print("[INFO] Hand Gesture: ON")
        print(f"[INFO] Voice Control: "
              f"{'ON' if self.voice.available else 'UNAVAILABLE (hand only)'}")
        if self.voice.available:
            print("[INFO] Listening... ucapkan mis. 'buka chrome'.")
        print("[INFO] Tombol: M=mouse V=voice C=kalibrasi K=kamera "
              "G=hand P=presentasi T=typing Q=keluar")

        try:
            while self.state.is_running():
                # 1. Kuras antrean perintah suara (FIFO, anti-duplikat).
                for _ in range(5):
                    pending = self.state.take_command()
                    if not pending:
                        break
                    self.processor.execute(pending)

                # 1b. Kuras antrean Telegram (eksekusi di main thread).
                self._poll_telegram()

                # 2. Satu frame webcam + hand tracking (skip bila kamera OFF).
                if not self.state.is_camera_on():
                    time.sleep(0.05)
                    if self.use_gui and self.gui is not None:
                        if self.gui.closed:
                            break
                        self.gui.update_status(self.state.snapshot())
                        self.gui.process_events()
                    continue
                ok, frame = self.cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
                frame = self._orient_frame(frame)
                fh, fw = frame.shape[:2]
                now = time.time()
                fps = (0.9 * self._last_fps()
                       + 0.1 * (1.0 / max(now - self.prev_t, 1e-6)))
                self.prev_t = now
                self._set_fps(fps)

                self._process_frame(frame, fh, fw, now, fps)

                # Active window (§2): judul + nama app tiap ~30 frame.
                self._frame_count += 1
                if self._frame_count % 30 == 0:
                    info = wm.get_active_window()
                    self.state.set_active_window(info["title"],
                                                 info["app"])

                # 3. Tampilkan.
                if self.use_gui and self.gui is not None:
                    if self.gui.closed:
                        break
                    self.gui.update_frame(frame)
                    self.gui.update_status(self.state.snapshot())
                    self.gui.process_events()
                else:
                    self._draw_classic(frame, fps)
                    cv2.imshow(CONFIG.window_name, frame)
                    if not self._handle_key(cv2.waitKey(1) & 0xFF):
                        break
        except KeyboardInterrupt:
            print("\n[INFO] Dihentikan pengguna (Ctrl+C).")
        except Exception as exc:
            print(f"[ERROR] Kesalahan tak terduga: {exc}")
            return 1
        finally:
            self.shutdown()
        return 0

    def _last_fps(self) -> float:
        return self.state.snapshot()["fps"]

    def _set_fps(self, fps: float) -> None:
        # disimpan via set_gesture tiap frame; placeholder agar run() rapi
        self._fps = fps

    def _process_frame(self, frame, fh: int, fw: int, now: float, fps: float) -> None:
        if not self.state.is_hand_enabled():
            # Hand tracking OFF: lepas drag, diam, hemat CPU (§13/§17).
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self.gesture = GestureState(name="NO_HAND")
            self.action = "Hand OFF"
            self.state.set_gesture("NO_HAND", self.action, fps)
            return

        hands = self.tracker.process(frame)
        hand = hands[0] if hands else None

        if hand is None:
            self.no_hand_frames += 1
            self.gesture = GestureState(name="NO_HAND")
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self._prev_gesture = "NO_HAND"
            if self.no_hand_frames > 30:
                self.mouse.reset_smoothing()
            self.state.set_gesture("NO_HAND", self.mouse.last_action, fps)
            return

        self.no_hand_frames = 0
        pts = self.tracker.landmarks_to_pixels(hand, fw, fh)
        self.tracker.draw(frame, pts)
        cfg = self.mouse.cfg  # config efektif (settings override)
        self.gesture = classify(pts, cfg.pinch_threshold_px)
        ix, iy = self.gesture.index_tip
        cv2.circle(frame, (int(ix), int(iy)), 8, (255, 0, 255), -1)

        name = self.gesture.name
        is_new = name != self._prev_gesture  # edge-trigger sekali-tembak
        if name not in ("R_CLICK", "DOUBLE", "NEXT", "PREV"):
            pass  # state kontinu (pinch/scroll/zoom) dikelola controller
        self._prev_gesture = name

        mouse_on = self.state.is_mouse_enabled()
        presenting = self.state.is_presentation()
        if not mouse_on or name == "PAUSE":
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self.action = ("Paused" if name == "PAUSE" else "Nonaktif")
        elif name in ("MOVE", "POINTER") and not presenting:
            self.mouse.move(ix, iy, fw, fh)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self.action = ("Pointer" if name == "POINTER"
                           else "Gerak kursor")
        elif name == "POINTER" and presenting:
            # §13: POINTER = pointer slide (cursor boleh gerak).
            self.mouse.move(ix, iy, fw, fh)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self.action = "Pointer"
        elif name == "PINCH" and not presenting:
            self.action = self.mouse.update_pinch(True, ix, iy, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
        elif name == "PINCH" and presenting and is_new:
            # §13: PINCH saat presentasi = klik slide (sekali per edge).
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            try:
                import pyautogui

                pyautogui.click(button="left")
                self.action = "Klik slide"
            except Exception as exc:
                self.action = f"Gagal klik: {exc}"
        elif name == "R_CLICK" and not presenting:
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            if is_new:
                self.action = self.mouse.trigger_right_click(now=now)
            else:
                self.action = self.mouse.last_action
        elif name == "DOUBLE" and not presenting:
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            if is_new:
                self.action = self.mouse.trigger_double_click(now=now)
            else:
                self.action = self.mouse.last_action
        elif name == "SCROLL" and not presenting:
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.action = self.mouse.update_scroll(self.gesture.middle_tip[1],
                                                   now=now)
        elif name == "ZOOM" and not presenting:
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            hand_y = float(pts[9, 1])  # titik tengah telapak
            self.action = self.mouse.update_zoom(hand_y, now=now)
        elif name in ("NEXT", "PREV"):
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            # Slide hanya bila mode presentasi + edge + cooldown (§13).
            if (is_new and presenting
                    and (now - self._last_slide)
                    >= CONFIG.presentation_next_cooldown_sec):
                self._last_slide = now
                ok, msg = (wc.slide_next() if name == "NEXT"
                           else wc.slide_prev())
                self.action = msg
            else:
                self.action = ("Slide berikutnya (butuh mode presentasi)"
                               if name == "NEXT"
                               else "Slide sebelumnya (butuh mode presentasi)")
        elif presenting:
            # §13: gesture mouse lain ditahan selama presentasi.
            self.mouse.update_pinch(False, 0, 0, fw, fh, now=now)
            self.mouse.reset_scroll()
            self.mouse.reset_zoom()
            self.action = "Mode presentasi (mouse off)"
        else:
            self.action = self.mouse.last_action
        self.state.set_gesture(name, self.action, fps)

    def _handle_key(self, key: int) -> bool:
        if key in (27, ord("q"), ord("Q")):
            return False
        if key in (ord("m"), ord("M")):
            self.toggle_mouse()
        elif key in (ord("v"), ord("V")):
            self.toggle_voice()
        elif key in (ord("c"), ord("C")):
            # Kalibrasi ROI kamera -> mapping presisi.
            try:
                ok, frame = self.cap.read()
                if ok and frame is not None:
                    fh, fw = frame.shape[:2]
                    self.mouse.calibrate(fw, fh)
                    print("[INFO] Kamera dikalibrasi (ROI 15%).")
            except Exception as exc:
                print(f"[WARNING] Kalibrasi gagal: {exc}")
        elif key in (ord("k"), ord("K")):
            self.toggle_camera()
        elif key in (ord("g"), ord("G")):
            self.toggle_hand()
        elif key in (ord("p"), ord("P")):
            self.toggle_presentation()
        elif key in (ord("t"), ord("T")):
            self.toggle_typing()
        elif key in (ord("h"), ord("H")):
            self.show_help = not self.show_help
        elif key in (ord("f"), ord("F")):
            self.cycle_camera_flip()
        return True

    def shutdown(self) -> None:
        self.state.stop()
        try:
            self.voice.stop()
        except Exception:
            pass
        try:
            if self.telegram is not None:
                self.telegram.stop()
        except Exception:
            pass
        try:
            if self.mouse is not None:
                self.mouse.force_release()
        except Exception:
            pass
        try:
            if self.tracker is not None:
                self.tracker.close()
        except Exception:
            pass
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        try:
            if self.gui is not None:
                self.gui.close()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


def main() -> int:
    return App().run()


if __name__ == "__main__":
    raise SystemExit(main())
