# MVP definition of done

## v0.1.0-alpha — current package

- [x] Cross-platform Python CLI entry point `vcmd`.
- [x] `vcmd init` is idempotent.
- [x] `vcmd doctor` reports dependencies and honest limitations.
- [x] `vcmd mode` persists preference (no claim of effect beyond that).
- [x] `vcmd check add/list/clear` manages executable argv arrays.
- [x] `vcmd run -- ...` invokes a user-approved executable with timeout.
- [x] Run configured checks and distinguish success / failure / unverified.
- [x] `vcmd evidence [id] --json` produces local machine-readable evidence.
- [x] `vcmd cost` does not count unknown billing as zero.
- [x] Demo executes a synthetic fixture and a real local check.
- [x] Unit tests and cross-platform GitHub Actions workflow prepared.
- [ ] Verify CI on published GitHub repository (not possible until repository exists).
- [ ] Test Windows, macOS and Linux on the actual published release.
- [ ] Publish downloadable release artifacts (wheel / installers).

## Release gate for v0.1 stable

- Ensure the CLI behaves consistently in PowerShell and POSIX shells.
- Harden process timeout behavior for subprocess descendants.
- Add checks to detect unwitting use of shell metacharacters as arguments.
- Add report version migration, safe file permissions and configured retention.
- Add `vcmd check remove` and richer check profiles.
- Record SHA of executable / project revision when safely obtainable.
- Make logging/redaction threat-model explicit and add regression tests.
- Add meaningful integrated test against a real coding agent noninteractive mode.
- Publish benchmark protocol and baseline runs; no fabricated numbers.

## Explicitly NOT alpha

- Autonomous task generation or patching.
- Model proxy, handoff or paid-provider adapters.
- Sandboxing or offline network enforcement.
- Guaranteed API budget cap or usage billing.
- Cryptographically signed audit chain.
- Native cmux/Warp-like terminal emulator.
