# Competitive context (checked 2026-11-01)

| Existing project | Already strong at | Why V/COMMAND exists alongside it |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode) | Open-source multi-model coding agent in terminal; desktop app | V/ is not another coding agent. It provides common verification / evidence across multiple agents. |
| [Codex CLI](https://github.com/openai/codex) | Terminal-based coding agent, project tools and IDE support | V/ wraps a trusted command to run user-configured independent checks and issue a local report. |
| [LiteLLM](https://github.com/BerriAI/litellm) | Provider-independent model routing, spend tracking and policy | Routing and cost control are not original by themselves. V/ aims at verified *task outcomes*, with preflight budget checks only after adapters exist. |
| Claude Code / IDE assistants | Agentic coding, tests, hooks and automation | V/ offers a provider-neutral evidence contract and interface, not a replacement for those tools. |

**Claim we can defend:** The alpha delivers local post-run check evidence without provider lock-in or cloud onboarding.

**Claims we cannot defend yet:** "better models at 20% lower cost", "zero bugs", "equal quality after every switch", "offline enforced" or "cryptographically audited".

Positioning hypothesis to validate in user interviews: a common evidence record and trustworthy failure state are worth having across agent tools, even if each individual agent already offers testing features.


## Update: agent command centers and routers (checked November 2026)

* **Devin Desktop** (the former Windsurf; [devin.ai/desktop](https://devin.ai/desktop)): a command center for many
  agents and models (via ACP), "Fusion" pairs a lead model with a cheaper executor, Kanban board of sessions,
  parallel sessions, local and cloud. Its page does not describe showing cost before a run or a planning
  step; third-party reviews describe billing (credits / quotas / ACUs) as hard to follow. A full IDE and a
  hosted product, tied to its own plans.
* **Routers / gateways** (OpenRouter, LiteLLM-style proxies): route API calls between models; they see
  requests, not tasks, steps, checks or a working tree.
* **Vendor CLIs** (Claude Code, Codex): excellent single-vendor agents; sub-agent model settings exist but
  there is no cross-vendor plan, budget or approval layer.

What V/COMMAND does that none of these is documented to do: a **plan you approve with a cost range computed from
your own history before anything runs**, sliders for who does how much across vendors, a **hard budget**, and
**your checks** (not the agent's report) deciding "done" — local, free, on your keys.

Honest risks: a large vendor can add a cost preview or a plan step in a quarter; the enhancer measured no
pass-rate gain over the context frame (see MISSION.md); estimates need history; the benchmark suites are small
and ours. The durable parts are neutrality, the evidence/handoff format, and the user-owned run history.
