"""Local execution, checks and evidence persistence. Standard library only."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
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


def execute(argv: list[str], root: Path, timeout: int, stdout: int | None = None,
            stdin: int | None = None, env: dict[str, str] | None = None, capture: bool = False) -> dict[str, Any]:
    """Run an explicitly supplied argv directly, without a shell or output capture.

    `stdout` may redirect the child's stdout to another file descriptor (e.g. 2 inside
    agent hooks, whose stdout is reserved for the hook protocol)."""
    start = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(argv, cwd=root, timeout=timeout, check=False,
                                   stdout=subprocess.PIPE if capture else stdout, stdin=stdin, env=env)
        exit_code = completed.returncode
        captured = completed.stdout if capture else None
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = 124
        captured = None
    except OSError as error:
        # Don't store stderr / environment / secrets; error class is sufficient.
        return {"argv": argv, "exit_code": 127, "duration_ms": int((time.monotonic()-start)*1000),
                "timed_out": False, "error_type": type(error).__name__, "passed": False}
    result = {"argv": argv, "exit_code": exit_code, "duration_ms": int((time.monotonic()-start)*1000),
              "timed_out": timed_out, "passed": exit_code == 0 and not timed_out}
    if capture:
        result["_stdout"] = captured  # transient: popped by run_task, never persisted
    return result


class _Sink:
    def write(self, *_: Any) -> None: ...


def parse_cost(parser: str | None, raw: bytes | None, echo) -> dict[str, Any]:
    """Provider-reported cost from captured agent stdout. Echoes the agent's answer to `echo`.

    Only real receipts count: when parsing fails the cost stays unknown (None), never zero."""
    unknown = {"currency": "USD", "amount": None, "source": "unavailable"}
    if parser is None:
        return unknown
    text = (raw or b"").decode("utf-8", "replace")
    if parser == "claude-json":
        try:
            data = json.loads(text.strip().splitlines()[-1] if text.strip() else "")
        except (json.JSONDecodeError, IndexError):
            echo.write(text)
            return unknown
        if isinstance(data, dict):
            if isinstance(data.get("result"), str):
                echo.write(data["result"].rstrip() + "\n")
            amount = data.get("total_cost_usd")
            if isinstance(amount, (int, float)) and amount >= 0:
                return {"currency": "USD", "amount": float(amount), "source": "claude-code total_cost_usd"}
        return unknown
    raise ValueError(f"Unknown cost parser: {parser}")


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
             cost_parser: str | None = None) -> dict[str, Any]:
    """Execute `argv`, then the configured checks, and persist evidence.

    external=True: the work was done elsewhere (e.g. an interactive agent session ending);
    `argv` is only a label and nothing but the checks is executed.
    record_argv: what to store instead of `argv` (e.g. to keep a long prompt out of evidence).
    gates_judge=True: run the checks even when the command exits non-zero or times out (an agent's
    exit code is a self-report); status then follows the checks. Launch errors still skip checks.
    cwd: where the command and checks run (e.g. an isolated worktree); state stays in `root`.
    """
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
        action = execute(argv, work, timeout, stdout=child_stdout, stdin=child_stdin, env=env,
                         capture=cost_parser is not None)
        action["argv"] = list(shown)
    raw_out = action.pop("_stdout", None)
    echo = sys.stdout if child_stdout is None else (_Sink() if child_stdout == subprocess.DEVNULL else sys.stderr)
    cost = parse_cost(cost_parser, raw_out, echo) \
        if cost_parser and not external else {"currency": "USD", "amount": None, "source": "unavailable"}
    checks: list[dict[str, Any]] = []
    # Checks must not leave Python bytecode behind: a cached .pyc from a check could mask a later
    # edit made within the same second with the same file size.
    check_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    run_checks = action["passed"] or (gates_judge and "error_type" not in action)
    if run_checks:
        for check_argv in cfg["checks"]:
            print(f"V/  VERIFY     {' '.join(check_argv)}", file=log, flush=True)
            checks.append(execute(check_argv, work, check_timeout, stdout=child_stdout, env=check_env))
    else:
        print("V/  CHECKS     skipped: execution failed", file=log, flush=True)
    # No checks -> unverified, even when action exit code is 0.
    if not run_checks:
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
        "memory_savings_usd": None, "rejected_candidate_count": None,
        "limitations": [
            "Verification reflects configured checks, not a formal proof of correctness.",
            "Git status is a repository snapshot and cannot attribute edits to this command.",
            "Cost is recorded only when the agent CLI reports it (e.g. Claude Code JSON); otherwise unknown.",
            "Mode is a saved preference only; it does not enforce network isolation or route models."
        ]
    }
    dest = root / CONFIG_DIR / "runs" / f"{task_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return evidence


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
