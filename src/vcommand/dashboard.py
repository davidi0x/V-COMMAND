"""`vcmd dashboard`: a local web dashboard for everything V/COMMAND knows about the project.

Serves one page on 127.0.0.1 with a random access token. Read views: overview KPIs, runs and costs,
ledger and pre-flight warnings, agents and their circuit state, queue, benchmark results, hardware,
the current context frame. Actions: store/delete API keys (kept in the OS secret store, values never
returned), answer a frozen queue task, add a queue task, reset agent circuits.

Security: binds to 127.0.0.1 only; every API call needs the token (header X-VCMD-Token); the Host
header must be the loopback address (DNS-rebinding protection); no CORS. Standard library only.
"""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hmac
import json
import os
import secrets as pysecrets
import shlex
import signal
import socket
import socketserver
import subprocess
import sys
import time
import urllib.parse
from typing import Any

from .core import CONFIG_DIR, list_evidence, load_config

PAGE = Path(__file__).with_name("dashboard.html")
ASSETS = Path(__file__).with_name("assets")
ASSET_TYPES = {".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml"}
STATE_FILE = "dashboard.json"
MAX_BODY = 64 * 1024


# ---------------------------------------------------------------- data

def _bench_results(root: Path) -> list[dict[str, Any]]:
    """Summaries from .vcommand/bench/<run>/summary.json and benchmarks/results/*.jsonl."""
    from .bench import summarize
    found = []
    for summary in sorted((root / CONFIG_DIR / "bench").glob("*/summary.json")):
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["source"] = str(summary.parent.relative_to(root))
            found.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    for jsonl in sorted((root / "benchmarks" / "results").glob("*.jsonl")):
        try:
            rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            continue
        arms = list(dict.fromkeys(r["arm"] for r in rows))
        data = summarize(rows, jsonl.stem, arms)
        data["source"] = str(jsonl.relative_to(root))
        found.append(data)
    return found[-12:]


def collect_state(root: Path) -> dict[str, Any]:
    from .state import build_frame, read_ledger, load_task
    from .adapters import agent_templates, load_health, open_circuits
    from .queue import load_queue
    from .secrets_store import describe_backend, list_secrets, KNOWN

    cfg = load_config(root)
    runs = list_evidence(root)
    ledger = read_ledger(root)
    frame = build_frame(root)
    known_costs = [r["cost"]["amount"] for r in runs if (r.get("cost") or {}).get("amount") is not None]
    statuses: dict[str, int] = {}
    for r in runs:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    per_agent: dict[str, dict[str, Any]] = {}
    for r in runs:
        a = per_agent.setdefault(r.get("agent") or "(command)", {"runs": 0, "verified": 0, "cost": 0.0,
                                                                  "unknown_cost": 0, "killed": 0})
        a["runs"] += 1
        a["verified"] += r["status"] == "verified_by_configured_checks"
        a["killed"] += bool(r["action"].get("killed"))
        amount = (r.get("cost") or {}).get("amount")
        if amount is None:
            a["unknown_cost"] += 1
        else:
            a["cost"] = round(a["cost"] + amount, 6)
    health, opened = load_health(root), open_circuits(root)
    templates = agent_templates(cfg)
    import shutil as _shutil
    code_slice = frame.get("code_slice") or {}
    try:
        stored = list_secrets()
        secret_error = None
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        stored, secret_error = [], str(error)
    return {
        "project": str(root.resolve()),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kpi": {
            "runs": len(runs),
            "verified": statuses.get("verified_by_configured_checks", 0),
            "failed": statuses.get("failed", 0) + statuses.get("failed_verification", 0),
            "unverified": statuses.get("unverified", 0),
            "known_cost_usd": round(sum(known_costs), 4),
            "unknown_cost_runs": len(runs) - len(known_costs),
            "ledger": len(ledger),
            "queue_waiting": sum(t["status"] == "frozen" for t in load_queue(root)["tasks"]),
        },
        "statuses": statuses,
        "task": load_task(root),
        "project_name": root.resolve().name,
        "frame": {"token": frame["continuity_token"], "gates": frame["acceptance_gates"],
                  "hints": frame.get("preflight_hints") or [], "focus": frame.get("focus") or [],
                  "slice_parser": code_slice.get("parser"),
                  "constraints": [e["constraint"] for e in frame["negative_knowledge"]],
                  "symbols": [{"file": s["file"], "symbol": s.get("symbol"), "lines": s.get("lines"),
                               "outline": len(s.get("outline", [])) if s.get("symbol") is None else None}
                              for s in code_slice.get("symbols", [])],
                  "references": [{"file": r["file"], "line": r["line"], "kind": r["kind"]}
                                 for r in code_slice.get("references", [])],
                  "problems": code_slice.get("problems", []),
                  "last_run": frame.get("last_run")},
        "runs": [{"id": r["id"], "agent": r.get("agent"), "status": r["status"], "created_at": r.get("created_at_utc"),
                  "exit_code": r["action"].get("exit_code"), "external": bool(r["action"].get("external")),
                  "changed": [l[3:] for l in (r.get("git_status_after") or [])
                              if len(l) > 3 and not l[3:].startswith((CONFIG_DIR, ".claude/", ".codex/"))][:30],
                  "task_id": r.get("task_id"),
                  "duration_ms": r["action"].get("duration_ms"), "cost": (r.get("cost") or {}).get("amount"),
                  "cost_source": (r.get("cost") or {}).get("source"), "estimated": (r.get("cost") or {}).get("estimated"),
                  "killed": r["action"].get("killed"), "isolated": r.get("isolated_worktree"),
                  "cancelled": bool(r["action"].get("cancelled")),
                  "checks": [{"cmd": " ".join(c["argv"])[-90:], "passed": c["passed"],
                              "duration_ms": c.get("duration_ms"), "timed_out": c.get("timed_out")} for c in r["checks"]]}
                 for r in reversed(runs[-200:])],
        "agents": [{"name": name, "argv": " ".join(spec["argv"]), "parser": spec["cost"],
                    "installed": bool(_shutil.which(spec["argv"][0])),
                    "circuit": "open" if name in opened else ("recovering" if name in health else "closed"),
                    "last_reason": (health.get(name) or {}).get("last_reason"),
                    **per_agent.get(name, {"runs": 0, "verified": 0, "cost": 0.0, "unknown_cost": 0, "killed": 0})}
                   for name, spec in sorted(templates.items())]
                  + [{"name": n, "argv": "", "parser": None, "installed": None, "circuit": "—", "last_reason": None, **v}
                     for n, v in per_agent.items() if n not in templates],
        "ledger": list(reversed(ledger[-100:])),
        "queue": load_queue(root)["tasks"],
        "bench": _bench_results(root),
        "secrets": {"backend": describe_backend(), "stored": stored, "error": secret_error,
                    "known": [{"name": k, "label": v} for k, v in KNOWN.items()]},
        "budget": cfg.get("budget", {}),
        "workflow": _workflow_state(root, cfg, frame),
    }


def _workflow_state(root: Path, cfg: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    from . import workflow as w
    vc = root / CONFIG_DIR

    def head(name: str, limit: int = 4000) -> str | None:
        f = vc / name
        return f.read_text(encoding="utf-8", errors="replace")[:limit] if f.exists() else None

    from . import sessions as se, channels as ch
    shared = se.shared_root(root)
    try:
        worktrees = se.list_worktrees(shared)
        clash = se.conflicts(shared) if worktrees else []
    except (OSError, subprocess.SubprocessError):
        worktrees, clash = [], []
    parallel = {"sessions": se.list_sessions(shared)[:20], "worktrees": worktrees, "conflicts": clash,
                "messages": list(reversed(se.list_messages(shared, 12))),
                "channels": [{"type": c["type"], "events": c.get("events") or ["all"]} for c in ch.channels(cfg)]}
    return {"parallel": parallel, "brief": frame.get("brief"), "handoff": w.read_handoff(root), "todos": w.read_todos(root),
            "decisions": list(reversed(w.read_decisions(root)[-30:])),
            "approvals": list(reversed(w.list_approvals(root)[-30:])),
            "roles": cfg.get("roles") or {}, "plan": head(w.PLAN_FILE), "review": head(w.REVIEW_FILE)}


# ---------------------------------------------------------------- HTTP

class _Handler(BaseHTTPRequestHandler):
    server_version = "vcommand-dashboard"
    root: Path
    token: str
    port: int

    def log_message(self, *_: Any) -> None:  # keep the terminal quiet; never log tokens
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _token_ok(self, query: dict[str, list[str]]) -> bool:
        given = self.headers.get("X-VCMD-Token") or (query.get("token") or [""])[0]
        return bool(given) and hmac.compare_digest(given, self.token)

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _guard(self) -> dict[str, list[str]] | None:
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "bad host"})
            return None
        if not self._token_ok(query):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or wrong token"})
            return None
        return query

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/assets/"):
            # static, non-sensitive files (font, licence): loopback Host still required, no token
            name = path.rsplit("/", 1)[-1]
            target = ASSETS / name
            if not self._host_ok() or "/" in name or not target.is_file() or target.suffix not in ASSET_TYPES:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self._send(HTTPStatus.OK, target.read_bytes(), ASSET_TYPES[target.suffix])
            return
        if self._guard() is None:
            return
        try:
            if path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(HTTPStatus.OK, collect_state(self.root))
            elif path == "/api/frame":
                from .state import build_frame, render_frame
                self._send(HTTPStatus.OK, render_frame(build_frame(self.root)).encode("utf-8"), "text/plain; charset=utf-8")
            elif path == "/api/hw":
                from .hw import probe, recommend
                info = probe(self.root)
                self._json(HTTPStatus.OK, {"hardware": info, "recommendation": recommend(info)})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as error:  # noqa: BLE001 - report, never crash the server
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(error).__name__}: {error}"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if self._guard() is None:
            return
        if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON only"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object expected")
            self._json(HTTPStatus.OK, self._action(path, body))
        except (ValueError, OSError, KeyError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _action(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        from . import queue as q
        from .secrets_store import delete_secret, set_secret
        if path == "/api/secret":
            return set_secret(str(body.get("name", "")), str(body.get("value", "")))
        if path == "/api/secret/delete":
            delete_secret(str(body.get("name", "")))
            return {"ok": True}
        if path == "/api/queue/answer":
            t = q.answer(self.root, str(body["id"]), str(body["text"]))
            return {"ok": True, "id": t["id"]}
        if path == "/api/queue/add":
            gates = [shlex.split(g) for g in body.get("gates", []) if str(g).strip()]
            focus = [str(f) for f in body.get("focus", []) if str(f).strip()]
            t = q.add_task(self.root, str(body.get("goal", "")), focus=focus, gates=gates)
            return {"ok": True, "id": t["id"]}
        if path == "/api/approval":
            from .workflow import decide_approval
            a = decide_approval(self.root, str(body.get("id", "")), bool(body.get("approve")))
            return {"ok": True, "id": a["id"], "status": a["status"]}
        if path == "/api/msg":
            from .sessions import send_message, shared_root
            m = send_message(shared_root(self.root), str(body.get("to", "")), str(body.get("text", "")),
                             sender="developer")
            return {"ok": True, "id": m["id"]}
        if path == "/api/todo/add":
            from .workflow import add_todo
            return {"ok": True, **add_todo(self.root, str(body.get("text", "")))}
        if path == "/api/todo/done":
            from .workflow import complete_todo
            return {"ok": True, **complete_todo(self.root, str(body.get("n", "")))}
        if path == "/api/health/reset":
            (self.root / CONFIG_DIR / "agent_health.json").unlink(missing_ok=True)
            return {"ok": True}
        raise ValueError("unknown action")


class _LoopbackServer(ThreadingHTTPServer):
    """HTTPServer.server_bind() calls socket.getfqdn(), a reverse DNS lookup that can block for tens of
    seconds on macOS when DNS is slow or unreachable (found on CI). A loopback server never needs it."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def make_server(root: Path, port: int = 0, token: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    load_config(root)  # must be an initialized project
    token = token or pysecrets.token_urlsafe(24)
    server = _LoopbackServer(("127.0.0.1", port), _Handler)
    actual = server.server_address[1]
    handler = type("Handler", (_Handler,), {"root": root, "token": token, "port": actual})
    server.RequestHandlerClass = handler
    return server, f"http://127.0.0.1:{actual}/?token={token}"


# ---------------------------------------------------------------- background process

def _state_path(root: Path) -> Path:
    return root / CONFIG_DIR / STATE_FILE


def _alive(info: dict[str, Any]) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=0.5):
            return True
    except (OSError, KeyError, ValueError):
        return False


def running(root: Path) -> dict[str, Any] | None:
    try:
        info = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return info if _alive(info) else None


def start_background(root: Path, port: int = 0) -> dict[str, Any]:
    existing = running(root)
    if existing:
        return existing
    token = pysecrets.token_urlsafe(24)
    if port == 0:
        with socket.socket() as probe_socket:
            probe_socket.bind(("127.0.0.1", 0))
            port = probe_socket.getsockname()[1]
    log_path = root / CONFIG_DIR / "dashboard.log"
    log = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - handed to the child process
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "cwd": root,
                              "env": {**os.environ, "VCOMMAND_DASHBOARD_TOKEN": token, "PYTHONUNBUFFERED": "1"}}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    # -X faulthandler: if start-up hangs, SIGABRT dumps every thread's stack into the log
    proc = subprocess.Popen([sys.executable, "-X", "faulthandler", "-m", "vcommand", "dashboard", "--port", str(port),
                             "--no-open"], **kwargs)
    log.close()
    info = {"pid": proc.pid, "port": port, "url": f"http://127.0.0.1:{port}/?token={token}"}

    def tail() -> str:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        return ("; log: " + text[-1500:]) if text else ""

    # a cold interpreter can take several seconds: wait up to 20 s, fail fast if the process dies,
    # and never leave an orphan behind on failure
    deadline = time.monotonic() + 20
    while not _alive(info):
        if proc.poll() is not None:
            raise OSError(f"dashboard exited during start-up (code {proc.returncode}){tail()}")
        if time.monotonic() > deadline:
            if os.name != "nt":
                proc.send_signal(signal.SIGABRT)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            proc.kill()
            raise OSError(f"dashboard did not start within 20 s{tail()}")
        time.sleep(0.1)
    path = _state_path(root)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds the token
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(info, handle)
    return info


def stop_background(root: Path) -> bool:
    try:
        info = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    try:
        os.kill(int(info["pid"]), signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        pass
    _state_path(root).unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------- slash command for Claude Code

COMMAND_MD = """---
description: Open the V/COMMAND dashboard (runs, costs, ledger, queue, benchmarks, API keys)
allowed-tools: Bash(vcmd dashboard:*)
---
Run `vcmd dashboard --background` and reply with the URL it prints, as a clickable link, plus one line
saying the dashboard runs locally on 127.0.0.1 and the link contains a private access token.
"""


def install_command(root: Path) -> Path:
    path = root / ".claude" / "commands" / "dashboard.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(COMMAND_MD, encoding="utf-8")
    return path
