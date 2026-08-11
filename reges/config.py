"""Reges configuration: schema, defaults, load/save, secret handling.

Config lives in TOML so you can hand-edit it. Secrets never do -- they go through
Windows DPAPI (CryptProtectData), which ties the ciphertext to the current user
account. On non-Windows the fallback is an obfuscated file with 0600 perms and a
loud warning; it is NOT real protection and says so.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

ENV_PREFIX = "REGES_"
CONFIG_FILENAME = "reges.toml"


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

@dataclass
class PathsConfig:
    app_dir: str = ""
    vault_dir: str = ""
    models_dir: str = ""
    logs_dir: str = ""


@dataclass
class ModelConfig:
    # Local OpenAI-compatible endpoint (LM Studio, Ollama, llama.cpp server, vLLM...)
    local_base_url: str = "http://127.0.0.1:1234/v1"
    local_model: str = ""
    local_timeout_s: int = 120

    # Remote heavy-reasoning model. Key is NOT stored here.
    remote_enabled: bool = False
    remote_model: str = "claude-sonnet-4-6"
    remote_max_tokens: int = 4096

    # Which tier handles which job.
    router_tier: str = "local"      # local | remote
    reasoning_tier: str = "remote"  # local | remote
    offline_fallback: bool = True   # if remote unreachable, degrade to local


@dataclass
class VoiceConfig:
    enabled: bool = True
    stt_engine: str = "whisper.cpp"
    stt_device: str = "auto"        # auto | cuda | cpu
    stt_language: str = "en"        # ISO code, or "auto" (unreliable on short clips)
    stt_model_size: str = "base"
    stt_model: str = "base.en"
    stt_binary: str = ""
    tts_engine: str = "piper"
    tts_voice: str = "en_US-lessac-medium"
    tts_binary: str = ""
    ptt_hotkey: str = "space"
    ptt_modifier: str = "ctrl+alt"
    wake_word_enabled: bool = False
    wake_word: str = "reges"
    input_device: str = ""
    output_device: str = ""


@dataclass
class AppearanceConfig:
    theme: str = "vault-dark"
    always_on_top: bool = True
    orb_density: int = 900          # particle count
    orb_scale: float = 1.0
    orb_speed: float = 1.0          # 0 = frozen, 1 = default, 2 = double
    theme: str = "obsidian"         # see hud/themes.js
    orb_variant: str = "lattice"    # lattice | nebula | rings | liquid | shards | pulse
    show_orb_widget: bool = True    # separate always-on-top orb window
    reduce_motion: bool = False
    # Per-state accent colours. The HUD derives its entire palette from the active one.
    colors: dict[str, str] = field(default_factory=lambda: {
        "idle":      "#2f6f7a",
        "listening": "#dfe9ee",
        "thinking":  "#7c5cff",
        "reasoning": "#ffab3d",
        "working":   "#3ddc84",
        "speaking":  "#3d9bff",
        "error":     "#ff4d4d",
    })


@dataclass
class BudgetConfig:
    session_token_cap: int = 250_000
    monthly_usd_cap: float = 50.0
    on_cap: str = "refuse"          # refuse | warn
    warn_at_pct: int = 80
    # Per-1M-token pricing used for the running cost estimate. Override per model.
    price_in_per_mtok: float = 3.0
    price_out_per_mtok: float = 15.0


@dataclass
class PricingConfig:
    """Per-model rates in USD per million tokens.

    Anything not listed falls back to the built-in table, and anything not in
    that either is reported as unpriced rather than guessed.
    Shape: {"model-substring": {"input": 3.0, "output": 15.0, "cache_read": 0.3}}
    """
    overrides: dict = field(default_factory=dict)
    default_input_per_mtok: float = 3.0
    default_output_per_mtok: float = 15.0


@dataclass
class SkillsConfig:
    enabled: list[str] = field(default_factory=lambda: [
        "vault", "plan-today", "tebex-pull", "content-brief", "market-brief",
    ])
    extra_skill_dirs: list[str] = field(default_factory=list)
    router_confidence_floor: float = 0.55  # below this, ask instead of guessing


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 7717
    open_hud_on_start: bool = True


@dataclass
class SafetyConfig:
    """Hard limits. The wizard shows these but does not offer to disable them."""
    allow_outbound_send: bool = False   # email/post/publish. v1: drafts only.
    allow_broker_orders: bool = False   # never flipped by the wizard. See PLAN.md section 7.
    allow_shell_exec: bool = False
    confirm_file_writes_outside_vault: bool = True


@dataclass
class RegesConfig:
    version: int = 1
    onboarded: bool = False
    setup_complete: bool = False
    paths: PathsConfig = field(default_factory=PathsConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


# --------------------------------------------------------------------------- #
# Load / save
# --------------------------------------------------------------------------- #

def _resolve_hints(cls) -> dict[str, Any]:
    """`from __future__ import annotations` makes dataclass field.type a *string*.
    Without resolving it, is_dataclass() is False for every nested section and the
    sub-tables silently load as plain dicts -- which fails later, far from here.
    """
    import typing
    try:
        return typing.get_type_hints(cls)
    except Exception:
        return {}


def _from_dict(cls, data: dict[str, Any]):
    if not is_dataclass(cls):
        return data
    hints = _resolve_hints(cls)
    kwargs = {}
    known = {f.name for f in fields(cls)}
    for key, val in data.items():
        if key not in known:
            continue  # forward-compatible: ignore unknown keys instead of exploding
        ftype = hints.get(key)
        if ftype is not None and is_dataclass(ftype) and isinstance(val, dict):
            kwargs[key] = _from_dict(ftype, val)
        else:
            kwargs[key] = val
    return cls(**kwargs)


def default_config_path() -> Path:
    override = os.environ.get(f"{ENV_PREFIX}CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Reges" / CONFIG_FILENAME


def load(path: Path | None = None) -> RegesConfig:
    path = path or default_config_path()
    if not path.exists():
        return RegesConfig()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    cfg = _from_dict(RegesConfig, raw)
    _apply_env_overrides(cfg)
    return cfg


def _apply_env_overrides(cfg: RegesConfig) -> None:
    """REGES_MODELS_LOCAL_MODEL=foo overrides cfg.models.local_model."""
    for section_field in fields(cfg):
        section = getattr(cfg, section_field.name)
        if not is_dataclass(section):
            continue
        for f in fields(section):
            env_key = f"{ENV_PREFIX}{section_field.name.upper()}_{f.name.upper()}"
            if env_key not in os.environ:
                continue
            raw = os.environ[env_key]
            current = getattr(section, f.name)
            try:
                if isinstance(current, bool):
                    coerced = raw.strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(current, int):
                    coerced = int(raw)
                elif isinstance(current, float):
                    coerced = float(raw)
                elif isinstance(current, (list, dict)):
                    coerced = json.loads(raw)
                else:
                    coerced = raw
            except (ValueError, json.JSONDecodeError):
                continue
            setattr(section, f.name, coerced)


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)  # JSON string escaping is valid TOML basic-string escaping
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        # Inline tables. Keeps per-model price overrides hand-editable:
        #   overrides = { "gpt-4o" = { input = 2.5, output = 10.0 } }
        parts = []
        for k, val in v.items():
            key = json.dumps(str(k))
            parts.append(f"{key} = {_toml_value(val)}")
        return "{ " + ", ".join(parts) + " }" if parts else "{}"
    raise TypeError(f"unsupported TOML value: {type(v)}")


def save(cfg: RegesConfig, path: Path | None = None) -> Path:
    """Hand-rolled TOML writer -- avoids a dependency for ~40 lines of output."""
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Reges configuration.",
        "# Hand-editable. Secrets are NOT stored here -- see `reges secrets`.",
        "",
        f"version = {cfg.version}",
    ]
    # Top-level scalars other than version were being dropped, which meant
    # setup_complete never persisted and the wizard reappeared every launch.
    for f in fields(cfg):
        if f.name == "version" or is_dataclass(getattr(cfg, f.name)):
            continue
        lines.append(f"{f.name} = {_toml_value(getattr(cfg, f.name))}")
    lines.append("")
    for section_field in fields(cfg):
        section = getattr(cfg, section_field.name)
        if not is_dataclass(section):
            continue
        lines.append(f"[{section_field.name}]")
        nested: list[tuple[str, dict]] = []
        for key, val in asdict(section).items():
            if isinstance(val, dict):
                nested.append((key, val))
                continue
            lines.append(f"{key} = {_toml_value(val)}")
        for key, table in nested:
            lines.append("")
            lines.append(f"[{section_field.name}.{key}]")
            for k, v in table.items():
                lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")

    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)  # atomic on the same volume; never leaves a half-written config
    return path


# --------------------------------------------------------------------------- #
# Secrets (DPAPI on Windows)
# --------------------------------------------------------------------------- #

class SecretStore:
    """Per-user encrypted key/value store.

    Windows: CryptProtectData / CryptUnprotectData via ctypes. Ciphertext is bound to
    the Windows user account -- copying the file to another machine or user yields
    nothing.

    Elsewhere: base64 in a 0600 file. That is obfuscation, not encryption, and
    `is_encrypted()` returns False so callers can warn.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_encrypted() -> bool:
        return sys.platform == "win32"

    # -- DPAPI ------------------------------------------------------------- #
    @staticmethod
    def _dpapi(data: bytes, unprotect: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        fn = crypt32.CryptUnprotectData if unprotect else crypt32.CryptProtectData
        args = ([ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)]
                if not unprotect else
                [ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)])
        if not fn(*args):
            raise OSError("DPAPI call failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _encode(self, plaintext: str) -> str:
        raw = plaintext.encode("utf-8")
        if self.is_encrypted():
            raw = self._dpapi(raw, unprotect=False)
        return base64.b64encode(raw).decode("ascii")

    def _decode(self, blob: str) -> str:
        raw = base64.b64decode(blob.encode("ascii"))
        if self.is_encrypted():
            raw = self._dpapi(raw, unprotect=True)
        return raw.decode("utf-8")

    # -- API --------------------------------------------------------------- #
    def _read_all(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_all(self, data: dict[str, str]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        if sys.platform != "win32":
            os.chmod(self.path, 0o600)

    def set(self, key: str, value: str) -> None:
        data = self._read_all()
        data[key] = self._encode(value)
        self._write_all(data)

    def get(self, key: str) -> str | None:
        blob = self._read_all().get(key)
        if blob is None:
            return None
        try:
            return self._decode(blob)
        except (OSError, ValueError):
            return None  # wrong user, corrupt store, or moved machine

    def delete(self, key: str) -> None:
        data = self._read_all()
        data.pop(key, None)
        self._write_all(data)

    def keys(self) -> list[str]:
        return sorted(self._read_all().keys())
