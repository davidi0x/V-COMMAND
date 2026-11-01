# Agent adapters

Adapters move the [context frame](EXECUTION_KERNEL.md) into coding agents and run the acceptance
gates on their work, without copying chat history and without storing prompts or agent output.

## Claude Code and Codex CLI — hooks (interactive sessions)

Both agents use the same hook protocol, so V/COMMAND supports both with the same handlers.

| | Claude Code | Codex CLI |
|---|---|---|
| Install | `vcmd hooks install claude` | `vcmd hooks install codex` |
| File | `.claude/settings.json` | `.codex/hooks.json` |
| Extra step | none | open `codex`, run `/hooks`, trust both V/COMMAND hooks (Codex skips untrusted project hooks) |
| Stop limit setting | `claude_max_stop_blocks` | `codex_max_stop_blocks` |

### Claude Code example

```bash
vcmd init
vcmd check add -- npm test
vcmd task start "Fix login and add password reset"
vcmd hooks install claude        # merges into .claude/settings.json, keeps your other hooks
claude
```

| Hook | What V/COMMAND does |
|---|---|
| `SessionStart` (startup, resume, `/clear`, compaction) | Prints the context frame; Claude Code adds it to the model's context. After a compaction or a fresh session the goal, completed steps, next step, failed approaches and gates are back. |
| `Stop` | Runs the configured checks (output goes to stderr). All pass → Claude may stop and evidence is written. A check fails → the stop is blocked with the failing gate as the reason, and the failure is added to the ledger. After `claude_max_stop_blocks` (default 3) blocked stops in a session, Claude is allowed to stop with a "Not verified" message, so a session can never loop forever. |

Settings:

```json
// .vcommand/config.json
{ "hooks": { "claude_max_stop_blocks": 3, "codex_max_stop_blocks": 3 } }
```

The hook commands are `vcmd hook <claude|codex> session-start` and `vcmd hook <claude|codex> stop`;
`vcmd` must be on the agent's `PATH`. Hooks fail open: an internal error is printed to stderr and never
breaks the agent session. Remove with `vcmd hooks uninstall claude` / `vcmd hooks uninstall codex`.

Verified live with Claude Code 2.1.x: an agent told only to reply "hi" was blocked at Stop by a
failing gate, created the missing file from the block reason, and the second Stop passed
(`verified_by_configured_checks`).

## Codex CLI, Claude Code print mode, other CLIs — wrapper

```bash
vcmd agent codex                 # one attempt
vcmd agent codex claude          # codex; if gates fail, hand off to claude with the updated frame
vcmd agent claude --attempts 3   # retry the same agent, each time with the newest failures
vcmd agent --list                # show command templates
```

Each attempt:

1. builds a fresh context frame (including failures from earlier attempts),
2. runs the agent non-interactively with the frame as its prompt (stdin is closed),
3. runs the gates **even if the agent exited non-zero** — the agent's exit code is a self-report and is
   only recorded; the gates decide. If the agent binary cannot be launched, checks are skipped and the
   attempt is `failed`,
4. on failure records a ledger entry (agent, attempt, changed files, failing gate) and continues with
   the next agent.

The changes of a failed attempt stay in the working tree; the next agent continues from them and sees
them in the frame. Commit or stash first if you want a clean baseline.

Evidence stores `<context frame sha256:…>` instead of the prompt.

### Templates

Defaults (override or add agents in `.vcommand/config.json`; `{prompt}` is required):

```json
{
  "agents": {
    "codex":  ["codex", "exec", "--sandbox", "workspace-write", "{prompt}"],
    "claude": ["claude", "-p", "--permission-mode", "acceptEdits", "{prompt}"],
    "cheap":  ["claude", "-p", "--model", "haiku", "--permission-mode", "acceptEdits", "{prompt}"]
  }
}
```

The `codex` template is checked against codex-cli 0.166 (`--full-auto` no longer exists there; use
`--sandbox workspace-write`). If your version differs, compare with `codex exec --help`.
Permission flags decide what the agent may do unattended; choose them deliberately.

Verified live: `vcmd agent codex claude` with Codex not logged in — Codex exited 1, the gate failed
and was recorded, the frame got a new continuity token, Claude received it, fixed the task and the
gate passed. A provider outage, quota or login problem becomes a handoff instead of a dead end.

## Not yet

- OpenCode adapter.
- Cost per attempt from provider receipts (cost remains `unknown`).
- Worktree isolation per attempt.
