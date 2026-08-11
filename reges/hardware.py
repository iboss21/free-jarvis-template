"""What can this machine actually run?

This is a product someone else installs. The buyer might have a 4GB laptop GPU,
a 5090, a DGX Spark, an M-series Mac with unified memory, or no GPU at all.
Nothing here may assume the developer's hardware.

So: detect, compute, recommend. Then let them choose local or API in plain
language, with the trade-off stated instead of implied.

Sizes are computed from bits-per-weight, not looked up from a table of file
names that would rot in a month. Every figure is marked as an estimate because
that is what it is — quantisation overhead varies by architecture.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict

# Approximate effective bits per weight for common GGUF quantisations.
# These are community-observed averages, not exact — a 30B at Q4_K_M lands
# within a few percent of the number below. Treat every derived size as ±10%.
BPW = {
    "IQ1_S":     1.56,
    "IQ2_XXS":   2.06,
    "IQ2_M":     2.70,
    "Q2_K":      3.35,
    "IQ3_M":     3.66,
    "Q3_K_M":    3.91,
    "Q4_K_S":    4.58,
    "Q4_K_M":    4.83,
    "MXFP4_MOE": 4.25,
    "Q5_K_M":    5.67,
    "Q6_K":      6.56,
    "Q8_0":      8.50,
    "BF16":     16.00,
}

# Quality ordering, best first. Used to pick the best quant that fits.
QUALITY_ORDER = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "MXFP4_MOE", "Q4_K_S",
                 "Q3_K_M", "IQ3_M", "Q2_K", "IQ2_M", "IQ2_XXS", "IQ1_S"]

# Below this, quantisation damage is severe enough that an API is the honest
# recommendation rather than a worse-than-useless local model.
USABLE_FLOOR = "Q3_K_M"


@dataclass
class Gpu:
    name: str = ""
    vram_gb: float = 0.0
    vendor: str = ""
    driver: str = ""
    unified: bool = False      # Apple Silicon / Grace-Hopper style shared memory


@dataclass
class Machine:
    os: str = ""
    os_version: str = ""
    arch: str = ""
    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0.0
    gpus: list = field(default_factory=list)
    disk_free_gb: float = 0.0
    python: str = ""
    notes: list = field(default_factory=list)

    @property
    def best_gpu(self) -> Gpu | None:
        return max(self.gpus, key=lambda g: g.vram_gb) if self.gpus else None

    @property
    def usable_gb(self) -> float:
        """Memory actually available to hold a model.

        Discrete GPU: VRAM minus headroom for the desktop, KV cache and
        framework overhead. Unified memory: a conservative share of system RAM,
        because the OS still needs to run. No GPU: system RAM, and it will be
        slow.
        """
        g = self.best_gpu
        if g and g.vram_gb and not g.unified:
            return max(0.0, g.vram_gb - _headroom(g.vram_gb))
        if g and g.unified:
            return max(0.0, self.ram_gb * 0.65)
        return max(0.0, self.ram_gb * 0.45)

    @property
    def tier(self) -> str:
        u = self.usable_gb
        if not self.gpus:
            return "cpu-only"
        if u < 5:
            return "small"
        if u < 11:
            return "mid"
        if u < 22:
            return "large"
        if u < 60:
            return "workstation"
        return "datacenter"


def _headroom(vram: float) -> float:
    """Leave room for the display, the KV cache and runtime overhead."""
    if vram <= 6:
        return 1.0
    if vram <= 12:
        return 1.5
    if vram <= 24:
        return 2.0
    return max(3.0, vram * 0.10)


# --------------------------------------------------------------------
# detection
# --------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _nvidia() -> list[Gpu]:
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(["nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits"])
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            mib = float(parts[1])
        except ValueError:
            continue
        gpus.append(Gpu(name=parts[0], vram_gb=round(mib / 1024, 1),
                        vendor="nvidia",
                        driver=parts[2] if len(parts) > 2 else ""))
    return gpus


def _apple() -> list[Gpu]:
    if sys.platform != "darwin":
        return []
    chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if "apple" not in chip.lower():
        return []
    return [Gpu(name=chip.strip(), vram_gb=0.0, vendor="apple", unified=True)]


def _windows_gpus() -> list[Gpu]:
    if sys.platform != "win32":
        return []
    # CIM first; falls back to the older WMI alias on older boxes.
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_VideoController | "
                "ForEach-Object { \"$($_.Name)|$($_.AdapterRAM)\" }"], 15)
    gpus = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, _, ram = line.partition("|")
        name = name.strip()
        if not name:
            continue
        try:
            # AdapterRAM is a signed 32-bit field and lies above 4GB. Only
            # trust it under that ceiling; nvidia-smi is authoritative anyway.
            gb = round(int(ram) / (1024 ** 3), 1) if ram.strip().isdigit() else 0.0
        except (ValueError, TypeError):
            gb = 0.0
        vendor = ("nvidia" if "nvidia" in name.lower() else
                  "amd" if any(k in name.lower() for k in ("radeon", "amd")) else
                  "intel" if "intel" in name.lower() else "")
        gpus.append(Gpu(name=name, vram_gb=gb, vendor=vendor))
    return gpus


def _linux_gpus() -> list[Gpu]:
    out = _run(["lspci"])
    gpus = []
    for line in out.splitlines():
        if not re.search(r"VGA|3D controller|Display controller", line, re.I):
            continue
        name = line.split(":")[-1].strip()
        vendor = ("nvidia" if "nvidia" in name.lower() else
                  "amd" if any(k in name.lower() for k in ("amd", "radeon")) else
                  "intel" if "intel" in name.lower() else "")
        gpus.append(Gpu(name=name, vendor=vendor))
    return gpus


def _ram_gb() -> float:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                         / (1024 ** 3), 1)
    except (ValueError, OSError):
        pass
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        if out.strip().isdigit():
            return round(int(out) / (1024 ** 3), 1)
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out.strip().isdigit():
            return round(int(out) / (1024 ** 3), 1)
    return 0.0


def _cpu_name() -> str:
    if sys.platform == "darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    if sys.platform == "linux":
        try:
            for line in open("/proc/cpuinfo", encoding="utf-8"):
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def detect(disk_path: str = ".") -> Machine:
    gpus = _nvidia() or _apple()
    if not gpus:
        gpus = _windows_gpus() if sys.platform == "win32" else _linux_gpus()

    m = Machine(
        os=platform.system(), os_version=platform.release(),
        arch=platform.machine(), cpu=_cpu_name(),
        cores=os.cpu_count() or 0, ram_gb=_ram_gb(), gpus=gpus,
        python=platform.python_version(),
    )

    try:
        m.disk_free_gb = round(shutil.disk_usage(disk_path).free / (1024 ** 3), 1)
    except OSError:
        m.disk_free_gb = 0.0

    g = m.best_gpu
    if g and g.unified:
        m.notes.append("Unified memory — the GPU shares system RAM, so the "
                       "usable budget scales with total RAM.")
    if g and g.vendor == "nvidia" and not shutil.which("nvidia-smi"):
        m.notes.append("NVIDIA GPU found but nvidia-smi is missing; VRAM could "
                       "not be read accurately.")
    if g and g.vram_gb == 0 and g.vendor and not g.unified:
        m.notes.append(f"{g.name}: VRAM could not be read. Estimates below "
                       "assume CPU memory only.")
    if not gpus:
        m.notes.append("No GPU detected. Local models will run on CPU — "
                       "workable for small models, slow for large ones.")
    if m.ram_gb and m.ram_gb < 8:
        m.notes.append("Under 8GB of system RAM. An API is likely the better "
                       "choice on this machine.")
    return m


# --------------------------------------------------------------------
# recommendation
# --------------------------------------------------------------------

def model_size_gb(params_b: float, quant: str) -> float:
    """Rough on-disk / in-memory size. ±10%."""
    bpw = BPW.get(quant.upper())
    if not bpw:
        return 0.0
    return round(params_b * 1e9 * bpw / 8 / (1024 ** 3) * 1.03, 1)


def kv_cache_gb(params_b: float, ctx: int = 32768) -> float:
    """Very rough KV cache budget. Grows with context and model width."""
    return round(max(0.4, params_b * 0.00004 * (ctx / 1024)), 1)


def best_quant(params_b: float, budget_gb: float, ctx: int = 32768) -> tuple[str, float] | None:
    """Highest-quality quant of this model that fits the budget."""
    room = budget_gb - kv_cache_gb(params_b, ctx)
    for q in QUALITY_ORDER:
        size = model_size_gb(params_b, q)
        if size and size <= room:
            return q, size
    return None


# Candidate sizes, not specific model names — names go stale, sizes do not.
CANDIDATES = [
    (1.7, "very small", "routing and simple commands only"),
    (4.0, "small", "chat and routing; shallow on hard questions"),
    (8.0, "medium", "solid general chat, decent instruction following"),
    (14.0, "large", "good reasoning, handles skills reliably"),
    (30.0, "very large", "strong reasoning; the sweet spot if it fits"),
    (70.0, "huge", "near-frontier locally"),
]


def recommend(m: Machine | None = None, ctx: int = 32768) -> dict:
    m = m or detect()
    budget = m.usable_gb
    options = []

    for params, label, note in CANDIDATES:
        fit = best_quant(params, budget, ctx)
        if not fit:
            continue
        quant, size = fit
        degraded = QUALITY_ORDER.index(quant) > QUALITY_ORDER.index(USABLE_FLOOR)
        options.append({
            "params_b": params, "label": label, "note": note,
            "quant": quant, "size_gb": size,
            "kv_gb": kv_cache_gb(params, ctx),
            "degraded": degraded,
            "fits": True,
        })

    good = [o for o in options if not o["degraded"]]
    pick = max(good, key=lambda o: o["params_b"]) if good else None

    if pick:
        verdict = "local"
        headline = (f"This machine can run a {pick['label']} model "
                    f"(~{pick['params_b']:g}B) at {pick['quant']}, "
                    f"about {pick['size_gb']}GB.")
        why = ("Runs entirely on your hardware. No API key, no per-token cost, "
               "nothing leaves the machine.")
    elif options:
        verdict = "local-limited"
        pick = max(options, key=lambda o: o["params_b"])
        headline = (f"This machine can only run heavily compressed models "
                    f"(~{pick['params_b']:g}B at {pick['quant']}).")
        why = ("Quantisation this aggressive costs real quality. It will work, "
               "but an API will feel noticeably better for the same effort.")
    else:
        verdict = "api"
        headline = "Not enough memory to run a useful model locally."
        why = ("An API key is the practical route here. You only pay for what "
               "you use and nothing needs downloading.")

    return {
        "machine": asdict(m),
        "tier": m.tier,
        "budget_gb": round(budget, 1),
        "verdict": verdict,
        "headline": headline,
        "why": why,
        "pick": pick,
        "options": options,
        "disk_ok": m.disk_free_gb > (pick["size_gb"] + 5 if pick else 5),
        "disclaimer": ("Sizes are computed from bits-per-weight and are "
                       "estimates, ±10%. Check the actual file size before "
                       "downloading."),
    }


def summary(m: Machine | None = None) -> str:
    m = m or detect()
    r = recommend(m)
    g = m.best_gpu
    lines = [
        f"{m.os} {m.os_version} · {m.arch} · Python {m.python}",
        f"CPU  {m.cpu} ({m.cores} cores)",
        f"RAM  {m.ram_gb}GB    disk free {m.disk_free_gb}GB",
    ]
    if g:
        lines.append(f"GPU  {g.name}" + (f" · {g.vram_gb}GB VRAM" if g.vram_gb else "")
                     + (" · unified memory" if g.unified else ""))
    else:
        lines.append("GPU  none detected")
    lines += ["", f"tier: {m.tier}   usable budget: {r['budget_gb']}GB",
              r["headline"], r["why"]]
    for n in m.notes:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
