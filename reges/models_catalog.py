"""Model catalog.

Every entry here was checked against the live repo listing — filenames and
sizes are real, not guessed. If a file is not in this table, Reges does not
offer to download it.

The point of this module is that a newcomer should never have to know what
"UD-Q4_K_XL" means. They pick their graphics card; the catalog picks the file.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field

HF = "https://huggingface.co"


@dataclass
class Quant:
    file: str
    gb: float
    min_vram_gb: float       # comfortable full-GPU residency
    label: str
    note: str = ""
    preferred: bool = False

    def url(self, repo: str) -> str:
        return f"{HF}/{repo}/resolve/main/{self.file}"


@dataclass
class Model:
    id: str
    name: str
    repo: str
    role: str                # "reasoning" | "router" | "both"
    params: str
    license: str
    blurb: str
    quants: list[Quant] = field(default_factory=list)
    extras: list[Quant] = field(default_factory=list)
    featured: bool = False
    homepage: str = ""


REGESCORE = Model(
    id="regescore-35b",
    name="RegesCore 1.0 35B",
    repo="iBossonline/RegesCore-1.0-35",
    role="reasoning",
    params="35B MoE",
    license="MIT",
    featured=True,
    homepage=f"{HF}/iBossonline/RegesCore-1.0-35",
    blurb=("The recommended brain for a high-end consumer GPU. Mixture-of-experts, "
           "so it runs far faster than its size suggests — only a fraction of the "
           "parameters fire per token. Vision-capable with the projector below."),
    quants=[
        Quant("RegesCore-1.0-35B-UD-IQ1_S.gguf", 10.5, 12,
              "IQ1_S — smallest", "Fits a 12GB card entirely. Lowest quality of the set."),
        Quant("RegesCore-1.0-35B-UD-IQ1_M.gguf", 11.0, 12,
              "IQ1_M", "12GB card, a step up from IQ1_S."),
        Quant("RegesCore-1.0-35B-UD-IQ2_M.gguf", 11.6, 12,
              "IQ2_M", "Best quality that still fits 12GB with a short context."),
        Quant("RegesCore-1.0-35B-UD-Q2_K_XL.gguf", 12.3, 16, "Q2_K_XL", ""),
        Quant("RegesCore-1.0-35B-UD-IQ3_XXS.gguf", 13.7, 16, "IQ3_XXS", ""),
        Quant("RegesCore-1.0-35B-UD-IQ3_S.gguf", 15.0, 16, "IQ3_S", ""),
        Quant("RegesCore-1.0-35B-UD-Q3_K_M.gguf", 16.7, 20, "Q3_K_M", ""),
        Quant("RegesCore-1.0-35B-UD-IQ4_XS.gguf", 17.8, 20, "IQ4_XS", ""),
        Quant("RegesCore-1.0-35B-UD-IQ4_NL.gguf", 18.1, 20, "IQ4_NL", ""),
        Quant("RegesCore-1.0-35B-UD-Q4_K_S.gguf", 20.9, 24, "Q4_K_S", ""),
        Quant("RegesCore-1.0-35B-MXFP4_MOE.gguf", 21.7, 24,
              "MXFP4_MOE — recommended",
              "The build tuned for this MoE. Best quality-per-GB.", preferred=True),
        Quant("RegesCore-1.0-35B-UD-Q4_K_M.gguf", 22.1, 24, "Q4_K_M", ""),
        Quant("RegesCore-1.0-35B-UD-Q4_K_XL.gguf", 22.3, 24, "Q4_K_XL", ""),
        Quant("RegesCore-1.0-35B-UD-Q5_K_S.gguf", 24.9, 32, "Q5_K_S", ""),
        Quant("RegesCore-1.0-35B-UD-Q5_K_M.gguf", 26.5, 32, "Q5_K_M", ""),
        Quant("RegesCore-1.0-35B-UD-Q5_K_XL.gguf", 26.5, 32, "Q5_K_XL", ""),
        Quant("RegesCore-1.0-35B-UD-Q6_K.gguf", 29.3, 32, "Q6_K", ""),
        Quant("RegesCore-1.0-35B-UD-Q6_K_XL.gguf", 31.8, 40, "Q6_K_XL", ""),
        Quant("RegesCore-1.0-35B-Q8_0.gguf", 36.9, 48, "Q8_0", "Near-lossless."),
        Quant("RegesCore-1.0-35B-UD-Q8_K_XL.gguf", 38.2, 48, "Q8_K_XL", "Near-lossless, XL tensors."),
    ],
    extras=[
        Quant("mmproj-F16.gguf", 0.9, 0, "Vision projector (F16)",
              "Optional. Needed only if you want the model to see images."),
        Quant("mmproj-BF16.gguf", 0.9, 0, "Vision projector (BF16)", "Optional."),
        Quant("mmproj-F32.gguf", 1.8, 0, "Vision projector (F32)", "Optional, highest precision."),
    ],
)

CATALOG: list[Model] = [REGESCORE]


# --------------------------------------------------------------------
# hardware
# --------------------------------------------------------------------

GPU_TIERS = [
    ("48+ GB", 48, "Workstation class. Run Q8 and never think about it again."),
    ("32 GB",  32, "Q5/Q6 fully resident."),
    ("24 GB",  24, "MXFP4_MOE or Q4_K_M fully resident. The sweet spot."),
    ("20 GB",  20, "IQ4 range fits."),
    ("16 GB",  16, "IQ3 range fits; IQ4 with CPU offload."),
    ("12 GB",  12, "IQ1/IQ2 fit. Larger quants work with CPU offload and more RAM."),
    ("8 GB",    8, "35B needs heavy offload here. Consider an API instead."),
    ("None / CPU only", 0, "Local 35B will be slow. An API key is the better path."),
]


def detect_gpu() -> dict:
    """Best-effort, never raises. nvidia-smi is the only reliable cross-check."""
    out = {"name": "", "vram_gb": 0.0, "source": "none"}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            r = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=12)
            line = (r.stdout or "").strip().splitlines()
            if line:
                name, mem = [x.strip() for x in line[0].split(",")[:2]]
                out.update(name=name, vram_gb=round(float(mem) / 1024, 1), source="nvidia-smi")
                return out
        except Exception:
            pass
    try:
        import ctranslate2  # type: ignore
        if ctranslate2.get_cuda_device_count() > 0:
            out.update(name="CUDA device", source="ctranslate2")
    except Exception:
        pass
    return out


def recommend(vram_gb: float, model: Model = REGESCORE) -> dict:
    """Pick the best quant that fits, and say plainly when nothing does."""
    if vram_gb <= 0:
        return {
            "quant": None,
            "why": ("No GPU detected. A 35B model on CPU is measured in seconds "
                    "per word, not words per second. Connect an API provider "
                    "instead, or run a small model for routing only."),
            "fits": False,
        }

    # Leave headroom for the KV cache and the desktop compositor.
    budget = vram_gb - 1.5
    fitting = [q for q in model.quants if q.gb <= budget]
    if fitting:
        # A hand-tuned build beats a marginally larger generic one. Only fall
        # back to "biggest that fits" when the preferred build does not.
        preferred = [q for q in fitting if q.preferred]
        best = preferred[0] if preferred else max(fitting, key=lambda q: q.gb)
        return {
            "quant": best.file,
            "label": best.label,
            "gb": best.gb,
            "fits": True,
            "why": (f"{best.gb} GB fits in {vram_gb} GB with room for context. "
                    f"{best.note}").strip(),
        }

    smallest = min(model.quants, key=lambda q: q.gb)
    return {
        "quant": smallest.file,
        "label": smallest.label,
        "gb": smallest.gb,
        "fits": False,
        "why": (f"Nothing fits {vram_gb} GB entirely. The smallest build is "
                f"{smallest.gb} GB and will need CPU offload — it works, it is "
                f"just slower. System RAM matters more than the card here."),
    }


def listing() -> list[dict]:
    return [{
        "id": m.id, "name": m.name, "repo": m.repo, "role": m.role,
        "params": m.params, "license": m.license, "blurb": m.blurb,
        "featured": m.featured, "homepage": m.homepage,
        "quants": [{"file": q.file, "gb": q.gb, "label": q.label,
                    "note": q.note, "min_vram_gb": q.min_vram_gb,
                    "preferred": q.preferred,
                    "url": q.url(m.repo)} for q in m.quants],
        "extras": [{"file": q.file, "gb": q.gb, "label": q.label,
                    "note": q.note, "url": q.url(m.repo)} for q in m.extras],
    } for m in CATALOG]


def find_quant(file: str) -> tuple[Model, Quant] | tuple[None, None]:
    for m in CATALOG:
        for q in list(m.quants) + list(m.extras):
            if q.file == file:
                return m, q
    return None, None
