"""First-run setup: detection, dependency install, model download, deploy.

Everything long-running is a background job with a progress feed, because a
7 GB download behind a spinner that says nothing is how you lose a newcomer.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg_mod
from . import models_catalog as catalog


# --------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------

@dataclass
class Job:
    id: str
    kind: str
    label: str
    state: str = "running"        # running | done | failed | cancelled
    pct: float = 0.0
    detail: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    lines: list[str] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label,
            "state": self.state, "pct": round(self.pct, 1),
            "detail": self.detail, "error": self.error,
            "elapsed": round((self.finished or time.time()) - self.started, 1),
            "lines": self.lines[-40:],
        }


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _new_job(kind: str, label: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label)
    with _LOCK:
        _JOBS[job.id] = job
    return job


def job_status(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
    return job.snapshot() if job else {"error": "unknown job"}


def all_jobs() -> list[dict]:
    with _LOCK:
        return [j.snapshot() for j in _JOBS.values()]


def cancel_job(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": "unknown job"}
    job.cancel.set()
    return {"ok": True}


# --------------------------------------------------------------------
# detection
# --------------------------------------------------------------------

def _mod(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _disk(path: Path) -> dict:
    try:
        p = path
        while not p.exists() and p.parent != p:
            p = p.parent
        u = shutil.disk_usage(str(p))
        return {"free_gb": round(u.free / 1024**3, 1),
                "total_gb": round(u.total / 1024**3, 1)}
    except Exception:
        return {"free_gb": 0.0, "total_gb": 0.0}


def preflight(app_dir: str = "") -> dict:
    """Everything the wizard needs to tell the user where they stand."""
    py = sys.version_info
    gpu = catalog.detect_gpu()
    target = Path(app_dir).expanduser() if app_dir else Path.cwd()

    checks = [
        {"id": "python", "label": "Python 3.11+",
         "ok": py >= (3, 11),
         "detail": f"{py.major}.{py.minor}.{py.micro} at {sys.executable}",
         "fix": "" if py >= (3, 11) else "Install Python 3.11 or newer from python.org",
         "required": True},
        {"id": "pip", "label": "pip",
         "ok": _mod("pip"), "detail": "package installer",
         "fix": "python -m ensurepip --upgrade", "required": True},
        {"id": "disk", "label": "Disk space",
         "ok": _disk(target)["free_gb"] >= 5,
         "detail": f"{_disk(target)['free_gb']} GB free on the chosen drive",
         "fix": "Pick a drive with more room, or skip the local model",
         "required": True},
        {"id": "gpu", "label": "GPU",
         "ok": gpu["vram_gb"] > 0,
         "detail": (f"{gpu['name']} · {gpu['vram_gb']} GB" if gpu["vram_gb"]
                    else "none detected — CPU or API only"),
         "fix": "", "required": False},
        {"id": "faster_whisper", "label": "Speech recognition (faster-whisper)",
         "ok": _mod("faster_whisper"), "detail": "lets you talk to Reges",
         "fix": "pip:faster-whisper", "required": False},
        {"id": "cuda_dlls", "label": "GPU speech acceleration",
         "ok": _mod("nvidia.cublas") or bool(os.environ.get("CUDA_PATH")),
         "detail": "cuBLAS + cuDNN runtime for GPU transcription",
         "fix": "pip:nvidia-cublas-cu12 nvidia-cudnn-cu12", "required": False},
        {"id": "hf", "label": "Model downloader (huggingface_hub)",
         "ok": _mod("huggingface_hub"),
         "detail": "resumable downloads for large model files",
         "fix": "pip:huggingface_hub", "required": False},
    ]

    return {
        "platform": f"{platform.system()} {platform.release()}",
        "python": f"{py.major}.{py.minor}.{py.micro}",
        "executable": sys.executable,
        "gpu": gpu,
        "disk": _disk(target),
        "checks": checks,
        "ready": all(c["ok"] for c in checks if c["required"]),
    }


# --------------------------------------------------------------------
# pip
# --------------------------------------------------------------------

SAFE_PACKAGES = {
    "faster-whisper", "huggingface_hub", "hf_transfer",
    "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "piper-tts", "sounddevice",
}


def install_packages(names: list[str]) -> dict:
    """pip install, streamed. Only from a fixed allowlist — a setup wizard is
    not a place to let arbitrary package names through."""
    bad = [n for n in names if n not in SAFE_PACKAGES]
    if bad:
        return {"ok": False, "error": f"not in the allowlist: {', '.join(bad)}"}
    if not names:
        return {"ok": False, "error": "nothing to install"}

    job = _new_job("pip", "Installing " + ", ".join(names))

    def run() -> None:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *names]
        job.detail = " ".join(cmd)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1)
            seen = 0
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                job.lines.append(line)
                seen += 1
                # pip gives no total, so this is honest motion, not a fake ETA
                job.pct = min(95.0, 5 + seen * 1.6)
                low = line.lower()
                if low.startswith("collecting") or low.startswith("downloading"):
                    job.detail = line[:120]
                if job.cancel.is_set():
                    proc.terminate()
                    job.state = "cancelled"
                    return
            code = proc.wait()
            job.pct = 100.0
            job.state = "done" if code == 0 else "failed"
            if code != 0:
                job.error = "\n".join(job.lines[-6:])[:600] or f"pip exited {code}"
            else:
                job.detail = "installed"
        except Exception as exc:
            job.state, job.error = "failed", str(exc)[:400]
        finally:
            job.finished = time.time()

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "job": job.id}


# --------------------------------------------------------------------
# model download
# --------------------------------------------------------------------

def download_model(file: str, dest_dir: str) -> dict:
    model, quant = catalog.find_quant(file)
    if not model or not quant:
        return {"ok": False, "error": f"unknown model file: {file}"}

    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / quant.file

    if target.exists() and target.stat().st_size > 1024:
        return {"ok": True, "already": True, "path": str(target),
                "gb": round(target.stat().st_size / 1024**3, 2)}

    free = _disk(dest)["free_gb"]
    if free < quant.gb + 2:
        return {"ok": False,
                "error": f"{quant.gb} GB needed, {free} GB free on that drive"}

    job = _new_job("download", f"{model.name} · {quant.label}")
    job.detail = f"{quant.gb} GB → {dest}"
    url = quant.url(model.repo)
    part = target.with_suffix(target.suffix + ".part")

    def run() -> None:
        try:
            done = part.stat().st_size if part.exists() else 0
            req = urllib.request.Request(url, headers={"User-Agent": "Reges/1.0"})
            if done:
                req.add_header("Range", f"bytes={done}-")   # resume
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0) + done
                mode = "ab" if done else "wb"
                t0, last = time.time(), done
                with part.open(mode) as fh:
                    while True:
                        if job.cancel.is_set():
                            job.state = "cancelled"
                            job.detail = "stopped — resumes where it left off"
                            return
                        chunk = resp.read(1024 * 512)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        if total:
                            job.pct = done / total * 100
                        el = time.time() - t0
                        if el > 0.7:
                            mbps = (done - last) / el / 1024**2
                            eta = ((total - done) / max(1, (done - last) / el)) if total else 0
                            job.detail = (f"{done/1024**3:.2f} / {total/1024**3:.2f} GB"
                                          f"  ·  {mbps:.1f} MB/s"
                                          + (f"  ·  {int(eta//60)}m {int(eta%60)}s left" if eta else ""))
                            t0, last = time.time(), done
            part.replace(target)
            job.pct, job.state = 100.0, "done"
            job.detail = f"saved to {target.name}"
        except Exception as exc:
            job.state, job.error = "failed", str(exc)[:400]
        finally:
            job.finished = time.time()

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "job": job.id, "path": str(target),
            "gb": quant.gb, "url": url}


def local_models(dest_dir: str) -> list[dict]:
    d = Path(dest_dir).expanduser()
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.gguf")):
        out.append({"file": f.name, "gb": round(f.stat().st_size / 1024**3, 2),
                    "path": str(f)})
    return out


# --------------------------------------------------------------------
# folders + finish
# --------------------------------------------------------------------

VAULT_DIRS = ["00-inbox", "10-daily", "20-wiki", "30-projects", "40-people",
              "50-outputs", "60-money", "60-money/ventures", "70-markets", "90-system"]


def make_folders(app_dir: str, vault_dir: str = "", models_dir: str = "") -> dict:
    app = Path(app_dir).expanduser().resolve()
    vault = Path(vault_dir).expanduser() if vault_dir else app / "vault"
    models = Path(models_dir).expanduser() if models_dir else app / "models"
    made = []
    try:
        for d in (app, vault, models, app / "data", app / "logs",
                  app / "skills", app / "knowledge"):
            if not d.exists():
                made.append(str(d))
            d.mkdir(parents=True, exist_ok=True)
        for sub in VAULT_DIRS:
            (vault / sub).mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, "app": str(app), "vault": str(vault),
            "models": str(models), "created": made,
            "disk": _disk(app)}


def suggested_dirs(app_dir: str = "") -> dict:
    """Sensible defaults that do not require admin rights.

    If Reges was launched with an explicit --app-dir, that wins — the wizard
    should not quietly propose somewhere else than where the user started.
    """
    if app_dir:
        base = Path(app_dir).expanduser().resolve()
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Reges"
    else:
        base = Path.home() / ".reges"
    return {
        "app": str(base),
        "vault": str(base / "vault"),
        "models": str(base / "models"),
        "drives": _drives(),
    }


def _drives() -> list[dict]:
    out = []
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:/")
            if root.exists():
                d = _disk(root)
                out.append({"path": f"{letter}:/", **d})
    else:
        d = _disk(Path.home())
        out.append({"path": str(Path.home()), **d})
    return out
