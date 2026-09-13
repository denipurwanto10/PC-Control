"""Intent detection ringan (rule-based, tanpa AI berbayar).

Alur: Speech -> STT -> Intent Detection -> Command Processor -> Action.

`detect()` menerima teks hasil STT dan mengembalikan IntentResult
berisi kunci aksi whitelist (sama dengan kunci registry command
processor), intent, target, query, dan confidence. Kunci dijamin
berasal dari tabel whitelist di modul ini — TIDAK PERNAH berupa
perintah arbitrer dari ucapan.

Contoh:
  "buka chrome" / "jalankan chrome" / "tolong buka google chrome" /
  "saya mau membuka chrome"  ->  INTENT=OPEN_APPLICATION TARGET=CHROME
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 %.,]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class IntentResult:
    key: str | None          # kunci aksi whitelist (None bila UNKNOWN)
    intent: str              # mis. OPEN_APPLICATION
    target: str              # mis. chrome / youtube / active
    query: str = ""          # sisa query (cari, file, volume...)
    confidence: float = 0.0
    matched: str = ""        # pemicu yang cocok


# ---------- kosakata ----------

_OPEN_VERBS = ("mau membuka", "mau buka", "tolong bukakan", "tolong buka",
               "coba buka", "bukakan", "buka", "jalankan", "jalanin",
               "nyalakan", "launch", "open", "start", "run")
_CLOSE_VERBS = ("tutupkan", "tutup", "close")
_FOCUS_VERBS = ("pindah ke", "fokus ke", "ganti ke", "fokus", "focus",
                "pindah")
_MINI_WORDS = ("minimize", "minimalkan", "kecilkan")
_MAXI_WORDS = ("maximize", "maksimalkan", "besarkan", "perbesar")
_RESTORE_WORDS = ("restore", "kembalikan", "pulihkan")

_APP_ALIASES: dict[str, list[str]] = {
    "chrome": ["google chrome", "chrome", "krom"],
    "vscode": ["visual studio code", "vs code", "vscode", "v s code"],
    "whatsapp": ["whatsapp", "w a"],
    "powerpoint": ["powerpoint", "power point", "ppt"],
}
_SITE_ALIASES: dict[str, list[str]] = {
    "youtube": ["youtube", "yutub"],
    "google": ["google", "gugel"],
    "github": ["github", "git hub"],
    "gmail": ["gmail", "email"],
}
_FOLDER_ALIASES: dict[str, list[str]] = {
    "downloads": ["folder download", "downloads", "download", "unduhan"],
    "documents": ["documents", "document", "dokumen"],
    "desktop": ["desktop"],
    "project": ["folder project", "folder projek", "project", "projek"],
}

# (key, intent, target, triggers) — dipindai terpanjang dulu.
_EXACT: list[tuple[str, str, str, list[str]]] = [
    ("typing_on", "TYPING_ON", "", ["mulai mengetik", "aktifkan mengetik",
                                    "mode mengetik", "start typing"]),
    ("typing_off", "TYPING_OFF", "", ["berhenti mengetik", "matikan mengetik",
                                      "stop mengetik", "keluar mode mengetik",
                                      "stop typing"]),
    ("presentation_on", "PRESENTATION_ON", "", ["aktifkan mode presentasi",
                                                "nyalakan mode presentasi",
                                                "mode presentasi"]),
    ("presentation_off", "PRESENTATION_OFF", "", ["matikan mode presentasi",
                                                  "nonaktifkan mode presentasi",
                                                  "keluar mode presentasi"]),
    ("slide_next", "SLIDE_NEXT", "", ["slide berikutnya", "slide selanjutnya",
                                      "next slide", "lanjut slide"]),
    ("slide_prev", "SLIDE_PREV", "", ["slide sebelumnya", "slide kembali",
                                      "previous slide", "slide mundur"]),
    ("listen_stop", "LISTEN_STOP", "", ["berhenti mendengarkan",
                                        "stop mendengarkan",
                                        "berhenti mendengar",
                                        "stop listening"]),
    ("listen_start", "LISTEN_START", "", ["mulai mendengarkan lagi",
                                          "mulai mendengarkan", "dengar lagi",
                                          "start listening"]),
    ("mouse_on", "MOUSE_ON", "", ["aktifkan mouse", "nyalakan mouse",
                                  "aktifkan tetikus", "mouse on",
                                  "enable mouse"]),
    ("mouse_off", "MOUSE_OFF", "", ["matikan mouse", "nonaktifkan mouse",
                                    "matikan tetikus", "mouse off",
                                    "disable mouse"]),
    ("rec_start", "START_RECORDING", "", ["mulai recording", "mulai rekam",
                                          "start recording", "rekam layar"]),
    ("rec_stop", "STOP_RECORDING", "", ["berhenti recording", "stop recording",
                                        "berhenti rekam",
                                        "hentikan recording"]),
    ("screenshot_active", "TAKE_SCREENSHOT", "window",
     ["screenshot window aktif", "screenshot jendela aktif",
      "screenshot window", "screenshot jendela", "screenshot aktif"]),
    ("screenshot_area", "TAKE_SCREENSHOT", "region",
     ["screenshot sebagian", "screenshot area", "tangkap area"]),
    ("screenshot", "TAKE_SCREENSHOT", "full",
     ["screenshot layar", "ambil screenshot", "screenshot",
      "ambil gambar", "tangkap layar", "foto layar", "screen shot"]),
    ("volume_up", "VOLUME_UP", "", ["volume naik", "volumenya naik",
                                    "besarkan suara", "keraskan suara",
                                    "volume up"]),
    ("volume_down", "VOLUME_DOWN", "", ["volume turun", "volumenya turun",
                                        "kecilkan suara", "pelankan suara",
                                        "volume down"]),
    ("mute", "MUTE", "", ["matikan suara", "bisukan", "mute", "hening",
                           "unmute"]),
    ("brightness_up", "BRIGHTNESS_UP", "", ["brightness naik",
                                            "cerahkan layar",
                                            "brightness up"]),
    ("brightness_down", "BRIGHTNESS_DOWN", "", ["brightness turun",
                                                "redupkan layar",
                                                "brightness down"]),
    ("media_pause", "MEDIA_PAUSE", "", ["pause", "jeda", "tahan dulu"]),
    ("media_play", "MEDIA_PLAY", "", ["putar", "mainkan", "play"]),
    ("media_next", "MEDIA_NEXT", "", ["lagu berikutnya", "berikutnya",
                                      "next", "lanjut"]),
    ("media_prev", "MEDIA_PREV", "", ["lagu sebelumnya", "sebelumnya",
                                      "previous", "mundur"]),
    ("click_left", "MOUSE_CLICK", "left", ["klik kiri", "click kiri",
                                           "left click"]),
    ("click_right", "MOUSE_CLICK", "right", ["klik kanan", "click kanan",
                                             "right click"]),
    ("double_click", "MOUSE_CLICK", "double", ["klik dua kali", "klik ganda",
                                               "double click",
                                               "double klik"]),
    ("scroll_up", "SCROLL", "up", ["scroll ke atas", "gulir ke atas",
                                   "scroll up", "geser ke atas"]),
    ("scroll_down", "SCROLL", "down", ["scroll ke bawah", "gulir ke bawah",
                                       "scroll down", "geser ke bawah"]),
    ("press_enter", "PRESS_KEY", "enter", ["tekan enter", "press enter",
                                           "enter"]),
    ("press_esc", "PRESS_KEY", "esc", ["tekan escape", "tekan esc", "escape",
                                       "esc"]),
    ("copy", "CLIPBOARD", "copy", ["copy", "salin", "copi"]),
    ("paste", "CLIPBOARD", "paste", ["paste", "tempel", "timpal"]),
    ("cut", "CLIPBOARD", "cut", ["cut", "potong", "gunting"]),
    ("select_all", "CLIPBOARD", "select_all", ["select all", "pilih semua",
                                               "blok semua"]),
    ("clear_clipboard", "CLIPBOARD", "clear", ["kosongkan clipboard",
                                               "clear clipboard",
                                               "hapus clipboard",
                                               "bersihkan clipboard"]),
    ("open_clipboard", "CLIPBOARD", "open", ["buka clipboard",
                                             "tampilkan clipboard",
                                             "lihat clipboard",
                                             "open clipboard"]),
    ("close_this", "CLOSE_WINDOW", "active", ["tutup jendela ini",
                                              "tutup window ini", "tutup ini",
                                              "close this"]),
    ("minimize_this", "MINIMIZE_WINDOW", "active", ["minimalkan ini",
                                                    "minimize ini",
                                                    "kecilkan ini"]),
    ("maximize_this", "MAXIMIZE_WINDOW", "active", ["maksimalkan ini",
                                                    "maximize ini",
                                                    "besarkan ini"]),
    ("restore_this", "RESTORE_WINDOW", "active", ["kembalikan ini",
                                                  "pulihkan ini",
                                                  "restore ini",
                                                  "restore window"]),
    ("tile_windows", "TILE_WINDOWS", "", ["susun window", "rapikan window",
                                          "tile windows", "atur window"]),
    ("make_folder", "MAKE_FOLDER", "", ["buat folder baru",
                                        "bikin folder baru", "buat folder",
                                        "new folder"]),
    ("find_file", "FIND_FILE", "", ["cari file", "cari berkas"]),
    ("open_file", "OPEN_FILE", "", ["bukakan file", "buka file"]),
    ("open_youtube", "OPEN_WEBSITE", "youtube", ["bukakan youtube",
                                                 "buka youtube", "buka yutub",
                                                 "bukakan yutub",
                                                 "open youtube"]),
    ("open_google", "OPEN_WEBSITE", "google", ["bukakan google", "buka google",
                                               "open google"]),
    ("open_github", "OPEN_WEBSITE", "github", ["buka github", "buka git hub",
                                               "open github"]),
    ("open_gmail", "OPEN_WEBSITE", "gmail", ["buka gmail", "buka email",
                                             "open gmail"]),
    ("open_chrome", "OPEN_APPLICATION", "chrome",
     ["buka google chrome", "tolong bukakan chrome", "tolong buka chrome",
      "saya mau membuka chrome", "saya mau buka chrome", "bukakan chrome",
      "jalankan chrome", "buka chrome", "open chrome", "launch chrome",
      "start chrome"]),
    ("open_vscode", "OPEN_APPLICATION", "vscode",
     ["buka visual studio code", "tolong buka vs code", "bukakan vs code",
      "jalankan vs code", "buka vs code", "buka vscode", "open vs code",
      "saya mau membuka vs code"]),
    ("open_whatsapp", "OPEN_APPLICATION", "whatsapp",
     ["bukakan whatsapp", "tolong buka whatsapp", "jalankan whatsapp",
      "buka whatsapp", "buka wa", "open whatsapp"]),
    ("open_powerpoint", "OPEN_APPLICATION", "powerpoint",
     ["buka powerpoint", "buka ppt", "open powerpoint"]),
    ("close_chrome", "CLOSE_APPLICATION", "chrome",
     ["tutup chrome", "tutup krom", "close chrome"]),
    ("minimize_chrome", "MINIMIZE_WINDOW", "chrome",
     ["minimize chrome", "minimalkan chrome", "kecilkan chrome"]),
    ("maximize_chrome", "MAXIMIZE_WINDOW", "chrome",
     ["maximize chrome", "maksimalkan chrome", "besarkan chrome"]),
    ("focus_chrome", "FOCUS_APPLICATION", "chrome",
     ["pindah ke chrome", "fokus ke chrome", "focus chrome", "ke chrome"]),
    ("focus_vscode", "FOCUS_APPLICATION", "vscode",
     ["pindah ke vs code", "fokus ke vs code", "ke vs code",
      "pindah ke vscode"]),
    ("focus_whatsapp", "FOCUS_APPLICATION", "whatsapp",
     ["pindah ke whatsapp", "fokus ke whatsapp", "ke whatsapp",
      "pindah ke wa"]),
    ("focus_powerpoint", "FOCUS_APPLICATION", "powerpoint",
     ["pindah ke powerpoint", "fokus ke powerpoint", "ke powerpoint"]),
    ("open_project", "OPEN_FOLDER", "project",
     ["buka folder project", "buka folder projek", "buka project"]),
    ("open_downloads", "OPEN_FOLDER", "downloads",
     ["buka folder download", "bukakan folder download", "buka download",
      "buka downloads", "buka unduhan", "open download"]),
    ("open_documents", "OPEN_FOLDER", "documents",
     ["buka documents", "buka dokumen", "buka document",
      "open documents"]),
    ("open_desktop", "OPEN_FOLDER", "desktop", ["buka desktop",
                                                "open desktop"]),
    ("workflow_coding", "WORKFLOW", "coding",
     ["saya mau coding", "mau coding", "mode coding", "workflow coding"]),
    ("workflow_presentasi", "WORKFLOW", "presentasi",
     ["saya mau presentasi", "mau presentasi", "mode presentasi siap",
      "workflow presentasi"]),
]

# Peta kunci -> (intent, target) untuk histori/GUI.
KEY_TO_INTENT: dict[str, tuple[str, str]] = {
    k: (i, t) for k, i, t, _ in _EXACT
}
KEY_TO_INTENT.update({
    "search_google": ("SEARCH_GOOGLE", ""),
    "search_youtube": ("SEARCH_YOUTUBE", ""),
    "volume_set": ("VOLUME_SET", ""),
    "presentation_fullscreen": ("PRESENTATION_FULLSCREEN", ""),
    "open_pictures": ("OPEN_FOLDER", "pictures"),
})

# Trigger exact terurut terpanjang dulu (phrase spesifik menang).
_SORTED_EXACT: list[tuple[str, str, str, str]] = sorted(
    ((k, i, t, trig) for k, i, t, trigs in _EXACT for trig in trigs),
    key=lambda r: -len(r[3]),
)


def _strip_leading(text: str, prefixes: list[str]) -> str:
    t = (text or "").strip()
    for p in sorted(prefixes, key=len, reverse=True):
        if t.startswith(p):
            return t[len(p):].strip(" ,.")
    return t


def _find_alias(norm: str, aliases: dict[str, list[str]]) -> str | None:
    for target, names in aliases.items():
        for name in sorted(names, key=len, reverse=True):
            if name and name in norm:
                return target
    return None


def _has_any(norm: str, words: tuple[str, ...]) -> str | None:
    for w in sorted(words, key=len, reverse=True):
        if w and w in norm:
            return w
    return None


_ID_WORDS = {"nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4,
             "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8,
             "sembilan": 9, "sepuluh": 10, "sebelas": 11, "seratus": 100}


def _has_number(norm: str) -> bool:
    if re.search(r"\d{1,3}", norm):
        return True
    return any(w in norm for w in list(_ID_WORDS) + ["puluh", "belas",
                                                    "persen", "%"])


def detect(text: str) -> IntentResult:
    """Deteksi intent + kunci whitelist dari teks STT."""
    norm = _norm(text)
    if not norm:
        return IntentResult(None, "UNKNOWN", "", "", 0.0, "")

    # 1. Frasa exact (spesifik menang).
    for key, intent, target, trig in _SORTED_EXACT:
        if trig and trig in norm:
            return IntentResult(key, intent, target, "", 1.0, trig)

    # 2. File ber-query (sebelum 'cari' generik).
    if norm.startswith(("cari file", "cari berkas")):
        q = _strip_leading(norm, ["cari file", "cari berkas", "cari"])
        return IntentResult("find_file", "FIND_FILE", "", q, 0.95,
                            "cari file")
    if norm.startswith(("bukakan file", "buka file")):
        q = _strip_leading(norm, ["bukakan file", "buka file", "buka"])
        return IntentResult("open_file", "OPEN_FILE", "", q, 0.95,
                            "buka file")

    # 3. YouTube ber-query.
    if ("youtube" in norm or "yutub" in norm) and ("cari" in norm
                                                  or "search" in norm):
        q = _strip_leading(norm, ["buka youtube dan cari",
                                  "buka yutub dan cari", "cari di youtube",
                                  "cari"])
        return IntentResult("open_youtube", "SEARCH_YOUTUBE", "youtube", q,
                            0.9, "youtube+cari")

    # 4. Volume ber-angka.
    if "volume" in norm and _has_number(norm):
        return IntentResult("volume_set", "VOLUME_SET", "", norm, 0.95,
                            "volume+angka")

    # 5. Cari generik -> Google.
    for trig in ("cari di google", "cari di gugel", "carikan", "cari",
                 "search"):
        if norm.startswith(trig) or f" {trig} " in f" {norm} ":
            q = _strip_leading(norm, ["cari di google", "cari di gugel",
                                      "carikan", "cari", "search"])
            return IntentResult("search_google", "SEARCH_GOOGLE", "", q,
                                0.85, trig)

    # 6. Aksi aplikasi generik: VERB + TARGET.
    app = _find_alias(norm, _APP_ALIASES)
    if app:
        if _has_any(norm, _CLOSE_VERBS):
            key = f"close_{app}"
            if (key, "x", "x", ["x"]) and key in KEY_TO_INTENT:
                return IntentResult(key, "CLOSE_APPLICATION", app, "", 0.9,
                                    "tutup+" + app)
        if _has_any(norm, _MINI_WORDS):
            key = f"minimize_{app}"
            if key in KEY_TO_INTENT:
                return IntentResult(key, "MINIMIZE_WINDOW", app, "", 0.9,
                                    "minimize+" + app)
        if _has_any(norm, _MAXI_WORDS):
            key = f"maximize_{app}"
            if key in KEY_TO_INTENT:
                return IntentResult(key, "MAXIMIZE_WINDOW", app, "", 0.9,
                                    "maximize+" + app)
        if _has_any(norm, _FOCUS_VERBS) or re.search(r"\bke\s+" + app + r"\b",
                                                     norm):
            key = f"focus_{app}"
            if key in KEY_TO_INTENT:
                return IntentResult(key, "FOCUS_APPLICATION", app, "", 0.9,
                                    "fokus+" + app)
        if _has_any(norm, _OPEN_VERBS):
            key = f"open_{app}"
            if key in KEY_TO_INTENT:
                return IntentResult(key, "OPEN_APPLICATION", app, "", 0.9,
                                    "buka+" + app)

    # 7. Website generik: VERB + SITE.
    site = _find_alias(norm, _SITE_ALIASES)
    if site and _has_any(norm, _OPEN_VERBS):
        key = f"open_{site}"
        if key in KEY_TO_INTENT:
            return IntentResult(key, "OPEN_WEBSITE", site, "", 0.9,
                                "buka+" + site)

    # 8. Folder generik: VERB + FOLDER.
    folder = _find_alias(norm, _FOLDER_ALIASES)
    if folder and _has_any(norm, _OPEN_VERBS):
        key = f"open_{folder}"
        if key in KEY_TO_INTENT:
            return IntentResult(key, "OPEN_FOLDER", folder, "", 0.9,
                                "buka+" + folder)

    return IntentResult(None, "UNKNOWN", "", "", 0.0, "")


def intent_of_key(key: str | None) -> tuple[str, str]:
    """Kembalikan (intent, target) untuk kunci registry apa pun."""
    if not key:
        return "UNKNOWN", ""
    if key in KEY_TO_INTENT:
        return KEY_TO_INTENT[key]
    head, _, tail = key.partition("_")
    guess = {"open": "OPEN", "close": "CLOSE"}.get(head, head.upper())
    return guess, tail
