# Execution Kernel — analysis and adoption plan

The Execution Kernel proposal treats an LLM as a **stateless processor**: project state
(goal, progress, failed approaches, acceptance gates, code structure) lives on disk, and each model
— cloud, local, or a fresh session of the same one — receives a compact, compiled snapshot instead of
chat history. This document records what V/COMMAND adopts now, what is staged for later, and which
claims must be measured before they appear in the README.

## Adopted in 0.1.x (implemented, tested)

| Concept | V/COMMAND implementation |
|---|---|
| State separated from the model | `.vcommand/task.json` — goal, completed steps, next step (`vcmd task …`) |
| Negative Knowledge Ledger | `.vcommand/ledger.jsonl` — append-only failed approaches. Filled automatically when `vcmd run` fails (`--agent`, `--note`) and manually with `vcmd ledger add` |
| Context Frame | `vcmd frame` (Markdown prompt) / `vcmd frame --json` — goal, done steps, next step, hard constraints, acceptance gates, last run, HEAD and working tree |
| Continuity token | SHA-256 over the frame's stable content; same state ⇒ same token, any change ⇒ new token |
| Deterministic gate as the only judge | Already the core rule: configured checks decide, never the agent's own report (in `vcmd agent`, not even its exit code) |
| Copy-on-write sandboxes | `vcmd agent --isolate`: disposable `git worktree` per attempt, dependencies linked, only verified patches applied |
| Automatic frame in / ledger out | Claude Code hooks and `vcmd agent` wrapper — see [ADAPTERS.md](ADAPTERS.md) |

Handoff between agents today:

```bash
vcmd task start "Fix login and add password reset"
vcmd run --agent model-a --note "jwt.destroy() in controller" -- <agent command>
# checks fail → failed approach recorded automatically
vcmd frame --out handoff.md          # paste into model B, any provider
vcmd run --agent model-b -- <agent command>
```

Unlike the original sketch, the frame does **not** store command output or compiler logs (secrets
risk); a failure is described by which gate failed and the human/agent-supplied `--note`.

## Staged (roadmap, not implemented)

| Concept | Stage | Precondition |
|---|---|---|
| AST slice + blast radius (tree-sitter / LSP) in the frame | Phase 2 | Language-specific; start with TypeScript, measure frame size vs. quality |
| Pre-flight hints learned from the ledger ("in this repo, changes to X usually break Y") | Phase 3 | Enough real ledger data; hints must cite counts, not invented percentages |
| SQLite ledger with per-call telemetry (model, time, cost, gate result) | Phase 3 | Real provider receipts for cost |
| Provider failover / circuit breaker, budget ceiling | Phase 3 | Adapter boundary; reuse LiteLLM-style routers rather than rebuild |
| Parallel speculative candidates in separate worktrees | Phase 3 | Benchmark showing a win in wall-clock time *and* cost |
| Streaming guard (kill generation on unknown method) | Research | Needs streaming access and real symbol tables; regex matching is too brittle |
| Hardware probe + local GGUF backup model recommendation | Phase 4, optional | Delegate inference to llama.cpp/Ollama/LM Studio; recommend only, never auto-download multi-GB weights |
| Overnight DAG queue with file locks and "frozen, needs human" tasks | Phase 4 | Sandboxes + adapters first |
| Rust daemon | Only if profiling shows Python is the bottleneck | Today the cost is model latency, not the CLI |

## Not adopted

- **Custom memory governor / NVMe tensor tiering (mmap, mlock, madvise, expert streaming).** llama.cpp
  already memory-maps GGUF weights and handles offload; re-implementing this outside the inference
  engine adds risk with no product advantage for a verification layer.
- **Simulated output.** The proposed `kernel daemon` prototype printed "GATE PASSED" and a fixed commit
  hash without running anything. V/COMMAND never prints a result it did not observe.

## Claims that need a benchmark before publication

From the proposal, stated as hypotheses only:

- "~900-token frame replaces 40k tokens of chat with no loss" — measure task success with frame vs. full history.
- "~3× faster wall-clock, 60–75% cheaper with two cheap models in parallel" — paired runs on the same task set.
- "Early kill saves 70% of tokens on hallucinations" — requires streaming adapter and measurement.
- "Local 30B MoE at ~38 tok/s on a 16 GB machine via NVMe" — hardware-specific; publish measured numbers only.
- Repository-specific failure rates (e.g. "68% of models forget cache invalidation") — only from actual ledger counts.

Benchmark plan (Phase 2 milestone): ~200 TypeScript tasks with deterministic tests; arms =
reference model solo, cheap model solo, cheap model + context frame (+ ledger after a failed attempt);
report pass rate, wall-clock, provider-reported cost, confidence intervals and failures.
