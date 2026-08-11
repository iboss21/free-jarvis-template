"""Local application control.

You asked for Reges to open and drive software — Photoshop, Webull, Discord.
Three tiers, and the difference between them is reliability, not ambition.

  TIER 1  LAUNCH / FOCUS / CLOSE          reliable, ~100%
          os.startfile, subprocess, taskkill. This just works.

  TIER 2  OFFICIAL SCRIPTING / API        reliable, and the right answer
          Photoshop  -> UXP / ExtendScript (photoshop.exe -r script.jsx)
          Webull     -> OpenAPI (HTTP + MQTT + gRPC, official Python SDK)
          Discord    -> REST API / webhooks
          Excel/Word -> COM automation
          If an app has this, Reges uses it and never touches the GUI.

  TIER 3  GUI AUTOMATION                  LAST RESORT, gated, confirmed
          Driving pixels and controls. Measured browser agents cap at 33-64%
          on live write tasks; desktop GUI automation is harder than that,
          not easier — no DOM, no stable selectors, no accessibility tree on
          canvas-heavy apps like Photoshop. Reges will do it, but only with
          confirmation, only for reversible steps, and it reports failure
          instead of guessing.

The registry below is data. Adding an app is an entry, not a code path.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

IS_WIN = sys.platform == "win32"


@dataclass
class App:
    id: str
    label: str
    exe: list[str] = field(default_factory=list)      # executable names to find
    hints: list[str] = field(default_factory=list)    # common install paths (Windows)
    process: str = ""                                 # process name for focus/close
    tier2: str = ""                                   # official control surface, if any
    tier2_docs: str = ""
    args: list[str] = field(default_factory=list)
    category: str = "app"


REGISTRY: dict[str, App] = {
    "photoshop": App(
        id="photoshop", label="Adobe Photoshop", category="design",
        exe=["Photoshop.exe"],
        hints=[r"C:\Program Files\Adobe\Adobe Photoshop *\Photoshop.exe"],
        process="Photoshop.exe",
        tier2="UXP plugin or ExtendScript (.jsx). Photoshop.exe accepts a script "
              "path; batch work should go through scripting, never the GUI.",
        tier2_docs="https://developer.adobe.com/photoshop/uxp/",
    ),
    "illustrator": App(
        id="illustrator", label="Adobe Illustrator", category="design",
        exe=["Illustrator.exe"],
        hints=[r"C:\Program Files\Adobe\Adobe Illustrator *\Support Files\Contents\Windows\Illustrator.exe"],
        process="Illustrator.exe",
        tier2="ExtendScript / UXP",
        tier2_docs="https://developer.adobe.com/illustrator/",
    ),
    "figma": App(
        id="figma", label="Figma", category="design",
        exe=["Figma.exe"], hints=[r"%LOCALAPPDATA%\Figma\Figma.exe"],
        process="Figma.exe",
        tier2="Figma REST API + plugin API. Reges already has an MCP connector.",
        tier2_docs="https://www.figma.com/developers/api",
    ),
    "webull": App(
        id="webull", label="Webull", category="finance",
        exe=["Webull.exe", "WebullDesktop.exe"],
        hints=[r"%LOCALAPPDATA%\Webull\Webull.exe"],
        process="Webull.exe",
        tier2="Webull OpenAPI — HTTP for requests, MQTT for market data, gRPC "
              "for order events. Official Python SDK. NEVER drive the desktop "
              "GUI for anything involving an order.",
        tier2_docs="https://developer.webull.com/apis/docs/",
    ),
    "discord": App(
        id="discord", label="Discord", category="comms",
        exe=["Discord.exe", "Update.exe"],
        hints=[r"%LOCALAPPDATA%\Discord\Update.exe"],
        args=["--processStart", "Discord.exe"], process="Discord.exe",
        tier2="Discord REST API and webhooks. Posting goes through the API, "
              "not through the client.",
        tier2_docs="https://discord.com/developers/docs",
    ),
    "obs": App(
        id="obs", label="OBS Studio", category="media",
        exe=["obs64.exe"], hints=[r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"],
        process="obs64.exe",
        tier2="obs-websocket — full scene and recording control over WebSocket.",
        tier2_docs="https://github.com/obsproject/obs-websocket",
    ),
    "vscode": App(
        id="vscode", label="VS Code", category="dev",
        exe=["Code.exe", "code"],
        hints=[r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"],
        process="Code.exe", tier2="`code` CLI",
    ),
    "lmstudio": App(
        id="lmstudio", label="LM Studio", category="ai",
        exe=["LM Studio.exe"], process="LM Studio.exe",
        tier2="Local HTTP server on 1234 / 2126 — Reges talks to that, "
              "not to the window.",
    ),
    "browser": App(
        id="browser", label="Default browser", category="web",
        exe=["chrome.exe", "msedge.exe", "firefox.exe"],
        tier2="Playwright or CDP for automation. DOM-driven beats vision-driven "
              "by 12-17 points on real sites.",
    ),
    "explorer": App(id="explorer", label="File Explorer", category="system",
                    exe=["explorer.exe"], process="explorer.exe"),
    "terminal": App(id="terminal", label="Windows Terminal", category="system",
                    exe=["wt.exe", "powershell.exe"]),
}


# --------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------

def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def resolve(app: App) -> str:
    """Find the executable, or return ''."""
    for name in app.exe:
        found = shutil.which(name)
        if found:
            return found
    if not IS_WIN:
        return ""
    for hint in app.hints:
        pattern = _expand(hint)
        if "*" in pattern:
            parent = Path(pattern).parent.parent
            try:
                matches = sorted(parent.glob(
                    str(Path(pattern).relative_to(parent))), reverse=True)
                if matches:
                    return str(matches[0])
            except Exception:
                continue
        elif Path(pattern).is_file():
            return pattern
    # Start Menu shortcut scan — catches everything installed normally.
    for root in (r"%ProgramData%\Microsoft\Windows\Start Menu\Programs",
                 r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"):
        base = Path(_expand(root))
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            if app.label.lower() in lnk.stem.lower():
                return str(lnk)
    return ""


def inventory() -> list[dict]:
    """What is actually installed on this machine."""
    rows = []
    for app in REGISTRY.values():
        path = resolve(app)
        rows.append({
            "id": app.id, "label": app.label, "category": app.category,
            "installed": bool(path), "path": path,
            "tier2": app.tier2, "tier2_docs": app.tier2_docs,
            "control": "api" if app.tier2 else "launch-only",
        })
    return sorted(rows, key=lambda r: (not r["installed"], r["category"], r["label"]))


# --------------------------------------------------------------------
# tier 1 — launch, focus, close
# --------------------------------------------------------------------

class AppError(RuntimeError):
    pass


def launch(app_id: str, extra_args: list[str] | None = None) -> dict:
    app = REGISTRY.get(app_id)
    if not app:
        raise AppError(f"unknown app: {app_id}")
    path = resolve(app)
    if not path:
        raise AppError(f"{app.label} is not installed, or not where Reges looked")

    args = [path] + app.args + (extra_args or [])
    try:
        if IS_WIN and path.lower().endswith(".lnk"):
            os.startfile(path)  # type: ignore[attr-defined]
            pid = None
        else:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) if IS_WIN else 0,
                start_new_session=not IS_WIN,
            )
            pid = proc.pid
    except OSError as exc:
        raise AppError(str(exc)) from exc

    return {"ok": True, "app": app.id, "label": app.label, "path": path, "pid": pid}


def open_url(url: str) -> dict:
    """Open a URL in the default browser. Safer than driving a browser window."""
    if not url.lower().startswith(("http://", "https://")):
        raise AppError("only http(s) URLs")
    import webbrowser
    webbrowser.open(url)
    return {"ok": True, "url": url}


def running(app_id: str) -> bool:
    app = REGISTRY.get(app_id)
    if not app or not app.process:
        return False
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {app.process}"],
                                 capture_output=True, text=True, timeout=10).stdout
            return app.process.lower() in out.lower()
        out = subprocess.run(["pgrep", "-f", app.process],
                             capture_output=True, text=True, timeout=10).stdout
        return bool(out.strip())
    except Exception:
        return False


def close(app_id: str, force: bool = False) -> dict:
    """Close an app. Never force-kills unless explicitly asked — an unsaved
    Photoshop document is not worth a tidy process table."""
    app = REGISTRY.get(app_id)
    if not app or not app.process:
        raise AppError(f"no process name known for {app_id}")
    if not IS_WIN:
        raise AppError("close is Windows-only for now")
    cmd = ["taskkill", "/IM", app.process]
    if force:
        cmd.append("/F")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return {"ok": r.returncode == 0, "app": app_id,
            "output": (r.stdout or r.stderr).strip()[:300]}


# --------------------------------------------------------------------
# tier 2 — official control surfaces
# --------------------------------------------------------------------

def control_plan(app_id: str, goal: str) -> dict:
    """What Reges should actually do to control this app for this goal.

    Returns the tier it will use and why. The point is to stop the agent
    reaching for the GUI when a real API exists two lines away.
    """
    app = REGISTRY.get(app_id)
    if not app:
        return {"tier": 0, "reason": f"unknown app: {app_id}"}
    if app.tier2:
        return {"tier": 2, "surface": app.tier2, "docs": app.tier2_docs,
                "reason": f"{app.label} has an official control surface. Use it. "
                          f"GUI automation on this app is slower and less reliable."}
    return {"tier": 3, "reason": f"{app.label} has no known API. GUI automation "
                                 f"only, with confirmation, and only for "
                                 f"reversible steps.",
            "caveat": "Measured live-site write-task success for the best agents "
                      "is 33-64%. Desktop GUI is harder. Expect failures and "
                      "design for retry."}


def run_photoshop_script(script_path: str) -> dict:
    """Tier 2 for Photoshop: hand it a .jsx instead of clicking.

    photoshop.exe -r <script> runs the script and is the supported batch path.
    """
    app = REGISTRY["photoshop"]
    exe = resolve(app)
    if not exe:
        raise AppError("Photoshop not found")
    p = Path(script_path)
    if not p.is_file() or p.suffix.lower() not in (".jsx", ".js"):
        raise AppError("expected a .jsx script path")
    subprocess.Popen([exe, "-r", str(p)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "script": str(p),
            "note": "Photoshop runs this without a human at the keyboard. "
                    "Verify the script on a copy first."}


def summary() -> str:
    inv = inventory()
    found = [r for r in inv if r["installed"]]
    lines = [f"platform: {platform.system()} {platform.release()}",
             f"{len(found)}/{len(inv)} known apps found"]
    for r in inv:
        mark = "x" if r["installed"] else " "
        lines.append(f"  [{mark}] {r['label']:<22} {r['control']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
    print()
    print(json.dumps(control_plan("webull", "place a trade"), indent=2))
