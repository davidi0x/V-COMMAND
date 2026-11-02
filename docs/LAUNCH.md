# Open-source launch & branding guide

## Identity

**Name:** V/COMMAND (subject to trademark clearance)
**CLI:** `vcmd` (check command/package availability before distribution)
**Symbol:** `V/` — simple enough for 16×16 icon, terminal prompt and product thumbnail.
**Tagline:** `Mission control for AI coding agents.` (one line to repeat: "Approve the plan and the cost range before anything runs.")
**Product promise:** `Done ≠ Verified.`

Brand intent: dependable development instrument, not a generic glowing AI dashboard.

- Base: terminal charcoal / off-white; one controlled signal color.
- Type: high-quality neutral sans for brand, monospaced for code.
- Tone: concise, exact, respectful. Avoid marketing percentages without benchmark data.
- UI motif: a compact, crisp line of execution states: RUN / VERIFY / EVIDENCE.
- Hero: real terminal capture with check failure then success. No fictitious API billing numbers.

## GitHub setup

Repository name suggestion: `vcommand` (GitHub repo names cannot contain `/`).

Description: `Terminal-first evidence and quality control for AI coding agents. Run. Verify. Prove. MIT-licensed.`

Topics: `coding-agents`, `developer-tools`, `terminal`, `cli`, `open-source`, `ai`, `verification`, `quality`.

Settings recommended: Issues enabled; Discussions enabled; branch protection requiring CI; Dependabot where relevant; Security Advisories; CODEOWNERS when team grows.

## First compelling demo storyboard (15–20 seconds)

0–3s: existing agent prints task finished.
3–6s: V/ VERIFY: one configured test fails; status FAILED_VERIFICATION.
6–11s: developer fixes test case or reruns coding agent (do not pretend automatic repair in alpha).
11–15s: V/ VERIFY: checks pass; evidence file written; show `vcmd evidence --json`.
15–20s: `V/COMMAND — Done isn't verified.` / `github.com/<owner>/vcommand` after publication.

## Distribution

- GitHub README with animated terminal recording and clear install.
- Product Hunt: open-source CLI, GitHub-first listing with honest capabilities.
- Hacker News `Show HN`, Reddit communities where project sharing is allowed.
- Developer demos on X/YouTube Shorts with screen capture, not slide decks.
- One-command install only after signed artifacts and release process exist.

## License & sustainability

MIT core forever free; donations/sponsorships optional. Users bring their own agent and model accounts. Paid API charges remain external, and are not hidden under "free" marketing.


## Launch plan (Product Hunt / Show HN) — what must be true first

Do not launch before these are done; a launch is one shot and visitors judge the first minute.

1. **One-line install that works.** Today: `pipx install git+https://github.com/davidi0x/V-COMMAND`. Publish to PyPI
   (`vcommand-cli`) and check the name before the day; add Homebrew only if there is demand.
2. **A 60-second demo, real, no slides:** one sentence → brief and questions → drag the sliders, watch the plan
   and the cost range change → approve → steps run, gates pass → report with estimate vs actual. Record from the
   dashboard Mission tab with a real agent; show a failure and a recovery too.
3. **Proof, including the unflattering parts.** Publish `benchmarks/results/*` as they are: the frame lifted
   Sonnet 65% → 95% on vague10, did nothing for Haiku, the enhancer did not beat the frame. Honesty is the brand;
   investors and developers check.
4. **Early users before the day:** 20–50 developers who ran a real mission, with their honest comments. Ask for
   feedback, never for votes. Do not buy or trade upvotes (it gets listings removed and is visible to investors).
5. **Listing:** name, the one-line tagline, 3–4 screenshots (Mission, plan with questions, report, dark mode),
   GIF, first comment with the story ("why I built it", the numbers, what it does not do), maker available all
   day. Tuesday–Thursday, 00:01 Pacific. Same week: Show HN with the honest benchmark as the hook.
6. **Metrics to track (and show to investors):** weekly active projects, missions approved per week, share of
   missions that finish with all gates passing, **cost per verified task** by model mix, retention after week 1.

## Business model (core stays MIT and free; users keep their own keys)

Paid layers for teams, never for the local core: shared run history / estimator and approvals with audit log
and SSO; hosted wake-ups ("autopilot" without your own server); organization policies (who may approve deploys,
database writes); optional, anonymized, opt-in community estimates. The data asset worth building is
**cost per verified task by model mix on real repositories** — published openly, never invented.
