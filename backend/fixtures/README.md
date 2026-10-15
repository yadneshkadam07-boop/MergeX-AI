# Analysis fixtures

Small, self-contained sample projects used as test input for the analysis
engine. Each has **deliberately seeded defects** and an `expected_findings.json`
manifest listing the rule IDs that must fire, so detection is asserted rather
than eyeballed.

All three are React + FastAPI, which is the stack MergeX is aimed at and the
one used for the demo. They are also the Phase 2–3 parser and rule-engine
inputs.

| Fixture | Layer under test | Seeded defects |
| --- | --- | --- |
| [`react_fastapi_mismatch/`](react_fastapi_mismatch) | frontend ↔ backend | missing endpoint, path typo, wrong HTTP method, request field-name drift, missing auth header |
| [`react_fastapi_schema_drift/`](react_fastapi_schema_drift) | backend ↔ database | model field absent from the migration, column type mismatch, query on a nonexistent column, missing foreign key, unindexed join column |
| [`react_fastapi_insecure/`](react_fastapi_insecure) | config ↔ deployment | hardcoded secrets (frontend and backend), unauthenticated money-moving routes, wildcard CORS with credentials, committed `.env`, debug mode, five vulnerable dependency pins |

## The point of these fixtures

Each one **parses, type-checks and lints cleanly layer by layer**. A linter, a
type checker and SonarQube all pass. The defects live only in the *seams*
between layers, which is the gap MergeX exists to close. A fixture whose bugs
a single-file tool could find would not be testing anything interesting.

## `expected_findings.json`

```jsonc
{
  "stack":    { /* what the stack detector must conclude  — asserted from Phase 1 */ },
  "findings": [ /* what the rule engine must report       — asserted from Phase 3 */ ],
  "must_not_report": [ /* correct code that must stay quiet */ ]
}
```

Three things to know:

- **`implemented: false`** marks a rule that does not exist yet. It is a
  to-do, not a test failure. Flip it to `true` in the same commit that adds
  the rule.
- **`must_not_report`** matters as much as `findings`. A cross-layer checker
  that cries wolf is useless, so each fixture contains correct code that is
  deliberately *similar* to the broken code — `listUsers` next to the broken
  `getUser`, `Supplier` next to the drifted `Product`.
- **Rule IDs** (`MX-API-001`, `MX-DB-001`, `MX-SEC-001`, `MX-DEP-001`) are the
  contract. The taxonomy is defined in `app/analysis` in Phase 3; these
  manifests were written first, deliberately, so the rules have a target.

## Ground rules

- Fixture code is **input data and is never executed**. It is excluded from
  ruff, black, mypy, pytest collection and coverage (see `pyproject.toml`).
- Application code must never import from this directory.
- Every credential here is **fabricated**. The AWS pair in
  `react_fastapi_insecure/backend/.env` is the example key from Amazon's own
  public documentation. The root `.gitignore` carries an explicit negation so
  that this one `.env` can be committed — "secrets in version control" is a
  defect MergeX detects, so a fixture has to contain one.
- Dependency pins in `react_fastapi_insecure` are chosen because they have
  **published advisories**. Do not "fix" them.
