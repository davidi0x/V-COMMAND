"""`vcmd demo`: "Done isn't verified" in two acts.

Scripted agents (no AI model is called), but every file, check, ledger entry and context frame is
real and produced by the same code paths as `vcmd agent`.
"""
from __future__ import annotations

from pathlib import Path
import io
import sys
import tempfile
import time

from .core import init_project, load_config, save_config, run_task
from .state import start_task, build_frame, record_run_failure, read_ledger
from .adapters import build_prompt

TEST = """import sys
from calc import add
result = add(2, 3)
print(f"V/  VERIFY     test_calc.py: add(2, 3) = {result}, expected 5")
sys.exit(0 if result == 5 else 1)
"""

# Agent A: buggy implementation, confident report.
AGENT_A = """from pathlib import Path
Path("calc.py").write_text("def add(a, b):\\n    return a - b\\n")
print("      agent-a: implemented add() in calc.py. Task complete, all done!")
"""

# Agent B: reads the handed-over frame (argv[1]) and acts on the recorded failure.
AGENT_B = """import sys
from pathlib import Path
frame = sys.argv[1]
constraints = frame.count("Do not repeat")
print(f"      agent-b: received context frame, {constraints} failed approach(es) to avoid")
Path("calc.py").write_text("def add(a, b):\\n    return a + b\\n")
print("      agent-b: fixed add() in calc.py")
"""


def _pause(seconds: float, fast: bool) -> None:
    if not fast:
        time.sleep(seconds)


def run_demo(fast: bool = False, out=None) -> int:
    out = out or sys.stdout

    def say(line: str = "", pause: float = 0.35) -> None:
        print(line, file=out, flush=True)
        _pause(pause, fast)

    with tempfile.TemporaryDirectory(prefix="vcommand-demo-") as temp:
        root = Path(temp)
        init_project(root)
        (root / "test_calc.py").write_text(TEST, encoding="utf-8")
        # -B: never trust bytecode cached from a previous attempt written in the same second.
        gate = [sys.executable, "-B", "test_calc.py"]
        cfg = load_config(root)
        cfg["checks"] = [gate]
        save_config(root, cfg)
        start_task(root, "Implement add(a, b) in calc.py")
        quiet = io.StringIO()  # keep run_task's raw argv lines out of the story

        say("V/COMMAND demo — Done isn't verified")
        say("(scripted agents; real files, real checks, real ledger; no AI model called)")
        say()
        say("[1] agent-a works on: Implement add(a, b) in calc.py")
        first = run_task(root, [sys.executable, "-c", AGENT_A], agent="agent-a", log=quiet, gates_judge=True)
        verdict = "PASS" if first["status"] == "verified_by_configured_checks" else "FAIL"
        say(f"V/  RESULT     {verdict} -> status: {first['status']}")
        if verdict == "PASS":
            return 1  # the story requires the first attempt to be caught
        say("V/  NOTE       the agent said \"done\"; the check disagrees. Not verified.", 0.8)
        entry = record_run_failure(root, first, agent="agent-a", note="agent-a: add() implemented as a - b")
        say(f"V/  LEDGER     {entry['id']}: \"{entry['tried']}\" failed test_calc.py; next agents must not repeat it")
        say()

        frame = build_frame(root)
        say(f"[2] handoff -> agent-b with context frame {frame['continuity_token'][:23]}")
        prompt = build_prompt(frame)
        second = run_task(root, [sys.executable, "-c", AGENT_B, prompt], agent="agent-b", log=quiet,
                          record_argv=[sys.executable, "-c", "<agent-b>", f"<context frame {frame['continuity_token'][:23]}>"],
                          gates_judge=True)
        ok = second["status"] == "verified_by_configured_checks"
        say(f"V/  RESULT     {'PASS' if ok else 'FAIL'} -> status: {second['status']}")
        say()
        say(f"Evidence: 2 runs, {len(read_ledger(root))} recorded failure, cost unknown (no provider receipt).")
        say("Done isn't verified. Verified is verified.", 0)
        return 0 if ok else 1
