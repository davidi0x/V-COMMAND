"""`vcmd bench`: measure whether the context frame helps, on the same tasks, under the same gates.

A suite is a directory with `suite.json` and one template directory per task:

    {
      "name": "sample",
      "tasks": [
        {"id": "fix-add", "dir": "fix-add", "goal": "Fix add() in calc.py",
         "focus": ["calc.py:add"], "gates": [["python", "-B", "test_calc.py"]]}
      ]
    }

Every (task, arm, repeat) runs in a fresh copy of the template, committed to a new git repo, with
a single agent attempt. Arms are `<agent>:plain` (goal + gate commands only — what a developer would
normally type) or `<agent>:frame` (full V/COMMAND context frame including the code slice).

The report gives per-arm pass rate with a Wilson 95% interval, median wall-clock time, provider-
reported cost where available, and paired task-level wins/losses. Small suites prove nothing; the
report says so. Standard library only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import median
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, TextIO

from .core import CONFIG_DIR, init_project, load_config, save_config, run_task
from .state import build_frame, set_focus, start_task
from .adapters import PROMPT_PLACEHOLDER, agent_templates, agent_env, build_prompt, resolve_agent

ARM_KINDS = ("plain", "frame")
PASS = "verified_by_configured_checks"


def load_suite(path: Path) -> dict[str, Any]:
    suite_file = path / "suite.json" if path.is_dir() else path
    data = json.loads(suite_file.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"{suite_file}: no tasks")
    ids = set()
    for t in tasks:
        for key in ("id", "dir", "goal", "gates"):
            if key not in t:
                raise ValueError(f"{suite_file}: task missing '{key}'")
        if t["id"] in ids:
            raise ValueError(f"{suite_file}: duplicate task id {t['id']}")
        ids.add(t["id"])
        if not (suite_file.parent / t["dir"]).is_dir():
            raise ValueError(f"{suite_file}: template dir not found: {t['dir']}")
        if not all(isinstance(g, list) and g and all(isinstance(a, str) for a in g) for g in t["gates"]):
            raise ValueError(f"{suite_file}: task {t['id']} gates must be argv lists")
    data["_base"] = suite_file.parent
    return data


def parse_arm(spec: str) -> tuple[str, str]:
    agent, _, kind = spec.partition(":")
    kind = kind or "frame"
    if not agent or kind not in ARM_KINDS:
        raise ValueError(f"Arm must be <agent>:plain or <agent>:frame, got {spec!r}")
    return agent, kind


def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = passed / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _python_gate(argv: list[str]) -> list[str]:
    # "python" in a suite means the interpreter running V/COMMAND (portable across OSes / venvs)
    return [sys.executable, *argv[1:]] if argv and argv[0] in {"python", "python3"} else argv


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=vcmd-bench", "-c", "user.email=bench@vcommand.invalid", *args],
                   cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def plain_prompt(task: dict[str, Any], gates: list[list[str]]) -> str:
    return (f"{task['goal']}\n\nWork in the current repository. The work is accepted when these commands pass:\n"
            + "\n".join(f"- {' '.join(g)}" for g in gates) + "\n")


def run_one(suite: dict[str, Any], task: dict[str, Any], agent: str, kind: str, *, timeout: int,
            check_timeout: int, templates: dict[str, Any]) -> dict[str, Any]:
    gates = [_python_gate(g) for g in task["gates"]]
    with tempfile.TemporaryDirectory(prefix="vcmd-bench-") as temp:
        work = Path(temp) / "repo"
        shutil.copytree(suite["_base"] / task["dir"], work)
        _git(work, "init", "-q")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", "task template")
        init_project(work)
        cfg = load_config(work)
        cfg["checks"] = gates
        save_config(work, cfg)
        start_task(work, task["goal"])
        if task.get("focus"):
            set_focus(work, task["focus"])
        if kind == "frame":
            frame = build_frame(work)
            prompt = build_prompt(frame)
        else:
            prompt = plain_prompt(task, task["gates"])
        spec = resolve_agent(templates, agent)
        argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
        shown = [f"<{kind} prompt>" if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
        start = time.monotonic()
        item = run_task(work, argv, timeout=timeout, check_timeout=check_timeout, agent=agent, record_argv=shown,
                        gates_judge=True, child_stdin=subprocess.DEVNULL, env=agent_env(work),
                        cost_parser=spec.get("cost"), log=_NullLog(), child_stdout=subprocess.DEVNULL)
        wall = time.monotonic() - start
    return {"task": task["id"], "agent": agent, "arm": f"{agent}:{kind}", "kind": kind,
            "passed": item["status"] == PASS, "status": item["status"], "wall_s": round(wall, 2),
            "agent_exit": item["action"].get("exit_code"), "cost_usd": item["cost"]["amount"],
            "cost_source": item["cost"]["source"], "prompt_chars": len(prompt)}


class _NullLog:
    def write(self, *_: Any) -> None: ...
    def flush(self) -> None: ...


def run_bench(suite_path: Path, arms: list[str], *, repeats: int = 1, out_dir: Path | None = None,
              timeout: int = 1800, check_timeout: int = 600, project_root: Path | None = None,
              tasks_filter: list[str] | None = None, out: TextIO | None = None) -> dict[str, Any]:
    out = out or sys.stdout
    if not shutil.which("git"):
        raise ValueError("vcmd bench needs git on PATH")
    suite = load_suite(suite_path)
    parsed = [parse_arm(a) for a in arms]
    if not parsed:
        raise ValueError("Give at least one --arm, e.g. --arm claude:plain --arm claude:frame")
    cfg = load_config(project_root) if project_root and (project_root / CONFIG_DIR / "config.json").exists() else {}
    templates = agent_templates(cfg)
    for agent, _ in parsed:
        resolve_agent(templates, agent)
    tasks = [t for t in suite["tasks"] if not tasks_filter or t["id"] in tasks_filter]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    dest = (out_dir or Path.cwd() / CONFIG_DIR / "bench") / run_id
    dest.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    total = len(tasks) * len(parsed) * repeats
    n = 0
    with (dest / "results.jsonl").open("w", encoding="utf-8") as sink:
        for r in range(1, repeats + 1):
            for task in tasks:
                for agent, kind in parsed:   # same task back-to-back across arms: paired conditions
                    n += 1
                    print(f"V/  BENCH      [{n}/{total}] {task['id']} {agent}:{kind} (repeat {r})", file=out, flush=True)
                    res = run_one(suite, task, agent, kind, timeout=timeout, check_timeout=check_timeout,
                                  templates=templates)
                    res["repeat"] = r
                    results.append(res)
                    sink.write(json.dumps(res) + "\n")
                    sink.flush()
                    print(f"V/  RESULT     {'PASS' if res['passed'] else 'FAIL'} {res['wall_s']}s"
                          + (f" ${res['cost_usd']:.4f}" if res["cost_usd"] is not None else ""), file=out, flush=True)
    summary = summarize(results, suite.get("name", suite_path.name), [f"{a}:{k}" for a, k in parsed])
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (dest / "report.md").write_text(render_report(summary), encoding="utf-8")
    summary["dir"] = str(dest)
    return summary


def summarize(results: list[dict[str, Any]], suite_name: str, arm_order: list[str]) -> dict[str, Any]:
    arms = {}
    for arm in arm_order:
        rows = [r for r in results if r["arm"] == arm]
        passed = sum(r["passed"] for r in rows)
        known = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
        lo, hi = wilson(passed, len(rows))
        arms[arm] = {"runs": len(rows), "passed": passed, "pass_rate": passed / len(rows) if rows else 0.0,
                     "wilson95": [round(lo, 3), round(hi, 3)],
                     "median_wall_s": round(median(r["wall_s"] for r in rows), 2) if rows else None,
                     "known_cost_usd": round(sum(known), 4) if known else None,
                     "runs_with_unknown_cost": len(rows) - len(known),
                     "median_prompt_chars": int(median(r["prompt_chars"] for r in rows)) if rows else None}
    paired = []
    for i, a in enumerate(arm_order):
        for b in arm_order[i + 1:]:
            wins = losses = ties = 0
            keys = {(r["task"], r["repeat"]) for r in results}
            for key in sorted(keys):
                ra = next((r for r in results if r["arm"] == a and (r["task"], r["repeat"]) == key), None)
                rb = next((r for r in results if r["arm"] == b and (r["task"], r["repeat"]) == key), None)
                if ra is None or rb is None:
                    continue
                if ra["passed"] and not rb["passed"]:
                    wins += 1
                elif rb["passed"] and not ra["passed"]:
                    losses += 1
                else:
                    ties += 1
            paired.append({"a": a, "b": b, "a_only_passed": wins, "b_only_passed": losses, "same": ties})
    n_tasks = len({r["task"] for r in results})
    return {"suite": suite_name, "tasks": n_tasks, "results": len(results), "arms": arms, "paired": paired,
            "caveats": ([f"Only {n_tasks} task(s): intervals are wide; this is a smoke test, not evidence."]
                        if n_tasks < 30 else []) +
                       ["Single attempt per run; no handoff or retries.",
                        "Cost is provider-reported where the agent template parses it; otherwise unknown, not zero."]}


def render_report(summary: dict[str, Any]) -> str:
    lines = [f"# V/COMMAND benchmark — {summary['suite']}", "",
             f"{summary['tasks']} task(s), {summary['results']} run(s).", "",
             "| Arm | Passed | Pass rate | Wilson 95% | Median wall (s) | Known cost (USD) | Unknown-cost runs | Median prompt chars |",
             "|---|---|---|---|---|---|---|---|"]
    for arm, s in summary["arms"].items():
        cost = "unknown" if s["known_cost_usd"] is None else f"{s['known_cost_usd']:.4f}"
        lines.append(f"| {arm} | {s['passed']}/{s['runs']} | {s['pass_rate']:.0%} | "
                     f"{s['wilson95'][0]:.0%}–{s['wilson95'][1]:.0%} | {s['median_wall_s']} | {cost} | "
                     f"{s['runs_with_unknown_cost']} | {s['median_prompt_chars']} |")
    if summary["paired"]:
        lines += ["", "## Paired (same task, same repeat)", ""]
        for p in summary["paired"]:
            lines.append(f"- {p['a']} only: {p['a_only_passed']} · {p['b']} only: {p['b_only_passed']} · "
                         f"same outcome: {p['same']}")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in summary["caveats"]]
    return "\n".join(lines) + "\n"
