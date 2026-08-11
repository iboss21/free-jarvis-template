"""Push-to-talk.

Wired but requires binaries the wizard can fetch. Deliberately fails loud and
early rather than silently doing nothing -- a voice agent that appears to be
listening and is not is worse than one that says it cannot hear you.

Chain: hotkey held -> capture mic -> whisper.cpp -> intent -> Piper -> speakers.
Mic RMS is pushed to the state bus every frame so the orb pulses to your voice.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable

from ..config import RegesConfig
from ..state import BUS, State

SAMPLE_RATE = 16000   # whisper.cpp expects 16k mono
CHANNELS = 1


class VoiceUnavailable(RuntimeError):
    pass


def _require(binary: str, hint: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise VoiceUnavailable(f"{binary} not on PATH -- {hint}")
    return found


def transcribe(wav_path: Path, cfg: RegesConfig) -> str:
    exe = cfg.voice.stt_binary or _require(
        "whisper-cli", "install whisper.cpp or set voice.stt_binary")
    model = Path(cfg.paths.models_dir) / f"ggml-{cfg.voice.stt_model}.bin"
    if not model.exists():
        raise VoiceUnavailable(f"whisper model missing: {model}")

    with BUS.during(State.THINKING, "transcribing"):
        r = subprocess.run(
            [exe, "-m", str(model), "-f", str(wav_path), "-nt", "-np", "--output-txt"],
            capture_output=True, text=True, timeout=120,
        )
    if r.returncode != 0:
        raise VoiceUnavailable(f"whisper failed: {r.stderr[:200]}")
    return r.stdout.strip()


def speak(text: str, cfg: RegesConfig) -> None:
    if cfg.voice.tts_voice == "none" or not text.strip():
        return
    exe = cfg.voice.tts_binary or _require("piper", "install Piper or set voice.tts_binary")
    model = Path(cfg.paths.models_dir) / f"{cfg.voice.tts_voice}.onnx"
    if not model.exists():
        BUS.log("warn", f"piper voice missing: {model.name}")
        return

    out = Path(tempfile.gettempdir()) / "reges-tts.wav"
    with BUS.during(State.SPEAKING, text[:48]):
        subprocess.run([exe, "-m", str(model), "-f", str(out)],
                       input=text.encode("utf-8"), capture_output=True, timeout=120)
        _play(out)


def _play(wav: Path) -> None:
    """Playback + level metering so the orb radius tracks the actual output."""
    import sys
    if sys.platform == "win32":
        try:
            import winsound
            # Level metering during winsound playback needs a second thread reading
            # the file; approximate from waveform peaks instead of guessing.
            threading.Thread(target=_meter_wav, args=(wav,), daemon=True).start()
            winsound.PlaySound(str(wav), winsound.SND_FILENAME)
            return
        except Exception:
            pass
    for player in ("aplay", "afplay", "ffplay"):
        exe = shutil.which(player)
        if exe:
            args = [exe, str(wav)] + (["-nodisp", "-autoexit"] if player == "ffplay" else [])
            subprocess.run(args, capture_output=True)
            return
    BUS.log("warn", "no audio player found -- TTS produced a file but could not play it")


def _meter_wav(wav: Path) -> None:
    """Feed the orb from the actual waveform rather than faking a pulse."""
    try:
        import audioop            # removed from the stdlib in Python 3.13
    except ImportError:
        audioop = None
    import time
    try:
        with wave.open(str(wav), "rb") as w:
            width, rate = w.getsampwidth(), w.getframerate()
            chunk = max(1, rate // 30)
            while True:
                frames = w.readframes(chunk)
                if not frames:
                    break
                BUS.set_level(min(1.0, audioop.rms(frames, width) / 12000)) if audioop else None
                time.sleep(chunk / rate)
    except Exception:
        pass
    finally:
        BUS.set_level(0.0)


def record_until_release(is_held: Callable[[], bool], cfg: RegesConfig) -> Path:
    try:
        import sounddevice as sd  # optional dep; installed by the wizard on request
    except ImportError:
        raise VoiceUnavailable("sounddevice not installed -- pip install sounddevice")

    try:
        import audioop            # removed from the stdlib in Python 3.13
    except ImportError:
        audioop = None
    frames: list[bytes] = []
    BUS.push(State.LISTENING, "listening")
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                               dtype="int16", blocksize=512) as stream:
            while is_held():
                block, _ = stream.read(512)
                frames.append(bytes(block))
                BUS.set_level(min(1.0, audioop.rms(bytes(block), 2) / 8000)) if audioop else None
    finally:
        BUS.set_level(0.0)
        BUS.pop()

    out = Path(tempfile.gettempdir()) / "reges-ptt.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(frames))
    return out


def start_ptt(cfg: RegesConfig, on_intent: Callable[[str], str]) -> None:
    """Register the global hotkey. Raises if unavailable -- the caller logs it
    rather than leaving the user to wonder why nothing happens."""
    try:
        import keyboard  # optional dep
    except ImportError:
        raise VoiceUnavailable("keyboard not installed -- pip install keyboard")

    combo = f"{cfg.voice.ptt_modifier}+{cfg.voice.ptt_hotkey}"
    busy = threading.Lock()

    def cycle() -> None:
        if not busy.acquire(blocking=False):
            return
        try:
            wav = record_until_release(lambda: keyboard.is_pressed(combo), cfg)
            text = transcribe(wav, cfg)
            if not text:
                BUS.log("warn", "heard nothing")
                return
            BUS.log("router", f'heard: "{text[:80]}"')
            speak(on_intent(text), cfg)
        except VoiceUnavailable as e:
            BUS.error(str(e))
        finally:
            busy.release()

    keyboard.add_hotkey(combo, lambda: threading.Thread(target=cycle, daemon=True).start())
    BUS.log("skill", f"push-to-talk armed on {combo}")
