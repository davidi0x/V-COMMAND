"""Agent adapters: hand the context frame to coding agents and verify their work automatically.

Two integration styles:

* Hooks (Claude Code, Codex CLI — same protocol): the agent runs interactively; V/COMMAND injects the context frame at
  SessionStart (startup, resume, /clear, compaction) and runs the acceptance gates at Stop.
  A failed gate blocks the stop (bounded), records the failure in the ledger and tells the
  agent which gate failed.
* Wrapper (Codex CLI, Claude Code print mode, anything with a prompt argument):
  `vcmd agent codex claude` runs each agent non-interactively with the frame as prompt,
  verifies, and on failure hands the task to the next agent with an updated frame.

Standard library only. Nothing here stores prompts, agent output or command output.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, TextIO

from .core import CONFIG_DIR, current_task_id, list_evidence, load_config, run_task, render_evidence, utc_now
from .state import build_frame, render_frame, record_run_failure, changed_files as _all_changed_files
from .isolation import DEFAULT_LINKS, IsolationError, Worktree, ensure_clean_repo

PROMPT_PLACEHOLDER = "{prompt}"

# Non-interactive invocations. Override per project in .vcommand/config.json under "agents".
# A template is an argv list containing "{prompt}", or {"argv": [...], "parser": "<output parser>"}
# ("cost" is accepted as an older name for "parser"). See parsers.py.
DEFAULT_AGENTS: dict[str, Any] = {
    # Codex CLI >= 0.16x: `--full-auto` was removed; workspace-write lets the agent edit the repo.
    # --json streams events with token usage (USD only as an estimate from configured prices).
    "codex": {"argv": ["codex", "exec", "--json", "--sandbox", "workspace-write", PROMPT_PLACEHOLDER],
              "parser": "codex-jsonl"},
    # stream-json: provider-reported cost (total_cost_usd) and the stream guard on every edit.
    "claude": {"argv": ["claude", "-p", "--output-format", "stream-json", "--verbose",
                        "--permission-mode", "acceptEdits", PROMPT_PLACEHOLDER], "parser": "claude-stream"},
    # OpenCode: `opencode run <message>` (non-interactive).
    "opencode": ["opencode", "run", PROMPT_PLACEHOLDER],
    # Model presets for roles (Claude Code model aliases). Which model suits which role is your call:
    # `vcmd roles set plan claude-opus`, `vcmd roles set build claude-sonnet`, ...
    "claude-opus": {"argv": ["claude", "-p", "--model", "opus", "--output-format", "stream-json", "--verbose",
                             "--permission-mode", "acceptEdits", PROMPT_PLACEHOLDER], "parser": "claude-stream"},
    "claude-sonnet": {"argv": ["claude", "-p", "--model", "sonnet", "--output-format", "stream-json", "--verbose",
                               "--permission-mode", "acceptEdits", PROMPT_PLACEHOLDER], "parser": "claude-stream"},
    "claude-haiku": {"argv": ["claude", "-p", "--model", "haiku", "--output-format", "stream-json", "--verbose",
                              "--permission-mode", "acceptEdits", PROMPT_PLACEHOLDER], "parser": "claude-stream"},
}
SESSION_PLACEHOLDER = "{session}"
from .parsers import PARSERS as COST_PARSERS  # noqa: E402

AGENT_INSTRUCTIONS = """You are continuing a software task managed by V/COMMAND.
The context frame below is the source of truth: operating brief (goal, scope, constraints, done
condition, leave-behind), completed steps, next step, approaches that already failed, and acceptance gates.
- Work in the current repository. Stay inside the scope; obey the constraints. Do not redo completed steps.
- Never repeat an approach listed under hard constraints.
- Ask before risky actions: deploys or publishing (including git push), database writes or migrations,
  bulk or recursive deletes. Do not run them; V/COMMAND blocks them until the developer approves.
- Leave state behind, if `vcmd` is available: progress with `vcmd task done "<step>"` and
  `vcmd task next "<exact next step>"`, decisions with `vcmd decide "<decision>" --why "<reason>"`,
  open items with `vcmd todo add "<item>"`. V/COMMAND writes handoff.md and the evidence (diff, gate results).
- Other sessions may work in parallel (`vcmd sessions`, `vcmd worktree list`). Send short findings,
  warnings or handoffs with `vcmd msg send <session|all> "<text>"`; `vcmd msg send developer "<text>"`
  reaches the developer's phone if channels are configured. Avoid files other worktrees changed.
- When the done condition is met, stop. V/COMMAND runs the acceptance gates itself; your own report is not evidence.
"""

DEFAULT_MAX_STOP_BLOCKS = 3
HOOK_TARGETS = ("claude", "codex")
AGENT_LABELS = {"claude": "claude-code", "codex": "codex"}


def hook_commands(target: str) -> dict[str, str]:
    cmds = {"SessionStart": f"vcmd hook {target} session-start", "Stop": f"vcmd hook {target} stop",
            "PreToolUse": f"vcmd hook {target} pre-tool", "PreCompact": f"vcmd hook {target} pre-compact",
            "PostToolUse": f"vcmd hook {target} post-tool", "UserPromptSubmit": f"vcmd hook {target} prompt"}
    if target == "claude":
        cmds["SessionEnd"] = f"vcmd hook {target} session-end"
    return cmds


HOOK_EVENTS = ("session-start", "stop", "pre-tool", "pre-compact", "post-tool", "prompt", "session-end")
DEFAULT_ROTATE_TOKENS = 200_000  # transcript bytes / 4: a rough, conservative estimate
# Claude Code names its shell tool "Bash"; Codex hooks are installed without a matcher and the handler
# looks for a shell command in the tool input.
HOOK_MATCHERS = {("claude", "PreToolUse"): "Bash"}


CLAUDE_HOOK_COMMANDS = hook_commands("claude")  # backwards-compatible name


# ---------------------------------------------------------------- wrapper (codex / claude -p / custom)

def _spec(name: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        raw = {"argv": raw}
    if not isinstance(raw, dict):
        raise ValueError(f'Invalid agent template for "{name}"')
    argv, cost = raw.get("argv"), raw.get("parser", raw.get("cost"))
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
        raise ValueError(f'Invalid agent template for "{name}"')
    if PROMPT_PLACEHOLDER not in argv:
        raise ValueError(f'Agent template "{name}" needs a "{PROMPT_PLACEHOLDER}" argument')
    if cost is not None and cost not in COST_PARSERS:
        raise ValueError(f'Agent "{name}": unknown output parser {cost!r} (known: {", ".join(COST_PARSERS)})')
    spec = {"argv": list(argv), "cost": cost}
    for key in ("resume", "fork"):
        alt = raw.get(key)
        if alt is not None:
            if not (isinstance(alt, list) and PROMPT_PLACEHOLDER in alt and SESSION_PLACEHOLDER in alt):
                raise ValueError(f'Agent "{name}": "{key}" must be an argv list with {PROMPT_PLACEHOLDER} '
                                 f'and {SESSION_PLACEHOLDER}')
            spec[key] = list(alt)
    return spec


def session_argv(spec: dict[str, Any], mode: str) -> list[str] | None:
    """argv that continues (mode "resume") or branches (mode "fork") an earlier agent session.

    Claude Code: `--resume <id>` (+ `--fork-session`). Codex: `codex exec resume <id>` (no fork).
    Other agents: the template's own "resume" / "fork" lists, or None (not supported)."""
    if mode in spec:
        return list(spec[mode])
    argv = spec["argv"]
    if argv[0] == "claude" or argv[0].endswith(("/claude", "\\claude", "claude.exe", "claude.cmd")):
        i = argv.index(PROMPT_PLACEHOLDER)
        extra = ["--resume", SESSION_PLACEHOLDER] + (["--fork-session"] if mode == "fork" else [])
        return argv[:i] + extra + argv[i:]
    if argv[:2] == ["codex", "exec"] and mode == "resume":
        model = []
        for flag in ("-m", "--model"):
            if flag in argv and argv.index(flag) + 1 < len(argv):
                model = [flag, argv[argv.index(flag) + 1]]
        return ["codex", "exec", "resume", "--json", "-c", 'sandbox_mode="workspace-write"', *model,
                SESSION_PLACEHOLDER, PROMPT_PLACEHOLDER]
    return None


def last_agent_session(root: Path, agent: str) -> str | None:
    task = current_task_id(root)
    runs = [r for r in list_evidence(root) if r.get("agent") == agent and r.get("agent_session")]
    same_task = [r for r in runs if r.get("task_id") == task]
    pick = (same_task or runs)
    return pick[-1]["agent_session"] if pick else None


def agent_templates(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    custom = cfg.get("agents", {})
    if not isinstance(custom, dict):
        raise ValueError('Config "agents" must map names to templates')
    merged = {**DEFAULT_AGENTS, **custom}
    return {name: _spec(name, raw) for name, raw in merged.items()}


def resolve_agent(templates: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    if name not in templates:
        raise ValueError(f"Unknown agent: {name}. Known: {', '.join(sorted(templates))}")
    return templates[name]


# ---------------------------------------------------------------- provider health (circuit breaker)

DEFAULT_COOLDOWN_S = 600


def _health_path(root: Path) -> Path:
    return root / CONFIG_DIR / "agent_health.json"


def load_health(root: Path) -> dict[str, Any]:
    try:
        data = json.loads(_health_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_health(root: Path, data: dict[str, Any]) -> None:
    path = _health_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


AGENT_OUTCOMES = {"success", "error_max_turns"}


def provider_failure_reason(item: dict[str, Any]) -> str | None:
    """Heuristic: did the attempt fail because of the agent/provider rather than the task?

    Launch errors, timeouts, and a non-zero exit with no file changes (auth, quota, rate limit,
    outage) count. A run that changed files and failed the gates is a task failure, not this."""
    action = item["action"]
    if action.get("error_type"):
        return f"could not launch ({action['error_type']})"
    if action.get("timed_out"):
        return "timed out"
    # Stopped by V/COMMAND itself (stream guard, guardrail, cancelled race): not the provider's fault.
    # Found live: a guardrail kill (exit -9, no edits) opened the circuit and the agent was skipped.
    if action.get("killed") or action.get("cancelled"):
        return None
    # The agent reported how it ended: running out of turns or finishing is the agent's outcome,
    # not an outage (found live: --max-turns runs exit 1 without edits and were misread as outages).
    if item.get("agent_result") in AGENT_OUTCOMES:
        return None
    if action.get("exit_code") not in (0, None) and not _all_changed_files(item):
        return f"exited {action['exit_code']} without changing any file"
    return None


_HEALTH_LOCK = threading.Lock()


def record_health(root: Path, agent: str, reason: str | None, cooldown_s: int) -> None:
    with _HEALTH_LOCK:
        _record_health(root, agent, reason, cooldown_s)


def _record_health(root: Path, agent: str, reason: str | None, cooldown_s: int) -> None:
    data = load_health(root)
    if reason is None:
        data.pop(agent, None)
    else:
        prev = data.get(agent, {})
        data[agent] = {"consecutive_failures": int(prev.get("consecutive_failures", 0)) + 1,
                       "open_until": time.time() + cooldown_s, "last_reason": reason}
    _save_health(root, data)


def open_circuits(root: Path, now: float | None = None) -> dict[str, dict[str, Any]]:
    now = time.time() if now is None else now
    return {a: h for a, h in load_health(root).items() if isinstance(h, dict) and h.get("open_until", 0) > now}


def guard_root(root: Path, extra_env: dict[str, str] | None = None) -> Path:
    """Where approval requests live: the main project, also for parallel queue workers."""
    q = (extra_env or {}).get("VCOMMAND_QUEUE_ROOT") or os.environ.get("VCOMMAND_QUEUE_ROOT")
    return Path(q) if q else root


def parser_context(root: Path, cfg: dict[str, Any], argv: list[str], *, agent: str | None = None,
                   extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """What output parsers need: banned patterns (ledger + config) and price table for estimates."""
    from .state import read_ledger
    banned = [{"pattern": e["pattern"], "reason": e.get("failure", "")} for e in read_ledger(root) if e.get("pattern")]
    banned += [b for b in cfg.get("guard", {}).get("banned", []) if isinstance(b, dict) and b.get("pattern")]
    model = None
    for flag in ("-m", "--model"):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            model = argv[argv.index(flag) + 1]
    guard = {"root": str(guard_root(root, extra_env)), "cfg": cfg, "agent": agent,
             "queue_task": (extra_env or {}).get("VCOMMAND_QUEUE_TASK") or os.environ.get("VCOMMAND_QUEUE_TASK")}
    return {"banned": banned, "prices": cfg.get("prices", {}), "model": model, "guardrails": guard}


def _task_spend(root: Path) -> tuple[float, int]:
    """Known provider-reported spend and number of unknown-cost runs for the current task."""
    task_id = current_task_id(root)
    if task_id is None:
        return 0.0, 0
    runs = [r for r in list_evidence(root) if r.get("task_id") == task_id and not r["action"].get("external")]
    known = [r["cost"]["amount"] for r in runs if r.get("cost", {}).get("amount") is not None]
    return float(sum(known)), len(runs) - len(known)


def build_prompt(frame: dict[str, Any], instruction: str | None = None) -> str:
    head = AGENT_INSTRUCTIONS + (f"\nAdditional instruction from the developer: {instruction}\n" if instruction else "")
    return head + "\n" + render_frame(frame)


def _changed_files(evidence: dict[str, Any], limit: int = 5) -> list[str]:
    files = _all_changed_files(evidence)
    return files[:limit] + ([f"+{len(files) - limit} more"] if len(files) > limit else [])


def agent_env(root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for launched agents: stored API keys (vcmd secret / dashboard), plus VCOMMAND_ROOT so
    `vcmd` inside them (CLI or hooks) targets the main project. Variables already set win over secrets."""
    secrets: dict[str, str] = {}
    if not os.environ.get("VCOMMAND_NO_SECRETS"):
        try:
            from .secrets_store import secrets_env
            secrets = secrets_env()
        except (OSError, ValueError, subprocess.SubprocessError):
            secrets = {}
    from .secrets_store import NOT_FOR_AGENTS
    shell = {k: v for k, v in os.environ.items() if k not in NOT_FOR_AGENTS and k not in PARENT_SESSION_VARS}
    return {**secrets, **shell, "VCOMMAND_ROOT": str(root.resolve()), "VCOMMAND_WRAPPED": "1", **(extra or {})}


# When V/COMMAND itself runs inside a Claude Code session, these belong to that parent session. Found live:
# a child `claude -p` inherited CLAUDE_CODE_SESSION_ID, reused the parent's session id, and its hooks
# wrote into the parent's session environment. Every launched agent gets its own session.
PARENT_SESSION_VARS = {"CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_ENV_FILE",
                       "VCOMMAND_SESSION"}

STOPPED_FOR_HUMAN = 3  # run_agents exit code: an agent asked for a human decision


def _approval_stop(root: Path, item: dict[str, Any], since: str, extra_env: dict[str, str] | None,
                   out: TextIO) -> bool:
    """A guardrail blocked a risky command during this attempt (hook or stream guard).

    Verified work stands (the agent finished without the command); otherwise the task waits for the
    developer instead of handing the same blocked step to the next agent."""
    from .workflow import pending_approvals
    groot = guard_root(root, extra_env)
    new = [a for a in pending_approvals(groot) if a.get("requested_at_utc", "") >= since]
    if not new:
        return False
    for a in new:
        print(f"V/  APPROVAL   {a['id']}: {a['rule']} `{a['command'][:120]}` blocked; approve: vcmd approve {a['id']}",
              file=out)
    if item["status"] == "verified_by_configured_checks":
        return False
    task = (extra_env or {}).get("VCOMMAND_QUEUE_TASK")
    if task:
        from . import queue as q
        try:
            q.ask(groot, task, f"Approve {new[0]['rule']} command `{new[0]['command'][:200]}`?",
                  [f"vcmd approve {new[0]['id']}", f"vcmd approve {new[0]['id']} --deny"])
        except (ValueError, FileNotFoundError):
            pass
    print("V/  FROZEN     waiting for your approval decision (`vcmd approve list`)", file=out)
    return True


def run_agents(root: Path, agents: list[str], *, notify_result: bool = True, **kw: Any) -> int:
    """Run agents in order until the gates pass (see `_run_agents`), then tell the developer's channels."""
    code = _run_agents(root, agents, **kw)
    if notify_result and not (kw.get("extra_env") or {}).get("VCOMMAND_QUEUE_TASK"):
        _notify_outcome(root, code, f"vcmd agent {' '.join(agents)}")
    return code


def _notify_outcome(root: Path, code: int, what: str) -> None:
    try:
        from .channels import notify, channels
        if not channels(load_config(root)):
            return
        from .workflow import build_handoff
        h = build_handoff(root)
        event = {0: "verified", STOPPED_FOR_HUMAN: "frozen"}.get(code, "failed")
        notify(root, event, f"{what}: {event}\nGoal: {h['goal']}\nState: {h['current_state']}\n"
                            f"Open: {'; '.join(h['open_issues'][:3]) or 'none'}\nNext: {h['next_step']}")
    except (OSError, ValueError, FileNotFoundError):
        pass


def _run_agents(root: Path, agents: list[str], *, attempts: int | None = None, instruction: str | None = None,
               timeout: int = 3600, check_timeout: int = 600, out: TextIO | None = None,
               isolate: bool = False, budget_usd: float | None = None,
               extra_checks: list[list[str]] | None = None, extra_env: dict[str, str] | None = None,
               stop_check=None, repo: Path | None = None, head: str | None = None, apply_fn=None,
               session: str | None = None) -> int:
    """Run agents in order (cycling) until the gates pass. Returns a CLI exit code.

    isolate=True: every attempt runs in a fresh git worktree at HEAD; only a verified attempt's
    changes are applied to the working tree, failed attempts are discarded.
    Agents whose provider recently failed (circuit open) are skipped while others are available.
    budget_usd (or config budget.max_usd_per_task): stop before an attempt once the known,
    provider-reported spend on the current task reaches the limit.
    stop_check(work_dir) -> reason | None is called after each attempt, before anything is applied;
    a reason stops the run with STOPPED_FOR_HUMAN and discards that attempt (used by the queue).
    repo: the git repository when V/COMMAND state lives elsewhere (`root`), e.g. parallel queue workers;
    head: base commit for isolated attempts (skips the clean-tree check, the caller guarantees it);
    apply_fn(worktree) -> changed paths: replaces the default "apply patch to repo" step.
    session: None = fresh agent session per attempt (the default: no context rot); "resume" / "fork" =
    continue or branch the agent's last recorded session; "resume:<id>" / "fork:<id>" = that session."""
    repo = repo or root
    out = out or sys.stdout
    cfg = load_config(root)
    templates = agent_templates(cfg)
    for name in agents or [""]:
        resolve_agent(templates, name)
    attempts = attempts or len(agents)
    if attempts < 1:
        raise ValueError("Attempts must be at least 1")
    budget = budget_usd if budget_usd is not None else cfg.get("budget", {}).get("max_usd_per_task")
    if budget is not None and (not isinstance(budget, (int, float)) or budget <= 0):
        raise ValueError("Budget must be a positive number of USD")
    cooldown = int(cfg.get("failover", {}).get("cooldown_s", DEFAULT_COOLDOWN_S))
    if isolate and head is None:
        head = ensure_clean_repo(repo)
    links = cfg.get("isolation", {}).get("link", list(DEFAULT_LINKS))
    if not cfg["checks"] and not extra_checks:
        print("V/  WARNING    no checks configured: the result can only be 'unverified' and no handoff will happen",
              file=out)
    cursor = 0
    for n in range(1, attempts + 1):
        if budget is not None:
            spent, unknown = _task_spend(root)
            if spent >= budget:
                print(f"V/  BUDGET     stopped: ${spent:.4f} of ${budget:.4f} known spend on this task"
                      + (f" ({unknown} attempt(s) with unknown cost not counted)" if unknown else ""), file=out)
                return 1
        circuits = open_circuits(root)
        available = [a for a in agents if a not in circuits]
        for skipped in sorted(set(agents) & set(circuits)):
            h = circuits[skipped]
            print(f"V/  FAILOVER   skipping {skipped}: {h['last_reason']} "
                  f"(retry after {time.strftime('%H:%M:%S', time.localtime(h['open_until']))})", file=out)
        if not available:
            print("V/  FAILOVER   every agent's circuit is open; trying anyway", file=out)
            available = agents
        name = available[cursor % len(available)]
        cursor += 1
        spec = templates[name]
        frame = build_frame(root, code_root=repo)
        from .sessions import shared_root, worktree_for, take_messages, render_messages
        shared = shared_root(repo)
        sname = (worktree_for(shared, repo) or {}).get("name") or name
        msgs = take_messages(shared, sname)
        extra = (f"\nMessages for this session from other sessions or the developer:\n{render_messages(msgs)}"
                 if msgs else "")
        prompt = build_prompt(frame, ((instruction or "") + extra).strip() or None)
        template = spec["argv"]
        if session:
            mode, _, sid = session.partition(":")
            sid = sid or last_agent_session(root, name)
            alt = session_argv(spec, mode)
            if alt is None or not sid:
                print(f"V/  SESSION    {name}: " + ("cannot " + mode + " sessions" if alt is None else
                                                    "no earlier session recorded") + "; starting fresh", file=out)
            else:
                template = [sid if a == SESSION_PLACEHOLDER else a for a in alt]
                print(f"V/  SESSION    {name}: {mode} {sid[:12]}", file=out)
        argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in template]
        shown = [f"<context frame {frame['continuity_token'][:23]}>" if a == PROMPT_PLACEHOLDER else a
                 for a in template]
        print(f"\nV/  HANDOFF    attempt {n}/{attempts} -> {name}", file=out, flush=True)
        common = dict(timeout=timeout, check_timeout=check_timeout, agent=name, record_argv=shown, gates_judge=True,
                      child_stdin=subprocess.DEVNULL,
                      env=agent_env(root, {"VCOMMAND_SESSION": sname, **(extra_env or {}), "VCOMMAND_AGENT": name}),
                      cost_parser=spec["cost"],
                      extra_checks=extra_checks,
                      parser_context=parser_context(root, cfg, spec["argv"], agent=name, extra_env=extra_env))
        attempt_started = utc_now()
        if isolate:
            with Worktree(repo, head, links) as wt:
                print(f"V/  ISOLATE    worktree at {head[:12]} ({wt.path})", file=out, flush=True)
                for warning in wt.warnings:
                    print(f"V/  WARNING    {warning}", file=out)
                item = run_task(root, argv, cwd=wt.path, isolated=True, **common)
                print(render_evidence(item), file=out)
                record_health(root, name, provider_failure_reason(item), cooldown)
                if _approval_stop(root, item, attempt_started, extra_env, out):
                    print("V/  DISCARDED  attempt changes (they wait for your approval decision)", file=out)
                    return STOPPED_FOR_HUMAN
                asked = stop_check(wt.path) if stop_check else None
                if asked:
                    print(f"V/  FROZEN     {asked}; attempt discarded", file=out)
                    return STOPPED_FOR_HUMAN
                if item["status"] in {"verified_by_configured_checks", "unverified"}:
                    try:
                        changed = apply_fn(wt) if apply_fn else wt.apply_to_root()
                    except IsolationError as error:
                        print(f"V/  Error: {error}. Verified changes were not applied.", file=out)
                        return 1
                    print(f"V/  APPLIED    {len(changed)} file(s) to the working tree: {', '.join(changed[:8])}"
                          + (" …" if len(changed) > 8 else ""), file=out)
                    return 0
                print("V/  DISCARDED  attempt changes (next attempt starts from HEAD)", file=out)
        else:
            item = run_task(root, argv, **common)
            print(render_evidence(item), file=out)
            record_health(root, name, provider_failure_reason(item), cooldown)
            if _approval_stop(root, item, attempt_started, extra_env, out):
                return STOPPED_FOR_HUMAN
            asked = stop_check(root) if stop_check else None
            if asked:
                print(f"V/  FROZEN     {asked}", file=out)
                return STOPPED_FOR_HUMAN
        if item["action"].get("error_type") == "FileNotFoundError":
            print(f"V/  Error: `{spec['argv'][0]}` not found in PATH (agent '{name}')", file=out)
        if item["status"] in {"verified_by_configured_checks", "unverified"}:
            return 0
        reason = provider_failure_reason(item)
        if reason:
            print(f"V/  FAILOVER   {name}: suspected provider/agent failure ({reason}); "
                  f"skipped for {cooldown}s while other agents are available", file=out)
        changed = _changed_files(item)
        note = f"{name} attempt {n}" + (f" changing {', '.join(changed)}" if changed else " (no file changes)")
        entry = record_run_failure(root, item, agent=name, note=note)
        if entry:
            print(f"V/  LEDGER     {entry['id']}: {entry['failure']}", file=out)
    print(f"V/  STOPPED    gates still failing after {attempts} attempt(s); see `vcmd frame` and `vcmd ledger list`",
          file=out)
    return 1


def run_race(root: Path, agents: list[str], *, instruction: str | None = None, timeout: int = 3600,
             check_timeout: int = 600, out: TextIO | None = None, budget_usd: float | None = None) -> int:
    """Speculative execution: all agents start at once on the same frame, each in its own worktree.

    The first attempt whose gates pass is applied; the others are killed (cancelled) and discarded.
    Failed attempts go to the ledger. Costs of every started attempt are recorded."""
    out = out or sys.stdout
    cfg = load_config(root)
    templates = agent_templates(cfg)
    if len(agents) < 2:
        raise ValueError("--race needs at least two agents")
    for name in agents:
        resolve_agent(templates, name)
    budget = budget_usd if budget_usd is not None else cfg.get("budget", {}).get("max_usd_per_task")
    if budget is not None:
        spent, _ = _task_spend(root)
        if spent >= budget:
            print(f"V/  BUDGET     stopped: ${spent:.4f} of ${budget:.4f} known spend on this task", file=out)
            return 1
    cooldown = int(cfg.get("failover", {}).get("cooldown_s", DEFAULT_COOLDOWN_S))
    head = ensure_clean_repo(root)
    links = cfg.get("isolation", {}).get("link", list(DEFAULT_LINKS))
    frame = build_frame(root)
    prompt = build_prompt(frame, instruction)
    cancel = threading.Event()
    lock = threading.Lock()
    outcome: dict[str, Any] = {"winner": None, "changed": [], "error": None}
    results: dict[str, dict[str, Any]] = {}
    print(f"V/  RACE       {', '.join(agents)} on frame {frame['continuity_token'][:23]} (first verified wins)",
          file=out, flush=True)

    def attempt(name: str) -> None:
        spec = templates[name]
        argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
        shown = [f"<context frame {frame['continuity_token'][:23]}>" if a == PROMPT_PLACEHOLDER else a
                 for a in spec["argv"]]
        try:
            with Worktree(root, head, links) as wt:
                item = run_task(root, argv, timeout=timeout, check_timeout=check_timeout, agent=name,
                                record_argv=shown, gates_judge=True, child_stdin=subprocess.DEVNULL,
                                child_stdout=subprocess.DEVNULL, env=agent_env(root), cost_parser=spec["cost"],
                                parser_context=parser_context(root, cfg, spec["argv"], agent=name), cwd=wt.path,
                                isolated=True, cancel=cancel, log=_Quiet())
                results[name] = item
                if item["status"] == "verified_by_configured_checks":
                    with lock:
                        if outcome["winner"] is None:
                            outcome["winner"] = name
                            cancel.set()
                            try:
                                outcome["changed"] = wt.apply_to_root()
                            except IsolationError as error:
                                outcome["error"] = str(error)
        except IsolationError as error:
            results[name] = {"status": "failed", "action": {"error_type": "IsolationError"}, "error": str(error)}

    threads = [threading.Thread(target=attempt, args=(name,), daemon=True) for name in agents]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for name in agents:
        item = results.get(name)
        if item is None or "id" not in item:
            print(f"V/  RACE       {name}: could not start ({(item or {}).get('error', 'unknown error')})", file=out)
            continue
        cost = item["cost"]["amount"]
        label = ("WINNER" if name == outcome["winner"] else
                 "cancelled" if item["action"].get("cancelled") else item["status"])
        print(f"V/  RACE       {name}: {label}, {item['action']['duration_ms']} ms"
              + (f", ${cost:.4f}" if cost is not None else ", cost unknown"), file=out)
        record_health(root, name, None if item["action"].get("cancelled") else provider_failure_reason(item), cooldown)
        if name != outcome["winner"] and not item["action"].get("cancelled"):
            changed = _changed_files(item)
            record_run_failure(root, item, agent=name, note=f"{name} (race)" +
                               (f" changing {', '.join(changed)}" if changed else " (no file changes)"))
    if outcome["error"]:
        print(f"V/  Error: {outcome['error']}. Verified changes were not applied.", file=out)
        return 1
    if outcome["winner"]:
        print(f"V/  APPLIED    {outcome['winner']}: {len(outcome['changed'])} file(s): "
              f"{', '.join(outcome['changed'][:8])}", file=out)
        return 0
    print("V/  RACE       no attempt passed the gates; see `vcmd ledger list`", file=out)
    return 1


class _Quiet:
    def write(self, *_: Any) -> None: ...
    def flush(self) -> None: ...


# ---------------------------------------------------------------- agent hooks (Claude Code, Codex)

def _hook_state_path(root: Path, target: str) -> Path:
    return root / CONFIG_DIR / "hooks" / f"{target}-stop.json"


def _bump_blocks(root: Path, target: str, session_id: str, reset: bool = False) -> int:
    path = _hook_state_path(root, target)
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        state = {}
    count = 0 if reset else int(state.get(session_id, 0)) + 1
    if reset:
        state.pop(session_id, None)
    else:
        state[session_id] = count
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    return count


def _hook_dirs(payload: dict[str, Any]) -> tuple[Path, Path]:
    """(state root, work dir). Inside `vcmd agent --isolate` the agent works in a worktree while
    V/COMMAND state stays in the main project (VCOMMAND_ROOT)."""
    cwd = payload.get("cwd")
    work = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    env = os.environ.get("VCOMMAND_ROOT")
    return (Path(env) if env else work), work


def _session_ctx(payload: dict[str, Any], target: str) -> tuple[Path, Path, Path, str, str]:
    """(state root, work dir, shared root, session id, session name) for a hook call."""
    from .sessions import shared_root, session_name
    root, work = _hook_dirs(payload)
    shared = shared_root(work)
    sid = str(payload.get("session_id") or "")
    if os.environ.get("VCOMMAND_WRAPPED") and not os.environ.get("VCOMMAND_SESSION"):
        name = os.environ.get("VCOMMAND_AGENT") or AGENT_LABELS.get(target, target)
    else:
        name = session_name(shared, work, sid or None, AGENT_LABELS.get(target, target))
    return root, work, shared, sid, name


def _inbox_text(shared: Path, name: str) -> str:
    from .sessions import take_messages, render_messages
    msgs = take_messages(shared, name)
    if not msgs:
        return ""
    return (f"[V/COMMAND] Message(s) for session `{name}` from other sessions or the developer:\n"
            + render_messages(msgs) + "\nAct on them if relevant; reply with `vcmd msg send <session> \"…\"`.")


def hook_session_start(payload: dict[str, Any], out: TextIO, target: str = "claude") -> int:
    """SessionStart: plain stdout is added to the agent's context (Claude Code and Codex)."""
    if os.environ.get("VCOMMAND_WRAPPED"):
        return 0  # `vcmd agent` already put the frame in the prompt
    root, work, shared, sid, _ = _session_ctx(payload, target)
    try:
        frame = build_frame(root)
    except FileNotFoundError:
        return 0  # project not initialized: stay silent
    from .sessions import register_session
    name = None
    if sid:
        name = register_session(shared, sid, agent=AGENT_LABELS.get(target, target), cwd=work,
                                source=payload.get("source"))["name"]
        env_file = os.environ.get("CLAUDE_ENV_FILE")
        if env_file:  # Claude Code: variables for this session's Bash commands (`vcmd msg` knows its sender)
            try:
                with open(env_file, "a", encoding="utf-8") as f:
                    f.write(f"export VCOMMAND_SESSION={name}\n")
            except OSError:
                pass
    source = payload.get("source", "startup")
    out.write(f"[V/COMMAND] Session {source}" + (f" `{name}`" if name else "") + ": project state restored from disk.\n\n")
    if name:
        inbox = _inbox_text(shared, name)
        if inbox:
            out.write(inbox + "\n\n")
    from .workflow import read_handoff
    handoff = read_handoff(root)
    if handoff:
        out.write("## Handoff from the previous session (.vcommand/handoff.md)\n")
        out.write(handoff.replace("# Handoff", "### Handoff", 1) + "\n")
    out.write(build_prompt(frame))
    return 0


def hook_pre_tool(payload: dict[str, Any], out: TextIO, target: str = "claude") -> int:
    """PreToolUse: risky shell commands (deploy, DB write, bulk delete) need the developer's approval.

    Interactive Claude Code: "ask" — Claude Code shows its own permission prompt to the developer.
    Codex, and every agent wrapped by V/COMMAND (no human at the keyboard): "deny" plus an approval
    request the developer answers with `vcmd approve <id>`; the exact command may then run."""
    from .workflow import classify_command, is_approved, guard_command, blocked_message
    root, _ = _hook_dirs(payload)
    try:
        cfg = load_config(root)
    except FileNotFoundError:
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        command = " ".join(str(c) for c in command)
    if not isinstance(command, str) or not command.strip():
        return 0
    groot = guard_root(root)
    if target == "claude" and not os.environ.get("VCOMMAND_WRAPPED"):
        rule = classify_command(cfg, command)
        if rule is None or is_approved(groot, command):
            return 0
        decision, reason = "ask", (f"V/COMMAND guardrail: this is a {rule} action. Allow it only if you "
                                   f"intended it now.")
    else:
        req = guard_command(groot, cfg, command, agent=AGENT_LABELS.get(target, target),
                            queue_task=os.environ.get("VCOMMAND_QUEUE_TASK"))
        if req is None:
            return 0
        decision, reason = "deny", blocked_message(req)
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                      "permissionDecisionReason": reason}}, out)
    out.write("\n")
    return 0


def _hook_state(shared: Path, name: str) -> tuple[Path, dict[str, Any]]:
    path = shared / CONFIG_DIR / "hooks" / f"session-{name}.json"
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, {}


def _collision_note(shared: Path, work: Path, name: str, file_path: str, state: dict[str, Any]) -> str | None:
    """Warn (once per file) when this session edits a file another live worktree already changed."""
    from .sessions import list_worktrees, _git, _changed
    if not _load_registry_has_worktrees(shared):
        return None
    top = _git(["rev-parse", "--show-toplevel"], work).stdout.strip()
    if not top:
        return None
    try:
        rel = Path(file_path).resolve().relative_to(Path(top).resolve()).as_posix()
    except (ValueError, OSError):
        return None
    warned = state.setdefault("collisions", [])
    if rel in warned:
        return None
    others = [w["name"] for w in list_worktrees(shared) if rel in w.get("changed", [])
              and not Path(top).resolve() == Path(w["path"]).resolve()]
    if Path(top).resolve() != shared.resolve():
        head = _git(["rev-parse", "HEAD"], shared).stdout.strip()
        if head and rel in _changed(shared, head):
            others.append("main")
    if not others:
        return None
    warned.append(rel)
    return (f"[V/COMMAND] Collision: `{rel}` is also changed in worktree(s) {', '.join(others)}. Parallel work only "
            f"stays clean when files stop colliding: coordinate first (`vcmd msg send {others[0]} \"…\"`) or "
            f"keep your change minimal and note it in `vcmd decide`.")


def _load_registry_has_worktrees(shared: Path) -> bool:
    from .sessions import _load
    return bool(_load(shared)["worktrees"])


def _rotation_note(root: Path, shared: Path, payload: dict[str, Any], state: dict[str, Any]) -> str | None:
    """Context rot: once the transcript is large, checkpoint and suggest a fresh session (once)."""
    path = payload.get("transcript_path")
    if not isinstance(path, str) or state.get("rotation_warned"):
        return None
    try:
        size = os.path.getsize(path)
        limit = int((load_config(root).get("rotation") or {}).get("max_context_tokens", DEFAULT_ROTATE_TOKENS))
    except (OSError, ValueError, TypeError, FileNotFoundError):
        return None
    if limit <= 0 or size // 4 < limit:
        return None
    state["rotation_warned"] = True
    from .workflow import write_handoff
    try:
        write_handoff(root)
    except (OSError, ValueError, FileNotFoundError):
        pass
    from .channels import notify
    notify(shared, "rotate", f"A session's context is large (~{size // 4000}k tokens est.); handoff.md checkpointed.")
    return (f"[V/COMMAND] This session's context is large (~{size // 4000}k tokens, estimated). Context rot "
            f"ahead: finish the current step, record `vcmd task next \"<exact next step>\"`, then tell the "
            f"developer to start a fresh session — handoff.md (just checkpointed) and the frame restore the state.")


def _context_reply(out: TextIO, event: str, parts: list[str]) -> None:
    text = "\n\n".join(p for p in parts if p)
    if text:
        json.dump({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, out)
        out.write("\n")


def hook_post_tool(payload: dict[str, Any], out: TextIO, target: str = "claude") -> int:
    """PostToolUse: deliver messages, warn about file collisions between worktrees, detect context rot."""
    root, work, shared, sid, name = _session_ctx(payload, target)
    try:
        load_config(shared)
    except FileNotFoundError:
        return 0
    from .sessions import touch_session
    if sid:
        touch_session(shared, sid)
    path, state = _hook_state(shared, name)
    parts = [_inbox_text(shared, name)]
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target_file = tool_input.get("file_path") or tool_input.get("notebook_path")
    if payload.get("tool_name") in {"Edit", "Write", "MultiEdit", "NotebookEdit"} and isinstance(target_file, str):
        parts.append(_collision_note(shared, work, name, target_file, state))
    parts.append(_rotation_note(root, shared, payload, state))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    except OSError:
        pass
    _context_reply(out, "PostToolUse", [p for p in parts if p])
    return 0


def hook_prompt(payload: dict[str, Any], out: TextIO, target: str = "claude") -> int:
    """UserPromptSubmit: messages that arrived while the session waited for the developer."""
    _, _, shared, sid, name = _session_ctx(payload, target)
    try:
        load_config(shared)
    except FileNotFoundError:
        return 0
    from .sessions import touch_session
    if sid:
        touch_session(shared, sid)
    _context_reply(out, "UserPromptSubmit", [_inbox_text(shared, name)])
    return 0


def hook_session_end(payload: dict[str, Any], out: TextIO, target: str = "claude") -> int:
    _, _, shared, sid, _ = _session_ctx(payload, target)
    if sid:
        from .sessions import touch_session
        touch_session(shared, sid, ended=True)
    return 0


def hook_pre_compact(payload: dict[str, Any], out: TextIO) -> int:
    """PreCompact: checkpoint before the context is summarized; SessionStart(compact) re-injects it."""
    from .workflow import write_handoff
    root, _ = _hook_dirs(payload)
    try:
        write_handoff(root)
    except FileNotFoundError:
        return 0
    return 0


def hook_stop(payload: dict[str, Any], out: TextIO, err: TextIO, target: str = "claude") -> int:
    """Stop: run gates; on failure block the stop (bounded) and record the failure.

    Reply protocol shared by Claude Code and Codex: JSON on stdout, {"decision": "block", "reason": ...}."""
    root, work, shared, sid, name = _session_ctx(payload, target)
    try:
        cfg = load_config(root)
    except FileNotFoundError:
        return 0
    try:
        inbox = _inbox_text(shared, name)
    except (OSError, ValueError):
        inbox = ""
    if inbox:  # a message arrived while the session worked: let it act before finishing
        json.dump({"decision": "block", "reason": inbox + "\nThen finish your task as usual."}, out)
        out.write("\n")
        return 0
    if not cfg["checks"]:
        return 0
    session = str(payload.get("session_id") or "unknown")
    hook_cfg = cfg.get("hooks", {})
    max_blocks = hook_cfg.get(f"{target}_max_stop_blocks", hook_cfg.get("max_stop_blocks", DEFAULT_MAX_STOP_BLOCKS))
    label = AGENT_LABELS.get(target, target)
    # Child processes and progress lines go to stderr: stdout is reserved for the hook's JSON reply.
    item = run_task(root, [f"{label}:session:{session[:8]}"], external=True, agent=label,
                    log=err, child_stdout=2, cwd=work)
    if item["status"] == "verified_by_configured_checks":
        _bump_blocks(root, target, session, reset=True)
        return 0
    changed = _changed_files(item)
    entry = record_run_failure(root, item, agent=label,
                               note=f"{label} session {session[:8]}" +
                                    (f" changing {', '.join(changed)}" if changed else ""))
    failure = entry["failure"] if entry else item["status"]
    blocks = _bump_blocks(root, target, session)
    if blocks <= max_blocks:
        reason = (f"V/COMMAND acceptance gates failed ({blocks}/{max_blocks}): {failure}. "
                  f"Run the failing check, fix the cause, and do not reuse an approach that already failed "
                  f"(see `vcmd frame`). Evidence: {item['id']}.")
        json.dump({"decision": "block", "reason": reason}, out)
    else:
        _bump_blocks(root, target, session, reset=True)
        json.dump({"systemMessage": f"V/COMMAND: gates still failing after {max_blocks} retries — {failure}. "
                                    f"Not verified. Evidence: {item['id']}."}, out)
    out.write("\n")
    return 0


def run_hook(target: str, event: str, stdin: TextIO, out: TextIO, err: TextIO) -> int:
    if target not in HOOK_TARGETS:
        raise ValueError(f"Unknown hook target: {target}")
    raw = stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if event == "session-start":
        return hook_session_start(payload, out, target)
    if event == "post-tool":
        return hook_post_tool(payload, out, target)
    if event == "prompt":
        return hook_prompt(payload, out, target)
    if event == "session-end":
        return hook_session_end(payload, out, target)
    if event == "stop":
        return hook_stop(payload, out, err, target)
    if event == "pre-tool":
        return hook_pre_tool(payload, out, target)
    if event == "pre-compact":
        return hook_pre_compact(payload, out)
    raise ValueError(f"Unknown hook event: {event}")


def run_claude_hook(event: str, stdin: TextIO, out: TextIO, err: TextIO) -> int:
    return run_hook("claude", event, stdin, out, err)


def settings_path(root: Path, target: str) -> Path:
    """Project-level hook files: Claude Code settings, or Codex hooks.json (needs /hooks trust)."""
    return root / ".claude" / "settings.json" if target == "claude" else root / ".codex" / "hooks.json"


def install_hooks(root: Path, target: str = "claude", settings: Path | None = None) -> tuple[Path, list[str]]:
    """Merge V/COMMAND hooks into the agent's project settings. Idempotent; keeps other hooks."""
    path = settings or settings_path(root, target)
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f'"hooks" in {path} is not an object')
    added = []
    for event, command in hook_commands(target).items():
        groups = hooks.setdefault(event, [])
        present = any(h.get("command") == command for g in groups if isinstance(g, dict)
                      for h in g.get("hooks", []) if isinstance(h, dict))
        if not present:
            group: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
            if (target, event) in HOOK_MATCHERS:
                group = {"matcher": HOOK_MATCHERS[(target, event)], **group}
            if event == "Stop":
                group["hooks"][0]["timeout"] = 900  # gates may run full test suites
            groups.append(group)
            added.append(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path, added


def uninstall_hooks(root: Path, target: str = "claude", settings: Path | None = None) -> tuple[Path, list[str]]:
    path = settings or settings_path(root, target)
    if not path.exists():
        return path, []
    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    removed = []
    for event, command in hook_commands(target).items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                inner = [h for h in g["hooks"] if not (isinstance(h, dict) and h.get("command") == command)]
                if len(inner) != len(g["hooks"]):
                    removed.append(event)
                if inner:
                    kept.append({**g, "hooks": inner})
            else:
                kept.append(g)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if isinstance(data, dict) and not hooks:
        data.pop("hooks", None)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, removed


def install_claude_hooks(root: Path, settings: Path | None = None) -> tuple[Path, list[str]]:
    return install_hooks(root, "claude", settings)


def uninstall_claude_hooks(root: Path, settings: Path | None = None) -> tuple[Path, list[str]]:
    return uninstall_hooks(root, "claude", settings)
