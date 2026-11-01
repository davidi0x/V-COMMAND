# Development roadmap and suggested GitHub issues

Priority order: demonstrate independent verification first, adapter interoperability second, cost/quality optimization third.

## Phase 0 — repo bootstrap (current)

- [x] MIT source repo archive, docs, initial CLI, tests.
- [ ] Create a public GitHub repository `vcommand` and import the files.
- [ ] Run CI on Windows, Ubuntu, macOS.
- [ ] Upload first honest `vcmd demo` terminal capture to README.

## Phase 1 — useful verification CLI (milestone: v0.1 stable)

Issues to open:
1. `feat: verifier profiles for Node, Python, Go and Rust` — auto-detect only with user confirmation.
2. `feat: safe report redaction and local retention controls` — avoid secrets in `argv` and Git file paths.
3. `feat: write JUnit + GitHub PR summary export` — machine-readable compatibility.
4. `test: windows process execution and child timeout coverage`.
5. `feat: task state events + deterministic replay for reporting`.

Success = 10 independent developers run it in their real repositories and understand the result without asking for a dashboard.

## Phase 2 — agent adapters (milestone: v0.2)

6. `adapter: Codex CLI noninteractive session lifecycle`.
7. `adapter: OpenCode session + event metadata`.
8. `adapter: Claude Code official hooks and lifecycle`.
9. `feat: handoff manifest schema for cross-model transfer`.
10. `feat: detect command intent / ask user approval before actions`.

Start with explicit user configurations and maintain a provider compatibility matrix. Do not collect credentials or scrape internal state.

## Phase 3 — trustworthy cost and memory (milestone: v0.3)

11. `feat: provider cost receipt ingestion and price source metadata`.
12. `feat: preflight budget gate at model adapter boundary`.
13. `feat: local memory with retention, clear, exclusions and project isolation`.
14. `benchmark: paired evaluation of routing/memory effect on verified tasks`.
15. `feat: attempt tracking based on actual agent traces`.

## Phase 4 — UX + launch

16. `ux: lean terminal TUI with keyboard-only flows`.
17. `integration: VS Code sidebar optional`.
18. `integration: macOS/Windows V/ Pulse tray optional`.
19. `marketing: 15-second demo showing a failed check caught and resolved`.

## Out of scope unless users demand it

- Building another IDE or another full terminal emulator.
- Implementing a new foundation model.
- Promising to equalize a large model through parallel smaller models.
- Always-on agent mascots and flashy visual dashboards.

## Benchmark guardrails

Compare *the same tasks* under fixed testing conditions. Measure full wall-clock time, provider spend and check pass rate. Include repeated runs, paired seeds when supported, confidence intervals and failure disclosure. Use actual receipts instead of token price approximations where possible.
