# Benchmarks

`vcmd bench` measures, on the same tasks and the same gates, whether V/COMMAND's context frame
changes pass rate, wall-clock time and provider-reported cost.

```bash
vcmd bench benchmarks/sample --arm claude:plain --arm claude:frame --repeats 3
```

- `<agent>:plain` — the prompt a developer would type: the goal plus the gate commands.
- `<agent>:frame` — the full context frame: goal, focus code slice, blast radius, pre-flight
  warnings, gates.
- Each run: fresh copy of the task template, new git repo, one agent attempt, gates decide.
- Output: `.vcommand/bench/<run>/results.jsonl`, `summary.json`, `report.md` (pass rate with Wilson
  95% interval, median wall time, known cost, paired task-level differences).

## Suite format

```
my-suite/
  suite.json
  task-a/   # template copied for every run (code + tests)
  task-b/
```

```json
{
  "name": "my-suite",
  "tasks": [
    {"id": "task-a", "dir": "task-a", "goal": "What the agent must achieve",
     "focus": ["src/file.ts:Symbol"],
     "gates": [["node", "--experimental-strip-types", "--test", "src/file.test.ts"]]}
  ]
}
```

`python` as the first gate word means the interpreter running V/COMMAND. TypeScript gates in the
sample use Node ≥ 22.6 type stripping, so no build step is needed.

## Status

- `sample/` — 5 small tasks (3 Python, 2 TypeScript), each with a real bug and a test that catches
  it. A smoke suite for the harness.
- `results/` — recorded runs with their interpretation. The first smoke run found no benefit from the
  frame on tasks this small, and a cost/latency overhead.
- **Not done yet:** the ~200-task TypeScript suite from the roadmap, and handoff arms (attempt →
  failure → second agent with vs. without the frame). Tasks for that suite should come from real
  bug-fix commits with their tests, so that "passing" means something.
