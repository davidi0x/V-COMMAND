"""Parallel live sessions: one git worktree per session, a session registry, and messages between sessions.

* `vcmd worktree new auth` creates `../<repo>-auth` on branch `vcmd/auth`, gives it its own
  V/COMMAND state (copied config, its own task / brief / ledger) and the agent hooks, so one Claude
  Code or Codex session can run inside each worktree without the sessions editing the same files.
* Collisions: `vcmd worktree conflicts` lists files changed in more than one worktree; the
  PostToolUse hook warns a session the moment it edits a file another live worktree already changed.
* Registry: every hooked session registers itself (name, agent, worktree, last activity) in the
  *shared* state of the main repository, so `vcmd sessions` shows who is working where.
* Messages: `vcmd msg send <session|all> "..."` — short findings, warnings, handoffs. A live session
  receives them through its hooks (after its next tool call, on the next prompt, or at Stop);
  wrapped agents get them in their next prompt.

Standard library only. Message texts are stored locally in `.vcommand/inbox.jsonl` of the main repo.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any

from .core import CONFIG_DIR, config_path, load_config, utc_now

REGISTRY = "sessions.json"
INBOX = "inbox.jsonl"
ACTIVE_S = 15 * 60
MAX_MESSAGE = 1000
_LOCK = threading.Lock()
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def _git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


def shared_root(start: Path) -> Path:
    """The main repository's V/COMMAND state, also when called from inside a linked worktree."""
    env = os.environ.get("VCOMMAND_SHARED_ROOT")
    if env:
        return Path(env)
    try:
        out = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], start, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return start
    if out.returncode == 0 and out.stdout.strip():
        common = Path(out.stdout.strip())
        main = common.parent if common.name == ".git" else None
        if main is not None and config_path(main).exists():
            return main
    return start


def _load(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / CONFIG_DIR / REGISTRY).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("worktrees", [])
            data.setdefault("sessions", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"worktrees": [], "sessions": {}}


def _save(root: Path, data: dict[str, Any]) -> None:
    path = root / CONFIG_DIR / REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _same(a: Path | str, b: Path | str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


# ---------------------------------------------------------------- worktrees

def create_worktree(root: Path, name: str, *, branch: str | None = None, base: str | None = None,
                    path: Path | None = None, goal: str | None = None) -> dict[str, Any]:
    load_config(root)
    if not _NAME_RE.match(name):
        raise ValueError("Worktree name: letters, digits, . _ - (max 40)")
    data = _load(root)
    if any(w["name"] == name for w in data["worktrees"]):
        raise ValueError(f"Worktree {name} already exists (vcmd worktree list)")
    base = base or "HEAD"
    rev = _git(["rev-parse", "--verify", base + "^{commit}"], root)
    if rev.returncode != 0:
        raise ValueError(f"Unknown base revision: {base}")
    base_sha = rev.stdout.strip()
    branch = branch or f"vcmd/{name}"
    path = (path or root.parent / f"{root.resolve().name}-{name}").resolve()
    if path.exists():
        raise ValueError(f"{path} already exists")
    exists = _git(["rev-parse", "--verify", f"refs/heads/{branch}"], root).returncode == 0
    args = ["worktree", "add", str(path), branch] if exists else ["worktree", "add", "-b", branch, str(path), base_sha]
    out = _git(args, root, timeout=120)
    if out.returncode != 0:
        raise ValueError(f"git worktree add failed: {out.stderr.strip()[:300]}")
    # Own state for the session: same checks, agents and guardrails; separate task and ledger.
    (path / CONFIG_DIR / "runs").mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path(root), config_path(path))
    for rel in (".claude/settings.json", ".codex/hooks.json", ".claude/commands/dashboard.md"):
        src, dst = root / rel, path / rel
        if src.exists() and not dst.exists():  # untracked hook files are not in the checkout
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    item = {"name": name, "path": str(path), "branch": branch, "base": base_sha, "created_at_utc": utc_now()}
    with _LOCK:
        data = _load(root)
        data["worktrees"].append(item)
        _save(root, data)
    if goal:
        from .state import start_task
        start_task(path, goal)
    return item


def _changed(path: Path, base: str | None) -> set[str]:
    files: set[str] = set()
    if base:
        diff = _git(["diff", "--name-only", base, "--"], path)
        if diff.returncode == 0:
            files |= {f for f in diff.stdout.splitlines() if f}
    status = _git(["status", "--porcelain", "-z", "--untracked-files=all"], path)
    if status.returncode == 0:
        for entry in status.stdout.split("\0"):
            if len(entry) > 3:
                files.add(entry[3:])
    return {f for f in files if not f.startswith((CONFIG_DIR + "/", ".claude/", ".codex/"))}


def list_worktrees(root: Path, with_changes: bool = True) -> list[dict[str, Any]]:
    data = _load(root)
    live = _git(["worktree", "list", "--porcelain"], root)
    paths = {l[9:] for l in live.stdout.splitlines() if l.startswith("worktree ")} if live.returncode == 0 else set()
    out = []
    for w in data["worktrees"]:
        present = any(_same(w["path"], p) for p in paths) and Path(w["path"]).exists()
        item = {**w, "present": present}
        if with_changes and present:
            item["changed"] = sorted(_changed(Path(w["path"]), w.get("base")))
        out.append(item)
    return out


def conflicts(root: Path) -> list[dict[str, Any]]:
    """Files changed in more than one place (the main working tree counts as `main`)."""
    owners: dict[str, list[str]] = {}
    head = _git(["rev-parse", "HEAD"], root).stdout.strip() or None
    for f in _changed(root, None if head is None else "HEAD"):
        owners.setdefault(f, []).append("main")
    for w in list_worktrees(root):
        for f in w.get("changed", []):
            owners.setdefault(f, []).append(w["name"])
    return [{"file": f, "worktrees": ws} for f, ws in sorted(owners.items()) if len(ws) > 1]


def remove_worktree(root: Path, name: str, *, force: bool = False) -> dict[str, Any]:
    with _LOCK:
        data = _load(root)
        hit = next((w for w in data["worktrees"] if w["name"] == name), None)
        if hit is None:
            raise ValueError(f"No worktree {name}")
        path = Path(hit["path"])
        if path.exists():
            if not force:
                dirty = _changed(path, None)
                if dirty:
                    raise ValueError(f"{name} has uncommitted changes ({', '.join(sorted(dirty)[:5])}); "
                                     f"commit them or use --force")
            # .vcommand/ (session state) is untracked inside the worktree; git needs --force for that.
            out = _git(["worktree", "remove", "--force", str(path)], root, timeout=120)
            if out.returncode != 0:
                raise ValueError(f"git worktree remove failed: {out.stderr.strip()[:300]}")
        else:
            _git(["worktree", "prune"], root)
        data["worktrees"] = [w for w in data["worktrees"] if w["name"] != name]
        _save(root, data)
    return hit


def worktree_for(root: Path, cwd: Path) -> dict[str, Any] | None:
    for w in _load(root)["worktrees"]:
        try:
            Path(cwd).resolve().relative_to(Path(w["path"]).resolve())
            return w
        except (ValueError, OSError):
            continue
    return None


# ---------------------------------------------------------------- session registry

def session_name(root: Path, cwd: Path, session_id: str | None = None, agent: str | None = None) -> str:
    if os.environ.get("VCOMMAND_SESSION"):
        return os.environ["VCOMMAND_SESSION"]
    data = _load(root)
    if session_id and session_id in data["sessions"]:
        return data["sessions"][session_id]["name"]
    wt = worktree_for(root, cwd)
    if wt:
        return wt["name"]
    if session_id is None:
        return "main"
    return f"{agent or 'session'}-{session_id[:6]}"


def register_session(root: Path, session_id: str, *, agent: str, cwd: Path, source: str | None = None) -> dict[str, Any]:
    with _LOCK:
        data = _load(root)
        prev = data["sessions"].get(session_id)
        wt = worktree_for(root, cwd)
        name = (prev["name"] if prev else os.environ.get("VCOMMAND_SESSION")
                or (wt["name"] if wt else f"{agent}-{session_id[:6]}"))
        item = {"name": name, "agent": agent, "cwd": str(cwd), "worktree": wt["name"] if wt else None,
                "branch": wt["branch"] if wt else None, "started_at_utc": (prev or {}).get("started_at_utc", utc_now()),
                "last_seen": time.time(), "source": source, "ended": False}
        data["sessions"][session_id] = item
        # keep the registry small: drop sessions idle for a week
        cutoff = time.time() - 7 * 86400
        data["sessions"] = {k: v for k, v in data["sessions"].items() if v.get("last_seen", 0) > cutoff}
        _save(root, data)
    return item


def touch_session(root: Path, session_id: str, *, ended: bool = False) -> None:
    with _LOCK:
        data = _load(root)
        s = data["sessions"].get(session_id)
        if s is None:
            return
        s["last_seen"] = time.time()
        if ended:
            s["ended"] = True
        _save(root, data)


def list_sessions(root: Path, now: float | None = None) -> list[dict[str, Any]]:
    now = time.time() if now is None else now
    unread = _unread_counts(root)
    out = []
    for sid, s in _load(root)["sessions"].items():
        status = "ended" if s.get("ended") else "active" if now - s.get("last_seen", 0) < ACTIVE_S else "idle"
        out.append({**s, "id": sid, "status": status, "unread": unread.get(s["name"], 0)})
    return sorted(out, key=lambda s: -s.get("last_seen", 0))


# ---------------------------------------------------------------- messages

def _inbox(root: Path) -> list[dict[str, Any]]:
    path = root / CONFIG_DIR / INBOX
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(m, dict):
            out.append(m)
    return out


def _write_inbox(root: Path, items: list[dict[str, Any]]) -> None:
    path = root / CONFIG_DIR / INBOX
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in items[-500:]), encoding="utf-8")
    tmp.replace(path)


def send_message(root: Path, to: str, text: str, *, sender: str = "developer") -> dict[str, Any]:
    load_config(root)
    text = " ".join(text.split())
    if not text:
        raise ValueError("Empty message")
    if to != "all" and not _NAME_RE.match(to):
        raise ValueError("Recipient must be a session name or 'all'")
    msg = {"id": "m-" + uuid.uuid4().hex[:6], "to": to, "from": sender, "text": text[:MAX_MESSAGE],
           "at_utc": utc_now(), "delivered_to": []}
    with _LOCK:
        path = root / CONFIG_DIR / INBOX
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg


def _for(m: dict[str, Any], name: str) -> bool:
    return (m["to"] == name or m["to"] == "all") and m.get("from") != name and name not in m.get("delivered_to", [])


def _unread_counts(root: Path) -> dict[str, int]:
    names = {s["name"] for s in _load(root)["sessions"].values()} | {w["name"] for w in _load(root)["worktrees"]}
    msgs = _inbox(root)
    return {n: sum(1 for m in msgs if _for(m, n)) for n in names}


def take_messages(root: Path, name: str, *, peek: bool = False) -> list[dict[str, Any]]:
    """Undelivered messages for `name` (and broadcasts); marks them delivered unless peek."""
    with _LOCK:
        items = _inbox(root)
        hits = [m for m in items if _for(m, name)]
        if hits and not peek:
            for m in hits:
                m.setdefault("delivered_to", []).append(name)
            _write_inbox(root, items)
    return hits


def list_messages(root: Path, limit: int = 50) -> list[dict[str, Any]]:
    return _inbox(root)[-limit:]


def render_messages(msgs: list[dict[str, Any]]) -> str:
    return "\n".join(f"- [{m['at_utc'][11:16]} from {m['from']}{' to all' if m['to'] == 'all' else ''}] {m['text']}"
                     for m in msgs)
