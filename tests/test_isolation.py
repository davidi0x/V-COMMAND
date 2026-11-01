from pathlib import Path
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config, list_evidence
from vcommand.state import start_task, load_task, read_ledger
from vcommand.adapters import run_agents
from vcommand.isolation import IsolationError, Worktree, ensure_clean_repo

# Leaves junk behind and never fixes the task.
MESSY = "import pathlib; pathlib.Path('junk.txt').write_text('broken')"
# Fixes the task and records progress through V/COMMAND from inside the worktree (VCOMMAND_ROOT).
FIXER = ("import pathlib; pathlib.Path('fixed.txt').write_text('ok'); "
         "from vcommand.core import project_root; from vcommand.state import complete_step; "
         "complete_step(project_root(), 'created fixed.txt in worktree')")
GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(shutil.which("git"), "git required")
class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("node_modules/\n")
        (self.root / "app.txt").write_text("v1\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "init")
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        cfg["agents"] = {"messy": [sys.executable, "-c", MESSY, "{prompt}"],
                         "fixer": [sys.executable, "-c", FIXER, "{prompt}"]}
        save_config(self.root, cfg)
        start_task(self.root, "Create fixed.txt")

    def agents(self, *names, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_agents(self.root, list(names), out=io.StringIO(), isolate=True, **kw)

    def test_failed_attempt_discarded_verified_attempt_applied(self):
        self.assertEqual(self.agents("messy", "fixer"), 0)
        self.assertFalse((self.root / "junk.txt").exists(), "failed attempt leaked into working tree")
        self.assertEqual((self.root / "fixed.txt").read_text(), "ok")
        runs = list_evidence(self.root)
        self.assertEqual([r["status"] for r in runs], ["failed_verification", "verified_by_configured_checks"])
        self.assertTrue(all(r["isolated_worktree"] for r in runs))
        ledger = read_ledger(self.root)
        self.assertEqual(len(ledger), 1)
        self.assertIn("junk.txt", ledger[0]["tried"])
        # state written from inside the worktree landed in the main project
        self.assertEqual(load_task(self.root)["completed_steps"][0]["step"], "created fixed.txt in worktree")

    def test_no_worktrees_left_behind(self):
        self.agents("messy", attempts=1)
        out = subprocess.run(["git", "worktree", "list"], cwd=self.root, stdout=subprocess.PIPE, text=True).stdout
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_dirty_repo_refused(self):
        (self.root / "app.txt").write_text("local edit\n")
        with self.assertRaises(IsolationError):
            self.agents("fixer")

    def test_tool_state_does_not_count_as_dirty(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text("{}")
        ensure_clean_repo(self.root)  # .vcommand/ and .claude/ are untracked but allowed

    def test_linked_dependencies_not_in_patch(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "dep.js").write_text("x")
        head = ensure_clean_repo(self.root)
        with Worktree(self.root, head) as wt:
            (wt.path / "fixed.txt").write_text("ok")
            if not wt.warnings:  # symlinks may be unavailable on Windows runners
                self.assertTrue((wt.path / "node_modules" / "dep.js").exists())
            changed = wt.apply_to_root()
        self.assertEqual(changed, ["fixed.txt"])
        self.assertTrue((self.root / "node_modules" / "dep.js").exists())


if __name__ == "__main__":
    unittest.main()
