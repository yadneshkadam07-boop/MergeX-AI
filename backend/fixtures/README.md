# Analysis fixtures

Small, self-contained sample projects used as test input for the analysis
engine. Each fixture has **deliberately seeded defects** and a manifest listing
the rule IDs that must fire, so detection is asserted, not eyeballed.

Created in Phase 3:

| Fixture | Seeded defects |
| --- | --- |
| `react_fastapi_mismatch/` | frontend calls an endpoint the backend never defines; HTTP method mismatch; path typo |
| `express_prisma_drift/` | ORM model fields absent from the SQL migration; query on a dropped column |
| `insecure_vite_app/` | hardcoded API key, committed `.env`, CORS wildcard, vulnerable dependency |

Fixture code is *input data*, never executed: it is excluded from linting,
type-checking and coverage.
