# CLAUDE.md

Working notes for AI assistants and new contributors. Read this before changing code.

---

## What MergeX AI is

A **multi-agent software integration & validation platform**. A user imports a GitHub repo
(URL) or uploads a ZIP; MergeX analyses the whole project and reports whether the frontend,
backend and database actually work *together*.

**The differentiator is cross-layer consistency.** SonarQube and Snyk analyse code in
isolation. MergeX compares layers against each other:

- frontend API calls ↔ backend route definitions
- backend ORM models ↔ database schema
- environment/config ↔ deployment requirements

The motivating case is AI-generated projects (Cursor, Copilot, Claude Code, Lovable), which
frequently ship layers that each look fine alone but do not line up.

---

## The one rule that shapes the architecture

> **Deterministic analysis finds issues. The LLM only explains them.**

Tree-sitter, Python's `ast` and the rule engines are the *only* sources of a finding. Gemini
receives findings that already exist and produces prose explanations, severity ranking input
and suggested fixes.

Consequences to respect in every change:

- Every issue carries `detected_by` — a stable rule ID pointing at deterministic code.
- If `GEMINI_API_KEY` is unset, analysis still runs and still reports every issue; only the
  explanation and suggested-fix fields are empty. `/health/ready` reports `not_configured`
  rather than `unavailable` for exactly this reason.
- A PR that makes the LLM the origin of a finding is wrong, regardless of how well it works.

---

## Layout

```
backend/
  app/
    main.py              FastAPI app factory + ASGI entrypoint
    core/                config (pydantic-settings), logging (structlog), security, rate_limit
    api/                 routers; health at the root, resources under /api/v1
    models/              SQLAlchemy 2.0 ORM          [Phase 1]
    schemas/             Pydantic v2 API contracts
    services/
      repo_importer.py   shallow clone / ZIP unpack into the sandbox   [Phase 1]
      stack_detector.py  framework detection from manifests            [Phase 1]
      parsers/           Tree-sitter JS/TS, Python ast, sqlglot        [Phase 2]
      extractors/        parse trees -> comparable facts               [Phase 2]
    agents/              LangGraph workflow + the five agents          [Phase 4]
    analysis/            issue taxonomy, rules, diff engines, scoring  [Phase 3]
  tests/                 pytest
  fixtures/              sample repos with seeded bugs                 [Phase 3]
frontend/
  src/{pages,components,hooks,lib,api}
scripts/dev.ps1          Windows task runner (mirrors the Makefile)
```

---

## Commands

Windows uses `scripts/dev.ps1`; Linux/macOS/CI use the identical `make` targets.

| Task | Windows | Linux / macOS |
| --- | --- | --- |
| Install everything | `.\scripts\dev.ps1 setup` | `make setup` |
| Backend (reload) | `.\scripts\dev.ps1 api` | `make api` |
| Frontend dev server | `.\scripts\dev.ps1 web` | `make web` |
| Full stack in Docker | `.\scripts\dev.ps1 up` | `make up` |
| Lint + types + tests | `.\scripts\dev.ps1 check` | `make check` |
| Auto-format | `.\scripts\dev.ps1 format` | `make format` |
| Tests + coverage | `.\scripts\dev.ps1 test` | `make test` |
| Apply migrations | `.\scripts\dev.ps1 migrate` | `make migrate` |
| New migration | `.\scripts\dev.ps1 migration "add x"` | `make migration m="add x"` |
| Show DB revision | `.\scripts\dev.ps1 db-current` | `make db-current` |

Raw equivalents, if you prefer them:

```bash
# backend (from backend/, venv active)
uvicorn app.main:app --reload --port 8000
pytest --cov=app --cov-report=term-missing
ruff check . && black --check . && mypy

# frontend (from frontend/)
npm run dev          # http://localhost:5173
npm run build        # tsc -b && vite build
npm run lint
```

Useful URLs: API docs <http://localhost:8000/docs>, liveness
<http://localhost:8000/health>, readiness <http://localhost:8000/health/ready>.

---

## Conventions

### Python

- Python 3.11. **Type hints everywhere**; `mypy --strict` must pass.
- `ruff` (lint + import order) and `black` (format), both at line length 100.
- `from __future__ import annotations` at the top of every module.
- **Absolute imports only** (`from app.core.config import Settings`); relative imports are
  banned by lint rule `TID252`.
- Nothing reads `os.environ` directly. Add a field to `Settings` in `app/core/config.py` and
  document it in `.env.example`.
- Public functions get a docstring explaining *why*, not a restatement of the signature.
- Filesystem work on imported repositories goes through `app/core/security.py`
  (`safe_join`, `safe_archive_member_path`). Never `Path.joinpath` a user-supplied name.

### TypeScript

- Strict TS, including `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`.
- `@/` is the alias for `src/` (declared in both `tsconfig.app.json` and `vite.config.ts`).
- Server state lives in TanStack Query, never in `useState`. Query keys come from the
  `*Keys` object in the matching `src/api/*.ts` module.
- `src/components/ui/` is shadcn/ui generated output; it is excluded from lint and Prettier.
  Do not hand-edit it — re-run `npx shadcn@latest add <component>`.
- Severity colours come from the `--severity-*` tokens in `src/index.css`. One severity must
  look identical in the table, the charts and the graph.

### Testing

- `pytest`, with `asyncio_mode = "auto"`.
- Analysis-engine coverage must stay **≥ 70%**.
- Tests never read the developer's `.env`: build a `Settings` object via the
  `settings_factory` fixture and inject it with `dependency_overrides`.
- Detection rules are asserted against fixture repos with seeded bugs, by rule ID. A rule
  without a fixture test does not count as implemented.
- Markers: `integration` (needs Postgres), `network` (real outbound calls), `llm` (needs a
  real API key). Default test runs must pass with none of them available.

### Git

- Conventional commit subjects: `feat:`, `fix:`, `chore:`, `test:`, `docs:`, `refactor:`.
- One meaningful commit per phase, at minimum.
- `pre-commit install` once per clone.

---

## Platform security (we execute nothing, we trust nothing)

Imported repositories are hostile input. Non-negotiables:

1. **Never execute user code.** No `npm install`, no `pip install`, no build, no test run on
   an imported repo. Analysis is static only.
2. Clone/extract into `WORKSPACE_DIR` only, through `safe_archive_member_path` (zip-slip).
3. Enforce `MAX_REPO_SIZE_MB` (100), `MAX_FILE_COUNT` (20 000) and `MAX_UPLOAD_SIZE_MB`
   *before* analysis, and `ANALYSIS_TIMEOUT_SECONDS` during it.
4. Delete the sandbox directory when an analysis finishes, including on failure.
5. Do not follow symlinks out of the sandbox.
6. Secrets stay in env vars. `SecretStr` for every credential; log through
   `mask_secret` / `redact_url_credentials`.
7. Error responses are opaque; stack traces go to logs, never to the client.

---

## Issue schema (stable contract)

`id`, `category` (`api_contract` | `schema` | `security` | `dependency`), `severity`
(`critical` | `high` | `medium` | `low`), `title`, `description`, `file_path`, `line_start`,
`line_end`, `evidence` (code snippet), `expected`, `actual`, `suggested_fix` (LLM),
`confidence`, `detected_by` (rule ID).

**Health score:** start at 100; deduct 15 per critical, 8 per high, 3 per medium, 1 per low;
floor at 0. Per-category sub-scores are computed the same way over that category's issues.

---

## Phase plan

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Monorepo scaffold, docker-compose, lint/format/CI, health endpoint | **done** |
| 1 | DB models, Alembic, project/analysis CRUD, repo importer, stack detector, seeded fixtures | **done** |
| 2 | Tree-sitter parsers + extractors, asserted against all three fixtures | **done** |
| 3 | Rule engines (16 rules), OSV lookup, dedupe, scoring | **done** |
| 4 | LangGraph workflow, Gemini explanations, SSE streaming | **done** |
| 5 | Frontend pages wired to the API | **done** |
| 6 | Architecture graph, polish, README screenshots, deploy configs | **done** |

Explicitly **out of scope** for now (stub only): documentation generation, deployment
readiness check, PR comment bot, VS Code extension.

---

## Decisions

Ambiguities resolved while building, with the reasoning. Append, do not rewrite.

### Phase 0

- **Repo root is the monorepo root.** The brief sketched a `mergex-ai/` wrapper directory;
  the working directory is already the project root, so an extra nesting level would add
  nothing. Paths in the brief map to `backend/`, `frontend/` at the top level.
- **`.env` lives at the repo root, not in `backend/`.** One file configures Postgres,
  the API and the Vite dev server, so docker-compose and the backend read the same source of
  truth. `Settings` reads root `.env` first, then an optional `backend/.env` override.
- **`asyncpg` everywhere, including Alembic.** One driver, so the URL in `.env` works for
  both the app and migrations; Alembic will use an async `env.py` (Phase 1).
- **Windows task runner alongside the Makefile.** `make` is not installed on the primary dev
  machine. `scripts/dev.ps1` mirrors every Makefile target; both must be updated together.
- **Rate limiting is hand-rolled, not `slowapi`.** This was not a preference. Against the
  installed FastAPI (0.143), `include_router` puts one internal `_IncludedRouter` object into
  `app.routes` rather than flattening the routes; `SlowAPIMiddleware` looks for `.endpoint`
  on the matched route, finds none, and **silently exempts every router-included endpoint**
  — verified: 70 requests against a 60/minute limit all returned 200. Its `@limiter.limit`
  decorator path fails differently, returning 500 on the allowed requests. A limiter that
  quietly stops limiting is worse than none, so `app/core/rate_limit.py` implements a fixed
  window per client with explicit tests (`tests/test_core_rate_limit.py`), including the
  router-included case that broke. Known limits: in-process counters (a multi-replica
  deployment needs Redis), and a fixed rather than sliding window, so a client can send up
  to `2 × limit` across a boundary.
- **Health probes and `/docs` are exempt from rate limiting** (`EXEMPT_PATH_PREFIXES`).
  Throttling a health check makes a deployment look unhealthy under load.
- **`TRUST_PROXY_HEADERS` defaults to false.** `X-Forwarded-For` is only honoured when
  explicitly enabled, because on a directly-exposed service a client can forge the header to
  mint a fresh limit bucket per request. Set it to true on Render, where the platform
  overwrites the header.
- **An unusable sandbox directory does not block start-up.** `lifespan` logs the error and
  `/health/ready` reports `workspace: unavailable`, which is more diagnosable than a crash
  loop behind a platform health check.
- **No `manualChunks`.** Rollup 5 (Vite 8) dropped the object form. Recharts and React Flow
  will be kept out of the entry chunk with route-level `React.lazy` in Phase 6 instead.
- **No `baseUrl` in `tsconfig`.** Deprecated in TypeScript 6; `paths` alone resolves
  relative to the config file.
- **Tailwind v4 (CSS-first) with `@tailwindcss/vite`.** No `tailwind.config.js`: tokens are
  declared in `src/index.css` under `@theme inline`, which is what current shadcn/ui expects.
- **Black is the formatter of record.** ~~`ruff-format --check` runs in pre-commit to catch
  disagreement between the two.~~ *Reversed in Phase 2:* black and ruff-format are different
  formatters and legitimately disagree on edge cases (notably annotated assignments with
  long values). A hook that blocks commits whenever the non-authoritative formatter differs
  is incoherent, so it was removed. Black alone formats; ruff alone lints.
- **Frontend has no test runner yet.** Vitest + Testing Library arrive with Phase 5, when
  there are components whose behaviour is worth asserting.

### Phase 1

- **Enums are `VARCHAR` + `CHECK`, not native PG enums** (`native_enum=False`). Adding a
  value to a native enum needs `ALTER TYPE`, which is awkward in a migration, and the issue
  taxonomy will keep growing. It also means the same DDL applies on SQLite, so tests need no
  database service. `values_callable` is mandatory — without it SQLAlchemy persists the
  member *name* (`CRITICAL`) instead of the value (`critical`).
- **UUID primary keys.** An analysis id can then be minted before the row exists (useful for
  the SSE stream URL), and ids are not enumerable.
- **The initial migration is hand-written.** Autogenerating it against SQLite would flatten
  `JSONB` to `JSON` and bake the wrong type into the PostgreSQL migration.
  `tests/test_migrations.py` asserts the migration and the models agree, which is what lets
  the rest of the suite use `create_all` instead of running Alembic per test.
- **Alembic takes its URL from `app.core.config`,** not `alembic.ini`, so migrations and the
  running service can never disagree. A URL already set in the Alembic config wins, which is
  how tests target a throwaway database. `env.py` supports sync *and* async drivers.
- **`DATABASE_URL` is normalised, not validated.** A pasted Supabase string works as-is:
  `postgres://`/`postgresql://` is rewritten to `postgresql+asyncpg://`, and `?sslmode=...`
  becomes asyncpg's `ssl` connect-arg (asyncpg has no `sslmode` kwarg and raises on it).
  `DB_DISABLE_PREPARED_STATEMENTS=true` is required for the pooled Supabase endpoint
  (port 6543, pgbouncer in transaction mode); run migrations against the direct connection.
- **SQLite foreign keys are enabled per connection** via a `PRAGMA foreign_keys=ON` listener.
  SQLite ignores `REFERENCES` by default, so `ON DELETE CASCADE` was silently a no-op and
  the cascade tests were passing without testing anything.
- **Coverage must declare `concurrency = ["thread", "greenlet"]`.** SQLAlchemy's asyncio
  support drives coroutines through greenlets and TestClient runs the app in a portal
  thread; without both, coverage silently misses the body of every async endpoint that
  touches the database. It reported 54% for a router that was in fact 98% covered.
- **Import happens synchronously at project creation.** The size and timeout caps bound it,
  and it makes Phase 1 demonstrable end to end. Phase 4 moves the whole pipeline into a
  background job with SSE progress; the service functions were written to be reusable there.
- **Blocking work is pushed to threads** with `anyio.to_thread.run_sync`: archive
  extraction, tree walking, stack detection and upload writes. At the 100 MB limit these
  would otherwise stall the event loop for seconds, including health probes.
- **ZIP uploads are retained; clones are not.** A ZIP has no origin to re-fetch from, so the
  archive is kept at `WORKSPACE_DIR/uploads/<project_id>.zip` and re-extracted per analysis.
  The filename comes from the project id, never from the user-supplied name.
- **`repo_importer` was split** into `git_client` (hardened subprocess), `archive` (ZIP
  safety) and `repo_importer` (orchestration). The brief listed one module; three are
  independently testable, and the ZIP safety rules deserve their own test file.
- **Only `github.com` is accepted** for imports. That is a security boundary: the URL is
  handed to `git clone`, so an arbitrary host would make the endpoint an SSRF primitive
  against anything the backend can reach.
- **`is_monorepo` requires an explicit workspace declaration.** A `frontend/` + `backend/`
  split is the most common shape MergeX sees and is *not* a monorepo; inferring one from
  "two manifests exist" would mislead the agents about how to pair layers. Layer locations
  are reported separately as `frontend_roots` / `backend_roots`, which Phase 2 uses to
  decide where to look for API calls versus route definitions.
- **One error envelope for every failure:** `{"error": "<code>", "detail": "<text>"}`, with
  `errors[]` added for validation. FastAPI's default bare `{"detail": ...}` would have meant
  two shapes for clients. Note `RequestValidationError.errors()` is *not* JSON-serialisable
  when a field validator raises — Pydantic puts the exception object in `ctx` — which turned
  every such 422 into a 500 until the handler began projecting out only the safe fields.
- **Issues have a DB-level `UNIQUE (analysis_id, fingerprint)`.** Deduplication is an
  invariant, not just something the synthesizer is trusted to do.
- **The three fixtures are all React + FastAPI**, per the brief. That leaves generality
  unproven: a non-Python backend fixture (Express + Prisma) should be added in Phase 2 or 3
  so the extractors are not accidentally FastAPI-specific.
### Phase 2

- **`SourceLocation` carries the snippet, captured at extraction time.** The sandbox is
  deleted when an analysis ends, so evidence looked up later would be looked up against
  nothing. Every extracted item has `file_path` + a 1-based inclusive line range + the text;
  `tests/test_extractors_fixtures.py` asserts this as an invariant over every extractor
  rather than spot-checking.
- **Locations are clamped to the file.** An off-by-one in a parser must not produce a line
  number the file does not have, because that surfaces as a broken evidence snippet in the
  UI rather than as an error anyone notices.
- **`.ts` and `.tsx` are different Tree-sitter grammars, not a flag.** Parsing `.tsx` with
  the TypeScript grammar mangles every JSX element; parsing `.ts` with the TSX grammar reads
  `<T>x` as JSX. The mapping is by extension in `js_ts_parser._SUFFIX_DIALECTS`.
- **Python uses `ast`, not Tree-sitter.** CPython's own parser is exact, carries
  `end_lineno`, and cannot drift from the language. A syntax error is *returned* as
  `SyntaxErrorInfo` rather than raised, so one broken file does not abort a repository.
- **SQL column lines come from sqlglot's token stream.** Its expression tree carries no
  positions. A column name is recognised by *shape* (identifier-like) rather than by token
  type: sqlglot gives `name`, `key`, `order`, `type` and `value` dedicated token types, and
  enumerating the accepted ones silently loses whichever was forgotten — `name` is among the
  most common column names there is.
- **Path parameter *names* are discarded** during normalisation: `/users/{id}`,
  `/users/:id`, `/users/<int:user_id>` and `/users/${id}` all become `/users/{}`. A frontend
  has no obligation to name a parameter the way the backend does, so comparing names would
  produce constant false positives. Position and count are what must match.
- **A numeric literal segment is treated as a parameter.** `/users/5` is the same endpoint
  as `/users/{id}`. That is the conservative call: it prevents a false "missing endpoint".
- **A leading `${...}` in a template is the origin, not a path segment.**
  `` `${API_BASE_URL}/api/users` `` is how nearly every real frontend is written; reading
  the interpolation as a segment normalises it to `/{}/api/users` and mismatches every route
  on the server. A value that is *entirely* an interpolation is marked `is_opaque` instead
  and never compared.
- **FastAPI mount prefixes are resolved across files, through nested `include_router`
  chains.** In the fixtures the routes say `/users` and `main.py` mounts them at `/api`.
  Reporting the unmounted path would make every correct call look like a missing endpoint —
  hundreds of false positives on a working application. A chain that cannot be followed to
  an app sets `mount_prefix_incomplete` and drops confidence, so the rule engine knows not
  to trust the path.
- **`is_monorepo`-style guessing is avoided in route extraction too**: an unresolved mount
  is recorded in `RouteExtraction.unresolved_mounts` rather than assumed to be root.
- **Django reports `method=None`.** It declares paths in `urls.py` and methods in the view.
  Guessing GET would invent method mismatches; "does this endpoint exist" still works
  without the method and catches more.
- **`db_schema` replays migrations in order** rather than reading the latest `CREATE TABLE`.
  A column added in migration 5 and dropped in 9 does not exist.
- **SQL and ORM types both reduce to the same canonical families** (`integer`, `decimal`,
  `string`, …). `NUMERIC(10,2)` vs `INTEGER` is a mismatch; `VARCHAR(64)` vs `VARCHAR(200)`
  is a length difference, which is a different and much weaker finding.
- **`sqlglot`'s `NotNullColumnConstraint` is nullability, not its negation.** One node
  serves both `NULL` and `NOT NULL`; `allow_null` is set for the former and absent for the
  latter. Reading it as a negation marked every `NOT NULL` column nullable.
- **`sql_queries` is a separate extractor** because an ORM prevents referring to a column
  that does not exist and raw SQL does not. A string is SQL when its *shape* says so;
  the executing callee only raises confidence.
- **Blocking extraction runs in a thread** (`anyio.to_thread`), consistent with Phase 1.
- **Timestamps have a Python-side default as well as a server default.** SQLite's
  `CURRENT_TIMESTAMP` is whole seconds, so two rows created in the same second tie and
  "newest first" falls back to comparing random UUIDs — a genuinely flaky ordering that a
  Phase 1 test caught only intermittently. The Python default supplies microseconds on every
  backend. No migration: neither default changes the DDL.
### Phase 3

- **Precision is the governing constraint, not recall.** A false positive on correct code is
  verifiable by the user in seconds, and from then on they disbelieve every other finding.
  Every rule therefore starts from a reason to stay *silent*, and the silence conditions are
  tested as hard as the detections. `must_not_report` in each fixture manifest is asserted
  end to end in `tests/test_analysis_engine.py`.
- **A rule ID is a public contract.** It appears in stored issues, the API, fixture manifests
  and eventually users' CI config, so an ID is never reused or repurposed. Retiring a rule
  means marking it retired.
- **`tests/test_analysis_taxonomy.py` enforces the manifests both ways:** a manifest claiming
  `implemented: true` for an unregistered rule fails, and a registered rule that no manifest
  exercises fails. Both failure modes were verified by deliberately breaking a manifest.
- **Fingerprints identify a root cause, never an occurrence.** They exclude file and line, so
  one typo'd path called from three components merges into one finding with three locations —
  and a finding keeps its identity when surrounding code moves, so it can be recognised
  across runs.
- **Evidence is redacted at construction.** A scanner that finds a hardcoded key and stores
  it verbatim in its own issue table has moved the secret, not reported it — and that table
  is served over an API and rendered in a browser. `make_finding(secrets=...)` masks the
  literals; `test_analysis_engine.py::test_no_finding_leaks_a_secret` asserts no fixture
  credential appears anywhere in any finding.
- **Deductions are per issue, not per occurrence.** Otherwise one typo in a shared helper
  dominates the score, which would make the number describe code structure rather than
  correctness.
- **A category with no issues scores 100, but carries `analysed=False` when there was
  nothing to check.** "No database" and "a perfect database" must not render identically.
- **The engine reports what it could not check.** A skipped category, an unreachable OSV, an
  unresolved mount — each produces a note. "We found nothing" and "we could not look" mean
  very different things to someone reading a score.
- **Absence checks are disabled when absence cannot be proven.** If any router mount could
  not be traced to an application, some route paths are incomplete, so MX-API-001 and
  MX-API-002 are skipped entirely rather than reported with a caveat.
- **MX-API-004 fires only on casing drift**, where the same field exists under the other
  casing. A field the model simply lacks could be many benign things. A Pydantic `alias`,
  `alias_generator` or `extra="allow"` suppresses the rule, because the accepted names can
  then no longer be enumerated.
- **MX-API-005 is suppressed by ambient auth.** An axios instance with a default
  `Authorization` header, or any `interceptors.request` use, means a call with no visible
  credentials may still be authenticated. The check is deliberately coarse: proving an
  interceptor *does* add credentials needs cross-module data flow, and withholding a true
  positive costs less than reporting a false one.
- **MX-SEC-002 reports an inconsistency, never "this route has no auth."** The latter is true
  of every public endpoint in every project. A sensitive route (narrow keyword list — `user`
  and `item` are far too common to carry signal) whose siblings are protected is nearly
  always an oversight. This is what keeps `create_task` quiet next to a protected
  `delete_all_tasks`.
- **Secret detection needs two signals:** a provider prefix (`sk_live_`, `AKIA`, `eyJ`) or a
  credential-shaped name with a high-entropy literal. Entropy alone flags UUIDs, hashes,
  minified bundles and test fixtures. Placeholders, env lookups without a literal default,
  plain URLs and version strings are excluded explicitly.
- **A committed `.env` is one finding, not one per line.** The root cause is that the file is
  tracked, so MX-SEC-001 skips `.env` files and MX-SEC-004 reports the file with every value
  masked and only the *keys* in metadata.
- **Only exactly-pinned dependency versions are checked.** `^1.6.0` resolves to whatever was
  installed; reporting the range's lower bound would flag already-patched projects. Ranges
  are counted and surfaced as a note so the gap is visible.
- **OSV is behind `VulnerabilityClient`**, so tests inject recorded advisories and never
  touch the network. An outage degrades: the report carries `degraded_reason`, the dependency
  check contributes no findings, and every other finding is still reported. One live test
  exists, marked `network` and excluded by default.
- **CVSS vectors are not decoded.** Computing a base score from a vector string is a
  specification unto itself and getting it subtly wrong would mis-rank findings. Severity
  comes from `database_specific.severity` or a numeric score; absent both, the rule default
  is used and the finding says so.
- **Type mismatches require both sides to be *recognised* families.** An unknown type falls
  back to its own lower-cased text, so `MY_CUSTOM_TYPE` against `SomeVendorType` would
  compare unequal and report a mismatch on correct code. Caught by a test.
- **`request_models.py` was added in Phase 3**, not Phase 2: MX-API-004 cannot run without
  the backend model's field names, and there was no earlier consumer for them.

### Phase 4

- **The model cannot change the finding set, structurally.** `apply_explanations` iterates
  over the *findings* and looks each one up by fingerprint. An invented `finding_id` matches
  nothing and is dropped; an omitted one gets a template. This is not a prompt instruction —
  the model's response is never iterated, so it has no way to add, remove or re-rank
  anything. `tests/test_agents_graph.py` runs all three fixtures with the template
  explainer, a well-behaved model and a deliberately hostile one that invents findings,
  drops the first and reverses the rest, and asserts identical fingerprints, severities,
  locations and score across all three.
- **Offline is the product, not a degraded mode.** With no API key `build_explainer` returns
  `TemplateExplainer`, which has a hand-written explanation and a concrete before/after for
  each of the 16 rules, with real file and line references. Gemini improves the prose; it
  does not enable the feature. Every test in the suite except the live one runs this path.
- **Two layers of fallback, because "never fail the analysis" has to survive the fallback
  failing.** Configured explainer → template explainer → empty result. A finding with no
  prose still carries its description, evidence and expected/actual, so the worst outcome
  is plainer wording, never a lost report.
- **Redaction masks by name as well as by shape.** The provider patterns (`sk_live_`,
  `AKIA`, `eyJ`, `SG.`) cannot recognise a bare AWS secret key or a 32-character signing
  key — nothing about the string gives it away. What does is the identifier it is assigned
  to, so `_CREDENTIAL_ASSIGNMENT` masks the value of any `*SECRET*`/`*TOKEN*`/`*KEY*`
  assignment and keeps the name, which is the part the model needs. Over-masking costs a
  little prose quality; under-masking sends a live credential to a third party. The seven
  credentials seeded in the insecure fixture are declared once in `tests/conftest.py`, and
  a guard test fails if the fixture is edited so that they no longer appear in it —
  otherwise a redaction test would search for a string that is not there and pass while
  proving nothing.
- **A rule group that crashes is isolated; extraction that crashes is not.** `_guard`
  catches per-node and records a `GroupError`, so the other two branches finish and the
  report names the failed category — "no security issues" and "the security analysis
  crashed" must never look the same. Extraction feeds all three branches, so its failure is
  a failed analysis, reported as one. Tested by making each rule *engine* raise: patching
  the node itself would remove the guard being tested.
- **Crash-isolation tests need a repository with defects in all three categories.** Each
  seeded fixture deliberately exercises one, so `tests/test_agents_graph.py` merges the
  schema-drift repository with the insecure one's routes and secrets.
- **The event bus keeps a bounded, replayable buffer per analysis.** A reconnecting client
  sends `Last-Event-ID` and receives exactly what it missed; one that connects after the run
  finished gets the whole story and the terminal event rather than a stream that hangs.
  Both success and failure publish a terminal `complete` event, because a stream that simply
  goes quiet is indistinguishable from a slow one.
- **`subscribe` drains its queue before honouring `finished_at`.** An analysis that finishes
  between the replay and the live loop leaves events in the subscriber's queue; returning on
  `finished_at` alone dropped them, the terminal event included. Found by a test, fixed in
  `app/core/events.py`.
- **The create-analysis handler commits explicitly** rather than leaving it to the
  dependency's teardown. The background task opens its own session and must be able to see
  the row; relying on the relative ordering of teardown and background execution is exactly
  the kind of assumption that breaks on a framework upgrade.
- **The bus is in-process.** Correct for a single instance, wrong for multiple replicas: a
  client would connect to a replica that never saw the analysis. Replacing it with Redis
  pub/sub behind the same interface is the deployment prerequisite.
- **Token usage is logged per analysis** (calls, prompt, output, total, and the
  template/model split). An LLM feature with no cost visibility is one nobody can run in
  production.

### Phase 5

- **The frontend has no fixtures of its own.** Every page reads `/report` and `/events`;
  there is no mock mode and no sample report in the bundle. The cost is that the UI cannot
  be opened without a backend, which is the right trade: a dashboard that renders convincing
  invented data is how you ship a dashboard that does not work.
- **`POST /projects/demo` packs the bundled fixture and hands it to the normal upload path.**
  The browser cannot zip a directory inside the backend image, and committing a second copy
  of the fixture as a binary would let the demo drift from what the tests assert. Packing at
  request time means the demo exercises the same import code a real upload does, and editing
  the fixture changes the demo.
- **Live progress and the finished report are separate routes.** `/analyses/:id` streams,
  `/analyses/:id/report` reads. One page that changes shape would make a report impossible
  to link to or reload without re-entering a "watching" state.
- **`Last-Event-ID` is sent as a query parameter.** `EventSource` cannot set headers, which
  is why the backend accepts both. The hook also closes and reopens the stream itself rather
  than letting `EventSource` auto-reconnect: the browser reconnects to the *original* URL, so
  a run that progressed while the tab was offline would replay from the start and the stepper
  would jump backwards.
- **`useAnalysisStream` keeps its factory and backoff schedule in refs.** They were in the
  effect's dependency list, so a caller passing inline options re-created the connection on
  every render. Caught by a test that expected one `EventSource` and found two.
- **Connection state and analysis state are separate.** A dropped stream shows "reconnecting",
  never "analysis failed": the run continues on the server, and claiming otherwise because a
  laptop slept would be a lie about the backend.
- **A table row is not a button.** Giving `<tr role="button">` strips the table semantics a
  screen reader needs; rows get `tabIndex` and a key handler instead and stay rows.
- **Only known stack keys become badges.** The stored stack report also carries `signals`, a
  list of objects, and `languages`, a map. Flat-mapping every array into React children threw
  and blanked the whole report page — found by the screenshot harness, fixed, and pinned by
  `stackBadgesFrom` tests.
- **Three distinguishable "nothing here" states.** Scored-and-clean, not-applicable (nothing
  of that kind in the project) and failed (the group crashed) are rendered differently
  everywhere they appear. Collapsing them is the easiest way for a dashboard to mislead.
- **Screenshots are captured from the real stack** (`frontend/scripts/screenshots.mjs`): a
  throwaway SQLite database, the production build, and real imports. The live-progress shots
  use a real GitHub repository because the bundled fixture finishes in under a second and
  cannot be photographed mid-run; the dashboard shots use the fixture because its findings
  are fixed and the picture is reproducible.

- **mypy is not a pre-commit hook.** It needs the project's dependency set to resolve
  imports, and pre-commit cannot supply that reliably: `language: system` fails because the
  git hook does not put the venv on PATH (on Windows `python` becomes the Microsoft Store
  stub), and `language: python` with a path-plus-extras dependency depends on pip's version.
  `mypy --strict` is enforced by `make check` / `dev.ps1 check` and by CI, which gates PRs.
  A hook that only works in an activated shell is worse than no hook.
- **`black` uses `force-exclude`, not `extend-exclude`.** `extend-exclude` is ignored for
  files passed explicitly on the command line, which is exactly how pre-commit invokes
  black — so fixtures were being reformatted by the hook but not by `black .`. Migrations
  are deliberately *not* excluded: Alembic's post-write hooks format them anyway.
- **`mixed-line-ending` skips `*.ps1`,** because `.gitattributes` mandates CRLF there.
  (Related trap: `pathlib.write_text` on Windows translates `\n` to `\r\n`, so a Python
  script that rewrites a tracked file will introduce CRLF unless it passes `newline="\n"`.)

### Phase 6

- **Interactive Architecture visualizer via React Flow with route-level code splitting.**
  The architecture graph is loaded dynamically (`React.lazy`) to prevent `@xyflow/react` and
  layout dependencies from bloating the initial bundle. Nodes represent services, routes,
  and databases with status-coded borders and metric badges derived from deterministic
  analysis findings.
- **Stateless JWT authentication with demo guest retention.**
  Authentication uses standard Bearer JWTs (`HS256`) with salted password hashing. Unauthenticated
  users can explore bundled demo repositories flagged with `is_demo=True`, which are pruned
  periodically by `demo_cleanup.py` on a retention schedule without interfering with registered
  projects.
- **Deploy Readiness Engine & Checklist.**
  A dedicated analysis pass verifies environment variables against code references, Dockerfiles,
  port configurations, and production manifests, surfacing blocking issues before cloud push.
- **Dual-platform deployment configuration.**
  `render.yaml` orchestrates the Python FastAPI backend, background workers, and PostgreSQL,
  while `frontend/vercel.json` provides client-side SPA routing and security headers for Vercel.

---

## Traps

- `get_settings()` is `lru_cache`d. Changing the environment mid-process has no effect —
  construct `Settings(...)` directly in tests.
- `RateLimitMiddleware` runs **before** routing, so unrouted paths (404s) are counted too.
  That is deliberate — it stops a scanner from spraying unlimited 404s — and it is what
  `tests/test_main.py` uses as a wiring probe while the API surface is health-only.
- Do not reintroduce `slowapi` without re-reading the Decisions entry. Its failure mode is a
  silent 200, so "it seems to work" is not evidence that it does.
- `uvicorn.access` logging is disabled on purpose; the request middleware in `app/main.py`
  emits a richer structured line instead.
- `tsconfig.app.json` and `vite.config.ts` both declare the `@/` alias. Change both.
- `backend/fixtures/` deliberately contains insecure, broken code. It is analysis *input*:
  excluded from ruff, black, mypy and coverage, and never imported by application code. The
  root `.gitignore` has an explicit `!backend/fixtures/**/.env` negation so the one
  deliberately-committed `.env` is trackable.
- A column with a server-side `onupdate` (`updated_at`) is **expired after an UPDATE**.
  Serialising the object then triggers lazy IO and raises `MissingGreenlet`, so a handler
  that mutates a row must `await session.refresh(obj)` before returning it.
- `FastAPI 0.143` does not flatten included routes into `app.routes` — it inserts one
  `_IncludedRouter` per `include_router`. Anything that introspects `app.routes` (as slowapi
  did) will find nothing. Use `app.openapi()["paths"]` to enumerate the API surface.
- Fixture manifests use `"implemented": false` for rules that do not exist yet. Flip it in
  the same commit that adds the rule; it is a to-do marker, not a failing assertion.
- `TestClient` runs `BackgroundTasks` **inline, before returning the response**. A test that
  queues an analysis therefore sees it already finished, which silently defeats the
  concurrency guard in `POST /projects/{id}/analyses`. `tests/test_api_analyses.py` stubs
  `_execute` for that reason; `tests/test_api_report.py` relies on the same behaviour
  deliberately, to run the whole pipeline through the API in one request.
- `sse_starlette` caches its shutdown `asyncio.Event` at module level, bound to the loop
  that first created it. `TestClient` uses a fresh loop per request, so the *second* SSE
  request in a session raises "bound to a different event loop" unless
  `AppStatus.should_exit_event` is reset between tests. A server has one loop, so this is a
  test-transport artefact, not an endpoint defect.
- A node replaced with `monkeypatch.setattr(graph_module, "api_contract_node", ...)` loses
  its `_guard` wrapper, because the decorator is applied at definition time. To test crash
  isolation, make the *rule engine* raise instead.
- The shadcn CLI writes to a literal `@/` directory because there is no `baseUrl` in
  `tsconfig` (a Phase 0 decision). Generate, then move the files into `src/components/ui/`.
  It also wires imports to a standalone `cn` package; repoint them at `@/lib/utils` so there
  is one `cn`.
- `CardHeader` is a grid, not a flex row. A trailing element only moves to the right when it
  is a `CardAction`; `className="flex-row justify-between"` on the header is ignored.
- lucide-react v1 has no brand icons — there is no `Github`. Use `FolderGit2`.
- Node 26 refuses to `spawn` a `.cmd` shim without a shell. Run the tool's `.js` entry with
  `process.execPath` instead of `npx`.
- Radix hides the rest of the page from the accessibility tree while a `Sheet` is open, so a
  `getByRole` query made before the dialog detaches finds nothing. Wait for
  `{ state: "detached" }`, not for the key press.
