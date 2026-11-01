from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest

from vcommand.core import init_project, load_config, save_config, list_evidence, execute
from vcommand.parsers import make_parser
from vcommand.state import start_task, add_ledger_entry, read_ledger
from vcommand.adapters import run_agents

# Emits Claude Code stream-json: a text block, an Edit containing a banned pattern, then keeps
# "thinking" for 30 s. The guard must kill it right after the edit event.
GUARDED = r"""
import json, sys, time
def emit(e): print(json.dumps(e), flush=True)
emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixing the controller."}]}})
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit",
      "input": {"file_path": "src/auth.ts", "old_string": "x", "new_string": "await jwt.destroy(token)"}}]}})
time.sleep(30)
emit({"type": "result", "total_cost_usd": 0.5})
"""
CLEAN = r"""
import json, pathlib
pathlib.Path('fixed.txt').write_text('ok')
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write",
      "input": {"file_path": "fixed.txt", "content": "store.invalidateAllForUser(id)"}}]}}))
print(json.dumps({"type": "result", "total_cost_usd": 0.0123}))
"""
GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


class ParserTests(unittest.TestCase):
    def test_codex_usage_and_estimate(self):
        events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 200,
                                                        "output_tokens": 300}}]
        echo = io.StringIO()
        p = make_parser("codex-jsonl", echo, {"model": "gpt-x", "prices": {"gpt-x": {
            "input_per_mtok": 1.0, "cached_input_per_mtok": 0.1, "output_per_mtok": 10.0}}})
        for e in events:
            p.feed(json.dumps(e) + "\n")
        cost = p.finish()
        self.assertEqual(echo.getvalue(), "done\n")
        self.assertEqual(cost["usage"], {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 300})
        self.assertAlmostEqual(cost["amount"], (800 * 1.0 + 200 * 0.1 + 300 * 10.0) / 1e6)
        self.assertTrue(cost["estimated"])

    def test_codex_without_price_keeps_usd_unknown(self):
        p = make_parser("codex-jsonl", io.StringIO(), {})
        p.feed(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}}))
        cost = p.finish()
        self.assertIsNone(cost["amount"])
        self.assertEqual(cost["usage"]["input_tokens"], 5)

    def test_unknown_parser_rejected(self):
        with self.assertRaises(ValueError):
            make_parser("guess", io.StringIO())

    def test_execute_cancel_stops_process(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        start = time.monotonic()
        result = execute([sys.executable, "-c", "import time; time.sleep(30)"], Path.cwd(), 60, cancel=cancel)
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(result["cancelled"])
        self.assertFalse(result["passed"])

    def test_execute_timeout_with_parser(self):
        p = make_parser("claude-json", io.StringIO())
        result = execute([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"],
                         Path.cwd(), 1, parser=p)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], 124)


class StreamGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        cfg["agents"] = {"guarded": {"argv": [sys.executable, "-c", GUARDED, "{prompt}"], "parser": "claude-stream"},
                         "clean": {"argv": [sys.executable, "-c", CLEAN, "{prompt}"], "parser": "claude-stream"}}
        save_config(self.root, cfg)
        start_task(self.root, "Invalidate sessions on password reset")
        add_ledger_entry(self.root, tried="jwt.destroy() in the controller", failure="TS2339: jsonwebtoken is stateless",
                         pattern="jwt.destroy(")

    def agents(self, *names, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            code = run_agents(self.root, list(names), out=out, **kw)
        return code, out.getvalue()

    def test_guard_kills_agent_on_banned_pattern(self):
        start = time.monotonic()
        code, _ = self.agents("guarded", attempts=1)
        self.assertLess(time.monotonic() - start, 15, "agent was not killed early")
        self.assertEqual(code, 1)
        run = list_evidence(self.root)[-1]
        self.assertIn("banned pattern `jwt.destroy(`", run["action"]["killed"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["checks"], [])
        self.assertIn("stream guard", read_ledger(self.root)[-1]["failure"])

    def test_clean_stream_passes_and_reports_cost(self):
        code, _ = self.agents("clean", attempts=1)
        self.assertEqual(code, 0)
        run = list_evidence(self.root)[-1]
        self.assertEqual(run["cost"]["amount"], 0.0123)
        self.assertNotIn("killed", run["action"])

    def test_handoff_after_kill(self):
        code, _ = self.agents("guarded", "clean")
        self.assertEqual(code, 0)
        self.assertEqual([r["agent"] for r in list_evidence(self.root)], ["guarded", "clean"])


if __name__ == "__main__":
    unittest.main()
