from pathlib import Path
import base64
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from vcommand.core import init_project
from vcommand.dashboard import make_server
from vcommand import terminal as tm
from vcommand import workspace as ws

POSIX = os.name != "nt"


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Repo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@e.com")
        git(self.root, "config", "user.name", "t")
        (self.root / ".gitignore").write_text(".vcommand/\n")
        (self.root / "a.py").write_bytes(b"x = 1\n")  # bytes: no CRLF translation on Windows
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.txt").write_text("hello\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "init")
        init_project(self.root)
        p = mock.patch.dict(os.environ, {"VCOMMAND_NO_SECRETS": "1"})
        p.start()
        self.addCleanup(p.stop)


class WorkspaceFilesTests(Repo):
    def test_tree_status_diff_revert(self):
        t = ws.tree(self.root)
        self.assertEqual(t["files"], [".gitignore", "a.py", "sub/b.txt"])  # tool state is not listed
        (self.root / "a.py").write_text("x = 2\n")
        (self.root / "new.txt").write_text("n1\nn2\n")
        st = {s["path"]: s["label"] for s in ws.status(self.root)}
        self.assertEqual(st, {"a.py": "modified", "new.txt": "untracked"})
        d = ws.diff(self.root, "a.py")
        self.assertIn("-x = 1", d["diff"])
        self.assertIn("+x = 2", d["diff"])
        self.assertIn("+n2", ws.diff(self.root, "new.txt")["diff"])
        ws.revert(self.root, "a.py")
        self.assertEqual((self.root / "a.py").read_text(), "x = 1\n")
        ws.revert(self.root, "new.txt")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(ws.status(self.root), [])
        with self.assertRaises(ws.WorkspaceError):
            ws.revert(self.root, "a.py")

    def test_read_write_conflict_and_create(self):
        f = ws.read_file(self.root, "a.py")
        self.assertEqual(f["content"], "x = 1\n")
        self.assertIsInstance(f["mtime_ns"], str)  # nanoseconds do not fit a JavaScript number
        ws.write_file(self.root, "a.py", "x = 5\n", base_mtime_ns=f["mtime_ns"])
        self.assertEqual((self.root / "a.py").read_text(), "x = 5\n")
        with self.assertRaises(ws.WorkspaceError) as e:  # stale base: an agent changed it meanwhile
            ws.write_file(self.root, "a.py", "x = 6\n", base_mtime_ns=f["mtime_ns"])
        self.assertIn("changed on disk", str(e.exception))
        ws.write_file(self.root, "pkg/new.py", "y = 1\n", create=True)
        self.assertEqual((self.root / "pkg" / "new.py").read_text(), "y = 1\n")
        with self.assertRaises(ws.WorkspaceError):
            ws.write_file(self.root, "missing.py", "z")  # no create flag
        mode_before = (self.root / "a.py").stat().st_mode
        ws.write_file(self.root, "a.py", "x = 7\n")
        self.assertEqual((self.root / "a.py").stat().st_mode, mode_before)

    def test_path_safety(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("secret")
        self.addCleanup(outside.unlink)
        for bad in ("../outside.txt", "/etc/passwd", "sub/../../outside.txt", ".git/config", "sub/../.git/HEAD", "", "a\0b"):
            with self.assertRaises(ws.WorkspaceError, msg=bad):
                ws.read_file(self.root, bad)
        with self.assertRaises(ws.WorkspaceError):
            ws.write_file(self.root, "../evil.txt", "x", create=True)
        with self.assertRaises(ws.WorkspaceError):
            ws.write_file(self.root, ".git/hooks/pre-commit", "#!/bin/sh\n", create=True)
        if POSIX:
            (self.root / "link").symlink_to(outside)
            with self.assertRaises(ws.WorkspaceError):  # a symlink that points out of the project
                ws.read_file(self.root, "link")
            (self.root / "dirlink").symlink_to(outside.parent)
            with self.assertRaises(ws.WorkspaceError):
                ws.write_file(self.root, "dirlink/x.txt", "x", create=True)
        with self.assertRaises(ws.WorkspaceError):
            ws.diff(self.root, "../x")

    def test_binary_and_large(self):
        (self.root / "bin.dat").write_bytes(b"\x00\x01\x02")
        with self.assertRaises(ws.WorkspaceError):
            ws.read_file(self.root, "bin.dat")
        (self.root / "big.txt").write_text("x" * (ws.MAX_READ + 1))
        with self.assertRaises(ws.WorkspaceError):
            ws.read_file(self.root, "big.txt")
        (self.root / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
        with self.assertRaises(ws.WorkspaceError):
            ws.read_file(self.root, "latin.txt")


@unittest.skipUnless(POSIX, "PTY terminals are Unix-only; Windows uses pipes")
class TerminalTests(unittest.TestCase):
    def wait_for(self, term, text, timeout=8):
        end = time.time() + timeout
        seen = b""
        while time.time() < end:
            data, _ = term.read(0)
            seen = data
            if text.encode() in data:
                return data
            time.sleep(0.05)
        self.fail(f"{text!r} not seen in {seen[-300:]!r}")

    def test_pty_echo_size_resize_exit_and_cursor(self):
        mgr = tm.TerminalManager()
        self.addCleanup(mgr.close_all)
        code = ("import os, sys, time\n"
                "print('SIZE', os.get_terminal_size().lines, os.get_terminal_size().columns, flush=True)\n"
                "print('TTY', os.isatty(0), os.isatty(1), flush=True)\n"
                "line = sys.stdin.readline().strip()\n"
                "print('GOT', line, flush=True)\n"
                "import signal\n"
                "signal.signal(signal.SIGWINCH, lambda *a: print('WINCH', os.get_terminal_size().lines, os.get_terminal_size().columns, flush=True))\n"
                "print('READY', flush=True)\n"
                "time.sleep(30)\n")
        t = mgr.create("py", [sys.executable, "-u", "-c", code], Path.cwd(), dict(os.environ), rows=30, cols=100)
        self.wait_for(t, "SIZE 30 100")
        self.wait_for(t, "TTY True True")  # a real terminal, so TUIs (claude, codex) behave
        t.write(b"hello world\n")
        self.wait_for(t, "GOT hello world")
        self.wait_for(t, "READY")
        t.resize(40, 120)
        self.wait_for(t, "WINCH 40 120")
        # cursors: reading from the end returns nothing new; reading from an earlier offset replays
        data, end = t.read(0)
        self.assertEqual(t.read(end)[0], b"")
        self.assertIn(b"hello world", t.read(max(0, end - 200))[0])
        mgr.close(t.id)
        self.assertEqual(mgr.list(), [])

    def test_exit_code_and_read_many_waits(self):
        mgr = tm.TerminalManager()
        self.addCleanup(mgr.close_all)
        t = mgr.create("sh", [sys.executable, "-c", "import time; time.sleep(0.4); print('bye'); raise SystemExit(3)"],
                       Path.cwd(), dict(os.environ))
        res = mgr.read_many({t.id: 0}, wait=5)  # blocks until output arrives
        self.assertIn(b"bye", res[t.id]["data"])
        deadline = time.time() + 5
        while mgr.list()[0]["exit_code"] is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(mgr.list()[0]["exit_code"], 3)
        self.assertEqual(mgr.read_many({"nope": 0}, wait=0)["nope"], {"gone": True})

    def test_ring_buffer_and_limits(self):
        mgr = tm.TerminalManager()
        self.addCleanup(mgr.close_all)
        t = mgr.create("big", [sys.executable, "-c", f"import sys; sys.stdout.write('x' * {tm.MAX_BUFFER + 50000}); sys.stdout.flush()"],
                       Path.cwd(), dict(os.environ))
        deadline = time.time() + 10
        while t.exit_code is None and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        data, end = t.read(0)
        self.assertLessEqual(len(data), tm.MAX_BUFFER)
        self.assertGreater(end, tm.MAX_BUFFER)  # offsets keep counting past what was trimmed
        for _ in range(tm.MAX_SESSIONS + 1):
            try:
                mgr.create("s", [sys.executable, "-c", "import time; time.sleep(20)"], Path.cwd(), dict(os.environ))
            except ValueError:
                break
        else:
            self.fail("session limit not enforced")

    def test_env_has_no_wrapped_flag_and_no_channel_tokens(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "1:abc", "CLAUDE_CODE_SESSION_ID": "parent",
                                          "CLAUDE_CODE_CHILD_SESSION": "1", "VCOMMAND_WRAPPED": ""}):
            env = tm.terminal_env(Path("/tmp/x"), {"agent": True}, "claude-1")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertNotIn("CLAUDE_CODE_CHILD_SESSION", env)  # would switch off the child's transcript saving
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["VCOMMAND_SESSION"], "claude-1")
        self.assertFalse(env.get("VCOMMAND_WRAPPED"))  # interactive agents must run the hooks

    def test_profiles(self):
        ps = {p["id"]: p for p in tm.profiles({"terminal": {"profiles": [{"name": "aider", "argv": ["aider", "--yes"]},
                                                                           {"name": "bad", "argv": "x"}]}})}
        self.assertTrue({"shell", "claude", "codex", "opencode", "custom:aider"} <= set(ps))
        self.assertNotIn("custom:bad", ps)
        self.assertTrue(ps["shell"]["installed"])


class WorkspaceServerTests(Repo):
    def start(self, workspace):
        self.server, url = make_server(self.root, 0, workspace=workspace)
        self.token = url.split("token=")[1]
        self.port = self.server.server_address[1]
        self.assertEqual(url.split("?")[0].endswith("/workspace"), workspace)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, body=None, headers=None, token=True):
        h = {"X-VCMD-Token": self.token} if token else {}
        h.update(headers or {})
        if body is not None:
            h.setdefault("Content-Type", "application/json")
            body = json.dumps(body)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_workspace_is_off_for_the_plain_dashboard(self):
        self.start(False)
        self.assertEqual(self.req("GET", "/api/ws/info")[0], 403)
        self.assertEqual(self.req("POST", "/api/term/new", {"profile": "shell"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ws/save", {"path": "a.py", "content": "x"})[0], 403)
        self.assertEqual(self.req("GET", f"/workspace?token={self.token}", token=False)[0], 403)

    def test_access_control_and_cross_origin(self):
        self.start(True)
        self.assertEqual(self.req("GET", "/api/ws/tree", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/ws/tree", headers={"X-VCMD-Token": "bad"})[0], 401)
        self.assertEqual(self.req("GET", "/api/ws/tree", headers={"Host": f"evil.test:{self.port}"})[0], 403)
        # a web page on another origin cannot drive the shell, even with a leaked token
        self.assertEqual(self.req("GET", "/api/ws/tree", headers={"Origin": "http://evil.test"})[0], 403)
        self.assertEqual(self.req("POST", "/api/term/new", {"profile": "shell"}, headers={"Origin": "http://evil.test"})[0], 403)
        self.assertEqual(self.req("GET", "/api/ws/tree", headers={"Origin": f"http://127.0.0.1:{self.port}"})[0], 200)
        self.assertEqual(self.req("POST", "/api/ws/save", "x=1", headers={"Content-Type": "text/plain"})[0], 415)

    def test_files_over_http(self):
        self.start(True)
        info = json.loads(self.req("GET", "/api/ws/info")[1])
        self.assertEqual((info["project"], info["repo"]), (self.root.name, True))
        self.assertIn("claude", [p["id"] for p in info["profiles"]])
        f = json.loads(self.req("GET", "/api/ws/file?path=a.py")[1])
        self.assertEqual(f["content"], "x = 1\n")
        s, r = self.req("POST", "/api/ws/save", {"path": "a.py", "content": "x = 9\n", "base_mtime_ns": f["mtime_ns"]})
        self.assertEqual(s, 200)
        s, r = self.req("POST", "/api/ws/save", {"path": "a.py", "content": "x = 0\n", "base_mtime_ns": f["mtime_ns"]})
        self.assertEqual(s, 400)
        self.assertIn("changed on disk", json.loads(r)["error"])
        self.assertEqual(self.req("GET", "/api/ws/file?path=../../etc/passwd")[0], 400)
        changes = json.loads(self.req("GET", "/api/ws/status")[1])["changes"]
        self.assertEqual(changes[0]["path"], "a.py")
        self.assertIn("+x = 9", json.loads(self.req("GET", "/api/ws/diff?path=a.py")[1])["diff"])
        self.assertEqual(self.req("POST", "/api/ws/revert", {"path": "a.py"})[0], 200)
        self.assertEqual((self.root / "a.py").read_text(), "x = 1\n")
        page = self.req("GET", f"/workspace?token={self.token}", token=False)
        self.assertEqual(page[0], 200)
        self.assertIn(b"xterm", page[1])

    def test_dashboard_state_tells_whether_the_workspace_is_on(self):
        self.start(False)
        self.assertFalse(json.loads(self.req("GET", "/api/state")[1])["workspace_enabled"])
        self.server.shutdown()
        self.start(True)
        self.assertTrue(json.loads(self.req("GET", "/api/state")[1])["workspace_enabled"])

    def test_xterm_assets_served(self):
        self.start(True)
        s, body = self.req("GET", "/assets/xterm.js", token=False)
        self.assertEqual(s, 200)
        self.assertGreater(len(body), 100_000)
        self.assertEqual(self.req("GET", "/assets/xterm.css", token=False)[0], 200)
        self.assertEqual(self.req("GET", "/assets/addon-fit.js", token=False)[0], 200)

    @unittest.skipUnless(POSIX, "PTY terminals are Unix-only")
    def test_terminal_over_http(self):
        self.start(True)
        s, r = self.req("POST", "/api/term/new", {"profile": "shell", "rows": 24, "cols": 80})
        self.assertEqual(s, 200, r)
        tid = json.loads(r)["terminal"]["id"]
        self.assertEqual(self.req("POST", "/api/term/input", {"id": tid, "data": "echo $((6*7)) && pwd\n"})[0], 200)
        seen, since = b"", 0
        deadline = time.time() + 10
        while time.time() < deadline and b"42" not in seen:
            s, r = self.req("GET", f"/api/term/read?cursors={tid}:{since}&wait=2")
            t = json.loads(r)["terminals"][tid]
            if t.get("data"):
                seen += base64.b64decode(t["data"])
                since = t["next"]
        self.assertIn(b"42", seen)
        self.assertIn(str(self.root).encode(), seen)  # the shell starts in the project
        self.assertEqual(self.req("POST", "/api/term/resize", {"id": tid, "rows": 30, "cols": 90})[0], 200)
        self.assertEqual(len(json.loads(self.req("GET", "/api/term/list")[1])["terminals"]), 1)
        self.assertEqual(self.req("POST", "/api/term/close", {"id": tid})[0], 200)
        self.assertEqual(json.loads(self.req("GET", "/api/term/list")[1])["terminals"], [])
        self.assertEqual(self.req("POST", "/api/term/new", {"profile": "nope"})[0], 400)
        self.assertEqual(self.req("POST", "/api/term/new", {"run_agent": "no-such-agent"})[0], 400)

    @unittest.skipUnless(POSIX, "PTY terminals are Unix-only")
    def test_verified_agent_run_in_a_terminal(self):
        from vcommand.core import load_config, save_config
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('done.txt').exists() else 1)"]]
        cfg["agents"] = {"maker": [sys.executable, "-c", "import pathlib; pathlib.Path('done.txt').write_text('ok')", "{prompt}"]}
        save_config(self.root, cfg)
        self.start(True)
        s, r = self.req("POST", "/api/term/new", {"run_agent": "maker", "instruction": "make it"})
        self.assertEqual(s, 200, r)
        tid = json.loads(r)["terminal"]["id"]
        deadline = time.time() + 30
        seen, since = b"", 0
        while time.time() < deadline and b"verified_by_configured_checks" not in seen:
            s, r = self.req("GET", f"/api/term/read?cursors={tid}:{since}&wait=2")
            t = json.loads(r)["terminals"][tid]
            if t.get("data"):
                seen += base64.b64decode(t["data"])
                since = t["next"]
        self.assertIn(b"verified_by_configured_checks", seen)
        self.assertTrue((self.root / "done.txt").exists())


if __name__ == "__main__":
    unittest.main()
