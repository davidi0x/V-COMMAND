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

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from typing import Any, TextIO

from .core import CONFIG_DIR, load_config, utc_now
from .state import start_task, set_focus, read_ledger, _LEDGER_LOCK
from .slice import parse_focus
from .isolation import IsolationError, ensure_clean_repo, stage, work_changes
from .adapters import STOPPED_FOR_HUMAN, run_agents, load_health, _HEALTH_LOCK

QUESTION_FILE = "VCOMMAND_QUESTION.md"
TASK_ENV = "VCOMMAND_QUEUE_TASK"
QUEUE_ROOT_ENV = "VCOMMAND_QUEUE_ROOT"   # the project whose queue.json `vcmd ask` must update
_QUEUE_LOCK = threading.RLock()            # queue.json read-modify-write from parallel workers
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
             after: list[str] | None = None, priority: int = 0, role: str | None = None) -> dict[str, Any]:
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
    if role:
        task["role"] = role
    data["tasks"].append(task)
    _save(root, data)
    return task


def ask(root: Path, task_id: str, question: str, options: list[str]) -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue(root)
        task = _find(data, task_id)
        task.update(status="frozen", question=" ".join(question.split())[:500],
                    options=[" ".join(o.split())[:200] for o in options][:6])
        _save(root, data)
    from .channels import notify
    notify(root, "frozen", f"Queue task {task_id} waits for your decision:\n{task['question']}\n"
                           + "".join(f"- {o}\n" for o in task["options"])
                           + f"Reply: /answer {task_id} <decision>")
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


def _worker_root(root: Path, task_id: str) -> Path:
    return root / CONFIG_DIR / "workers" / task_id


def _prepare_worker(root: Path, task: dict[str, Any]) -> tuple[Path, int]:
    """Private V/COMMAND state for one queue task (its own task.json / frame), seeded from the project."""
    wroot = _worker_root(root, task["id"])
    shutil.rmtree(wroot, ignore_errors=True)
    (wroot / CONFIG_DIR / "runs").mkdir(parents=True)
    for name in ("config.json", "ledger.jsonl", "agent_health.json"):
        src = root / CONFIG_DIR / name
        if src.exists():
            shutil.copy2(src, wroot / CONFIG_DIR / name)
    goal = task["goal"] + "".join(f" Developer decision — {a['question']}: {a['answer']}" for a in task["answers"])
    start_task(wroot, goal)
    if task["focus"]:
        set_focus(wroot, task["focus"])
    return wroot, len(read_ledger(wroot))


def _merge_worker(root: Path, wroot: Path, ledger_seen: int) -> list[dict[str, Any]]:
    """Fold the worker's new ledger entries, evidence and provider health back into the project."""
    new_entries = read_ledger(wroot)[ledger_seen:]
    if new_entries:
        with _LEDGER_LOCK, (root / CONFIG_DIR / "ledger.jsonl").open("a", encoding="utf-8") as handle:
            for e in new_entries:
                handle.write(json.dumps(e, ensure_ascii=False) + "\n")
    (root / CONFIG_DIR / "runs").mkdir(parents=True, exist_ok=True)
    for run in (wroot / CONFIG_DIR / "runs").glob("*.json"):
        shutil.move(str(run), str(root / CONFIG_DIR / "runs" / run.name))
    worker_health = load_health(wroot)
    if worker_health:
        with _HEALTH_LOCK:
            merged = load_health(root)
            for agent, h in worker_health.items():
                if h.get("open_until", 0) >= merged.get(agent, {}).get("open_until", 0):
                    merged[agent] = h
            (root / CONFIG_DIR / "agent_health.json").write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(wroot, ignore_errors=True)
    return new_entries


def _task_files(task: dict[str, Any]) -> set[str]:
    return {parse_focus(f)[0] for f in task["focus"]}


def run_queue(root: Path, agents: list[str], *, attempts: int | None = None, max_tasks: int | None = None,
              until: str | None = None, budget_usd: float | None = None, timeout: int = 3600,
              check_timeout: int = 600, out: TextIO | None = None, jobs: int = 1) -> int:
    """Process the queue with up to `jobs` tasks in parallel.

    Tasks whose focus files overlap never run at the same time. Applying a verified patch and
    committing it happen under one lock, so history stays linear; a patch that no longer applies
    (another task changed the same lines) sends the task back to the queue once, from the new HEAD."""
    out = out or sys.stdout
    if jobs < 1:
        raise ValueError("--jobs must be at least 1")
    deadline = parse_until(until) if until else None
    ensure_clean_repo(root)
    with _QUEUE_LOCK:
        data = load_queue(root)
        for t in data["tasks"]:
            if t["status"] == "running":  # a previous run was interrupted
                t.update(status="pending", note="restarted after an interrupted run")
        _save(root, data)
    commit_lock = threading.Lock()
    print_lock = threading.Lock()
    locked: set[str] = set()

    def say(text: str) -> None:
        with print_lock:
            print(text, file=out, flush=True)

    def work(task: dict[str, Any]) -> None:
        wroot, seen = _prepare_worker(root, task)
        state = {"commit": None, "conflict": None}

        def apply_fn(wt) -> list[str]:
            with commit_lock:
                try:
                    changed = wt.apply_to_root()
                except IsolationError as error:
                    state["conflict"] = str(error)
                    raise
                with _QUEUE_LOCK:
                    current = _find(load_queue(root), task["id"])
                state["commit"] = _commit(root, current)
                return changed

        def stop_check(work_dir: Path) -> str | None:
            q = _read_question_file(work_dir)
            if q:
                ask(root, task["id"], q[0], q[1])
                return f"agent asked: {q[0]}"
            with _QUEUE_LOCK:
                current = _find(load_queue(root), task["id"])
            return f"agent asked: {current['question']}" if current["status"] == "frozen" else None

        with commit_lock:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        buffer = io.StringIO()
        try:
            code = run_agents(wroot, role_agents(load_config(root), task.get("role")) or agents, attempts=attempts, instruction=QUEUE_INSTRUCTION, timeout=timeout,
                              check_timeout=check_timeout, out=buffer if jobs > 1 else out, isolate=True,
                              budget_usd=budget_usd, extra_checks=task["gates"], stop_check=stop_check,
                              extra_env={TASK_ENV: task["id"], QUEUE_ROOT_ENV: str(root.resolve())},
                              repo=root, head=head, apply_fn=apply_fn)
        except (IsolationError, ValueError) as error:
            code = 1
            buffer.write(f"V/  Error: {error}\n")
        new_entries = _merge_worker(root, wroot, seen)
        with _QUEUE_LOCK:
            data = load_queue(root)
            current = _find(data, task["id"])
            if code == STOPPED_FOR_HUMAN or current["status"] == "frozen":
                current["status"] = "frozen"
            elif code == 0 and state["commit"]:
                current.update(status="done", commit=state["commit"])
            elif state["conflict"] and not current.get("conflict_retried"):
                current.update(status="pending", conflict_retried=True,
                               note="patch conflicted with a concurrently committed task; re-queued from new HEAD")
            elif code == 0:
                current.update(status="done", commit="(no changes)")
            else:
                current.update(status="failed", note=state["conflict"] or
                               (new_entries[-1]["failure"] if new_entries else "gates not passed"))
            current["finished_at_utc"] = utc_now() if current["status"] != "pending" else None
            _save(root, data)
            status, commit = current["status"], current["commit"]
        if jobs > 1:
            say(f"\n--- {task['id']} ---\n{buffer.getvalue().rstrip()}")
        say(f"V/  QUEUE      {task['id']} -> {status}" + (f" ({commit})" if commit else ""))
        if status in {"done", "failed"}:
            from .channels import notify
            notify(root, "verified" if status == "done" else "failed",
                   f"Queue task {task['id']} {status}: {task['goal']}" + (f"\nCommit: {commit}" if commit else ""))

    started = 0
    stop_note_shown = False
    futures: dict[Any, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        while True:
            with _QUEUE_LOCK:
                data = load_queue(root)
                for t in _blocked(data):
                    t.update(status="blocked", note="a dependency failed, is frozen or blocked")
                _save(root, data)
                ready = [t for t in _runnable(data) if not (_task_files(t) & locked)]
                while ready and len(futures) < jobs:
                    reason = (f"--max-tasks {max_tasks} reached" if max_tasks is not None and started >= max_tasks
                              else f"--until {until} reached" if deadline and datetime.now() >= deadline else None)
                    if reason:
                        if not stop_note_shown:
                            say(f"V/  QUEUE      not starting new tasks: {reason}")
                            stop_note_shown = True
                        break
                    task = ready.pop(0)
                    if _task_files(task) & locked:
                        continue
                    _find(data, task["id"])["status"] = "running"
                    _save(root, data)
                    locked |= _task_files(task)
                    started += 1
                    say(f"\nV/  QUEUE      {task['id']}: {task['goal']}"
                        + (f"  [locks: {', '.join(sorted(_task_files(task)))}]" if jobs > 1 and task["focus"] else ""))
                    futures[pool.submit(work, task)] = task
            if not futures:
                break
            finished, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in finished:
                task = futures.pop(future)
                locked -= _task_files(task)
                error = future.exception()
                if error is not None:
                    say(f"V/  QUEUE      {task['id']} crashed: {type(error).__name__}: {error}")
                    with _QUEUE_LOCK:
                        data = load_queue(root)
                        _find(data, task["id"]).update(status="failed", note=f"internal error: {error}")
                        _save(root, data)
    say("\n" + render_report(load_queue(root)))
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


def role_agents(cfg: dict[str, Any], role: str | None) -> list[str]:
    """Agents configured for a role (config "roles": {"hard": ["claude-opus"], "chore": "claude-haiku"})."""
    if not role:
        return []
    value = (cfg.get("roles") or {}).get(role)
    if value is None:
        raise ValueError(f"Role '{role}' is not configured (vcmd roles set {role} <agent> [...])")
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def current_queue_task() -> str | None:
    return os.environ.get(TASK_ENV)


def current_queue_root(default: Path) -> Path:
    env = os.environ.get(QUEUE_ROOT_ENV)
    return Path(env) if env else default
