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
| `PreToolUse` (Claude Code: matcher `Bash`; Codex: all tools) | Risky shell commands (deploy, publish, DB write, bulk delete): interactive Claude Code gets `ask` (its own permission prompt); Codex and wrapped agents get `deny` plus an approval request for `vcmd approve`. See [WORKFLOW.md](WORKFLOW.md#3-guardrails-ask-before-deploys-database-writes-and-bulk-deletes). |
| `PreCompact` | Writes `.vcommand/handoff.md` before the context is summarized; `SessionStart` injects it again with the frame. |

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

Without isolation, the changes of a failed attempt stay in the working tree; the next agent continues
from them and sees them in the frame.

### Isolation: `--isolate`

```bash
vcmd agent codex claude --isolate
```

- Every attempt runs in a fresh `git worktree` at `HEAD`, outside the repository; the gates run there.
- A verified attempt's changes are applied to your working tree as a patch (`V/  APPLIED`).
- A failed attempt is discarded (`V/  DISCARDED`); its changed files and failing gate go to the ledger,
  so the next agent starts clean but knows what failed.
- Requires a clean working tree (commit or stash first). `.vcommand/`, `.claude/`, `.codex/` don't count.
- Untracked dependency directories are shared by symlink instead of reinstalling; default
  `node_modules`, configurable:

  ```json
  { "isolation": { "link": ["node_modules", ".venv"] } }
  ```
- Agents get `VCOMMAND_ROOT`, so `vcmd task done …` inside the worktree updates the main project, and
  `VCOMMAND_WRAPPED=1`, so installed hooks don't inject the frame a second time. A Stop hook inside a
  wrapped session still runs the gates in the agent's worktree.

Verified live: `vcmd agent codex claude --isolate` — Codex attempt discarded, Claude's attempt verified
in its worktree and applied (`fixed.txt`), no worktrees left behind.

Evidence stores `<context frame sha256:…>` instead of the prompt.

### Templates

Defaults (override or add agents in `.vcommand/config.json`; `{prompt}` is required). A template is an
argv list, or `{"argv": [...], "cost": "claude-json"}` to record the provider-reported cost:

```json
{
  "agents": {
    "codex":  ["codex", "exec", "--sandbox", "workspace-write", "{prompt}"],
    "claude": {"argv": ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits", "{prompt}"],
               "cost": "claude-json"},
    "cheap":  {"argv": ["claude", "-p", "--model", "haiku", "--output-format", "json",
                        "--permission-mode", "acceptEdits", "{prompt}"], "cost": "claude-json"},
    "local":  {"argv": ["codex", "exec", "--oss", "--local-provider", "ollama", "-m", "qwen2.5-coder:7b",
                        "--sandbox", "workspace-write", "{prompt}"]}
  },
  "failover": {"cooldown_s": 600},
  "budget": {"max_usd_per_task": 1.0}
}
```

`local` is what `vcmd hw --add-agent local` writes for your machine.

### Failover and budget

- **Circuit breaker.** An attempt that could not launch, timed out, or exited non-zero without changing
  any file is treated as a provider/agent failure (auth, quota, rate limit, outage, no local server).
  That agent is skipped for `failover.cooldown_s` while other listed agents are available
  (`V/  FAILOVER   skipping codex: …`). Success closes the circuit. `vcmd agent --health` shows the
  state, `--reset-health` clears it. Verified live: unauthenticated Codex was skipped on the next run
  and Haiku took the task directly.
- **Budget.** `--budget 0.50` or `budget.max_usd_per_task` stops before the next attempt once the known,
  provider-reported spend on the current task reaches the limit. Attempts with unknown cost (agents
  without a cost parser) are listed, not counted as zero.

The `codex` template is checked against codex-cli 0.166 (`--full-auto` no longer exists there; use
`--sandbox workspace-write`). If your version differs, compare with `codex exec --help`.
Permission flags decide what the agent may do unattended; choose them deliberately.

Verified live: `vcmd agent codex claude` with Codex not logged in — Codex exited 1, the gate failed
and was recorded, the frame got a new continuity token, Claude received it, fixed the task and the
gate passed. A provider outage, quota or login problem becomes a handoff instead of a dead end.

### Race: `--race`

```bash
vcmd agent --race claude codex local
```

All agents start at the same time on the same frame, each in its own worktree. The first attempt whose
gates pass is applied; the others are killed (their whole process group) and discarded. Failed attempts
go to the ledger. Verified live: Codex failed, Haiku won after 18.8 s ($0.0060), the second Haiku was
cancelled.

### Stream guard

The default `claude` template streams events (`--output-format stream-json --verbose`, parser
`claude-stream`). Every Edit / Write / MultiEdit is checked before the agent continues:

```bash
vcmd ledger add --tried "jwt.destroy() in the controller" --why "TS2339: jsonwebtoken is stateless" \
                --pattern "jwt.destroy("
```

```json
{ "guard": { "banned": [{"pattern": "eval(", "reason": "security policy"}] } }
```

An edit containing a banned pattern kills the agent immediately (`V/  KILLED     stream guard: …`); the
gates are skipped and the kill is recorded. Verified live: Claude Haiku was stopped 4.8 s into an
attempt. The guard enforces patterns you or earlier failures defined; it does not detect unknown
symbols — the gates (`tsc`, tests) do.

### Codex cost

`codex exec --json` (default template, parser `codex-jsonl`) reports token usage, not USD. V/COMMAND
records the tokens and computes USD only if you set prices; the amount is then marked `estimated`:

```json
{ "prices": { "gpt-5-codex": {"input_per_mtok": 1.25, "cached_input_per_mtok": 0.125, "output_per_mtok": 10.0} } }
```

The model key is the `-m` / `--model` value in the agent template.

### OpenCode

`opencode run {prompt}` (checked against opencode 1.19.5). OpenCode asks before some actions;
`--auto` approves everything not explicitly denied — add it to your template only deliberately.

## Verification status of the newer hooks

* Claude Code `PreToolUse` / `PreCompact`: protocol per the Claude Code hooks documentation; the
  wrapped path (stream guard + approval + retry after `vcmd approve`) was verified live with
  Claude Haiku. The interactive `ask` prompt was not exercised in this environment.
* Codex `PreToolUse` / `PreCompact`: the event names and the `permissionDecision` field are present
  in codex-cli 0.166; a live Codex run was not possible here (no Codex login), so treat Codex
  enforcement as unverified until you see a blocked command in your own session. The `codex-jsonl`
  stream guard on `command_execution` events is covered by unit tests only.
