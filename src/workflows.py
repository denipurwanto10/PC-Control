"""Workflow & custom command: aksi berurutan dari kunci whitelist.

- WORKFLOWS bawaan: "saya mau coding", "saya mau presentasi".
- Custom: config/commands.json memetakan frasa -> daftar langkah.
  Langkah boleh berupa KUNCI aksi registry (mis. "open_vscode") atau
  aksi "open:TARGET" (mis. "open:vs_code", "open:project_folder",
  "open:chrome", "open:email") yang dipetakan ke kunci di bawah.
- Hanya kunci yang terdaftar yang dijalankan; kunci asing diabaikan
  dengan pesan (tidak ada eksekusi arbitrer).
"""
from __future__ import annotations

import json
from pathlib import Path

CUSTOM_FILE = Path("config/commands.json")

# Aksi "open:TARGET" -> kunci registry whitelist.
OPEN_ACTION_MAP: dict[str, str] = {
    "vs_code": "open_vscode",
    "vscode": "open_vscode",
    "chrome": "open_chrome",
    "whatsapp": "open_whatsapp",
    "wa": "open_whatsapp",
    "powerpoint": "open_powerpoint",
    "ppt": "open_powerpoint",
    "email": "open_gmail",
    "gmail": "open_gmail",
    "youtube": "open_youtube",
    "github": "open_github",
    "project_folder": "open_project",
    "project": "open_project",
    "downloads": "open_downloads",
    "documents": "open_documents",
    "desktop": "open_desktop",
}


def resolve_step(step: str) -> str | None:
    """Langkah config -> kunci registry; None bila tidak dikenal."""
    s = (step or "").strip().lower()
    if not s:
        return None
    if s.startswith("open:"):
        return OPEN_ACTION_MAP.get(s[5:].strip())
    return s  # diasumsikan sudah berupa kunci registry


def project_dir() -> Path | None:
    """Folder project: env PROJECT_DIR > ~/Documents/project > ~/project."""
    import os

    env = os.environ.get("PROJECT_DIR", "").strip()
    for cand in (env, str(Path.home() / "Documents" / "project"),
                 str(Path.home() / "project"), "."):
        if cand and Path(cand).exists():
            return Path(cand)
    return None


def load_custom() -> dict[str, list[str]]:
    """Baca custom commands; {} bila file hilang/rusak.

    Mendukung dua format langkah: kunci registry ("open_vscode")
    atau aksi "open:TARGET" ("open:vs_code"). Kunci asing tetap
    disimpan — penyaringan dilakukan saat eksekusi (diberi pesan,
    tidak dieksekusi).
    """
    try:
        if not CUSTOM_FILE.exists():
            return {}
        data = json.loads(CUSTOM_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, list):
                steps = [s for s in v if isinstance(s, str)]
                if steps:
                    out[k.strip().lower()] = steps
        return out
    except Exception:
        return {}


# (kunci, label, fungsi-dari-windows_controller-atau-callable)
# Di-resolve lazy di command_processor agar import tetap ringan.


def builtin_coding() -> list[str]:
    """Langkah workflow 'saya mau coding' (kunci aksi)."""
    return ["open_vscode", "open_project", "open_chrome",
            "open_github", "tile_windows"]


def builtin_presentasi() -> list[str]:
    """Langkah workflow 'saya mau presentasi' (kunci aksi)."""
    return ["open_powerpoint", "presentation_on", "presentation_fullscreen"]
