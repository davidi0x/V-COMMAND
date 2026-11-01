from datetime import datetime
from pathlib import Path
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config
from vcommand.queue import add_task, answer, load_queue, parse_until, render_report, run_queue, ask

# Reads the goal from the frame; asks a question for ASK tasks (until a decision arrives),
# otherwise creates the file named after "create".
WORKER = r"""
import sys, re, pathlib
p = sys.argv[1]
goal = p.split('## Goal\n', 1)[1].split('\n', 1)[0]
if 'ASK' in goal and 'Developer decision' not in goal:
    pathlib.Path('VCOMMAND_QUESTION.md').write_text('Which color?\n- red\n- blue\n')
else:
    m = re.search(r'create (\S+)', goal)
    if m:
        pathlib.Path(m.group(1)).write_text('ok')
"""


def exists_gate(name):
    return [sys.executable, "-c", f"import pathlib, sys; sys.exit(0 if pathlib.Path('{name}').exists() else 1)"]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(shutil.which("git"), "git required")
class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "user.email", "test@example.com")
        (self.root / "README").write_text("x\n")
        # regression: an existing, gitignored .vcommand/ broke `git add` with pathspec excludes
        (self.root / ".gitignore").write_text(".vcommand/\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "init")
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["agents"] = {"worker": [sys.executable, "-c", WORKER, "{prompt}"]}
        save_config(self.root, cfg)

    def run_q(self, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            out = io.StringIO()
            code = run_queue(self.root, ["worker"], out=out, **kw)
        return code, out.getvalue()

    def status(self):
        return {t["goal"].split(" — ")[0]: t["status"] for t in load_queue(self.root)["tasks"]}

    def test_overnight_queue(self):
        a = add_task(self.root, "create a.txt", gates=[exists_gate("a.txt")])
        add_task(self.root, "create b.txt", gates=[exists_gate("b.txt")], after=[a["id"]])
        asked = add_task(self.root, "ASK then create c.txt", gates=[exists_gate("c.txt")])
        add_task(self.root, "create d.txt", gates=[exists_gate("d.txt")], after=[asked["id"]])
        add_task(self.root, "create e.txt", gates=[exists_gate("never.txt")])
        code, out = self.run_q()
        self.assertEqual(code, 0)
        self.assertEqual(self.status(), {"create a.txt": "done", "create b.txt": "done",
                                         "ASK then create c.txt": "frozen", "create d.txt": "blocked",
                                         "create e.txt": "failed"})
        log = git(self.root, "log", "--format=%s")
        self.assertIn("vcmd queue: create a.txt", log)
        self.assertIn("vcmd queue: create b.txt", log)
        self.assertEqual(git(self.root, "status", "--porcelain", "--", ".", ":(exclude).vcommand"), "")
        self.assertFalse((self.root / "VCOMMAND_QUESTION.md").exists())
        self.assertFalse((self.root / "e.txt").exists())  # failed attempts are discarded
        report = render_report(load_queue(self.root))
        self.assertIn("Which color?", report)
        self.assertIn("A) red", report)
        self.assertIn("vcmd queue answer", report)

        answer(self.root, asked["id"], "blue")
        data = load_queue(self.root)
        for t in data["tasks"]:
            if t["status"] == "blocked":
                t["status"] = "pending"  # developer re-queues the dependent task
        from vcommand.queue import _save
        _save(self.root, data)
        code, _ = self.run_q()
        self.assertEqual(self.status()["ASK then create c.txt"], "done")
        self.assertEqual(self.status()["create d.txt"], "done")
        self.assertTrue((self.root / "c.txt").exists())

    def test_max_tasks_and_dirty_tree(self):
        add_task(self.root, "create a.txt", gates=[exists_gate("a.txt")])
        add_task(self.root, "create b.txt", gates=[exists_gate("b.txt")])
        _, out = self.run_q(max_tasks=1)
        self.assertIn("--max-tasks 1 reached", out)
        (self.root / "README").write_text("dirty\n")
        from vcommand.isolation import IsolationError
        with self.assertRaises(IsolationError):
            self.run_q()

    def test_ask_and_answer_validation(self):
        t = add_task(self.root, "goal")
        with self.assertRaises(ValueError):
            answer(self.root, t["id"], "x")
        ask(self.root, t["id"], "Q?", ["A", "B"])
        self.assertEqual(load_queue(self.root)["tasks"][0]["status"], "frozen")
        with self.assertRaises(ValueError):
            add_task(self.root, "x", after=["q-missing"])

    def test_parse_until(self):
        now = datetime(2026, 11, 1, 23, 0)
        self.assertEqual(parse_until("06:30", now), datetime(2026, 11, 2, 6, 30))
        self.assertEqual(parse_until("23:30", now), datetime(2026, 11, 1, 23, 30))
        with self.assertRaises(ValueError):
            parse_until("soon", now)


if __name__ == "__main__":
    unittest.main()
