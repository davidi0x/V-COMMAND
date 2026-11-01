from pathlib import Path
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config, run_task
from vcommand.state import (start_task, complete_step, set_next_step, load_task, add_ledger_entry,
                            read_ledger, ledger_path, record_run_failure, build_frame, render_frame,
                            continuity_token)
from vcommand.cli import main


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)

    def test_task_checkpoint_roundtrip(self):
        start_task(self.root, "Add password reset")
        set_next_step(self.root, "Invalidate sessions")
        complete_step(self.root, "Validate reset token")
        task = load_task(self.root)
        self.assertEqual(task["goal"], "Add password reset")
        self.assertEqual([s["step"] for s in task["completed_steps"]], ["Validate reset token"])
        self.assertEqual(task["next_step"], "Invalidate sessions")

    def test_completing_next_step_clears_it(self):
        start_task(self.root, "goal")
        set_next_step(self.root, "step one")
        complete_step(self.root, "step one")
        self.assertIsNone(load_task(self.root)["next_step"])

    def test_task_requires_init(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(FileNotFoundError):
                start_task(Path(other), "goal")

    def test_ledger_default_constraint_and_tolerates_torn_line(self):
        add_ledger_entry(self.root, tried="jwt.destroy() in controller", failure="TS2339")
        with ledger_path(self.root).open("a", encoding="utf-8") as f:
            f.write('{"broken": ')
        entries = read_ledger(self.root)
        self.assertEqual(len(entries), 1)
        self.assertIn("jwt.destroy()", entries[0]["constraint"])

    def test_failed_verification_recorded_without_output(self):
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", "raise SystemExit(3)"]]
        save_config(self.root, cfg)
        run = run_task(self.root, [sys.executable, "-c", "print('SECRET_OUTPUT_X')"], agent="model-a")
        entry = record_run_failure(self.root, run, agent="model-a", note="tried approach A")
        self.assertEqual(entry["tried"], "tried approach A")
        self.assertIn("exited 3", entry["failure"])
        self.assertEqual(entry["run_id"], run["id"])
        self.assertNotIn("SECRET_OUTPUT_X", ledger_path(self.root).read_text(encoding="utf-8"))

    def test_successful_run_not_recorded(self):
        run = run_task(self.root, [sys.executable, "-c", "pass"])
        self.assertIsNone(record_run_failure(self.root, run, agent=None, note=None))
        self.assertEqual(read_ledger(self.root), [])

    def test_frame_contains_handoff_state(self):
        cfg = load_config(self.root)
        cfg["checks"] = [["npm", "test"]]
        save_config(self.root, cfg)
        start_task(self.root, "Fix login")
        complete_step(self.root, "Reproduced bug")
        add_ledger_entry(self.root, tried="change middleware", failure="session test race",
                         constraint="Do not touch middleware order", agent="model-a")
        frame = build_frame(self.root)
        self.assertEqual(frame["task"]["goal"], "Fix login")
        self.assertEqual(frame["acceptance_gates"], ["npm test"])
        self.assertEqual(frame["negative_knowledge"][0]["constraint"], "Do not touch middleware order")
        text = render_frame(frame)
        for needle in ("Fix login", "Reproduced bug", "Do not touch middleware order", "`npm test`"):
            self.assertIn(needle, text)

    def test_continuity_token_stable_and_state_sensitive(self):
        start_task(self.root, "goal")
        a, b = build_frame(self.root), build_frame(self.root)
        self.assertEqual(a["continuity_token"], b["continuity_token"])
        self.assertEqual(continuity_token(a), a["continuity_token"])
        add_ledger_entry(self.root, tried="x", failure="y")
        self.assertNotEqual(build_frame(self.root)["continuity_token"], a["continuity_token"])


class StateCLITests(unittest.TestCase):
    def test_cli_handoff_flow(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)  # registered first, runs last: after chdir back (Windows)
        temp = temp_dir.name
        cwd = os.getcwd()
        os.chdir(temp)
        self.addCleanup(os.chdir, cwd)
        quiet = contextlib.redirect_stdout(io.StringIO())
        with quiet:
            self.assertEqual(main(["init"]), 0)
            self.assertEqual(main(["check", "add", "--", sys.executable, "-c", "raise SystemExit(1)"]), 0)
            self.assertEqual(main(["task", "start", "Ship feature"]), 0)
            self.assertEqual(main(["run", "--agent", "model-a", "--note", "approach A", "--",
                                   sys.executable, "-c", "pass"]), 1)
            self.assertEqual(main(["frame", "--json", "--out", "frame.json"]), 0)
        frame = json.loads(Path(temp, "frame.json").read_text(encoding="utf-8"))
        self.assertEqual(frame["task"]["goal"], "Ship feature")
        self.assertEqual(frame["negative_knowledge"][0]["tried"], "approach A")
        self.assertEqual(frame["negative_knowledge"][0]["agent"], "model-a")
        self.assertEqual(frame["last_run"]["status"], "failed_verification")


if __name__ == "__main__":
    unittest.main()
