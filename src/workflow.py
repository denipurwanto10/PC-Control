"""Workflow (nama kanonis sesuai struktur target).

Implementasi berada di `workflows.py`; modul ini re-ekspor agar
`from src.workflow import ...` maupun `from src.workflows import ...`
keduanya valid. Jangan duplikasi logika di sini.
"""
from __future__ import annotations

from .workflows import (  # noqa: F401
    CUSTOM_FILE,
    builtin_coding,
    builtin_presentasi,
    load_custom,
    project_dir,
)
