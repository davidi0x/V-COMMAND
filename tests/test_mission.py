from pathlib import Path
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from vcommand.core import init_project, load_config, save_config, list_evidence
from vcommand import mission as mi
from vcommand.cli import main

GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('c.txt').exists() else 1)"]
PLAN = {"brief": {"scope": "text files only", "constraints": ["no deps"], "done": "a.txt b.txt c.txt exist"},
        "questions": ["Which encoding?"], "assumptions": ["UTF-8"],
        "steps": [{"title": "create a.txt", "difficulty": "easy", "detail": "write a"},
                  {"title": "create b.txt", "difficulty": "hard", "detail": "write b"},
                  {"title": "create c.txt", "difficulty": "medium", "detail": "write c"}]}


def stream(body: str, cost: float | None = 0.01) -> dict:
    code = ("import json, sys, pathlib\n"
            "prompt = sys.argv[1]\n"
            "def emit(e): print(json.dumps(e), flush=True)\n"
            "def done(t):\n"
            f"    r = {{'type': 'result', 'subtype': 'success', 'result': t}}\n"
            + ("" if cost is None else
               f"    r.update(total_cost_usd={cost!r}, usage={{'input_tokens': 100, 'output_tokens': 50}})\n") +
            "    emit(r)\n" + body)
    return {"argv": [sys.executable, "-c", code, "{prompt}"], "parser": "claude-stream"}


class MissionBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for cmd in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"]):
            subprocess.run(["git", *cmd], cwd=self.root, check=True, capture_output=True)
        (self.root / ".gitignore").write_text(".vcommand/\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.root, check=True, capture_output=True)
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [[sys.executable, "-c",
                          "import pathlib, sys; w = open('.vcommand/want').read().split(); "
                          "sys.exit(0 if w and all(pathlib.Path(f).exists() for f in w) else 1)"]]
        cfg["agents"] = {
            "planner": stream("emit({'type': 'system', 'session_id': 's'})\ndone(" + repr(json.dumps(PLAN)) + ")"),
            "alpha": stream("import re\nm = re.search(r'create (\\w\\.txt)', prompt)\n"
                            "pathlib.Path(m.group(1)).write_text('a'); pathlib.Path('.vcommand/want').write_text(\n"
                            "  ' '.join(sorted(p.name for p in pathlib.Path('.').glob('?.txt'))))\ndone('ok')", 0.02),
            "beta": stream("import re\nm = re.search(r'create (\\w\\.txt)', prompt)\n"
                           "pathlib.Path(m.group(1)).write_text('b'); pathlib.Path('.vcommand/want').write_text(\n"
                           "  ' '.join(sorted(p.name for p in pathlib.Path('.').glob('?.txt'))))\ndone('ok')", 0.05),
            "nocost": stream("done('x')", None)}
        save_config(self.root, cfg)
        (self.root / ".vcommand" / "want").write_text("")
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        p = mock.patch.dict(os.environ, {"VCOMMAND_NO_SECRETS": "1", "VCOMMAND_NO_NOTIFY": "1"})
        p.start()
        self.addCleanup(p.stop)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(argv))
        return code, out.getvalue()


class PlanTests(unittest.TestCase):
    def test_parse_plan_tolerates_fences_and_garbage(self):
        text = "Here you go:\n```json\n" + json.dumps(PLAN) + "\n```\nHope it helps."
        p = mi.parse_plan(text)
        self.assertEqual([s["difficulty"] for s in p["steps"]], ["easy", "hard", "medium"])
        self.assertEqual(p["questions"], ["Which encoding?"])
        self.assertIsNone(mi.parse_plan("no json here"))
        self.assertIsNone(mi.parse_plan("{broken"))
        weird = mi.parse_plan(json.dumps({"steps": [{"title": "x", "difficulty": "impossible"}, {"nope": 1}]}))
        self.assertEqual(weird["steps"], [{"title": "x", "difficulty": "medium", "detail": ""}])

    def test_allocation_follows_shares_and_pins(self):
        steps = [{"n": i, "difficulty": d} for i, d in enumerate(["hard", "easy", "medium", "easy", "hard", "medium"], 1)]
        a = mi.allocate(steps, {"x": 50, "y": 50})
        units = {"x": 0, "y": 0}
        for s in steps:
            units[a[s["n"]]] += mi.UNITS[s["difficulty"]]
        self.assertEqual(units, {"x": 6, "y": 6})
        only = mi.allocate(steps, {"x": 100, "y": 0})
        self.assertEqual(set(only.values()), {"x"})
        pinned = mi.allocate(steps, {"x": 50, "y": 50}, {"1": "y"})
        self.assertEqual(pinned[1], "y")
        with self.assertRaises(ValueError):
            mi.allocate(steps, {"x": 0})
        skew = mi.allocate(steps, {"x": 80, "y": 20})
        share_x = sum(mi.UNITS[s["difficulty"]] for s in steps if skew[s["n"]] == "x") / 12
        self.assertGreater(share_x, 0.6)


class MissionFlowTests(MissionBase):
    def test_enhance_edit_approve_run_report(self):
        m = mi.new_mission(self.root, "Make three files", agents=["alpha", "beta"], enhancer="planner", out=io.StringIO())
        self.assertEqual(len(m["steps"]), 3)
        self.assertEqual(m["enhancer"], "planner")
        v = mi.view(self.root)
        self.assertTrue(any("no cost data" in w for w in v["warnings"]))  # nothing measured yet: unknown, not $0
        self.assertTrue(any("unanswered" in w for w in v["warnings"]))
        self.assertIsNone(v["total"]["usd"])
        with self.assertRaises(ValueError):
            mi.approve(self.root)  # open question
        mi.answer_question(self.root, 1, "UTF-8, please")
        mi.set_shares(self.root, {"alpha": 70, "beta": 30})
        mi.set_budget(self.root, 5.0)
        approved = mi.approve(self.root)
        self.assertEqual(approved["status"], "approved")
        task = json.loads((self.root / ".vcommand" / "task.json").read_text())
        self.assertEqual(task["brief"]["scope"], "text files only")
        self.assertIn("Decision on 'Which encoding?': UTF-8, please", task["brief"]["constraints"])
        with self.assertRaises(ValueError):  # editing needs a fresh approval, run needs approval
            mi.set_budget(self.root, 1.0)
            mi.run_mission(self.root, out=io.StringIO())
        mi.approve(self.root)
        out = io.StringIO()
        code = mi.run_mission(self.root, attempts=1, out=out)
        self.assertEqual(code, 0, out.getvalue())
        final = mi.load_mission(self.root)
        self.assertEqual(final["status"], "done")
        self.assertEqual([s["status"] for s in final["steps"]], ["done"] * 3)
        self.assertTrue(all((self.root / f).exists() for f in ("a.txt", "b.txt", "c.txt")))
        usd = sum(s["actual"]["usd"] for s in final["steps"])
        self.assertAlmostEqual(usd, sum(r["cost"]["amount"] for r in list_evidence(self.root)
                                        if r.get("agent") in {"alpha", "beta"}), places=6)
        self.assertTrue((self.root / ".vcommand" / "mission_report.md").exists())
        self.assertIn("1. **Goal:** Make three files", (self.root / ".vcommand" / "handoff.md").read_text())
        # the run built history: the next estimate is a range from measured costs, with tokens
        mi.discard(self.root)
        mi.new_mission(self.root, "Again", agents=["alpha", "beta"], enhancer="planner", out=io.StringIO())
        v = mi.view(self.root)
        self.assertIsNotNone(v["total"]["usd"])
        self.assertIsNotNone(v["total"]["tokens"])
        lo, mid, hi = v["total"]["usd"]
        self.assertTrue(0 < lo <= mid <= hi)
        self.assertTrue(all(s["estimate"]["basis"].startswith("history") for s in v["steps"]))
        self.assertIn("too few", v["steps"][0]["estimate"]["basis"])  # 1-3 runs: said out loud

    def test_no_data_and_assumption_are_labelled(self):
        mi.new_mission(self.root, "x", agents=["nocost"], enhancer=None)
        est = mi.view(self.root)["steps"][0]["estimate"]
        self.assertEqual((est["usd"], est["basis"]), (None, "no data"))
        cfg = load_config(self.root)
        cfg["mission"] = {"assume": {"nocost": {"usd_per_step": 0.5}}}
        save_config(self.root, cfg)
        est = mi.view(self.root)["steps"][0]["estimate"]
        self.assertEqual(est["usd"], [0.5, 0.5, 0.5])
        self.assertIn("your assumption", est["basis"])

    def test_budget_is_a_hard_stop(self):
        mi.new_mission(self.root, "Make three files", agents=["beta"], enhancer="planner", out=io.StringIO())
        mi.answer_question(self.root, 1, "UTF-8")
        mi.set_budget(self.root, 0.06)  # beta costs 0.05 per attempt: two steps fit, the third must not start
        mi.approve(self.root)
        out = io.StringIO()
        code = mi.run_mission(self.root, attempts=1, out=out)
        self.assertEqual(code, 1)
        final = mi.load_mission(self.root)
        self.assertEqual(final["status"], "stopped")
        self.assertEqual(final["stop_reason"], "budget")
        self.assertEqual([s["status"] for s in final["steps"]], ["done", "done", "pending"])

    def test_failed_step_stops_and_resume_continues(self):
        cfg = load_config(self.root)
        cfg["agents"]["flaky"] = stream("done('did nothing')", 0.01)
        save_config(self.root, cfg)
        mi.new_mission(self.root, "Make three files", agents=["flaky"], enhancer="planner", out=io.StringIO())
        mi.approve(self.root, skip_questions=True)
        out = io.StringIO()
        self.assertEqual(mi.run_mission(self.root, attempts=1, out=out), 1)
        m = mi.load_mission(self.root)
        self.assertEqual((m["status"], m["steps"][0]["status"], m["steps"][1]["status"]), ("stopped", "failed", "pending"))
        self.assertIn("did not pass the gates", m["stop_reason"])
        self.assertIn("Fix the cause", (self.root / ".vcommand" / "handoff.md").read_text())

    def test_per_agent_cap_hands_work_over(self):
        mi.new_mission(self.root, "Make three files", agents=["alpha", "beta"], enhancer="planner", out=io.StringIO())
        mi.set_shares(self.root, {"alpha": 100, "beta": 0})
        mi.set_shares(self.root, {"alpha": 90, "beta": 10})
        mi.pin_step(self.root, 1, "alpha")
        mi.pin_step(self.root, 2, "alpha")
        mi.pin_step(self.root, 3, "alpha")
        mi.set_budget(self.root, 0.03, agent="alpha")  # alpha: 0.02 per attempt; cap reached after two steps
        mi.approve(self.root, skip_questions=True)
        mi.run_mission(self.root, attempts=1, out=io.StringIO())
        agents = [s["actual"]["agents"] for s in mi.load_mission(self.root)["steps"]]
        self.assertEqual(agents, [["alpha"], ["alpha"], ["beta"]])

    def test_enhancer_failure_falls_back_to_single_step(self):
        cfg = load_config(self.root)
        cfg["agents"]["mute"] = stream("done('I cannot do that')", 0.01)
        save_config(self.root, cfg)
        m = mi.new_mission(self.root, "Do the thing", agents=["alpha"], enhancer="mute", out=io.StringIO())
        self.assertEqual([s["title"] for s in m["steps"]], ["Do the thing"])
        self.assertIn("no usable plan twice", m["enhancer_note"])
        self.assertIsNone(m["enhancer"])

    def test_enhancer_gets_one_retry(self):
        cfg = load_config(self.root)
        marker = self.root / "tried"
        body = ("import pathlib\nm = pathlib.Path(" + repr(str(marker)) + ")\n"
                "if 'previous reply was not' in prompt: done(" + repr(json.dumps(PLAN)) + ")\n"
                "else: done('Sure! Here is my plan in prose.')")
        cfg["agents"]["chatty"] = stream(body, 0.01)
        save_config(self.root, cfg)
        m = mi.new_mission(self.root, "Make three files", agents=["alpha"], enhancer="chatty", out=io.StringIO())
        self.assertEqual(len(m["steps"]), 3)
        self.assertEqual(m["enhancer"], "chatty")

    def test_stale_task_of_a_finished_mission_is_cleared(self):
        mi.new_mission(self.root, "Make three files", agents=["alpha"], enhancer="planner", out=io.StringIO())
        mi.approve(self.root, skip_questions=True)
        self.assertTrue((self.root / ".vcommand" / "task.json").exists())
        mi.discard(self.root)
        self.assertFalse((self.root / ".vcommand" / "task.json").exists())
        mi.new_mission(self.root, "Again", agents=["alpha"], enhancer=None)
        mi.approve(self.root)
        mi.new_mission(self.root, "Next", agents=["alpha"], enhancer=None)  # new draft over an approved one
        self.assertFalse((self.root / ".vcommand" / "task.json").exists())

    def test_enhancer_is_read_only_and_never_counts_as_history(self):
        mi.new_mission(self.root, "Make three files", agents=["alpha"], enhancer="planner", out=io.StringIO())
        run = list_evidence(self.root)[-1]
        self.assertTrue(run["text_role"])
        self.assertEqual(run["checks"], [])
        self.assertEqual(mi.all_history(self.root), [])  # "planner:enhance" is not an agent's work history

    def test_cli_flow(self):
        code, text = self.cli("mission", "new", "Make three files", "--agents", "alpha", "beta", "--enhance", "planner")
        self.assertEqual(code, 0)
        self.assertIn("Question 1: Which encoding?", text)
        self.assertIn("create b.txt", text)
        self.assertEqual(self.cli("mission", "share", "alpha=70", "beta=30")[0], 0)
        self.assertEqual(self.cli("mission", "share", "alpha=x")[0], 2)
        self.assertEqual(self.cli("mission", "share", "gamma=10")[0], 2)
        self.assertEqual(self.cli("mission", "approve")[0], 2)  # unanswered question
        self.assertEqual(self.cli("mission", "answer", "1", "UTF-8")[0], 0)
        self.assertEqual(self.cli("mission", "budget", "3")[0], 0)
        self.assertEqual(self.cli("mission", "pin", "2", "beta")[0], 0)
        self.assertEqual(self.cli("mission", "approve")[0], 0)
        code, text = self.cli("mission", "run", "--attempts", "1")
        self.assertEqual(code, 0, text)
        self.assertIn("Total: 3/3 steps verified", self.cli("mission", "report")[1])
        self.assertIn("[done]", self.cli("mission")[1])


if __name__ == "__main__":
    unittest.main()
