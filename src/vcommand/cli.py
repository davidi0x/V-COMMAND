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
from .state import (start_task, load_task, complete_step, set_next_step, clear_task, set_focus, set_brief,
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
    t_start = task_sub.add_parser("start", help="Start a new task with its operating brief (replaces the current one)")
    t_start.add_argument("goal")
    t_brief = task_sub.add_parser("brief", help="Set operating-brief fields of the current task")
    for tp in (t_start, t_brief):
        tp.add_argument("--scope", help="What is in scope (and implicitly what is not)")
        tp.add_argument("--constraint", action="append", default=[], help="Hard rule for every agent (repeatable)")
        tp.add_argument("--done", help="Done condition, e.g. 'tests pass and /login returns 200'")
        tp.add_argument("--leave-behind", help="What every session must leave (default: handoff.md + evidence)")
    t_brief.add_argument("--clear-constraints", action="store_true")
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
    decide = sub.add_parser("decide", help="Record a decision in .vcommand/decisions.md (append-only)")
    decide.add_argument("text")
    decide.add_argument("--why", help="Reason")
    decide.add_argument("--agent", help="Who decided (default: VCOMMAND agent env or 'developer')")
    sub.add_parser("decisions", help="List recorded decisions")
    todo = sub.add_parser("todo", help="Open items for the next session (.vcommand/todo.md)")
    todo_sub = todo.add_subparsers(dest="todo_action", required=True)
    todo_add = todo_sub.add_parser("add", help="Add an item")
    todo_add.add_argument("text")
    todo_add.add_argument("--owner", help="Who should do it (session, agent or person)")
    todo_sub.add_parser("done", help="Close an item by number or unique text").add_argument("ref")
    todo_sub.add_parser("list", help="List items")
    handoff = sub.add_parser("handoff", help="5-line handoff: goal, state, files touched, open issues, next step")
    handoff.add_argument("--write", action="store_true", help="Rewrite .vcommand/handoff.md now (checkpoint)")
    handoff.add_argument("--out", help="Also write it to this file (e.g. handoff.md in the repo)")
    approve = sub.add_parser("approve", help="Approve or deny risky commands agents asked to run (deploy, DB write, bulk delete)")
    approve.add_argument("id", nargs="?", help="Approval id (apr-…); omit or 'list' to list")
    approve.add_argument("--deny", action="store_true")
    approve.add_argument("--all", action="store_true", help="With list: include decided requests")
    guard = sub.add_parser("guard", help="Check how the guardrails classify a shell command")
    guard.add_argument("shell", nargs=argparse.REMAINDER, metavar="command")
    loop = sub.add_parser("loop", help="Role loop: plan -> build/test (gates) -> review -> handoff")
    loop.add_argument("--plan", help="Planner agent (default: config roles.plan; 'none' to skip)")
    loop.add_argument("--build", action="append", default=[], help="Builder agent(s), in failover order")
    loop.add_argument("--review", help="Reviewer agent (default: config roles.review; 'none' to skip)")
    loop.add_argument("--rounds", type=int, help="Build/review rounds (default: config roles.rounds or 2)")
    loop.add_argument("--attempts", type=int, help="Build attempts per round (default: one per builder)")
    loop.add_argument("--timeout", type=int, default=3600)
    loop.add_argument("--check-timeout", type=int, default=600)
    loop.add_argument("--budget", type=float)
    wake = sub.add_parser("wake", help="Trigger entry point (cron/CI/webhook): continue queue or active task")
    wake.add_argument("agents", nargs="*", help="Agents (default: config wake.agents or roles.build)")
    wake.add_argument("--loop", action="store_true", help="Continue the active task with the role loop")
    wake.add_argument("--max-tasks", type=int)
    wake.add_argument("--until", help="Do not start new queue tasks after HH:MM")
    wake.add_argument("--budget", type=float)
    wake.add_argument("--timeout", type=int, default=3600)
    wake.add_argument("--jobs", type=int, default=1)
    sched = sub.add_parser("schedule", help="Print a trigger that runs `vcmd wake` (cron, systemd, GitHub Actions)")
    sched.add_argument("kind", choices=["cron", "systemd", "github"])
    sched.add_argument("agents", nargs="*")
    sched.add_argument("--at", default="02:00", help="HH:MM (GitHub: UTC)")
    sched.add_argument("--loop", action="store_true")
    sched.add_argument("--write", action="store_true", help="github: write .github/workflows/vcommand-wake.yml")
    mi = sub.add_parser("mission", help="Say the goal once: plan, cost range, who-does-what sliders, approve, run")
    mi_sub = mi.add_subparsers(dest="mi_action")
    mi_new = mi_sub.add_parser("new", help="Draft a mission from one sentence (the enhancer writes brief, questions, steps)")
    mi_new.add_argument("goal")
    mi_new.add_argument("--agents", nargs="+", help="Agents that may work on it (default: from vcmd roles)")
    mi_new.add_argument("--enhance", metavar="AGENT", help="Agent that drafts the brief (default: roles.plan)")
    mi_new.add_argument("--no-enhance", action="store_true", help="Skip the enhancer: the goal becomes one step")
    mi_new.add_argument("--timeout", type=int, default=600)
    mi_sub.add_parser("show", help="The plan, estimates and sliders (default)")
    mi_ag = mi_sub.add_parser("agents", help="Choose the agents")
    mi_ag.add_argument("names", nargs="+")
    mi_sh = mi_sub.add_parser("share", help="Sliders: share of the work per agent, e.g. claude=60 codex=40")
    mi_sh.add_argument("pairs", nargs="+", metavar="agent=PERCENT")
    mi_pin = mi_sub.add_parser("pin", help="Force a step onto an agent (or --clear)")
    mi_pin.add_argument("step", type=int)
    mi_pin.add_argument("agent", nargs="?")
    mi_bu = mi_sub.add_parser("budget", help="Hard stop in USD (all agents, or one with --agent)")
    mi_bu.add_argument("usd", type=float)
    mi_bu.add_argument("--agent")
    mi_bu.add_argument("--clear", action="store_true")
    mi_an = mi_sub.add_parser("answer", help="Answer an enhancer question")
    mi_an.add_argument("n", type=int)
    mi_an.add_argument("text")
    mi_ed = mi_sub.add_parser("edit", help="Edit a step")
    mi_ed.add_argument("step", type=int)
    mi_ed.add_argument("--title")
    mi_ed.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    mi_ed.add_argument("--detail")
    mi_ap = mi_sub.add_parser("approve", help="Approve the plan; nothing runs before this")
    mi_ap.add_argument("--skip-questions", action="store_true")
    mi_run = mi_sub.add_parser("run", help="Run the approved mission step by step")
    mi_run.add_argument("--attempts", type=int, default=2)
    mi_run.add_argument("--timeout", type=int, default=3600)
    mi_run.add_argument("--review", action="store_true", help="Ask roles.review for a verdict at the end")
    mi_sub.add_parser("report", help="Estimate vs actual")
    mi_sub.add_parser("discard", help="Drop the current mission")
    wt = sub.add_parser("worktree", help="One git worktree per live session (parallel work without collisions)")
    wt_sub = wt.add_subparsers(dest="wt_action", required=True)
    wt_new = wt_sub.add_parser("new", help="Create ../<repo>-<name> on branch vcmd/<name> with its own state and hooks")
    wt_new.add_argument("name")
    wt_new.add_argument("--branch")
    wt_new.add_argument("--base", help="Start point (default HEAD)")
    wt_new.add_argument("--path")
    wt_new.add_argument("--goal", help="Start this task in the worktree")
    wt_sub.add_parser("list", help="Worktrees, branches and changed files")
    wt_sub.add_parser("conflicts", help="Files changed in more than one worktree")
    wt_rm = wt_sub.add_parser("rm", help="Remove a worktree (refuses with uncommitted changes)")
    wt_rm.add_argument("name")
    wt_rm.add_argument("--force", action="store_true")
    sub.add_parser("sessions", help="Live agent sessions registered by the hooks")
    msg = sub.add_parser("msg", help="Short messages between live sessions (and to the developer's channels)")
    msg_sub = msg.add_subparsers(dest="msg_action", required=True)
    msg_send = msg_sub.add_parser("send", help="Send to a session name, 'all', or 'developer' (your channels)")
    msg_send.add_argument("to")
    msg_send.add_argument("text")
    msg_send.add_argument("--from", dest="sender", help="Sender name (default: this session)")
    msg_sub.add_parser("list", help="Recent messages")
    ch = sub.add_parser("channel", help="Notification channels: telegram, slack, ntfy, webhook")
    ch_sub = ch.add_subparsers(dest="ch_action", required=True)
    ch_add = ch_sub.add_parser("add", help="Add a channel")
    ch_add.add_argument("type", choices=["telegram", "slack", "ntfy", "webhook"])
    ch_add.add_argument("--chat", help="telegram: chat id allowed to receive and send commands")
    ch_add.add_argument("--topic", help="ntfy: topic (min 12 chars, acts as a password)")
    ch_add.add_argument("--server", help="ntfy: server (default https://ntfy.sh)")
    ch_add.add_argument("--secret", help="Secret name holding the token / webhook URL")
    ch_add.add_argument("--event", action="append", default=[], help="Only these events (repeatable)")
    ch_sub.add_parser("list", help="Configured channels")
    ch_sub.add_parser("test", help="Send a test message to every channel")
    ch_rm = ch_sub.add_parser("rm", help="Remove channel #N")
    ch_rm.add_argument("index", type=int)
    conn = sub.add_parser("connect", help="Bring your own: connect YOUR Telegram bot, Slack, ntfy topic or webhook")
    conn_sub = conn.add_subparsers(dest="conn_kind", required=True)
    c_tg = conn_sub.add_parser("telegram", help="Your bot from @BotFather (token is read hidden, stored as a secret)")
    c_tg.add_argument("--chat", help="Chat id (default: read from the last message you sent the bot)")
    conn_sub.add_parser("slack", help="Your Slack incoming webhook URL (read hidden)")
    c_nt = conn_sub.add_parser("ntfy", help="Your ntfy topic (ntfy.sh or your own server)")
    c_nt.add_argument("topic", nargs="?", help="Topic name (default: a random one)")
    c_nt.add_argument("--server")
    c_wh = conn_sub.add_parser("webhook", help="Any HTTPS endpoint (Discord, Teams, n8n, your service)")
    c_wh.add_argument("name", help="Secret name for the URL, e.g. MY_HOOK_URL")
    c_ag = conn_sub.add_parser("agent", help="Register any CLI agent with its own API key and base URL")
    c_ag.add_argument("name")
    c_ag.add_argument("--key", help="Secret name for its API key (value read hidden if not yet stored)")
    c_ag.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="Plain variable, e.g. BASE_URL=…")
    c_ag.add_argument("--parser", choices=["claude-json", "claude-stream", "codex-jsonl"])
    c_ag.add_argument("argv", nargs="*", help="-- command with {prompt}")
    remote = sub.add_parser("remote", help="Steer V/COMMAND from your phone (Telegram bot, long polling)")
    remote.add_argument("kind", choices=["telegram"])
    remote.add_argument("--once", action="store_true", help="Process pending commands and exit")
    auto = sub.add_parser("autopilot", help="Keep working: vcmd wake every N minutes (+ Telegram remote)")
    auto.add_argument("agents", nargs="*")
    auto.add_argument("--every", default="30m", help="Interval, e.g. 30m, 2h (default 30m)")
    auto.add_argument("--loop", action="store_true", help="Use the role loop for the active task")
    auto.add_argument("--remote", action="store_true", help="Also answer Telegram commands")
    auto.add_argument("--cycles", type=int, help="Stop after N cycles")
    auto.add_argument("--budget", type=float)
    auto.add_argument("--timeout", type=int, default=3600)
    roles = sub.add_parser("roles", help="Which agent plays which role (plan, build, review, hard, chore, ...)")
    roles_sub = roles.add_subparsers(dest="roles_action")
    roles_set = roles_sub.add_parser("set", help="Assign agent(s) to a role")
    roles_set.add_argument("role")
    roles_set.add_argument("agents", nargs="+")
    roles_rm = roles_sub.add_parser("rm", help="Remove a role")
    roles_rm.add_argument("role")
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
    agent.add_argument("--role", help="Use the agents configured for this role (vcmd roles)")
    sess = agent.add_mutually_exclusive_group()
    sess.add_argument("--continue", dest="resume_last", action="store_true",
                      help="Continue the agent's last session (full context) instead of a fresh one")
    sess.add_argument("--resume", metavar="SESSION_ID", help="Continue this agent session id")
    sess.add_argument("--fork", nargs="?", const="", metavar="SESSION_ID",
                      help="Branch from the last (or given) session without changing it (Claude Code)")
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
    bench.add_argument("--resume", help="Results directory of an earlier run: re-run only infra errors and missing runs")
    hooks = sub.add_parser("hooks", help="Install or remove agent hooks (Claude Code, Codex CLI)")
    hooks.add_argument("action", choices=["install", "uninstall"])
    hooks.add_argument("target", choices=HOOK_TARGETS)
    hooks.add_argument("--settings", help="Hook file (default: .claude/settings.json or .codex/hooks.json)")
    hook = sub.add_parser("hook", help="Hook entry point called by the agent (reads JSON on stdin)")
    hook.add_argument("target", choices=HOOK_TARGETS)
    hook.add_argument("event", choices=["session-start", "stop", "pre-tool", "pre-compact", "post-tool", "prompt",
                                        "session-end"])
    queue = sub.add_parser("queue", help="Overnight task queue: verified tasks are committed, questions wait for you")
    queue_sub = queue.add_subparsers(dest="queue_action", required=True)
    q_add = queue_sub.add_parser("add", help="Add a task")
    q_add.add_argument("goal")
    q_add.add_argument("--focus", action="append", default=[], help="file or file:Symbol (repeatable)")
    q_add.add_argument("--gate", action="append", default=[], help="Extra gate command for this task (repeatable)")
    q_add.add_argument("--after", action="append", default=[], help="Run only after this task id is done")
    q_add.add_argument("--priority", type=int, default=0)
    q_add.add_argument("--role", help="Run with the agents of this role (e.g. hard -> strongest model, chore -> cheapest)")
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
    dash = sub.add_parser("dashboard", help="Local web dashboard: runs, costs, ledger, queue, benchmarks, API keys")
    dash.add_argument("--port", type=int, default=0, help="Port on 127.0.0.1 (default: random free port)")
    dash.add_argument("--no-open", action="store_true", help="Do not open a browser")
    dash.add_argument("--background", action="store_true", help="Run detached and print the URL (used by /dashboard)")
    dash.add_argument("--stop", action="store_true", help="Stop a background dashboard")
    wsp = sub.add_parser("workspace", help="Local workspace: real terminals (Claude Code, Codex, shell), files, editor, git changes")
    wsp.add_argument("--port", type=int, default=0, help="Port on 127.0.0.1 (default: random free port)")
    wsp.add_argument("--no-open", action="store_true", help="Do not open a browser")
    dash.add_argument("--install-command", action="store_true", help="Add /dashboard to Claude Code (.claude/commands)")
    sec = sub.add_parser("secret", help="Store API keys as secrets (OS keychain / DPAPI / secret-tool / 0600 file)")
    sec_sub = sec.add_subparsers(dest="secret_action", required=True)
    sec_set = sec_sub.add_parser("set", help="Store a key (value read without echo)")
    sec_set.add_argument("name")
    sec_sub.add_parser("list", help="List stored key names (values masked)")
    sec_rm = sec_sub.add_parser("rm", help="Delete a key")
    sec_rm.add_argument("name")
    sub.add_parser("cost", help="Report tracked and unknown provider costs")
    demo = sub.add_parser("demo", help="Done isn't verified: scripted agents, real checks, ledger and handoff")
    demo.add_argument("--fast", action="store_true", help="No pauses (for CI and recordings)")
    return p


def _workflow_command(args, root: Path, cfg: dict) -> int:
    from . import workflow as w
    if args.command == "decide":
        agent = args.agent or os.environ.get("VCOMMAND_AGENT") or ("agent" if os.environ.get("VCOMMAND_WRAPPED")
                                                                   else "developer")
        print(f"V/  Decision recorded: {w.add_decision(root, args.text, why=args.why, agent=agent)[2:]}")
        return 0
    if args.command == "decisions":
        items = w.read_decisions(root)
        print("\n".join(f"- {d}" for d in items) if items else "V/  No decisions recorded (vcmd decide \"…\")")
        return 0
    if args.command == "todo":
        if args.todo_action == "add":
            item = w.add_todo(root, args.text + (f" (owner: {args.owner})" if args.owner else ""))
            print(f"V/  To-do {item['n']}: {item['text']}")
        elif args.todo_action == "done":
            item = w.complete_todo(root, args.ref)
            print(f"V/  Done: {item['text']}")
        else:
            items = w.read_todos(root)
            for i in items:
                print(f"{i['n']:3}. [{'x' if i['done'] else ' '}] {i['text']}")
            if not items:
                print("V/  No to-dos")
        return 0
    if args.command == "handoff":
        if args.write or args.out:
            path = w.write_handoff(root)
            text = path.read_text(encoding="utf-8")
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(f"V/  Handoff written: {path}" + (f" and {args.out}" if args.out else ""))
            return 0
        print(w.render_handoff(w.build_handoff(root)), end="")
        return 0
    if args.command == "approve":
        if args.id in {None, "list"}:
            items = w.list_approvals(root) if args.all else w.pending_approvals(root)
            if not items:
                print("V/  No pending approvals" if not args.all else "V/  No approval requests")
            for a in items:
                print(f"{a['id']}  {a['status']:8} {a['rule']:12} {a.get('agent') or '-':12} {a['command'][:100]}"
                      + (f"   (queue task {a['queue_task']})" if a.get("queue_task") else ""))
            if items and not args.all:
                print("V/  Approve: vcmd approve <id>   Deny: vcmd approve <id> --deny")
            return 0
        a = w.decide_approval(root, args.id, approve=not args.deny)
        if a["status"] == "approved":
            print(f"V/  Approved {a['id']} for 24 h: `{a['command'][:160]}` (exactly this command)")
        else:
            print(f"V/  Denied {a['id']}")
        if a.get("queue_task"):
            print(f"V/  Queue task {a['queue_task']} is back in the queue with your decision")
        return 0
    if args.command == "guard":
        command = " ".join(tokens(args.shell))
        if not command:
            raise ValueError("Use: vcmd guard -- <shell command>")
        rule = w.classify_command(cfg, command)
        if rule is None:
            print("V/  allowed: no guardrail matches")
        else:
            print(f"V/  needs approval: {rule}" + (" (already approved)" if w.is_approved(root, command) else ""))
        return 0
    roles = cfg.get("roles") or {}
    if args.command == "loop":
        plan = args.plan if args.plan is not None else roles.get("plan")
        review = args.review if args.review is not None else roles.get("review")
        return w.run_loop(root, plan=None if plan == "none" else plan, build=args.build or w._as_list(roles.get("build")),
                          review=None if review == "none" else review,
                          rounds=args.rounds or int(roles.get("rounds", 2)), attempts=args.attempts,
                          timeout=args.timeout, check_timeout=args.check_timeout, budget_usd=args.budget)
    return w.run_wake(root, args.agents, use_loop=args.loop, max_tasks=args.max_tasks, until=args.until,
                      budget_usd=args.budget, timeout=args.timeout, jobs=args.jobs)


def _mission_command(args, root: Path, cfg: dict) -> int:
    from . import mission as mi
    act = args.mi_action or "show"
    if act == "new":
        roles = cfg.get("roles") or {}
        enhancer = None if args.no_enhance else (args.enhance or (roles.get("plan") if isinstance(roles.get("plan"), str) else None))
        if not enhancer and not args.no_enhance:
            print("V/  No enhancer agent (--enhance <agent> or vcmd roles set plan <agent>): the goal becomes one step.")
        m = mi.new_mission(root, args.goal, agents=args.agents, enhancer=enhancer, timeout=args.timeout)
        print("\n" + mi.render_view(mi.view(root, m)))
        return 0
    if act == "agents":
        mi.set_agents(root, args.names)
    elif act == "share":
        shares = {}
        for pair in args.pairs:
            name, sep, val = pair.partition("=")
            if not sep or not val.strip().isdigit():
                raise ValueError("Use agent=PERCENT, e.g. claude=60 codex=40")
            shares[name] = int(val)
        mi.set_shares(root, shares)
    elif act == "pin":
        mi.pin_step(root, args.step, args.agent)
    elif act == "budget":
        mi.set_budget(root, None if args.clear else args.usd, args.agent)
    elif act == "answer":
        mi.answer_question(root, args.n, args.text)
    elif act == "edit":
        mi.edit_step(root, args.step, title=args.title, difficulty=args.difficulty, detail=args.detail)
    elif act == "approve":
        m = mi.approve(root, skip_questions=args.skip_questions)
        print(f"V/  Mission {m['id']} approved ({len(m['steps'])} step(s)). Start: vcmd mission run")
        return 0
    elif act == "run":
        if args.attempts < 1 or args.timeout < 1:
            raise ValueError("--attempts and --timeout must be positive")
        return mi.run_mission(root, attempts=args.attempts, timeout=args.timeout, review=args.review)
    elif act == "report":
        m = mi.load_mission(root)
        if m is None:
            raise FileNotFoundError('No mission. Start one: vcmd mission new "<goal>"')
        print(mi.render_report(root, m), end="")
        return 0
    elif act == "discard":
        print("V/  Mission discarded" if mi.discard(root) else "V/  No mission")
        return 0
    print(mi.render_view(mi.view(root)))
    return 0


def _hidden(prompt: str) -> str:
    import getpass
    value = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass(prompt)
    return value.strip()


def _connect_command(args, root: Path, cfg: dict) -> int:
    """Bring your own keys: everything is stored in YOUR OS secret store and used only from this machine."""
    from . import channels as ch
    from . import secrets_store as ss
    kind = args.conn_kind
    if kind == "telegram":
        item = ch.connect_telegram(root, _hidden("Bot token from @BotFather: "), args.chat)
        print(f"V/  Connected your bot @{item['bot']} (chat {item['chat_id']}); token stored in {ss.describe_backend()['name']}")
        print("V/  Test: vcmd channel test   ·   Steer from your phone: vcmd remote telegram")
    elif kind == "slack":
        ch.connect_slack(root, _hidden("Slack incoming webhook URL: "))
        print("V/  Slack connected (notifications only). Test: vcmd channel test")
    elif kind == "ntfy":
        import secrets as _secrets
        topic = args.topic or "vcmd-" + _secrets.token_urlsafe(12)
        ch.add_channel(root, "ntfy", topic=topic, server=args.server)
        print(f"V/  ntfy topic: {topic}  (subscribe to it in the ntfy app; the name is the password)")
    elif kind == "webhook":
        ch.connect_webhook(root, args.name, _hidden(f"URL for {args.name}: "))
        print(f"V/  Webhook connected; URL stored as secret {args.name}")
    else:
        argv = tokens(args.argv)
        if not argv or "{prompt}" not in argv:
            raise ValueError('Use: vcmd connect agent NAME --key MY_KEY --env BASE_URL=https://… -- my-cli run "{prompt}"')
        spec: dict = {"argv": argv}
        if args.parser:
            spec["parser"] = args.parser
        if args.key:
            ss.validate_name(args.key)
            if not any(x["name"] == args.key for x in ss.list_secrets()) and not os.environ.get(args.key):
                ss.set_secret(args.key, _hidden(f"{args.key}: "))
            spec["secrets"] = [args.key]
        env = {}
        for item in args.env:
            name, sep, value = item.partition("=")
            if not sep or not name:
                raise ValueError("--env needs NAME=VALUE")
            env[name] = value
        if env:
            spec["env"] = env
        cfg.setdefault("agents", {})[args.name] = spec
        from .adapters import agent_templates
        agent_templates(cfg)  # validate before saving
        save_config(root, cfg)
        print(f"V/  Agent '{args.name}' registered" + (f"; it receives only the secret {args.key}" if args.key else ""))
        print(f"V/  Run: vcmd agent {args.name}")
    return 0


def _parallel_command(args, root: Path, cfg: dict) -> int:
    from . import sessions as se, channels as ch
    shared = se.shared_root(root)
    if args.command == "worktree":
        if args.wt_action == "new":
            w = se.create_worktree(shared, args.name, branch=args.branch, base=args.base,
                                   path=Path(args.path) if args.path else None, goal=args.goal)
            print(f"V/  Worktree {w['name']}: {w['path']} on {w['branch']} (base {w['base'][:10]})")
            print(f"V/  Start a session there:  cd {w['path']} && claude     (or codex)")
            print("V/  It has its own task/brief/ledger; sessions, messages and approvals are shared.")
        elif args.wt_action == "list":
            items = se.list_worktrees(shared)
            if not items:
                print("V/  No worktrees. Create one: vcmd worktree new <name>")
            for w in items:
                state = f"{len(w.get('changed', []))} changed file(s)" if w["present"] else "missing on disk"
                print(f"{w['name']:16} {w['branch']:28} {state:22} {w['path']}")
        elif args.wt_action == "conflicts":
            items = se.conflicts(shared)
            print("\n".join(f"{c['file']:50} {', '.join(c['worktrees'])}" for c in items)
                  or "V/  No collisions: no file is changed in more than one worktree")
            return 1 if items else 0
        else:
            w = se.remove_worktree(shared, args.name, force=args.force)
            print(f"V/  Removed worktree {w['name']} ({w['path']}); branch {w['branch']} kept")
        return 0
    if args.command == "sessions":
        items = se.list_sessions(shared)
        if not items:
            print("V/  No sessions yet. Install hooks (vcmd hooks install claude|codex) and start an agent.")
        for x in items:
            ago = int((__import__("time").time() - x.get("last_seen", 0)) // 60)
            print(f"{x['name']:18} {x['agent']:12} {x['status']:7} {(x.get('branch') or '-'):24} "
                  f"{ago:>4} min ago" + (f"   {x['unread']} unread" if x["unread"] else ""))
        return 0
    if args.command == "msg":
        if args.msg_action == "send":
            sender = args.sender or se.session_name(shared, Path.cwd())
            if args.to == "developer":
                sent = ch.notify(shared, "message", f"From {sender}: {args.text}")
                print(f"V/  Sent to {sent} channel(s)" if sent else "V/  No channel reached (vcmd channel list)")
                return 0 if sent else 1
            m = se.send_message(shared, args.to, args.text, sender=sender)
            print(f"V/  {m['id']} queued for {args.to}; delivered at its next tool call, prompt or stop")
        else:
            msgs = se.list_messages(shared)
            for m in msgs:
                got = ", ".join(m.get("delivered_to") or []) or "not delivered yet"
                print(f"{m['id']}  {m['at_utc'][:16]}  {m['from']} -> {m['to']}: {m['text'][:120]}  [{got}]")
            if not msgs:
                print("V/  No messages")
        return 0
    if args.command == "channel":
        if args.ch_action == "add":
            c = ch.add_channel(root, args.type, chat_id=args.chat, topic=args.topic, server=args.server,
                               secret=args.secret, events=args.event or None)
            print(f"V/  Channel added: {c['type']}" + (f" (secret {c['secret']})" if c.get("secret") else ""))
            if c.get("secret") and not ch._secret(c["secret"]):
                print(f"V/  Store it: vcmd secret set {c['secret']}")
        elif args.ch_action == "rm":
            c = ch.remove_channel(root, args.index)
            print(f"V/  Removed {c['type']}")
        elif args.ch_action == "test":
            items = ch.channels(cfg)
            if not items:
                raise ValueError("No channels configured (vcmd channel add ...)")
            failed = 0
            for i, c in enumerate(items, 1):
                try:
                    ch.send(root, c, "Test message: notifications from V/COMMAND reach you here.")
                    print(f"V/  #{i} {c['type']}: sent")
                except Exception as error:  # noqa: BLE001 - report every channel
                    failed += 1
                    print(f"V/  #{i} {c['type']}: FAILED ({type(error).__name__}: {str(error)[:120]})")
            return 1 if failed else 0
        else:
            items = ch.channels(cfg)
            for i, c in enumerate(items, 1):
                detail = c.get("chat_id") or c.get("topic") or c.get("secret") or ""
                print(f"{i}. {c['type']:9} {detail:24} events: {', '.join(c.get('events') or ['all'])}")
            if not items:
                print("V/  No channels. Example: vcmd channel add telegram --chat 123456789")
        return 0
    if args.command == "remote":
        try:
            return ch.telegram_remote(root, once=args.once)
        except KeyboardInterrupt:
            return 0
    if args.command == "autopilot":
        return ch.run_autopilot(root, args.agents, every_s=ch.parse_every(args.every), use_loop=args.loop,
                                remote=args.remote, max_cycles=args.cycles, budget_usd=args.budget,
                                timeout=args.timeout)
    # roles
    roles = dict(cfg.get("roles") or {})
    if args.roles_action == "set":
        from .adapters import agent_templates, resolve_agent
        templates = agent_templates(cfg)
        for a in args.agents:
            resolve_agent(templates, a)
        if args.role == "rounds":
            raise ValueError("Use the config file for roles.rounds")
        roles[args.role] = args.agents[0] if args.role in {"plan", "review"} else args.agents
        cfg["roles"] = roles
        save_config(root, cfg)
    elif args.roles_action == "rm":
        roles.pop(args.role, None)
        cfg["roles"] = roles
        save_config(root, cfg)
    for role, value in roles.items():
        print(f"{role:10} {', '.join(value) if isinstance(value, list) else value}")
    if not roles:
        print("V/  No roles. Example: vcmd roles set plan claude-opus; vcmd roles set build claude-sonnet codex;")
        print("V/                     vcmd roles set review codex; vcmd roles set chore claude-haiku")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    trailing: list[str] | None = None
    if argv[:2] == ["connect", "agent"] and "--" in argv:
        # argparse (3.10 and 3.11) swallows what follows `--` when options are mixed with positionals:
        # split the agent command off by hand.
        i = argv.index("--")
        argv, trailing = argv[:i], argv[i + 1:]
    args = make_parser().parse_args(argv)
    if trailing is not None:
        args.argv = trailing
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
            print("\nV/  Tool access for agents (bash, search, git, tests, web/MCP, browser):")
            tools = [("bash", "bash"), ("ripgrep", "rg"), ("git", "git"), ("node", "node"), ("npx", "npx"),
                     ("python", "python3" if os.name != "nt" else "python"), ("docker", "docker"),
                     ("claude", "claude"), ("codex", "codex"), ("opencode", "opencode"), ("ollama", "ollama")]
            for label, exe in tools:
                print(f"    {label:10} {shutil.which(exe) or '-'}")
            mcp = [p for p in (root / ".mcp.json", root / ".codex" / "config.toml") if p.exists()]
            print(f"    {'mcp':10} {', '.join(str(p.name) for p in mcp) or '- (no .mcp.json in the project)'}")
            try:
                import importlib.util
                pw = importlib.util.find_spec("playwright") is not None
            except (ImportError, ValueError):
                pw = False
            print(f"    {'playwright':10} {'python package installed' if pw else '- (npx playwright works if Node is present)'}")
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
                if args.role:
                    q.role_agents(load_config(root), args.role)  # fail early on unknown roles
                t = q.add_task(root, args.goal, focus=args.focus, gates=gates, after=args.after,
                               priority=args.priority, role=args.role)
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
        if args.command == "workspace":
            from . import dashboard as d
            server, url = d.make_server(root, args.port, os.environ.get("VCOMMAND_DASHBOARD_TOKEN"), workspace=True)
            print(f"V/  Workspace: {url}")
            print("V/  Local only (127.0.0.1). It contains a terminal: anyone with this link can run commands as you,")
            print("V/  so keep the link private. Ctrl+C stops the server and every terminal in it.")
            if not args.no_open:
                import webbrowser
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        if args.command == "dashboard":
            from . import dashboard as d
            if args.install_command:
                print(f"V/  /dashboard added for Claude Code: {d.install_command(root)}")
                return 0
            if args.stop:
                print("V/  Dashboard stopped" if d.stop_background(root) else "V/  No background dashboard")
                return 0
            if args.background:
                info = d.start_background(root, args.port)
                print(f"V/  Dashboard: {info['url']}")
                print("V/  Local only (127.0.0.1); the link contains a private access token. Stop: vcmd dashboard --stop")
                return 0
            server, url = d.make_server(root, args.port, os.environ.get("VCOMMAND_DASHBOARD_TOKEN"))
            print(f"V/  Dashboard: {url}")
            print("V/  Local only (127.0.0.1). Ctrl+C to stop.")
            if not args.no_open:
                import webbrowser
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
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
                                tasks_filter=args.task, jobs=args.jobs, handoffs=args.handoff, limit=args.limit,
                                resume=Path(args.resume) if args.resume else None)
            from .bench import render_report
            print("\n" + render_report(summary))
            print(f"V/  Results: {summary['dir']}")
            return 0
        if args.command == "secret":
            from . import secrets_store as ss
            if args.secret_action == "set":
                import getpass
                value = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass(f"{args.name}: ")
                r = ss.set_secret(args.name, value)
                print(f"V/  Stored {r['name']} ({r['hint']}) in {r['backend']}")
            elif args.secret_action == "rm":
                ss.delete_secret(args.name)
                print(f"V/  Deleted {args.name}")
            else:
                b = ss.describe_backend()
                print(f"V/  Store: {b['name']}")
                for x in ss.list_secrets():
                    print(f"{x['name']:24} {x['hint']:14} {x['label']}")
            return 0
        if args.command == "schedule":
            from .workflow import schedule_template
            agents = args.agents or ["claude"]
            text = schedule_template(args.kind, agents=agents, at=args.at, use_loop=args.loop)
            if args.write:
                if args.kind != "github":
                    raise ValueError("--write is only for github; install cron/systemd entries yourself")
                dest = root / ".github" / "workflows" / "vcommand-wake.yml"
                if dest.exists():
                    raise ValueError(f"{dest} exists; remove it first or print without --write")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                print(f"V/  Wrote {dest}. Add repository secrets (ANTHROPIC_API_KEY / OPENAI_API_KEY) and commit it.")
            else:
                print(text, end="")
            return 0
        if args.command == "hooks":
            settings = Path(args.settings) if args.settings else None
            name = {"claude": "Claude Code", "codex": "Codex"}[args.target]
            if args.action == "install":
                path, changed = install_hooks(root, args.target, settings)
                if args.target == "claude":
                    from .dashboard import install_command
                    install_command(root)
                print(f"V/  {name} hooks {'added: ' + ', '.join(changed) if changed else 'already installed'} ({path})")
                print(f"V/  SessionStart injects the context frame; Stop runs your checks before {name} may finish.")
                if args.target == "claude":
                    print("V/  /dashboard is available in Claude Code (.claude/commands/dashboard.md)")
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
            agents = args.agents
            if args.role:
                from .queue import role_agents
                agents = role_agents(cfg, args.role)
            if not agents:
                raise ValueError("Name the agents (vcmd agent claude codex) or use --role (vcmd roles)")
            session = ("resume" if args.resume_last else f"resume:{args.resume}" if args.resume else
                       None if args.fork is None else f"fork:{args.fork}" if args.fork else "fork")
            if args.race:
                from .adapters import run_race
                return run_race(root, agents, instruction=args.instruction, timeout=args.timeout,
                                check_timeout=args.check_timeout, budget_usd=args.budget)
            return run_agents(root, agents, attempts=args.attempts, instruction=args.instruction,
                              timeout=args.timeout, check_timeout=args.check_timeout, isolate=args.isolate,
                              budget_usd=args.budget, session=session)
        if args.command == "task":
            if args.task_action == "start":
                from .workflow import normalize_brief
                t = start_task(root, args.goal, normalize_brief(args.scope, args.constraint, args.done,
                                                                args.leave_behind))
                print(f"V/  Task {t['id']} started: {t['goal']}")
                if not t.get("brief"):
                    print("V/  Tip: add the operating brief: vcmd task brief --scope … --constraint … --done …")
            elif args.task_action == "brief":
                t = set_brief(root, scope=args.scope, constraints=args.constraint, done=args.done,
                              leave_behind=args.leave_behind, clear_constraints=args.clear_constraints)
                from .workflow import brief_view, render_brief
                print("\n".join(render_brief(brief_view(t, [" ".join(c) for c in cfg["checks"]]))).rstrip())
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
                    from .workflow import brief_view, render_brief
                    print("\n".join(render_brief(brief_view(t, [" ".join(c) for c in cfg["checks"]]))).rstrip())
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
        if args.command == "connect":
            return _connect_command(args, root, cfg)
        if args.command == "mission":
            return _mission_command(args, root, cfg)
        if args.command in {"worktree", "sessions", "msg", "channel", "remote", "autopilot", "roles"}:
            return _parallel_command(args, root, cfg)
        if args.command in {"decide", "decisions", "todo", "handoff", "approve", "guard", "loop", "wake"}:
            return _workflow_command(args, root, cfg)
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
