"""V/COMMAND alpha CLI. All functionality works with Python stdlib."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from . import __version__
from .core import (MODES, init_project, load_config, save_config, run_task,
                   read_evidence, render_evidence, list_evidence)


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
    run.add_argument("argv", nargs=argparse.REMAINDER)
    evidence = sub.add_parser("evidence", help="View evidence of a run")
    evidence.add_argument("id", nargs="?", default="last")
    evidence.add_argument("--json", action="store_true")
    sub.add_parser("cost", help="Report tracked and unknown provider costs")
    sub.add_parser("demo", help="Run a truthful, synthetic demo with real local checks")
    return p


def demo() -> int:
    # This exercise creates and checks a real local file. It is NOT an AI-agent demo.
    with tempfile.TemporaryDirectory(prefix="vcommand-demo-") as temp:
        root = Path(temp)
        init_project(root)
        cfg = load_config(root)
        cfg["checks"] = [[sys.executable, "-c", "from pathlib import Path; assert Path('output.txt').read_text() == 'ok\\n'"]]
        save_config(root, cfg)
        action = [sys.executable, "-c", "from pathlib import Path; Path('output.txt').write_text('ok\\n')"]
        result = run_task(root, action, demo=True)
        print(render_evidence(result))
        print("DEMO ONLY: synthetic fixture, real subprocess/check result, no AI model called.")
        return 0 if result["status"] == "verified_by_configured_checks" else 1


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    root = Path.cwd()
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
            return demo()
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
            item = run_task(root, command, timeout=args.timeout, check_timeout=args.check_timeout)
            print(render_evidence(item))
            return 0 if item["status"] in {"verified_by_configured_checks", "unverified"} else 1
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
    except (ValueError, FileNotFoundError, json.JSONDecodeError, PermissionError) as error:
        print(f"V/  Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
