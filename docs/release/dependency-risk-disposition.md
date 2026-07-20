# Dependency Risk Disposition

How dependency vulnerabilities are detected, triaged, and dispositioned for the
release candidate.

## Scanning

- **Python:** `pip-audit` runs in CI against the resolved environment on every
  push and pull request, querying the PyPI Advisory Database and OSV. The step
  runs with `--strict` (advisories with no fix are still reported).
- **Frontend:** `npm audit` against `frontend/package-lock.json` (run alongside
  the frontend CI job).
- **SBOM:** a CycloneDX SBOM is generated each CI run for the full transitive
  closure, so scans operate on exactly what is installed.

## Disposition policy

Each finding is assigned one disposition:

| Disposition | Meaning | Release gate |
|---|---|---|
| FIX | upgrade to a patched version | required before release for critical/high |
| MITIGATED | not reachable from desk code paths; documented rationale | allowed with note |
| ACCEPTED | low/medium residual with no fix; time-boxed re-review | allowed with note |
| BLOCKING | critical/high reachable with no mitigation | blocks release |

Release gate M18 requires **zero unresolved critical or high-severity findings**.
Reachability is judged against the desk's actual imports — a vulnerability in a
transitive package that the desk never calls is MITIGATED with the reason
recorded here.

## Current disposition

At the time of writing, the runtime dependency set
(`software-bill-of-materials.md`) is on current stable releases with permissive
licenses. Any advisory surfaced by the CI `pip-audit` / `npm audit` steps is
recorded in the table below with its disposition before release sign-off.

| Advisory | Package | Severity | Disposition | Rationale / re-review date |
|---|---|---|---|---|
| _(none accepted at RC cut)_ | — | — | — | populated from CI scan output at sign-off |

## Accepted residual warnings

Non-vulnerability advisories that are deliberately not actioned (e.g. deprecation
notices) are listed here with rationale, so a green scan is never achieved by
suppressing signal silently:

- `StarletteDeprecationWarning` (httpx test client): cosmetic test-time warning;
  no runtime impact; tracked for the next FastAPI/Starlette bump.
