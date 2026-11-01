"""V/COMMAND alpha CLI. All functionality works with Python stdlib."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from . import __version__
from .core import (project_root, MODES, init_project, load_config, save_config, run_task,
                   read_evidence, render_evidence, list_evidence)
from .state import (start_task, load_task, complete_step, set_next_step, clear_task, set_focus,
                    add_ledger_entry, read_ledger, record_run_failure, build_frame, render_frame)
from .isolation import IsolationError
from .demo import run_demo
from .adapters import (run_agents, run_hook, install_hooks, uninstall_hooks, agent_templates, HOOK_TARGETS,
                       load_health, open_circuits)


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
    focus = task_sub.add_parser("focus", help="Files or file:Symbol the task is about (code slice in the frame)")
    focus.add_argument("specs", nargs="*", help="e.g. src/auth.ts:AuthService.login src/util.py")
    focus.add_argument("--clear", action="store_true")
    task_sub.add_parser("clear", help="Remove the current task")
    ledger = sub.add_parser("ledger", help="Negative knowledge: approaches that already failed")
    ledger_sub = ledger.add_subparsers(dest="ledger_action", required=True)
    ledger_add = ledger_sub.add_parser("add", help="Record a failed approach")
    ledger_add.add_argument("--tried", required=True, help="What was attempted")
    ledger_add.add_argument("--why", required=True, help="Why it failed (error, failing test, reason)")
    ledger_add.add_argument("--constraint", help="Rule for the next agent (default derived from --tried/--why)")
    ledger_add.add_argument("--agent", help="Agent/model that made the attempt")
    ledger_add.add_argument("--pattern", help="Literal code the stream guard must refuse in later edits, e.g. 'jwt.destroy('")
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
    agent.add_argument("--race", action="store_true",
                       help="Start all agents at once in separate worktrees; first verified wins, others are killed")
    agent.add_argument("--budget", type=float, help="Stop when known provider-reported spend on this task reaches USD")
    agent.add_argument("--health", action="store_true", help="Show agent circuit-breaker state")
    agent.add_argument("--reset-health", action="store_true", help="Close all agent circuits")
    bench = sub.add_parser("bench", help="Benchmark arms (agent:plain vs agent:frame) on a task suite")
    bench.add_argument("suite", help="Suite directory containing suite.json")
    bench.add_argument("--arm", action="append", default=[], help="<agent>:plain or <agent>:frame (repeatable)")
    bench.add_argument("--repeats", type=int, default=1)
    bench.add_argument("--task", action="append", help="Only these task ids (repeatable)")
    bench.add_argument("--timeout", type=int, default=1800)
    bench.add_argument("--out", help="Results directory (default .vcommand/bench/<run>)")
    bench.add_argument("--handoff", action="append", default=[],
                       help="A>B: A tries first (plain); on failure B continues with plain vs frame briefing")
    bench.add_argument("--jobs", type=int, default=1, help="Runs in parallel")
    bench.add_argument("--limit", type=int, help="Only the first N tasks")
    hooks = sub.add_parser("hooks", help="Install or remove agent hooks (Claude Code, Codex CLI)")
    hooks.add_argument("action", choices=["install", "uninstall"])
    hooks.add_argument("target", choices=HOOK_TARGETS)
    hooks.add_argument("--settings", help="Hook file (default: .claude/settings.json or .codex/hooks.json)")
    hook = sub.add_parser("hook", help="Hook entry point called by the agent (reads JSON on stdin)")
    hook.add_argument("target", choices=HOOK_TARGETS)
    hook.add_argument("event", choices=["session-start", "stop"])
    queue = sub.add_parser("queue", help="Overnight task queue: verified tasks are committed, questions wait for you")
    queue_sub = queue.add_subparsers(dest="queue_action", required=True)
    q_add = queue_sub.add_parser("add", help="Add a task")
    q_add.add_argument("goal")
    q_add.add_argument("--focus", action="append", default=[], help="file or file:Symbol (repeatable)")
    q_add.add_argument("--gate", action="append", default=[], help="Extra gate command for this task (repeatable)")
    q_add.add_argument("--after", action="append", default=[], help="Run only after this task id is done")
    q_add.add_argument("--priority", type=int, default=0)
    queue_sub.add_parser("list", help="Show queue state (same as report)")
    queue_sub.add_parser("report", help="Morning report: committed, failed, waiting for decisions")
    q_run = queue_sub.add_parser("run", help="Process the queue with the given agents (isolated attempts)")
    q_run.add_argument("agents", nargs="+")
    q_run.add_argument("--attempts", type=int)
    q_run.add_argument("--max-tasks", type=int)
    q_run.add_argument("--until", help="Do not start new tasks after HH:MM (local time)")
    q_run.add_argument("--budget", type=float, help="Per-task budget in USD (known provider-reported spend)")
    q_run.add_argument("--timeout", type=int, default=3600)
    q_run.add_argument("--jobs", type=int, default=1, help="Tasks in parallel (focus files are locked)")
    q_ans = queue_sub.add_parser("answer", help="Answer a frozen task's question; it returns to the queue")
    q_ans.add_argument("id")
    q_ans.add_argument("text")
    ask_p = sub.add_parser("ask", help="(for agents) freeze the current queue task with a question for the developer")
    ask_p.add_argument("question")
    ask_p.add_argument("--option", action="append", default=[])
    hw = sub.add_parser("hw", help="Hardware probe and local backup model recommendation")
    hw.add_argument("--json", action="store_true")
    hw.add_argument("--add-agent", metavar="NAME", help="Register a local agent (Codex --oss + Ollama) in config")
    hw.add_argument("--model", help="Model tag for --add-agent (default: the recommendation)")
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
        if args.command == "queue":
            from . import queue as q
            if args.queue_action == "add":
                import shlex
                gates = [shlex.split(g, posix=os.name != "nt") for g in args.gate]
                t = q.add_task(root, args.goal, focus=args.focus, gates=gates, after=args.after,
                               priority=args.priority)
                print(f"V/  Queued {t['id']}: {t['goal']}")
                return 0
            if args.queue_action in {"list", "report"}:
                print(q.render_report(q.load_queue(root)))
                return 0
            if args.queue_action == "answer":
                t = q.answer(root, args.id, args.text)
                print(f"V/  {t['id']} back in the queue with your decision")
                return 0
            return q.run_queue(root, args.agents, attempts=args.attempts, max_tasks=args.max_tasks,
                               until=args.until, budget_usd=args.budget, timeout=args.timeout, jobs=args.jobs)
        if args.command == "ask":
            from . import queue as q
            task_id = q.current_queue_task()
            if not task_id:
                raise ValueError("vcmd ask works inside a queue run (VCOMMAND_QUEUE_TASK is not set)")
            q.ask(q.current_queue_root(root), task_id, args.question, args.option)
            print(f"V/  Task {task_id} frozen until the developer answers. Stop working on it now.")
            return 0
        if args.command == "hw":
            from .hw import probe, recommend, render, local_agent_template
            info = probe(root)
            rec = recommend(info)
            if args.add_agent:
                model = args.model or (rec["model"] or {}).get("tag")
                if not model:
                    raise ValueError("No local model fits this machine; pass --model <ollama tag> to override")
                cfg = load_config(root)
                cfg.setdefault("agents", {})[args.add_agent] = local_agent_template(model)
                save_config(root, cfg)
                print(f"V/  Agent '{args.add_agent}' -> codex --oss with Ollama model {model}")
                print(f"V/  Use it as fallback: vcmd agent claude {args.add_agent}")
                if not rec["installed"] or args.model:
                    print(f"V/  Make sure the model is available: ollama pull {model}")
                return 0
            print(json.dumps({"hardware": info, "recommendation": rec}, indent=2) if args.json else render(info, rec))
            return 0
        if args.command == "bench":
            from .bench import run_bench
            if args.repeats < 1 or args.timeout < 1:
                raise ValueError("--repeats and --timeout must be positive")
            summary = run_bench(Path(args.suite), args.arm, repeats=args.repeats, timeout=args.timeout,
                                out_dir=Path(args.out) if args.out else None, project_root=root,
                                tasks_filter=args.task, jobs=args.jobs, handoffs=args.handoff, limit=args.limit)
            from .bench import render_report
            print("\n" + render_report(summary))
            print(f"V/  Results: {summary['dir']}")
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
                for name, spec in sorted(agent_templates(cfg).items()):
                    print(f"{name:12} {' '.join(spec['argv'])}" + (f"   [parser: {spec['cost']}]" if spec["cost"] else ""))
                return 0
            if args.reset_health:
                (root / ".vcommand" / "agent_health.json").unlink(missing_ok=True)
                print("V/  All agent circuits closed")
                return 0
            if args.health:
                health, opened = load_health(root), open_circuits(root)
                if not health:
                    print("V/  No provider failures recorded")
                for name, h in sorted(health.items()):
                    state = "OPEN (skipped)" if name in opened else "closed (cooldown over)"
                    print(f"{name:12} {state:24} failures in a row: {h['consecutive_failures']}  last: {h['last_reason']}")
                return 0
            if args.timeout < 1 or args.check_timeout < 1:
                raise ValueError("Timeout must be a positive number of seconds")
            if args.race:
                from .adapters import run_race
                return run_race(root, args.agents, instruction=args.instruction, timeout=args.timeout,
                                check_timeout=args.check_timeout, budget_usd=args.budget)
            return run_agents(root, args.agents, attempts=args.attempts, instruction=args.instruction,
                              timeout=args.timeout, check_timeout=args.check_timeout, isolate=args.isolate,
                              budget_usd=args.budget)
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
            elif args.task_action == "focus":
                if not args.specs and not args.clear:
                    raise ValueError("Use: vcmd task focus src/file.ts:Symbol [...]  or  --clear")
                t = set_focus(root, [] if args.clear else args.specs)
                print(f"V/  Focus: {', '.join(t['focus']) or 'cleared'}")
                if t["focus"]:
                    from .slice import build_slice
                    sl = build_slice(root, t["focus"])
                    print(f"V/  Slice: {len(sl['symbols'])} item(s), {len(sl['references'])} reference(s)"
                          + (f"; problems: {'; '.join(sl['problems'])}" if sl["problems"] else ""))
            else:
                t = load_task(root)
                if t is None:
                    print('V/  No active task. Use: vcmd task start "<goal>"')
                else:
                    print(f"V/  Task {t['id']}: {t['goal']}")
                    for i, step in enumerate(t["completed_steps"], 1):
                        print(f"  {i}. [done] {step['step']}")
                    print(f"  next: {t.get('next_step') or 'not set'}")
                    if t.get("focus"):
                        print(f"  focus: {', '.join(t['focus'])}")
            return 0
        if args.command == "ledger":
            if args.ledger_action == "add":
                e = add_ledger_entry(root, tried=args.tried, failure=args.why,
                                     constraint=args.constraint, agent=args.agent, pattern=args.pattern)
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
