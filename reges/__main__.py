"""Reges CLI.

    reges setup                  run the install wizard
    reges start                  launch the HUD + agent
    reges say "plan my day"      send one intent, print the answer, exit
    reges doctor                 check the live config against reality
    reges budget [--reset]       show or clear the session token meter
    reges secrets set <key>      store a key (prompted, never in argv)
    reges agent install --pack   install contract + skills + knowledge
    reges agent knowledge        knowledge freshness (exit 1 if anything stale)
    reges agent venture ...      venture registry
    reges agent cycle "..."      run one bounded cycle
"""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import config as cfg_mod
from .config import SecretStore
from .llm import LLM, LLMError
from .router import load_skills, route
from .state import BUS, BudgetExceeded, State
from .vault import Vault
from .agent import cli as agent_cli


def _secrets(cfg) -> SecretStore:
    return SecretStore(cfg_mod.default_config_path().parent / "secrets.json")


# --------------------------------------------------------------------------- #
# The agent loop
# --------------------------------------------------------------------------- #

CHAT_TURNS = 12   # how much conversation the chat fallback carries


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.vault = Vault(cfg.paths.vault_dir)
        self.secrets = _secrets(cfg)
        self.llm = LLM(cfg, self.secrets)
        self.skills = load_skills(cfg)
        self.history: list[tuple[str, str]] = []   # [(user, assistant), ...]

    def handle(self, intent: str) -> str:
        try:
            r = route(intent, self.skills, self.llm, self.cfg)
            if not r.ok:
                # No skill matched. That is not an error — it is a conversation.
                # An assistant that can only answer in eight fixed shapes is a
                # menu, not an assistant.
                BUS.log("router", "chat")
                return self.chat(intent)

            skill = self.skills[r.skill]
            with BUS.during(State.WORKING, skill.name):
                answer = self.llm.reason(
                    system=(
                        f"You are Reges, a personal automation agent.\n"
                        f"You are executing the skill below. Follow it exactly.\n"
                        f"Be terse. No preamble. State what you did, not what you are about to do.\n"
                        f"If a rule in the skill says do not do something, that rule wins.\n\n"
                        f"--- SKILL: {skill.name} ---\n{skill.body}"
                    ),
                    user=intent,
                )
                self.vault.capture(
                    title=intent[:70], body=answer, skill=skill.name,
                    tags=["intent"], links=[],
                )
            return answer

        except BudgetExceeded as e:
            BUS.error(str(e))
            return f"Stopped: {e}"
        except LLMError as e:
            BUS.error(str(e))
            return f"Model error: {e}"

    # -- chat ---------------------------------------------------------- #
    def chat(self, message: str) -> str:
        """Plain conversation. Used when nothing routes, or on demand."""
        skills = ", ".join(self.skills) or "none"
        system = (
            "You are Reges, a local automation agent running on the user's own "
            "machine. You are talking, not executing a skill.\n"
            "Be brief and direct. No preamble, no bullet lists unless asked.\n"
            "You may answer normally about anything.\n"
            "If the user asks for something one of your skills covers, say which "
            "one and that they can just ask for it.\n"
            f"Skills available: {skills}"
        )
        convo = []
        for u, a in self.history[-CHAT_TURNS:]:
            convo.append(f"User: {u}")
            convo.append(f"Reges: {a}")
        convo.append(f"User: {message}")
        convo.append("Reges:")

        with BUS.during(State.THINKING, "chat"):
            answer = (self.llm.reason(system=system, user="\n".join(convo)) or "").strip()

        if not answer:
            answer = ("No answer came back from the model. Check Settings — "
                      "base URL, model id, and TEST CONNECTION.")

        self.history.append((message, answer))
        if len(self.history) > CHAT_TURNS * 2:
            self.history = self.history[-CHAT_TURNS:]
        return answer


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_setup(_args) -> int:
    wizard = Path(__file__).resolve().parent.parent / "install" / "wizard.py"
    return subprocess.call([sys.executable, str(wizard)])


def cmd_start(args) -> int:
    from .server import serve

    cfg = cfg_mod.load()
    if not cfg.paths.vault_dir:
        print("No config found. Run: reges setup")
        return 2

    agent = Agent(cfg)
    httpd = serve(cfg, agent.handle)

    url = f"http://{cfg.server.host}:{cfg.server.port}"
    print(f"REGES running — {url}")
    print(f"vault  {cfg.paths.vault_dir}")
    print(f"skills {', '.join(agent.skills) or 'none'}")
    print("ctrl-c to stop\n")

    if cfg.server.open_hud_on_start and not args.no_browser:
        webbrowser.open(url)

    if cfg.voice.enabled:
        try:
            from .voice.ptt import start_ptt
            start_ptt(cfg, agent.handle)
        except Exception as e:
            BUS.log("warn", f"voice unavailable: {e}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
        httpd.shutdown()
    return 0


def cmd_say(args) -> int:
    cfg = cfg_mod.load()
    agent = Agent(cfg)
    print(agent.handle(" ".join(args.text)))
    t = BUS.snapshot()["tokens"]
    print(f"\n[{t['total']:,} tok  ${t['usd']:.4f}]", file=sys.stderr)
    return 0


def cmd_doctor(_args) -> int:
    from install.wizard import probe_openai_endpoint  # type: ignore

    cfg_path = cfg_mod.default_config_path()
    print(f"config   {cfg_path}  {'ok' if cfg_path.exists() else 'MISSING — run: reges setup'}")
    if not cfg_path.exists():
        return 2

    cfg = cfg_mod.load()
    problems = 0

    vault = Path(cfg.paths.vault_dir)
    if vault.exists():
        print(f"vault    {vault}  ok")
    else:
        print(f"vault    {vault}  MISSING")
        problems += 1

    alive, ids, err = probe_openai_endpoint(cfg.models.local_base_url, timeout=4)
    if alive:
        has = cfg.models.local_model in ids
        print(f"local    {cfg.models.local_base_url}  ok ({len(ids)} models)")
        if not has:
            print(f"         model '{cfg.models.local_model}' NOT loaded — routing will fail")
            problems += 1
    else:
        print(f"local    {cfg.models.local_base_url}  UNREACHABLE ({err})")
        problems += 1

    store = _secrets(cfg)
    keys = store.keys()
    print(f"secrets  {len(keys)} stored "
          f"({'DPAPI' if store.is_encrypted() else 'obfuscated only — not encrypted'})")
    if cfg.models.remote_enabled and "anthropic_api_key" not in keys:
        print("         remote enabled but no api key — reasoning will fall back to local")
        problems += 1

    skills = load_skills(cfg)
    missing = set(cfg.skills.enabled) - set(skills)
    print(f"skills   {len(skills)} loaded" + (f", MISSING: {', '.join(sorted(missing))}" if missing else ""))
    problems += len(missing)

    print(f"\n{'no problems' if not problems else f'{problems} problem(s)'}")
    return 0 if not problems else 1


def cmd_budget(args) -> int:
    cfg = cfg_mod.load()
    BUS.configure(session_cap=cfg.budgets.session_token_cap,
                  price_in=cfg.budgets.price_in_per_mtok,
                  price_out=cfg.budgets.price_out_per_mtok,
                  on_cap=cfg.budgets.on_cap)
    if args.reset:
        BUS.reset_budget()
        print("session meter reset")
        return 0
    t = BUS.snapshot()["tokens"]
    print(f"tokens  {t['total']:,} / {t['cap']:,}  ({t['pct']}%)")
    print(f"cost    ${t['usd']:.4f} this session")
    print(f"calls   {t['calls']}")
    print(f"on cap  {cfg.budgets.on_cap}")
    return 0


def cmd_secrets(args) -> int:
    cfg = cfg_mod.load()
    store = _secrets(cfg)
    if args.action == "list":
        for k in store.keys():
            print(k)
        if not store.is_encrypted():
            print("\nWARNING: not on Windows — these are obfuscated, not encrypted.",
                  file=sys.stderr)
        return 0
    if args.action == "set":
        val = getpass.getpass(f"{args.key}: ")   # never through argv; shell history is forever
        if not val:
            print("empty — nothing stored")
            return 1
        store.set(args.key, val)
        print(f"stored {args.key}")
        return 0
    if args.action == "delete":
        store.delete(args.key)
        print(f"deleted {args.key}")
        return 0
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="reges", description="Reges — AI automation agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="run the install wizard").set_defaults(fn=cmd_setup)

    p = sub.add_parser("start", help="launch the HUD and agent")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("say", help="send one intent and print the answer")
    p.add_argument("text", nargs="+")
    p.set_defaults(fn=cmd_say)

    sub.add_parser("doctor", help="check config against reality").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("budget", help="show or reset the token meter")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(fn=cmd_budget)

    p = sub.add_parser("secrets", help="manage stored keys")
    p.add_argument("action", choices=["list", "set", "delete"])
    p.add_argument("key", nargs="?", default="")
    p.set_defaults(fn=cmd_secrets)

    agent_cli.register(
        sub,
        cfg_loader=lambda: cfg_mod.load(),
        llm_loader=lambda: LLM(cfg_mod.load(), _secrets(cfg_mod.load())),
        skills_loader=lambda: load_skills(cfg_mod.load()),
    )

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
