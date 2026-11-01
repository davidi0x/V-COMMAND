# V/COMMAND

**Your agents. Under control.**

> Open-source, terminal-first execution evidence for AI coding agents.
>
> **Alpha:** real subprocess execution + verification checks + local evidence. No claim of autonomous model orchestration yet.

```text
V/COMMAND                                      / verified execution
────────────────────────────────────────────────────────────────────
V/  EXECUTE    python -m my_existing_agent
V/  VERIFY     python -m unittest discover -s tests
V/  EVIDENCE
Run       20261101T210000Z-example
Status    verified_by_configured_checks
Checks    1/1 command passed
API cost  unknown (no provider receipt)
Savings   unknown (no benchmark baseline)
────────────────────────────────────────────────────────────────────
```

## Why

AI coding agents are useful, but "task completed" is not evidence the change works. Developers also need transparent cost accounting and continuity across models. V/COMMAND starts with independent verification and truthful, local evidence reports. Future releases can add opt-in provider adapters, memory, handoffs, routing and budgets.

## Current features (0.1.0-alpha)

- Run a user-supplied command **without a shell**; output stays in your terminal.
- Configure verification commands and automatically execute them after a successful task command.
- Store each run's status, check results, timing and optional Git *status snapshots* locally as JSON.
- Distinguish `unverified`, `verified_by_configured_checks`, `failed`, and `failed_verification`.
- View reports in human-friendly CLI or machine-readable JSON.
- Save a work-mode preference (`speed`, `balanced`, `offline`); **this does not yet route models or enforce offline isolation**.
- No API dependency, no background daemon, no telemetry, no cloud account.
- Python 3.10+, Windows/macOS/Linux intended; tested in CI matrix.

## Quick start

```bash
# At project root, with Python >= 3.10
python -m pip install -e .
vcmd doctor
vcmd demo
vcmd init
vcmd check add -- python -m unittest discover -s tests
vcmd run -- python -c "print('agent completed')"
vcmd evidence
vcmd evidence --json
vcmd mode offline
vcmd cost
```

**Note:** The example shows an actual Python command, not an LLM integration. Replace it with your existing trusted agent command (e.g. any executable available in PATH). Commands are executed with *your* current OS permissions. Do not run untrusted tools.

### Typical workflow

```bash
vcmd init
vcmd check add -- npm test
vcmd run -- npm run build
vcmd evidence --json
```

The resulting JSON is stored in `.vcommand/runs/` (should be Git-ignored). It is not cryptographically tamper-proof. Verification means only the *configured checks* passed; it does **not** prove the software correct or secure.

## What this alpha does NOT do

| Capability | Status |
|---|---|
| Existing command execution | Implemented |
| Configurable post-run checks | Implemented |
| Local Evidence Report | Implemented |
| Git status before/after (not causal attribution) | Implemented |
| Live agent session adapters | Planned |
| Automatic model routing / cross-provider handoff | Planned |
| Enforced cost ceiling / provider receipts | Planned |
| True air-gapped offline enforcement | Not implemented |
| Local semantic memory / savings measurements | Planned |
| Auto-repair on failed verification | Planned |
| Advanced TUI and IDE companions | Planned |

## Project principles

1. **Terminal-first**: works in PowerShell, Warp, Ghostty, Windows Terminal, VS Code integrated terminals and others.
2. **Evidence, not decoration**: clear status backed by checks.
3. **Unknown is not zero**: do not invent money saved, model cost, or errors prevented.
4. **User sovereignty**: local by default; no forced cloud, account or subscription.
5. **Provider-neutral**: no special dependency on one model or coding agent.

## Documentation

- [Full product concept (Polish)](docs/CONCEPT_PL.md)
- [Architecture and evidence contract](docs/ARCHITECTURE.md)
- [MVP acceptance criteria](docs/MVP.md)
- [Milestones and GitHub issues](docs/ROADMAP.md)
- [Open-source launch and branding](docs/LAUNCH.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT — free to use, fork, modify and redistribute. Running paid model APIs still incurs providers' normal charges; V/COMMAND itself is free.

## Prior art / competition

See [competitive notes](docs/COMPETITION.md). Existing model routers and agents are important complements, not claims of invention.
