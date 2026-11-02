"""Channels: reach the developer anywhere, and let them steer V/COMMAND from anywhere.

Outbound (`notify`): approvals needed, frozen tasks, verified / failed work, context rotation and
messages addressed to `developer` go to the configured channels:

* telegram — Bot API `sendMessage` (token: secret TELEGRAM_BOT_TOKEN, `chat_id` in config)
* slack    — incoming webhook (secret SLACK_WEBHOOK_URL)
* ntfy     — `POST <server>/<topic>` (ntfy.sh or self-hosted; the topic name acts as a password)
* webhook  — JSON `POST` to a URL kept in a secret (Discord, Teams, n8n, your own service)

Inbound (`vcmd remote telegram`): long-polls the Telegram Bot API — no public endpoint, no port
forwarding — and accepts commands only from the configured chat ids: status, approvals, queue,
answers, messages to live sessions, wake-up.

`vcmd autopilot`: keeps the work going without a terminal open — `vcmd wake` every N minutes, plus
the Telegram remote in the same process.

Standard library only. Tokens are read from the environment or the OS secret store at send time
and never written to logs or evidence.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, TextIO

from .core import CONFIG_DIR, load_config, save_config, utc_now

TYPES = ("telegram", "slack", "ntfy", "webhook")
EVENTS = ("approval", "frozen", "verified", "failed", "rotate", "message", "wake")
LOG = "channels.log"
TIMEOUT_S = 8


def _secret(name: str | None) -> str | None:
    if not name:
        return None
    if os.environ.get(name):
        return os.environ[name]
    try:
        from .secrets_store import get_secret
        return get_secret(name)
    except Exception:  # noqa: BLE001 - a missing store must not break notifications
        return None


def _log(root: Path, text: str) -> None:
    try:
        with (root / CONFIG_DIR / LOG).open("a", encoding="utf-8") as f:
            f.write(f"{utc_now()} {text}\n")
    except OSError:
        pass


def _post(url: str, data: bytes, ctype: str, headers: dict[str, str] | None = None) -> int:
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype, "User-Agent": "vcommand", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - configured https endpoints
        return resp.status


def telegram_api() -> str:
    return os.environ.get("VCOMMAND_TELEGRAM_API", "https://api.telegram.org")


# ---------------------------------------------------------------- configuration

def channels(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    items = cfg.get("channels") or []
    return [c for c in items if isinstance(c, dict) and c.get("type") in TYPES]


def add_channel(root: Path, kind: str, *, chat_id: str | None = None, topic: str | None = None,
                server: str | None = None, secret: str | None = None, events: list[str] | None = None) -> dict[str, Any]:
    if kind not in TYPES:
        raise ValueError(f"Channel type must be one of {', '.join(TYPES)}")
    bad = [e for e in events or [] if e not in EVENTS]
    if bad:
        raise ValueError(f"Unknown event(s) {', '.join(bad)}; known: {', '.join(EVENTS)}")
    item: dict[str, Any] = {"type": kind}
    if kind == "telegram":
        if not chat_id:
            raise ValueError("telegram needs --chat <id> (message your bot, then open "
                             "https://api.telegram.org/bot<TOKEN>/getUpdates to see your chat id)")
        item.update(chat_id=str(chat_id), secret=secret or "TELEGRAM_BOT_TOKEN")
    elif kind == "slack":
        item["secret"] = secret or "SLACK_WEBHOOK_URL"
    elif kind == "ntfy":
        if not topic or len(topic) < 12:
            raise ValueError("ntfy needs --topic with at least 12 characters (anyone who knows it can read it)")
        item.update(topic=topic, server=(server or "https://ntfy.sh").rstrip("/"))
    else:
        if not secret:
            raise ValueError("webhook needs --secret <NAME> holding the URL (vcmd secret set NAME)")
        item["secret"] = secret
    if events:
        item["events"] = events
    cfg = load_config(root)
    cfg["channels"] = [c for c in channels(cfg) if c != item] + [item]
    save_config(root, cfg)
    return item


def remove_channel(root: Path, index: int) -> dict[str, Any]:
    cfg = load_config(root)
    items = channels(cfg)
    if not 1 <= index <= len(items):
        raise ValueError(f"No channel #{index} (vcmd channel list)")
    hit = items.pop(index - 1)
    cfg["channels"] = items
    save_config(root, cfg)
    return hit


# ---------------------------------------------------------------- outbound

def send(root: Path, channel: dict[str, Any], text: str, title: str = "V/COMMAND") -> None:
    """Send to one channel; raises on failure (callers decide whether that matters)."""
    kind = channel["type"]
    body = f"{title}\n{text}" if title else text
    if kind == "telegram":
        token = _secret(channel.get("secret", "TELEGRAM_BOT_TOKEN"))
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set (vcmd secret set TELEGRAM_BOT_TOKEN)")
        _post(f"{telegram_api()}/bot{token}/sendMessage",
              json.dumps({"chat_id": channel["chat_id"], "text": body[:4000],
                          "disable_web_page_preview": True}).encode(), "application/json")
    elif kind == "slack":
        url = _secret(channel.get("secret", "SLACK_WEBHOOK_URL"))
        if not url:
            raise ValueError("SLACK_WEBHOOK_URL is not set (vcmd secret set SLACK_WEBHOOK_URL)")
        _post(url, json.dumps({"text": body[:3500]}).encode(), "application/json")
    elif kind == "ntfy":
        _post(f"{channel['server']}/{urllib.parse.quote(channel['topic'])}", text[:3500].encode("utf-8"),
              "text/plain; charset=utf-8", {"Title": title})
    else:
        url = _secret(channel.get("secret"))
        if not url:
            raise ValueError(f"{channel.get('secret')} is not set")
        _post(url, json.dumps({"source": "vcommand", "title": title, "text": text[:3500],
                               "content": body[:1900]}).encode(), "application/json")


def notify(root: Path, event: str, text: str) -> int:
    """Best effort: never raises, never blocks longer than the timeout per channel. Returns sends."""
    if os.environ.get("VCOMMAND_NO_NOTIFY"):
        return 0
    from .sessions import shared_root
    root = shared_root(root)  # channels live in the main project's config, also for worktree sessions
    try:
        cfg = load_config(root)
    except (FileNotFoundError, ValueError):
        return 0
    sent = 0
    project = root.resolve().name
    for ch in channels(cfg):
        if ch.get("events") and event not in ch["events"]:
            continue
        try:
            send(root, ch, text, title=f"V/COMMAND · {project} · {event}")
            sent += 1
        except (OSError, ValueError, urllib.error.URLError) as error:
            _log(root, f"{ch['type']} {event} failed: {type(error).__name__}: {str(error)[:200]}")
    return sent


# ---------------------------------------------------------------- inbound commands (any channel)

HELP = """Commands:
/status — task, handoff, approvals, queue
/approvals — pending approval requests
/approve <id> · /deny <id>
/queue <goal> — add a task to the queue
/answer <task id> <decision>
/sessions — live sessions and worktrees
/msg <session|all> <text> — message a live session
/todo <text> — add an item to todo.md
/wake [agents] — continue the work now
/handoff — the latest handoff.md"""


def handle_command(root: Path, text: str, *, spawn: Callable[[list[str]], None] | None = None) -> str:
    """One remote command -> reply text. Errors are replied, not raised."""
    from . import workflow as w, sessions as s, queue as q
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return HELP
    cmd, rest = parts[0].split("@", 1)[0].lower(), (parts[1] if len(parts) > 1 else "").strip()
    try:
        if cmd in {"/start", "/help"}:
            return HELP
        if cmd == "/status":
            h = w.build_handoff(root)
            data = q.load_queue(root)["tasks"]
            counts = {k: sum(t["status"] == k for t in data) for k in ("pending", "running", "frozen", "done", "failed")}
            pend = w.pending_approvals(root)
            return (f"Goal: {h['goal']}\nState: {h['current_state']}\nNext: {h['next_step']}\n"
                    f"Approvals waiting: {len(pend)}\nQueue: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
                    + ("" if any(counts.values()) else "empty"))
        if cmd == "/handoff":
            return w.read_handoff(root) or "No handoff yet."
        if cmd == "/approvals":
            pend = w.pending_approvals(root)
            return "\n".join(f"{a['id']} {a['rule']}: {a['command'][:200]}" for a in pend) or "No pending approvals."
        if cmd in {"/approve", "/deny"}:
            if not rest:
                return f"Use: {cmd} <id>"
            a = w.decide_approval(root, rest.split()[0], approve=cmd == "/approve")
            return f"{a['id']} {a['status']}: {a['command'][:200]}"
        if cmd == "/queue":
            t = q.add_task(root, rest)
            return f"Queued {t['id']}: {t['goal']}"
        if cmd == "/answer":
            tid, _, answer = rest.partition(" ")
            t = q.answer(root, tid, answer)
            return f"{t['id']} is back in the queue with your decision."
        if cmd == "/msg":
            to, _, body = rest.partition(" ")
            m = s.send_message(root, to, body, sender="developer")
            return f"Sent {m['id']} to {to}."
        if cmd == "/todo":
            item = w.add_todo(root, rest)
            return f"To-do {item['n']}: {item['text']}"
        if cmd == "/sessions":
            rows = [f"{x['name']} ({x['agent']}) {x['status']}" + (f", {x['unread']} unread" if x["unread"] else "")
                    for x in s.list_sessions(root)[:10]]
            wts = [f"worktree {x['name']} on {x['branch']}" for x in s.list_worktrees(root, with_changes=False)]
            return "\n".join(rows + wts) or "No sessions registered."
        if cmd == "/wake":
            argv = [sys.executable, "-m", "vcommand", "wake", *rest.split()]
            (spawn or _spawn_detached(root))(argv)
            return "Waking up. You will get the result here when it finishes."
        return "Unknown command.\n" + HELP
    except (ValueError, FileNotFoundError, KeyError) as error:
        return f"Error: {error}"


def _spawn_detached(root: Path) -> Callable[[list[str]], None]:
    def run(argv: list[str]) -> None:
        log = (root / CONFIG_DIR / "wake.log").open("a", encoding="utf-8")

        def worker() -> None:
            code = subprocess.call(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT)
            log.close()
            from .workflow import build_handoff
            try:
                h = build_handoff(root)
                notify(root, "wake", f"Wake finished (exit {code}).\nState: {h['current_state']}\nNext: {h['next_step']}")
            except (OSError, ValueError, FileNotFoundError):
                pass
        threading.Thread(target=worker, daemon=True).start()
    return run


# ---------------------------------------------------------------- Telegram long-poll remote

def _tg(token: str, method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = f"{telegram_api()}/bot{token}/{method}"
    req = urllib.request.Request(url, data=json.dumps(params).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def telegram_remote(root: Path, *, stop: threading.Event | None = None, poll_s: int = 30, out: TextIO | None = None,
                    once: bool = False, spawn: Callable[[list[str]], None] | None = None) -> int:
    """Answer commands from the configured Telegram chats until `stop` is set (or one poll if once)."""
    out = out or sys.stdout
    cfg = load_config(root)
    tg = [c for c in channels(cfg) if c["type"] == "telegram"]
    if not tg:
        raise ValueError("No telegram channel: vcmd channel add telegram --chat <id>")
    token = _secret(tg[0].get("secret", "TELEGRAM_BOT_TOKEN"))
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set (vcmd secret set TELEGRAM_BOT_TOKEN)")
    allowed = {str(c["chat_id"]) for c in tg}
    offset_path = root / CONFIG_DIR / "telegram_offset"
    try:
        offset = int(offset_path.read_text().strip())
    except (OSError, ValueError):
        offset = 0
    stop = stop or threading.Event()
    print(f"V/  REMOTE     Telegram: listening for {len(allowed)} chat(s). Send /help to your bot.", file=out, flush=True)
    while not stop.is_set():
        try:
            data = _tg(token, "getUpdates", {"offset": offset, "timeout": 0 if once else poll_s,
                                             "allowed_updates": ["message"]}, timeout=poll_s + 10)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            _log(root, f"telegram poll failed: {type(error).__name__}")
            if once:
                return 1
            stop.wait(10)
            continue
        for upd in data.get("result", []):
            offset = max(offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            text = msg.get("text") or ""
            if chat not in allowed:
                _log(root, f"telegram: ignored message from chat {chat[:4]}…")
                continue
            reply = handle_command(root, text, spawn=spawn) if text.startswith("/") else (
                "Send /help for commands. Plain text is not forwarded; use /msg <session> <text>.")
            print(f"V/  REMOTE     {text.split()[0] if text else '?'} -> {reply.splitlines()[0][:80]}", file=out, flush=True)
            try:
                _tg(token, "sendMessage", {"chat_id": chat, "text": reply[:4000]}, timeout=TIMEOUT_S)
            except (OSError, urllib.error.URLError) as error:
                _log(root, f"telegram reply failed: {type(error).__name__}")
        offset_path.write_text(str(offset), encoding="utf-8")
        if once:
            return 0
    return 0


# ---------------------------------------------------------------- autopilot

def parse_every(text: str) -> int:
    text = text.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        value = int(text[:-1]) * units[text[-1]] if text[-1] in units else int(text) * 60
    except (ValueError, IndexError, KeyError) as error:
        raise ValueError("--every like 30m, 2h or 900s") from error
    if value < 60:
        raise ValueError("--every must be at least 60s")
    return value


def run_autopilot(root: Path, agents: list[str], *, every_s: int, use_loop: bool = False, remote: bool = False,
                  max_cycles: int | None = None, budget_usd: float | None = None, timeout: int = 3600,
                  out: TextIO | None = None, stop: threading.Event | None = None) -> int:
    """`vcmd wake` every `every_s` seconds (and the Telegram remote, if asked) until Ctrl+C."""
    from .workflow import run_wake
    out = out or sys.stdout
    stop = stop or threading.Event()
    listener = None
    if remote:
        listener = threading.Thread(target=telegram_remote, args=(root,), kwargs={"stop": stop, "out": out},
                                    daemon=True)
        listener.start()
    cycles = 0
    try:
        while not stop.is_set():
            cycles += 1
            print(f"\nV/  AUTOPILOT  cycle {cycles} at {time.strftime('%H:%M:%S')}", file=out, flush=True)
            try:
                code = run_wake(root, agents, use_loop=use_loop, budget_usd=budget_usd, timeout=timeout, out=out)
                if code not in (0,):
                    from .workflow import build_handoff
                    h = build_handoff(root)
                    notify(root, "failed" if code == 1 else "frozen",
                           f"Autopilot cycle {cycles} ended with exit {code}.\nState: {h['current_state']}\nNext: {h['next_step']}")
            except Exception as error:  # noqa: BLE001 - keep the pilot running; report the problem
                print(f"V/  AUTOPILOT  cycle failed: {type(error).__name__}: {error}", file=out, flush=True)
                notify(root, "failed", f"Autopilot cycle {cycles} crashed: {type(error).__name__}: {error}")
            if max_cycles and cycles >= max_cycles:
                break
            print(f"V/  AUTOPILOT  next wake in {every_s // 60} min (Ctrl+C to stop)", file=out, flush=True)
            stop.wait(every_s)
    except KeyboardInterrupt:
        print("\nV/  AUTOPILOT  stopped", file=out)
    finally:
        stop.set()
    return 0
