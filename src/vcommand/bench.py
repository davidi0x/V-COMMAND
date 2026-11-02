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
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TextIO

from .core import CONFIG_DIR, init_project, load_config, save_config, run_task
from .state import build_frame, record_run_failure, set_focus, start_task
from .adapters import (PROMPT_PLACEHOLDER, agent_templates, agent_env, build_prompt, parser_context, resolve_agent,
                       provider_failure_reason)

# Provider failures (rate limit, quota, outage) are not task results: retry with backoff, and if they
# persist mark the run `infra_error` and exclude it from pass rates.
INFRA_BACKOFF_S = (30, 90)

ARM_KINDS = ("plain", "frame")          # arms usable in A>B handoff comparisons
KINDS = ("plain", "frame", "enhanced")  # arms for `agent:kind`; enhanced = the mission enhancer writes the brief first
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
    if not agent or kind not in KINDS:
        raise ValueError(f"Arm must be <agent>:plain, <agent>:frame or <agent>:enhanced, got {spec!r}")
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


class _NullLog:
    def write(self, *_: Any) -> None: ...
    def flush(self) -> None: ...


def _setup(suite: dict[str, Any], task: dict[str, Any], dest: Path) -> list[list[str]]:
    gates = [_python_gate(g) for g in task["gates"]]
    shutil.copytree(suite["_base"] / task["dir"], dest)
    _git(dest, "init", "-q")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "task template")
    init_project(dest)
    cfg = load_config(dest)
    cfg["checks"] = gates
    save_config(dest, cfg)
    start_task(dest, task["goal"])
    if task.get("focus"):
        set_focus(dest, task["focus"])
    return gates


def _enhanced_prompt(work: Path, task: dict[str, Any], agent: str, templates: dict[str, Any], *,
                     timeout: int) -> tuple[str, list[float]]:
    """The mission enhancer (same agent, read-only) writes brief + assumptions + steps; the worker gets them with
    the context frame. If the enhancer fails, the worker gets the plain prompt (and the failure is a cost, not a win)."""
    from .mission import ENHANCER_INSTRUCTION, parse_plan
    from .workflow import _text_role, normalize_brief
    text, e_item = _text_role(work, agent, ENHANCER_INSTRUCTION + task["goal"], out=_NullLog(), timeout=timeout,
                              label="enhance", quiet=True, templates=templates)
    cost = [e_item["cost"]["amount"]] if e_item["cost"]["amount"] is not None else []
    plan = parse_plan(text or "")
    if plan is None or not plan["steps"]:
        return plain_prompt(task, task["gates"]), cost
    b = plan["brief"]
    constraints = list(b.get("constraints") or []) + [f"Assumption: {a}" for a in plan["assumptions"]]
    start_task(work, task["goal"], normalize_brief(b.get("scope"), constraints[:12], b.get("done"), None))
    steps = "\n".join(f"{i}. ({s['difficulty']}) {s['title']}: {s['detail']}" for i, s in enumerate(plan["steps"], 1))
    note = ("Plan prepared for this task (follow it; the acceptance gates decide whether it is done):\n" + steps
            + "\nThere is no human to ask: where the goal is ambiguous, apply the stated assumptions and the "
              "repository's own conventions (README.md, neighbouring modules).")
    return build_prompt(build_frame(work), note), cost


def _attempt(work: Path, task: dict[str, Any], agent: str, kind: str, templates: dict[str, Any], *,
             timeout: int, check_timeout: int) -> dict[str, Any]:
    enhancer_cost: list[float] = []
    if kind == "enhanced":
        prompt, enhancer_cost = _enhanced_prompt(work, task, agent, templates, timeout=timeout)
    else:
        prompt = build_prompt(build_frame(work)) if kind == "frame" else plain_prompt(task, task["gates"])
    spec = resolve_agent(templates, agent)
    argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
    shown = [f"<{kind} prompt>" if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
    spent: list[float] = []
    infra = None
    for wait_s in (0, *INFRA_BACKOFF_S):
        if wait_s:
            time.sleep(wait_s)
        start = time.monotonic()
        item = run_task(work, argv, timeout=timeout, check_timeout=check_timeout, agent=agent, record_argv=shown,
                        gates_judge=True, child_stdin=subprocess.DEVNULL, env=agent_env(work),
                        cost_parser=spec.get("cost"), log=_NullLog(), child_stdout=subprocess.DEVNULL,
                        parser_context=parser_context(work, load_config(work), spec["argv"]))
        wall = time.monotonic() - start
        if item["cost"]["amount"] is not None:
            spent.append(item["cost"]["amount"])
        infra = None if item["status"] == PASS else provider_failure_reason(item)
        if not infra:
            break
    spent_all = spent + enhancer_cost  # the enhancer's cost belongs to the arm that uses it
    if kind == "enhanced" and not enhancer_cost:
        spent_all = []  # enhancer cost unknown: the arm's cost is unknown, never silently lower
    return {"item": item, "passed": item["status"] == PASS, "wall_s": wall,
            "cost_usd": (round(sum(spent_all), 6) if spent_all else None) if kind == "enhanced"
            else (round(sum(spent), 6) if spent else item["cost"]["amount"]),
            "cost_source": item["cost"]["source"], "prompt_chars": len(prompt), "infra_error": infra}


def run_one(suite: dict[str, Any], task: dict[str, Any], agent: str, kind: str, *, timeout: int,
            check_timeout: int, templates: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vcmd-bench-") as temp:
        work = Path(temp) / "repo"
        _setup(suite, task, work)
        a = _attempt(work, task, agent, kind, templates, timeout=timeout, check_timeout=check_timeout)
    return {"task": task["id"], "agent": agent, "arm": f"{agent}:{kind}", "kind": kind,
            "passed": a["passed"], "status": a["item"]["status"], "wall_s": round(a["wall_s"], 2),
            "agent_exit": a["item"]["action"].get("exit_code"), "cost_usd": a["cost_usd"],
            "cost_source": a["cost_source"], "prompt_chars": a["prompt_chars"], "attempts": 1,
            "infra_error": a["infra_error"]}


def run_handoff(suite: dict[str, Any], task: dict[str, Any], first: str, second: str, *, timeout: int,
                check_timeout: int, templates: dict[str, Any]) -> list[dict[str, Any]]:
    """Attempt 1: `first` with the plain prompt. If it fails, the same post-failure repository state is
    copied twice and `second` continues once with the plain prompt and once with the context frame
    (which now carries the failed attempt in its ledger). Both arms share attempt 1."""
    rows = []
    with tempfile.TemporaryDirectory(prefix="vcmd-bench-") as temp:
        work = Path(temp) / "repo"
        _setup(suite, task, work)
        a1 = _attempt(work, task, first, "plain", templates, timeout=timeout, check_timeout=check_timeout)
        if a1["infra_error"]:
            return [{"task": task["id"], "agent": f"{first}>{second}", "arm": f"{first}>{second}:{kind}", "kind": kind,
                     "passed": False, "first_attempt_passed": False, "rescued": False, "status": a1["item"]["status"],
                     "wall_s": round(a1["wall_s"], 2), "agent_exit": a1["item"]["action"].get("exit_code"),
                     "cost_usd": a1["cost_usd"], "cost_source": a1["cost_source"], "prompt_chars": a1["prompt_chars"],
                     "attempts": 1, "infra_error": f"first attempt: {a1['infra_error']}"} for kind in ARM_KINDS]
        if not a1["passed"]:
            record_run_failure(work, a1["item"], agent=first, note=f"{first} first attempt")
        for kind in ARM_KINDS:
            if a1["passed"]:
                a2 = None
            else:
                branch = Path(temp) / f"repo-{kind}"
                shutil.copytree(work, branch, symlinks=True)
                a2 = _attempt(branch, task, second, kind, templates, timeout=timeout, check_timeout=check_timeout)
            costs = [x["cost_usd"] for x in (a1, a2) if x is not None]
            rows.append({"task": task["id"], "agent": f"{first}>{second}", "arm": f"{first}>{second}:{kind}",
                         "kind": kind, "passed": a1["passed"] or bool(a2 and a2["passed"]),
                         "first_attempt_passed": a1["passed"], "rescued": bool(a2 and a2["passed"]),
                         "status": (a2 or a1)["item"]["status"],
                         "wall_s": round(a1["wall_s"] + (a2["wall_s"] if a2 else 0), 2),
                         "agent_exit": (a2 or a1)["item"]["action"].get("exit_code"),
                         "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 6),
                         "cost_source": (a2 or a1)["cost_source"],
                         "prompt_chars": (a2 or a1)["prompt_chars"], "attempts": 1 if a2 is None else 2,
                         "infra_error": a2["infra_error"] if a2 else None})
    return rows


def run_bench(suite_path: Path, arms: list[str], *, repeats: int = 1, out_dir: Path | None = None,
              timeout: int = 1800, check_timeout: int = 600, project_root: Path | None = None,
              tasks_filter: list[str] | None = None, out: TextIO | None = None, jobs: int = 1,
              handoffs: list[str] | None = None, limit: int | None = None,
              resume: Path | None = None) -> dict[str, Any]:
    out = out or sys.stdout
    if not shutil.which("git"):
        raise ValueError("vcmd bench needs git on PATH")
    suite = load_suite(suite_path)
    parsed = [parse_arm(a) for a in arms]
    pairs = []
    for h in handoffs or []:
        first, sep, second = h.partition(">")
        if not sep or not first or not second:
            raise ValueError(f"--handoff must be A>B, got {h!r}")
        pairs.append((first, second))
    if not parsed and not pairs:
        raise ValueError("Give --arm agent:plain / agent:frame and/or --handoff A>B")
    cfg = load_config(project_root) if project_root and (project_root / CONFIG_DIR / "config.json").exists() else {}
    templates = agent_templates(cfg)
    for agent in [a for a, _ in parsed] + [x for p in pairs for x in p]:
        resolve_agent(templates, agent)
    tasks = [t for t in suite["tasks"] if not tasks_filter or t["id"] in tasks_filter][:limit]
    kept: list[dict[str, Any]] = []
    if resume is not None:
        dest = resume
        previous = [json.loads(l) for l in (dest / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        kept = [r for r in previous if not r.get("infra_error")]
        print(f"V/  RESUME     keeping {len(kept)} valid result(s), re-running {len(previous) - len(kept)} "
              f"infra error(s) and anything missing", file=out, flush=True)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        dest = (out_dir or Path.cwd() / CONFIG_DIR / "bench") / run_id
        dest.mkdir(parents=True, exist_ok=True)
    done = {(r["task"], r["arm"], r.get("repeat", 1)) for r in kept}
    units = []
    for r in range(1, repeats + 1):
        for task in tasks:
            units += [("arm", task, a, k, r) for a, k in parsed if (task["id"], f"{a}:{k}", r) not in done]
            units += [("handoff", task, f, s, r) for f, s in pairs
                      if not all((task["id"], f"{f}>{s}:{k}", r) in done for k in ARM_KINDS)]
    results: list[dict[str, Any]] = list(kept)
    lock = threading.Lock()
    counter = {"n": 0}
    with (dest / "results.jsonl").open("w", encoding="utf-8") as rewrite:
        for row in kept:
            rewrite.write(json.dumps(row) + "\n")
    sink = (dest / "results.jsonl").open("a", encoding="utf-8")

    def do(unit) -> None:
        mode, task, a, b, r = unit
        if mode == "arm":
            rows = [run_one(suite, task, a, b, timeout=timeout, check_timeout=check_timeout, templates=templates)]
        else:
            rows = run_handoff(suite, task, a, b, timeout=timeout, check_timeout=check_timeout, templates=templates)
        with lock:
            for row in rows:
                row["repeat"] = r
                results.append(row)
                sink.write(json.dumps(row) + "\n")
            sink.flush()
            counter["n"] += 1
            print(f"V/  BENCH      [{counter['n']}/{len(units)}] {task['id']} "
                  + " ".join(f"{row['arm']}={'INFRA' if row.get('infra_error') else 'PASS' if row['passed'] else 'FAIL'}"
                             for row in rows)
                  + f" ({sum(row['wall_s'] for row in rows):.1f}s)", file=out, flush=True)

    try:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for future in [pool.submit(do, u) for u in units]:
                future.result()
    finally:
        sink.close()
    arm_names = [f"{a}:{k}" for a, k in parsed] + [f"{f}>{s}:{k}" for f, s in pairs for k in ARM_KINDS]
    summary = summarize(results, suite.get("name", suite_path.name), arm_names)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (dest / "report.md").write_text(render_report(summary), encoding="utf-8")
    summary["dir"] = str(dest)
    return summary


def summarize(results: list[dict[str, Any]], suite_name: str, arm_order: list[str]) -> dict[str, Any]:
    arms = {}
    for arm in arm_order:
        all_rows = [r for r in results if r["arm"] == arm]
        known = [r["cost_usd"] for r in all_rows if r["cost_usd"] is not None]   # spend is spend, infra or not
        rows = [r for r in all_rows if not r.get("infra_error")]
        passed = sum(r["passed"] for r in rows)
        handoff = [r for r in rows if "first_attempt_passed" in r]
        lo, hi = wilson(passed, len(rows))
        arms[arm] = {"runs": len(rows), "passed": passed, "pass_rate": passed / len(rows) if rows else 0.0,
                     "wilson95": [round(lo, 3), round(hi, 3)],
                     "median_wall_s": round(median(r["wall_s"] for r in rows), 2) if rows else None,
                     "known_cost_usd": round(sum(known), 4) if known else None,
                     "runs_with_unknown_cost": len(all_rows) - len(known),
                     "infra_errors": len(all_rows) - len(rows),
                     "median_prompt_chars": int(median(r["prompt_chars"] for r in rows)) if rows else None,
                     # only when every run's cost is known: money spent per task the gates actually verified
                     "cost_per_verified_usd": (round(sum(known) / passed, 4)
                                               if passed and known and len(known) == len(all_rows) else None)}
        if handoff:
            arms[arm].update(first_attempt_passed=sum(r["first_attempt_passed"] for r in handoff),
                             second_attempts=sum(r["attempts"] == 2 for r in handoff),
                             rescued=sum(r["rescued"] for r in handoff))
    paired = []
    for i, a in enumerate(arm_order):
        for b in arm_order[i + 1:]:
            wins = losses = ties = 0
            keys = {(r["task"], r["repeat"]) for r in results}
            for key in sorted(keys):
                ra = next((r for r in results if r["arm"] == a and (r["task"], r["repeat"]) == key), None)
                rb = next((r for r in results if r["arm"] == b and (r["task"], r["repeat"]) == key), None)
                if ra is None or rb is None or ra.get("infra_error") or rb.get("infra_error"):
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
                       ["Arms agent:kind are single attempts; A>B arms share attempt 1 and differ only in "
                        "how agent B is briefed after a failure.",
                        "Cost is provider-reported where the agent template parses it; otherwise unknown, not zero."]}


def render_report(summary: dict[str, Any]) -> str:
    lines = [f"# V/COMMAND benchmark — {summary['suite']}", "",
             f"{summary['tasks']} task(s), {summary['results']} run(s).", "",
             "| Arm | Passed | Pass rate | Wilson 95% | Median wall (s) | Known cost (USD) | Cost per verified task (USD) | Unknown-cost runs | Median prompt chars | Infra errors (excluded) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm, s in summary["arms"].items():
        cost = "unknown" if s["known_cost_usd"] is None else f"{s['known_cost_usd']:.4f}"
        lines.append(f"| {arm} | {s['passed']}/{s['runs']} | {s['pass_rate']:.0%} | "
                     f"{s['wilson95'][0]:.0%}–{s['wilson95'][1]:.0%} | {s['median_wall_s']} | {cost} | "
                     f"{'n/a' if s.get('cost_per_verified_usd') is None else format(s['cost_per_verified_usd'], '.4f')} | "
                     f"{s['runs_with_unknown_cost']} | {s['median_prompt_chars']} | {s.get('infra_errors', 0)} |")
    handoff = {a: s for a, s in summary["arms"].items() if "rescued" in s}
    if handoff:
        lines += ["", "## Handoff after a failed first attempt", "",
                  "| Arm | First attempt passed | Second attempts | Rescued by agent B |", "|---|---|---|---|"]
        for arm, s in handoff.items():
            lines.append(f"| {arm} | {s['first_attempt_passed']}/{s['runs']} | {s['second_attempts']} | "
                         f"{s['rescued']}/{s['second_attempts'] or 0} |")
    if summary["paired"]:
        lines += ["", "## Paired (same task, same repeat)", ""]
        for p in summary["paired"]:
            lines.append(f"- {p['a']} only: {p['a_only_passed']} · {p['b']} only: {p['b_only_passed']} · "
                         f"same outcome: {p['same']}")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in summary["caveats"]]
    return "\n".join(lines) + "\n"
