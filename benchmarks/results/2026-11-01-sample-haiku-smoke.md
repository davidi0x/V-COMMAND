# Smoke run — sample suite, Claude Haiku, 2026-11-01

Command (Claude Code 2.1.316, model alias `haiku`, one attempt per run):

```bash
vcmd bench benchmarks/sample --arm haiku:plain --arm haiku:frame --timeout 300
```

`haiku` agent template: `claude -p --model haiku --output-format json --permission-mode acceptEdits {prompt}`
with the `claude-json` cost parser (costs below are provider-reported `total_cost_usd`).

5 task(s), 10 run(s).

| Arm | Passed | Pass rate | Wilson 95% | Median wall (s) | Known cost (USD) | Unknown-cost runs | Median prompt chars |
|---|---|---|---|---|---|---|---|
| haiku:plain | 5/5 | 100% | 57%–100% | 12.65 | 0.0220 | 0 | 175 |
| haiku:frame | 5/5 | 100% | 57%–100% | 16.65 | 0.0305 | 0 | 1715 |

## Paired (same task, same repeat)

- haiku:plain only: 0 · haiku:frame only: 0 · same outcome: 5

## Caveats

- Only 5 task(s): intervals are wide; this is a smoke test, not evidence.
- Single attempt per run; no handoff or retries.
- Cost is provider-reported where the agent template parses it; otherwise unknown, not zero.

## Reading

- Both arms solved all five tasks. On tasks this small the frame adds no measurable benefit.
- The frame arm cost more (+$0.0085 total, about +39%) and took longer (median +4 s): its prompt is
  about 10× longer (goal, instructions, code slice, blast radius, gates).
- This does **not** test the claims the frame exists for — continuity after a failed attempt, a
  provider switch, or larger codebases where finding the right code is the hard part. Those need a
  suite of harder tasks (target: ~200 TypeScript tasks) and handoff arms.
- n = 5: the Wilson intervals (57–100%) are far too wide to compare pass rates.

Raw rows: `2026-11-01-sample-haiku-smoke.jsonl`.
