"""Agent-mode CLI commands. Registered into the existing reges parser."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import cycle as cyclemod
from . import db, knowledge
from .paths import AgentPaths


def _paths(cfg) -> AgentPaths:
    p = AgentPaths(cfg)
    p.ensure()
    return p


def cmd_agent_install(cfg, args) -> int:
    """Install the agent-mode pack: contract, skills, knowledge."""
    p = _paths(cfg)
    src = Path(args.pack).expanduser()
    if not src.exists():
        print(f"pack not found: {src}", file=sys.stderr)
        return 2
    for d in ("skills", "knowledge"):
        s = src / d
        if s.exists():
            shutil.copytree(s, getattr(p, d), dirs_exist_ok=True)
    contract = src / "AGENT-MODE.md"
    if contract.exists():
        shutil.copy2(contract, p.contract)
    db.init(p.db)
    print(f"contract   {'installed' if p.contract.exists() else 'MISSING'}")
    print(f"knowledge  {len(knowledge.load_all(p.knowledge))} entries -> {p.knowledge}")
    print(f"database   {p.db}")
    return 0


def cmd_knowledge(cfg, args) -> int:
    p = _paths(cfg)
    rows = knowledge.status(p.knowledge)
    if not rows:
        print("no knowledge entries — run: reges agent install --pack <dir>")
        return 1
    width = max(len(r["title"]) for r in rows)
    for r in rows:
        flag = "STALE" if r["stale"] else f"{r['days_left']:>4}d left"
        print(f"{r['id']:<8} {r['title']:<{width}}  verified {r['verified_on']}  {flag}")
    stale = [r["id"] for r in rows if r["stale"]]
    if stale:
        print(f"\n{len(stale)} stale: {', '.join(stale)}")
        print("A stale entry is treated as ABSENT. Dependent actions will halt.")
    return 1 if stale else 0


def cmd_venture(cfg, args) -> int:
    p = _paths(cfg)
    db.init(p.db)

    if args.vcmd == "create":
        if not args.kill:
            print("refused: --kill is required. A venture with no kill criteria "
                  "is not an experiment.", file=sys.stderr)
            return 2
        try:
            v = db.create_venture(
                p.db, slug=args.slug, name=args.name or args.slug,
                niche=args.niche or "", autonomy=args.autonomy.upper(),
                budget_usd=args.budget, deadline=args.deadline or "",
                rails=args.rail or [], kill_criteria=args.kill)
        except Exception as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(v, indent=2))
        return 0

    if args.vcmd == "list":
        rows = db.list_ventures(p.db)
        if not rows:
            print("no ventures")
            return 0
        for v in rows:
            print(f"{v['slug']:<28} {v['state']:<12} {v['autonomy']:<3} "
                  f"warn={v['policy_warnings']}  {v['niche'] or ''}")
        return 0

    if args.vcmd == "state":
        try:
            v = db.set_state(p.db, args.slug, args.state.upper())
        except Exception as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"{v['slug']} -> {v['state']}")
        return 0

    return 2


def cmd_cycle(cfg, args, *, llm, skills) -> int:
    d = cyclemod.run(cfg, " ".join(args.task), role=args.role.upper(),
                     venture=args.venture, autonomy=args.autonomy.upper(),
                     llm=llm, skills=skills, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        print(f"[{d['decision']}] {d.get('reason','')}")
        if d.get("fields"):
            print(json.dumps(d["fields"], indent=2, ensure_ascii=False))
        for i in d.get("intents") or []:
            print(f"  intent {i.get('type')}  evidence={i.get('evidence')}")
    return 0 if d["decision"] in ("act", "split") else 1


def register(sub, cfg_loader, llm_loader, skills_loader) -> None:
    """Attach agent commands to the existing top-level subparser."""

    a = sub.add_parser("agent", help="agent mode — ventures, knowledge, cycles")
    asub = a.add_subparsers(dest="acmd", required=True)

    ai = asub.add_parser("install", help="install the agent-mode pack")
    ai.add_argument("--pack", required=True)
    ai.set_defaults(fn=lambda args: cmd_agent_install(cfg_loader(), args))

    ak = asub.add_parser("knowledge", help="knowledge freshness")
    ak.set_defaults(fn=lambda args: cmd_knowledge(cfg_loader(), args))

    ac = asub.add_parser("cycle", help="run one bounded cycle")
    ac.add_argument("task", nargs="+")
    ac.add_argument("--role", default="WORKER")
    ac.add_argument("--venture")
    ac.add_argument("--autonomy", default="L1")
    ac.add_argument("--dry-run", action="store_true")
    ac.add_argument("--json", action="store_true")
    ac.set_defaults(fn=lambda args: cmd_cycle(
        cfg_loader(), args, llm=llm_loader(), skills=skills_loader()))

    v = asub.add_parser("venture", help="venture registry")
    vsub = v.add_subparsers(dest="vcmd", required=True)

    vc = vsub.add_parser("create")
    vc.add_argument("slug")
    vc.add_argument("--name")
    vc.add_argument("--niche")
    vc.add_argument("--autonomy", default="L1")
    vc.add_argument("--budget", type=float, default=0.0)
    vc.add_argument("--deadline")
    vc.add_argument("--rail", action="append")
    vc.add_argument("--kill", action="append",
                    help="kill criterion — REQUIRED, repeatable")
    vc.set_defaults(fn=lambda args: cmd_venture(cfg_loader(), args))

    vl = vsub.add_parser("list")
    vl.set_defaults(fn=lambda args: cmd_venture(cfg_loader(), args))

    vs = vsub.add_parser("state")
    vs.add_argument("slug")
    vs.add_argument("state")
    vs.set_defaults(fn=lambda args: cmd_venture(cfg_loader(), args))
