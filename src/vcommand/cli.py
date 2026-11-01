"""V/COMMAND alpha CLI. All functionality works with Python stdlib."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from . import __version__
from .core import (project_root, MODES, init_project, load_config, save_config, run_task,
                   read_evidence, render_evidence, list_evidence)
from .state import (start_task, load_task, complete_step, set_next_step, clear_task,
                    add_ledger_entry, read_ledger, record_run_failure, build_frame, render_frame)
from .isolation import IsolationError
from .demo import run_demo
from .adapters import run_agents, run_hook, install_hooks, uninstall_hooks, agent_templates, HOOK_TARGETS


def tokens(args: list[str]) -> list[str]:
    return args[1:] if args and args[0] == "--" else args


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vcmd", description="V/COMMAND | Run. Check. Prove.")
    p.add_argument("--version", action="version", version=f"V/COMMAND {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize local project settings")
    sub.add_parser("doctor", help="Check local environment")
    mode = sub.add_parser("mode", help="View or save strategy preference (no routing yet)")
    mode.add_argument("value", nargs="?", choices=MODES)
    checks = sub.add_parser("check", help="Manage verification commands")
    check_sub = checks.add_subparsers(dest="check_action", required=True)
    check_add = check_sub.add_parser("add", help="Add verification command as argv")
    check_add.add_argument("argv", nargs=argparse.REMAINDER)
    check_sub.add_parser("list", help="List checks")
    check_sub.add_parser("clear", help="Remove all checks")
    run = sub.add_parser("run", help="Execute a command and independently verify it")
    run.add_argument("--timeout", type=int, default=600, help="Command timeout in seconds")
    run.add_argument("--check-timeout", type=int, default=120, help="Each check timeout in seconds")
    run.add_argument("--agent", help="Name of the agent/model doing the work (recorded in evidence and ledger)")
    run.add_argument("--note", help="What this attempt tries; recorded in the ledger if it fails")
    run.add_argument("argv", nargs=argparse.REMAINDER)
    task = sub.add_parser("task", help="Task checkpoint kept outside any model session")
    task_sub = task.add_subparsers(dest="task_action", required=True)
    task_sub.add_parser("start", help="Start a new task (replaces the current one)").add_argument("goal")
    task_sub.add_parser("done", help="Record a completed step").add_argument("step")
    task_sub.add_parser("next", help="Set the next step to hand over").add_argument("step")
    task_sub.add_parser("show", help="Show the current task")
    task_sub.add_parser("clear", help="Remove the current task")
    ledger = sub.add_parser("ledger", help="Negative knowledge: approaches that already failed")
    ledger_sub = ledger.add_subparsers(dest="ledger_action", required=True)
    ledger_add = ledger_sub.add_parser("add", help="Record a failed approach")
    ledger_add.add_argument("--tried", required=True, help="What was attempted")
    ledger_add.add_argument("--why", required=True, help="Why it failed (error, failing test, reason)")
    ledger_add.add_argument("--constraint", help="Rule for the next agent (default derived from --tried/--why)")
    ledger_add.add_argument("--agent", help="Agent/model that made the attempt")
    ledger_sub.add_parser("list", help="List recorded failed approaches")
    frame = sub.add_parser("frame", help="Compile a context frame to hand the task to any agent/model")
    frame.add_argument("--json", action="store_true", help="Machine-readable frame")
    frame.add_argument("--out", help="Write to this file instead of stdout")
    evidence = sub.add_parser("evidence", help="View evidence of a run")
    evidence.add_argument("id", nargs="?", default="last")
    evidence.add_argument("--json", action="store_true")
    agent = sub.add_parser("agent", help="Run agents with the context frame; hand off to the next on failed gates")
    agent.add_argument("agents", nargs="*", help="Agents in order, e.g. `codex claude` (cycled for --attempts)")
    agent.add_argument("--attempts", type=int, help="Total attempts (default: one per listed agent)")
    agent.add_argument("--instruction", help="Extra instruction added above the context frame")
    agent.add_argument("--timeout", type=int, default=3600, help="Per-attempt agent timeout in seconds")
    agent.add_argument("--check-timeout", type=int, default=600, help="Each check timeout in seconds")
    agent.add_argument("--list", action="store_true", help="Show configured agent command templates")
    agent.add_argument("--isolate", action="store_true",
                       help="Run each attempt in a fresh git worktree; apply changes only when gates pass")
    hooks = sub.add_parser("hooks", help="Install or remove agent hooks (Claude Code, Codex CLI)")
    hooks.add_argument("action", choices=["install", "uninstall"])
    hooks.add_argument("target", choices=HOOK_TARGETS)
    hooks.add_argument("--settings", help="Hook file (default: .claude/settings.json or .codex/hooks.json)")
    hook = sub.add_parser("hook", help="Hook entry point called by the agent (reads JSON on stdin)")
    hook.add_argument("target", choices=HOOK_TARGETS)
    hook.add_argument("event", choices=["session-start", "stop"])
    sub.add_parser("cost", help="Report tracked and unknown provider costs")
    demo = sub.add_parser("demo", help="Done isn't verified: scripted agents, real checks, ledger and handoff")
    demo.add_argument("--fast", action="store_true", help="No pauses (for CI and recordings)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    root = project_root()
    try:
        if args.command == "init":
            created = init_project(root)
            print("V/  Initialized .vcommand/config.json" if created else "V/  Already initialized. No files overwritten.")
            return 0
        if args.command == "doctor":
            print(f"V/  Python       {sys.version.split()[0]}")
            print(f"V/  Git          {shutil.which('git') or 'not found'}")
            print(f"V/  Repository   {root}")
            print(f"V/  Configuration {'present' if (root/'.vcommand'/'config.json').exists() else 'missing (vcmd init)'}")
            print("V/  Network isolation and model-provider integration are not implemented.")
            return 0
        if args.command == "demo":
            return run_demo(fast=args.fast)
        if args.command == "hook":
            # Never break the agent session because of V/COMMAND: report and exit 0.
            try:
                return run_hook(args.target, args.event, sys.stdin, sys.stdout, sys.stderr)
            except Exception as error:  # noqa: BLE001 - hooks must fail open
                print(f"V/  hook error: {type(error).__name__}: {error}", file=sys.stderr)
                return 0
        if args.command == "hooks":
            settings = Path(args.settings) if args.settings else None
            name = {"claude": "Claude Code", "codex": "Codex"}[args.target]
            if args.action == "install":
                path, changed = install_hooks(root, args.target, settings)
                print(f"V/  {name} hooks {'added: ' + ', '.join(changed) if changed else 'already installed'} ({path})")
                print(f"V/  SessionStart injects the context frame; Stop runs your checks before {name} may finish.")
                print(f"V/  Requires `vcmd` on PATH for {name}. Remove with: vcmd hooks uninstall {args.target}")
                if args.target == "codex":
                    print("V/  Codex runs project hooks only after you trust them: open `codex`, run /hooks, trust both.")
            else:
                path, changed = uninstall_hooks(root, args.target, settings)
                print(f"V/  Removed: {', '.join(changed)} ({path})" if changed else "V/  No V/COMMAND hooks found")
            return 0
        cfg = load_config(root)
        if args.command == "mode":
            if args.value:
                cfg["mode"] = args.value
                save_config(root, cfg)
            print(f"V/  Mode: {cfg['mode']} (preference only; not yet model routing / offline enforcement)")
            return 0
        if args.command == "check":
            if args.check_action == "add":
                command = tokens(args.argv)
                if not command:
                    raise ValueError("Use: vcmd check add -- python -m unittest discover -s tests")
                cfg["checks"].append(command)
                save_config(root, cfg)
                print(f"V/  Added verification command: {' '.join(command)}")
            elif args.check_action == "clear":
                cfg["checks"].clear()
                save_config(root, cfg)
                print("V/  Cleared verification commands")
            elif args.check_action == "list":
                for index, command in enumerate(cfg["checks"], 1):
                    print(f"{index}. {' '.join(command)}")
                if not cfg["checks"]:
                    print("V/  No verification commands configured")
            return 0
        if args.command == "run":
            command = tokens(args.argv)
            if not command:
                raise ValueError("Use: vcmd run -- python my_agent.py")
            if args.timeout < 1 or args.check_timeout < 1:
                raise ValueError("Timeout must be a positive number of seconds")
            item = run_task(root, command, timeout=args.timeout, check_timeout=args.check_timeout, agent=args.agent)
            print(render_evidence(item))
            entry = record_run_failure(root, item, agent=args.agent, note=args.note)
            if entry:
                print(f"V/  LEDGER     recorded failed approach {entry['id']} (next agents will see it in `vcmd frame`)")
            return 0 if item["status"] in {"verified_by_configured_checks", "unverified"} else 1
        if args.command == "agent":
            if args.list:
                for name, argv in sorted(agent_templates(cfg).items()):
                    print(f"{name:8} {' '.join(argv)}")
                return 0
            if args.timeout < 1 or args.check_timeout < 1:
                raise ValueError("Timeout must be a positive number of seconds")
            return run_agents(root, args.agents, attempts=args.attempts, instruction=args.instruction,
                              timeout=args.timeout, check_timeout=args.check_timeout, isolate=args.isolate)
        if args.command == "task":
            if args.task_action == "start":
                t = start_task(root, args.goal)
                print(f"V/  Task {t['id']} started: {t['goal']}")
            elif args.task_action == "done":
                t = complete_step(root, args.step)
                print(f"V/  Step recorded ({len(t['completed_steps'])} done)")
            elif args.task_action == "next":
                set_next_step(root, args.step)
                print(f"V/  Next step set: {args.step}")
            elif args.task_action == "clear":
                print("V/  Task cleared" if clear_task(root) else "V/  No active task")
            else:
                t = load_task(root)
                if t is None:
                    print('V/  No active task. Use: vcmd task start "<goal>"')
                else:
                    print(f"V/  Task {t['id']}: {t['goal']}")
                    for i, step in enumerate(t["completed_steps"], 1):
                        print(f"  {i}. [done] {step['step']}")
                    print(f"  next: {t.get('next_step') or 'not set'}")
            return 0
        if args.command == "ledger":
            if args.ledger_action == "add":
                e = add_ledger_entry(root, tried=args.tried, failure=args.why,
                                     constraint=args.constraint, agent=args.agent)
                print(f"V/  Recorded {e['id']}: {e['constraint']}")
            else:
                entries = read_ledger(root)
                if not entries:
                    print("V/  No failed approaches recorded")
                for e in entries:
                    who = f" [{e['agent']}]" if e.get("agent") else ""
                    print(f"{e['id']}  {e['created_at_utc']}{who}\n  tried:   {e['tried']}\n  failed:  {e['failure']}")
            return 0
        if args.command == "frame":
            data = build_frame(root)
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n" if args.json else render_frame(data)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(f"V/  Frame written to {args.out} ({data['continuity_token'][:23]})")
            else:
                print(text, end="")
            return 0
        if args.command == "evidence":
            item = read_evidence(root, args.id)
            print(json.dumps(item, indent=2, ensure_ascii=False) if args.json else render_evidence(item))
            return 0
        if args.command == "cost":
            items = list_evidence(root)
            tracked = [i for i in items if i.get("cost", {}).get("amount") is not None]
            usd = sum(float(i["cost"]["amount"]) for i in tracked if i["cost"]["currency"] == "USD")
            print(f"V/  Runs: {len(items)} | known USD costs: ${usd:.4f} | unknown costs: {len(items)-len(tracked)}")
            print("V/  No provider integration in alpha; unknown is not zero.")
            return 0
        return 2
    except (ValueError, FileNotFoundError, json.JSONDecodeError, PermissionError, IsolationError) as error:
        print(f"V/  Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
