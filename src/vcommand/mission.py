"""Mission: say the goal once, see the plan and its cost range, tune who does what, approve, run.

    vcmd mission new "Add password reset"   # enhancer turns one sentence into a brief + questions + steps
    vcmd mission                            # plan, who does what, cost / token / time ranges
    vcmd mission share claude=60 codex=40   # sliders: share of the work per agent
    vcmd mission budget 2.50                # hard stop
    vcmd mission approve                    # nothing runs before this
    vcmd mission run                        # step by step, gates after every step, handoff at the end

Honesty rules (the product's principles apply to the numbers):

* An estimate is a **range from your own history** (`.vcommand/mission_history.jsonl`, then the evidence
  of past runs). With no history for an agent it says "no data" — never an invented number. You may state
  an assumption yourself (config `mission.assume`), and it is labelled as one.
* The budget is a hard stop, because an estimate before a run is only an estimate.
* The enhancer is read-only. It writes questions instead of guessing; you approve (or edit) the brief.
* "Done" is the gates plus the done condition. A mission that cannot be verified says so.

Standard library only.
"""
from __future__ import annotations

from pathlib import Path
from statistics import median
import io
import json
import re
import sys
import threading
import time
import uuid
from typing import Any, TextIO

from .core import CONFIG_DIR, list_evidence, load_config, utc_now

MISSION_FILE = "mission.json"
HISTORY_FILE = "mission_history.jsonl"
REPORT_FILE = "mission_report.md"
UNITS = {"easy": 1, "medium": 2, "hard": 3}
MAX_STEPS = 12
_LOCK = threading.Lock()

ENHANCER_INSTRUCTION = """ROLE: MISSION ENHANCER. Do not edit, create or delete any file and do not run commands that change
anything. Read the repository as needed, then turn the developer's goal into a precise, checkable mission.

Reply with ONLY one JSON object (no prose, no code fence):
{"brief": {"scope": "<what is in scope; name files or directories>",
           "constraints": ["<rule every agent must obey>", ...],
           "done": "<observable done condition the acceptance gates or a command can check>"},
 "questions": ["<question only the developer can answer>", ...],
 "assumptions": ["<assumption you made because the goal did not say>", ...],
 "steps": [{"title": "<one verifiable step>", "difficulty": "easy|medium|hard", "detail": "<files, approach, how it is checked>"}, ...]}

Rules:
- Do not invent requirements. When the goal is ambiguous, put the question in "questions" (max 5) AND state
  the assumption you would otherwise make in "assumptions".
- 1 to 8 steps, in execution order, each small enough to verify on its own; "hard" = real design or
  debugging, "easy" = mechanical.
- Reuse what the repository already does (its test style, helpers, naming). Name concrete files.
- The acceptance gates in the context frame are fixed; say in "done" what extra behavior must hold.

DEVELOPER'S GOAL:
"""


def _path(root: Path) -> Path:
    return root / CONFIG_DIR / MISSION_FILE


def load_mission(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_mission(root: Path, m: dict[str, Any]) -> None:
    with _LOCK:
        path = _path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)


def _require(root: Path) -> dict[str, Any]:
    m = load_mission(root)
    if m is None:
        raise FileNotFoundError('No mission. Start one: vcmd mission new "<goal>"')
    return m


def _line(text: Any, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


# ---------------------------------------------------------------- plan parsing

def parse_plan(text: str) -> dict[str, Any] | None:
    """Pull the enhancer's JSON out of its reply (tolerates a code fence or a sentence around it)."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    brief = data.get("brief") if isinstance(data.get("brief"), dict) else {}
    steps = []
    for raw in data.get("steps") or []:
        if isinstance(raw, dict) and raw.get("title"):
            diff = str(raw.get("difficulty", "medium")).lower()
            steps.append({"title": _line(raw["title"], 160), "difficulty": diff if diff in UNITS else "medium",
                          "detail": _line(raw.get("detail", ""), 600)})
    return {
        "brief": {"scope": _line(brief["scope"], 500) if brief.get("scope") else None,
                  "constraints": [_line(c, 300) for c in brief.get("constraints") or [] if str(c).strip()][:8],
                  "done": _line(brief["done"], 600) if brief.get("done") else None},
        "questions": [_line(q, 400) for q in data.get("questions") or [] if str(q).strip()][:5],
        "assumptions": [_line(a, 400) for a in data.get("assumptions") or [] if str(a).strip()][:8],
        "steps": steps[:MAX_STEPS],
    }


# ---------------------------------------------------------------- creating a mission

def new_mission(root: Path, goal: str, *, agents: list[str] | None = None, enhancer: str | None = None,
                timeout: int = 600, out: TextIO | None = None) -> dict[str, Any]:
    """Draft a mission. With an enhancer agent the goal becomes brief + questions + steps; without one
    (or when it fails) the mission is the goal as a single step — still valid, just less prepared."""
    from .adapters import agent_templates, resolve_agent
    out = out or sys.stdout
    cfg = load_config(root)
    goal = _line(goal, 500)
    if not goal:
        raise ValueError("Empty goal")
    templates = agent_templates(cfg)
    roles = cfg.get("roles") or {}
    agents = agents or _agents_from_roles(roles) or []
    for a in agents + ([enhancer] if enhancer else []):
        resolve_agent(templates, a)
    plan = None
    enhancer_note = None
    previous = load_mission(root)
    if previous and previous.get("status") == "running":
        raise ValueError("A mission is running; wait for it or stop it first")
    _clear_own_task(root, previous)  # a finished mission's task must not colour the next plan
    if enhancer:
        from .workflow import _text_role
        for attempt in (1, 2):  # models occasionally answer in prose: one retry with the format restated
            retry = "" if attempt == 1 else ("\n\n(Your previous reply was not a single valid JSON object. "
                                             "Reply with ONLY the JSON object described above.)")
            text, item = _text_role(root, enhancer, ENHANCER_INSTRUCTION + goal + retry, out=out, timeout=timeout,
                                    label="enhance", quiet=True)
            plan = parse_plan(text or "")
            if plan is not None and plan["steps"]:
                break
            plan = None
        if plan is None:
            enhancer_note = f"{enhancer} returned no usable plan twice (status {item['status']}); using the goal as one step"
            print(f"V/  MISSION    {enhancer_note}", file=out)
    if plan is None:
        plan = {"brief": {"scope": None, "constraints": [], "done": None}, "questions": [], "assumptions": [],
                "steps": [{"title": goal, "difficulty": "medium", "detail": ""}]}
    steps = [{"n": i, "title": s["title"], "difficulty": s["difficulty"], "detail": s["detail"], "agent": None,
              "pinned": False, "status": "pending", "actual": None} for i, s in enumerate(plan["steps"], 1)]
    m = {"schema_version": 1, "id": "mis-" + uuid.uuid4().hex[:6], "status": "draft", "goal": goal,
         "created_at_utc": utc_now(), "enhancer": enhancer if plan is not None and not enhancer_note else None,
         "enhancer_note": enhancer_note, "brief": plan["brief"], "assumptions": plan["assumptions"],
         "questions": [{"q": q, "answer": None} for q in plan["questions"]], "steps": steps,
         "agents": agents, "shares": {a: 100 // max(1, len(agents)) for a in agents}, "pins": {},
         "budget_usd": None, "caps": {}, "task_id": None}
    save_mission(root, m)
    return m


def _agents_from_roles(roles: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("plan", "build", "review"):
        v = roles.get(key)
        for a in ([v] if isinstance(v, str) else v or []):
            if isinstance(a, str) and a not in out:
                out.append(a)
    return out


# ---------------------------------------------------------------- history and estimates

def _history(root: Path) -> list[dict[str, Any]]:
    path = root / CONFIG_DIR / HISTORY_FILE
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and r.get("agent"):
                rows.append(r)
    return rows


def _tokens(cost: dict[str, Any] | None) -> int | None:
    u = (cost or {}).get("usage")
    if not isinstance(u, dict):
        return None
    vals = [u.get(k) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                               "cache_read_input_tokens", "cached_input_tokens") if isinstance(u.get(k), int)]
    return sum(vals) if vals else None


def all_history(root: Path) -> list[dict[str, Any]]:
    """Mission history (with step difficulty) plus evidence of other runs; a run is never counted twice."""
    mission_rows = _history(root)
    known = {r.get("run_id") for r in mission_rows if r.get("run_id")}
    return mission_rows + [e for e in _evidence_rows(root) if e["run_id"] not in known]


def _evidence_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for r in list_evidence(root):
        agent = r.get("agent")
        if not agent or ":" in agent or r.get("text_role") or r["action"].get("external"):
            continue
        cost = r.get("cost") or {}
        rows.append({"run_id": r["id"], "agent": agent, "difficulty": None, "usd": cost.get("amount"), "tokens": _tokens(cost),
                     "seconds": (r["action"].get("duration_ms") or 0) / 1000 or None, "passed": r["status"] in
                     {"verified_by_configured_checks", "unverified"}, "source": "evidence"})
    return rows


def _band(values: list[float]) -> list[float] | None:
    """[low, typical, high] from observed values: quartiles with 4+ samples, min/median/max below."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) >= 4:
        q = _quartiles(vals)
        return [q[0], median(vals), q[2]]
    return [vals[0], median(vals), vals[-1]]


def _quartiles(vals: list[float]) -> list[float]:
    from statistics import quantiles
    return quantiles(vals, n=4, method="inclusive")


def step_estimate(root: Path, cfg: dict[str, Any], agent: str, difficulty: str,
                  history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Cost / tokens / time range for one step by `agent`, from the most specific data available."""
    hist = history if history is not None else all_history(root)
    own = [h for h in hist if h["agent"] == agent]
    tiers = [("this agent on %s steps" % difficulty, [h for h in own if h.get("difficulty") == difficulty]),
             ("this agent's past runs", own)]
    for label, rows in tiers:
        usd = _band([h.get("usd") for h in rows])
        if usd is not None and len(rows) >= 1:
            return {"agent": agent, "usd": usd, "tokens": _band([h.get("tokens") for h in rows]),
                    "seconds": _band([h.get("seconds") for h in rows]),
                    "basis": f"history: {label}, {len(rows)} run(s)" + (" — too few for a reliable range" if len(rows) < 4 else ""),
                    "samples": len(rows)}
    assumed = ((cfg.get("mission") or {}).get("assume") or {}).get(agent)
    if isinstance(assumed, dict) and isinstance(assumed.get("usd_per_step"), (int, float)):
        v = float(assumed["usd_per_step"])
        return {"agent": agent, "usd": [v, v, v], "tokens": None, "seconds": None,
                "basis": "your assumption (config mission.assume)", "samples": 0}
    return {"agent": agent, "usd": None, "tokens": None, "seconds": None, "basis": "no data", "samples": 0}


# ---------------------------------------------------------------- allocation (the sliders)

def allocate(steps: list[dict[str, Any]], shares: dict[str, int], pins: dict[str, str] | None = None) -> dict[int, str]:
    """Assign steps to agents so that work units (easy 1, medium 2, hard 3) follow the shares.

    Pinned steps go first; then the hardest steps, each to the agent furthest below its target."""
    pins = pins or {}
    active = {a: w for a, w in shares.items() if w > 0}
    if not active:
        raise ValueError("Give at least one agent a share above 0")
    total_share = sum(active.values())
    units = {s["n"]: UNITS.get(s["difficulty"], 2) for s in steps}
    total_units = sum(units.values())
    target = {a: total_units * w / total_share for a, w in active.items()}
    got = {a: 0.0 for a in active}
    out: dict[int, str] = {}
    for s in steps:
        pin = pins.get(str(s["n"]))
        if pin:
            out[s["n"]] = pin
            if pin in got:
                got[pin] += units[s["n"]]
    for s in sorted((s for s in steps if s["n"] not in out), key=lambda s: (-units[s["n"]], s["n"])):
        agent = max(active, key=lambda a: (target[a] - got[a], active[a], a))
        out[s["n"]] = agent
        got[agent] += units[s["n"]]
    return out


def view(root: Path, m: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything a screen needs: assignment, per-agent shares, estimates, warnings."""
    m = m or _require(root)
    cfg = load_config(root)
    hist = all_history(root)
    assign = allocate(m["steps"], m["shares"], m["pins"]) if m["agents"] else {}
    if m["status"] in {"running", "done", "failed", "stopped"}:  # the plan as it was run
        assign = {s["n"]: s.get("agent") or assign.get(s["n"]) for s in m["steps"]}
    per_step, agents = [], {}
    units_total = sum(UNITS.get(s["difficulty"], 2) for s in m["steps"]) or 1
    for s in m["steps"]:
        agent = assign.get(s["n"])
        est = step_estimate(root, cfg, agent, s["difficulty"], hist) if agent else None
        per_step.append({**{k: s[k] for k in ("n", "title", "difficulty", "detail", "status", "pinned", "actual")},
                         "agent": agent, "estimate": est})
        if agent:
            a = agents.setdefault(agent, {"steps": 0, "units": 0, "usd": [0.0, 0.0, 0.0], "usd_known": 0,
                                          "tokens": [0, 0, 0], "tokens_known": 0, "seconds": [0.0, 0.0, 0.0],
                                          "seconds_known": 0})
            a["steps"] += 1
            a["units"] += UNITS.get(s["difficulty"], 2)
            for key in ("usd", "tokens", "seconds"):
                if est and est[key]:
                    a[key] = [x + y for x, y in zip(a[key], est[key])]
                    a[key + "_known"] += 1
    for name, a in agents.items():
        a["work_share"] = round(100 * a["units"] / units_total)
        for key in ("usd", "tokens", "seconds"):
            if a[key + "_known"] < a["steps"]:
                a[key + "_missing"] = a["steps"] - a[key + "_known"]
    total = {"steps": len(m["steps"])}
    for key in ("usd", "tokens", "seconds"):
        parts = [a[key] for a in agents.values() if a[key + "_known"]]
        total[key] = [sum(p[i] for p in parts) for i in range(3)] if parts else None
        total[key + "_missing"] = sum(a["steps"] - a[key + "_known"] for a in agents.values())
    warnings = []
    if not m["agents"]:
        warnings.append("No agents chosen: vcmd mission agents <name> [...]")
    if total["usd"] is not None and m.get("budget_usd") and total["usd"][2] > m["budget_usd"]:
        warnings.append(f"The high end of the estimate (${total['usd'][2]:.2f}) is above your budget "
                        f"(${m['budget_usd']:.2f}); the budget will stop the run.")
    if total["usd_missing"]:
        warnings.append(f"{total['usd_missing']} step(s) have no cost data yet (unknown is not zero); "
                        f"the first run builds your history.")
    if not cfg["checks"]:
        warnings.append("No acceptance gates configured: the result can only be 'unverified'. vcmd check add -- <command>")
    open_q = [q for q in m["questions"] if not q["answer"]]
    if open_q:
        warnings.append(f"{len(open_q)} question(s) unanswered; approve with --skip-questions to accept the assumptions.")
    return {"id": m["id"], "status": m["status"], "goal": m["goal"], "brief": m["brief"],
            "assumptions": m["assumptions"], "questions": m["questions"], "steps": per_step, "agents": agents,
            "shares": m["shares"], "budget_usd": m.get("budget_usd"), "caps": m.get("caps") or {},
            "total": total, "warnings": warnings, "enhancer": m.get("enhancer"), "enhancer_note": m.get("enhancer_note"),
            "all_agents": sorted(m["agents"])}


# ---------------------------------------------------------------- editing a draft

def _draft(root: Path) -> dict[str, Any]:
    m = _require(root)
    if m["status"] not in {"draft", "approved"}:
        raise ValueError(f"Mission is {m['status']}; start a new one to change the plan")
    if m["status"] == "approved":
        m["status"] = "draft"  # any change needs a fresh approval
    return m


def set_agents(root: Path, agents: list[str]) -> dict[str, Any]:
    from .adapters import agent_templates, resolve_agent
    templates = agent_templates(load_config(root))
    for a in agents:
        resolve_agent(templates, a)
    m = _draft(root)
    m["agents"] = list(dict.fromkeys(agents))
    m["shares"] = {a: m["shares"].get(a, 100 // max(1, len(m["agents"]))) for a in m["agents"]}
    m["pins"] = {k: v for k, v in m["pins"].items() if v in m["agents"]}
    save_mission(root, m)
    return m


def set_shares(root: Path, shares: dict[str, int]) -> dict[str, Any]:
    m = _draft(root)
    for a, w in shares.items():
        if a not in m["agents"]:
            raise ValueError(f"{a} is not in this mission (vcmd mission agents …)")
        if not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= 100:
            raise ValueError("A share is a whole number from 0 to 100")
    m["shares"] = {**m["shares"], **shares}
    if not any(w > 0 for w in m["shares"].values()):
        raise ValueError("Give at least one agent a share above 0")
    save_mission(root, m)
    return m


def pin_step(root: Path, n: int, agent: str | None) -> dict[str, Any]:
    m = _draft(root)
    if not any(s["n"] == n for s in m["steps"]):
        raise ValueError(f"No step {n}")
    if agent and agent not in m["agents"]:
        raise ValueError(f"{agent} is not in this mission")
    pins = dict(m["pins"])
    pins.pop(str(n), None)
    if agent:
        pins[str(n)] = agent
    m["pins"] = pins
    for s in m["steps"]:
        s["pinned"] = str(s["n"]) in pins
    save_mission(root, m)
    return m


def set_budget(root: Path, usd: float | None, agent: str | None = None) -> dict[str, Any]:
    m = _draft(root)
    if usd is not None and (not isinstance(usd, (int, float)) or usd <= 0):
        raise ValueError("Budget must be a positive number of USD")
    if agent:
        if agent not in m["agents"]:
            raise ValueError(f"{agent} is not in this mission")
        caps = dict(m["caps"])
        caps.pop(agent, None)
        if usd is not None:
            caps[agent] = float(usd)
        m["caps"] = caps
    else:
        m["budget_usd"] = None if usd is None else float(usd)
    save_mission(root, m)
    return m


def answer_question(root: Path, n: int, text: str) -> dict[str, Any]:
    m = _draft(root)
    if not 1 <= n <= len(m["questions"]):
        raise ValueError(f"No question {n}")
    m["questions"][n - 1]["answer"] = _line(text)
    save_mission(root, m)
    return m


def edit_step(root: Path, n: int, *, title: str | None = None, difficulty: str | None = None,
              detail: str | None = None) -> dict[str, Any]:
    m = _draft(root)
    step = next((s for s in m["steps"] if s["n"] == n), None)
    if step is None:
        raise ValueError(f"No step {n}")
    if difficulty is not None:
        if difficulty not in UNITS:
            raise ValueError("difficulty is easy, medium or hard")
        step["difficulty"] = difficulty
    if title:
        step["title"] = _line(title, 160)
    if detail is not None:
        step["detail"] = _line(detail, 600)
    save_mission(root, m)
    return m


def _clear_own_task(root: Path, m: dict[str, Any] | None) -> None:
    """The task a mission created goes away with it: a stale task would mislead the next enhancer."""
    from .core import current_task_id
    from .state import clear_task
    if m and m.get("task_id") and m["task_id"] == current_task_id(root):
        clear_task(root)


def discard(root: Path) -> bool:
    path = _path(root)
    if path.exists():
        m = load_mission(root)
        if m and m.get("status") == "running":
            raise ValueError("The mission is running; stop it first")
        _clear_own_task(root, m)
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------- approval and run

def approve(root: Path, *, skip_questions: bool = False) -> dict[str, Any]:
    from .state import start_task
    from .workflow import normalize_brief, add_decision
    m = _require(root)
    if m["status"] not in {"draft", "approved"}:
        raise ValueError(f"Mission is {m['status']}")
    if not m["agents"]:
        raise ValueError("Choose the agents first: vcmd mission agents claude codex")
    if [q for q in m["questions"] if not q["answer"]] and not skip_questions:
        raise ValueError("Answer the open questions (vcmd mission answer N \"…\") or approve with --skip-questions "
                         "to accept the stated assumptions")
    assign = allocate(m["steps"], m["shares"], m["pins"])
    for s in m["steps"]:
        s["agent"] = assign[s["n"]]
    brief = dict(m["brief"])
    constraints = list(brief.get("constraints") or [])
    constraints += [f"Decision on '{q['q']}': {q['answer']}" for q in m["questions"] if q["answer"]]
    constraints += [f"Assumption (not confirmed): {a}" for a in m["assumptions"]]
    task = start_task(root, m["goal"], normalize_brief(brief.get("scope"), constraints[:12], brief.get("done"), None))
    m.update(status="approved", approved_at_utc=utc_now(), task_id=task["id"])
    save_mission(root, m)
    add_decision(root, f"Mission {m['id']} approved: {len(m['steps'])} step(s), agents "
                       + ", ".join(f"{a} {m['shares'].get(a, 0)}%" for a in m["agents"] if m["shares"].get(a)),
                 agent="developer")
    return m


def _known_spend(root: Path, since_ids: set[str]) -> tuple[float, int]:
    runs = [r for r in list_evidence(root) if r["id"] not in since_ids and not r["action"].get("external")]
    known = [r["cost"]["amount"] for r in runs if (r.get("cost") or {}).get("amount") is not None]
    return float(sum(known)), len(runs) - len(known)


def _append_history(root: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with _LOCK:
        with (root / CONFIG_DIR / HISTORY_FILE).open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_mission(root: Path, *, attempts: int = 2, timeout: int = 3600, check_timeout: int = 600,
                review: bool = False, out: TextIO | None = None, stop: threading.Event | None = None) -> int:
    """Run the approved mission step by step. Exit 0 = every step verified, 1 = stopped, 3 = needs you."""
    from .adapters import run_agents, STOPPED_FOR_HUMAN
    from .state import complete_step, set_next_step
    from .workflow import write_handoff, _text_role, parse_verdict, REVIEW_INSTRUCTION, _diff_text, add_todo
    out = out or sys.stdout
    m = _require(root)
    if m["status"] not in {"approved", "running", "stopped"}:
        raise ValueError(f"Mission is {m['status']}: approve it first (vcmd mission approve)")
    cfg = load_config(root)
    seen = {r["id"] for r in list_evidence(root)}
    if m["status"] != "running":
        m["started_at_utc"] = m.get("started_at_utc") or utc_now()
    m["status"] = "running"
    save_mission(root, m)
    est_view = view(root, m)
    code = 0
    pending = [s for s in m["steps"] if s["status"] != "done"]
    print(f"V/  MISSION    {m['id']}: {len(pending)} step(s) to run", file=out, flush=True)
    for s in pending:
        if stop is not None and stop.is_set():
            code = 1
            break
        spent, _ = _known_spend(root, seen)
        if m.get("budget_usd") and spent >= m["budget_usd"]:
            print(f"V/  BUDGET     stopped before step {s['n']}: ${spent:.4f} of ${m['budget_usd']:.2f}", file=out)
            m["stop_reason"] = "budget"
            code = 1
            break
        agent = s.get("agent") or next(iter(m["agents"]))
        agent = _within_caps(root, m, agent, seen)
        others = [a for a in m["agents"] if a != agent and m["shares"].get(a, 0) > 0]
        order = [agent] + others
        before = {r["id"] for r in list_evidence(root)}
        s["status"] = "running"
        save_mission(root, m)
        instruction = (f"MISSION STEP {s['n']}/{len(m['steps'])} ({s['difficulty']}): {s['title']}\n"
                       + (f"{s['detail']}\n" if s["detail"] else "")
                       + "Do only this step. Earlier steps are done; do not start later ones. "
                         "The acceptance gates must pass when you finish.")
        t0 = time.time()
        print(f"\nV/  STEP       {s['n']}/{len(m['steps'])} [{s['difficulty']}] {s['title']} -> {agent}",
              file=out, flush=True)
        rc = run_agents(root, order, attempts=min(attempts, len(order)) if len(order) > 1 else attempts,
                        instruction=instruction, timeout=timeout, check_timeout=check_timeout,
                        budget_usd=None, out=out, notify_result=False)
        runs = [r for r in list_evidence(root) if r["id"] not in before and not r["action"].get("external")]
        rows, usd, tokens = [], [], []
        for r in runs:
            cost = r.get("cost") or {}
            rows.append({"run_id": r["id"], "agent": r.get("agent"), "difficulty": s["difficulty"], "usd": cost.get("amount"),
                         "tokens": _tokens(cost), "seconds": (r["action"].get("duration_ms") or 0) / 1000 or None,
                         "passed": r["status"] in {"verified_by_configured_checks", "unverified"},
                         "mission": m["id"], "step": s["n"], "at_utc": utc_now(), "source": "mission"})
            usd.append(cost.get("amount"))
            tokens.append(_tokens(cost))
        _append_history(root, rows)
        s["actual"] = {"agents": sorted({r["agent"] for r in rows if r["agent"]}), "attempts": len(runs),
                       "usd": round(sum(u for u in usd if u is not None), 6) if any(u is not None for u in usd) else None,
                       "usd_unknown_runs": sum(u is None for u in usd),
                       "tokens": sum(t for t in tokens if t is not None) if any(t is not None for t in tokens) else None,
                       "seconds": round(time.time() - t0, 1),
                       "status": runs[-1]["status"] if runs else "not run"}
        if rc == 0:
            s["status"] = "done"
            complete_step(root, f"Step {s['n']}: {s['title']}")
            nxt = next((x for x in m["steps"] if x["status"] not in {"done"} and x["n"] != s["n"]), None)
            if nxt:
                set_next_step(root, f"Step {nxt['n']}: {nxt['title']}")
            save_mission(root, m)
            continue
        s["status"] = "needs_you" if rc == STOPPED_FOR_HUMAN else "failed"
        m["stop_reason"] = "needs you (approval or question)" if rc == STOPPED_FOR_HUMAN else \
            f"step {s['n']} did not pass the gates"
        code = rc
        save_mission(root, m)
        break
    m["finished_at_utc"] = utc_now()
    if all(s["status"] == "done" for s in m["steps"]):
        m["status"] = "done"
        if review and (cfg.get("roles") or {}).get("review") and code == 0:
            reviewer = cfg["roles"]["review"]
            text, _ = _text_role(root, reviewer, REVIEW_INSTRUCTION + "\n\nCHANGE UNDER REVIEW (git diff HEAD):\n```diff\n"
                                 + _diff_text(root) + "\n```", out=out, timeout=timeout, label="review")
            verdict = parse_verdict(text or "")
            m["review"] = {"agent": reviewer, "verdict": verdict, "text": (text or "")[:4000]}
            if verdict != "APPROVE":
                add_todo(root, f"Mission review by {reviewer}: {verdict or 'no verdict'} (.vcommand/mission_report.md)")
                code = 1 if verdict == "CHANGES" else code
    else:
        m["status"] = "stopped" if code in (1, STOPPED_FOR_HUMAN) else "failed"
    save_mission(root, m)
    report = render_report(root, m, est_view)
    (root / CONFIG_DIR / REPORT_FILE).write_text(report, encoding="utf-8")
    write_handoff(root)
    print("\n" + report, file=out)
    from .channels import notify
    notify(root, "verified" if m["status"] == "done" and code == 0 else "failed",
           f"Mission {m['id']} {m['status']}: {m['goal'][:120]}\n" + _totals_line(m))
    return code


def _within_caps(root: Path, m: dict[str, Any], agent: str, seen: set[str]) -> str:
    """Per-agent cost caps: past its cap an agent hands its steps to the next agent with room."""
    caps = m.get("caps") or {}
    if agent not in caps:
        return agent
    spent = sum((r.get("cost") or {}).get("amount") or 0 for r in list_evidence(root)
                if r["id"] not in seen and r.get("agent") == agent)
    if spent < caps[agent]:
        return agent
    for other in m["agents"]:
        if other != agent and m["shares"].get(other, 0) > 0 and other not in caps:
            return other
    return agent


def _totals_line(m: dict[str, Any]) -> str:
    done = sum(s["status"] == "done" for s in m["steps"])
    usd = [s["actual"]["usd"] for s in m["steps"] if s.get("actual") and s["actual"].get("usd") is not None]
    return f"{done}/{len(m['steps'])} steps verified" + (f", known spend ${sum(usd):.4f}" if usd else "")


def _range(b: list[float] | None, fmt: str) -> str:
    if not b:
        return "no data"
    lo, mid, hi = b
    return f"{fmt % lo}–{fmt % hi} (typ. {fmt % mid})"


def render_report(root: Path, m: dict[str, Any], est: dict[str, Any] | None = None) -> str:
    est = est or view(root, m)
    lines = [f"# Mission {m['id']}: {m['status']}", f"Goal: {m['goal']}", ""]
    lines.append("| Step | Agent | Result | Estimate | Actual |")
    lines.append("|---|---|---|---|---|")
    for s, e in zip(m["steps"], est["steps"]):
        a = s.get("actual") or {}
        e_usd = _range((e.get("estimate") or {}).get("usd"), "$%.3f")
        a_usd = "unknown" if a.get("usd") is None and a else (f"${a['usd']:.4f}" if a else "–")
        lines.append(f"| {s['n']}. {s['title'][:60]} | {(', '.join(a.get('agents', [])) or s.get('agent') or '–')} | "
                     f"{s['status']} | {e_usd} | {a_usd}" + (f", {a['seconds']}s" if a else "") + " |")
    usd = [s["actual"]["usd"] for s in m["steps"] if s.get("actual") and s["actual"].get("usd") is not None]
    unknown = sum(s["actual"]["usd_unknown_runs"] for s in m["steps"] if s.get("actual"))
    lines += ["", f"Total: {_totals_line(m)}" + (f"; {unknown} run(s) without a provider receipt (unknown is not $0)"
                                                  if unknown else ""),
              f"Estimate before approval: {_range((est['total'] or {}).get('usd'), '$%.2f')}"]
    if m.get("stop_reason"):
        lines.append(f"Stopped: {m['stop_reason']}. State is in .vcommand/handoff.md; continue with `vcmd mission run`.")
    if m.get("review"):
        lines.append(f"Review ({m['review']['agent']}): {m['review']['verdict'] or 'no verdict'}")
    return "\n".join(lines) + "\n"


def render_view(v: dict[str, Any]) -> str:
    out = [f"V/  MISSION {v['id']} [{v['status']}]", f"Goal: {v['goal']}", ""]
    b = v["brief"]
    if b.get("scope") or b.get("done") or b.get("constraints"):
        out.append("Brief" + (f"  (enhanced by {v['enhancer']})" if v.get("enhancer") else ""))
        out.append(f"  scope:       {b.get('scope') or 'not set'}")
        for c in b.get("constraints") or []:
            out.append(f"  constraint:  {c}")
        out.append(f"  done when:   {b.get('done') or 'all acceptance gates pass'}")
        out.append("")
    if v.get("enhancer_note"):
        out += [f"  note: {v['enhancer_note']}", ""]
    for i, q in enumerate(v["questions"], 1):
        out.append(f"Question {i}: {q['q']}" + (f"\n   -> {q['answer']}" if q["answer"] else "   (unanswered)"))
    for a in v["assumptions"]:
        out.append(f"Assumption: {a}")
    if v["questions"] or v["assumptions"]:
        out.append("")
    out.append("Plan")
    for s in v["steps"]:
        mark = {"done": "x", "failed": "!", "needs_you": "?", "running": ">"}.get(s["status"], " ")
        est = s.get("estimate")
        cost = f"  est {_range(est['usd'], '$%.3f')}" if est and est.get("usd") else ("  est: no data" if est else "")
        out.append(f" [{mark}] {s['n']}. ({s['difficulty']}) {s['title']}  -> {s.get('agent') or '-'}"
                   + (" [pinned]" if s["pinned"] else "") + cost)
    out += ["", "Who does what (sliders = share of the work, easy 1 · medium 2 · hard 3 units)"]
    for name in v["all_agents"]:
        a = v["agents"].get(name)
        share = v["shares"].get(name, 0)
        bar = "█" * (share // 5) + "░" * (20 - share // 5)
        got = f"{a['steps']} step(s), {a['work_share']}% of the work" if a else "no steps"
        cost = _range(a["usd"], "$%.2f") if a and a["usd_known"] else "no data"
        out.append(f"  {name:16} {bar} {share:3}%   {got:30} cost {cost}")
    t = v["total"]
    out += ["", f"Estimate: cost {_range(t['usd'], '$%.2f')}"
            + (f" · tokens {_range(t['tokens'], '%.0f')}" if t.get("tokens") else "")
            + (f" · time {_range(t['seconds'], '%.0f s')}" if t.get("seconds") else "")]
    out.append(f"Budget: " + (f"${v['budget_usd']:.2f} (hard stop)" if v["budget_usd"] else "none set (vcmd mission budget 2.50)"))
    for w in v["warnings"]:
        out.append(f"[!] {w}")
    nxt = {"draft": "Tune: vcmd mission share a=60 b=40 · vcmd mission budget N · then vcmd mission approve",
           "approved": "Approved. Start: vcmd mission run", "running": "Running…",
           "done": "Done. Report: .vcommand/mission_report.md",
           "stopped": "Stopped. Continue: vcmd mission run", "failed": "Failed. See .vcommand/mission_report.md"}[v["status"]]
    out += ["", nxt]
    return "\n".join(out)


def run_detached(root: Path, args: list[str]) -> int:
    """Start `vcmd mission run` in the background (dashboard Run button). Output goes to mission.log."""
    import subprocess
    log = (root / CONFIG_DIR / "mission.log").open("ab")
    proc = subprocess.Popen([sys.executable, "-m", "vcommand", "mission", "run", *args], cwd=root, stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return proc.pid
