"""The vault: markdown-on-disk memory.

Knowledge is markdown. Metrics are SQLite. Nothing else is a store.

Invariants the code enforces (not just documents):
  * raw/ is append-only. `capture()` refuses to overwrite; it suffixes instead.
  * every file carries YAML frontmatter with type/skill/created/tags/links
  * wikilinks stay [[bare]] so Obsidian indexes them with zero config
  * paths are clamped inside the vault root -- a skill cannot write to C:\\Windows
"""

from __future__ import annotations

import re
import sqlite3
import sqlite3 as _sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUBDIRS = (
    "raw",
    "wiki",
    "wiki/ventures",
    "wiki/market",
    "outputs",
    "outputs/drafts",
    "outputs/reports",
    "system",
    ".reges",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, maxlen: int = 60) -> str:
    s = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "untitled"


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    # -- lifecycle --------------------------------------------------------- #
    def scaffold(self) -> list[Path]:
        """Create the tree. Idempotent -- safe to run on an existing vault."""
        created = []
        for sub in SUBDIRS:
            p = self.root / sub
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                created.append(p)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(_VAULT_README, encoding="utf-8")
            created.append(readme)
        today = self.root / "system" / "today.md"
        if not today.exists():
            self.write("system/today.md", "# Today\n\n_Nothing planned yet._\n",
                       meta={"type": "system", "skill": "plan-today"})
            created.append(today)
        queue = self.root / "system" / "queue.md"
        if not queue.exists():
            self.write("system/queue.md", "# Queue\n\n_Empty._\n",
                       meta={"type": "system", "skill": "router"})
            created.append(queue)
        self._init_metrics_db()
        return created

    def _safe(self, relpath: str | Path) -> Path:
        p = (self.root / Path(relpath)).resolve()
        try:
            p.relative_to(self.root)
        except ValueError:
            raise VaultError(f"path escapes vault root: {relpath}")
        return p

    # -- write ------------------------------------------------------------- #
    def write(self, relpath: str, body: str, meta: dict[str, Any] | None = None,
              overwrite: bool = True) -> Path:
        p = self._safe(relpath)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not overwrite:
            raise VaultError(f"refusing to overwrite {relpath}")
        p.write_text(_frontmatter(meta or {}) + body.rstrip() + "\n", encoding="utf-8")
        return p

    def append(self, relpath: str, body: str) -> Path:
        p = self._safe(relpath)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n" + body.rstrip() + "\n")
        return p

    def capture(self, title: str, body: str, skill: str = "",
                tags: Iterable[str] = (), links: Iterable[str] = (),
                when: datetime | None = None) -> Path:
        """Append-only raw capture: raw/YYYY-MM-DD/HHMM-slug.md

        Never overwrites. A same-minute collision gets -2, -3, ... so two skills
        firing in the same minute cannot destroy each other's output.
        """
        when = when or datetime.now()
        day = when.strftime("%Y-%m-%d")
        stem = f"{when.strftime('%H%M')}-{slugify(title)}"
        folder = self._safe(f"raw/{day}")
        folder.mkdir(parents=True, exist_ok=True)

        candidate = folder / f"{stem}.md"
        n = 2
        while candidate.exists():
            candidate = folder / f"{stem}-{n}.md"
            n += 1

        meta = {
            "type": "capture",
            "skill": skill,
            "created": when.astimezone().isoformat(timespec="seconds"),
            "tags": list(tags),
            "links": list(links),
        }
        candidate.write_text(
            _frontmatter(meta) + f"# {title}\n\n" + body.rstrip() + "\n",
            encoding="utf-8",
        )
        return candidate

    def output(self, kind: str, title: str, body: str, skill: str = "") -> Path:
        """Something Reges produced for you to actually use. kind: drafts|reports"""
        if kind not in ("drafts", "reports"):
            raise VaultError(f"unknown output kind: {kind}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        rel = f"outputs/{kind}/{stamp}-{slugify(title)}.md"
        return self.write(rel, f"# {title}\n\n{body}", meta={
            "type": kind[:-1], "skill": skill,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        })

    # -- read / search ----------------------------------------------------- #
    def read(self, relpath: str) -> str:
        p = self._safe(relpath)
        if not p.exists():
            raise VaultError(f"not found: {relpath}")
        return p.read_text(encoding="utf-8")

    def search(self, needle: str, limit: int = 20,
               subdirs: Iterable[str] = ("wiki", "raw", "outputs", "system")) -> list[dict]:
        """Plain substring search. Deliberately not embeddings.

        If you can't grep it, it isn't memory. Semantic search over 200 notes is a
        solution to a problem you do not have yet; add it when grep actually fails.
        """
        needle_l = needle.lower()
        hits: list[dict] = []
        for sub in subdirs:
            base = self.root / sub
            if not base.exists():
                continue
            for p in sorted(base.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                idx = text.lower().find(needle_l)
                if idx < 0:
                    continue
                start = max(0, idx - 80)
                hits.append({
                    "path": str(p.relative_to(self.root)).replace("\\", "/"),
                    "excerpt": text[start:idx + 160].strip().replace("\n", " "),
                    "mtime": p.stat().st_mtime,
                })
                if len(hits) >= limit:
                    return hits
        return hits

    def recent(self, n: int = 10, sub: str = "raw") -> list[str]:
        base = self.root / sub
        if not base.exists():
            return []
        files = sorted(base.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [str(p.relative_to(self.root)).replace("\\", "/") for p in files[:n]]

    # -- metrics (SQLite; time-series only) -------------------------------- #
    def _db_path(self) -> Path:
        return self.root / ".reges" / "metrics.sqlite"

    def _init_metrics_db(self) -> None:
        self._db_path().parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id      INTEGER PRIMARY KEY,
                    ts      REAL    NOT NULL,
                    source  TEXT    NOT NULL,
                    key     TEXT    NOT NULL,
                    value   REAL    NOT NULL,
                    meta    TEXT
                )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_metrics_lookup ON metrics(source, key, ts)")
            db.commit()

    def record_metric(self, source: str, key: str, value: float,
                      meta: str = "", ts: float | None = None) -> None:
        self._init_metrics_db()
        with sqlite3.connect(self._db_path()) as db:
            db.execute(
                "INSERT INTO metrics (ts, source, key, value, meta) VALUES (?,?,?,?,?)",
                (ts or datetime.now(timezone.utc).timestamp(), source, key, float(value), meta),
            )
            db.commit()

    def metric_series(self, source: str, key: str, days: int = 28) -> list[tuple[float, float]]:
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        with sqlite3.connect(self._db_path()) as db:
            rows = db.execute(
                "SELECT ts, value FROM metrics WHERE source=? AND key=? AND ts>=? ORDER BY ts",
                (source, key, cutoff),
            ).fetchall()
        return [(float(t), float(v)) for t, v in rows]


def _frontmatter(meta: dict[str, Any]) -> str:
    if not meta:
        return ""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            if not v:
                continue
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            if v in ("", None):
                continue
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


_VAULT_README = """# Reges Vault

Plain markdown. No database for knowledge. Open it in Obsidian, VS Code, or Notepad.

- `raw/` --- every capture, timestamped, **append-only**. Reges never rewrites these.
- `wiki/` --- distilled knowledge. Yours to edit freely; Reges proposes, you approve.
- `outputs/` --- drafts and reports Reges produced for you to use.
- `system/` --- today.md, queue.md. Working state.
- `.reges/` --- metrics.sqlite (time-series only) and internal state. Don't hand-edit.

If it isn't in here, it didn't happen.
"""
