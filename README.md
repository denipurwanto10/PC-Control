# Multimodal Desktop Controller — Tangan + Suara + Keyboard + Automation

Aplikasi desktop Python (Windows) untuk mengendalikan komputer memakai
**gerakan tangan** (webcam), **perintah suara** (microphone), **keyboard**,
dan **workflow automation** — terintegrasi dalam satu aplikasi ringan.
 
> ✅ **Status lingkungan ini: TERINSTAL & SIAP JALAN.**
> Virtualenv `.venv` (Python 3.13) berisi `numpy`, `opencv-python`,
> `mediapipe 1.x`, `pyautogui`, `SpeechRecognition`, `sounddevice`,
> `soundfile`, `Pillow`, `pygetwindow`, `pyperclip`.
> Model `assets/hand_landmarker.task` sudah terunduh.
> Jalankan: klik 2x **`run.bat`**.

## Alur sistem

```text
             🎤 VOICE
                ↓
         Speech Recognition
                ↓
          Intent Detection          🖐️ HAND
                ↓                      ↓
         Command Processor          MediaPipe
                ↓                      ↓
        Windows Controller      Gesture Detection
                ↓                      ↓
              💻                   Mouse Controller
                                        ↓
                                      🖱️
```

Keduanya dapat digunakan **bersamaan**. Speech → STT → Intent Detection
(`src/intent_detector.py`, rule-based ringan, tanpa AI berbayar) →
Command Processor → Action whitelist.

Sejak update Telegram, arsitektur menjadi 3 metode kontrol:

```text
                  LAPTOP
                     |
        +------------+------------+
        |            |            |
     Gesture       Voice       Telegram
        |            |            |
        +------------+------------+
                     v
             Command Processor
                     |
                     v
            Windows Controller
                     |
                     v
                  Windows
```

Voice ("buka chrome"), Telegram ("/buka_chrome"), dan tombol GUI
semuanya melewati **Command Processor yang sama** sehingga hasilnya identik.

## 1. Fitur gesture (§5)

| Gesture | Aksi |
|---|---|
| ☝️ Telunjuk bergerak | Gerakkan kursor (smoothing + sensitivitas + ROI kalibrasi) |
| 👌 Jempol + telunjuk cubit cepat + lepas | Klik kiri (cooldown, anti klik-berulang) |
| Cubit + tahan + gerak | Drag & drop |
| Jempol + jari tengah (tengah ditekuk) | Klik kanan |
| Jempol + telunjuk + tengah menyatu | Double click |
| ✌️ Telunjuk + tengah naik/turun | Scroll |
| Jempol + kelingking, gerak vertikal | Zoom in/out (Ctrl +/−) |
| ✋ Telapak terbuka | Pause |
| Tangan hilang | Kursor diam, aplikasi tetap jalan |

Mapping mudah dikonfigurasi: `click_threshold_px` (jarak pinch),
`gesture_cooldown_sec` (debounce klik), `smoothing`, `sensitivity` —
via dialog Settings atau `config/settings.json`.
Gesture sekali-tembak memakai edge-trigger + cooldown sehingga tangan
diam tidak memicu klik berulang.

## 2. Voice command (§16 — Indonesia + Inggris)

Perintah dipahami lewat **intent detection**, bukan string persis:

```text
buka chrome / jalankan chrome / tolong buka google chrome /
saya mau membuka chrome   →   INTENT = OPEN_APPLICATION, TARGET = CHROME
```

Normalisasi (lowercase, tanpa diakritik/tanda baca) membuat kapitalisasi
dan tanda baca tidak menggagalkan command.

**Aplikasi:** buka/tutup chrome, buka vs code/whatsapp/powerpoint,
minimize/maximize chrome, pindah/fokus ke chrome/vscode/whatsapp/
powerpoint, tutup/minimize/maximize/kembalikan ini (window aktif),
susun window.

**Website:** buka youtube/google/github/gmail, cari di google ...,
buka youtube dan cari ...

**File & folder:** buka downloads/documents/desktop/pictures/
folder project, cari file ..., buka file ..., buat folder baru.

**Sistem:** volume naik/turun, volume N persen ("lima puluh" didukung),
mute, brightness naik/turun.

**Media (§6):** play, pause, next, previous.

**Mouse:** klik kiri/kanan, double click, scroll ke atas/bawah.

**Keyboard:** tekan enter/escape, copy, paste, cut, select all,
clear/buka clipboard.

**Screenshot (§7):** screenshot (full), screenshot window aktif,
screenshot area (pilih area dengan mouse, ESC batal).
Format nama: `Screenshot_YYYY-MM-DD_HH-MM-SS.png` di
`Pictures/Screenshots`.

**Recording (§8):** mulai/berhenti recording (butuh `mss`, opsional —
modul terpisah `screenshot_tools.py`, hasil ke folder `Videos`).

**Mode:** aktifkan/matikan mouse, mulai/berhenti mengetik (voice typing),
aktifkan/matikan mode presentasi, mulai presentasi (F5),
slide berikut/sebelumnya, berhenti/mulai mendengarkan.

**Workflow:** "saya mau coding", "mode coding", "mode kerja".

Perintah di luar daftar **diabaikan dengan aman** (whitelist intent/
action — tanpa `os.system`, tanpa `shell=True`, tanpa eksekusi CMD/
PowerShell arbitrer, tanpa shutdown/restart/hapus file).

## 3. Voice typing (§1)

Ucapkan "mulai mengetik" → semua ucapan diketik ke window aktif
(mis. Notepad/Word). "berhenti mengetik" untuk keluar. Kalimat biasa
tidak pernah dianggap command selama typing (hanya escape + kontrol
mouse/voice yang lolos).

## 4. Context awareness (§2)

`src/window_manager.py`: active window title, nama aplikasi aktif
(tebakan ramah dari judul), focus/minimize/maximize/restore/close
window, daftar window. GUI menampilkan Active Window setiap frame.
Contoh: "tutup ini", "minimize ini", "maximize ini",
"kembalikan ini", "pindah ke Chrome".

## 5. Multi-command (§3)

Kalimat majemuk dipecah otomatis:
"Buka Chrome lalu buka YouTube dan cari musik lo-fi" → 3 aksi berurutan.
"Buka VS Code dan buka folder project" → 2 aksi. Pemisah: lalu,
kemudian, koma, dan, terus, habis itu, setelah itu (maks 5 aksi).

## 6. Custom workflow (§10) — `config/commands.json`

```json
{
  "mode coding": ["open:vs_code", "open:chrome", "open:project_folder"],
  "mode kerja": ["open:chrome", "open:email", "open:vs_code"]
}
```

Frasa → daftar langkah; langkah boleh **kunci whitelist**
(`open_vscode`) atau **aksi `open:...`** (`open:vs_code`,
`open:project_folder`, `open:email`, ...). Kunci asing diabaikan
dengan pesan — voice tidak pernah bisa menambah perintah arbitrer.
Workflow tidak di-hardcode di `main.py` (modul `src/workflows.py` /
`src/workflow.py`).

## 7. Custom application (§11) — `config/apps.json`

```json
{
  "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "vscode": "",
  "whatsapp": "",
  "powerpoint": ""
}
```

Kosong (`""`) = deteksi otomatis (lokasi umum Windows → PATH).
Bila path diisi tapi tidak ditemukan → error jelas, aplikasi tetap jalan.
Hanya 4 kunci di atas yang dibaca; voice tidak bisa menambah path.

## 8. Command history (§12)

Tab 📜 Riwayat + file `data/command_history.json`:

```text
VOICE HISTORY

22:01  Buka Chrome              ✓
22:02  Buka YouTube             ✓
22:04  Screenshot               ✓
22:05  Volume 50 persen         ✓
```

Tersimpan: timestamp, voice input, intent, action, status, error.

## 9. Presentation mode (§13)

"aktifkan mode presentasi" → gesture mouse normal **dinonaktifkan**
agar tidak mengganggu slide; yang aktif: NEXT (3 jari) = slide
berikutnya, PREV (kepalan) = sebelumnya, POINTER (bentuk L) = pointer,
PINCH = klik. Voice: "slide berikutnya/sebelumnya",
"matikan mode presentasi".

## 10. GUI (§14)

```text
MULTIMODAL DESKTOP CONTROLLER

Camera             ● ON
Hand Tracking      ● ON
Mouse Control      ● ON
Voice Control      ● ON
Voice Typing       ○ OFF

Active Window:
Google Chrome

Gesture:
Point

Last Voice:
"Buka YouTube"

Intent:
OPEN_WEBSITE

Last Action:
YouTube opened successfully

FPS:
30
```

Tombol: Camera ON/OFF, Hand Gesture ON/OFF, Mouse ON/OFF, Voice ON/OFF,
Voice Typing, Presentation Mode, Settings, Exit. Ringan & responsif
(update hanya saat nilai berubah, tanpa animasi berat).

## 11. Settings (§15) — `config/settings.json`

Dialog ⚙ Settings: sensitivity cursor, smoothing, click threshold,
gesture cooldown, microphone (+ device list), camera selection,
voice language (id-ID/en-US), mouse/hand/voice enable-disable.
Tersimpan lokal; mouse/hand/voice + smoothing/sensitivitas/threshold/
cooldown berlaku langsung, kamera/mic/bahasa berlaku setelah restart.

## 12. Menjalankan

**Klik 2x `run.bat`**, atau:

```powershell
.\.venv\Scripts\python.exe main.py
```

Keyboard: `M` mouse, `V` voice, `C` kalibrasi kamera, `K` kamera,
`G` hand tracking, `P` presentasi, `T` typing, `H` bantuan,
`Q`/`ESC` keluar.

## 13. Instalasi dari nol (PC lain / Windows)

1. Python **3.13 64-bit** (centang Add python.exe to PATH).
2. `python -m venv .venv` → aktivasi →
   `pip install -r requirements.txt` (sounddevice dipertahankan sebagai
   fallback mic — JANGAN hapus; PyAudio TIDAK wajib di 3.13).
3. Unduh model ke `assets/hand_landmarker.task`:
   `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task`
4. `python main.py` (atau `run.bat`).

## 14. Setup webcam & microphone

**Webcam:** tutup Zoom/Teams bila bentrok; izin Settings → Privacy →
Camera; ubah `camera_index` di Settings (0/1/2); tekan `C` untuk
kalibrasi area kamera.

**Microphone:** backend otomatis (PyAudio bila ada, else
sounddevice+soundfile — tanpa perlu PyAudio di 3.13). Izin Settings →
Privacy → Microphone. Pilih device di Settings bila mic salah.
Google Speech Recognition butuh **internet** (id-ID → fallback en-US);
tanpa internet voice ERROR tetapi gesture tetap jalan. Mic sibuk/tak
ada → mode hand-only (tidak crash).

**PyAudio (opsional):** tidak wajib. Bila ingin, `pip install pipwin`
→ `pipwin install pyaudio`; aplikasi otomatis memakainya.

**Screen recording (opsional):** `pip install mss`; tanpa ini perintah
"mulai recording" menolak dengan pesan ramah.

## 15. Struktur project (§20)

```text
cursor-control/
│
├── main.py
├── requirements.txt
├── README.md
├── run.bat
│
├── config/
│   ├── apps.json        # custom path aplikasi (§11)
│   ├── commands.json    # custom workflow (§10)
│   ├── telegram_commands.json  # /nama -> frasa voice (Telegram)
│   └── settings.json    # dibuat otomatis dari dialog Settings (§15)
│
├── data/
│   └── command_history.json   # riwayat (§12, otomatis)
│
├── src/
│   ├── hand_tracker.py
│   ├── gesture.py
│   ├── mouse_controller.py
│   ├── voice_controller.py
│   ├── mic_input.py
│   ├── intent_detector.py     # intent detection (§4, BARU)
│   ├── command_processor.py
│   ├── windows_controller.py
│   ├── window_manager.py      # context awareness (§2, BARU)
│   ├── screenshot.py          # screenshot kanonis (§7, BARU)
│   ├── screenshot_tools.py    # recording + kompat lama (§8)
│   ├── clipboard.py
│   ├── workflows.py
│   ├── workflow.py            # alias nama-kanonis (§20, BARU)
│   ├── command_history.py
│   ├── settings.py            # settings persisten (§15, BARU)
│   ├── app_state.py
│   ├── actions.py             # lama (kompat, tidak wajib)
│   ├── gui.py
│   ├── telegram_controller.py  # remote Telegram (BARU)
│   └── config.py
│
└── assets/
    └── hand_landmarker.task
```

Tidak ada modul duplikat: `window_manager` kanonis (windows_controller
delegasi), `screenshot` kanonis (screenshot_tools delegasi),
`workflow` alias dari `workflows`.

## 17. Telegram Remote Controller

Kendalikan laptop dari HP via bot Telegram. Telegram adalah **metode
ketiga** — hand gesture dan voice tetap berjalan seperti biasa.
Semua perintah Telegram melewati **Command Processor yang sama**
dengan voice, sehingga `/buka_chrome` hasilnya identik dengan
ucapan "buka chrome".

### 17.1 Membuat bot via BotFather

1. Buka Telegram, cari **@BotFather** (akun resmi, centang biru).
2. Kirim `/newbot`, lalu ikuti panduannya:
   - *nama tampilan* bebas, mis. `Laptop Controller Saya`.
   - *username* wajib berakhiran `bot`, mis. `laptopku_controller_bot`.
3. BotFather membalas **token** seperti:
   `1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
   Salin token ini — perlakukan seperti password, jangan dibagikan.

### 17.2 Mendapatkan bot token

Token hanya berasal dari BotFather (langkah 17.1). Tidak ada cara
lain yang resmi. Bila token bocor, kirim `/revoke` ke @BotFather
untuk membuat token baru.

### 17.3 Mendapatkan Telegram user ID

1. Cari **@userinfobot** di Telegram, kirim `/start`.
2. Ia membalas `Id: 123456789` — angka itulah user ID kamu.
3. Bila beberapa orang boleh mengendalikan, kumpulkan semua ID-nya.

### 17.4 Konfigurasi (.env)

Salin `.env.example` menjadi `.env`, lalu isi:

```text
TELEGRAM_BOT_TOKEN=1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_ALLOWED_USER_ID=123456789
```

Beberapa user: pisahkan koma —
`TELEGRAM_ALLOWED_USER_ID=111,222,333`.
`.env` sudah masuk `.gitignore` dan **tidak pernah** di-commit.
Tanpa token/ID yang valid, Telegram nonaktif otomatis sedangkan
hand gesture + voice tetap jalan normal.

### 17.5 Menjalankan

```powershell
.\.venv\Scripts\python.exe main.py
```

atau klik 2x `run.bat`. Tanda sukses di console:

```text
[TELEGRAM] Bot connected
[TELEGRAM] Waiting for commands...
```

GUI menampilkan `Telegram Control: ON`, status koneksi, user
terotorisasi, dan perintah terakhir, plus tombol Start/Stop Telegram
(mematikan Telegram tidak menghentikan gesture/voice).

### 17.6 Menggunakan

Kirim ke bot (atau tekan tombol inline keyboard dari `/start`):

```text
/start        panel tombol utama
/help         daftar perintah
/status       info laptop (CPU/RAM/uptime/window aktif)
/screenshot   foto layar dikirim balik ke chat
/buka_chrome  buka Chrome (sama dgn voice "buka chrome")
/buka_vscode  buka VS Code
/volume_up /volume_down /mute
/play /pause /next /previous
/downloads /desktop /documents
/minimize /maximize /window
/mouse_on /mouse_off /voice_on /voice_off
/coding       workflow coding (lihat config/telegram_commands.json)
/presentasi   workflow presentasi
```

Custom command (`/coding`, `/kerja`, ...) dipetakan di
`config/telegram_commands.json` — `/nama` diteruskan sebagai frasa
voice ke Command Processor, jadi tidak perlu ubah kode untuk
menambah workflow baru.

### 17.7 Keamanan

- Hanya user ID di whitelist yang dijawab; yang lain menerima
  `Unauthorized user` dan perintahnya diabaikan.
- Hanya command whitelist yang diteruskan ke Command Processor —
  tidak ada `os.system`/`subprocess` dari isi pesan, tidak ada
  eksekusi path arbitrer, folder hanya yang sudah ditentukan.
- Token tidak pernah muncul di log, GUI, maupun balasan chat.

## 18. Troubleshooting (lanjutan Telegram)

| Masalah | Solusi |
|---|---|
| Telegram disabled saat start | Isi `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USER_ID` di `.env`. |
| Bot tidak merespons | Cek internet laptop; pastikan user ID benar (via @userinfobot). |
| Unauthorized user | Tambahkan ID pengirim ke `TELEGRAM_ALLOWED_USER_ID`, restart app. |
| Screenshot gagal terkirim | Cek folder Pictures/Screenshots; error jelas dikirim ke chat. |
| CPU/RAM tampil n/a | `pip install psutil` (sudah di requirements). |


## 16. Troubleshooting (§18)

| Masalah | Solusi |
|---|---|
| Webcam tidak tersedia | Tutup app kamera lain, cek izin, ubah `camera_index` di Settings. |
| Voice UNAVAILABLE | Cek mic + izin mic; aplikasi jalan hand-only. |
| Mic sibuk | Tutup app yang memakai mic; pilih device lain di Settings. |
| Voice ERROR jaringan | Google SR butuh internet. |
| Perintah tak dikenal | Ucapkan frasa dari §2; cek teks terdengar + Intent di GUI. |
| Aplikasi tidak ditemukan | Isi path di `config/apps.json` atau install aplikasi. |
| Window tidak ditemukan | Buka dulu aplikasinya, lalu ulangi perintah. |
| File tidak ditemukan | File dicari di Downloads/Documents/Desktop/Pictures. |
| Klik kanan/double sulit | Sentuhkan ujung jari hingga benar-benar dekat; naikkan threshold. |
| Kursor bergetar | Naikkan smoothing; tekan `C` untuk kalibrasi. |
| Slide lompat 2x | Cooldown 1 dtk sudah bawaan; gerakkan gesture sekali saja. |
| Recording ditolak | Install `mss` (opsional). |
