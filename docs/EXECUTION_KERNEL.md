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
| Automatic frame in / ledger out | Claude Code and Codex hooks, `vcmd agent` wrapper — see [ADAPTERS.md](ADAPTERS.md) |
| Code slice + blast radius (stage 2) | `vcmd task focus file[:Symbol]`: focused source or file outline, references ranked tests → imports → uses. Python via `ast`; TS/JS via a declaration scanner (heuristic, stdlib — tree-sitter was not adopted to keep zero native dependencies) |
| Benchmark harness (stage 2) | `vcmd bench suite --arm agent:plain --arm agent:frame`: fresh repo per run, Wilson 95% intervals, paired results, provider-reported cost — see [benchmarks/](../benchmarks/README.md) |
| Pre-flight hints (stage 3) | Frame section computed only from ledger counts: gates that failed repeatedly, files involved in several failed attempts (focus files first) |
| Provider failover (stage 3) | Circuit breaker per agent: launch error, timeout or non-zero exit without file changes ⇒ skipped for `failover.cooldown_s` while other agents are available |
| Cost and budget (stage 3) | Provider-reported cost from `claude -p --output-format json` (`total_cost_usd`); `--budget` / `budget.max_usd_per_task` stops before the next attempt; unknown cost is reported, never counted as zero |
| Hardware probe + local backup (stage 4) | `vcmd hw`: RAM / VRAM / unified memory, Ollama / llama.cpp detection, memory budget with OS reserve, Ollama model recommendation; `--add-agent local` registers `codex --oss` against Ollama. Inference stays in Ollama — nothing is downloaded by V/COMMAND |
| Overnight queue (stage 4) | `vcmd queue`: sequential isolated tasks with dependencies and per-task gates; verified tasks are committed; agents freeze a task with a question instead of guessing; morning report |

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

### What was measured so far

One live smoke run (5 small tasks, Claude Haiku, 10 runs, $0.0525 — [results](../benchmarks/results/2026-11-01-sample-haiku-smoke.md)):
both arms passed 5/5; the frame arm cost about 39% more and was ~4 s slower per task. On small tasks
the frame is overhead. Whether it pays off on harder tasks and after a failed attempt is still open.

## Still open

| Concept | Why not yet |
|---|---|
| ~200-task TypeScript suite with handoff arms | Needs real bug-fix tasks with tests; the harness is ready, the task set is not |
| Cost for Codex CLI | `codex exec` reports tokens, not USD; a price table would be an estimate, so cost stays unknown |
| Parallel speculative candidates / parallel queue workers | Sequential first; parallelism only if a benchmark shows a wall-clock *and* cost win |
| Streaming guard (kill generation on unknown method) | Needs streaming access and real symbol tables; regex matching is too brittle |
| Tree-sitter / LSP precision for the slice | Optional backend later; would add native dependencies |
| Rust daemon | Only if profiling shows Python is the bottleneck; today the cost is model latency |

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

Benchmark plan: ~200 TypeScript tasks with deterministic tests; arms = reference model solo, cheap
model solo, cheap model + context frame (+ ledger after a failed attempt); report pass rate,
wall-clock, provider-reported cost, confidence intervals and failures. `vcmd bench` implements the
measurement; the task set is the remaining work.
