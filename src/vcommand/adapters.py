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
from typing import Any, TextIO

from .core import CONFIG_DIR, load_config, run_task, render_evidence
from .state import build_frame, render_frame, record_run_failure
from .isolation import DEFAULT_LINKS, IsolationError, Worktree, ensure_clean_repo

PROMPT_PLACEHOLDER = "{prompt}"

# Non-interactive invocations. Override per project in .vcommand/config.json under "agents".
DEFAULT_AGENTS: dict[str, list[str]] = {
    # Codex CLI >= 0.16x: `--full-auto` was removed; workspace-write lets the agent edit the repo.
    "codex": ["codex", "exec", "--sandbox", "workspace-write", PROMPT_PLACEHOLDER],
    "claude": ["claude", "-p", "--permission-mode", "acceptEdits", PROMPT_PLACEHOLDER],
}

AGENT_INSTRUCTIONS = """You are continuing a software task managed by V/COMMAND.
The context frame below is the source of truth: goal, completed steps, next step,
approaches that already failed, and acceptance gates.
- Work in the current repository. Do not redo completed steps.
- Never repeat an approach listed under hard constraints.
- Record progress with `vcmd task done "<step>"` and `vcmd task next "<step>"` if available.
- When finished, stop. V/COMMAND runs the acceptance gates itself; your own report is not evidence.
"""

DEFAULT_MAX_STOP_BLOCKS = 3
HOOK_TARGETS = ("claude", "codex")
AGENT_LABELS = {"claude": "claude-code", "codex": "codex"}


def hook_commands(target: str) -> dict[str, str]:
    return {"SessionStart": f"vcmd hook {target} session-start", "Stop": f"vcmd hook {target} stop"}


CLAUDE_HOOK_COMMANDS = hook_commands("claude")  # backwards-compatible name


# ---------------------------------------------------------------- wrapper (codex / claude -p / custom)

def agent_templates(cfg: dict[str, Any]) -> dict[str, list[str]]:
    templates = dict(DEFAULT_AGENTS)
    custom = cfg.get("agents", {})
    if not isinstance(custom, dict):
        raise ValueError('Config "agents" must map names to argv lists')
    for name, argv in custom.items():
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)):
            raise ValueError(f'Invalid agent template for "{name}"')
        if PROMPT_PLACEHOLDER not in argv:
            raise ValueError(f'Agent template "{name}" needs a "{PROMPT_PLACEHOLDER}" argument')
        templates[name] = argv
    return templates


def build_prompt(frame: dict[str, Any], instruction: str | None = None) -> str:
    head = AGENT_INSTRUCTIONS + (f"\nAdditional instruction from the developer: {instruction}\n" if instruction else "")
    return head + "\n" + render_frame(frame)


def _changed_files(evidence: dict[str, Any], limit: int = 5) -> list[str]:
    after = evidence.get("git_status_after") or []
    ignored = (CONFIG_DIR, ".claude/", ".codex/")  # tool state, not work product
    files = [line[3:] for line in after if len(line) > 3 and not line[3:].startswith(ignored)]
    return files[:limit] + ([f"+{len(files) - limit} more"] if len(files) > limit else [])


def agent_env(root: Path) -> dict[str, str]:
    """Environment for launched agents: `vcmd` inside them (CLI or hooks) targets the main project."""
    return {**os.environ, "VCOMMAND_ROOT": str(root.resolve()), "VCOMMAND_WRAPPED": "1"}


def run_agents(root: Path, agents: list[str], *, attempts: int | None = None, instruction: str | None = None,
               timeout: int = 3600, check_timeout: int = 600, out: TextIO | None = None,
               isolate: bool = False) -> int:
    """Run agents in order (cycling) until the gates pass. Returns a CLI exit code.

    isolate=True: every attempt runs in a fresh git worktree at HEAD; only a verified attempt's
    changes are applied to the working tree, failed attempts are discarded."""
    out = out or sys.stdout
    cfg = load_config(root)
    templates = agent_templates(cfg)
    unknown = [a for a in agents if a not in templates]
    if not agents or unknown:
        raise ValueError(f"Unknown agent(s): {', '.join(unknown) or '(none)'}. Known: {', '.join(sorted(templates))}")
    attempts = attempts or len(agents)
    if attempts < 1:
        raise ValueError("Attempts must be at least 1")
    head = ensure_clean_repo(root) if isolate else None
    links = cfg.get("isolation", {}).get("link", list(DEFAULT_LINKS))
    if not cfg["checks"]:
        print("V/  WARNING    no checks configured: the result can only be 'unverified' and no handoff will happen",
              file=out)
    for n in range(1, attempts + 1):
        name = agents[(n - 1) % len(agents)]
        frame = build_frame(root)
        prompt = build_prompt(frame, instruction)
        argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in templates[name]]
        shown = [f"<context frame {frame['continuity_token'][:23]}>" if a == PROMPT_PLACEHOLDER else a
                 for a in templates[name]]
        print(f"\nV/  HANDOFF    attempt {n}/{attempts} -> {name}", file=out, flush=True)
        if isolate:
            with Worktree(root, head, links) as wt:
                print(f"V/  ISOLATE    worktree at {head[:12]} ({wt.path})", file=out, flush=True)
                for warning in wt.warnings:
                    print(f"V/  WARNING    {warning}", file=out)
                item = run_task(root, argv, timeout=timeout, check_timeout=check_timeout, agent=name,
                                record_argv=shown, gates_judge=True, child_stdin=subprocess.DEVNULL,
                                cwd=wt.path, env=agent_env(root), isolated=True)
                print(render_evidence(item), file=out)
                if item["status"] in {"verified_by_configured_checks", "unverified"}:
                    try:
                        changed = wt.apply_to_root()
                    except IsolationError as error:
                        print(f"V/  Error: {error}. Verified changes were not applied.", file=out)
                        return 1
                    print(f"V/  APPLIED    {len(changed)} file(s) to the working tree: {', '.join(changed[:8])}"
                          + (" …" if len(changed) > 8 else ""), file=out)
                    return 0
                print("V/  DISCARDED  attempt changes (next attempt starts from HEAD)", file=out)
        else:
            item = run_task(root, argv, timeout=timeout, check_timeout=check_timeout, agent=name,
                            record_argv=shown, gates_judge=True, child_stdin=subprocess.DEVNULL,
                            env=agent_env(root))
            print(render_evidence(item), file=out)
        if item["action"].get("error_type") == "FileNotFoundError":
            print(f"V/  Error: `{templates[name][0]}` not found in PATH (agent '{name}')", file=out)
        if item["status"] in {"verified_by_configured_checks", "unverified"}:
            return 0
        changed = _changed_files(item)
        note = f"{name} attempt {n}" + (f" changing {', '.join(changed)}" if changed else " (no file changes)")
        entry = record_run_failure(root, item, agent=name, note=note)
        if entry:
            print(f"V/  LEDGER     {entry['id']}: {entry['failure']}", file=out)
    print(f"V/  STOPPED    gates still failing after {attempts} attempt(s); see `vcmd frame` and `vcmd ledger list`",
          file=out)
    return 1


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


def hook_session_start(payload: dict[str, Any], out: TextIO) -> int:
    """SessionStart: plain stdout is added to the agent's context (Claude Code and Codex)."""
    if os.environ.get("VCOMMAND_WRAPPED"):
        return 0  # `vcmd agent` already put the frame in the prompt
    root, _ = _hook_dirs(payload)
    try:
        frame = build_frame(root)
    except FileNotFoundError:
        return 0  # project not initialized: stay silent
    source = payload.get("source", "startup")
    out.write(f"[V/COMMAND] Session {source}: project state restored from disk.\n\n")
    out.write(build_prompt(frame))
    return 0


def hook_stop(payload: dict[str, Any], out: TextIO, err: TextIO, target: str = "claude") -> int:
    """Stop: run gates; on failure block the stop (bounded) and record the failure.

    Reply protocol shared by Claude Code and Codex: JSON on stdout, {"decision": "block", "reason": ...}."""
    root, work = _hook_dirs(payload)
    try:
        cfg = load_config(root)
    except FileNotFoundError:
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
        return hook_session_start(payload, out)
    if event == "stop":
        return hook_stop(payload, out, err, target)
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
