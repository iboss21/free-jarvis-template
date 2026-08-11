"""Settings + apps API.

Everything the settings screen needs, kept out of server.py so the HTTP
handler stays a thin router.

API keys go in through here and never come back out. `has_key: true` is the
only thing the browser is ever told.
"""
from __future__ import annotations

from pathlib import Path

from . import config as cfg_mod
from . import providers
from .config import SecretStore


def secrets_dir(cfg=None) -> Path:
    src = getattr(cfg, "_source_path", None) if cfg else None
    return Path(src).parent if src else cfg_mod.default_config_path().parent


def _secrets(cfg=None) -> SecretStore:
    return SecretStore(secrets_dir(cfg) / "secrets.json")


def _key_for(pid: str) -> str | None:
    p = providers.get(pid)
    if not p or not p.secret_key:
        return None
    try:
        return _secrets().get(p.secret_key)
    except Exception:
        return None


def get_settings(cfg) -> dict:
    m = cfg.models
    rows = providers.listing()
    for r in rows:
        r["has_key"] = bool(_key_for(r["id"])) if r["needs_key"] else True
    return {
        "providers": rows,
        "current": {
            "local_provider": getattr(m, "local_provider", "lmstudio"),
            "local_base_url": m.local_base_url,
            "local_model": m.local_model,
            "local_timeout_s": m.local_timeout_s,
            "remote_enabled": m.remote_enabled,
            "remote_provider": getattr(m, "remote_provider", "anthropic"),
            "remote_model": m.remote_model,
            "remote_max_tokens": m.remote_max_tokens,
            "router_tier": m.router_tier,
            "reasoning_tier": m.reasoning_tier,
            "offline_fallback": m.offline_fallback,
        },
        "budget": {
            "session_token_cap": getattr(cfg.budgets, "session_token_cap", 0),
        },
        "paths": {
            "app_dir": cfg.paths.app_dir,
            "vault_dir": cfg.paths.vault_dir,
            "config_file": str(getattr(cfg, "_source_path", "") or cfg_mod.default_config_path()),
        },
        "appearance": {
            "orb_density": cfg.appearance.orb_density,
            "orb_speed": getattr(cfg.appearance, "orb_speed", 1.0),
            "reduce_motion": cfg.appearance.reduce_motion,
        },
        "safety": {
            "allow_outbound_send": cfg.safety.allow_outbound_send,
            "allow_broker_orders": cfg.safety.allow_broker_orders,
            "allow_shell_exec": cfg.safety.allow_shell_exec,
        },
    }


def save_settings(cfg, data: dict) -> dict:
    m = cfg.models
    cur = data.get("current") or {}

    for field in ("local_base_url", "local_model", "remote_model",
                  "router_tier", "reasoning_tier"):
        if field in cur and isinstance(cur[field], str):
            setattr(m, field, cur[field].strip())
    for field in ("remote_enabled", "offline_fallback"):
        if field in cur:
            setattr(m, field, bool(cur[field]))
    for field in ("local_timeout_s", "remote_max_tokens"):
        if field in cur:
            try:
                setattr(m, field, int(cur[field]))
            except (TypeError, ValueError):
                pass
    # Provider ids are stored as plain attributes; the dataclass tolerates it
    # and load() round-trips them through the TOML.
    for field in ("local_provider", "remote_provider"):
        if field in cur and isinstance(cur[field], str):
            setattr(m, field, cur[field].strip())

    app = data.get("appearance") or {}
    if "orb_density" in app:
        try:
            cfg.appearance.orb_density = max(150, min(4000, int(app["orb_density"])))
        except (TypeError, ValueError):
            pass
    if "orb_speed" in app:
        try:
            cfg.appearance.orb_speed = max(0.0, min(3.0, float(app["orb_speed"])))
        except (TypeError, ValueError):
            pass
    if "reduce_motion" in app:
        cfg.appearance.reduce_motion = bool(app["reduce_motion"])

    # API key: write-only. Never echoed back.
    key = (data.get("api_key") or "").strip()
    key_for = (data.get("api_key_provider") or "").strip()
    if key and key_for:
        p = providers.get(key_for)
        if p and p.secret_key:
            _secrets().set(p.secret_key, key)

    # Save back to the file this config came from, not the global default —
    # run.py --app-dir must round-trip to the same place.
    src = getattr(cfg, "_source_path", None)
    path = cfg_mod.save(cfg, Path(src)) if src else cfg_mod.save(cfg)
    return {"ok": True, "saved_to": str(path)}


def test_connection(data: dict) -> dict:
    pid = (data.get("provider") or "").strip()
    p = providers.get(pid)
    if not p:
        return {"ok": False, "error": f"unknown provider: {pid}"}
    base = (data.get("base_url") or "").strip() or p.base_url
    model = (data.get("model") or "").strip() or p.default_model
    key = (data.get("api_key") or "").strip() or _key_for(pid)
    if not model:
        return {"ok": False, "error": "no model selected"}
    return providers.test(p, key, base, model)


def list_models(data: dict) -> dict:
    pid = (data.get("provider") or "").strip()
    p = providers.get(pid)
    if not p:
        return {"ok": False, "error": f"unknown provider: {pid}"}
    base = (data.get("base_url") or "").strip() or p.base_url
    key = (data.get("api_key") or "").strip() or _key_for(pid)
    models, err = providers.list_models(p, key, base)
    return {"ok": not err, "models": models, "error": err}


# ------------------------------------------------------------------ apps

def list_apps() -> dict:
    from .agent import apps as appmod
    return {"apps": appmod.inventory()}


def app_action(data: dict) -> dict:
    from .agent import apps as appmod
    action = (data.get("action") or "").strip()
    app_id = (data.get("app") or "").strip()
    try:
        if action == "launch":
            return appmod.launch(app_id, data.get("args") or [])
        if action == "close":
            return appmod.close(app_id, force=bool(data.get("force")))
        if action == "running":
            return {"ok": True, "app": app_id, "running": appmod.running(app_id)}
        if action == "plan":
            return appmod.control_plan(app_id, data.get("goal") or "")
        if action == "open_url":
            return appmod.open_url(data.get("url") or "")
        return {"ok": False, "error": f"unknown action: {action}"}
    except appmod.AppError as exc:
        return {"ok": False, "error": str(exc)}
