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

All runs with Claude Haiku via Claude Code, provider-reported costs, results in `benchmarks/results/`:

| Run | Plain prompt | Context frame | Frame cost |
|---|---|---|---|
| sample, 5 tasks, single attempt | 5/5 | 5/5 | +39% |
| ts200, 200 tasks, single attempt | 200/200 | 200/200 | +4.9% |
| ts200, handoff after a failed attempt | 200/200 rescued | 200/200 rescued | +6.5% |

**So far the frame has shown no pass-rate benefit and a small cost.** These tasks are solvable from the
goal alone, and failed first attempts left no misleading edits behind. The frame's claimed value —
continuity after misleading failures, and finding the right code in large repositories — remains a
hypothesis until a harder suite shows it. Total spend on these measurements: about $6.

## Completed after the first review

| Concept | Implementation |
|---|---|
| 200-task TypeScript suite + handoff arms | `benchmarks/ts200` (generated: 20 bug families × 10 domains, each verified both ways in CI); `vcmd bench --handoff A>B` |
| Speculative parallel candidates | `vcmd agent --race a b c`: same frame, separate worktrees, first verified wins, the rest are killed |
| Parallel queue workers | `vcmd queue run --jobs N`: focus-file locks, per-task state, serialized apply+commit, conflict ⇒ re-queue once |
| Streaming guard | `claude-stream` parser: every Edit/Write is checked against banned patterns (ledger `--pattern`, `guard.banned`); the agent is killed mid-attempt. It enforces known-bad patterns; detecting *unknown* symbols mid-stream is left to the gates (`tsc`, tests) |
| Codex cost | `codex-jsonl` parser sums token usage; USD only as an estimate from `prices` in config, flagged `estimated` |
| Tree-sitter precision | Optional backend (`pip install "vcommand-cli[ast]"`); scanner remains the zero-dependency default |
| OpenCode | `opencode run {prompt}` template (checked against opencode 1.19.5) |

### Deliberately not built

| Concept | Reason |
|---|---|
| Rust daemon | Measured: `vcmd frame` with a code slice takes ~0.11 s and `vcmd run` overhead ~0.1 s, against a median agent attempt of 16.5 s (ts200 run) — under 1%. A rewrite cannot make attempts noticeably faster |

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
- "Early kill saves 70% of tokens on hallucinations" — the guard now kills on banned patterns (live: 4.8 s into
  an attempt); a token-saving percentage still needs a measured comparison.
- "Local 30B MoE at ~38 tok/s on a 16 GB machine via NVMe" — hardware-specific; publish measured numbers only.
- Repository-specific failure rates (e.g. "68% of models forget cache invalidation") — only from actual ledger counts.

Benchmark plan: ~200 TypeScript tasks with deterministic tests; arms = reference model solo, cheap
model solo, cheap model + context frame (+ ledger after a failed attempt); report pass rate,
wall-clock, provider-reported cost, confidence intervals and failures — implemented by `vcmd bench` on
`benchmarks/ts200`; results in `benchmarks/results/`.
