"""
Servicio que ejecuta el scraper maestro (recetapp/scraper.py) sin modificarlo.

RecetApp compara precios de medicamentos por unidad. El scraper descarga los
catálogos de varias farmacias (VTEX + Playwright), cura los datos y genera
data/precios.csv, que luego lee la web embebida.

Aquí sólo se invoca scraper.py como subproceso (en segundo plano) y se expone:
  - precios_info(): estado del CSV generado (existe, filas, fecha).
  - start_job()/get_job(): trabajo con registro de salida en vivo.
"""
from __future__ import annotations

import csv
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

RECETAPP_DIR = Path(__file__).resolve().parent.parent / "recetapp"
SCRAPER_PY = RECETAPP_DIR / "scraper.py"
DATA_DIR = RECETAPP_DIR / "data"
PRECIOS_CSV = DATA_DIR / "precios.csv"

# Farmacias que soporta scraper.py (claves del argumento --farmacias).
FARMACIAS: list[dict] = [
    {"key": "larebaja", "nombre": "La Rebaja"},
    {"key": "habib", "nombre": "Habib Droguerías"},
    {"key": "laeconomia", "nombre": "La Economía"},
    {"key": "farmatodo", "nombre": "Farmatodo"},
    {"key": "cruzverde", "nombre": "Cruz Verde"},
]

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_LOG_LINEAS = 400


def precios_info() -> dict:
    """Estado del archivo data/precios.csv que lee la web."""
    if not PRECIOS_CSV.exists():
        return {"exists": False, "rows": 0, "modified": None, "size": 0}
    rows = 0
    try:
        with PRECIOS_CSV.open("r", encoding="utf-8", errors="replace") as f:
            rows = max(0, sum(1 for _ in f) - 1)  # resta la cabecera
    except OSError:
        pass
    stat = PRECIOS_CSV.stat()
    return {
        "exists": True,
        "rows": rows,
        "modified": stat.st_mtime,
        "size": stat.st_size,
    }


def start_job(farmacias: Optional[list[str]] = None, max_paginas: Optional[int] = None) -> str:
    """Lanza scraper.py en segundo plano y devuelve el id del trabajo."""
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "log": [],
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    threading.Thread(target=_run, args=(job_id, farmacias, max_paginas), daemon=True).start()
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _JOBS.get(job_id)


def _append_log(job: dict, line: str) -> None:
    job["log"].append(line)
    if len(job["log"]) > _MAX_LOG_LINEAS:
        job["log"] = job["log"][-_MAX_LOG_LINEAS:]


def _run(job_id: str, farmacias: Optional[list[str]], max_paginas: Optional[int]) -> None:
    job = _JOBS[job_id]
    cmd = [sys.executable, str(SCRAPER_PY)]
    if farmacias:
        cmd += ["--farmacias"] + [str(f) for f in farmacias]
    if max_paginas:
        cmd += ["--max-paginas", str(int(max_paginas))]
    _append_log(job, "$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(RECETAPP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                _append_log(job, line)
        proc.wait()
        if proc.returncode != 0:
            job["error"] = f"El scraper terminó con código {proc.returncode}."
    except Exception as exc:  # noqa: BLE001
        job["error"] = str(exc)
    job["finished_at"] = time.time()
    job["status"] = "done"
