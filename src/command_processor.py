"""Command processor: STT -> Intent Detection -> aksi whitelist.

Alur (lihat src/intent_detector.py):
    Speech -> Speech-to-Text -> Intent Detection
           -> Command Processor -> Action
Chaining ("lalu", ",", "dan"), mode typing, custom commands.json,
workflow bawaan, dan histori — semua di sini.
Keamanan: perintah di luar whitelist TIDAK PERNAH dieksekusi; tanpa
os.system/shell; query (cari/buka file) hanya jadi parameter jinak.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from . import clipboard as cb
from . import intent_detector as intent
from . import screenshot_tools as shots
from . import windows_controller as wc
from . import workflows as wf
from .app_state import AppState
from .command_history import CommandHistory

Action = Callable[[str], tuple[bool, str]]  # fn(sisa_teks) -> (ok, pesan)


def normalize(text: str) -> str:
    """Lowercase, buang diakritik & tanda baca, rapatkan spasi."""
    return intent._norm(text)


def _set_mouse(state: AppState, on: bool):
    def _fn(_rest: str) -> tuple[bool, str]:
        state.set_mouse(on)
        return True, f"Hand gesture mouse {'AKTIF' if on else 'NONAKTIF'}."
    return _fn


def _set_listen(state: AppState, on: bool):
    def _fn(_rest: str) -> tuple[bool, str]:
        state.set_listening(on)
        return True, ("Mendengarkan perintah." if on
                      else "Berhenti mendengarkan. Ucapkan 'mulai mendengarkan'.")
    return _fn


def _set_presentation(state: AppState, on: bool):
    def _fn(_rest: str) -> tuple[bool, str]:
        state.set_presentation(on)
        return True, (f"Mode presentasi AKTIF. Gesture: ✋=next, ✊=prev, "
                      f"☝=pointer, 👌=klik." if on else "Mode presentasi mati.")
    return _fn


def _set_typing(state: AppState, on: bool):
    def _fn(_rest: str) -> tuple[bool, str]:
        state.set_typing(on)
        return True, ("Mode mengetik AKTIF: ucapan akan diketik ke window aktif."
                      if on else "Mode mengetik berhenti.")
    return _fn


def _volume_percent(state: AppState):
    def _fn(rest: str) -> tuple[bool, str]:
        v = wc.parse_percent(rest)
        if v is None:
            return False, "Sebutkan persen volume (mis. 'volume 50 persen')."
        return wc.volume_set(v)
    return _fn


def _search_google(state: AppState):
    def _fn(rest: str) -> tuple[bool, str]:
        q = _strip_leading(rest, ["cari di google", "cari di gugel",
                                  "cari", "carikan", "search"])
        return wc.search_google(q)
    return _fn


def _search_youtube(state: AppState):
    def _fn(rest: str) -> tuple[bool, str]:
        q = _strip_leading(rest, ["buka youtube dan cari", "buka yutub dan cari",
                                  "cari di youtube", "cari"])
        if not q:
            q = _strip_leading(rest, ["buka youtube", "buka yutub"])
        return wc.search_youtube(q)
    return _fn


def _strip_leading(text: str, prefixes: list[str]) -> str:
    t = (text or "").strip()
    for p in sorted(prefixes, key=len, reverse=True):
        if t.startswith(p):
            return t[len(p):].strip(" ,.")
    return t


def _find_file(state: AppState):
    def _fn(rest: str) -> tuple[bool, str]:
        q = _strip_leading(rest, ["cari file", "cari berkas", "cari"])
        return wc.find_file(q)
    return _fn


def _open_file(state: AppState):
    def _fn(rest: str) -> tuple[bool, str]:
        q = _strip_leading(rest, ["buka file", "bukakan file", "buka"])
        return wc.open_found_file(q)
    return _fn


def _press(state: AppState, key: str, label: str):
    def _fn(_rest: str) -> tuple[bool, str]:
        return wc.press_key(key)
    _fn.__doc__ = label
    return _fn


def _simple(fn):
    def _fn(_rest: str) -> tuple[bool, str]:
        return fn()
    return _fn


def build_registry(state: AppState) -> list[tuple[str, list[str], Action]]:
    """(kunci, frasa, aksi). Frasa dicocokkan substring; terpanjang menang."""
    return [
        # --- aplikasi ---
        ("open_chrome", ["buka chrome", "bukakan chrome", "open chrome"],
         _simple(lambda: wc.open_app("chrome"))),
        ("close_chrome", ["tutup chrome", "tutup krom", "close chrome"],
         _simple(lambda: wc.close_app("chrome"))),
        ("minimize_chrome", ["minimize chrome", "minimalkan chrome",
                             "kecilkan chrome"],
         _simple(lambda: wc.minimize_window("chrome"))),
        ("maximize_chrome", ["maximize chrome", "maksimalkan chrome",
                             "besarkan chrome"],
         _simple(lambda: wc.maximize_window("chrome"))),
        ("focus_chrome", ["pindah ke chrome", "fokus ke chrome",
                          "ke chrome", "focus chrome"],
         _simple(lambda: wc.focus_window("chrome"))),
        ("focus_vscode", ["pindah ke vs code", "pindah ke vscode",
                          "fokus ke vs code", "ke vs code"],
         _simple(lambda: wc.focus_window("vscode"))),
        ("focus_whatsapp", ["pindah ke whatsapp", "pindah ke wa",
                            "fokus ke whatsapp", "ke whatsapp"],
         _simple(lambda: wc.focus_window("whatsapp"))),
        ("focus_powerpoint", ["pindah ke powerpoint",
                              "fokus ke powerpoint", "ke powerpoint"],
         _simple(lambda: wc.focus_window("powerpoint"))),
        ("open_vscode", ["buka vs code", "buka vscode", "bukakan vs code",
                         "open vs code", "buka visual studio code"],
         _simple(lambda: wc.open_app("vscode"))),
        ("open_whatsapp", ["buka whatsapp", "buka wa", "bukakan whatsapp",
                           "open whatsapp"],
         _simple(lambda: wc.open_app("whatsapp"))),
        ("open_powerpoint", ["buka powerpoint", "buka ppt",
                             "open powerpoint"],
         _simple(lambda: wc.open_app("powerpoint"))),
        ("open_project", ["buka folder project", "buka project",
                          "buka folder projek"],
         _simple(lambda: wc.open_folder("project"))),
        # --- konteks window aktif ---
        ("close_this", ["tutup ini", "tutup jendela ini", "tutup window ini",
                        "close this"],
         _simple(wc.close_active_window)),
        ("minimize_this", ["minimize ini", "minimalkan ini",
                           "kecilkan ini", "minimize ini"],
         _simple(lambda: wc.minimize_window(None))),
        ("maximize_this", ["maximize ini", "maksimalkan ini",
                           "besarkan ini", "maximize ini"],
         _simple(lambda: wc.maximize_window(None))),
        ("restore_this", ["kembalikan ini", "pulihkan ini", "restore ini",
                          "restore window", "kembalikan window"],
         _simple(lambda: wc.restore_window(None))),
        # --- website & pencarian ---
        ("open_youtube", ["buka youtube dan cari", "buka yutub dan cari",
                          "buka youtube", "bukakan youtube", "buka yutub",
                          "bukakan yutub", "open youtube"],
         _search_youtube(state)),
        ("open_google", ["buka google", "bukakan google", "open google"],
         _simple(lambda: wc.open_site("google"))),
        ("open_github", ["buka github", "buka git hub", "open github"],
         _simple(lambda: wc.open_site("github"))),
        ("open_gmail", ["buka gmail", "buka email", "open gmail"],
         _simple(lambda: wc.open_site("gmail"))),
        ("search_google", ["cari di google", "cari di gugel", "carikan",
                           "cari"],
         _search_google(state)),
        # --- file & folder ---
        ("open_downloads", ["buka folder download", "bukakan folder download",
                            "buka download", "buka downloads", "buka unduhan",
                            "open download"],
         _simple(lambda: wc.open_folder("downloads"))),
        ("open_documents", ["buka documents", "buka dokumen", "buka document",
                            "open documents"],
         _simple(lambda: wc.open_folder("documents"))),
        ("open_desktop", ["buka desktop", "open desktop"],
         _simple(lambda: wc.open_folder("desktop"))),
        ("open_pictures", ["buka pictures", "buka gambar", "buka foto",
                           "open pictures", "buka screenshots"],
         _simple(lambda: wc.open_folder("pictures"))),
        ("find_file", ["cari file", "cari berkas"],
         _find_file(state)),
        ("open_file", ["buka file", "bukakan file"],
         _open_file(state)),
        ("make_folder", ["buat folder baru", "bikin folder baru",
                         "buat folder", "new folder"],
         _simple(wc.make_folder_here)),
        # --- screenshot & recording ---
        ("screenshot", ["screenshot layar", "ambil screenshot",
                        "screenshot", "ambil gambar", "tangkap layar",
                        "foto layar", "screen shot"],
         _simple(shots.screenshot_full)),
        ("screenshot_active", ["screenshot window aktif",
                               "screenshot jendela aktif",
                               "screenshot window", "screenshot jendela",
                               "screenshot aktif"],
         _simple(shots.screenshot_active)),
        ("screenshot_area", ["screenshot area", "screenshot sebagian",
                             "tangkap area"],
         _simple(shots.screenshot_region)),
        ("rec_start", ["mulai recording", "mulai rekam", "start recording",
                       "rekam layar"],
         _simple(lambda: shots.start_recording())),
        ("rec_stop", ["stop recording", "berhenti recording",
                      "berhenti rekam", "hentikan recording"],
         _simple(shots.stop_recording)),
        # --- sistem: volume/brightness/media ---
        ("volume_up", ["volume naik", "volumenya naik", "besarkan suara",
                       "keraskan suara", "volume up"],
         _simple(wc.volume_up)),
        ("volume_down", ["volume turun", "volumenya turun", "kecilkan suara",
                         "pelankan suara", "volume down"],
         _simple(wc.volume_down)),
        ("volume_set", ["volume", "atur volume"],
         _volume_percent(state)),
        ("mute", ["mute", "bisukan", "matikan suara", "hening", "unmute"],
         _simple(wc.volume_mute)),
        ("brightness_up", ["brightness naik", "cerahkan layar",
                           "brightness up"],
         _simple(lambda: wc.brightness(True))),
        ("brightness_down", ["brightness turun", "redupkan layar",
                             "brightness down"],
         _simple(lambda: wc.brightness(False))),
        ("media_play", ["play", "putar", "mainkan"],
         _simple(lambda: wc.media("play"))),
        ("media_pause", ["pause", "jeda", "tahan dulu"],
         _simple(lambda: wc.media("pause"))),
        ("media_next", ["next", "lanjut", "berikutnya", "lagu berikutnya"],
         _simple(lambda: wc.media("next"))),
        ("media_prev", ["previous", "sebelumnya", "lagu sebelumnya",
                        "mundur"],
         _simple(lambda: wc.media("previous"))),
        # --- mouse via suara ---
        ("click_left", ["klik kiri", "click kiri", "left click"],
         _simple(lambda: wc.voice_click("left"))),
        ("click_right", ["klik kanan", "click kanan", "right click"],
         _simple(lambda: wc.voice_click("right"))),
        ("double_click", ["double click", "klik dua kali",
                          "klik ganda", "double klik"],
         _simple(lambda: wc.voice_click("double"))),
        ("scroll_up", ["scroll ke atas", "gulir ke atas", "scroll up",
                       "geser ke atas"],
         _simple(lambda: wc.voice_scroll("up"))),
        ("scroll_down", ["scroll ke bawah", "gulir ke bawah",
                         "scroll down", "geser ke bawah"],
         _simple(lambda: wc.voice_scroll("down"))),
        # --- keyboard ---
        ("press_enter", ["tekan enter", "enter", "press enter"],
         _press(state, "enter", "Enter")),
        ("press_esc", ["tekan escape", "tekan esc", "escape", "esc"],
         _press(state, "esc", "Escape")),
        ("copy", ["copy", "salin", "copi"],
         _simple(cb.copy)),
        ("paste", ["paste", "tempel", "timpal"],
         _simple(cb.paste)),
        ("cut", ["cut", "potong", "gunting"],
         _simple(cb.cut)),
        ("select_all", ["select all", "pilih semua", "blok semua"],
         _simple(cb.select_all)),
        ("clear_clipboard", ["clear clipboard", "kosongkan clipboard",
                             "hapus clipboard", "bersihkan clipboard"],
         _simple(cb.clear)),
        ("open_clipboard", ["buka clipboard", "tampilkan clipboard",
                            "lihat clipboard", "open clipboard"],
         _simple(cb.show)),
        # --- workflow bawaan ---
        ("workflow_coding", ["saya mau coding", "mau coding",
                             "mode coding", "workflow coding"],
         lambda rest: ("WORKFLOW", "coding")),
        ("workflow_presentasi", ["saya mau presentasi", "mau presentasi",
                                 "mode presentasi siap",
                                 "workflow presentasi"],
         lambda rest: ("WORKFLOW", "presentasi")),
        ("tile_windows", ["susun window", "atur window",
                          "tile windows", "rapikan window"],
         _simple(wc.tile_side_by_side)),
        # --- mode presentasi & typing ---
        ("presentation_on", ["aktifkan mode presentasi",
                             "nyalakan mode presentasi",
                             "mode presentasi"],
         _set_presentation(state, True)),
        ("presentation_off", ["matikan mode presentasi",
                              "nonaktifkan mode presentasi",
                              "keluar mode presentasi"],
         _set_presentation(state, False)),
        ("presentation_fullscreen", ["mulai presentasi", "fullscreen",
                                     "tampilkan presentasi",
                                     "jalan presentasi"],
         _simple(wc.presentation_fullscreen)),
        ("slide_next", ["slide berikutnya", "slide selanjutnya",
                        "next slide", "lanjut slide"],
         _simple(wc.slide_next)),
        ("slide_prev", ["slide sebelumnya", "slide kembali",
                        "previous slide", "slide mundur"],
         _simple(wc.slide_prev)),
        ("typing_on", ["mulai mengetik", "mode mengetik",
                       "aktifkan mengetik", "start typing"],
         _set_typing(state, True)),
        ("typing_off", ["berhenti mengetik", "stop mengetik",
                        "matikan mengetik", "stop typing",
                        "keluar mode mengetik"],
         _set_typing(state, False)),
        # --- mouse & voice (lama, dipertahankan) ---
        ("mouse_on", ["aktifkan mouse", "nyalakan mouse",
                      "aktifkan tetikus", "mouse on", "enable mouse"],
         _set_mouse(state, True)),
        ("mouse_off", ["matikan mouse", "nonaktifkan mouse",
                       "matikan tetikus", "mouse off", "disable mouse"],
         _set_mouse(state, False)),
        ("listen_stop", ["berhenti mendengarkan", "stop mendengarkan",
                         "berhenti mendengar", "stop listening"],
         _set_listen(state, False)),
        ("listen_start", ["mulai mendengarkan", "mulai mendengarkan lagi",
                          "dengar lagi", "start listening"],
         _set_listen(state, True)),
    ]


# Frasa yang SELALU diproses sebagai command walau typing mode aktif
# (agar pengguna bisa keluar dari mode typing).
_TYPING_ESCAPES = ("berhenti mengetik", "stop mengetik", "matikan mengetik",
                   "stop typing", "keluar mode mengetik")


class CommandProcessor:
    """Normalisasi + chaining + whitelist + histori."""

    def __init__(self, state: AppState, history: CommandHistory | None = None) -> None:
        from .config import CONFIG as _CFG

        self._state = state
        self._cfg = _CFG
        self._history = history or CommandHistory(
            file=_CFG.history_file, max_entries=_CFG.history_max)
        self._registry = build_registry(state)
        self._flat: list[tuple[str, str, Action]] = sorted(
            ((key, phrase, fn) for key, phrases, fn in self._registry
             for phrase in phrases),
            key=lambda item: -len(item[1]),
        )
        self._custom = wf.load_custom()

    @property
    def history(self) -> CommandHistory:
        return self._history

    @property
    def known_phrases(self) -> list[str]:
        seen: list[str] = []
        for _, phrases, _ in self._registry:
            for p in phrases:
                if p not in seen:
                    seen.append(p)
        return seen

    # ---------- pencocokan ----------

    def match(self, text: str) -> tuple[str | None, str]:
        norm = normalize(text)
        if not norm:
            return None, ""
        for key, phrase, _ in self._flat:
            if phrase in norm:
                return key, phrase
        return None, ""

    def split_chain(self, text: str) -> list[str]:
        """Pecah kalimat majemuk menjadi segmen perintah."""
        norm = normalize(text)
        parts = [norm]
        for sep in self._cfg.chain_separators:
            nxt: list[str] = []
            for p in parts:
                nxt.extend([s.strip() for s in p.split(sep) if s.strip()])
            parts = nxt
        # Buang kata penghubung sisa di awal segmen ("lalu", "dan", ...).
        fillers = ("lalu ", "kemudian ", "dan ", "terus ")
        cleaned = []
        for p in parts:
            for f in fillers:
                if p.startswith(f):
                    p = p[len(f):]
            if p:
                cleaned.append(p)
        return cleaned[:self._cfg.chain_max_commands]

    def match_custom(self, text: str) -> list[str] | None:
        norm = normalize(text)
        for phrase, steps in self._custom.items():
            if phrase and phrase in norm:
                return steps
        return None

    # ---------- eksekusi ----------

    def execute(self, text: str) -> tuple[bool, str]:
        """Dipanggil dari MAIN thread. Kembalikan (sukses, pesan status)."""
        raw = (text or "").strip()
        if not raw:
            return False, "Perintah kosong."
        norm = normalize(raw)

        # Mode typing: semua ucapan diketik, kecuali escape + mouse/voice.
        if self._state.is_typing() and not any(
                e in norm for e in _TYPING_ESCAPES):
            key, _ = self.match(norm)
            if key in ("mouse_on", "mouse_off", "listen_stop",
                       "listen_start", "typing_off"):
                return self._execute_single(raw, norm)
            ok, msg = wc.type_text(raw,
                                   self._cfg.typing_chunk_delay_sec)
            self._state.set_intent("VOICE_TYPING", f"{len(raw)} char")
            label = f"Voice(typing): {raw} | {msg}"
            self._state.set_command_result(label)
            print(f"[VOICE] {label}")
            self._history.add(raw, msg, ok, intent="VOICE_TYPING",
                              error="" if ok else msg)
            return ok, msg

        segments = self.split_chain(raw)
        results: list[tuple[bool, str]] = []
        for seg in segments:
            results.append(self._execute_single(seg, normalize(seg)))
        if len(results) == 1:
            return results[0]
        ok_all = all(r[0] for r in results)
        summary = " | ".join(r[1] for r in results)[:200]
        return ok_all, f"{len(results)} aksi: {summary}"

    def _execute_single(self, raw: str, norm: str) -> tuple[bool, str]:
        # 1. Custom commands.json (frasa -> langkah kunci / open:...).
        steps = self.match_custom(norm)
        if steps:
            resolved = [wf.resolve_step(s) for s in steps]
            unknown = [s for s, r in zip(steps, resolved) if r is None]
            if unknown:
                msg = (f"Langkah tidak dikenal diabaikan: "
                       f"{', '.join(unknown[:3])}")
                self._finish(raw, "CUSTOM_WORKFLOW", "", False, msg)
                return False, msg
            return self._execute_steps(raw, [r for r in resolved if r],
                                       label="Custom")

        # 2. Intent detection (rule-based, ringan).
        #    Fallback ke substring registry bila UNKNOWN (kompat lama).
        ir = intent.detect(norm)
        key = ir.key
        if key is None:
            key, _ = self.match(norm)
            if key is not None:
                ir = intent.IntentResult(key, *intent.intent_of_key(key),
                                         "", 0.8, "registry")
        if key == "workflow_coding":
            self._state.set_intent("WORKFLOW", "coding")
            return self._execute_steps(raw, wf.builtin_coding(),
                                       label="Workflow coding")
        if key == "workflow_presentasi":
            self._state.set_intent("WORKFLOW", "presentasi")
            return self._execute_steps(raw, wf.builtin_presentasi(),
                                       label="Workflow presentasi")

        # 3. Registry whitelist (kunci dari intent — tidak pernah arbitrer).
        if key is None:
            return self._finish(raw, "UNKNOWN", "", False,
                                f"Perintah tidak dikenal: '{raw}'")
        self._state.set_intent(ir.intent, ir.target or ir.query)
        for cmd_key, _phrases, fn in self._registry:
            if cmd_key == key:
                try:
                    # Query dari intent (cari/buka file, volume, dsb.)
                    # diutamakan bila ada; fallback: segmen penuh.
                    arg = ir.query if ir.query else norm
                    res = fn(arg)
                    ok, msg = res
                except Exception as exc:
                    ok, msg = False, f"Aksi '{key}' gagal: {exc}"
                return self._finish(raw, ir.intent,
                                    ir.target or ir.query, ok, msg)
        return self._finish(raw, "UNKNOWN", "", False,
                            f"Perintah tidak dikenal: '{raw}'")

    def _finish(self, raw: str, intent_name: str, target: str,
                ok: bool, msg: str) -> tuple[bool, str]:
        label = f"Voice: {raw} | Action: {msg}"
        self._state.set_intent(intent_name, target)
        self._state.set_command_result(label)
        print(f"[VOICE] {label}")
        self._history.add(raw, msg, ok, intent=intent_name,
                          error="" if ok else msg)
        return ok, msg

    def _execute_steps(self, raw: str, steps: list[str],
                       label: str = "Workflow") -> tuple[bool, str]:
        import time as _t

        by_key = {k: fn for k, _p, fn in self._registry}
        msgs: list[str] = []
        ok_all = True
        intents: list[str] = []
        for step in steps[:self._cfg.chain_max_commands]:
            key = wf.resolve_step(step) or step
            fn = by_key.get(key)
            if fn is None:
                msgs.append(f"{key}: kunci tidak dikenal (diabaikan)")
                ok_all = False
                continue
            try:
                ok, msg = fn("")
            except Exception as exc:
                ok, msg = False, f"{key} gagal: {exc}"
            msgs.append(msg)
            ok_all = ok_all and ok
            intents.append(intent.intent_of_key(key)[0])
            _t.sleep(0.6)  # jeda antar langkah agar OS sempat merespons
        summary = " | ".join(msgs)[:200]
        full = f"{label}: {summary}"
        self._state.set_intent(label.upper().replace(" ", "_"),
                               ", ".join(intents[:3]))
        self._state.set_command_result(f"Voice: {raw} | {full}")
        print(f"[VOICE] {full}")
        self._history.add(raw, full, ok_all,
                          intent=label.upper().replace(" ", "_"))
        return ok_all, full

    def reload_custom(self) -> int:
        self._custom = wf.load_custom()
        return len(self._custom)
