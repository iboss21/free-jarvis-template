#!/usr/bin/env python3
"""RUN REGES.

One command. No wizard, no install, no dependencies.

    python run.py

Writes a default config on first run, starts the HUD server, opens the browser.
Everything lands under ./.reges/ next to this file unless you pass --app-dir.

    python run.py --port 7717
    python run.py --app-dir D:/Reges
    python run.py --no-browser
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="Launch Reges")
    ap.add_argument("--app-dir", default=str(HERE / ".reges"),
                    help="where config, vault, data and logs live")
    ap.add_argument("--port", type=int, default=7717)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-voice", action="store_true", default=True,
                    help="voice is off by default; it needs extra binaries")
    args = ap.parse_args()

    if sys.version_info < (3, 11):
        print(f"Python 3.11+ required, found {sys.version.split()[0]}")
        return 2

    from reges import config as cfg_mod

    app = Path(args.app_dir).expanduser().resolve()
    cfg_file = app / "config.toml"
    first_run = not cfg_file.exists()

    if first_run:
        app.mkdir(parents=True, exist_ok=True)
        cfg = cfg_mod.RegesConfig()
        cfg.paths.app_dir = str(app)
        cfg.paths.vault_dir = str(app / "vault")
        cfg.paths.logs_dir = str(app / "logs")
        cfg.paths.models_dir = str(app / "models")
        cfg.voice.enabled = False          # needs whisper/piper binaries
        cfg.models.remote_enabled = False  # no key required to boot
        cfg_mod.save(cfg, cfg_file)
        for sub in ("vault", "logs", "data", "knowledge", "skills"):
            (app / sub).mkdir(parents=True, exist_ok=True)

    cfg = cfg_mod.load(cfg_file)
    cfg._source_path = str(cfg_file)   # settings save round-trips here
    cfg.server.host = args.host
    cfg.server.port = args.port
    cfg.server.open_hud_on_start = not args.no_browser
    if args.no_voice:
        cfg.voice.enabled = False

    # Install the agent-mode pack on first run if it is sitting next to us.
    pack = HERE / "reges-agent-mode"
    if first_run and pack.exists():
        for d in ("skills", "knowledge"):
            src = pack / d
            if src.exists():
                shutil.copytree(src, app / d, dirs_exist_ok=True)
        contract = pack / "AGENT-MODE.md"
        if contract.exists():
            shutil.copy2(contract, app / "AGENT-MODE.md")

    # Database + knowledge status.
    try:
        from reges.agent import db as agent_db
        from reges.agent import knowledge as agent_kb
        from reges.agent.paths import AgentPaths
        ap_paths = AgentPaths(cfg)
        ap_paths.ensure()
        agent_db.init(ap_paths.db)
        kb_rows = agent_kb.status(ap_paths.knowledge)
    except Exception as exc:  # agent layer is optional; the HUD still runs
        kb_rows = []
        print(f"agent layer unavailable: {exc}")

    from reges.server import serve
    from reges.state import BUS
    from reges.__main__ import Agent

    agent = Agent(cfg)
    httpd = serve(cfg, agent.handle)
    url = f"http://{cfg.server.host}:{cfg.server.port}"

    print()
    print("  R E G E S")
    print(f"  HUD        {url}")
    print(f"  app dir    {app}")
    print(f"  vault      {cfg.paths.vault_dir}")
    print(f"  skills     {', '.join(agent.skills) if agent.skills else 'none'}")
    if kb_rows:
        stale = [r["id"] for r in kb_rows if r["stale"]]
        print(f"  knowledge  {len(kb_rows)} entries"
              + (f", {len(stale)} STALE {stale}" if stale else ", all fresh"))
    mode = "local" if not cfg.models.remote_enabled else "remote"
    print(f"  model      {mode} -> {cfg.models.local_base_url}")
    if first_run:
        print()
        print("  First run. Config written. To point at your own model, edit:")
        print(f"    {cfg_file}")
        print("    [models] local_base_url / local_model")
    print()
    print("  ctrl-c to stop")
    print()

    if cfg.server.open_hud_on_start:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
