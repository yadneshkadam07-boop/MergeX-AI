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
| 1 | DB models, Alembic, project/analysis CRUD, repo importer, stack detector | next |
| 2 | Tree-sitter parsers + extractors, unit tests against fixtures | |
| 3 | API-contract diff, schema validation, security scanner, seeded-bug fixtures | |
| 4 | LangGraph workflow, Gemini integration, synthesizer, scoring, SSE | |
| 5 | Frontend pages wired to the API | |
| 6 | Architecture graph, polish, README screenshots, deploy configs | |

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
- **Black is the formatter of record**, with `ruff-format --check` in pre-commit only to
  catch disagreement between the two.
- **Frontend has no test runner yet.** Vitest + Testing Library arrive with Phase 5, when
  there are components whose behaviour is worth asserting.

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
  excluded from ruff, black, mypy and coverage, and never imported by application code.
