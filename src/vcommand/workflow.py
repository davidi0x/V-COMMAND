"""Persistent agent workflow: operating brief, leave-behind artifacts, guardrails, role loop, wake.

A long-running agent workflow is a chain of short, fresh sessions that share state on disk:

    brief -> plan -> build/test -> review -> handoff.md saved -> a trigger wakes the next session

Everything here works the same for every agent V/COMMAND drives (Claude Code, Codex, OpenCode,
a local model, any CLI with a prompt argument):

* Operating brief (`vcmd task start/brief`): goal, scope, constraints, done condition, leave-behind.
* Leave-behinds in `.vcommand/`: `handoff.md` (5 lines, rewritten after every run, hook stop and
  pre-compaction), `decisions.md` (append-only, `vcmd decide`), `todo.md` (`vcmd todo`).
* Guardrails: deploys/publishing, database writes and bulk deletes need a human approval
  (`vcmd approve`). Enforced by the PreToolUse hook (Claude Code, Codex) and, as a backstop, by the
  claude-stream guard in the wrapper.
* Role loop (`vcmd loop`): planner, builder(s) and reviewer are any configured agents; the gates
  still judge the build, the reviewer can only withhold "done".
* Wake (`vcmd wake`, `vcmd schedule`): one entry point for cron, CI and webhooks that continues
  whatever is pending — the queue first, then the active task.

Standard library only. Nothing here stores prompts or agent transcripts; plan and review texts are
kept only because they are the workflow's leave-behinds, and only in the local `.vcommand/`.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, TextIO

from .core import CONFIG_DIR, list_evidence, load_config, utc_now

HANDOFF_FILE = "handoff.md"
DECISIONS_FILE = "decisions.md"
TODO_FILE = "todo.md"
PLAN_FILE = "plan.md"
REVIEW_FILE = "review.md"
APPROVALS_FILE = "approvals.json"
MAX_ITEM = 300
APPROVAL_TTL_S = 24 * 3600
_LOCK = threading.Lock()


def _path(root: Path, name: str) -> Path:
    return root / CONFIG_DIR / name


def _one_line(text: str, field: str, limit: int = MAX_ITEM) -> str:
    text = " ".join(str(text).split())
    if not text:
        raise ValueError(f"Empty {field}")
    return text[:limit]


# ---------------------------------------------------------------- operating brief

BRIEF_FIELDS = ("scope", "constraints", "done", "leave_behind")
DEFAULT_LEAVE_BEHIND = "handoff.md + evidence (diff, gate results); decisions in decisions.md"


def normalize_brief(scope: str | None = None, constraints: list[str] | None = None,
                    done: str | None = None, leave_behind: str | None = None) -> dict[str, Any]:
    return {
        "scope": _one_line(scope, "scope") if scope else None,
        "constraints": [_one_line(c, "constraint") for c in (constraints or []) if c and c.strip()],
        "done": _one_line(done, "done condition") if done else None,
        "leave_behind": _one_line(leave_behind, "leave-behind") if leave_behind else None,
    }


def brief_view(task: dict[str, Any] | None, gates: list[str]) -> dict[str, Any] | None:
    """The 5-field brief as agents see it; unset fields get explicit, honest defaults."""
    if task is None:
        return None
    b = task.get("brief") or {}
    return {
        "goal": task["goal"],
        "scope": b.get("scope") or "Not set: stay within what the goal requires; do not refactor unrelated code.",
        "constraints": list(b.get("constraints") or []),
        "done": b.get("done") or ("All acceptance gates pass." if gates else
                                  "Not set and no gates configured: the result can only be unverified."),
        "leave_behind": b.get("leave_behind") or DEFAULT_LEAVE_BEHIND,
    }


def render_brief(brief: dict[str, Any]) -> list[str]:
    out = ["## Operating brief (the goal is above)",
           f"- Scope: {brief['scope']}"]
    if brief["constraints"]:
        out.append("- Constraints:")
        out += [f"  - {c}" for c in brief["constraints"]]
    else:
        out.append("- Constraints: none recorded beyond the hard constraints below.")
    out += [f"- Done condition: {brief['done']}", f"- Leave behind: {brief['leave_behind']}", ""]
    return out


# ---------------------------------------------------------------- decisions.md / todo.md

def add_decision(root: Path, text: str, *, why: str | None = None, agent: str | None = None) -> str:
    load_config(root)
    line = f"- {utc_now()}" + (f" [{_one_line(agent, 'agent', 60)}]" if agent else "") + \
           f" {_one_line(text, 'decision')}" + (f" — because {_one_line(why, 'reason')}" if why else "")
    path = _path(root, DECISIONS_FILE)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if new:
                f.write("# Decisions\n\nAppend-only. Newest last. Written by `vcmd decide` and the role loop.\n\n")
            f.write(line + "\n")
    return line


def read_decisions(root: Path) -> list[str]:
    path = _path(root, DECISIONS_FILE)
    if not path.exists():
        return []
    return [l[2:] for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]


_TODO_RE = re.compile(r"^- \[( |x)\] (.*)$")


def read_todos(root: Path) -> list[dict[str, Any]]:
    path = _path(root, TODO_FILE)
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _TODO_RE.match(line)
        if m:
            items.append({"n": len(items) + 1, "done": m.group(1) == "x", "text": m.group(2)})
    return items


def _write_todos(root: Path, items: list[dict[str, Any]]) -> None:
    path = _path(root, TODO_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# To do\n\nOpen items for the next session. `vcmd todo add|done|list`.\n\n"
    body += "".join(f"- [{'x' if i['done'] else ' '}] {i['text']}\n" for i in items)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def add_todo(root: Path, text: str) -> dict[str, Any]:
    load_config(root)
    with _LOCK:
        items = read_todos(root)
        item = {"n": len(items) + 1, "done": False, "text": _one_line(text, "to-do item")}
        _write_todos(root, items + [item])
    return item


def complete_todo(root: Path, ref: str) -> dict[str, Any]:
    """Mark an item done by its number or by a unique substring."""
    with _LOCK:
        items = read_todos(root)
        if ref.isdigit() and 1 <= int(ref) <= len(items):
            hit = items[int(ref) - 1]
        else:
            matches = [i for i in items if not i["done"] and ref.lower() in i["text"].lower()]
            if len(matches) != 1:
                raise ValueError(f"No unique open to-do matches {ref!r} ({len(matches)} matches)")
            hit = matches[0]
        hit["done"] = True
        _write_todos(root, items)
    return hit


def open_todos(root: Path) -> list[str]:
    return [i["text"] for i in read_todos(root) if not i["done"]]


# ---------------------------------------------------------------- guardrails (ask before risky actions)

# Commands an agent must not run without a human approval. Matched against the whole shell command.
DEFAULT_RISK_RULES: list[dict[str, str]] = [
    {"rule": "deploy", "pattern": r"\b(vercel|netlify|firebase|wrangler|serverless|sls|flyctl|fly|railway|"
                                  r"heroku|eb|amplify|cdk|sam)\b[^\n|;&]*\b(deploy|publish|--prod|release)\b"},
    {"rule": "deploy", "pattern": r"\bkubectl\s+(apply|create|delete|replace|rollout|scale|set|patch|edit)\b"},
    {"rule": "deploy", "pattern": r"\bhelm\s+(install|upgrade|uninstall|rollback|delete)\b"},
    {"rule": "deploy", "pattern": r"\b(terraform|tofu)\s+(apply|destroy|import)\b|\bpulumi\s+(up|destroy|update)\b"},
    {"rule": "deploy", "pattern": r"\bgcloud\b[^\n|;&]*\b(deploy|instances\s+(create|delete))\b"},
    {"rule": "deploy", "pattern": r"\baws\s+(lambda\s+update-function-code|ecs\s+update-service|"
                                  r"cloudformation\s+(deploy|delete-stack|update-stack)|s3\s+sync)\b"},
    {"rule": "publish", "pattern": r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|"
                                   r"\bgem\s+push\b|\bdocker\s+push\b|\bgh\s+release\s+create\b|\bpoetry\s+publish\b"},
    {"rule": "publish", "pattern": r"\bgit\s+push\b"},
    {"rule": "db-write", "pattern": r"(?i)\b(psql|mysql|mariadb|sqlite3|sqlcmd|mongosh|mongo|cqlsh|clickhouse-client)\b"
                                    r"[^\n]*\b(insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+(table|database|schema|index)|"
                                    r"truncate|alter\s+table|create\s+table|grant|revoke|\.drop\(|\.delete(one|many)\()"},
    {"rule": "db-write", "pattern": r"(?i)\bredis-cli\b[^\n]*\b(flushall|flushdb|del|set|hset|expire)\b"},
    {"rule": "db-write", "pattern": r"\b(prisma\s+(migrate\s+(deploy|reset|dev)|db\s+(push|seed|execute))|"
                                    r"rails\s+db:(migrate|drop|reset|seed|setup|rollback)|rake\s+db:\w+|"
                                    r"alembic\s+(upgrade|downgrade)|knex\s+(migrate|seed):\w+|"
                                    r"sequelize(-cli)?\s+db:(migrate|seed|drop)|manage\.py\s+(migrate|flush|loaddata)|"
                                    r"drizzle-kit\s+(push|migrate)|supabase\s+db\s+(push|reset)|flyway\s+(migrate|clean))\b"},
    {"rule": "bulk-delete", "pattern": r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b"},
    {"rule": "bulk-delete", "pattern": r"\bfind\b[^\n|;&]*\s-delete\b|\bxargs\b[^\n|;&]*\brm\b"},
    {"rule": "bulk-delete", "pattern": r"\bgit\s+(clean\s+-[a-zA-Z]*f|reset\s+--hard|checkout\s+--\s+\.|restore\s+\.)"},
    {"rule": "bulk-delete", "pattern": r"\b(aws\s+s3\s+rm\b[^\n]*--recursive|gsutil\s+(-m\s+)?rm\s+-r|az\s+storage\s+blob\s+delete-batch)"},
    {"rule": "bulk-delete", "pattern": r"(?i)\b(Remove-Item\b[^\n]*-Recurse|rmdir\s+/s|del\s+/s|rd\s+/s)"},
]
# Recursive deletes of build output and caches are routine for agents.
DEFAULT_ALLOW = [r"^\s*rm\s+-[rRf]+\s+((\./)?(node_modules|dist|build|out|coverage|\.next|\.turbo|\.cache|"
                 r"__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|target|tmp|\.tmp)/?\s*)+$"]


def risk_rules(cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[re.Pattern]]:
    g = cfg.get("guardrails") or {}
    if g.get("enabled") is False:
        return [], []
    rules = [] if g.get("replace_defaults") else list(DEFAULT_RISK_RULES)
    rules += [r for r in g.get("rules", []) if isinstance(r, dict) and r.get("pattern")]
    compiled = []
    for r in rules:
        try:
            compiled.append({"rule": r.get("rule", "custom"), "re": re.compile(r["pattern"])})
        except re.error as error:
            raise ValueError(f"Invalid guardrail pattern {r['pattern']!r}: {error}") from error
    allow = []
    for p in DEFAULT_ALLOW + [a for a in g.get("allow", []) if isinstance(a, str)]:
        try:
            allow.append(re.compile(p))
        except re.error as error:
            raise ValueError(f"Invalid guardrail allow pattern {p!r}: {error}") from error
    return compiled, allow


def _segments(command: str) -> list[str]:
    """Split on unquoted `&&`, `||`, `;`, `|` and newlines (quotes and escapes respected)."""
    out, cur, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                cur.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch == "\\" and i + 1 < len(command):
            cur += [ch, command[i + 1]]
            i += 1
        elif ch in ";|\n&":
            if ch == "&" and command[i + 1:i + 2] != "&":
                cur.append(ch)  # background `&` or redirection like 2>&1
            else:
                out.append("".join(cur))
                cur = []
                if command[i + 1:i + 2] == ch:
                    i += 1
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


# Programs whose arguments are text, not actions: a commit message or a to-do that *mentions*
# `git push` is not a push. Found live: an agent's `vcmd todo add "... git push ..."` was flagged.
TEXT_ONLY_PROGRAMS = {"vcmd", "echo", "printf", "grep", "rg", "egrep", "fgrep", "true", "false", ":"}
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def _is_text_only(segment: str) -> bool:
    words = segment.split()
    while words and _ENV_ASSIGN.match(words[0]):
        words = words[1:]
    if not words:
        return True
    prog = words[0].rsplit("/", 1)[-1]
    if prog in TEXT_ONLY_PROGRAMS:
        return True
    return prog == "git" and len(words) > 1 and words[1] in {"commit", "log", "show", "status", "diff", "tag"} \
        and not (words[1] == "tag" and "-d" in words)


def classify_command(cfg: dict[str, Any], command: str) -> str | None:
    """Name of the risk rule a shell command matches, or None. Every `&&`/`;`/`|` segment is checked;
    segments that only print or record text (echo, vcmd, git commit -m …) are skipped."""
    rules, allow = risk_rules(cfg)
    for seg in _segments(command):
        if _is_text_only(seg) or any(a.search(seg) for a in allow):
            continue
        for r in rules:
            if r["re"].search(seg):
                return r["rule"]
    return None


def _norm(command: str) -> str:
    return " ".join(command.split())


def _approvals(root: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_path(root, APPROVALS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_approvals(root: Path, items: list[dict[str, Any]]) -> None:
    path = _path(root, APPROVALS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-200:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_approvals(root: Path) -> list[dict[str, Any]]:
    return _approvals(root)


def pending_approvals(root: Path) -> list[dict[str, Any]]:
    return [a for a in _approvals(root) if a.get("status") == "pending"]


def is_approved(root: Path, command: str, now: float | None = None) -> bool:
    """An approval is for one exact command (whitespace-normalized) and expires after a day."""
    now = time.time() if now is None else now
    cmd = _norm(command)
    return any(a.get("status") == "approved" and a.get("command") == cmd and a.get("expires_at", 0) > now
               for a in _approvals(root))


def request_approval(root: Path, command: str, rule: str, *, agent: str | None = None,
                     queue_task: str | None = None) -> dict[str, Any]:
    cmd = _norm(command)[:2000]
    with _LOCK:
        items = _approvals(root)
        for a in items:
            if a.get("status") == "pending" and a.get("command") == cmd:
                if queue_task and not a.get("queue_task"):
                    a["queue_task"] = queue_task
                    _save_approvals(root, items)
                return a
        item = {"id": "apr-" + uuid.uuid4().hex[:6], "command": cmd, "rule": rule, "agent": agent,
                "queue_task": queue_task, "status": "pending", "requested_at_utc": utc_now()}
        items.append(item)
        _save_approvals(root, items)
    from .channels import notify
    notify(root, "approval", f"{agent or 'An agent'} wants to run a {rule} command:\n{cmd[:500]}\n"
                             f"Approve: /approve {item['id']}   Deny: /deny {item['id']}\n"
                             f"(terminal: vcmd approve {item['id']})")
    return item


def decide_approval(root: Path, approval_id: str, approve: bool) -> dict[str, Any]:
    with _LOCK:
        items = _approvals(root)
        hit = next((a for a in items if a.get("id") == approval_id), None)
        if hit is None:
            raise ValueError(f"No approval request {approval_id}")
        if hit["status"] != "pending":
            raise ValueError(f"{approval_id} is already {hit['status']}")
        hit.update(status="approved" if approve else "denied", decided_at_utc=utc_now())
        if approve:
            hit["expires_at"] = time.time() + APPROVAL_TTL_S
        _save_approvals(root, items)
    add_decision(root, f"{'Approved' if approve else 'Denied'} {hit['rule']} command `{hit['command'][:160]}`"
                 + (f" requested by {hit['agent']}" if hit.get("agent") else ""), agent="developer")
    if hit.get("queue_task"):
        from . import queue as q
        try:
            q.answer(root, hit["queue_task"],
                     f"Approved: you may run `{hit['command']}` (exactly this command)." if approve else
                     f"Denied: do not run `{hit['command']}`; finish the task without it or ask again.")
        except (ValueError, FileNotFoundError):
            pass  # the task was answered or removed meanwhile
    return hit


def guard_command(root: Path, cfg: dict[str, Any], command: str, *, agent: str | None = None,
                  queue_task: str | None = None) -> dict[str, Any] | None:
    """None when the command may run; otherwise the (pending) approval request that blocks it."""
    rule = classify_command(cfg, command)
    if rule is None or is_approved(root, command):
        return None
    return request_approval(root, command, rule, agent=agent, queue_task=queue_task)


def blocked_message(req: dict[str, Any]) -> str:
    return (f"V/COMMAND guardrail: `{req['command'][:200]}` is a {req['rule']} action and needs the developer's "
            f"approval ({req['id']}). Do not run it or work around it (no alternative command for the same effect). "
            f"Continue with the rest of the task, record it with `vcmd todo add`, and stop. "
            f"The developer approves with: vcmd approve {req['id']}")


# ---------------------------------------------------------------- handoff.md (5-line leave-behind)

def _files_touched(root: Path, evidence: dict[str, Any] | None) -> list[str]:
    from .state import changed_files
    if evidence is not None:
        return changed_files(evidence)
    from .core import git_status
    return [l[3:] for l in (git_status(root) or []) if len(l) > 3 and not l[3:].startswith(CONFIG_DIR + "/")]


def build_handoff(root: Path, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    from .state import load_task, read_ledger
    cfg = load_config(root)
    task = load_task(root)
    runs = [r for r in list_evidence(root) if not r.get("text_role")] if evidence is None else [evidence]
    last = runs[-1] if runs else None
    gates = [" ".join(c) for c in cfg["checks"]]
    if last is None:
        state = "No runs yet."
    else:
        checks = last.get("checks") or []
        passed = sum(1 for c in checks if c.get("passed"))
        state = (f"{last['status']} — run {last['id']}" + (f" by {last['agent']}" if last.get("agent") else "")
                 + (f", gates {passed}/{len(checks)} passed" if checks else ", no gates ran"))
        if (last.get("action") or {}).get("killed"):
            state += f"; stopped: {last['action']['killed']}"
    issues = []
    if last is not None:
        issues += [f"gate failing: `{' '.join(c['argv'])}`" for c in last.get("checks") or [] if not c.get("passed")]
    issues += [f"approval pending {a['id']}: {a['rule']} `{a['command'][:120]}`" for a in pending_approvals(root)]
    issues += [f"todo: {t}" for t in open_todos(root)]
    ledger = read_ledger(root)
    if ledger and last is not None and last["status"] not in {"verified_by_configured_checks", "unverified"}:
        issues.append(f"do not repeat: {ledger[-1]['constraint']}")
    files = _files_touched(root, last)
    if task and task.get("next_step"):
        nxt = task["next_step"]
    elif last is not None and last["status"] == "verified_by_configured_checks" and not issues:
        nxt = "Gates pass. Review the diff and commit, or set the next step (`vcmd task next`)."
    elif last is not None and last["status"] in {"failed_verification", "failed"}:
        failing = [i for i in issues if i.startswith("gate failing")]
        nxt = f"Fix the cause of: {failing[0][14:]}" if failing else "Find why the last attempt failed (`vcmd evidence`)."
    else:
        nxt = "Not set — decide from the goal (`vcmd task next \"<step>\"`)."
    return {
        "generated_at_utc": utc_now(),
        "goal": task["goal"] if task else "No active task (`vcmd task start`).",
        "current_state": state,
        "files_touched": files,
        "open_issues": issues,
        "next_step": nxt,
        "decisions": read_decisions(root)[-5:],
        "gates": gates,
    }


def render_handoff(h: dict[str, Any]) -> str:
    files = h["files_touched"]
    shown = ", ".join(f"`{f}`" for f in files[:12]) + (f" (+{len(files) - 12} more)" if len(files) > 12 else "")
    out = [f"# Handoff — {h['generated_at_utc']}", "",
           f"1. **Goal:** {h['goal']}",
           f"2. **Current state:** {h['current_state']}",
           f"3. **Files touched:** {shown or 'none'}",
           f"4. **Open issues:** " + ("; ".join(h['open_issues']) if h["open_issues"] else "none recorded"),
           f"5. **Next exact step:** {h['next_step']}", ""]
    if h["decisions"]:
        out += ["Recent decisions (`.vcommand/decisions.md`):"] + [f"- {d}" for d in h["decisions"]] + [""]
    out.append("_Written by V/COMMAND after every run, hook stop and context compaction. "
               "Start the next session from this file plus `vcmd frame`; not from chat history._")
    return "\n".join(out) + "\n"


def write_handoff(root: Path, evidence: dict[str, Any] | None = None) -> Path:
    text = render_handoff(build_handoff(root, evidence))
    path = _path(root, HANDOFF_FILE)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    return path


def read_handoff(root: Path) -> str | None:
    path = _path(root, HANDOFF_FILE)
    return path.read_text(encoding="utf-8") if path.exists() else None


# ---------------------------------------------------------------- evidence: diff

MAX_PATCH_BYTES = 1_000_000


def save_patch(root: Path, work: Path, run_id: str) -> dict[str, Any] | None:
    """Store `git diff HEAD` (plus untracked file names) of the work tree next to the evidence."""
    try:
        diff = subprocess.run(["git", "diff", "HEAD", "--no-color", "--", ".", f":(exclude){CONFIG_DIR}"],
                              cwd=work, capture_output=True, timeout=30, check=False)
        stat = subprocess.run(["git", "diff", "HEAD", "--numstat", "--", ".", f":(exclude){CONFIG_DIR}"],
                              cwd=work, capture_output=True, text=True, timeout=30, check=False)
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                   cwd=work, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if diff.returncode != 0:
        return None
    new_files = [f for f in untracked.stdout.splitlines() if f and not f.startswith(CONFIG_DIR + "/")]
    if not diff.stdout and not new_files:
        return {"path": None, "bytes": 0, "files": 0, "insertions": 0, "deletions": 0, "untracked": []}
    body = diff.stdout[:MAX_PATCH_BYTES]
    path = root / CONFIG_DIR / "runs" / f"{run_id}.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "".join(f"# untracked: {f}\n" for f in new_files[:200]).encode("utf-8")
    path.write_bytes(header + body)
    ins = dels = files = 0
    for line in stat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            files += 1
            ins += int(parts[0]) if parts[0].isdigit() else 0
            dels += int(parts[1]) if parts[1].isdigit() else 0
    return {"path": f"{CONFIG_DIR}/runs/{run_id}.patch", "bytes": len(diff.stdout), "files": files,
            "insertions": ins, "deletions": dels, "untracked": new_files[:50],
            "truncated": len(diff.stdout) > MAX_PATCH_BYTES,
            "sha256": hashlib.sha256(diff.stdout).hexdigest()}


# ---------------------------------------------------------------- role loop: plan -> build -> review

PLAN_INSTRUCTION = """ROLE: PLANNER. Do not edit, create or delete any project file and do not run commands that
change anything. Read what you need, then reply with a short numbered implementation plan (max 12 steps)
for the brief below: files to change, the order, how each step will be checked against the acceptance
gates, and risks. If you cannot reply in text, write the plan to VCOMMAND_PLAN.md in the repository root."""

BUILD_INSTRUCTION = """ROLE: BUILDER. Implement the plan below in small steps and run the relevant checks yourself.
Stay inside the brief's scope. Record decisions with `vcmd decide "<decision>" --why "<reason>"` and anything
left open with `vcmd todo add "<item>"`."""

REVIEW_INSTRUCTION = """ROLE: REVIEWER. Do not edit any file. Review the change below against the brief and the plan:
correctness, scope creep, missing tests, security, anything the gates cannot see. The acceptance gates
already passed. End your reply with exactly one line `VERDICT: APPROVE` or `VERDICT: CHANGES`, followed
(for CHANGES) by a bullet list of concrete, required changes. Do not request optional polish."""

_VERDICT_RE = re.compile(r"^\s*\**\s*VERDICT\s*:\s*\**\s*(APPROVE|CHANGES)\b", re.I | re.M)


def parse_verdict(text: str) -> str | None:
    hits = _VERDICT_RE.findall(text or "")
    return hits[-1].upper() if hits else None


def _tree_fingerprint(repo: Path) -> str:
    try:
        diff = subprocess.run(["git", "diff", "HEAD", "--no-color", "--", ".", f":(exclude){CONFIG_DIR}"],
                              cwd=repo, capture_output=True, timeout=30, check=False).stdout
        others = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                cwd=repo, capture_output=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return hashlib.sha256(diff + b"\0" + others).hexdigest()


def _diff_text(repo: Path, limit: int = 40_000) -> str:
    try:
        diff = subprocess.run(["git", "diff", "HEAD", "--no-color", "--", ".", f":(exclude){CONFIG_DIR}"],
                              cwd=repo, capture_output=True, text=True, timeout=30, check=False).stdout
        others = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                cwd=repo, capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "(diff unavailable)"
    new = [f for f in others.splitlines() if f and not f.startswith(CONFIG_DIR + "/")]
    text = diff + ("".join(f"\n# new file (read it): {f}" for f in new) if new else "")
    return text[:limit] + (f"\n… diff truncated at {limit} characters; read the files directly." if len(text) > limit else "")


def _text_role(root: Path, agent: str, instruction: str, *, out: TextIO, timeout: int, label: str,
               fallback_file: str | None = None) -> tuple[str | None, dict[str, Any]]:
    """Run one agent for a text answer (planner / reviewer). Gates are not run for text roles."""
    from .adapters import (agent_templates, resolve_agent, build_prompt, agent_env, parser_context,
                           PROMPT_PLACEHOLDER)
    from .core import run_task
    from .state import build_frame
    cfg = load_config(root)
    spec = resolve_agent(agent_templates(cfg), agent)
    frame = build_frame(root)
    prompt = build_prompt(frame, instruction)
    argv = [prompt if a == PROMPT_PLACEHOLDER else a for a in spec["argv"]]
    shown = [f"<{label} prompt {frame['continuity_token'][:23]}>" if a == PROMPT_PLACEHOLDER else a
             for a in spec["argv"]]
    before = _tree_fingerprint(root)
    print(f"\nV/  ROLE       {label} -> {agent}", file=out, flush=True)
    item = run_task(root, argv, timeout=timeout, agent=f"{agent}:{label}", record_argv=shown,
                    child_stdin=subprocess.DEVNULL, env=agent_env(root), cost_parser=spec["cost"],
                    parser_context=parser_context(root, cfg, spec["argv"]), log=out, run_checks=False)
    text = item.get("agent_text")
    if fallback_file:
        f = root / fallback_file
        if f.exists():
            text = (text + "\n\n" if text else "") + f.read_text(encoding="utf-8", errors="replace")[:20_000]
            f.unlink()
    if _tree_fingerprint(root) != before:
        print(f"V/  WARNING    the {label} changed project files although its role is read-only; "
              f"the changes are kept for you to inspect (`git status`)", file=out)
        item["role_violation"] = True
    return (text.strip() if text and text.strip() else None), item


def run_loop(root: Path, **kw: Any) -> int:
    """Role loop (see `_run_loop`); the outcome goes to the developer's channels."""
    from .adapters import _notify_outcome
    code = _run_loop(root, **kw)
    _notify_outcome(root, code, "vcmd loop")
    return code


def _run_loop(root: Path, *, plan: str | None, build: list[str], review: str | None, rounds: int = 2,
             attempts: int | None = None, timeout: int = 3600, check_timeout: int = 600,
             budget_usd: float | None = None, out: TextIO | None = None) -> int:
    """brief -> plan -> build/test (gates) -> review -> handoff. Returns a CLI exit code.

    The gates decide whether the build is verified; the reviewer can only withhold "done" and send the
    work back to the builder with concrete changes (up to `rounds` builds)."""
    from .adapters import run_agents, STOPPED_FOR_HUMAN
    from .state import load_task
    out = out or sys.stdout
    if not build:
        raise ValueError("The loop needs at least one builder agent (--build or config roles.build)")
    if rounds < 1:
        raise ValueError("--rounds must be at least 1")
    if load_task(root) is None:
        raise FileNotFoundError('No active task. Write the brief first: vcmd task start "<goal>" --scope … --done …')
    plan_text = None
    if plan:
        plan_text, item = _text_role(root, plan, PLAN_INSTRUCTION, out=out, timeout=timeout, label="plan",
                                     fallback_file="VCOMMAND_PLAN.md")
        if plan_text:
            _path(root, PLAN_FILE).write_text(f"# Plan ({plan}, {utc_now()})\n\n{plan_text}\n", encoding="utf-8")
            add_decision(root, f"Plan written by {plan} (.vcommand/plan.md)", agent=plan)
            print(f"V/  PLAN       saved to .vcommand/plan.md ({len(plan_text)} chars)", file=out)
        else:
            print(f"V/  PLAN       {plan} returned no plan text (status {item['status']}); building from the brief",
                  file=out)
    notes = None
    code = 1
    for rnd in range(1, rounds + 1):
        parts = [BUILD_INSTRUCTION]
        if plan_text:
            parts.append("PLAN:\n" + plan_text[:12_000])
        if notes:
            parts.append(f"REVIEW ROUND {rnd - 1} REQUESTED THESE CHANGES (required):\n{notes[:8000]}")
        print(f"\nV/  ROUND      {rnd}/{rounds}: build", file=out, flush=True)
        code = run_agents(root, build, attempts=attempts, instruction="\n\n".join(parts), timeout=timeout,
                          check_timeout=check_timeout, budget_usd=budget_usd, out=out, notify_result=False)
        if code != 0:
            write_handoff(root)
            if code == STOPPED_FOR_HUMAN:
                print("V/  LOOP       stopped for a human decision (see `vcmd approve` / handoff.md)", file=out)
            return code
        if not review:
            write_handoff(root)
            print("V/  LOOP       verified by gates (no reviewer configured)", file=out)
            return 0
        instruction = REVIEW_INSTRUCTION + ("\n\nPLAN:\n" + plan_text[:8000] if plan_text else "") + \
            "\n\nCHANGE UNDER REVIEW (git diff HEAD):\n```diff\n" + _diff_text(root) + "\n```"
        text, item = _text_role(root, review, instruction, out=out, timeout=timeout, label="review")
        verdict = parse_verdict(text or "")
        _path(root, REVIEW_FILE).write_text(f"# Review round {rnd} ({review}, {utc_now()})\n\n"
                                            f"{text or '(no review text)'}\n", encoding="utf-8")
        if item.get("role_violation"):
            from .core import run_task
            recheck = run_task(root, [f"{review}:review:recheck"], external=True, agent=f"{review}:review",
                               check_timeout=check_timeout, log=out)
            if recheck["status"] != "verified_by_configured_checks":
                verdict = "CHANGES"
                text = (text or "") + "\n- The reviewer edited files and the gates no longer pass; restore them."
        if verdict is None:
            print(f"V/  REVIEW     {review} gave no verdict line; treating as not approved", file=out)
            add_decision(root, f"Review round {rnd}: no verdict from {review}", agent=review)
            write_handoff(root)
            return 1
        add_decision(root, f"Review round {rnd}: {verdict} by {review} (.vcommand/review.md)", agent=review)
        print(f"V/  REVIEW     round {rnd}: {verdict} ({review})", file=out)
        if verdict == "APPROVE":
            write_handoff(root)
            print("V/  LOOP       done: gates pass and the reviewer approved. Review the diff and commit.", file=out)
            return 0
        notes = text
    write_handoff(root)
    print(f"V/  LOOP       gates pass but the reviewer still requests changes after {rounds} round(s); "
          f"see .vcommand/review.md", file=out)
    return 1


# ---------------------------------------------------------------- wake: one entry point for triggers

def run_wake(root: Path, agents: list[str], *, use_loop: bool = False, max_tasks: int | None = None,
             until: str | None = None, budget_usd: float | None = None, timeout: int = 3600,
             jobs: int = 1, out: TextIO | None = None) -> int:
    """Continue whatever is pending: runnable queue tasks first, then the active task.

    Exit 0 also when there is nothing to do, so a cron job or CI schedule stays green."""
    from . import queue as q
    from .state import load_task
    out = out or sys.stdout
    cfg = load_config(root)
    roles = cfg.get("roles") or {}
    wake_cfg = cfg.get("wake") or {}
    agents = agents or list(wake_cfg.get("agents") or []) or _as_list(roles.get("build"))
    if not agents:
        raise ValueError("No agents: pass them (`vcmd wake claude codex`) or set config wake.agents / roles.build")
    print(f"V/  WAKE       {utc_now()} agents: {', '.join(agents)}", file=out, flush=True)
    data = q.load_queue(root)
    runnable = [t for t in data.get("tasks", []) if t.get("status") == "pending"]
    if runnable:
        print(f"V/  WAKE       {len(runnable)} queued task(s) pending", file=out, flush=True)
        code = q.run_queue(root, agents, max_tasks=max_tasks, until=until, budget_usd=budget_usd,
                           timeout=timeout, jobs=jobs)
        write_handoff(root)
        return code
    task = load_task(root)
    if task is None:
        print("V/  WAKE       nothing to do: queue empty, no active task", file=out)
        return 0
    runs = [r for r in list_evidence(root) if r.get("task_id") == task["id"]]
    if runs and runs[-1]["status"] == "verified_by_configured_checks" and not task.get("next_step"):
        print(f"V/  WAKE       nothing to do: task {task['id']} is verified and has no next step", file=out)
        return 0
    if pending_approvals(root):
        print("V/  WAKE       waiting for approvals: " + ", ".join(a["id"] for a in pending_approvals(root))
              + " (vcmd approve list)", file=out)
        return 0
    print(f"V/  WAKE       continuing task {task['id']}: {task['goal']}", file=out, flush=True)
    if use_loop:
        return run_loop(root, plan=roles.get("plan"), build=agents, review=roles.get("review"),
                        rounds=int(roles.get("rounds", 2)), timeout=timeout, budget_usd=budget_usd, out=out)
    from .adapters import run_agents
    code = run_agents(root, agents, instruction="Continue from the handoff in the context frame.",
                      timeout=timeout, budget_usd=budget_usd, out=out)
    write_handoff(root)
    return code


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def schedule_template(kind: str, *, agents: list[str], at: str = "02:00", use_loop: bool = False,
                      vcmd: str = "vcmd") -> str:
    """Trigger templates that wake `vcmd wake` on a schedule or event. Printed, never installed silently."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", at)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("--at must be HH:MM")
    hh, mm = int(m.group(1)), int(m.group(2))
    cmd = f"{vcmd} wake {' '.join(agents)}" + (" --loop" if use_loop else "")
    if kind == "cron":
        return (f"# crontab -e   (local time {hh:02d}:{mm:02d} every day)\n"
                f"{mm} {hh} * * * cd {Path.cwd()} && {cmd} >> .vcommand/wake.log 2>&1\n")
    if kind == "systemd":
        return (f"# ~/.config/systemd/user/vcommand-wake.service\n[Unit]\nDescription=V/COMMAND wake\n\n"
                f"[Service]\nType=oneshot\nWorkingDirectory={Path.cwd()}\nExecStart={cmd}\n\n"
                f"# ~/.config/systemd/user/vcommand-wake.timer\n[Unit]\nDescription=V/COMMAND wake daily\n\n"
                f"[Timer]\nOnCalendar=*-*-* {hh:02d}:{mm:02d}:00\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
                f"# systemctl --user enable --now vcommand-wake.timer\n")
    if kind == "github":
        installs = []
        if any(a.startswith("claude") for a in agents):
            installs.append("npm install -g @anthropic-ai/claude-code")
        if any(a.startswith("codex") for a in agents):
            installs.append("npm install -g @openai/codex")
        install = "\n".join(f"          {line}" for line in installs) or "          true"
        return f"""# .github/workflows/vcommand-wake.yml — wakes V/COMMAND on a schedule, by hand, or by webhook:
#   curl -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \\
#        https://api.github.com/repos/OWNER/REPO/dispatches -d '{{"event_type":"vcommand-wake"}}'
# Verified work is pushed to a new branch `vcommand/wake-<run id>` for you to review. Nothing is merged
# or deployed. The handoff, decisions and evidence are uploaded as a build artifact.
name: vcommand-wake
on:
  schedule:
    - cron: "{mm} {hh} * * *"   # UTC
  workflow_dispatch:
  repository_dispatch:
    types: [vcommand-wake]
permissions:
  contents: write
concurrency:
  group: vcommand-wake
  cancel-in-progress: false
jobs:
  wake:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Install V/COMMAND and agents
        run: |
          pip install vcommand-cli
{install}
      - name: Restore V/COMMAND state
        uses: actions/cache@v4
        with:
          path: .vcommand
          key: vcommand-${{{{ github.run_id }}}}
          restore-keys: vcommand-
      - name: Wake
        env:
          ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
          OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
        run: |
          git config user.name "vcommand-bot"
          git config user.email "vcommand-bot@users.noreply.github.com"
          {cmd}
          if [ -n "$(git status --porcelain -- . ':!.vcommand')" ]; then
            git add -A -- . ':!.vcommand'
            git commit -m "V/COMMAND wake: changes verified by the configured gates"
          fi
      - name: Push verified commits to a review branch
        run: |
          if [ -n "$(git log origin/${{{{ github.ref_name }}}}..HEAD --oneline)" ]; then
            git push origin HEAD:refs/heads/vcommand/wake-${{{{ github.run_id }}}}
          fi
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: vcommand-handoff
          path: |
            .vcommand/handoff.md
            .vcommand/decisions.md
            .vcommand/todo.md
            .vcommand/runs/
          if-no-files-found: ignore
"""
    raise ValueError("Schedule kind must be cron, systemd or github")
