# ts200 — plain prompt vs context frame, Claude Haiku, 2026-11-02

```bash
vcmd bench benchmarks/ts200 --arm haiku:plain --arm haiku:frame --jobs 8 --timeout 300
vcmd bench benchmarks/ts200 --arm haiku:plain --arm haiku:frame --jobs 4 --resume <dir>   # after rate limiting
```

Agent: Claude Code 2.1.316, `--model haiku`, stream-json with the `claude-stream` parser (provider-reported
`total_cost_usd`). One attempt per run, 200 tasks × 2 arms = 400 runs.

| Arm | Passed | Pass rate | Wilson 95% | Median wall (s) | Known cost (USD) | Unknown-cost runs | Median prompt chars | Infra errors (excluded) |
|---|---|---|---|---|---|---|---|---|
| haiku:plain | 200/200 | 100% | 98%–100% | 16.16 | 1.1609 | 0 | 215 | 0 |
| haiku:frame | 200/200 | 100% | 98%–100% | 17.12 | 1.2183 | 0 | 1711 | 0 |

## Paired (same task, same repeat)

- haiku:plain only: 0 · haiku:frame only: 0 · same outcome: 200

## Reading

- **Both arms solved all 200 tasks.** On these tasks a single Haiku attempt does not need the frame;
  the suite does not discriminate between the arms on first attempts.
- **The frame costs more:** +$0.057 in total (+4.9%) and ~1 s per run (median 17.1 s vs 16.2 s), for an
  8× longer prompt (1,711 vs 215 characters).
- **Provider failures are not results.** During the first pass, 8 parallel runs hit Claude rate limits:
  89 runs exited immediately with code 1 and $0 cost. They were classified as infra errors, excluded,
  and re-run with `--resume` at 4 parallel runs — all 89 passed. Without that classification the report
  would have shown a false 78% pass rate.
- The question the frame exists for — continuing after a failed attempt — is measured separately with
  handoff arms (`--handoff haiku-short>haiku`).

Total provider-reported spend for this run: **$2.38**.
