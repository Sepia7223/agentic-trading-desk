# Software Bill of Materials

Direct runtime and development dependencies of the IG Demo trading desk. Resolved
versions are the toolchain the release candidate was built and tested against; CI
also generates a machine-readable CycloneDX SBOM (`sbom.json`) on every run for
the full transitive closure.

## Runtime dependencies

| Package | Constraint | Resolved | License | Purpose |
|---|---|---|---|---|
| fastapi | >=0.115 | 0.139.2 | MIT | GET-only Operations Center API |
| httpx | >=0.27 | 0.28.1 | BSD-3-Clause | IG Demo HTTP client (read + governed mutation) |
| hmmlearn | >=0.3.2 | 0.3.3 | BSD-3-Clause | regime hidden-Markov model |
| numpy | >=1.26 | 2.2.6 | BSD-3-Clause | numeric core |
| pandas | >=2.2 | 2.3.3 | BSD-3-Clause | bar/series handling |
| pyarrow | >=15.0 | 23.0.1 | Apache-2.0 | columnar dataset IO |
| pydantic | >=2.7 | 2.13.4 | MIT | frozen contracts and validation |
| scikit-learn | >=1.4 | 1.9.0 | BSD-3-Clause | feature/statistics utilities |
| scipy | >=1.11 | 1.16.3 | BSD-3-Clause | scientific routines |
| uvicorn | >=0.30 | 0.51.0 | BSD-3-Clause | ASGI server for the Operations API |

## Development / CI dependencies

| Package | Constraint | Purpose |
|---|---|---|
| mypy | >=1.10 | static typing (`check_untyped_defs=true`) |
| pytest | >=8.2 | test runner |
| ruff | >=0.5 | format + lint |
| pip-audit | >=2.7 | dependency vulnerability scan |

## Frontend

The frontend toolchain and its transitive dependencies are pinned in
`frontend/package-lock.json`; `npm ci` installs exactly that lockfile in CI.

## Provenance and integrity

- All licenses above are permissive (MIT / BSD / Apache-2.0); no copyleft runtime
  dependency is present.
- Python dependencies resolve from PyPI; the frontend from the npm registry.
- CI regenerates the CycloneDX SBOM each run so this document and the machine
  artifact cannot silently drift from the installed environment.
