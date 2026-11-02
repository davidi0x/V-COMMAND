from pathlib import Path
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from vcommand.core import init_project, load_config, save_config, list_evidence, run_task
from vcommand.state import start_task, set_brief, build_frame, render_frame, set_next_step
from vcommand.adapters import run_agents, run_hook, install_hooks, STOPPED_FOR_HUMAN, build_prompt
from vcommand.parsers import make_parser
from vcommand import workflow as w
from vcommand.cli import main

GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


def stream_agent(body: str) -> dict:
    """A fake Claude Code in stream-json mode: `body` is Python that may call emit(event)."""
    code = ("import json, sys, pathlib\n"
            "def emit(e): print(json.dumps(e), flush=True)\n"
            "def text(t): emit({'type': 'result', 'subtype': 'success', 'result': t, 'total_cost_usd': 0.001})\n"
            "def bash(c): emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', "
            "'input': {'command': c}}]}})\n"
            "prompt = sys.argv[1]\n" + body)
    return {"argv": [sys.executable, "-c", code, "{prompt}"], "parser": "claude-stream"}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / ".gitignore").write_text(".vcommand/\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "init")
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        save_config(self.root, cfg)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)

    def set_agents(self, **agents):
        cfg = load_config(self.root)
        cfg["agents"] = agents
        save_config(self.root, cfg)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(argv))
        return code, out.getvalue()


class BriefAndLeaveBehindTests(Base):
    def test_brief_todos_decisions_and_approvals_reach_every_agent_prompt(self):
        start_task(self.root, "Ship login", w.normalize_brief("auth module only", ["no new deps"], "tests pass", None))
        set_brief(self.root, constraints=["keep API stable"])
        w.add_todo(self.root, "document the reset flow")
        w.add_decision(self.root, "Use JWT", why="existing clients", agent="planner")
        w.request_approval(self.root, "git push origin main", "publish", agent="claude")
        frame = build_frame(self.root)
        self.assertEqual(frame["brief"]["constraints"], ["no new deps", "keep API stable"])
        prompt = build_prompt(frame)
        for needle in ("Scope: auth module only", "Done condition: tests pass", "- keep API stable",
                       "- [ ] document the reset flow", "Use JWT — because existing clients",
                       "`git push origin main`", "Ask before risky actions"):
            self.assertIn(needle, prompt)
        self.assertIn("## Goal\nShip login", render_frame(frame))  # unchanged section for existing parsers

    def test_unset_brief_fields_are_explicit(self):
        start_task(self.root, "Ship")
        brief = build_frame(self.root)["brief"]
        self.assertEqual(brief["done"], "All acceptance gates pass.")
        self.assertIn("Not set", brief["scope"])

    def test_todo_cli(self):
        start_task(self.root, "Ship")
        self.assertEqual(self.cli("todo", "add", "first")[0], 0)
        self.cli("todo", "add", "second thing")
        self.assertEqual(self.cli("todo", "done", "second")[0], 0)
        self.assertEqual(w.open_todos(self.root), ["first"])
        self.assertEqual(self.cli("todo", "done", "zzz")[0], 2)

    def test_every_run_writes_five_line_handoff_and_patch(self):
        start_task(self.root, "Create fixed.txt")
        set_next_step(self.root, "write fixed.txt")
        item = run_task(self.root, [sys.executable, "-c", "open('fixed.txt','w').write('x')"], log=io.StringIO())
        text = (self.root / ".vcommand" / "handoff.md").read_text()
        for n, label in enumerate(["Goal", "Current state", "Files touched", "Open issues", "Next exact step"], 1):
            self.assertIn(f"{n}. **{label}:**", text)
        self.assertIn("verified_by_configured_checks", text)
        self.assertIn("`fixed.txt`", text)
        self.assertEqual(item["diff"]["untracked"], ["fixed.txt"])
        self.assertTrue((self.root / item["diff"]["path"]).exists())

    def test_failed_run_handoff_names_failing_gate(self):
        start_task(self.root, "Create fixed.txt")
        run_task(self.root, [sys.executable, "-c", "pass"], log=io.StringIO())
        h = w.build_handoff(self.root)
        self.assertTrue(any(i.startswith("gate failing") for i in h["open_issues"]))
        self.assertTrue(h["next_step"].startswith("Fix the cause of"))

    def test_text_role_skips_gates(self):
        item = run_task(self.root, [sys.executable, "-c", "pass"], log=io.StringIO(), run_checks=False)
        self.assertEqual(item["status"], "unverified")
        self.assertEqual(item["checks"], [])


class GuardrailTests(Base):
    def test_classification(self):
        cfg = load_config(self.root)
        risky = {"git push origin main": "publish", "npm publish": "publish", "vercel deploy --prod": "deploy",
                 "kubectl apply -f k8s/": "deploy", "terraform apply": "deploy",
                 'psql "$DB" -c "DELETE FROM users"': "db-write", "npx prisma migrate deploy": "db-write",
                 "python manage.py migrate": "db-write", "rm -rf src": "bulk-delete",
                 "npm test && rm -rf ~": "bulk-delete", "find . -name '*.tmp' -delete": "bulk-delete",
                 "git reset --hard HEAD~3": "bulk-delete"}
        for command, rule in risky.items():
            self.assertEqual(w.classify_command(cfg, command), rule, command)
        risky.update({"echo hi; git push": "publish", "cat x | xargs rm": "bulk-delete",
                      "FOO=1 npm publish": "publish", "bash -lc 'rm -rf src'": "bulk-delete"})
        for command, rule in risky.items():
            self.assertEqual(w.classify_command(cfg, command), rule, command)
        for command in ("git status", "rm -rf node_modules", "rm -rf dist build", "rm -f a.txt",
                        "npm test", "psql -c 'SELECT 1'", "git commit -m 'deploy docs'",
                        # found live: text that mentions a risky command is not that command
                        'vcmd todo add "Push pending approval: run git push origin HEAD:main"',
                        'vcmd decide "hold git push && rm -rf build/" --why "needs approval"',
                        'echo "run: rm -rf src" > notes.txt', 'git commit -m "x; git push"',
                        "npm test 2>&1 | tail -5", "sleep 1 &"):
            self.assertIsNone(w.classify_command(cfg, command), command)

    def test_config_can_add_allow_and_disable(self):
        cfg = load_config(self.root)
        cfg["guardrails"] = {"rules": [{"rule": "payments", "pattern": r"\bstripe\s+refunds\b"}],
                             "allow": [r"^git push origin feature/"]}
        self.assertEqual(w.classify_command(cfg, "stripe refunds create"), "payments")
        self.assertIsNone(w.classify_command(cfg, "git push origin feature/x"))
        self.assertEqual(w.classify_command(cfg, "git push origin main"), "publish")
        cfg["guardrails"] = {"enabled": False}
        self.assertIsNone(w.classify_command(cfg, "rm -rf /"))

    def test_approval_is_exact_and_expires(self):
        req = w.request_approval(self.root, "git  push origin main", "publish")
        self.assertEqual(w.request_approval(self.root, "git push origin main", "publish")["id"], req["id"])
        self.assertFalse(w.is_approved(self.root, "git push origin main"))
        w.decide_approval(self.root, req["id"], True)
        self.assertTrue(w.is_approved(self.root, "git push  origin main"))
        self.assertFalse(w.is_approved(self.root, "git push origin main --force"))
        self.assertFalse(w.is_approved(self.root, "git push origin main", now=time.time() + w.APPROVAL_TTL_S + 1))
        self.assertIn("Approved publish", w.read_decisions(self.root)[-1])
        with self.assertRaises(ValueError):
            w.decide_approval(self.root, req["id"], False)

    def hook(self, target, command, wrapped):
        env = {k: v for k, v in os.environ.items() if k != "VCOMMAND_WRAPPED"}
        if wrapped:
            env["VCOMMAND_WRAPPED"] = "1"
        payload = {"cwd": str(self.root), "tool_name": "Bash", "tool_input": {"command": command}}
        out = io.StringIO()
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            run_hook(target, "pre-tool", io.StringIO(json.dumps(payload)), out, io.StringIO())
        finally:
            os.environ.clear()
            os.environ.update(old)
        return json.loads(out.getvalue())["hookSpecificOutput"] if out.getvalue().strip() else None

    def test_pre_tool_hook(self):
        self.assertIsNone(self.hook("claude", "npm test", wrapped=False))
        ask = self.hook("claude", "vercel deploy --prod", wrapped=False)
        self.assertEqual(ask["permissionDecision"], "ask")  # Claude Code asks the developer itself
        self.assertEqual(w.pending_approvals(self.root), [])
        deny = self.hook("claude", "vercel deploy --prod", wrapped=True)
        self.assertEqual(deny["permissionDecision"], "deny")
        req = w.pending_approvals(self.root)[0]
        self.assertIn(f"vcmd approve {req['id']}", deny["permissionDecisionReason"])
        self.assertEqual(self.hook("codex", "vercel deploy --prod", wrapped=False)["permissionDecision"], "deny")
        w.decide_approval(self.root, req["id"], True)
        self.assertIsNone(self.hook("codex", "vercel deploy --prod", wrapped=True))

    def test_install_adds_bash_matcher_for_claude(self):
        path, _ = install_hooks(self.root, "claude")
        groups = json.loads(path.read_text())["hooks"]["PreToolUse"]
        self.assertEqual(groups[0]["matcher"], "Bash")
        self.assertEqual(groups[0]["hooks"][0]["command"], "vcmd hook claude pre-tool")

    def test_pre_compact_checkpoints(self):
        start_task(self.root, "Ship")
        run_hook("claude", "pre-compact", io.StringIO(json.dumps({"cwd": str(self.root)})), io.StringIO(), io.StringIO())
        self.assertIn("1. **Goal:** Ship", (self.root / ".vcommand" / "handoff.md").read_text())
        out = io.StringIO()
        env = os.environ.pop("VCOMMAND_WRAPPED", None)
        try:
            run_hook("claude", "session-start", io.StringIO(json.dumps({"cwd": str(self.root), "source": "compact"})),
                     out, io.StringIO())
        finally:
            if env is not None:
                os.environ["VCOMMAND_WRAPPED"] = env
        self.assertIn("Handoff from the previous session", out.getvalue())

    def test_stream_guard_kills_risky_bash_and_run_stops_for_human(self):
        start_task(self.root, "Ship")
        self.set_agents(pusher=stream_agent("bash('git push origin main')\nimport time; time.sleep(5)\n"
                                            "pathlib.Path('fixed.txt').write_text('x')\n"),
                        good=stream_agent("pathlib.Path('fixed.txt').write_text('x'); text('done')"))
        out = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            code = run_agents(self.root, ["pusher", "good"], out=out)
        self.assertEqual(code, STOPPED_FOR_HUMAN)  # not handed to `good`: the blocked step needs a human
        run = list_evidence(self.root)[-1]
        self.assertTrue(run["action"]["killed"].startswith("guardrail: publish"))
        self.assertEqual(run["guardrail"]["command"], "git push origin main")
        self.assertLess(run["action"]["duration_ms"], 4000)
        self.assertFalse((self.root / "fixed.txt").exists())
        self.assertIn("APPROVAL", out.getvalue())
        self.assertEqual(len(list_evidence(self.root)), 1)
        from vcommand.adapters import open_circuits
        self.assertEqual(open_circuits(self.root), {})  # our own kill is not a provider outage

    def test_codex_command_execution_is_guarded(self):
        ctx = {"guardrails": {"root": str(self.root), "cfg": load_config(self.root)}}
        p = make_parser("codex-jsonl", io.StringIO(), ctx)
        ev = {"type": "item.started", "item": {"type": "command_execution", "command": "bash -lc 'rm -rf src'"}}
        self.assertTrue(p.feed(json.dumps(ev)).startswith("guardrail: bulk-delete"))
        ok = {"type": "item.started", "item": {"type": "command_execution", "command": "npm test"}}
        self.assertIsNone(p.feed(json.dumps(ok)))

    def test_queue_task_freezes_and_approval_answers_it(self):
        from vcommand import queue as q
        self.set_agents(pusher=stream_agent("bash('npm publish')\nimport time; time.sleep(5)\n"))
        t = q.add_task(self.root, "publish it")
        with contextlib.redirect_stdout(io.StringIO()):
            q.run_queue(self.root, ["pusher"], out=io.StringIO())
        task = q.load_queue(self.root)["tasks"][0]
        self.assertEqual(task["status"], "frozen")
        self.assertIn("npm publish", task["question"])
        req = w.pending_approvals(self.root)[0]
        self.assertEqual(req["queue_task"], t["id"])
        self.assertEqual(self.cli("approve", req["id"])[0], 0)
        self.assertEqual(q.load_queue(self.root)["tasks"][0]["status"], "pending")


class LoopAndWakeTests(Base):
    PLANNER = stream_agent("text('1. create fixed.txt\\n2. stop')")
    BUILDER = stream_agent(
        "assert 'ROLE: BUILDER' in prompt and 'create fixed.txt' in prompt, 'plan missing'\n"
        "pathlib.Path('fixed.txt').write_text('v2' if 'REQUESTED THESE CHANGES' in prompt else 'v1')\n"
        "text('built')")
    REVIEWER = stream_agent(
        "assert '+v1' in prompt or '+v2' in prompt or 'fixed.txt' in prompt, 'diff missing'\n"
        "text('VERDICT: APPROVE' if 'v2' in pathlib.Path('fixed.txt').read_text() else "
        "'Content too old.\\nVERDICT: CHANGES\\n- write v2')")

    def test_plan_build_review_rounds(self):
        start_task(self.root, "Create fixed.txt")
        self.set_agents(planner=self.PLANNER, builder=self.BUILDER, reviewer=self.REVIEWER)
        out = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            code = w.run_loop(self.root, plan="planner", build=["builder"], review="reviewer", rounds=2, out=out)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual((self.root / "fixed.txt").read_text(), "v2")
        vc = self.root / ".vcommand"
        self.assertIn("1. create fixed.txt", (vc / "plan.md").read_text())
        self.assertIn("VERDICT: APPROVE", (vc / "review.md").read_text())
        decisions = w.read_decisions(self.root)
        self.assertTrue(any("Review round 1: CHANGES" in d for d in decisions))
        self.assertTrue(any("Review round 2: APPROVE" in d for d in decisions))
        agents = [r["agent"] for r in list_evidence(self.root)]
        self.assertEqual(agents, ["planner:plan", "builder", "reviewer:review", "builder", "reviewer:review"])
        handoff = (vc / "handoff.md").read_text()
        self.assertIn("1. **Goal:** Create fixed.txt", handoff)
        self.assertIn("verified_by_configured_checks", handoff)  # last gated run, not the reviewer's answer
        self.assertIn("Review round 2: APPROVE", handoff)

    def test_reviewer_without_approval_withholds_done(self):
        start_task(self.root, "Create fixed.txt")
        self.set_agents(builder=stream_agent("pathlib.Path('fixed.txt').write_text('v1'); text('ok')"),
                        reviewer=stream_agent("text('VERDICT: CHANGES\\n- more')"))
        with contextlib.redirect_stdout(io.StringIO()):
            code = w.run_loop(self.root, plan=None, build=["builder"], review="reviewer", rounds=1, out=io.StringIO())
        self.assertEqual(code, 1)

    def test_api_error_result_is_not_a_finished_task(self):
        from vcommand.adapters import provider_failure_reason
        p = make_parser("claude-stream", io.StringIO(), {})
        p.feed(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "API Error: overloaded"}))
        self.assertEqual(p.result_subtype, "api_error")
        item = {"action": {"exit_code": 1}, "agent_result": p.result_subtype, "git_status_before": [], "git_status_after": []}
        self.assertIsNotNone(provider_failure_reason(item))  # retried / failed over, not counted as a wrong answer
        ok = make_parser("claude-stream", io.StringIO(), {})
        ok.feed(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done"}))
        self.assertEqual(ok.result_subtype, "success")

    def test_parse_verdict(self):
        self.assertEqual(w.parse_verdict("x\n**VERDICT: approve**"), "APPROVE")
        self.assertEqual(w.parse_verdict("VERDICT: CHANGES\n- a"), "CHANGES")
        self.assertIsNone(w.parse_verdict("looks good"))

    def test_wake(self):
        self.set_agents(builder=stream_agent("pathlib.Path('fixed.txt').write_text('x'); text('ok')"))
        code, text = self.cli("wake", "builder")
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", text)
        start_task(self.root, "Create fixed.txt")
        code, text = self.cli("wake", "builder")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "fixed.txt").exists())
        code, text = self.cli("wake", "builder")
        self.assertIn("is verified and has no next step", text)

    def test_schedule_templates(self):
        self.assertIn("vcmd wake claude codex", w.schedule_template("cron", agents=["claude", "codex"], at="03:15"))
        self.assertIn("15 3 * * *", w.schedule_template("cron", agents=["claude"], at="03:15"))
        gh = w.schedule_template("github", agents=["claude"], use_loop=True)
        self.assertIn("repository_dispatch", gh)
        self.assertIn("vcmd wake claude --loop", gh)
        self.assertIn("@anthropic-ai/claude-code", gh)
        self.assertNotIn("@openai/codex", gh)
        self.assertIn("OnCalendar=*-*-* 02:00:00", w.schedule_template("systemd", agents=["x"]))
        with self.assertRaises(ValueError):
            w.schedule_template("cron", agents=["x"], at="25:00")


if __name__ == "__main__":
    unittest.main()
