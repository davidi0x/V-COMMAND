"""Local execution, checks and evidence persistence. Standard library only."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

CONFIG_DIR = ".vcommand"
MODES = ("speed", "balanced", "offline")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config_path(root: Path) -> Path:
    return root / CONFIG_DIR / "config.json"


def default_config() -> dict[str, Any]:
    return {"schema_version": 1, "mode": "balanced", "checks": [], "privacy": "local-metadata-only"}


def init_project(root: Path) -> bool:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "runs").mkdir(exist_ok=True)
    if path.exists():
        return False
    path.write_text(json.dumps(default_config(), indent=2) + "\n", encoding="utf-8")
    return True


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(root)
    if not path.exists():
        raise FileNotFoundError(f"Not initialized: {root}. Run `vcmd init` first.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or cfg.get("schema_version") != 1:
        raise ValueError("Unsupported config schema version")
    if cfg.get("mode") not in MODES:
        raise ValueError("Unknown work mode in config")
    checks = cfg.get("checks")
    if not isinstance(checks, list) or any(not isinstance(c, list) or not c or not all(isinstance(a, str) and a for a in c) for c in checks):
        raise ValueError("Invalid check definitions")
    return cfg


def save_config(root: Path, cfg: dict[str, Any]) -> None:
    path = config_path(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def project_root() -> Path:
    """Where V/COMMAND state lives. Agents launched by V/COMMAND get VCOMMAND_ROOT so that
    `vcmd` calls from inside an isolated worktree still update the main project's state."""
    env = os.environ.get("VCOMMAND_ROOT")
    return Path(env) if env else Path.cwd()


def git_status(root: Path) -> list[str] | None:
    if not shutil.which("git"):
        return None
    try:
        result = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=normal"], cwd=root,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None


def _popen_kwargs() -> dict[str, Any]:
    # own process group, so a kill also stops the agent's child processes
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def execute(argv: list[str], root: Path, timeout: int, stdout: int | None = None,
            stdin: int | None = None, env: dict[str, str] | None = None, parser=None,
            cancel: threading.Event | None = None) -> dict[str, Any]:
    """Run an explicitly supplied argv directly, without a shell.

    `stdout` may redirect the child's stdout (e.g. fd 2 inside agent hooks, whose stdout is reserved
    for the hook protocol). With a `parser`, stdout is read line by line while the process runs: the
    parser echoes it and may return a reason to kill the process (stream guard). A set `cancel` event
    kills the process (used when a parallel attempt already won). Output is never persisted."""
    start = time.monotonic()
    elapsed = lambda: int((time.monotonic() - start) * 1000)  # noqa: E731
    if parser is None and cancel is None:
        try:
            completed = subprocess.run(argv, cwd=root, timeout=timeout, check=False, stdout=stdout,
                                       stdin=stdin, env=env)
            code, timed_out = completed.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
        except OSError as error:
            # Don't store stderr / environment / secrets; error class is sufficient.
            return {"argv": argv, "exit_code": 127, "duration_ms": elapsed(), "timed_out": False,
                    "error_type": type(error).__name__, "passed": False}
        return {"argv": argv, "exit_code": code, "duration_ms": elapsed(), "timed_out": timed_out,
                "passed": code == 0 and not timed_out}

    try:
        proc = subprocess.Popen(argv, cwd=root, stdin=stdin, env=env,
                                stdout=subprocess.PIPE if parser is not None else stdout, **_popen_kwargs())
    except OSError as error:
        return {"argv": argv, "exit_code": 127, "duration_ms": elapsed(), "timed_out": False,
                "error_type": type(error).__name__, "passed": False}
    lines: queue.Queue = queue.Queue()
    reader = None
    if parser is not None:
        def pump() -> None:
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw.decode("utf-8", "replace"))
            lines.put(None)
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
    stop_reason = None
    timed_out = cancelled = False
    eof = parser is None
    while True:
        if parser is not None and not eof:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:
                eof = True
            elif line and stop_reason is None:
                stop_reason = parser.feed(line)
        else:
            time.sleep(0.05 if proc.poll() is None else 0)
        if stop_reason or (cancel is not None and cancel.is_set()) or time.monotonic() - start > timeout:
            if not stop_reason:
                cancelled = cancel is not None and cancel.is_set()
                timed_out = not cancelled
            _kill(proc)
            break
        if eof and proc.poll() is not None:
            break
    code = proc.wait()
    if reader is not None:
        reader.join(timeout=2)
        if not reader.is_alive():
            proc.stdout.close()
    result = {"argv": argv, "exit_code": 124 if timed_out else code, "duration_ms": elapsed(),
              "timed_out": timed_out, "passed": code == 0 and not (timed_out or cancelled or stop_reason)}
    if stop_reason:
        result["killed"] = stop_reason
    if cancelled:
        result["cancelled"] = True
    return result


class _Sink:
    def write(self, *_: Any) -> None: ...


def parse_cost(parser: str | None, raw: bytes | None, echo, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cost from a complete captured output (kept for callers that already have the bytes)."""
    from .parsers import make_parser
    p = make_parser(parser, echo, context)
    if p is None:
        return {"currency": "USD", "amount": None, "source": "unavailable"}
    for line in (raw or b"").decode("utf-8", "replace").splitlines(keepends=True):
        p.feed(line)
    return p.finish()


def current_task_id(root: Path) -> str | None:
    try:
        data = json.loads((root / CONFIG_DIR / "task.json").read_text(encoding="utf-8"))
        return data.get("id") if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def run_task(root: Path, argv: list[str], *, timeout: int = 600, check_timeout: int = 120,
             demo: bool = False, agent: str | None = None, record_argv: list[str] | None = None,
             external: bool = False, log=None, child_stdout: int | None = None,
             gates_judge: bool = False, child_stdin: int | None = None, cwd: Path | None = None,
             env: dict[str, str] | None = None, isolated: bool = False,
             cost_parser: str | None = None, extra_checks: list[list[str]] | None = None,
             parser_context: dict[str, Any] | None = None, cancel: threading.Event | None = None,
             run_checks: bool = True) -> dict[str, Any]:
    """Execute `argv`, then the configured checks, and persist evidence.

    external=True: the work was done elsewhere (e.g. an interactive agent session ending);
    `argv` is only a label and nothing but the checks is executed.
    record_argv: what to store instead of `argv` (e.g. to keep a long prompt out of evidence).
    gates_judge=True: run the checks even when the command exits non-zero or times out (an agent's
    exit code is a self-report); status then follows the checks. Launch errors still skip checks.
    cwd: where the command and checks run (e.g. an isolated worktree); state stays in `root`.
    run_checks=False: a text-only role (planner, reviewer); no gates run, status is at best unverified.
    The returned dict also carries `agent_text` (the agent's final answer, when its parser reports it);
    that key is not persisted.
    """
    checks_enabled = run_checks
    work = cwd or root
    if not argv:
        raise ValueError("Missing command")
    log = log or sys.stdout
    cfg = load_config(root)
    before = git_status(work)
    # Microseconds keep IDs (and therefore `sorted(runs/*.json)`) in execution order within one second.
    task_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    started_at = utc_now()
    shown = record_argv or argv
    if external:
        print(f"\nV/  SESSION    {' '.join(shown)}", file=log, flush=True)
        action = {"argv": list(shown), "external": True, "exit_code": None, "duration_ms": None,
                  "timed_out": False, "passed": True}
    else:
        print(f"\nV/  EXECUTE    {' '.join(shown)}", file=log, flush=True)
        from .parsers import make_parser
        echo = sys.stdout if child_stdout is None else (_Sink() if child_stdout == subprocess.DEVNULL else sys.stderr)
        parser = make_parser(cost_parser, echo, parser_context)
        action = execute(argv, work, timeout, stdout=child_stdout, stdin=child_stdin, env=env, parser=parser,
                         cancel=cancel)
        action["argv"] = list(shown)
        if action.get("killed"):
            print(f"V/  KILLED     {action['killed']}", file=log, flush=True)
    cost = parser.finish() if not external and parser is not None else \
        {"currency": "USD", "amount": None, "source": "unavailable"}
    checks: list[dict[str, Any]] = []
    # Checks must not leave Python bytecode behind: a cached .pyc from a check could mask a later
    # edit made within the same second with the same file size.
    check_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # killed by the stream guard or cancelled by a winning parallel attempt: nothing to verify
    run_checks = checks_enabled and action["passed"] or (checks_enabled and gates_judge and "error_type" not in action
                                      and not action.get("killed") and not action.get("cancelled"))
    if run_checks:
        for check_argv in cfg["checks"] + list(extra_checks or []):
            print(f"V/  VERIFY     {' '.join(check_argv)}", file=log, flush=True)
            checks.append(execute(check_argv, work, check_timeout, stdout=child_stdout, env=check_env))
    elif checks_enabled:
        print("V/  CHECKS     skipped: execution failed", file=log, flush=True)
    # No checks -> unverified, even when action exit code is 0.
    if not checks_enabled:
        status = "unverified" if action["passed"] else "failed"
    elif not run_checks:
        status = "failed"
    elif not checks:
        status = "unverified" if action["passed"] else "failed"
    elif all(check["passed"] for check in checks):
        status = "verified_by_configured_checks"
    else:
        status = "failed_verification"
    after = git_status(work)
    evidence = {
        "schema_version": 1, "id": task_id, "created_at_utc": started_at,
        "mode": cfg["mode"], "demo": demo, "agent": agent, "isolated_worktree": isolated,
        "task_id": current_task_id(root),
        "status": status, "action": action, "checks": checks,
        "git_status_before": before, "git_status_after": after,
        "cost": cost,
        "agent_result": getattr(parser, "result_subtype", None) if not external and parser is not None else None,
        "memory_savings_usd": None, "rejected_candidate_count": None,
        "limitations": [
            "Verification reflects configured checks, not a formal proof of correctness.",
            "Git status is a repository snapshot and cannot attribute edits to this command.",
            "Cost is recorded only when the agent CLI reports it (e.g. Claude Code JSON); otherwise unknown.",
            "Mode is a saved preference only; it does not enforce network isolation or route models."
        ]
    }
    if not checks_enabled:
        evidence["text_role"] = True  # planner / reviewer answer: no gates by design
    guard_hit = getattr(parser, "guardrail_hit", None) if not external and parser is not None else None
    if guard_hit:
        evidence["guardrail"] = guard_hit
    from . import workflow
    try:
        evidence["diff"] = workflow.save_patch(root, work, task_id)
    except (OSError, ValueError):
        evidence["diff"] = None
    dest = root / CONFIG_DIR / "runs" / f"{task_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:  # the leave-behind for the next session; never fail a run because of it
        workflow.write_handoff(root, None if evidence.get("text_role") else evidence)
    except (OSError, ValueError, FileNotFoundError, KeyError):
        pass
    text = getattr(parser, "final_text", None) if not external and parser is not None else None
    return {**evidence, "agent_text": text} if text else evidence


def read_evidence(root: Path, task_id: str = "last") -> dict[str, Any]:
    run_dir = root / CONFIG_DIR / "runs"
    if task_id == "last":
        matches = sorted(run_dir.glob("*.json")) if run_dir.exists() else []
        if not matches:
            raise FileNotFoundError("No local run evidence yet. Use `vcmd run -- <command>`.")
        path = matches[-1]
    else:
        if not task_id or any(c not in "0123456789abcdefTZ-" for c in task_id):
            raise ValueError("Invalid run ID")
        path = run_dir / f"{task_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_evidence(root: Path) -> list[dict[str, Any]]:
    run_dir = root / CONFIG_DIR / "runs"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(run_dir.glob("*.json"))] if run_dir.exists() else []


def render_evidence(item: dict[str, Any]) -> str:
    checks = item["checks"]
    total = len(checks)
    passed = sum(bool(c["passed"]) for c in checks)
    lines = [
        "", "V/  EVIDENCE", "-" * 56,
        f"Run       {item['id']}", f"Status    {item['status']}", f"Mode      {item['mode']}",
        f"Command   {' '.join(item['action']['argv'])}",
        *([f"Agent     {item['agent']}"] if item.get("agent") else []),
        *(["Session   external (work not executed by V/COMMAND; only checks were)"] if item["action"].get("external")
          else [f"Exit code {item['action']['exit_code']}", f"Duration  {item['action']['duration_ms']} ms"]),
        f"Checks    {passed}/{total} passed" if total else "Checks    not configured",
    ]
    for idx, c in enumerate(checks, 1):
        lines.append(f"  {idx}. {'PASS' if c['passed'] else 'FAIL'}  {' '.join(c['argv'])} ({c['duration_ms']} ms)")
    cost = item.get("cost") or {}
    lines += [f"API cost  ${cost['amount']:.4f} ({cost.get('source')})" if cost.get("amount") is not None
              else "API cost  unknown (no provider receipt)",
              "Savings   unknown (no benchmark baseline)",
              "Attempts  unknown (no agent trace)",
              "Evidence reflects executed checks; it is not a security attestation.", ""]
    return "\n".join(lines)
