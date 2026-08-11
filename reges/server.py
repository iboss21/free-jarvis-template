"""HUD server.

Deliberately stdlib-only. Adding FastAPI + uvicorn buys nothing here and costs
two more things that can fail to install on a fresh Windows box -- and the
installer's first impression is the whole product.

Routes:
    GET  /                 HUD
    GET  /stream           SSE: full agent snapshot per frame
    GET  /api/appearance   colours, orb density, PTT hint
    GET  /api/commands     command deck buttons, built from enabled skills
    GET  /api/today        parsed system/today.md
    POST /api/intent       {"text": "..."} -> queued for the router
"""

from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .config import RegesConfig
from .state import BUS, State
from .vault import Vault

HUD_DIR = Path(__file__).resolve().parent.parent / "hud"


class RegesHandler(BaseHTTPRequestHandler):
    server_version = "Reges"
    protocol_version = "HTTP/1.1"

    cfg: RegesConfig
    vault: Vault
    on_intent: Callable[[str], None]

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:
        return  # the activity log is the log; stop spamming stdout

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode("utf-8"), "application/json")

    def _guard_origin(self) -> bool:
        """Loopback-only service: reject cross-origin POSTs so a random page in
        the user's browser cannot drive their agent."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host", "")
        return origin.endswith(host) or "127.0.0.1" in origin or "localhost" in origin

    # -- GET --------------------------------------------------------------- #
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/stream":
            return self._stream()
        if path.startswith("/api/"):
            return self._api_get(path)
        return self._static(path)

    def _static(self, path: str) -> None:
        if path in ("/", ""):
            # A first-time buyer should meet a setup screen, not a cockpit.
            done = (getattr(self.cfg, "setup_complete", False)
                    or getattr(self.cfg, "onboarded", False))
            rel = "index.html" if done else "welcome.html"
        else:
            rel = path.lstrip("/")
        target = (HUD_DIR / rel).resolve()
        try:
            target.relative_to(HUD_DIR)
        except ValueError:
            return self._send(403, b"forbidden", "text/plain")
        if not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript"   # required or the browser refuses the ES module
        self._send(200, target.read_bytes(), ctype)

    def _api_get(self, path: str) -> None:
        if path == "/api/appearance":
            a = self.cfg.appearance
            return self._json({
                "colors": a.colors,
                "orb_density": a.orb_density,
                "orb_speed": getattr(a, "orb_speed", 1.0),
                "theme": getattr(a, "theme", "obsidian"),
                "orb_variant": getattr(a, "orb_variant", "lattice"),
                "reduce_motion": a.reduce_motion,
                "ptt": f"{self.cfg.voice.ptt_modifier}+{self.cfg.voice.ptt_hotkey}",
            })
        if path == "/api/commands":
            return self._json(build_deck(self.cfg))
        if path == "/api/today":
            return self._json(parse_today(self.vault))
        if path == "/api/state":
            return self._json(BUS.snapshot())
        if path == "/api/settings":
            from .settings_api import get_settings
            return self._json(get_settings(self.cfg))
        if path == "/api/apps":
            from .settings_api import list_apps
            return self._json(list_apps())
        if path == "/api/hardware":
            from .settings_api import get_hardware
            return self._json(get_hardware())
        if path == "/api/pricing":
            from .settings_api import get_pricing
            return self._json(get_pricing(self.cfg))
        if path == "/api/setup/preflight":
            from .setup_api import preflight
            return self._json(preflight(self.cfg.paths.app_dir))
        if path == "/api/setup/dirs":
            from .setup_api import suggested_dirs
            return self._json(suggested_dirs(self.cfg.paths.app_dir))
        if path == "/api/setup/catalog":
            from .models_catalog import GPU_TIERS, detect_gpu, listing, recommend
            gpu = detect_gpu()
            return self._json({
                "models": listing(), "gpu": gpu, "tiers": [
                    {"label": l, "vram": v, "note": n} for l, v, n in GPU_TIERS],
                "recommended": recommend(gpu["vram_gb"]),
            })
        if path.startswith("/api/setup/job/"):
            from .setup_api import job_status
            return self._json(job_status(path.rsplit("/", 1)[-1]))
        if path == "/api/setup/local-models":
            from .setup_api import local_models
            return self._json({"models": local_models(self.cfg.paths.models_dir)})
        if path == "/api/voice/status":
            from .voice.engines import capabilities
            from pathlib import Path as _P
            md = _P(self.cfg.paths.models_dir) if self.cfg.paths.models_dir else None
            return self._json(capabilities(md))
        return self._json({"error": "unknown endpoint"}, 404)

    # -- SSE --------------------------------------------------------------- #
    def _stream(self) -> None:
        q = BUS.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                try:
                    snap = q.get(timeout=15)
                    payload = f"data: {json.dumps(snap)}\n\n"
                except queue.Empty:
                    payload = ": keepalive\n\n"   # keeps proxies and Windows NAT from folding the socket
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            BUS.unsubscribe(q)

    # -- setup ------------------------------------------------------------- #
    def _setup_post(self, action: str, data: dict) -> None:
        from . import setup_api as su
        try:
            if action == "install":
                return self._json(su.install_packages(data.get("packages") or []))
            if action == "download":
                return self._json(su.download_model(
                    data.get("file", ""),
                    data.get("dest") or self.cfg.paths.models_dir))
            if action == "folders":
                return self._json(su.make_folders(
                    data.get("app", ""), data.get("vault", ""), data.get("models", "")))
            if action == "recommend":
                from .models_catalog import recommend
                return self._json(recommend(float(data.get("vram_gb") or 0)))
            if action == "cancel":
                return self._json(su.cancel_job(data.get("job", "")))
            if action == "finish":
                return self._json(self._setup_finish(data))
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)[:400]}, 500)
        return self._json({"error": "unknown setup action"}, 404)

    def _setup_finish(self, data: dict) -> dict:
        """Write everything the wizard collected, then declare the box live."""
        from . import config as cfg_mod
        cfg = self.cfg
        paths = data.get("paths") or {}
        if paths.get("app"):
            cfg.paths.app_dir = paths["app"]
        if paths.get("vault"):
            cfg.paths.vault_dir = paths["vault"]
        if paths.get("models"):
            cfg.paths.models_dir = paths["models"]
            cfg.paths.logs_dir = str(Path(cfg.paths.app_dir) / "logs")

        m = data.get("model") or {}
        if m.get("local_base_url"):
            cfg.models.local_base_url = m["local_base_url"]
        if m.get("local_model"):
            cfg.models.local_model = m["local_model"]
        if "remote_enabled" in m:
            cfg.models.remote_enabled = bool(m["remote_enabled"])
        if m.get("remote_model"):
            cfg.models.remote_model = m["remote_model"]
        for f in ("router_tier", "reasoning_tier"):
            if m.get(f):
                setattr(cfg.models, f, m[f])

        key, key_for = (data.get("api_key") or "").strip(), (data.get("api_key_provider") or "").strip()
        if key and key_for:
            from .providers import get as get_provider
            from .settings_api import _secrets
            p = get_provider(key_for)
            if p and p.secret_key:
                _secrets(cfg).set(p.secret_key, key)

        ap = data.get("appearance") or {}
        for f, cast in (("orb_speed", float), ("orb_density", int)):
            if f in ap:
                try:
                    setattr(cfg.appearance, f, cast(ap[f]))
                except (TypeError, ValueError):
                    pass
        for f in ("theme", "orb_variant"):
            if ap.get(f):
                setattr(cfg.appearance, f, str(ap[f]))
        if "reduce_motion" in ap:
            cfg.appearance.reduce_motion = bool(ap["reduce_motion"])

        v = data.get("voice") or {}
        cfg.voice.enabled = bool(v.get("enabled", False))
        if v.get("stt_language"):
            cfg.voice.stt_language = str(v["stt_language"])
        cfg.setup_complete = True

        src = getattr(cfg, "_source_path", None)
        path = cfg_mod.save(cfg, Path(src)) if src else cfg_mod.save(cfg)
        BUS.log("skill", "setup complete — Reges is live")
        return {"ok": True, "saved_to": str(path), "hud": "/"}

    # -- voice ------------------------------------------------------------- #
    def _voice_stt(self) -> None:
        """Raw audio in, text out. The clip never leaves this machine."""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._json({"error": "no audio"}, 400)
        if length > 25_000_000:
            return self._json({"error": "audio too large"}, 413)
        audio = self.rfile.read(length)
        mime = self.headers.get("Content-Type") or "audio/webm"
        lang = self.headers.get("X-Reges-Lang") or None
        from .voice.engines import VoiceError, transcribe
        dev = getattr(self.cfg.voice, "stt_device", "auto") or "auto"
        # Header wins (per-request override), then config, then English.
        lang = lang or getattr(self.cfg.voice, "stt_language", "en") or "en"
        size = getattr(self.cfg.voice, "stt_model_size", "base") or "base"
        try:
            with BUS.during(State.LISTENING, "transcribing"):
                out = transcribe(audio, mime, language=lang, device=dev,
                                 model_size=size)
        except VoiceError as exc:
            BUS.error(str(exc))
            return self._json({"ok": False, "error": str(exc)}, 503)
        except Exception as exc:
            BUS.error(str(exc)[:200])
            return self._json({"ok": False, "error": str(exc)[:300]}, 500)
        if out.get("fallback"):
            BUS.log("warn", out["fallback"][:180])
        if not (out.get("text") or "").strip():
            BUS.log("voice", "heard nothing — try holding the key a little longer")
            return self._json({"ok": True, **out})
        tag = out.get("language", "")
        if not out.get("language_forced"):
            conf = out.get("language_confidence")
            tag += f" auto{f' {int(conf*100)}%' if conf else ''}"
        BUS.log("voice", f'heard [{out.get("device","cpu")} · {tag}]: "{out.get("text","")[:70]}"')
        return self._json({"ok": True, **out})

    def _voice_tts(self, data: dict) -> None:
        from pathlib import Path as _P
        from .voice.engines import VoiceError, synthesize
        md = _P(self.cfg.paths.models_dir) if self.cfg.paths.models_dir else None
        try:
            out = synthesize(data.get("text") or "", models_dir=md)
        except VoiceError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        if not out.get("audio"):
            # Valid answer: the browser speaks it. Zero install, still local.
            return self._json({"ok": True, "engine": out["engine"],
                               "note": out.get("note", "")})
        return self._send(200, out["audio"], out["mime"],
                          {"X-Reges-Engine": out["engine"]})

    # -- POST -------------------------------------------------------------- #
    def do_POST(self) -> None:
        if not self._guard_origin():
            return self._json({"error": "cross-origin rejected"}, 403)
        ALLOWED = ("/api/intent", "/api/settings", "/api/test", "/api/models",
                   "/api/apps/action", "/api/ask", "/api/pricing",
                   "/api/voice/stt", "/api/voice/tts", "/api/setup")
        if self.path not in ALLOWED and not self.path.startswith("/api/setup/"):
            return self._json({"error": "unknown endpoint"}, 404)

        # Audio is raw bytes, not JSON. Handle it before the JSON parse.
        if self.path == "/api/voice/stt":
            return self._voice_stt()

        length = int(self.headers.get("Content-Length") or 0)
        if length > 64_000:
            return self._json({"error": "payload too large"}, 413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        if self.path == "/api/settings":
            from .settings_api import save_settings
            try:
                return self._json(save_settings(self.cfg, data))
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)[:300]}, 500)
        if self.path == "/api/test":
            from .settings_api import test_connection
            return self._json(test_connection(data))
        if self.path == "/api/models":
            from .settings_api import list_models
            return self._json(list_models(data))
        if self.path == "/api/apps/action":
            from .settings_api import app_action
            return self._json(app_action(data))
        if self.path == "/api/setup":
            from .settings_api import save_setup
            try:
                return self._json(save_setup(self.cfg, data))
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)[:300]}, 500)
        if self.path == "/api/pricing":
            from .settings_api import save_pricing
            try:
                return self._json(save_pricing(self.cfg, data))
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)[:300]}, 500)
        if self.path.startswith("/api/setup/"):
            return self._setup_post(self.path.rsplit("/", 1)[-1], data)
        if self.path == "/api/voice/tts":
            return self._voice_tts(data)
        if self.path == "/api/ask":
            # Synchronous. Voice needs the answer back, not a fire-and-forget.
            text = (data.get("text") or "").strip()
            if not text:
                return self._json({"error": "empty"}, 400)
            BUS.say("user", text)
            try:
                reply = self.on_intent(text)
            except Exception as exc:
                BUS.error(str(exc)[:300])
                return self._json({"ok": False, "error": str(exc)[:300]}, 500)
            if isinstance(reply, str) and reply.strip():
                BUS.say("reges", reply)
            return self._json({"ok": True, "reply": reply if isinstance(reply, str) else ""})

        text = (data.get("text") or "").strip()
        if not text:
            return self._json({"error": "empty intent"}, 400)

        BUS.say("user", text)

        def _run(t: str) -> None:
            try:
                reply = self.on_intent(t)
                if isinstance(reply, str) and reply.strip():
                    BUS.say("reges", reply)
            except Exception as exc:
                BUS.error(str(exc)[:300])

        threading.Thread(target=_run, args=(text,), daemon=True).start()
        return self._json({"ok": True})


# --------------------------------------------------------------------------- #
# Deck + schedule
# --------------------------------------------------------------------------- #

# Every `intent` here must contain a literal trigger phrase from the matching
# SKILL.md. A deck button is a deterministic action -- it routes by keyword and
# never costs an LLM roundtrip. build_deck() asserts this at startup.
DECK_LABELS = {
    "plan-today":    [("plan today", "write today's top 3", "plan my day"),
                      ("plan tmrw", "queue tomorrow", "plan tomorrow")],
    "tebex-pull":    [("metrics pull", "Lux Empire sales", "metrics pull"),
                      ("wk review", "week over week", "week review")],
    "content-brief": [("content brief", "marketing angle from the numbers", "content brief")],
    "market-brief":  [("market brief", "pre-market read (research only)", "market brief")],
    "vault":         [("vault search", "search memory", "search the vault"),
                      ("vault clean", "promote patterns to wiki", "vault clean")],
}


def build_deck(cfg: RegesConfig) -> list[dict]:
    """Build the deck and verify every button still routes by keyword.

    A drifted intent string doesn't crash -- it silently becomes an LLM roundtrip
    that may route somewhere else entirely. Catch it at boot, not in six months.
    """
    from .router import _keyword_route, load_skills

    skills = load_skills(cfg)
    out = []
    for skill in cfg.skills.enabled:
        for label, desc, intent in DECK_LABELS.get(skill, []):
            hit = _keyword_route(intent, skills)
            if skills and (hit is None or hit.skill != skill):
                BUS.log("warn", f"deck '{label}' no longer keyword-routes to {skill}")
            out.append({"label": label, "description": desc, "intent": intent})
    return out


_SLOT_RE = re.compile(r"^\s*[-*]?\s*(?:\[(?P<done>[ xX])\]\s*)?(?P<time>\d{1,2}:\d{2})?\s*(?P<text>.+)$")


def parse_today(vault: Vault) -> list[dict]:
    """system/today.md -> schedule rows. Markdown stays the source of truth;
    the HUD is a view over it, never a second copy."""
    try:
        raw = vault.read("system/today.md")
    except Exception:
        return []

    now = datetime.now().strftime("%H:%M")
    slots: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("#") or line.startswith("---") or not line.strip():
            continue
        m = _SLOT_RE.match(line)
        if not m or not m.group("text"):
            continue
        slots.append({
            "time": m.group("time") or "",
            "text": m.group("text").strip(),
            "done": (m.group("done") or "").lower() == "x",
            "now": False,
        })

    timed = [s for s in slots if s["time"] and not s["done"]]
    current = [s for s in timed if s["time"] <= now]
    if current:
        current[-1]["now"] = True
    return slots[:14]


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #

class _QuietServer(ThreadingHTTPServer):
    """A browser closing a tab, navigating away, or dropping the SSE stream
    raises ConnectionAbortedError / ConnectionResetError / BrokenPipeError deep
    inside socketserver, which then dumps a full traceback to the console.

    That is the client behaving normally. Swallow those; print everything else.
    """

    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def serve(cfg: RegesConfig, on_intent: Callable[[str], None]) -> ThreadingHTTPServer:
    RegesHandler.cfg = cfg
    RegesHandler.vault = Vault(cfg.paths.vault_dir)
    RegesHandler.on_intent = staticmethod(on_intent)

    BUS.configure(
        session_cap=cfg.budgets.session_token_cap,
        price_in=cfg.budgets.price_in_per_mtok,
        price_out=cfg.budgets.price_out_per_mtok,
        on_cap=cfg.budgets.on_cap,
    )

    httpd = _QuietServer((cfg.server.host, cfg.server.port), RegesHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    BUS.push(State.IDLE)
    BUS.log("skill", f"hud on http://{cfg.server.host}:{cfg.server.port}")
    return httpd
