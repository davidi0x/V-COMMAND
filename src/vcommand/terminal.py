"""Real terminals for the workspace: a PTY per tab, so Claude Code, Codex, a shell or any TUI works.

Unix (macOS, Linux): a pseudo-terminal with window-size support, exactly what a terminal emulator gives a
program. Windows has no `pty` in the standard library; there a tab is a pipe-based console (line-oriented
programs work, full-screen TUIs do not) — a ConPTY backend is future work and is said so in the UI.

The server keeps each terminal's recent output (1 MB ring buffer) and a byte cursor, so a browser can
reload and re-attach, and several terminals can be followed with one long-poll request.

Standard library only. A terminal is a shell: the workspace that exposes it is opt-in (`vcmd workspace`),
loopback-only, token-protected and checked against cross-origin requests.
"""
from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any

IS_WINDOWS = os.name == "nt"
if not IS_WINDOWS:
    import fcntl
    import pty
    import select
    import struct
    import termios

MAX_BUFFER = 1_000_000
MAX_SESSIONS = 10
MAX_INPUT = 65_536


class Terminal:
    def __init__(self, tid: str, label: str, argv: list[str], cwd: Path, env: dict[str, str], rows: int, cols: int,
                 notify: threading.Condition):
        self.id, self.label, self.argv, self.cwd = tid, label, argv, cwd
        self.rows, self.cols = rows, cols
        self.created = time.time()
        self.exit_code: int | None = None
        self.pty = not IS_WINDOWS
        self._buf = bytearray()
        self._base = 0  # stream offset of _buf[0]
        self._lock = threading.Lock()
        self._notify = notify
        self._master = -1
        if self.pty:
            master, slave = pty.openpty()
            self._set_size(master, rows, cols)
            self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                                         close_fds=True, start_new_session=True,
                                         preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
            os.close(slave)
            self._master = master
            target = self._read_pty
        else:
            self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, bufsize=0,
                                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            target = self._read_pipe
        threading.Thread(target=target, daemon=True, name=f"vcmd-term-{tid}").start()

    # ---- output
    def _append(self, chunk: bytes) -> None:
        with self._lock:
            self._buf += chunk
            if len(self._buf) > MAX_BUFFER:
                cut = len(self._buf) - MAX_BUFFER
                del self._buf[:cut]
                self._base += cut
        with self._notify:
            self._notify.notify_all()

    def _finish(self) -> None:
        code = self.proc.wait()
        self.exit_code = code
        if self.pty and self._master >= 0:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = -1
        with self._notify:
            self._notify.notify_all()

    def _read_pty(self) -> None:
        while True:
            try:
                ready, _, _ = select.select([self._master], [], [], 0.5)
                if ready:
                    chunk = os.read(self._master, 65536)
                    if not chunk:
                        break
                    self._append(chunk)
                elif self.proc.poll() is not None:
                    # drain what is left, then stop
                    try:
                        while select.select([self._master], [], [], 0)[0]:
                            chunk = os.read(self._master, 65536)
                            if not chunk:
                                break
                            self._append(chunk)
                    except OSError:
                        pass
                    break
            except OSError:
                break
        self._finish()

    def _read_pipe(self) -> None:
        while True:
            chunk = self.proc.stdout.read(4096)
            if not chunk:
                break
            self._append(chunk)
        self._finish()

    def read(self, since: int) -> tuple[bytes, int]:
        """Output at or after stream offset `since` (older output that fell out of the buffer is skipped)."""
        with self._lock:
            start = max(since, self._base)
            data = bytes(self._buf[start - self._base:])
            return data, self._base + len(self._buf)

    @property
    def end(self) -> int:
        with self._lock:
            return self._base + len(self._buf)

    # ---- input
    def write(self, data: bytes) -> None:
        if self.exit_code is not None:
            return
        data = data[:MAX_INPUT]
        try:
            if self.pty:
                os.write(self._master, data)
            else:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _set_size(fd: int, rows: int, cols: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        if self.pty and self._master >= 0 and self.exit_code is None:
            try:
                self._set_size(self._master, rows, cols)
                os.killpg(self.proc.pid, signal.SIGWINCH)
            except (OSError, ProcessLookupError):
                pass

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                if IS_WINDOWS:
                    self.proc.terminate()
                else:
                    os.killpg(self.proc.pid, signal.SIGHUP)
            except (OSError, ProcessLookupError):
                pass
            try:
                self.proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    if IS_WINDOWS:
                        self.proc.kill()
                    else:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass

    def info(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "cwd": str(self.cwd), "argv0": Path(self.argv[0]).name,
                "exit_code": self.exit_code, "alive": self.exit_code is None, "end": self.end,
                "rows": self.rows, "cols": self.cols, "pty": self.pty}


class TerminalManager:
    def __init__(self) -> None:
        self.cond = threading.Condition()
        self._lock = threading.Lock()
        self._terms: dict[str, Terminal] = {}
        self._n = 0

    def create(self, label: str, argv: list[str], cwd: Path, env: dict[str, str], rows: int = 24, cols: int = 80) -> Terminal:
        rows, cols = max(2, min(int(rows), 500)), max(2, min(int(cols), 1000))
        with self._lock:
            alive = [t for t in self._terms.values() if t.exit_code is None]
            if len(alive) >= MAX_SESSIONS:
                raise ValueError(f"At most {MAX_SESSIONS} live terminals; close one first")
            self._n += 1
            tid = f"t{self._n}"
            term = Terminal(tid, label, argv, cwd, env, rows, cols, self.cond)
            self._terms[tid] = term
        return term

    def get(self, tid: str) -> Terminal:
        with self._lock:
            t = self._terms.get(tid)
        if t is None:
            raise ValueError(f"No terminal {tid}")
        return t

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [t.info() for t in self._terms.values()]

    def close(self, tid: str) -> None:
        with self._lock:
            t = self._terms.pop(tid, None)
        if t is not None:
            t.close()

    def close_all(self) -> None:
        with self._lock:
            terms, self._terms = list(self._terms.values()), {}
        for t in terms:
            t.close()

    def read_many(self, cursors: dict[str, int], wait: float = 0.0) -> dict[str, Any]:
        """Output newer than each cursor; waits up to `wait` seconds when there is nothing yet."""
        deadline = time.monotonic() + max(0.0, min(wait, 25.0))
        while True:
            out: dict[str, Any] = {}
            with self._lock:
                terms = dict(self._terms)
            for tid, since in cursors.items():
                t = terms.get(tid)
                if t is None:
                    out[tid] = {"gone": True}
                    continue
                data, nxt = t.read(since)
                if data or (t.exit_code is not None and since <= nxt):
                    out[tid] = {"data": data, "next": nxt, "exit_code": t.exit_code}
            if out and any(v.get("data") or v.get("gone") for v in out.values()):
                return out
            if out and not wait:
                return out
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return out
            with self.cond:
                self.cond.wait(timeout=min(remaining, 1.0))


# ---------------------------------------------------------------- profiles

BUILTIN = (("shell", "Shell", None, False), ("claude", "Claude Code", "claude", True),
           ("codex", "Codex", "codex", True), ("opencode", "OpenCode", "opencode", True))


def default_shell() -> list[str]:
    if IS_WINDOWS:
        return [os.environ.get("COMSPEC", "cmd.exe")]
    sh = os.environ.get("SHELL")
    return [sh if sh and Path(sh).exists() else "/bin/bash", "-l"] if sh else ["/bin/sh"]


def profiles(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    import shutil
    out = []
    for pid, label, exe, agent in BUILTIN:
        argv = default_shell() if pid == "shell" else [exe]
        out.append({"id": pid, "label": label, "argv": argv, "agent": agent,
                    "installed": bool(shutil.which(argv[0])) if pid != "shell" else True})
    for p in (cfg.get("terminal") or {}).get("profiles", []):
        if isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("argv"), list) \
                and p["argv"] and all(isinstance(a, str) for a in p["argv"]):
            out.append({"id": "custom:" + p["name"], "label": p["name"], "argv": p["argv"], "agent": True,
                        "installed": bool(shutil.which(p["argv"][0])),
                        "secrets": p.get("secrets") if isinstance(p.get("secrets"), list) else None})
    return out


def terminal_env(cwd: Path, profile: dict[str, Any], label: str) -> dict[str, str]:
    """Environment for a terminal tab.

    No VCOMMAND_WRAPPED: interactive agents must run the V/COMMAND hooks (frame at start, gates at stop,
    session registry). Agent tabs get the stored API keys (scoped by the profile's "secrets" list if present);
    a plain shell does not — keys come only from your own shell variables. Channel tokens never."""
    from .adapters import PARENT_SESSION_VARS
    from .secrets_store import NOT_FOR_AGENTS
    env = {k: v for k, v in os.environ.items() if k not in NOT_FOR_AGENTS and k not in PARENT_SESSION_VARS}
    if profile.get("agent") and not os.environ.get("VCOMMAND_NO_SECRETS"):
        try:
            from .secrets_store import secrets_env
            keys = secrets_env()
            if profile.get("secrets") is not None:
                keys = {k: v for k, v in keys.items() if k in profile["secrets"]}
            env.update({k: v for k, v in keys.items() if k not in env})
        except Exception:  # noqa: BLE001 - a broken secret store must not block a terminal
            pass
    env.update(TERM="xterm-256color", COLORTERM="truecolor", VCOMMAND_ROOT=str(cwd), VCOMMAND_SESSION=label)
    return env
