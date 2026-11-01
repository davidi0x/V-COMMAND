"""`vcmd queue`: an overnight task queue that never claims work it did not verify.

Tasks run one after another, each through `vcmd agent --isolate` (fresh worktree per attempt, gates
decide, failed attempts discarded). A verified task is committed; the next task starts from that
commit. A task whose agent needs a human decision is frozen with its question and options, and the
queue moves on to tasks that do not depend on it. In the morning `vcmd queue report` lists what was
committed, what failed and which decisions are waiting.

Agents can ask for a decision in two ways:
* run `vcmd ask "<question>" --option A --option B` (agents allowed to run shell commands), or
* create `VCOMMAND_QUESTION.md` in the repository: first line = question, `- ` lines = options
  (works for agents that may only edit files).
Standard library only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import subprocess
import sys
import uuid
from typing import Any, TextIO

from .core import CONFIG_DIR, load_config, utc_now
from .state import start_task, set_focus, read_ledger
from .isolation import IsolationError, ensure_clean_repo, stage, work_changes
from .adapters import STOPPED_FOR_HUMAN, run_agents

QUESTION_FILE = "VCOMMAND_QUESTION.md"
TASK_ENV = "VCOMMAND_QUEUE_TASK"
QUEUE_INSTRUCTION = (f"If you cannot finish without a decision from the developer, do not guess: create "
                     f"{QUESTION_FILE} with the question on the first line and each option on its own "
                     f"line starting with '- ', then stop.")


def queue_path(root: Path) -> Path:
    return root / CONFIG_DIR / "queue.json"


def load_queue(root: Path) -> dict[str, Any]:
    path = queue_path(root)
    if not path.exists():
        return {"schema_version": 1, "tasks": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported queue schema version")
    return data


def _save(root: Path, data: dict[str, Any]) -> None:
    path = queue_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _find(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    for t in data["tasks"]:
        if t["id"] == task_id:
            return t
    raise ValueError(f"No queue task {task_id}")


def add_task(root: Path, goal: str, *, focus: list[str] | None = None, gates: list[list[str]] | None = None,
             after: list[str] | None = None, priority: int = 0) -> dict[str, Any]:
    load_config(root)
    goal = " ".join(goal.split())
    if not goal:
        raise ValueError("Empty goal")
    data = load_queue(root)
    for dep in after or []:
        _find(data, dep)
    task = {"id": "q-" + uuid.uuid4().hex[:6], "goal": goal, "focus": focus or [], "gates": gates or [],
            "after": after or [], "priority": priority, "status": "pending", "created_at_utc": utc_now(),
            "question": None, "options": [], "answers": [], "commit": None, "note": None, "finished_at_utc": None}
    data["tasks"].append(task)
    _save(root, data)
    return task


def ask(root: Path, task_id: str, question: str, options: list[str]) -> dict[str, Any]:
    data = load_queue(root)
    task = _find(data, task_id)
    task.update(status="frozen", question=" ".join(question.split())[:500],
                options=[" ".join(o.split())[:200] for o in options][:6])
    _save(root, data)
    return task


def answer(root: Path, task_id: str, text: str) -> dict[str, Any]:
    data = load_queue(root)
    task = _find(data, task_id)
    if task["status"] != "frozen":
        raise ValueError(f"Task {task_id} is not waiting for a decision (status: {task['status']})")
    task["answers"].append({"question": task["question"], "answer": " ".join(text.split())})
    task.update(status="pending", question=None, options=[])
    _save(root, data)
    return task


def _read_question_file(work: Path) -> tuple[str, list[str]] | None:
    path = work / QUESTION_FILE
    if not path.is_file():
        return None
    lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    if not lines:
        return None
    question = lines[0].lstrip("# ").strip()
    options = [l[2:].strip() for l in lines[1:] if l.startswith(("- ", "* "))]
    return question, options


def _runnable(data: dict[str, Any]) -> list[dict[str, Any]]:
    status = {t["id"]: t["status"] for t in data["tasks"]}
    ready = [t for t in data["tasks"] if t["status"] == "pending" and all(status.get(d) == "done" for d in t["after"])]
    return sorted(ready, key=lambda t: (-t["priority"], t["created_at_utc"]))


def _blocked(data: dict[str, Any]) -> list[dict[str, Any]]:
    status = {t["id"]: t["status"] for t in data["tasks"]}
    return [t for t in data["tasks"] if t["status"] == "pending"
            and any(status.get(d) in {"failed", "frozen", "blocked"} for d in t["after"])]


def _commit(root: Path, task: dict[str, Any]) -> str:
    stage(root, work_changes(root, (QUESTION_FILE,)))
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root)
    if staged.returncode == 0:
        return "(no changes)"
    msg = f"vcmd queue: {task['goal'][:72]}\n\nQueue task {task['id']}, verified by V/COMMAND gates."
    commit = subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, capture_output=True, text=True)
    if commit.returncode != 0:
        raise IsolationError(f"git commit failed (configure git user.name/user.email?): "
                             f"{(commit.stderr or commit.stdout).strip()[-200:]}")
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True)
    return head.stdout.strip()


def parse_until(text: str, now: datetime | None = None) -> datetime:
    """'HH:MM' local time; the next occurrence (tomorrow if already past)."""
    try:
        hh, mm = (int(x) for x in text.split(":"))
        now = now or datetime.now()
        deadline = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError as error:
        raise ValueError(f"--until must be HH:MM, got {text!r}") from error
    return deadline if deadline > now else deadline + timedelta(days=1)


def run_queue(root: Path, agents: list[str], *, attempts: int | None = None, max_tasks: int | None = None,
              until: str | None = None, budget_usd: float | None = None, timeout: int = 3600,
              check_timeout: int = 600, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    deadline = parse_until(until) if until else None
    ensure_clean_repo(root)
    data = load_queue(root)
    for t in data["tasks"]:
        if t["status"] == "running":  # a previous run was interrupted
            t.update(status="pending", note="restarted after an interrupted run")
    _save(root, data)
    done = 0
    while True:
        data = load_queue(root)
        for t in _blocked(data):
            t.update(status="blocked", note="a dependency failed, is frozen or blocked")
        _save(root, data)
        ready = _runnable(data)
        if not ready:
            break
        if max_tasks is not None and done >= max_tasks:
            print(f"V/  QUEUE      stopping: --max-tasks {max_tasks} reached", file=out)
            break
        if deadline and datetime.now() >= deadline:
            print(f"V/  QUEUE      stopping: --until {until} reached", file=out)
            break
        task = ready[0]
        task.update(status="running")
        _save(root, data)
        print(f"\nV/  QUEUE      {task['id']}: {task['goal']}", file=out, flush=True)
        goal = task["goal"] + "".join(f"\nDeveloper decision — {a['question']}: {a['answer']}" for a in task["answers"])
        start_task(root, goal)
        if task["focus"]:
            set_focus(root, task["focus"])
        ledger_before = len(read_ledger(root))

        def stop_check(work: Path, task_id: str = task["id"]) -> str | None:
            q = _read_question_file(work)
            if q:
                ask(root, task_id, q[0], q[1])
                return f"agent asked: {q[0]}"
            current = _find(load_queue(root), task_id)
            if current["status"] == "frozen":
                return f"agent asked: {current['question']}"
            return None

        try:
            code = run_agents(root, agents, attempts=attempts, instruction=QUEUE_INSTRUCTION, timeout=timeout,
                              check_timeout=check_timeout, out=out, isolate=True, budget_usd=budget_usd,
                              extra_checks=task["gates"], extra_env={TASK_ENV: task["id"]}, stop_check=stop_check)
        except (IsolationError, ValueError) as error:
            code = 1
            print(f"V/  Error: {error}", file=out)
        data = load_queue(root)
        current = _find(data, task["id"])
        if code == STOPPED_FOR_HUMAN or current["status"] == "frozen":
            current["status"] = "frozen"
        elif code == 0:
            try:
                current["commit"] = _commit(root, current)
                current["status"] = "done"
            except IsolationError as error:
                current.update(status="failed", note=str(error))
                _save(root, data)
                print(f"V/  QUEUE      {error}; stopping (working tree is not clean)", file=out)
                return 1
        else:
            failures = read_ledger(root)[ledger_before:]
            current.update(status="failed", note=(failures[-1]["failure"] if failures else "gates not passed"))
        current["finished_at_utc"] = utc_now()
        _save(root, data)
        print(f"V/  QUEUE      {task['id']} -> {current['status']}"
              + (f" ({current['commit']})" if current["commit"] else ""), file=out, flush=True)
        done += 1
    print("\n" + render_report(load_queue(root)), file=out)
    return 0


def render_report(data: dict[str, Any]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in data["tasks"]:
        groups.setdefault(t["status"], []).append(t)
    lines = ["V/  QUEUE REPORT", "-" * 56]
    labels = [("done", "Verified and committed"), ("frozen", "Waiting for your decision"), ("failed", "Failed"),
              ("blocked", "Blocked by another task"), ("pending", "Not started"), ("running", "Interrupted")]
    for key, label in labels:
        tasks = groups.get(key, [])
        if not tasks:
            continue
        lines.append(f"{label} ({len(tasks)}):")
        for t in tasks:
            extra = ""
            if key == "done":
                extra = f"  [{t['commit']}]"
            elif key in {"failed", "blocked"} and t.get("note"):
                extra = f"  — {t['note']}"
            lines.append(f"  {t['id']}  {t['goal'][:70]}{extra}")
            if key == "frozen":
                lines.append(f"      ? {t['question']}")
                lines += [f"      {chr(65 + i)}) {o}" for i, o in enumerate(t["options"])]
                lines.append(f"      answer: vcmd queue answer {t['id']} \"<your decision>\"")
    if len(lines) == 2:
        lines.append("Queue is empty. Add tasks: vcmd queue add \"<goal>\"")
    return "\n".join(lines)


def current_queue_task() -> str | None:
    return os.environ.get(TASK_ENV)
