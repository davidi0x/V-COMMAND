# ts200 — handoff after a failed attempt, Claude Haiku, 2026-11-02

```bash
vcmd bench benchmarks/ts200 --handoff "haiku-short>haiku" --jobs 4 --timeout 300
```

- Attempt 1: `haiku-short` = Claude Code `--model haiku --max-turns 2` with the plain prompt. Two turns are
  not enough to read and fix the code, so it simulates an agent that stops early (turn limit, crash, quota).
- On failure the repository state after attempt 1 is copied twice; `haiku` (no turn limit) continues once
  with the plain prompt and once with the context frame, which now records attempt 1's failure.
- 200 tasks, 400 rows (both arms share attempt 1).

| Arm | Passed | Pass rate | Wilson 95% | Median wall (s) | Known cost (USD) | Unknown-cost runs | Median prompt chars | Infra errors (excluded) |
|---|---|---|---|---|---|---|---|---|
| haiku-short>haiku:plain | 200/200 | 100% | 98%–100% | 26.02 | 1.7873 | 0 | 215 | 0 |
| haiku-short>haiku:frame | 200/200 | 100% | 98%–100% | 26.93 | 1.9036 | 0 | 2076 | 0 |

## Handoff after a failed first attempt

| Arm | First attempt passed | Second attempts | Rescued by agent B |
|---|---|---|---|
| haiku-short>haiku:plain | 0/200 | 200 | 200/200 |
| haiku-short>haiku:frame | 0/200 | 200 | 200/200 |

## Paired (same task, same repeat)

- haiku-short>haiku:plain only: 0 · haiku-short>haiku:frame only: 0 · same outcome: 200

## Reading

- **Attempt 1 failed on all 200 tasks** (the turn limit), and **agent B rescued 200/200 in both arms.**
  On this suite, briefing the second agent with the frame did not change the outcome.
- **The frame costs more:** $1.90 vs $1.79 for the arm (+6.5%), median wall time +0.9 s per task,
  for a ~10× longer prompt (2,076 vs 215 characters).
- **Why no difference:** attempt 1 never got to edit anything, so the second agent starts from a clean
  repository with nothing misleading to undo, and these bugs are small enough to find from the goal alone.
  The frame's value — carrying knowledge about *what already went wrong* — needs tasks where the first
  attempt leaves a plausible but wrong change, or where finding the right code is hard.
- **Classification fix found by this run:** the first version of this benchmark marked every
  `--max-turns` exit as a provider outage. Agents that report `error_max_turns` are now treated as agent
  failures; provider errors are still excluded from pass rates.

Provider-reported spend for this run: at most $3.69 (both arms' rows include the shared first attempt).
