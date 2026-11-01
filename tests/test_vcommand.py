from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config, run_task, read_evidence, git_status
from vcommand.cli import main


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)

    def test_init_does_not_overwrite_settings(self):
        cfg = load_config(self.root)
        cfg["mode"] = "offline"
        save_config(self.root, cfg)
        self.assertFalse(init_project(self.root))
        self.assertEqual(load_config(self.root)["mode"], "offline")

    def test_without_checks_is_unverified(self):
        run = run_task(self.root, [sys.executable, "-c", "print('hello')"])
        self.assertEqual(run["status"], "unverified")
        self.assertIsNone(run["cost"]["amount"])
        self.assertEqual(read_evidence(self.root, run["id"])["id"], run["id"])

    def test_checks_pass(self):
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", "assert True"]]
        save_config(self.root, cfg)
        run = run_task(self.root, [sys.executable, "-c", "print('hello')"])
        self.assertEqual(run["status"], "verified_by_configured_checks")
        self.assertEqual(len(run["checks"]), 1)

    def test_checks_fail(self):
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", "raise AssertionError('failed')"]]
        save_config(self.root, cfg)
        run = run_task(self.root, [sys.executable, "-c", "pass"])
        self.assertEqual(run["status"], "failed_verification")

    def test_command_fail_skips_checks(self):
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", "assert True"]]
        save_config(self.root, cfg)
        run = run_task(self.root, [sys.executable, "-c", "raise SystemExit(5)"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["checks"], [])

    def test_missing_command_fails(self):
        with self.assertRaises(ValueError):
            run_task(self.root, [])

    def test_no_secrets_in_raw_output(self):
        # Command output streams to user's console and is not captured in report.
        run = run_task(self.root, [sys.executable, "-c", "print(''.join(['SECRET','_EXAMPLE','_NOT_TO_PERSIST']))"])
        data = json.dumps(run)
        self.assertNotIn("SECRET_EXAMPLE_NOT_TO_PERSIST", data)

    def test_argv_with_spaces_not_shell_interpreted(self):
        run = run_task(self.root, [sys.executable, "-c", "print('safe')", "literal;not-shell"])
        self.assertEqual(run["action"]["exit_code"], 0)


class CLITests(unittest.TestCase):
    def test_demo_story_fail_then_verified(self):
        from vcommand.demo import run_demo
        out = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_demo(fast=True, out=out), 0)
        text = out.getvalue()
        self.assertLess(text.index("FAIL -> status: failed_verification"),
                        text.index("PASS -> status: verified_by_configured_checks"))

    def test_demo_real_checks(self):
        self.assertEqual(main(["demo", "--fast"]), 0)


if __name__ == "__main__":
    unittest.main()
