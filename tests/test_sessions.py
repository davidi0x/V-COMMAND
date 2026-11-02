from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from vcommand.core import init_project, load_config, save_config, list_evidence
from vcommand.state import start_task
from vcommand.adapters import run_hook, run_agents, session_argv, agent_templates, agent_env
from vcommand import sessions as se, channels as ch, workflow as w, queue as q
from vcommand.cli import main

GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


class Repo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "app"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / ".gitignore").write_text(".vcommand/\n")
        (self.root / "shared.py").write_text("x = 1\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "init")
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        save_config(self.root, cfg)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        env = mock.patch.dict(os.environ, {"VCOMMAND_NO_SECRETS": "1"})
        env.start()
        self.addCleanup(env.stop)
        for k in ("VCOMMAND_WRAPPED", "VCOMMAND_SESSION", "VCOMMAND_ROOT", "VCOMMAND_SHARED_ROOT", "CLAUDE_ENV_FILE"):
            os.environ.pop(k, None)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(argv))
        return code, out.getvalue()

    def hook(self, event, payload, target="claude"):
        out = io.StringIO()
        run_hook(target, event, io.StringIO(json.dumps(payload)), out, io.StringIO())
        return out.getvalue()


class WorktreeTests(Repo):
    def test_worktree_lifecycle_and_conflicts(self):
        a = se.create_worktree(self.root, "auth", goal="Build auth")
        b = se.create_worktree(self.root, "ui")
        pa, pb = Path(a["path"]), Path(b["path"])
        self.assertEqual(pa, self.base / "app-auth")
        self.assertEqual(git(pa, "branch", "--show-current").strip(), "vcmd/auth")
        self.assertTrue((pa / ".vcommand" / "config.json").exists())
        self.assertEqual(json.loads((pa / ".vcommand" / "task.json").read_text())["goal"], "Build auth")
        self.assertEqual(se.shared_root(pa), self.root)  # state of the main repo is reachable from a worktree
        self.assertEqual(se.conflicts(self.root), [])
        (pa / "shared.py").write_text("x = 2\n")
        (pb / "shared.py").write_text("x = 3\n")
        (pb / "only_ui.py").write_text("y = 1\n")
        clash = se.conflicts(self.root)
        self.assertEqual(clash, [{"file": "shared.py", "worktrees": ["auth", "ui"]}])
        self.assertEqual(self.cli("worktree", "conflicts")[0], 1)
        with self.assertRaises(ValueError):
            se.remove_worktree(self.root, "ui")  # uncommitted changes
        se.remove_worktree(self.root, "ui", force=True)
        self.assertFalse(pb.exists())
        self.assertEqual([x["name"] for x in se.list_worktrees(self.root)], ["auth"])
        with self.assertRaises(ValueError):
            se.create_worktree(self.root, "bad name")

    def test_collision_warning_once_per_file(self):
        a = se.create_worktree(self.root, "auth")
        b = se.create_worktree(self.root, "ui")
        (Path(a["path"]) / "shared.py").write_text("x = 2\n")
        payload = {"cwd": b["path"], "session_id": "s-ui", "tool_name": "Edit",
                   "tool_input": {"file_path": str(Path(b["path"]) / "shared.py")}}
        first = json.loads(self.hook("post-tool", payload))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("`shared.py` is also changed in worktree(s) auth", first)
        self.assertEqual(self.hook("post-tool", payload), "")


class SessionMessageTests(Repo):
    def test_register_message_deliver_and_stop(self):
        a = se.create_worktree(self.root, "arch")
        env_file = self.base / "env.sh"
        env_file.write_text("")
        with mock.patch.dict(os.environ, {"CLAUDE_ENV_FILE": str(env_file)}):
            text = self.hook("session-start", {"cwd": a["path"], "session_id": "sid-arch-1", "source": "startup"})
        self.assertIn("Session startup `arch`", text)
        self.assertIn("export VCOMMAND_SESSION=arch", env_file.read_text())
        self.hook("session-start", {"cwd": str(self.root), "session_id": "sid-main-22", "source": "startup"})
        names = {s["name"]: s for s in se.list_sessions(self.root)}
        self.assertEqual(set(names), {"arch", "claude-code-sid-ma"})  # worktree name, else agent + session id
        self.assertEqual(names["arch"]["status"], "active")
        code, _ = self.cli("msg", "send", "arch", "Auth flow updated. Please review refresh logic.", "--from", "sonnet")
        self.assertEqual(code, 0)
        self.assertEqual({s["name"]: s["unread"] for s in se.list_sessions(self.root)}["arch"], 1)
        got = json.loads(self.hook("post-tool", {"cwd": a["path"], "session_id": "sid-arch-1", "tool_name": "Bash",
                                                  "tool_input": {"command": "ls"}}))
        self.assertIn("from sonnet] Auth flow updated", got["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.hook("post-tool", {"cwd": a["path"], "session_id": "sid-arch-1", "tool_name": "Bash",
                                                 "tool_input": {"command": "ls"}}), "")
        se.send_message(self.root, "all", "Freeze merges for 10 min", sender="developer")
        stop = json.loads(self.hook("stop", {"cwd": a["path"], "session_id": "sid-arch-1"}))
        self.assertEqual(stop["decision"], "block")
        self.assertIn("Freeze merges", stop["reason"])
        prompt = self.hook("prompt", {"cwd": str(self.root), "session_id": "sid-main-22", "prompt": "hi"})
        self.assertIn("Freeze merges", prompt)  # broadcast reaches every session once
        self.hook("session-end", {"cwd": a["path"], "session_id": "sid-arch-1"})
        self.assertEqual({s["name"]: s["status"] for s in se.list_sessions(self.root)}["arch"], "ended")

    def test_wrapped_agent_gets_messages_in_prompt(self):
        start_task(self.root, "Ship")
        cfg = load_config(self.root)
        cfg["agents"] = {"bot": [sys.executable, "-c",
                                 "import sys, pathlib; assert 'Rebase on main first' in sys.argv[1]; "
                                 "pathlib.Path('fixed.txt').write_text('x')", "{prompt}"]}
        save_config(self.root, cfg)
        se.send_message(self.root, "bot", "Rebase on main first")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_agents(self.root, ["bot"], out=io.StringIO()), 0)

    def test_rotation_note_on_large_transcript(self):
        cfg = load_config(self.root)
        cfg["rotation"] = {"max_context_tokens": 1000}
        save_config(self.root, cfg)
        start_task(self.root, "Long task")
        transcript = self.base / "t.jsonl"
        transcript.write_text("x" * 8000)
        payload = {"cwd": str(self.root), "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "ls"},
                   "transcript_path": str(transcript)}
        first = json.loads(self.hook("post-tool", payload))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Context rot", first)
        self.assertTrue((self.root / ".vcommand" / "handoff.md").exists())
        self.assertEqual(self.hook("post-tool", payload), "")  # once per session


class ResumeAndRoleTests(Repo):
    def test_session_argv(self):
        t = agent_templates({})
        claude = session_argv(t["claude"], "resume")
        self.assertEqual(claude[claude.index("--resume") + 1], "{session}")
        self.assertLess(claude.index("--resume"), claude.index("{prompt}"))
        self.assertIn("--fork-session", session_argv(t["claude"], "fork"))
        self.assertEqual(session_argv(t["codex"], "resume")[:3], ["codex", "exec", "resume"])
        self.assertIsNone(session_argv(t["codex"], "fork"))
        self.assertIsNone(session_argv(t["opencode"], "resume"))

    def test_continue_uses_recorded_session(self):
        start_task(self.root, "Ship")
        code = ("import json, sys, pathlib\n"
                "args = sys.argv[1:]\n"
                "sid = args[args.index('--resume') + 1] if '--resume' in args else 'sess-1'\n"
                "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': sid}))\n"
                "pathlib.Path('resumed.txt').write_text(sid if '--resume' in args else '')\n"
                "print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'ok', 'session_id': sid}))\n")
        cfg = load_config(self.root)
        cfg["agents"] = {"fake": {"argv": [sys.executable, "-c", code, "{prompt}"], "parser": "claude-stream",
                                  "resume": [sys.executable, "-c", code, "--resume", "{session}", "{prompt}"]}}
        save_config(self.root, cfg)
        with contextlib.redirect_stdout(io.StringIO()):
            run_agents(self.root, ["fake"], out=io.StringIO())
            self.assertEqual(list_evidence(self.root)[-1]["agent_session"], "sess-1")
            run_agents(self.root, ["fake"], out=io.StringIO(), session="resume")
        self.assertEqual((self.root / "resumed.txt").read_text(), "sess-1")

    def test_roles_cli_and_queue_routing(self):
        self.assertEqual(self.cli("roles", "set", "hard", "claude-opus")[0], 0)
        self.assertEqual(self.cli("roles", "set", "plan", "claude-opus")[0], 0)
        self.assertEqual(load_config(self.root)["roles"], {"hard": ["claude-opus"], "plan": "claude-opus"})
        self.assertEqual(self.cli("roles", "set", "x", "no-such-agent")[0], 2)
        self.assertEqual(q.role_agents(load_config(self.root), "hard"), ["claude-opus"])
        self.assertEqual(self.cli("queue", "add", "design bridge", "--role", "hard")[0], 0)
        self.assertEqual(q.load_queue(self.root)["tasks"][0]["role"], "hard")
        self.assertEqual(self.cli("queue", "add", "x", "--role", "missing")[0], 2)

    def test_channel_secrets_never_reach_agents(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "SLACK_WEBHOOK_URL": "https://x",
                                          "CLAUDE_CODE_SESSION_ID": "parent", "CLAUDE_ENV_FILE": "/x"}):
            env = agent_env(self.root)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)  # a child agent must not reuse its parent's session
        self.assertNotIn("CLAUDE_ENV_FILE", env)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", env)
        self.assertNotIn("SLACK_WEBHOOK_URL", env)


class FakeApi(BaseHTTPRequestHandler):
    calls: list = []
    updates: list = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = body.decode()
        FakeApi.calls.append((self.path, data, dict(self.headers)))
        reply = {"ok": True, "result": FakeApi.updates if self.path.endswith("/getUpdates") else {}}
        if self.path.endswith("/getUpdates"):
            FakeApi.updates = []
        raw = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ChannelTests(Repo):
    def setUp(self):
        super().setUp()
        FakeApi.calls, FakeApi.updates = [], []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"
        patch = mock.patch.dict(os.environ, {"VCOMMAND_TELEGRAM_API": self.api, "TELEGRAM_BOT_TOKEN": "42:tok",
                                             "VCMD_TEST_HOOK_URL": self.api + "/hook", "NO_PROXY": "127.0.0.1",
                                             "no_proxy": "127.0.0.1"})
        patch.start()
        self.addCleanup(patch.stop)
        ch.add_channel(self.root, "telegram", chat_id="777")
        ch.add_channel(self.root, "webhook", secret="VCMD_TEST_HOOK_URL", events=["approval"])

    def test_approval_reaches_phone_and_is_answered_from_there(self):
        req = w.request_approval(self.root, "vercel deploy --prod", "deploy", agent="claude")
        paths = [c[0] for c in FakeApi.calls]
        self.assertIn("/bot42:tok/sendMessage", paths)
        self.assertIn("/hook", paths)
        tg = next(c[1] for c in FakeApi.calls if c[0].endswith("sendMessage"))
        self.assertEqual(tg["chat_id"], "777")
        self.assertIn(f"/approve {req['id']}", tg["text"])
        FakeApi.calls = []
        FakeApi.updates = [
            {"update_id": 10, "message": {"chat": {"id": 777}, "text": f"/approve {req['id']}"}},
            {"update_id": 11, "message": {"chat": {"id": 666}, "text": "/approve whatever"}},  # stranger: ignored
            {"update_id": 12, "message": {"chat": {"id": 777}, "text": "/queue Add rate limiting"}},
        ]
        self.assertEqual(ch.telegram_remote(self.root, once=True, out=io.StringIO()), 0)
        self.assertTrue(w.is_approved(self.root, "vercel deploy --prod"))
        self.assertEqual(q.load_queue(self.root)["tasks"][0]["goal"], "Add rate limiting")
        replies = [c[1] for c in FakeApi.calls if c[0].endswith("sendMessage")]
        self.assertEqual({r["chat_id"] for r in replies}, {"777"})
        self.assertEqual(len(replies), 2)
        self.assertEqual((self.root / ".vcommand" / "telegram_offset").read_text(), "13")

    def test_commands(self):
        start_task(self.root, "Ship it")
        self.assertIn("Goal: Ship it", ch.handle_command(self.root, "/status"))
        self.assertIn("Sent", ch.handle_command(self.root, "/msg all hello"))
        self.assertIn("Error", ch.handle_command(self.root, "/approve apr-nope"))
        spawned = []
        self.assertIn("Waking", ch.handle_command(self.root, "/wake claude", spawn=spawned.append))
        self.assertEqual(spawned[0][-2:], ["wake", "claude"])
        self.assertIn("/status", ch.handle_command(self.root, "/help"))

    def test_msg_to_developer_and_channel_cli(self):
        code, text = self.cli("msg", "send", "developer", "Need a decision on the schema", "--from", "arch")
        self.assertEqual(code, 0)
        tg = next(c[1] for c in FakeApi.calls if c[0].endswith("sendMessage"))
        self.assertIn("From arch: Need a decision", tg["text"])
        code, text = self.cli("channel", "list")
        self.assertIn("telegram", text)
        self.assertEqual(self.cli("channel", "test")[0], 0)
        self.assertEqual(self.cli("channel", "add", "ntfy", "--topic", "short")[0], 2)

    def test_failures_never_raise(self):
        with mock.patch.dict(os.environ, {"VCOMMAND_TELEGRAM_API": "http://127.0.0.1:9"}):
            self.assertEqual(ch.notify(self.root, "failed", "x"), 0)
        self.assertIn("telegram failed failed", (self.root / ".vcommand" / "channels.log").read_text())

    def test_autopilot_and_every(self):
        self.assertEqual(ch.parse_every("30m"), 1800)
        self.assertEqual(ch.parse_every("2h"), 7200)
        with self.assertRaises(ValueError):
            ch.parse_every("10s")
        out = io.StringIO()
        self.assertEqual(ch.run_autopilot(self.root, ["claude"], every_s=60, max_cycles=1, out=out), 0)
        self.assertIn("nothing to do", out.getvalue())


if __name__ == "__main__":
    unittest.main()
