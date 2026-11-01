# Security policy

This is a pre-release developer tool. Run `vcmd run` and `vcmd check add` only with commands you trust. They execute with your current user's privileges; this tool is NOT a sandbox and does NOT prevent network access. In `offline` mode, only the preference is stored. Do not mistake this for isolation.

The application stores local metadata in `.vcommand/runs`. By default it does not capture command stdout/stderr, API keys or environment variables. However, argv (including accidental secrets passed as CLI arguments), project paths in Git status and verification commands ARE stored. Avoid putting credentials in commands and review reports before sharing.

No automatic uploads or telemetry in this release.

Please report security issues privately to the repository maintainer instead of opening a public issue containing exploits or secrets. A dedicated reporting address will be published after repository creation.
