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

## Start smaller

One focused task, a five-field brief, the gates that define done, the hooks installed, and a
handoff you read the next morning. Add the loop, the queue and the triggers when the single session
works.
