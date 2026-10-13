# Safety boundaries and release gates

Grid is a local coding assistant with guardrails, not a secure execution sandbox.
Do not expose its local API or give an untrusted project access to a machine
containing valuable credentials. Repository code, package installers and test
commands can execute with the permissions and network access of the Grid process.

## Implemented protections

- A shared abuse policy applies to agent and quick replies. Explicit harmful
  requests and proposed tool payloads are checked locally. A blocked payload
  cannot be waived with an ordinary tool approval.
- Rule floors flag wrapped Git mutations, inline interpreters and command
  substitution. Unknown actions cannot execute unattended. RED categories retain
  their existing approval requirements.
- One cooperating writer holds a project lock across a task. Editor saves from
  the UI compare content versions before writing; external editors can still race
  between that comparison and the write.
- Verification stops its process group on cancellation or timeout. Reported
  failures and all-skipped test summaries cannot become success. The existing
  check command is selected before the task can edit instructions. Changes that
  remove assertions or introduce skips need human review.
- “Checks passed” reports the observed command result. It is not a claim of
  product correctness, complete coverage, security or harmlessness.

## What remains before use by untrusted users

1. **Confinement:** run every tool, package install and check in an isolated
   workspace with a read-only base, no host secrets and denied-by-default network
   access. Enforce paths and resource limits at the OS boundary.
2. **Semantic abuse detection:** the current local patterns recognize a limited
   set of explicit English requests. They can be evaded with paraphrases,
   languages, encoded payloads or multi-turn decomposition, and can incorrectly
   flag quoted examples. Add an independent policy service before task/tool
   execution with fail-closed behavior and documented appeals.
3. **Adversarial evaluation:** test prompt injection through repositories,
   plugins, websites and tool output, unsafe partial tasks, policy evasion,
   secret exfiltration, false positives and benign security research. Maintain
   reproducible release thresholds instead of relying on policy text alone.
4. **Trusted verification:** freeze or separately store baseline tests and runner
   configuration. The current diff heuristic does not catch every way to weaken
   tests, fake their output or alter dependencies and test discovery.
5. **Operational controls:** add authenticated user roles for hosted use, spending
   limits, abuse reporting, privacy-aware audit records, signed releases and a
   secure update channel. Have a documented incident and revocation process.

Approvals authorize a specific operation; they do not override the abuse policy.
No product can promise that nobody will misuse it. Release claims should match
the tested protections and remaining limitations above.


## Restricted prerelease mode

A container-backed mode and independent policy-service gate have now been added.
They are explicitly enabled with `GRID_RESTRICTED=1`; trusted-host mode remains
available and the UI identifies it. Restricted mode has no host execution fallback.
See [the release procedures](docs/release/RELEASE.md) for setup, evidence and
remaining limits. The reference local classifier matched eight smoke cases; this
is not a claim of complete policy coverage. The release gates above remain
applicable to public use until independently reviewed.
