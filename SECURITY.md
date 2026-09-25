# Security Policy

## Supported versions

Sextant is pre-1.0 (`0.x`). Only the `main` branch is supported; there are no
maintained release branches yet. Security fixes land on `main` and are called
out in the changelog when one exists.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a suspected security
vulnerability.

Instead, use GitHub's private vulnerability reporting for this repository
(Security tab → "Report a vulnerability"), which opens a private advisory
visible only to the maintainer and you. If that is not available, use
GitHub's [private security advisories](https://docs.github.com/en/code-security/security-advisories)
feature directly against this repository.

Please include:

- A description of the issue and its potential impact.
- Steps to reproduce, or a minimal proof of concept.
- The version/commit you tested against.

There is no formal SLA at this stage of the project, but reports will be
acknowledged and triaged as promptly as possible, and credited in the
resulting advisory unless you ask otherwise.

## Security design

This section summarises the security-relevant design decisions. It is a
summary, not the full threat model; see `docs/PROJECT_PLAN.md` §14 for
context.

- **API keys.** Keys are generated as random 256-bit values. Only a SHA-256
  hash of a key is stored; the raw key is shown once, at creation time.
  Verification uses a constant-time comparison to avoid timing side-channels.
- **Role-based access control (RBAC).** Roles are `viewer`, `auditor`,
  `analyst`, `control_owner`, `risk_owner`, `risk_manager`, `executive`, and
  `admin`. Authorisation is enforced per endpoint. Notably, `admin` carries
  **no risk-acceptance authority** — administrative/technical privilege is
  kept separate from the business accountability of accepting a risk.
- **Segregation of duties (SoD).** The person who assessed a risk cannot also
  be the one who accepts it; acceptance additionally requires an authority
  rank appropriate to the risk level (`risk_owner` < `risk_manager` <
  `executive`).
- **Audit log.** Append-only and enforced at the database level with
  triggers, and hash-chained (each entry commits to the hash of the previous
  one) so that tampering is *evident*. This makes the log **tamper-evident,
  not tamper-proof**: a party with direct database access could in principle
  rewrite the chain consistently. External anchoring (e.g. periodically
  publishing chain heads outside the system of record) is recommended for
  stronger guarantees and is not implemented yet (see Known limitations).
- **Evidence integrity.** Evidence records carry a SHA-256 digest of their
  content. Sextant does not host a file store; evidence files themselves
  remain in the organisation's own system of record, referenced by digest and
  metadata.
- **Input validation and resource limits.** All API payloads are validated
  with Pydantic. Monte Carlo simulation size is bounded by
  `SEXTANT_API_MAX_TRIALS` to guard against resource-exhaustion via
  oversized simulation requests.
- **No unsafe deserialization.** YAML is only ever read with
  `yaml.safe_load`. No `pickle`, and no `eval`/`exec` on external input.
- **Secrets.** Read only from the environment (`SEXTANT_*` variables). None
  are committed to the repository; `.env` is git-ignored (see
  `.env.example`).
- **Container hardening.** The Docker image runs as a non-root user
  (`sextant`, uid 10001); `docker-compose.yml` additionally runs the API
  container with a read-only root filesystem, `no-new-privileges`, and all
  Linux capabilities dropped.
- **CI security checks.** Every push/PR runs `pip-audit` against the locked
  dependency set, and `ruff` with the bandit-derived `S` rule set as part of
  linting.
- **Data.** All data shipped in this repository (`examples/`) is synthetic
  and describes a fictional organisation. No personal data is stored in the
  repository.

## Known limitations

- No SSO/OIDC integration yet; authentication is API-key based only.
- No built-in rate limiting. Deploy Sextant behind a reverse proxy or API
  gateway that provides it.
- No multi-tenancy: one deployment serves one organisation's register.
- The audit hash chain is not externally anchored (see above).
- No evidence file storage; only digests and metadata are recorded, and
  evidence files stay in the organisation's own system of record.
