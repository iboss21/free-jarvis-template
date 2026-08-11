"""Reges setup wizard.

Zero third-party dependencies -- it must run on a Windows box with nothing but a
fresh CPython. Anything that needs pip gets installed *by* this wizard, not
assumed by it.

Nine screens. Every one has a default and takes Enter. Nothing is written to disk
until the final confirm, so an abort at screen 7 leaves no half-configured state.

    python install/wizard.py            # interactive
    python install/wizard.py --repair   # keep existing answers, re-run preflight
    python install/wizard.py --quiet    # accept every default, no prompts
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reges import config as cfg_mod  # noqa: E402
from reges.config import RegesConfig, SecretStore  # noqa: E402
from reges.vault import Vault  # noqa: E402

# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
CYAN = "\x1b[38;5;44m"
VIOLET = "\x1b[38;5;99m"
AMBER = "\x1b[38;5;214m"
GREEN = "\x1b[38;5;42m"
RED = "\x1b[38;5;203m"
GREY = "\x1b[38;5;244m"

TOTAL_SCREENS = 9


def _enable_vt() -> None:
    """Legacy conhost needs VT processing turned on explicitly."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        pass


def clear() -> None:
    print("\x1b[2J\x1b[H", end="")


def banner() -> None:
    print(f"""{CYAN}
      ██████  ███████  ██████  ███████ ███████
      ██   ██ ██      ██       ██      ██
      ██████  █████   ██   ███ █████   ███████
      ██   ██ ██      ██    ██ ██           ██
      ██   ██ ███████  ██████  ███████ ███████{RESET}
      {GREY}speak. route. remember. repeat.{RESET}
""")


def screen(n: int, title: str, subtitle: str = "") -> None:
    clear()
    bar_w = 34
    filled = int(bar_w * n / TOTAL_SCREENS)
    bar = f"{CYAN}{'━' * filled}{RESET}{GREY}{'━' * (bar_w - filled)}{RESET}"
    print()
    print(f"  {GREY}{n:02d}/{TOTAL_SCREENS}{RESET}  {bar}")
    print()
    print(f"  {BOLD}{title}{RESET}")
    if subtitle:
        print(f"  {GREY}{subtitle}{RESET}")
    print()


def ok(msg: str) -> None:
    print(f"    {GREEN}✓{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"    {AMBER}!{RESET} {msg}")


def bad(msg: str) -> None:
    print(f"    {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"    {GREY}·{RESET} {GREY}{msg}{RESET}")


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

QUIET = False


def ask(label: str, default: str = "", hint: str = "") -> str:
    if hint:
        print(f"    {GREY}{hint}{RESET}")
    if QUIET:
        print(f"  {CYAN}›{RESET} {label} {GREY}[{default}]{RESET} {DIM}(auto){RESET}")
        return default
    shown = f" {GREY}[{default}]{RESET}" if default else ""
    try:
        val = input(f"  {CYAN}›{RESET} {label}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        abort()
    return val or default


def ask_bool(label: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    if QUIET:
        return default
    while True:
        val = ask(f"{label} ({d})", "").lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        bad("answer y or n")


def ask_int(label: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    while True:
        raw = ask(label, str(default))
        try:
            v = int(raw)
        except ValueError:
            bad("numbers only")
            continue
        if lo is not None and v < lo:
            bad(f"minimum is {lo}")
            continue
        if hi is not None and v > hi:
            bad(f"maximum is {hi}")
            continue
        return v


def ask_choice(label: str, options: list[tuple[str, str]], default_idx: int = 0) -> str:
    for i, (val, desc) in enumerate(options, 1):
        mark = f"{CYAN}●{RESET}" if i - 1 == default_idx else f"{GREY}○{RESET}"
        print(f"    {mark} {BOLD}{i}{RESET}. {val}  {GREY}{desc}{RESET}")
    print()
    while True:
        raw = ask(label, str(default_idx + 1))
        try:
            i = int(raw)
            if 1 <= i <= len(options):
                return options[i - 1][0]
        except ValueError:
            pass
        bad(f"pick 1-{len(options)}")


def ask_path(label: str, default: Path, must_be_writable: bool = True) -> Path:
    while True:
        raw = ask(label, str(default))
        p = Path(os.path.expandvars(raw)).expanduser()
        try:
            p = p.resolve()
        except OSError:
            bad("that path can't be resolved")
            continue
        if not must_be_writable:
            return p
        probe = p if p.exists() else _nearest_existing(p)
        if probe is None:
            bad("no existing parent -- check the drive letter")
            continue
        if not os.access(probe, os.W_OK):
            bad(f"not writable: {probe}  (try a path under your user folder)")
            continue
        return p


def _nearest_existing(p: Path) -> Path | None:
    cur = p
    for _ in range(12):
        if cur.exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def pause() -> None:
    if QUIET:
        return
    try:
        input(f"\n  {GREY}Enter to continue{RESET}")
    except (EOFError, KeyboardInterrupt):
        print()
        abort()


def abort(code: int = 1):
    print(f"\n  {AMBER}Aborted. Nothing was written.{RESET}\n")
    sys.exit(code)


# --------------------------------------------------------------------------- #
# Screen 1 -- preflight
# --------------------------------------------------------------------------- #

def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}PB"


def probe_system() -> dict:
    out: dict = {"platform": sys.platform, "python": sys.version.split()[0]}
    out["python_ok"] = sys.version_info >= (3, 11)

    try:
        out["cpus"] = os.cpu_count() or 0
    except Exception:
        out["cpus"] = 0

    # RAM
    ram = 0
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD),
                            ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            ram = st.ullTotalPhys
        else:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        pass
    out["ram"] = ram
    out["ram_ok"] = ram >= 8 * 1024 ** 3

    # GPU (nvidia only -- absence is not fatal, just slower)
    gpu = ""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=6)
        if r.returncode == 0 and r.stdout.strip():
            gpu = r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    out["gpu"] = gpu

    try:
        du = shutil.disk_usage(Path.home())
        out["disk_free"] = du.free
        out["disk_ok"] = du.free >= 5 * 1024 ** 3
    except Exception:
        out["disk_free"] = 0
        out["disk_ok"] = False

    out["existing_config"] = cfg_mod.default_config_path().exists()
    return out


def screen_preflight() -> dict:
    screen(1, "Preflight", "Checking this machine before anything gets written.")
    p = probe_system()

    (ok if p["python_ok"] else bad)(f"Python {p['python']}" + ("" if p["python_ok"] else "  -- 3.11+ required"))
    (ok if p["ram_ok"] else warn)(f"RAM {human_bytes(p['ram'])}" + ("" if p["ram_ok"] else "  -- 8GB+ recommended for local models"))
    (ok if p["disk_ok"] else warn)(f"Disk free {human_bytes(p['disk_free'])}" + ("" if p["disk_ok"] else "  -- models need room"))
    info(f"CPU threads {p['cpus']}")
    if p["gpu"]:
        ok(f"GPU {p['gpu']}")
    else:
        warn("No NVIDIA GPU detected -- local models will run on CPU (slower, still works)")
    if p["platform"] != "win32":
        warn(f"Platform is {p['platform']}, not Windows. Voice + autostart are stubbed.")
    if p["existing_config"]:
        warn(f"Existing config at {cfg_mod.default_config_path()} -- it will be replaced at the end")

    if not p["python_ok"]:
        print()
        bad("Cannot continue on this Python. Install 3.11 or newer and re-run.")
        sys.exit(2)

    pause()
    return p


# --------------------------------------------------------------------------- #
# Screens 2-3 -- locations
# --------------------------------------------------------------------------- #

def default_app_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Reges"
    return Path.home() / ".local" / "share" / "reges"


def default_vault_dir() -> Path:
    return Path.home() / "Documents" / "Reges Vault"


def screen_install_location(cfg: RegesConfig) -> None:
    screen(2, "Install location", "Where the Reges program files live.")
    info("Put this on your fastest drive. It is program data, not your data.")
    info("Roughly 200MB, plus whatever models you download later.")
    print()
    app = ask_path("Install to", default_app_dir())
    models = ask_path("Models folder", app / "models")
    logs = ask_path("Logs folder", app / "logs")
    cfg.paths.app_dir = str(app)
    cfg.paths.models_dir = str(models)
    cfg.paths.logs_dir = str(logs)
    print()
    ok(f"App     {app}")
    ok(f"Models  {models}")
    ok(f"Logs    {logs}")
    pause()


def screen_vault_location(cfg: RegesConfig) -> None:
    screen(3, "Vault location", "Where your memory lives. This is the folder that matters.")
    info("Everything Reges learns lands here as plain markdown.")
    info("Separate question from the install path on purpose -- most people want")
    info("the vault in OneDrive/Dropbox for sync, and the app on a fast local disk.")
    print()
    vault = ask_path("Vault folder", default_vault_dir())
    cfg.paths.vault_dir = str(vault)

    existing = (vault / "raw").exists() or (vault / "wiki").exists()
    print()
    if existing:
        warn("A vault already exists here. Reges will use it as-is and add nothing destructive.")
    else:
        ok(f"Will scaffold a new vault at {vault}")
    info("Structure: raw/  wiki/  outputs/  system/  .reges/")
    pause()


# --------------------------------------------------------------------------- #
# Screen 4 -- model backend
# --------------------------------------------------------------------------- #

def probe_openai_endpoint(base_url: str, timeout: float = 4.0) -> tuple[bool, list[str], str]:
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        return True, ids, ""
    except urllib.error.URLError as e:
        return False, [], str(getattr(e, "reason", e))
    except Exception as e:
        return False, [], str(e)


def screen_models(cfg: RegesConfig) -> None:
    screen(4, "Model backend", "Local model for routing and quick turns.")
    info("Any OpenAI-compatible server: LM Studio, Ollama, llama.cpp, vLLM.")
    print()

    candidates = [
        "http://127.0.0.1:1234/v1",   # LM Studio
        "http://127.0.0.1:11434/v1",  # Ollama
        "http://127.0.0.1:8000/v1",   # vLLM / llama.cpp
    ]
    found_url, found_models = "", []
    for url in candidates:
        alive, ids, _ = probe_openai_endpoint(url, timeout=1.5)
        if alive:
            found_url, found_models = url, ids
            ok(f"Found a server at {url}  ({len(ids)} models)")
            break
    if not found_url:
        warn("No local model server responded on the usual ports.")
        info("That is fine -- you can set it now and start the server later.")
    print()

    base = ask("Local endpoint", found_url or candidates[0])
    alive, ids, err = probe_openai_endpoint(base, timeout=4.0)
    if alive:
        ok(f"Reachable -- {len(ids)} models")
        for m in ids[:8]:
            info(m)
        if len(ids) > 8:
            info(f"... and {len(ids) - 8} more")
    else:
        warn(f"Not reachable ({err}). Saving anyway.")
    print()

    model = ask("Router model id", (ids[0] if ids else ""),
                hint="The small/fast one. Routing does not need your biggest model.")
    cfg.models.local_base_url = base
    cfg.models.local_model = model

    print()
    print(f"  {BOLD}Heavy reasoning{RESET}")
    info("Routing on a 7B is fine. Analysis is not. A remote model handles the")
    info("hard turns; everything else stays local.")
    print()
    cfg.models.remote_enabled = ask_bool("Enable a remote model for heavy reasoning?", True)
    if cfg.models.remote_enabled:
        cfg.models.reasoning_tier = "remote"
        cfg.models.offline_fallback = ask_bool(
            "If the remote is unreachable, fall back to local instead of failing?", True)
    else:
        cfg.models.reasoning_tier = "local"
    pause()


# --------------------------------------------------------------------------- #
# Screen 5 -- secrets
# --------------------------------------------------------------------------- #

def screen_secrets(cfg: RegesConfig, store: SecretStore) -> dict[str, str]:
    screen(5, "Keys", "Stored encrypted. Never in the TOML.")
    if store.is_encrypted():
        ok("Windows DPAPI available -- keys are encrypted against your user account")
        info("Copying the file to another machine or user account yields nothing")
    else:
        warn("Not on Windows: keys will be base64 in a 0600 file")
        warn("That is obfuscation, NOT encryption. Use env vars in production.")
    print()

    pending: dict[str, str] = {}
    if cfg.models.remote_enabled:
        v = ask("Anthropic API key", "", hint="Leave blank to set later with: reges secrets set anthropic_api_key")
        if v:
            pending["anthropic_api_key"] = v
            ok("Queued (written at the end)")
    print()
    info("Optional now, needed by specific skills later:")
    for key, label in (("tebex_secret", "Tebex secret  (tebex-pull)"),
                       ("wolves_rcon", "wolves.land RCON  (server-health)")):
        v = ask(label, "")
        if v:
            pending[key] = v
    pause()
    return pending


# --------------------------------------------------------------------------- #
# Screen 6 -- voice
# --------------------------------------------------------------------------- #

def screen_voice(cfg: RegesConfig) -> None:
    screen(6, "Voice", "Local ears and mouth. Audio never leaves the machine.")
    cfg.voice.enabled = ask_bool("Enable voice?", True)
    if not cfg.voice.enabled:
        info("Voice off. The HUD and skills still work by keyboard.")
        pause()
        return

    print()
    print(f"  {BOLD}Speech to text{RESET}")
    cfg.voice.stt_model = ask_choice("Whisper model", [
        ("tiny.en",   "~75MB   fastest, sloppy on names"),
        ("base.en",   "~145MB  the right default"),
        ("small.en",  "~470MB  noticeably better, still real-time on CPU"),
        ("medium.en", "~1.5GB  GPU recommended"),
    ], default_idx=1)

    print()
    print(f"  {BOLD}Text to speech{RESET}")
    cfg.voice.tts_voice = ask_choice("Piper voice", [
        ("en_US-lessac-medium", "neutral, clear"),
        ("en_US-ryan-high",     "warmer, slower"),
        ("en_GB-alba-medium",   "British"),
        ("none",                "text only, no speech"),
    ], default_idx=0)

    print()
    print(f"  {BOLD}Push to talk{RESET}")
    info("Wake word means a model listening on your mic all day. Off by default.")
    print()
    cfg.voice.ptt_modifier = ask("PTT modifier", "ctrl+alt")
    cfg.voice.ptt_hotkey = ask("PTT key", "space")
    combo = f"{cfg.voice.ptt_modifier}+{cfg.voice.ptt_hotkey}"

    conflicts = {
        "ctrl+alt+delete": "reserved by Windows",
        "alt+tab": "window switching",
        "ctrl+alt+space": "conflicts with some IMEs",
    }
    if combo.lower() in conflicts:
        warn(f"{combo} -- {conflicts[combo.lower()]}. Consider another combo.")
    else:
        ok(f"Hotkey {combo}")
    if ask_bool("Do you play RedM/FiveM on this machine?", True):
        info("Noted: PTT is stored in config, not hardcoded. Change it any time")
        info("without touching code if it collides with an in-game bind.")
    print()
    cfg.voice.wake_word_enabled = ask_bool("Enable wake word too? (not recommended)", False)
    pause()


# --------------------------------------------------------------------------- #
# Screen 7 -- appearance
# --------------------------------------------------------------------------- #

PALETTES = {
    "vault": {"idle": "#2f6f7a", "listening": "#dfe9ee", "thinking": "#7c5cff",
              "reasoning": "#ffab3d", "working": "#3ddc84", "speaking": "#3d9bff",
              "error": "#ff4d4d"},
    "ember": {"idle": "#6b4a2f", "listening": "#f5e6d3", "thinking": "#ff7a3d",
              "reasoning": "#ffc93d", "working": "#d4a017", "speaking": "#ff5e3a",
              "error": "#ff2d55"},
    "mono":  {"idle": "#3a3a3a", "listening": "#ffffff", "thinking": "#8a8a8a",
              "reasoning": "#b4b4b4", "working": "#d4d4d4", "speaking": "#eaeaea",
              "error": "#ff4d4d"},
    "abyss": {"idle": "#1f4d5c", "listening": "#c8f0ff", "thinking": "#00b3a4",
              "reasoning": "#00d4ff", "working": "#00ff9d", "speaking": "#4dd2ff",
              "error": "#ff3d71"},
}


def _swatch(hexcolor: str) -> str:
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\x1b[48;2;{r};{g};{b}m   {RESET}"


def screen_appearance(cfg: RegesConfig) -> None:
    screen(7, "Appearance", "The orb is a live readout of the agent, not decoration.")
    info("Each state gets its own colour and its own motion signature.")
    print()

    names = list(PALETTES)
    for i, name in enumerate(names, 1):
        pal = PALETTES[name]
        swatches = "".join(_swatch(pal[k]) for k in
                           ("idle", "listening", "thinking", "reasoning", "working", "speaking"))
        print(f"    {BOLD}{i}{RESET}. {name:<7} {swatches}")
    print()
    print(f"       {GREY}idle  listen  think  reason  work  speak{RESET}")
    print()
    choice = ask_int("Palette", 1, 1, len(names))
    pal_name = names[choice - 1]
    cfg.appearance.colors = dict(PALETTES[pal_name])
    cfg.appearance.theme = f"{pal_name}-dark"

    if ask_bool("Customise individual state colours?", False):
        for state in ("idle", "listening", "thinking", "reasoning", "working", "speaking", "error"):
            cur = cfg.appearance.colors[state]
            print(f"    {_swatch(cur)} {state}")
            v = ask(f"  {state} hex", cur)
            if v.startswith("#") and len(v) == 7:
                cfg.appearance.colors[state] = v
            elif v != cur:
                warn("expected #rrggbb -- keeping previous")
    print()

    cfg.appearance.orb_density = ask_int("Orb particle count", 900, 120, 4000)
    if cfg.appearance.orb_density > 2200:
        warn("Above ~2200 particles the orb costs real GPU. Fine on a desktop, not on a laptop battery.")
    cfg.appearance.show_orb_widget = ask_bool("Show the small always-on-top orb widget?", True)
    cfg.appearance.always_on_top = ask_bool("Keep the HUD above other windows?", True)
    cfg.appearance.reduce_motion = ask_bool("Reduce motion? (accessibility)", False)
    pause()


# --------------------------------------------------------------------------- #
# Screen 8 -- budgets
# --------------------------------------------------------------------------- #

def screen_budgets(cfg: RegesConfig) -> None:
    screen(8, "Budgets", "A hard stop, not a dashboard you'll ignore.")
    info("Token counting is on the same event bus as the orb -- the gauge under it")
    info("fills toward this cap, ambers at 80%, and stops paid calls at 100%.")
    print()
    cfg.budgets.session_token_cap = ask_int("Session token cap", 250_000, 0, 50_000_000)
    if cfg.budgets.session_token_cap == 0:
        warn("0 = unlimited. You will find out the cost at the end of the month.")
    cfg.budgets.monthly_usd_cap = float(ask("Monthly USD cap", "50"))
    cfg.budgets.on_cap = ask_choice("At the cap, Reges should", [
        ("refuse", "stop making paid calls until reset  (recommended)"),
        ("warn",   "log a warning and keep going"),
    ], default_idx=0)
    print()
    print(f"  {BOLD}Safety{RESET}  {GREY}shown so you know what is and isn't on{RESET}")
    print()
    ok("Drafts only -- Reges composes, you press send")
    ok("No broker credentials, no order placement  (see PLAN.md section 7)")
    ok("No shell execution")
    ok("Writes outside the vault require confirmation")
    info("These are set in config under [safety] and are off by default by design.")
    pause()


# --------------------------------------------------------------------------- #
# Screen 9 -- skills + write
# --------------------------------------------------------------------------- #

SKILL_CATALOG = [
    ("vault",         "read/write/search memory -- every other skill calls it", True),
    ("plan-today",    "reads yesterday + queue, writes today's top 3, speaks it", True),
    ("tebex-pull",    "Lux Empire sales per resource, flags broken trends", True),
    ("content-brief", "turns metric outliers into a marketing angle (draft only)", True),
    ("market-brief",  "pre-market read on your watchlist -- research, no orders", False),
]


def screen_skills(cfg: RegesConfig) -> None:
    screen(9, "Skills", "Small single-purpose skills beat one giant prompt.")
    enabled = []
    for name, desc, default_on in SKILL_CATALOG:
        print(f"    {BOLD}{name}{RESET}  {GREY}{desc}{RESET}")
        if ask_bool(f"  enable {name}?", default_on):
            enabled.append(name)
        print()
    cfg.skills.enabled = enabled or ["vault"]
    ok(f"{len(cfg.skills.enabled)} skills enabled")


def summary(cfg: RegesConfig, pending_secrets: dict) -> None:
    clear()
    print()
    print(f"  {BOLD}Review{RESET}  {GREY}nothing has been written yet{RESET}")
    print()
    rows = [
        ("App",        cfg.paths.app_dir),
        ("Vault",      cfg.paths.vault_dir),
        ("Local model", f"{cfg.models.local_model or '(unset)'} @ {cfg.models.local_base_url}"),
        ("Remote",     cfg.models.remote_model if cfg.models.remote_enabled else "disabled"),
        ("Voice",      (f"{cfg.voice.stt_model} / {cfg.voice.tts_voice} / "
                        f"{cfg.voice.ptt_modifier}+{cfg.voice.ptt_hotkey}")
                       if cfg.voice.enabled else "disabled"),
        ("Theme",      f"{cfg.appearance.theme}, {cfg.appearance.orb_density} particles"),
        ("Budget",     f"{cfg.budgets.session_token_cap:,} tok/session, "
                       f"${cfg.budgets.monthly_usd_cap:.0f}/mo, on cap: {cfg.budgets.on_cap}"),
        ("Skills",     ", ".join(cfg.skills.enabled)),
        ("Keys",       ", ".join(pending_secrets) or "none"),
    ]
    for k, v in rows:
        print(f"    {GREY}{k:<12}{RESET}{v}")
    print()


def commit(cfg: RegesConfig, pending_secrets: dict, sysinfo: dict) -> None:
    print(f"  {BOLD}Writing{RESET}")
    print()

    for label, p in (("app", cfg.paths.app_dir), ("models", cfg.paths.models_dir),
                     ("logs", cfg.paths.logs_dir)):
        Path(p).mkdir(parents=True, exist_ok=True)
        ok(f"{label} folder")

    vault = Vault(cfg.paths.vault_dir)
    created = vault.scaffold()
    ok(f"vault scaffolded ({len(created)} new entries)" if created else "vault already present, untouched")

    cfg_path = cfg_mod.save(cfg)
    ok(f"config -> {cfg_path}")

    if pending_secrets:
        store = SecretStore(cfg_path.parent / "secrets.json")
        for k, v in pending_secrets.items():
            store.set(k, v)
        ok(f"{len(pending_secrets)} key(s) stored "
           f"({'DPAPI-encrypted' if store.is_encrypted() else 'obfuscated only'})")

    (Path(cfg.paths.app_dir) / "install-report.json").write_text(
        json.dumps({"system": sysinfo, "config": asdict(cfg)}, indent=2, default=str),
        encoding="utf-8")
    ok("install report written")

    print()
    print(f"  {GREEN}{BOLD}Reges is installed.{RESET}")
    print()
    print(f"    {CYAN}reges start{RESET}          {GREY}launch the HUD{RESET}")
    print(f"    {CYAN}reges doctor{RESET}         {GREY}re-run preflight against the live config{RESET}")
    print(f"    {CYAN}reges say \"...\"{RESET}      {GREY}send an intent without voice{RESET}")
    print()
    print(f"  {GREY}HUD: http://{cfg.server.host}:{cfg.server.port}{RESET}")
    print(f"  {GREY}Vault: {cfg.paths.vault_dir}{RESET}")
    print()


def main() -> int:
    global QUIET
    ap = argparse.ArgumentParser(description="Reges setup wizard")
    ap.add_argument("--quiet", action="store_true", help="accept every default")
    ap.add_argument("--repair", action="store_true", help="start from existing config")
    args = ap.parse_args()
    QUIET = args.quiet

    _enable_vt()
    clear()
    banner()
    if not QUIET:
        print(f"  {GREY}Nine screens. Enter accepts the default. Ctrl-C aborts cleanly.{RESET}")
        print(f"  {GREY}Nothing is written until you confirm at the end.{RESET}")
        pause()

    cfg = cfg_mod.load() if args.repair else RegesConfig()
    sysinfo = screen_preflight()
    screen_install_location(cfg)
    screen_vault_location(cfg)
    screen_models(cfg)
    store = SecretStore(cfg_mod.default_config_path().parent / "secrets.json")
    pending = screen_secrets(cfg, store)
    screen_voice(cfg)
    screen_appearance(cfg)
    screen_budgets(cfg)
    screen_skills(cfg)

    summary(cfg, pending)
    if not ask_bool("Write this configuration?", True):
        abort(0)
    print()
    commit(cfg, pending, sysinfo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        abort()
