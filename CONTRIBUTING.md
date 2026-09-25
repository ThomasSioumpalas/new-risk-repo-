# Contributing to Sextant

Thank you for your interest in improving Sextant. This document covers local
setup, the quality gates every change must pass, and the conventions used in
this repository.

## Development setup

Sextant uses [uv](https://docs.astral.sh/uv/) for dependency management and
requires Python 3.12+.

```bash
uv sync --locked      # install project + dev dependencies from the lockfile
```

This creates a `.venv` and installs everything pinned in `uv.lock`. Do not run
`uv add` or `uv lock` casually — the lockfile is part of the reproducibility
guarantee described in the project plan. If a dependency genuinely needs to
change, update `pyproject.toml` deliberately and regenerate the lock in its
own commit, with the reason in the commit message.

## Quality gates

These are exactly the checks CI runs (`.github/workflows/ci.yml`). Run them
locally before opening a pull request — `make check` covers lint, type-check
and tests in one go.

```bash
uv run ruff check .                                             # lint
uv run ruff format --check .                                    # formatting
uv run mypy src                                                 # static types (strict)
uv run pytest --cov=sextant --cov-report=term --cov-report=xml  # tests + coverage
```

Dependency vulnerability audit (also run in CI, in its own job):

```bash
uv export --frozen --no-dev --no-hashes --format requirements-txt > /tmp/req.txt
uv run pip-audit -r /tmp/req.txt --strict
```

[pre-commit](https://pre-commit.com/) hooks are provided
(`.pre-commit-config.yaml`) to catch most of this before you even commit:

```bash
uv run pre-commit install
```

## Branch and commit conventions

- Branch from `main`; use short, descriptive branch names
  (`feat/loss-exceedance-curve`, `fix/beta-binomial-edge-case`).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `<type>(<optional scope>): <summary>`, for example:
  - `feat(engine): add expected-shortfall allocation to portfolio module`
  - `fix(api): reject negative trial counts in simulation requests`
  - `docs(security): document the audit hash-chain limitations`
  - Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`.
- Keep commits focused; prefer several small, reviewable commits over one
  large one.

## Adding a compliance framework catalog

Catalogs live as YAML under `src/sextant/compliance/catalogs/`. Because ISO
standards are copyrighted, and public-domain sources (NIST, EU legislation)
are not, catalog content must respect the following:

- **No normative ISO/IEC text.** For ISO-derived catalogs (e.g. 27001 Annex A),
  only the official control **identifiers** may be reproduced, together with a
  short topic label written for this project — never the standard's own
  clause or control wording.
- **Public-domain text is fine as-is**, for example NIST CSF 2.0, NIST SP
  800-30/-37 taxonomies, NIST AI RMF, and EU legislation such as the NIS2
  Directive.
- Every catalog file must include `source` (where the identifiers/taxonomy
  come from) and `license` (or copyright status) fields at the top level, so
  provenance is auditable without opening an external reference.
- Load catalogs with `yaml.safe_load` only (see [SECURITY.md](SECURITY.md));
  never introduce `yaml.load` or any other deserializer for catalog data.

## Changing the risk methodology

The methodology (scales, matrix, appetite, acceptance authority, review
cycles) is versioned YAML, not hard-coded constants
(`src/sextant/domain/methodology.py` and
`src/sextant/domain/default_methodology.yaml`).

- **Bump the methodology version** whenever you change criteria that affect
  how a risk is evaluated or accepted (scales, matrix bands, appetite,
  authority ranks, review cadence).
- **Never edit a methodology version that is already referenced by a
  finalised assessment.** Every assessment records the methodology version
  and its SHA-256 fingerprint it was evaluated against; mutating that version
  after the fact breaks reproducibility and the audit trail. Instead, create
  a new version and let new assessments adopt it.

## Changing the engine

The risk engine (`src/sextant/engine/`) is a pure library: no I/O, no
framework imports, deterministic for a given seed.

- **Bump `ENGINE_VERSION`** in `src/sextant/__init__.py` for any change that
  can alter the numerical output for the same inputs and seed (a new
  distribution fit, a changed simulation algorithm, a different random-number
  consumption order, and so on). `ENGINE_VERSION` is stored with every
  assessment so a result can always be tied to the exact model that produced
  it.
- **Add or adjust statistical validation tests** in `tests/validation` for
  any change to a distribution, Bayesian update, or simulation routine —
  these compare the implementation against closed-form results or known
  reference values, not just "does it run".
- Changes that do not affect numerical output (refactors, performance,
  logging) do not require an `ENGINE_VERSION` bump, but should say so in the
  PR description.

## Test layout

| Directory | Contents |
|---|---|
| `tests/unit` | Pure functions and schema validation; fast, no I/O. |
| `tests/validation` | Statistical validation against closed-form mathematics and known reference values. Mark heavy simulations `@pytest.mark.slow` so `make test-fast` (`pytest -m "not slow"`) can skip them. |
| `tests/integration` | API + database, end-to-end lifecycle and audit-trail behaviour. |

## Pull request checklist

- [ ] `make check` (lint, type-check, tests) passes locally.
- [ ] New/changed behaviour has tests in the appropriate layer (see above).
- [ ] If numerical output could change for the same inputs and seed,
      `ENGINE_VERSION` is bumped and validation tests updated.
- [ ] If methodology criteria changed, a new methodology version was created
      rather than an existing one edited in place.
- [ ] New catalog content includes `source`/`license` fields and reproduces no
      normative ISO text.
- [ ] Documentation (`docs/`, this file, `SECURITY.md`) updated if behaviour
      or security posture changed.
- [ ] No secrets, real personal data, or non-synthetic figures introduced.
