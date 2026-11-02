from pathlib import Path
import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest

from vcommand.core import init_project
from vcommand.state import start_task, add_ledger_entry
from vcommand import secrets_store as ss
from vcommand.dashboard import make_server, install_command, start_background, stop_background, running
from vcommand.queue import add_task, ask, load_queue
from vcommand.adapters import agent_env, install_hooks


class SecretEnv(unittest.TestCase):
    """Every test gets its own secret store (never the developer's real one)."""
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = {k: os.environ.get(k) for k in ("VCOMMAND_HOME", "VCOMMAND_SECRETS_BACKEND", "VCMD_TEST_KEY")}
        os.environ["VCOMMAND_HOME"] = self.home.name
        os.environ["VCOMMAND_SECRETS_BACKEND"] = "file"
        os.environ.pop("VCMD_TEST_KEY", None)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class SecretStoreTests(SecretEnv):
    def test_roundtrip_mask_and_permissions(self):
        r = ss.set_secret("VCMD_TEST_KEY", "sk-test-0123456789abcdef")
        self.assertEqual(r["hint"], "sk-…cdef")
        self.assertEqual(ss.get_secret("VCMD_TEST_KEY"), "sk-test-0123456789abcdef")
        listed = ss.list_secrets()
        self.assertEqual([x["name"] for x in listed], ["VCMD_TEST_KEY"])
        self.assertNotIn("0123456789", json.dumps(listed))
        if os.name != "nt":
            mode = stat.S_IMODE(os.stat(Path(self.home.name) / "secrets.json").st_mode)
            self.assertEqual(mode, 0o600)
        ss.delete_secret("VCMD_TEST_KEY")
        self.assertIsNone(ss.get_secret("VCMD_TEST_KEY"))

    def test_invalid_names_and_empty_values(self):
        for bad in ("lower", "WITH SPACE", "1START", ""):
            with self.assertRaises(ValueError):
                ss.set_secret(bad, "x")
        with self.assertRaises(ValueError):
            ss.set_secret("OK_NAME", "   ")

    def test_agents_receive_secrets_but_shell_wins(self):
        ss.set_secret("VCMD_TEST_KEY", "from-store-12345")
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(agent_env(Path(root))["VCMD_TEST_KEY"], "from-store-12345")
            os.environ["VCMD_TEST_KEY"] = "from-shell"
            self.assertEqual(agent_env(Path(root))["VCMD_TEST_KEY"], "from-shell")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_dpapi_encrypts_at_rest(self):
        os.environ["VCOMMAND_SECRETS_BACKEND"] = ""
        b = ss.backend()
        self.assertIsInstance(b, ss.DpapiBackend)
        b.set("VCMD_TEST_KEY", "dpapi-secret-value")
        raw = (Path(self.home.name) / "secrets.dpapi.json").read_text()
        self.assertNotIn("dpapi-secret-value", raw)
        self.assertEqual(b.get("VCMD_TEST_KEY"), "dpapi-secret-value")


class DashboardServerTests(SecretEnv):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)
        start_task(self.root, "Ship the dashboard")
        add_ledger_entry(self.root, tried="x", failure="y", pattern="eval(")
        self.server, url = make_server(self.root, 0)
        self.token = url.split("token=")[1]
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, body=None, headers=None, token=True):
        h = {"X-VCMD-Token": self.token} if token else {}
        h.update(headers or {})
        if body is not None:
            h.setdefault("Content-Type", "application/json")
            body = json.dumps(body) if not isinstance(body, str) else body
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_access_control(self):
        self.assertEqual(self.req("GET", "/api/state", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/state", headers={"X-VCMD-Token": "wrong"})[0], 401)
        self.assertEqual(self.req("GET", "/api/state", headers={"Host": f"attacker.test:{self.port}"})[0], 403)
        self.assertEqual(self.req("POST", "/api/secret", "name=X", {"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(self.req("GET", "/", token=False)[0], 401)
        self.assertEqual(self.req("GET", f"/?token={self.token}", token=False)[0], 200)

    def test_state_and_secret_never_returned(self):
        status, _ = self.req("POST", "/api/secret", {"name": "VCMD_TEST_KEY", "value": "sk-live-SUPERSECRET-9999"})
        self.assertEqual(status, 200)
        status, raw = self.req("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn(b"SUPERSECRET", raw)
        state = json.loads(raw)
        self.assertEqual(state["task"]["goal"], "Ship the dashboard")
        self.assertEqual(state["kpi"]["ledger"], 1)
        self.assertEqual(state["secrets"]["stored"][0]["hint"], "sk-…9999")
        self.assertEqual(self.req("POST", "/api/secret/delete", {"name": "VCMD_TEST_KEY"})[0], 200)
        self.assertEqual(json.loads(self.req("GET", "/api/state")[1])["secrets"]["stored"], [])

    def test_queue_actions_and_frame(self):
        status, raw = self.req("POST", "/api/queue/add", {"goal": "Write docs", "gates": ["python -c pass"], "focus": []})
        self.assertEqual(status, 200)
        task_id = json.loads(raw)["id"]
        ask(self.root, task_id, "Which format?", ["md", "rst"])
        self.assertEqual(self.req("POST", "/api/queue/answer", {"id": task_id, "text": "md"})[0], 200)
        task = load_queue(self.root)["tasks"][0]
        self.assertEqual((task["status"], task["answers"][0]["answer"], task["gates"]), ("pending", "md", [["python", "-c", "pass"]]))
        status, frame = self.req("GET", "/api/frame")
        self.assertIn(b"Ship the dashboard", frame)
        self.assertEqual(self.req("POST", "/api/nope", {})[0], 400)


class CommandTests(unittest.TestCase):
    def test_slash_command_installed_with_claude_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = install_command(root)
            text = path.read_text()
            self.assertIn("vcmd dashboard --background", text)
            self.assertIn("allowed-tools: Bash(vcmd dashboard:*)", text)

    @unittest.skipIf(sys.platform == "win32", "detached background process test is POSIX-only")
    def test_background_start_reuse_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_project(root)
            info = start_background(root)
            try:
                self.assertTrue(running(root))
                self.assertEqual(start_background(root)["url"], info["url"])  # reused, not a second server
                c = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                c.request("GET", "/api/state", headers={"X-VCMD-Token": info["url"].split("token=")[1]})
                self.assertEqual(c.getresponse().status, 200)
            finally:
                self.assertTrue(stop_background(root))
            import time
            for _ in range(30):
                if not running(root):
                    break
                time.sleep(0.1)
            self.assertIsNone(running(root))


if __name__ == "__main__":
    unittest.main()
