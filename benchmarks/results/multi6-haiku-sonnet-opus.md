# multi6 — Claude Haiku, Sonnet and Opus on multi-file tasks (live, context frame, provider-reported cost)

Suite: `benchmarks/multi6` — six Python tasks that each need 3–4 files changed (a field through model, totals,
renderer and CLI; a rename with a deprecation shim and all callers; a TTL cache with a clock; layered
configuration; an event bus wired into two services; a three-module CSV pipeline). Explicit goals. Agent:
Claude Code (`claude -p`, stream-json), arm `<model>:frame`, 2 repeats, single attempt, no infra errors.
Raw rows: `multi6-haiku-sonnet-opus.jsonl`.

| Model | Passed | Pass rate | Wilson 95% | Cost per verified task (USD) | Known cost (USD) | Median wall (s) |
|---|---|---|---|---|---|---|
| haiku | 12/12 | 100% | 76–100% | 0.0113 | 0.1362 | 39.95 |
| sonnet | 12/12 | 100% | 76–100% | 0.1160 | 1.3920 | 26.92 |
| opus | 12/12 | 100% | 76–100% | 0.2874 | 3.4489 | 39.32 |

## What this does and does not show

* **On these tasks a cheaper model was enough:** the same 12/12, at about 10x (Sonnet) and 25x (Opus) the cost
  per verified task of Haiku. For work like this, routing to the cheapest model that passes your gates saves
  most of the money — and the gates tell you when it does not.
* **It says nothing about quality differences between models**: the suite is saturated (everyone passes), so it
  cannot rank them. Tasks that separate the models (large codebases, ambiguous design, hard debugging) have not
  been measured. Do not read this as "Haiku is as good as Opus".
* Small suite written by us, Python only, explicit goals; wall time varies with load (Haiku was not faster).
* A first attempt of this run (36 runs) failed in ~4 s each with exit 1 and zero cost while the session's
  worker was restarted; those results were discarded as an infrastructure failure, and the benchmark now
  treats an agent reply with `is_error` as an infrastructure error instead of a task failure.
