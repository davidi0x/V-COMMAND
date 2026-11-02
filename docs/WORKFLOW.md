# Persistent agent workflow

A long-running task works best as a chain of **short, fresh sessions that share state on disk**.
One huge chat drifts: the context rots, decisions get lost, and nobody can tell what was
verified. V/COMMAND keeps the state outside every model, so each session (Claude Code, Codex,
OpenCode, a local model, or any CLI with a prompt argument) starts from the same files:

```
brief ─▶ plan ─▶ build/test ─▶ review ─▶ handoff.md saved ─▶ a trigger wakes the next session
          │          │            │
       any agent  gates judge   can only withhold "done"
```

Every part below works the same for every agent: through the hooks (interactive Claude Code and
Codex) and through the wrapper (`vcmd agent`, `vcmd loop`, `vcmd queue`, `vcmd wake`).

## 1. Operating brief (5 fields)

```bash
vcmd task start "Add password reset" \
  --scope "src/auth/* and its tests" \
  --constraint "no new runtime dependencies" --constraint "do not change the public API" \
  --done "npm test passes and POST /reset returns 200" \
  --leave-behind "handoff.md + a decision note for the token TTL"
vcmd task brief --constraint "keep emails in the existing queue"   # edit later
```

Goal, scope, constraints, done condition and leave-behind go into every context frame and every
agent prompt. Fields you leave out get explicit defaults (for example: done = "all acceptance gates
pass"), so an agent never has to guess what "done" means.

## 2. Leave-behinds

| File (in `.vcommand/`) | Written by | Content |
|---|---|---|
| `handoff.md` | V/COMMAND, after **every** run, hook stop and context compaction | 1 goal · 2 current state · 3 files touched · 4 open issues · 5 next exact step (+ recent decisions) |
| `decisions.md` | `vcmd decide "<decision>" --why "<reason>"`, approvals, the role loop | append-only decision log |
| `todo.md` | `vcmd todo add / done / list`, the dashboard | open items for the next session |
| `plan.md`, `review.md` | `vcmd loop` | the planner's plan, the reviewer's last verdict |
| `runs/<id>.json` + `runs/<id>.patch` | every run | evidence: gate results, cost, `git diff HEAD` of the work tree |

Agents are told to record decisions and to-dos themselves (`vcmd` is on their `PATH` and
`VCOMMAND_ROOT` points to the project). The handoff is computed from files and evidence, not from
what an agent says about itself. `vcmd handoff` prints it, `vcmd handoff --out handoff.md` copies
it into the repository if you want it committed.

## 3. Guardrails: ask before deploys, database writes and bulk deletes

Risky shell commands need a human approval:

| Rule | Examples |
|---|---|
| `deploy` | `vercel deploy --prod`, `kubectl apply`, `helm upgrade`, `terraform apply`, `gcloud … deploy` |
| `publish` | `git push`, `npm publish`, `docker push`, `twine upload`, `gh release create` |
| `db-write` | `psql -c "DELETE …"`, `prisma migrate deploy`, `rails db:migrate`, `manage.py migrate`, `redis-cli FLUSHALL` |
| `bulk-delete` | `rm -rf src`, `find … -delete`, `git reset --hard`, `git clean -fd`, `aws s3 rm --recursive` |

Every `&&` / `;` / `|` segment is checked, quotes respected. Segments that only print or record
text (`echo`, `vcmd todo add "…git push…"`, `git commit -m "…"`) are skipped — found in a live
run, where an agent's to-do note mentioning `git push` was flagged. Deleting build output
(`rm -rf node_modules dist build …`) is allowed. Check a command with `vcmd guard -- <command>`.

Enforcement:

* **Interactive Claude Code** (`vcmd hooks install claude`): the `PreToolUse` hook answers `ask`,
  so Claude Code shows its own permission prompt to you.
* **Codex** (`vcmd hooks install codex`) and **every wrapped agent**: the hook answers `deny`
  with an approval id, and the claude-stream guard kills the agent if the command still shows up
  in its stream (backstop for agents without hooks; Codex `command_execution` events are guarded
  the same way). The attempt stops for you (`vcmd agent` exits 3) instead of handing the blocked
  step to the next agent; a queue task is frozen with the question.
* `vcmd approve` lists requests; `vcmd approve apr-xxxxxx` allows **exactly that command** for
  24 hours (and unfreezes its queue task); `--deny` refuses. The dashboard has the same buttons
  under *Needs you*. Every decision is written to `decisions.md`.

Config (`.vcommand/config.json`):

```json
"guardrails": {
  "rules": [{"rule": "payments", "pattern": "\\bstripe\\s+refunds\\b"}],
  "allow": ["^git push origin feature/"],
  "enabled": true
}
```

Measured live with Claude Haiku (`claude -p`, stream-json): asked to run
`git push origin HEAD:main`, the agent was killed at the tool call, the remote was unchanged and
the run waited for approval; after `vcmd approve` the same command ran and the remote received the
commit. Without the forcing instruction, the agent followed the "ask before risky actions" rule
on its own, committed locally and left the push for the developer.

Limits: this is pattern matching on shell commands, not a sandbox. A command built at runtime
(`sh -c "$(curl …)"`), a script file that deploys, or an MCP tool with the same effect is not
recognized. Use the agent's own sandbox and permission settings as well.

## 4. Roles: plan → build/test → review

```bash
vcmd loop --plan claude-opus --build claude --build codex --review codex --rounds 2
```

or once in config, then just `vcmd loop`:

```json
"agents": {
  "claude-opus": {"argv": ["claude", "-p", "--model", "opus", "--output-format", "stream-json",
                            "--verbose", "--permission-mode", "acceptEdits", "{prompt}"],
                  "parser": "claude-stream"}
},
"roles": {"plan": "claude-opus", "build": ["claude", "codex"], "review": "codex", "rounds": 2}
```

* **Planner** — read-only; its answer is saved to `plan.md` and recorded as a decision.
* **Builder(s)** — `vcmd agent` semantics: failover between builders, ledger, budget; the gates
  decide whether the build is verified.
* **Reviewer** — read-only; gets the brief, the plan and `git diff HEAD`, ends with
  `VERDICT: APPROVE` or `VERDICT: CHANGES` + required changes. `CHANGES` sends the work back to the
  builder with those notes (up to `--rounds`). The reviewer can only withhold "done"; it cannot
  mark failing gates as passing. A role that edits files although it is read-only is reported and
  the gates are re-run.

Which model plays which role is your configuration — V/COMMAND does not claim one model is better
at planning. Text roles need an agent with an output parser (`claude-stream`, `claude-json`,
`codex-jsonl`), or the agent can write `VCOMMAND_PLAN.md`.

Live check (Claude Haiku in all three roles, `median()` task with 4 unit tests): plan saved
(2.6 k chars), build verified by the gates on the first attempt ($0.011), reviewer approved on
round 1, handoff and decisions written.

## 5. Wake the next session with events

`vcmd wake [agents] [--loop]` is the one entry point for every trigger. It continues whatever is
pending — runnable queue tasks first, then the active task — writes the handoff, and exits 0 when
there is nothing to do (verified task without a next step, or only approvals waiting).

```bash
vcmd schedule cron claude codex --at 02:00          # prints a crontab line
vcmd schedule systemd claude --at 02:00             # prints a user service + timer
vcmd schedule github claude --loop --write          # .github/workflows/vcommand-wake.yml
```

The GitHub workflow runs on a schedule, by hand, and on a `repository_dispatch` webhook
(`event_type: vcommand-wake`), so CI results, chat bots or other services can wake it. Verified
work is pushed to a new `vcommand/wake-<run id>` branch for review — nothing is merged or deployed —
and `handoff.md`, `decisions.md`, `todo.md` and the evidence are uploaded as a build artifact.
Nothing is installed silently: templates are printed unless you pass `--write`.

## 6. Context rot: checkpoint, then a fresh session

* Every wrapped attempt is already a fresh process with the frame as its prompt.
* For interactive sessions, the `PreCompact` hook writes `handoff.md` before the context is
  summarized, and `SessionStart` (startup, resume, `/clear`, compaction) injects the handoff and
  the frame. When a session drifts, end it and start a new one: nothing is lost.
* `vcmd handoff --write` makes a checkpoint by hand.

## 7. Worktrees, not chaos: one isolated workspace per live session

```bash
vcmd worktree new arch --goal "Design the session bridge"   # ../<repo>-arch on branch vcmd/arch
vcmd worktree new ui                                          # ../<repo>-ui   on branch vcmd/ui
cd ../<repo>-arch && claude          # one session per worktree (or codex)
vcmd worktree list                   # branches and changed files
vcmd worktree conflicts              # files changed in more than one worktree (exit 1 if any)
vcmd worktree rm ui                  # refuses while there are uncommitted changes (--force)
```

Each worktree gets its own V/COMMAND state (same checks, agents and guardrails; its own task,
brief and ledger) and the agent hooks. Sessions, messages, approvals and channels stay shared in
the main repository. When a session edits a file another worktree already changed, the
`PostToolUse` hook tells it right away (once per file) — parallel work only stays clean when files
stop colliding.

## 8. Sessions can talk

```bash
vcmd sessions                                   # name, agent, active/idle/ended, branch, unread messages
vcmd msg send ui "Auth flow updated. Please review the refresh logic."
vcmd msg send all "Freeze merges for 10 minutes"
vcmd msg send developer "Need a decision on the schema"   # goes to your channels (phone)
vcmd msg list
```

Hooked sessions register themselves (worktree name, otherwise `<agent>-<id>`). A message reaches a
live session after its next tool call (`PostToolUse`), with the next prompt (`UserPromptSubmit`),
at `SessionStart`, or at `Stop` (the stop is held once so the session can act on it). Wrapped agents
get messages for them in their next prompt. Agents send messages themselves with the same command.

Live check (Claude Haiku, Claude Code 2.1.316, hooks installed in a worktree): a message queued
before the session started arrived at `SessionStart`; a message sent 12 s into the session arrived
through a later hook while the agent was working; the session showed up as `arch` and was marked
`ended` by `SessionEnd`.

## 9. Continue, resume, fork

The default stays a **fresh session per attempt** (no context rot; state comes from the frame and
the handoff). When full context matters:

```bash
vcmd agent claude --continue           # continue this agent's last recorded session
vcmd agent claude --resume <id>        # a specific session (ids are in the evidence: agent_session)
vcmd agent claude --fork               # branch from the last session without changing it (Claude Code)
```

Claude Code uses `--resume` (`--fork-session` for forks); Codex uses `codex exec resume <id>`
(no fork); other agents can declare `"resume"` / `"fork"` argv templates with `{session}`.
Messages are for lightweight updates; resume when the full conversation matters.

Live check (Claude Haiku): a secret word given only in the first attempt's instruction was written
correctly by the `--continue` attempt; a fresh attempt answered `UNKNOWN`. Found and fixed in that
run: launched agents inherited the parent Claude Code session id (`CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_REMOTE_SESSION_ID`) and wrote into the parent's session environment; V/COMMAND now
strips them, so every agent gets its own session.

## 10. One job per model

```bash
vcmd roles set plan claude-opus          # presets: claude-opus, claude-sonnet, claude-haiku (Claude Code aliases)
vcmd roles set build claude-sonnet codex
vcmd roles set review codex
vcmd roles set hard claude-opus          # any role name works
vcmd roles set chore claude-haiku        # do not burn the best reasoning model on chores
vcmd queue add "Design the session bridge" --role hard
vcmd queue add "Rename the config keys" --role chore
vcmd agent --role build
```

`vcmd loop` uses `plan` / `build` / `review`; queue tasks with `--role` run with that role's agents.
The assignment is yours: V/COMMAND does not claim which model is best at what.

## 11. Reach the developer anywhere, steer from anywhere

```bash
vcmd secret set TELEGRAM_BOT_TOKEN                 # from @BotFather; never passed to agents
vcmd channel add telegram --chat 123456789         # your chat id with the bot
vcmd secret set SLACK_WEBHOOK_URL && vcmd channel add slack
vcmd channel add ntfy --topic vcmd-7f3k2-myproject # ntfy.sh or self-hosted; the topic is the password
vcmd channel add webhook --secret MY_HOOK_URL      # Discord, Teams, n8n, your service
vcmd channel test
```

Notifications: approval needed (with `/approve <id>`), task frozen with its question, verified,
failed, context rotation, and `vcmd msg send developer`. Limit a channel with `--event approval`.

Remote control without a public endpoint (Telegram long polling; only the configured chat ids are
obeyed, everything else is ignored and logged):

```bash
vcmd remote telegram
# in Telegram: /status  /approvals  /approve apr-…  /deny apr-…  /queue <goal>
#              /answer q-… <decision>  /sessions  /msg <session|all> <text>  /todo <text>  /wake [agents]  /handoff
```

Keep it running without a terminal session of yours:

```bash
vcmd autopilot claude codex --every 30m --remote   # wake every 30 min + Telegram commands, until Ctrl+C
```

Each cycle runs `vcmd wake` (queue first, then the active task); a failing or frozen cycle is sent
to your channels and the pilot keeps going. Run it under `tmux`, `systemd` (see `vcmd schedule
systemd`) or on a small server. Channel tokens (`TELEGRAM_BOT_TOKEN`, `SLACK_WEBHOOK_URL`) are never
put in an agent's environment — an agent that could read them could approve its own risky commands.

Tested with a local fake Telegram API (approval message, `/approve` from the allowed chat, a
stranger's `/approve` ignored, `/queue`, offset handling). Not tested against the real Telegram,
Slack or ntfy services from this environment.

## 12. Bring your own keys — V/COMMAND ships none

V/COMMAND has no account, no proxy, no hosted bot and no API keys of its own, and it sends nothing to
us. Every key and token is yours, stored in your OS secret store (`vcmd secret`, or the dashboard),
and used only from your machine. The only hosts it contacts are the ones you configure: your agent's
own provider (through the agent CLI), your Telegram bot, your Slack webhook, your ntfy server.

```bash
vcmd connect telegram          # paste YOUR bot token (from @BotFather); message the bot once; chat id is found for you
vcmd connect slack             # YOUR incoming-webhook URL
vcmd connect ntfy              # a random topic on ntfy.sh, or --server https://your-ntfy.example
vcmd connect webhook MY_HOOK   # any HTTPS endpoint (Discord, Teams, n8n, your service)
vcmd connect agent mine --key MY_PROVIDER_KEY --env MY_BASE_URL=https://gateway.example/v1 \
     --parser claude-stream -- my-cli run "{prompt}"
```

`connect agent` registers any CLI with **its own** key: the agent receives only the secrets named in
its `"secrets"` list (plus its `"env"` variables, e.g. a base URL), never the keys of your other
providers. Agents without a `"secrets"` list keep the old behaviour (every stored key except channel
credentials). Values are read hidden (or from stdin), never printed, never written to the config or
to evidence — the config holds only names.

## Start smaller

One focused task, a five-field brief, the gates that define done, the hooks installed, and a
handoff you read the next morning. Add the loop, the queue and the triggers when the single session
works.
