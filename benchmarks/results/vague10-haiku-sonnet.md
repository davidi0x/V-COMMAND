# vague10 — Claude Haiku and Claude Sonnet, three briefing arms (live, provider-reported cost)

Suite: `benchmarks/vague10` (10 Python tasks, one-sentence goal; the exact requirements are only in each task's
README.md). Agent: Claude Code (`claude -p`, stream-json). 2 repeats per task and arm, single attempt, no
infra errors. Raw rows: `vague10-haiku-sonnet.jsonl`.

| Arm | Passed | Pass rate | Wilson 95% | Cost per verified task (USD) | Known cost (USD) |
|---|---|---|---|---|---|
| haiku:plain (goal + gate commands) | 20/20 | 100% | 84–100% | 0.0060 | 0.1194 |
| haiku:frame (context frame) | 20/20 | 100% | 84–100% | 0.0081 | 0.1622 |
| haiku:enhanced (enhancer brief + frame) | 20/20 | 100% | 84–100% | 0.0134 | 0.2672 |
| sonnet:plain | 13/20 | 65% | 43–82% | 0.1237 | 1.6085 |
| sonnet:frame | 19/20 | 95% | 76–99% | 0.0975 | 1.8524 |
| sonnet:enhanced | 18/20 | 90% | 70–97% | 0.1731 | 3.1165 |

Enhanced arms include the enhancer's own cost.

Two-sided Fisher exact tests (unpaired, n = 20 per arm):

* sonnet:plain vs sonnet:frame — 13/20 vs 19/20, p = 0.044
* sonnet:plain vs sonnet:enhanced — 13/20 vs 18/20, p = 0.127
* sonnet:frame vs sonnet:enhanced — 19/20 vs 18/20, p = 1.0
* haiku:plain vs sonnet:plain — 20/20 vs 13/20, p = 0.008

## What this does and does not show

* **The context frame helped Sonnet on these tasks** (65% -> 95%, p = 0.044) and made no difference for Haiku,
  which already passed everything (it reads the repository README on its own; Sonnet, left to the bare goal,
  often did not and failed the convention tests). Earlier suites (sample, ts200) showed no benefit; this is
  the first measured one, on one suite we wrote, with one model family, n = 20 per arm. Treat it as a lead.
* **The enhancer did not beat the frame** (Haiku 100% vs 100%, Sonnet 90% vs 95%) and cost 1.7–2.2x more per
  verified task. Its value here is for the human (the questions it raises, an explicit plan and brief), not a
  higher pass rate. It is optional in Mission.
* **Cheaper model, same suite:** haiku:plain verified a task for $0.006, sonnet:frame for $0.098 — about 16x
  more — at a *higher* pass rate for Haiku on this suite. That is a measurement of the routing idea on easy,
  self-contained tasks only; harder, multi-file work may reverse it.
* Tasks were written by us, with hidden tests known to us; the suite is small and Python-only.
