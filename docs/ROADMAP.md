# Development roadmap and suggested GitHub issues

Priority order: demonstrate independent verification first, adapter interoperability second, cost/quality optimization third.

## Phase 0 — repo bootstrap (current)

- [x] MIT source repo archive, docs, initial CLI, tests.
- [x] Import into the public GitHub repository `davidi0x/V-COMMAND`.
- [x] Task checkpoint, negative knowledge ledger and context frame handoff (`vcmd task|ledger|frame`).
- [x] Run CI on Windows, Ubuntu, macOS.
- [x] Upload first honest `vcmd demo` terminal capture to README (`docs/demo.svg`, rendered from a real run).

## Phase 1 — useful verification CLI (milestone: v0.1 stable)

Issues to open:
1. `feat: verifier profiles for Node, Python, Go and Rust` — auto-detect only with user confirmation.
2. `feat: safe report redaction and local retention controls` — avoid secrets in `argv` and Git file paths.
3. `feat: write JUnit + GitHub PR summary export` — machine-readable compatibility.
4. `test: windows process execution and child timeout coverage`.
5. `feat: task state events + deterministic replay for reporting`.

Success = 10 independent developers run it in their real repositories and understand the result without asking for a dashboard.

## Phase 2 — agent adapters (milestone: v0.2)

6. [x] `adapter: Codex CLI` — `vcmd agent codex` wrapper (checked against codex-cli 0.166) and `vcmd hooks install codex`.
7. [x] `adapter: OpenCode` — `opencode run {prompt}` template.
8. [x] `adapter: Claude Code official hooks and lifecycle` — SessionStart frame injection, Stop gate.
8a. [x] `feat: per-attempt worktree isolation` — `vcmd agent --isolate`.
9. [x] `feat: code slice and blast radius in the context frame` — `vcmd task focus` (Python ast, TS/JS scanner).
9a. [x] `feat: benchmark harness` — `vcmd bench`, sample suite, first smoke result recorded.
9b. [x] `benchmark: ~200 TypeScript tasks incl. handoff arms` — `benchmarks/ts200`, `vcmd bench --handoff`, results in `benchmarks/results/`.
9c. [x] `feat: race mode` — `vcmd agent --race`.
9d. [x] `feat: stream guard` — banned patterns, kill mid-attempt.
9e. [x] `feat: optional tree-sitter backend` — `pip install "vcommand-cli[ast]"`.
10. `feat: detect command intent / ask user approval before actions`.

Start with explicit user configurations and maintain a provider compatibility matrix. Do not collect credentials or scrape internal state.

## Phase 3 — trustworthy cost and memory (milestone: v0.3)

11. [x] `feat: provider cost receipt ingestion` — Claude Code `total_cost_usd`; Codex tokens + labelled estimate from configured prices.
12. [x] `feat: budget gate` — `--budget`, `budget.max_usd_per_task`, checked before each attempt.
13. `feat: local memory with retention, clear, exclusions and project isolation`.
14. `benchmark: paired evaluation of routing/memory effect on verified tasks`.
15. `feat: attempt tracking based on actual agent traces`.
15a. [x] `feat: pre-flight hints derived from ledger counts`.
15b. [x] `feat: provider circuit breaker + failover at the adapter boundary`.

## Phase 4 — UX + launch

16. `ux: lean terminal TUI with keyboard-only flows`.
17. `integration: VS Code sidebar optional`.
18. `integration: macOS/Windows V/ Pulse tray optional`.
19. [x] `marketing: 15-second demo showing a failed check caught and resolved` — `vcmd demo`, `docs/demo.svg`.
20. [x] `feat: hardware probe + local backup model recommendation` — `vcmd hw`, `--add-agent local` (codex --oss + Ollama).
21. [x] `feat: overnight task queue with tasks frozen for human decisions` — `vcmd queue`, `vcmd ask`, `--jobs N` parallel workers with file locks.

## Out of scope unless users demand it

- Building another IDE or another full terminal emulator.
- Implementing a new foundation model.
- Promising to equalize a large model through parallel smaller models.
- Always-on agent mascots and flashy visual dashboards.

## Benchmark guardrails

Compare *the same tasks* under fixed testing conditions. Measure full wall-clock time, provider spend and check pass rate. Include repeated runs, paired seeds when supported, confidence intervals and failure disclosure. Use actual receipts instead of token price approximations where possible.
