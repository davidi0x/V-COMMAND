from pathlib import Path
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config, list_evidence
from vcommand.state import start_task, read_ledger
from vcommand.adapters import (run_agents, run_claude_hook, install_claude_hooks, uninstall_claude_hooks,
                               agent_templates, CLAUDE_HOOK_COMMANDS, run_hook, install_hooks,
                               uninstall_hooks, DEFAULT_AGENTS)
from vcommand.cli import main

# "bad" ignores the task. "good" fixes it only if the prompt carries bad's failure from the ledger.
BAD = "import sys; sys.exit(0)"
GOOD = ("import sys, pathlib; p = sys.argv[1]; "
        "sys.exit(7) if 'bad attempt 1' not in p or 'Ship it' not in p else pathlib.Path('fixed.txt').write_text('ok')")
# Does the work but exits non-zero (e.g. an agent hitting its turn limit).
QUITTER = "import pathlib, sys; pathlib.Path('fixed.txt').write_text('ok'); sys.exit(3)"
GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


class AgentWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        cfg["agents"] = {"bad": [sys.executable, "-c", BAD, "{prompt}"],
                         "quitter": [sys.executable, "-c", QUITTER, "{prompt}"],
                         "good": [sys.executable, "-c", GOOD, "{prompt}"]}
        save_config(self.root, cfg)
        start_task(self.root, "Ship it")
        cwd = os.getcwd()
        os.chdir(self.root)  # agents and checks run in root anyway; keeps relative paths sane
        self.addCleanup(os.chdir, cwd)

    def run_agents(self, *args, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_agents(self.root, list(args), out=io.StringIO(), **kw)

    def test_handoff_carries_negative_knowledge_to_next_agent(self):
        self.assertEqual(self.run_agents("bad", "good"), 0)
        self.assertTrue((self.root / "fixed.txt").exists())
        ledger = read_ledger(self.root)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["agent"], "bad")
        runs = list_evidence(self.root)
        self.assertEqual([r["status"] for r in runs], ["failed_verification", "verified_by_configured_checks"])

    def test_prompt_not_stored_in_evidence(self):
        self.run_agents("bad", "good")
        for run in list_evidence(self.root):
            self.assertNotIn("context frame v1", json.dumps(run))  # rendered frame header
            self.assertTrue(run["action"]["argv"][-1].startswith("<context frame sha256:"))

    def test_gates_judge_not_agent_exit_code(self):
        self.assertEqual(self.run_agents("quitter"), 0)
        run = list_evidence(self.root)[-1]
        self.assertEqual(run["action"]["exit_code"], 3)
        self.assertEqual(run["status"], "verified_by_configured_checks")

    def test_missing_agent_binary_fails_without_checks(self):
        cfg = load_config(self.root)
        cfg["agents"]["ghost"] = ["vcmd-no-such-agent-binary", "{prompt}"]
        save_config(self.root, cfg)
        (self.root / "fixed.txt").write_text("ok")  # gates would pass, but the agent never ran
        self.assertEqual(self.run_agents("ghost"), 1)
        run = list_evidence(self.root)[-1]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["checks"], [])

    def test_gives_up_after_attempts(self):
        self.assertEqual(self.run_agents("bad", attempts=2), 1)
        self.assertEqual(len(read_ledger(self.root)), 2)

    def test_unknown_agent_rejected(self):
        with self.assertRaises(ValueError):
            self.run_agents("nope")

    def test_template_requires_prompt_placeholder(self):
        with self.assertRaises(ValueError):
            agent_templates({"agents": {"x": ["tool"]}})
        self.assertIn("codex", agent_templates({}))


class ClaudeHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)
        start_task(self.root, "Fix login")

    def hook(self, event, **payload):
        payload.setdefault("cwd", str(self.root))
        out, err = io.StringIO(), io.StringIO()
        code = run_claude_hook(event, io.StringIO(json.dumps(payload)), out, err)
        self.assertEqual(code, 0)
        return out.getvalue()

    def set_gate(self, passing):
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c", f"raise SystemExit({0 if passing else 1})"]]
        cfg["hooks"] = {"claude_max_stop_blocks": 2}
        save_config(self.root, cfg)

    def test_session_start_injects_frame(self):
        text = self.hook("session-start", source="compact")
        self.assertIn("Session compact", text)
        self.assertIn("Fix login", text)

    def test_hooks_silent_when_not_initialized(self):
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(self.hook("session-start", cwd=other), "")
            self.assertEqual(self.hook("stop", cwd=other), "")

    def test_stop_blocks_on_failed_gate_then_gives_up(self):
        self.set_gate(False)
        for _ in range(2):
            reply = json.loads(self.hook("stop", session_id="s1"))
            self.assertEqual(reply["decision"], "block")
            self.assertIn("exited 1", reply["reason"])
        final = json.loads(self.hook("stop", session_id="s1"))
        self.assertNotIn("decision", final)
        self.assertIn("Not verified", final["systemMessage"])
        self.assertEqual(len(read_ledger(self.root)), 3)
        # counter was reset: a later stop in the same session blocks again
        self.assertEqual(json.loads(self.hook("stop", session_id="s1"))["decision"], "block")

    def test_stop_passes_silently_and_records_evidence(self):
        self.set_gate(True)
        self.assertEqual(self.hook("stop", session_id="s2"), "")
        run = list_evidence(self.root)[-1]
        self.assertEqual(run["status"], "verified_by_configured_checks")
        self.assertTrue(run["action"]["external"])

    def test_install_is_idempotent_and_preserves_existing(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        existing = {"permissions": {"allow": ["Bash(ls)"]},
                    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
        settings.write_text(json.dumps(existing))
        _, added = install_claude_hooks(self.root)
        self.assertEqual(sorted(added), sorted(CLAUDE_HOOK_COMMANDS))
        _, added_again = install_claude_hooks(self.root)
        self.assertEqual(added_again, [])
        data = json.loads(settings.read_text())
        self.assertEqual(data["permissions"], existing["permissions"])
        commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(commands, ["other", CLAUDE_HOOK_COMMANDS["Stop"]])
        _, removed = uninstall_claude_hooks(self.root)
        self.assertEqual(sorted(removed), sorted(CLAUDE_HOOK_COMMANDS))
        self.assertEqual(json.loads(settings.read_text()), existing)

    def test_codex_hooks_file_and_stop_protocol(self):
        path, added = install_hooks(self.root, "codex")
        self.assertEqual(path, self.root / ".codex" / "hooks.json")
        data = json.loads(path.read_text())
        self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "vcmd hook codex stop")
        self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], "vcmd hook codex session-start")
        self.set_gate(False)
        out = io.StringIO()
        run_hook("codex", "stop", io.StringIO(json.dumps({"cwd": str(self.root), "session_id": "c1",
                                                          "stop_hook_active": False})), out, io.StringIO())
        self.assertEqual(json.loads(out.getvalue())["decision"], "block")
        self.assertEqual(read_ledger(self.root)[-1]["agent"], "codex")
        _, removed = uninstall_hooks(self.root, "codex")
        self.assertEqual(sorted(removed), ["PostToolUse", "PreCompact", "PreToolUse", "SessionStart", "Stop",
                                           "UserPromptSubmit"])

    def test_codex_template_uses_supported_flags(self):
        # `--full-auto` was removed from `codex exec` (verified against codex-cli 0.166).
        argv = DEFAULT_AGENTS["codex"]["argv"]
        self.assertNotIn("--full-auto", argv)
        self.assertEqual(argv[:5], ["codex", "exec", "--json", "--sandbox", "workspace-write"])

    def test_cli_hook_fails_open_on_bad_input(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        stdin = sys.stdin
        sys.stdin = io.StringIO("not json")
        self.addCleanup(setattr, sys, "stdin", stdin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["hook", "claude", "stop"]), 0)


if __name__ == "__main__":
    unittest.main()
