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
