"""Project state kept outside any model: task checkpoint, negative-knowledge ledger, context frames.

The idea: a coding model is a stateless processor. Everything a new model (or a fresh
session of the same model) needs to continue a task lives on disk in `.vcommand/`,
and `build_frame` compiles it into a compact, provider-neutral handoff.
Standard library only.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess
import shutil
import threading
import uuid
from typing import Any

from .core import CONFIG_DIR, list_evidence, load_config, git_status, utc_now
from .slice import build_slice, parse_focus, render_slice
from .workflow import brief_view, render_brief, open_todos, read_decisions, pending_approvals

FRAME_VERSION = 1
_LEDGER_LOCK = threading.Lock()  # parallel attempts / queue workers append from several threads
MAX_TEXT = 500           # per ledger field; keeps frames small and limits accidental leakage
MAX_LEDGER_IN_FRAME = 20
MAX_STATUS_LINES = 50
MAX_TODOS_IN_FRAME = 15
MAX_DECISIONS_IN_FRAME = 8


# ---------------------------------------------------------------- task checkpoint

def task_path(root: Path) -> Path:
    return root / CONFIG_DIR / "task.json"


def load_task(root: Path) -> dict[str, Any] | None:
    path = task_path(root)
    if not path.exists():
        return None
    task = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(task, dict) or task.get("schema_version") != 1:
        raise ValueError("Unsupported task schema version")
    return task


def _save_task(root: Path, task: dict[str, Any]) -> None:
    path = task_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clean(text: str, field: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise ValueError(f"Empty {field}")
    return text[:MAX_TEXT]


def start_task(root: Path, goal: str, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """brief: operating-brief fields (scope, constraints, done, leave_behind), see workflow.normalize_brief."""
    load_config(root)  # must be initialized
    task = {"schema_version": 1, "id": "task-" + uuid.uuid4().hex[:8], "goal": _clean(goal, "goal"),
            "created_at_utc": utc_now(), "completed_steps": [], "next_step": None}
    if brief and any(brief.values()):
        task["brief"] = brief
    _save_task(root, task)
    return task


def set_brief(root: Path, *, scope: str | None = None, constraints: list[str] | None = None,
              done: str | None = None, leave_behind: str | None = None, clear_constraints: bool = False) -> dict[str, Any]:
    """Update operating-brief fields of the current task; unspecified fields are kept, constraints appended."""
    from .workflow import normalize_brief
    task = _require_task(root)
    new = normalize_brief(scope, constraints, done, leave_behind)
    brief = dict(task.get("brief") or {})
    for key in ("scope", "done", "leave_behind"):
        if new[key]:
            brief[key] = new[key]
    brief["constraints"] = ([] if clear_constraints else list(brief.get("constraints") or [])) + new["constraints"]
    task["brief"] = brief
    _save_task(root, task)
    return task


def _require_task(root: Path) -> dict[str, Any]:
    task = load_task(root)
    if task is None:
        raise FileNotFoundError('No active task. Use: vcmd task start "<goal>"')
    return task


def complete_step(root: Path, step: str) -> dict[str, Any]:
    task = _require_task(root)
    task["completed_steps"].append({"step": _clean(step, "step"), "at_utc": utc_now()})
    if task.get("next_step") == task["completed_steps"][-1]["step"]:
        task["next_step"] = None
    _save_task(root, task)
    return task


def set_next_step(root: Path, step: str) -> dict[str, Any]:
    task = _require_task(root)
    task["next_step"] = _clean(step, "step")
    _save_task(root, task)
    return task


def set_focus(root: Path, specs: list[str]) -> dict[str, Any]:
    """Files or `file:Symbol` the task is about; the frame then carries their code and blast radius."""
    task = _require_task(root)
    task["focus"] = [s.strip() for s in specs if s.strip()]
    _save_task(root, task)
    return task


def clear_task(root: Path) -> bool:
    path = task_path(root)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------- negative knowledge ledger

def ledger_path(root: Path) -> Path:
    return root / CONFIG_DIR / "ledger.jsonl"


def changed_files(evidence: dict[str, Any]) -> list[str]:
    """Work-product files from a run's post-run git status (tool state directories excluded)."""
    after = evidence.get("git_status_after") or []
    ignored = (CONFIG_DIR, ".claude/", ".codex/")
    return [line[3:].strip('"') for line in after if len(line) > 3 and not line[3:].startswith(ignored)]


def add_ledger_entry(root: Path, *, tried: str, failure: str, constraint: str | None = None,
                     agent: str | None = None, run_id: str | None = None, source: str = "manual",
                     files: list[str] | None = None, failed_checks: list[str] | None = None,
                     pattern: str | None = None) -> dict[str, Any]:
    """Append one failed approach. Append-only JSON Lines; never stores command output."""
    tried_c = _clean(tried, "description of what was tried")
    failure_c = _clean(failure, "failure reason")
    entry = {
        "schema_version": 1,
        "id": "neg-" + uuid.uuid4().hex[:8],
        "created_at_utc": utc_now(),
        "source": source,
        "run_id": run_id,
        "agent": _clean(agent, "agent") if agent else None,
        "tried": tried_c,
        "failure": failure_c,
        "constraint": _clean(constraint, "constraint") if constraint else f"Do not repeat: {tried_c} (failed: {failure_c})"[:MAX_TEXT],
        # structured fields feed pre-flight hints (counts per file / per gate)
        "files": [f[:200] for f in (files or [])][:50],
        "failed_checks": [c[:300] for c in (failed_checks or [])][:20],
        # literal code fragment the stream guard refuses in later edits (e.g. "jwt.destroy(")
        "pattern": pattern.strip()[:200] if pattern and pattern.strip() else None,
    }
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = ledger_path(root)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn final line must not make the whole ledger unreadable
    return entries


def record_run_failure(root: Path, evidence: dict[str, Any], *, agent: str | None, note: str | None) -> dict[str, Any] | None:
    """Turn a failed `vcmd run` into a ledger entry. Returns None when the run did not fail."""
    status = evidence["status"]
    failed_checks: list[str] = []
    if status == "failed":
        a = evidence["action"]
        failure = (a["killed"] if a.get("killed") else
                   "command timed out" if a.get("timed_out") else f"command exited with code {a['exit_code']}")
    elif status == "failed_verification":
        failed = [c for c in evidence["checks"] if not c["passed"]]
        failed_checks = [" ".join(c["argv"]) for c in failed]
        failure = "; ".join(f"check `{' '.join(c['argv'])}` " + ("timed out" if c.get("timed_out") else f"exited {c['exit_code']}")
                            for c in failed)
    else:
        return None
    tried = note or f"run `{' '.join(evidence['action']['argv'])}`"
    return add_ledger_entry(root, tried=tried, failure=failure, agent=agent, run_id=evidence["id"], source="run",
                            files=changed_files(evidence), failed_checks=failed_checks)


# ---------------------------------------------------------------- context frame

def _git_head(root: Path) -> str | None:
    if not shutil.which("git"):
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def preflight_hints(ledger: list[dict[str, Any]], focus: list[str] | None = None, limit: int = 5) -> list[str]:
    """Pre-flight warnings derived only from counts in this project's ledger — never invented rates.

    A gate that failed repeatedly, or a file that was part of several failed attempts, is worth
    flagging before the next agent starts. Files in the task focus are ranked first."""
    from collections import Counter

    total = len(ledger)
    if total < 2:
        return []
    gates = Counter(c for e in ledger for c in set(e.get("failed_checks") or []))
    files = Counter(f for e in ledger for f in set(e.get("files") or []))
    focus_files = {parse_focus(spec)[0] for spec in (focus or [])}
    hints = []
    for gate, n in gates.most_common():
        if n >= 2:
            hints.append((0, f"Gate `{gate}` failed in {n} of {total} recorded failed attempts in this project."))
    for f, n in sorted(files.items(), key=lambda kv: (kv[0] not in focus_files, -kv[1], kv[0])):
        if n >= 2:
            hints.append((0 if f in focus_files else 1,
                          f"`{f}` was changed in {n} of {total} recorded failed attempts; check its callers and tests."))
    return [h for _, h in sorted(hints, key=lambda x: x[0])][:limit]


def continuity_token(frame: dict[str, Any]) -> str:
    """SHA-256 over the frame's state (excluding volatile fields). Same state -> same token."""
    stable = {k: v for k, v in frame.items() if k not in {"generated_at_utc", "continuity_token"}}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "sha256:" + digest


def build_frame(root: Path, code_root: Path | None = None) -> dict[str, Any]:
    """`root` holds V/COMMAND state; `code_root` (default: root) is the repository the code slice and
    git information come from — they differ for parallel queue workers."""
    code = code_root or root
    cfg = load_config(root)
    task = load_task(root)
    ledger = read_ledger(root)
    runs = [r for r in list_evidence(root) if not r.get("text_role")]  # planner/reviewer answers have no gates
    last = runs[-1] if runs else None
    status = git_status(code)
    frame: dict[str, Any] = {
        "frame_version": FRAME_VERSION,
        "generated_at_utc": utc_now(),
        "task": None if task is None else {
            "id": task["id"], "goal": task["goal"],
            "completed_steps": [s["step"] for s in task["completed_steps"]],
            "next_step": task.get("next_step"),
        },
        "brief": brief_view(task, [" ".join(c) for c in cfg["checks"]]),
        "focus": None if task is None else task.get("focus") or None,
        "code_slice": build_slice(code, task["focus"]) if task and task.get("focus") else None,
        "acceptance_gates": [" ".join(c) for c in cfg["checks"]],
        "negative_knowledge": [
            {k: e.get(k) for k in ("id", "agent", "tried", "failure", "constraint")}
            for e in ledger[-MAX_LEDGER_IN_FRAME:]
        ],
        "negative_knowledge_omitted": max(0, len(ledger) - MAX_LEDGER_IN_FRAME),
        "preflight_hints": preflight_hints(ledger, (task or {}).get("focus")),
        "open_todos": open_todos(root)[:MAX_TODOS_IN_FRAME],
        "recent_decisions": read_decisions(root)[-MAX_DECISIONS_IN_FRAME:],
        "pending_approvals": [{k: a.get(k) for k in ("id", "rule", "command")} for a in pending_approvals(root)],
        "last_run": None if last is None else {
            "id": last["id"], "status": last["status"],
            "failed_checks": [" ".join(c["argv"]) for c in last["checks"] if not c["passed"]],
        },
        "repository": {
            "head": _git_head(code),
            "working_tree": None if status is None else status[:MAX_STATUS_LINES],
            "working_tree_omitted": 0 if status is None else max(0, len(status) - MAX_STATUS_LINES),
        },
        "limitations": [
            ("Code slice is heuristic for TS/JS (Python uses the ast module); references are text matches."
             if task and task.get("focus") else
             "No code focus set (`vcmd task focus`): the receiving agent must read the files it needs."),
            "Working tree is a git status snapshot, not a diff.",
            "Gates are the configured checks; passing them is not proof of correctness.",
        ],
    }
    frame["continuity_token"] = continuity_token(frame)
    return frame


def render_frame(frame: dict[str, Any]) -> str:
    """Markdown handoff prompt, paste-able into any coding agent."""
    out = [f"# V/COMMAND context frame v{frame['frame_version']}",
           f"Continuity token: `{frame['continuity_token'][:23]}`", ""]
    task = frame["task"]
    if task:
        out += ["## Goal", task["goal"], ""]
        if frame.get("brief"):
            out += render_brief(frame["brief"])
        if task["completed_steps"]:
            out += ["## Already done (do not redo)"] + [f"- {s}" for s in task["completed_steps"]] + [""]
        out += ["## Next step", task["next_step"] or "Not set — decide from the goal and the state below.", ""]
    else:
        out += ["## Goal", "No active task recorded (`vcmd task start`).", ""]
    if frame["negative_knowledge"]:
        out.append("## Hard constraints from failed attempts (do not repeat)")
        for e in frame["negative_knowledge"]:
            who = f" [{e['agent']}]" if e.get("agent") else ""
            out.append(f"- {e['constraint']}{who}")
        if frame["negative_knowledge_omitted"]:
            out.append(f"- …{frame['negative_knowledge_omitted']} older entries omitted (`vcmd ledger list`)")
        out.append("")
    if frame.get("open_todos"):
        out += ["## Open to-dos (.vcommand/todo.md)"] + [f"- [ ] {t}" for t in frame["open_todos"]] + [""]
    if frame.get("recent_decisions"):
        out += ["## Decisions already made (.vcommand/decisions.md; do not reopen without new evidence)"]
        out += [f"- {d}" for d in frame["recent_decisions"]] + [""]
    if frame.get("pending_approvals"):
        out.append("## Waiting for the developer's approval (do not run or work around)")
        out += [f"- {a['id']}: {a['rule']} `{a['command'][:160]}`" for a in frame["pending_approvals"]]
        out.append("")
    if frame.get("preflight_hints"):
        out.append("## Pre-flight warnings (counted from this project's ledger)")
        out += [f"- [!] {h}" for h in frame["preflight_hints"]]
        out.append("")
    if frame.get("code_slice"):
        out += render_slice(frame["code_slice"])
    out.append("## Acceptance gates (must pass, run by V/COMMAND, not self-reported)")
    out += [f"- `{g}`" for g in frame["acceptance_gates"]] or ["- none configured: work will be reported as unverified"]
    out.append("")
    if frame["last_run"]:
        lr = frame["last_run"]
        out.append(f"## Last run\n{lr['id']}: {lr['status']}")
        out += [f"- failed: `{c}`" for c in lr["failed_checks"]]
        out.append("")
    repo = frame["repository"]
    if repo["head"]:
        out.append(f"## Repository\nHEAD `{repo['head'][:12]}`")
        if repo["working_tree"]:
            out += ["Uncommitted changes:", "```"] + repo["working_tree"] + ["```"]
        out.append("")
    out += ["## Limitations"] + [f"- {l}" for l in frame["limitations"]]
    return "\n".join(out) + "\n"
