"""Voice engines.

The old ptt.py needed whisper.cpp, piper, sounddevice and keyboard all
installed before anything worked at all. That is why voice was off.

This replaces the requirement, not the ambition:

  EARS   the mic is in the browser you already have open. Hold space in the
         HUD, MediaRecorder captures, the audio POSTs to 127.0.0.1 and is
         transcribed locally. It never leaves the machine.

         faster-whisper  (pip install faster-whisper)   best, no binary
         whisper.cpp     (binary on PATH)               if you already have it
         none            type instead, and the HUD says exactly what to install

  MOUTH  Windows SAPI is already on your machine. Zero install, works today.

         piper       (binary + .onnx voice)  best quality
         sapi        Windows, built in       DEFAULT — nothing to install
         say/espeak  mac/linux               built in
         browser     speechSynthesis         final fallback, still local

Every tier degrades to the next and reports which one it used. Nothing here
silently pretends to listen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

IS_WIN = sys.platform == "win32"
SAMPLE_RATE = 16000

# Whisper ships English-ONLY weights for the small sizes. They are the real fix
# for "I said hello and it wrote Cyrillic": an English-only model physically
# cannot emit another language, so detection can never go wrong.
ENGLISH_ONLY = {"tiny": "tiny.en", "base": "base.en",
                "small": "small.en", "medium": "medium.en"}

LANGUAGES = [
    ("en", "English"),
    ("ka", "Georgian"),
    ("ru", "Russian"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("pl", "Polish"),
    ("nl", "Dutch"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("auto", "Auto-detect (unreliable on short clips)"),
]


# --------------------------------------------------------------------
# detection
# --------------------------------------------------------------------

def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _whisper_cpp() -> str:
    for exe in ("whisper-cli", "whisper-cpp", "main", "whisper"):
        found = shutil.which(exe)
        if found:
            return found
    return ""


def _piper() -> str:
    return shutil.which("piper") or shutil.which("piper.exe") or ""


def _piper_voice(models_dir: Path | None) -> str:
    roots = [models_dir] if models_dir else []
    roots += [Path.home() / ".local/share/piper", Path("./models")]
    for root in roots:
        if root and root.exists():
            for onnx in root.rglob("*.onnx"):
                return str(onnx)
    return ""


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


@dataclass
class Capability:
    id: str
    label: str
    available: bool
    detail: str = ""
    install: str = ""


def capabilities(models_dir: Path | None = None) -> dict:
    stt = [
        Capability("faster-whisper", "faster-whisper", _has_module("faster_whisper"),
                   "local, GPU or CPU, no binary needed",
                   "pip install faster-whisper"),
        Capability("whisper.cpp", "whisper.cpp", bool(_whisper_cpp()),
                   _whisper_cpp() or "binary not on PATH",
                   "download a build and put whisper-cli on PATH"),
    ]
    piper_bin = _piper()
    voice = _piper_voice(models_dir)
    tts = [
        Capability("piper", "Piper", bool(piper_bin and voice),
                   f"{piper_bin or 'no binary'} / {voice or 'no .onnx voice'}",
                   "download piper + a voice .onnx into your models folder"),
        Capability("sapi", "Windows built-in (SAPI)", IS_WIN,
                   "already installed on every Windows machine" if IS_WIN
                   else "Windows only", ""),
        Capability("say", "macOS say", sys.platform == "darwin", "", ""),
        Capability("espeak", "espeak-ng", bool(shutil.which("espeak-ng") or shutil.which("espeak")),
                   "", "apt install espeak-ng"),
        Capability("browser", "Browser speechSynthesis", True,
                   "runs in the HUD tab, still local", ""),
    ]
    gpu_seen = False
    try:
        _add_cuda_dll_dirs()
        import ctranslate2  # type: ignore
        gpu_seen = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass

    return {
        "languages": [{"code": c, "label": l} for c, l in LANGUAGES],
        "gpu_detected": gpu_seen,
        "device": _WHISPER.get("device") or ("cuda" if gpu_seen and not _CUDA_BANNED["why"] else "cpu"),
        "cuda_note": cuda_note(),
        "stt": [c.__dict__ for c in stt],
        "tts": [c.__dict__ for c in tts],
        "stt_active": next((c.id for c in stt if c.available), ""),
        "tts_active": next((c.id for c in tts if c.available), "browser"),
        "ffmpeg": bool(_ffmpeg()),
        "can_listen": any(c.available for c in stt),
        "can_speak": True,  # browser fallback always exists
    }


# --------------------------------------------------------------------
# STT
# --------------------------------------------------------------------

class VoiceError(RuntimeError):
    pass


_WHISPER = {"model": None, "size": None, "device": "", "compute": ""}
_CUDA_BANNED = {"why": ""}   # once CUDA proves broken, stop retrying it


def _add_cuda_dll_dirs() -> list[str]:
    """Windows: CTranslate2 needs cuBLAS 12 and cuDNN DLLs on the DLL search
    path. Detecting a GPU is NOT the same as being able to use it — the
    classic symptom is `Library cublas64_12.dll is not found or cannot be
    loaded` on a machine with a perfectly good card.

    pip's nvidia-* wheels ship those DLLs inside site-packages but do not put
    them on the search path. If they are there, add them. Also honour a real
    CUDA toolkit install via CUDA_PATH.
    """
    if not IS_WIN:
        return []
    added = []
    try:
        import site
        roots = list(site.getsitepackages())
        try:
            roots.append(site.getusersitepackages())
        except Exception:
            pass
    except Exception:
        roots = []

    for root in roots:
        nv = Path(root) / "nvidia"
        if not nv.is_dir():
            continue
        for sub in nv.iterdir():
            binp = sub / "bin"
            if binp.is_dir():
                try:
                    os.add_dll_directory(str(binp))  # type: ignore[attr-defined]
                    added.append(str(binp))
                except Exception:
                    pass

    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        binp = Path(cuda_path) / "bin"
        if binp.is_dir():
            try:
                os.add_dll_directory(str(binp))  # type: ignore[attr-defined]
                added.append(str(binp))
            except Exception:
                pass
    return added


def _cuda_available() -> bool:
    if _CUDA_BANNED["why"]:
        return False
    try:
        _add_cuda_dll_dirs()
        import ctranslate2  # type: ignore
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _build(size: str, device: str, compute: str):
    from faster_whisper import WhisperModel  # type: ignore
    model = WhisperModel(size, device=device, compute_type=compute)
    _WHISPER.update(model=model, size=size, device=device, compute=compute)
    return model


def resolve_size(size: str, language: str) -> str:
    """English + a size with .en weights -> use the English-only build."""
    base = (size or "base").replace(".en", "")
    if (language or "").lower() == "en" and base in ENGLISH_ONLY:
        return ENGLISH_ONLY[base]
    return base


def _load_faster_whisper(size: str = "base", prefer: str = "auto"):
    """Returns (model, device). Never raises because a GPU is half-installed."""
    if (_WHISPER["model"] is not None and _WHISPER["size"] == size
            and not (prefer == "cuda" and _WHISPER["device"] == "cpu")):
        return _WHISPER["model"], _WHISPER["device"]

    want_cuda = prefer == "cuda" or (prefer == "auto" and _cuda_available())
    if want_cuda:
        try:
            return _build(size, "cuda", "float16"), "cuda"
        except Exception as exc:
            _CUDA_BANNED["why"] = str(exc)[:300]

    return _build(size, "cpu", "int8"), "cpu"


def cuda_note() -> str:
    """Plain-language explanation when the GPU was seen but could not be used."""
    if not _CUDA_BANNED["why"]:
        return ""
    return (
        "GPU detected but unusable: " + _CUDA_BANNED["why"] +
        " — CTranslate2 needs the cuBLAS 12 and cuDNN runtime DLLs on the DLL "
        "search path. Running on CPU instead. To try GPU: "
        "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12, then restart Reges."
    )


def _to_wav(src: Path) -> Path:
    """Browser MediaRecorder gives webm/opus. Convert if ffmpeg exists."""
    if src.suffix.lower() == ".wav":
        return src
    ff = _ffmpeg()
    if not ff:
        return src  # faster-whisper decodes via PyAV, which handles webm
    dst = src.with_suffix(".wav")
    subprocess.run([ff, "-y", "-i", str(src), "-ar", str(SAMPLE_RATE),
                    "-ac", "1", "-f", "wav", str(dst)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return dst if dst.exists() else src


def transcribe(audio: bytes, mime: str = "audio/webm", *,
               model_size: str = "base", language: str | None = "en",
               device: str = "auto") -> dict:
    """Audio in, text out. Never leaves this machine."""
    if not audio:
        raise VoiceError("empty audio")

    suffix = ".wav" if "wav" in mime else (".ogg" if "ogg" in mime else ".webm")
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"clip{suffix}"
        src.write_bytes(audio)

        if _has_module("faster_whisper"):
            lang = (language or "en").lower()
            auto = lang in ("auto", "")
            size = resolve_size(model_size, "" if auto else lang)

            def _run(dev: str):
                model, used = _load_faster_whisper(size, prefer=dev)
                segments, info = model.transcribe(
                    str(src),
                    # Pinning the language is the difference between "hey Jarvis"
                    # and Cyrillic phonetics. Auto-detect on a two-second clip is
                    # a coin flip, and Whisper commits to whatever it guessed.
                    language=None if auto else lang,
                    vad_filter=True,
                    beam_size=1,
                    condition_on_previous_text=False,
                    # Whisper invents speech in silence. These make it shut up.
                    no_speech_threshold=0.6,
                    log_prob_threshold=-1.0,
                    temperature=0.0)
                # Generators are lazy — the CUDA error surfaces HERE, on encode,
                # not on load. Force the work inside the try.
                txt = " ".join(sg.text.strip() for sg in segments).strip()
                return txt, info, used

            try:
                text, info, used = _run(device)
            except Exception as exc:
                msg = str(exc)
                cuda_ish = ("cublas" in msg.lower() or "cudnn" in msg.lower()
                            or "cuda" in msg.lower() or "library" in msg.lower())
                if cuda_ish and _WHISPER.get("device") != "cpu":
                    # A half-installed CUDA runtime must never be fatal.
                    _CUDA_BANNED["why"] = msg[:300]
                    _WHISPER.update(model=None, size=None, device="", compute="")
                    try:
                        text, info, used = _run("cpu")
                    except Exception as exc2:
                        raise VoiceError(f"faster-whisper failed on CPU too: {exc2}") from exc2
                else:
                    raise VoiceError(f"faster-whisper failed: {exc}") from exc

            detected = getattr(info, "language", "") or lang
            prob = getattr(info, "language_probability", None)
            return {"text": text, "engine": "faster-whisper", "device": used,
                    "model": size,
                    "language": detected,
                    "language_forced": not auto,
                    "language_confidence": round(prob, 2) if prob else None,
                    "fallback": cuda_note(),
                    "ms": int((time.time() - t0) * 1000)}

        cli = _whisper_cpp()
        if cli:
            wav = _to_wav(src)
            out = Path(td) / "out"
            cmd = [cli, "-f", str(wav), "-otxt", "-of", str(out), "-np"]
            if language:
                cmd += ["-l", language]
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=300)
            txt = out.with_suffix(".txt")
            if txt.exists():
                return {"text": txt.read_text(encoding="utf-8").strip(),
                        "engine": "whisper.cpp", "language": language or "",
                        "ms": int((time.time() - t0) * 1000)}
            raise VoiceError("whisper.cpp produced no output")

    raise VoiceError(
        "No local speech engine installed. Run: pip install faster-whisper")


# --------------------------------------------------------------------
# TTS
# --------------------------------------------------------------------

def synthesize(text: str, *, models_dir: Path | None = None,
               voice: str = "") -> dict:
    """Text in, wav bytes out. Returns engine='browser' with no audio when the
    client should speak it itself — that is a valid, zero-install answer."""
    text = (text or "").strip()
    if not text:
        raise VoiceError("empty text")
    text = text[:4000]

    piper_bin = _piper()
    onnx = voice or _piper_voice(models_dir)
    if piper_bin and onnx:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.wav"
            try:
                subprocess.run([piper_bin, "-m", onnx, "-f", str(out)],
                               input=text.encode("utf-8"),
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=120)
                if out.exists() and out.stat().st_size > 44:
                    return {"engine": "piper", "audio": out.read_bytes(),
                            "mime": "audio/wav"}
            except Exception:
                pass

    if IS_WIN:
        # System.Speech ships with Windows. Nothing to install, ever.
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.wav"
            safe = text.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.SetOutputToWaveFile('{out}'); "
                f"$s.Speak('{safe}'); $s.Dispose()"
            )
            try:
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", ps],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=120)
                if out.exists() and out.stat().st_size > 44:
                    return {"engine": "sapi", "audio": out.read_bytes(),
                            "mime": "audio/wav"}
            except Exception:
                pass

    if sys.platform == "darwin" and shutil.which("say"):
        with tempfile.TemporaryDirectory() as td:
            aiff = Path(td) / "o.aiff"
            subprocess.run(["say", "-o", str(aiff), text], timeout=120)
            wav = _to_wav(aiff)
            if wav.exists():
                return {"engine": "say", "audio": wav.read_bytes(),
                        "mime": "audio/wav"}

    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "o.wav"
            subprocess.run([espeak, "-w", str(out), text],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=120)
            if out.exists() and out.stat().st_size > 44:
                return {"engine": "espeak", "audio": out.read_bytes(),
                        "mime": "audio/wav"}

    return {"engine": "browser", "audio": b"", "mime": "",
            "note": "no server-side voice available; the HUD will speak it"}


def wav_duration_ms(data: bytes) -> int:
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.wav"
            p.write_bytes(data)
            with wave.open(str(p), "rb") as w:
                return int(w.getnframes() / w.getframerate() * 1000)
    except Exception:
        return 0
