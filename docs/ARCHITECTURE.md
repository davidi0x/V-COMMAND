# Architecture & evidence contract

## Alpha (implemented)

```text
               developer terminal (any OS)
                         |
                    vcmd run -- ...
                         |
                  stdlib subprocess
                    /         \
             user command   local check profile(s)
                    \         /
                      event assembly
                           |
                   evidence JSON on disk
                           |
                    vcmd evidence
```

All executable commands are **explicit argv arrays** (no `shell=True`). Command stdout/stderr are inherited by the terminal and not persisted. Evidence is JSON stored in `.vcommand/runs/` relative to the invocation directory. The tool is *not* a sandbox: commands run with normal user privileges and may access the network.

A successful command without configured checks is **unverified**, never "passed". When configured checks pass, status is `verified_by_configured_checks`. Checks failing => `failed_verification`.

## Evidence schema v1

```json
{
  "schema_version": 1,
  "id": "20261101T220000123456Z-a1b2c3d4",
  "created_at_utc": "2026-11-01T22:00:00+00:00",
  "mode": "balanced",
  "demo": false,
  "status": "verified_by_configured_checks",
  "action": {"argv": ["python", "-m", "unittest"], "exit_code": 0, "duration_ms": 100, "timed_out": false, "passed": true},
  "checks": [{"argv": ["python", "-m", "compileall", "-q", "."], "exit_code": 0, "duration_ms": 42, "timed_out": false, "passed": true}],
  "git_status_before": null,
  "git_status_after": null,
  "cost": {"currency": "USD", "amount": null, "source": "unavailable"},
  "memory_savings_usd": null,
  "rejected_candidate_count": null,
  "limitations": ["See generated file for full limitations"]
}
```

Git status reflects repository *snapshots* (may contain work that predated the command). No causal attribution of edits is claimed. JSON is not signed or tamper-proof and requires redaction before sharing externally.

## Project state (implemented)

Model-independent state lives next to the evidence:

```text
.vcommand/
  config.json      checks (acceptance gates), mode
  task.json        goal, completed steps, next step
  ledger.jsonl     append-only failed approaches (negative knowledge)
  runs/*.json      evidence per run
```

`vcmd frame` compiles these plus `git rev-parse HEAD` and `git status` into a context frame
(`frame_version: 1`). `continuity_token` is SHA-256 over the frame without `generated_at_utc`.
Ledger entries contain the agent name, what was tried, which gate failed and a constraint — never
command output. See [EXECUTION_KERNEL.md](EXECUTION_KERNEL.md).

## Future modular design

```text
                TUI CLI | IDE companion | Pulse
                            |
                  V/ session coordinator
                            |
     +----------------------+------------------------+
     |                      |                        |
 Agent adapters         Verification             Cost collector
 (Codex/OpenCode/       checks + policy          (provider receipts)
  Claude Code/others)         |                        |
     |                       +------------+-----------+
     |                                    |
     +--------> append-only local events -+
                                          |
                              evidence ledger (SQLite)
                                          |
                   local memory <---- audit + diagnostics
                                          |
                          optional signed / CI artifacts
```

Avoid forced proxying of secrets and unsupported usage hooks. Prefer official extension points and noninteractive CLI modes; track each provider's version compatibility and output formats. Cost enforcement should be at request ingress, not after the billable operation.

## Design invariants

1. Unknown cost, rejected attempts and savings are null, never zero or synthetic.
2. One task gets one immutable run ID. Alpha writes one JSON file; future signed append-only records should prevent silent mutation.
3. Verification status never claims semantic correctness or security certification.
4. No command output or keys are persisted by default; argv and Git filenames are still potentially sensitive.
5. Offline mode requires real isolation to be labelled "enforced"; not available in alpha.
6. A failed test remains visible even when the agent says it succeeded.
