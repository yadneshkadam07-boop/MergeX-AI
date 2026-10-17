# MergeX AI

**Multi-agent software integration & validation platform.**

Import a GitHub repository or upload a ZIP. MergeX analyses the whole project and reports
whether the frontend, backend and database actually work *together*.

Existing tools analyse code in isolation. MergeX checks **cross-layer consistency**:

| Layer pair | What is compared |
| --- | --- |
| Frontend ↔ Backend | `fetch`/`axios`/`ky` call sites against real route definitions — missing endpoints, wrong HTTP method, path typos, mismatched field names, missing auth headers |
| Backend ↔ Database | ORM models against the migrated schema — fields absent from the DB, type mismatches, queries on columns that do not exist, missing foreign keys and indexes |
| Config ↔ Deployment | hardcoded secrets, unprotected routes, CORS wildcards, committed `.env`, dependency CVEs via [OSV.dev](https://osv.dev) |

The motivating case is AI-generated projects, where each layer looks plausible on its own but
the seams do not line up.

> **Design principle:** deterministic analysis (Tree-sitter, Python `ast`, rule engines)
> *finds* every issue. Gemini only *explains* issues, ranks them and suggests fixes. The model
> is never the sole source of a finding — so results are reproducible, and the tool still
> works with no API key configured.

---

## Status

Phase 5 of 6 complete. **The product works end to end**: paste a GitHub URL or drop a ZIP,
watch the analysis stream stage by stage, and read a dashboard with a health score,
per-category sub-scores and every finding explained with a concrete before/after fix. 16
rules across four categories, all deterministic — no language model is involved in finding
anything, and the finding set is provably identical with and without Gemini. The
architecture graph arrives in Phase 6.

No repository to hand? **Load demo** analyses a bundled React + FastAPI project with seeded
defects. No API key needed: every finding is explained offline from its rule's template.

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Monorepo, container stack, tooling, CI, health endpoints | ✅ |
| 1 | Schema + migrations, project/analysis API, repo importer, stack detector, seeded fixtures | ✅ |
| 2 | Tree-sitter parsers and extractors | ✅ |
| 3 | Contract diff, schema validation, security scanner, scoring | ✅ |
| 4 | LangGraph pipeline, Gemini explanations, SSE progress, report endpoint | ✅ |
| 5 | Dashboard UI, live progress, issue drawer, Vitest | ✅ |
| 6 | Architecture graph, deploy configs | next |

See [CLAUDE.md](CLAUDE.md) for the engineering conventions and the decision log.

### Working today

```bash
# Upload a project, queue a run, watch it, read the report.
curl -F file=@project.zip localhost:8000/api/v1/projects/upload
curl -X POST localhost:8000/api/v1/projects/$PROJECT_ID/analyses -d '{}'
curl -N localhost:8000/api/v1/analyses/$ANALYSIS_ID/events   # SSE progress
curl localhost:8000/api/v1/analyses/$ANALYSIS_ID/report
```

```
event: stack       {"status":"completed","message":"Detected React, FastAPI"}
event: api         {"status":"completed","finding_count":5,"total_findings":5}
event: schema      {"status":"skipped","message":"No migrations or no models"}
event: security    {"status":"completed","finding_count":0,"total_findings":5}
event: synthesis   {"status":"completed","finding_count":5}
event: complete    {"status":"completed","total_findings":5,"data":{"score":46}}
```

Reconnect with `Last-Event-ID` and the stream resumes where it left off; a client that
connects after the run has finished still receives the whole history and the terminal
event. Both success and failure emit `complete`, so the UI always knows when to stop.

```
react_fastapi_insecure   score=0/100   15 findings
  sub-scores: api_contract 100 · schema 100 · security 0 · dependency 63

  MX-SEC-001 [critical] frontend/src/api/config.ts:3   STRIPE_SECRET_KEY = ********JkOm
  MX-SEC-002 [critical] backend/app/routes.py:15       refund_payment has no authentication
  MX-SEC-004 [critical] backend/.env:1                 6 variables committed
  MX-DEP-001 [critical] backend/requirements.txt:6     PyYAML==5.3.1 → 5.4 or later
  MX-SEC-003 [high]     backend/app/main.py:12-18      allow_origins=['*'] with credentials
  MX-SEC-005 [medium]   backend/app/main.py:8          FastAPI(debug=True)
  …
```

Every finding carries a stable rule ID, a confidence score, the file and line range, the
source snippet as evidence, and an expected-versus-actual pair. Secrets are **masked in
stored evidence** — a tool that finds a credential and then saves it has moved the secret,
not reported it — and masked again before any snippet is sent to a model.

Each finding also carries an explanation and a concrete fix:

```
MX-API-002 [critical] frontend/src/api/users.ts:7   confidence 1.0

  The call asks for GET /api/user/{}, but the backend serves GET /api/users/{} —
  the two differ by a single character. The request returns 404, and because the
  path reads almost correctly this is easy to miss in review.

  fix:    At frontend/src/api/users.ts:7, change the request path from
          '/api/user/${id}' to '/api/users/${id}' to match get_user.
  before: const response = await api.get(`/api/user/${id}`);
  after:  const response = await api.get(`/api/users/${id}`);
```

**That output needs no API key.** Each of the 16 rules has a hand-written explanation and
fix template, so the whole product runs offline; Gemini rewrites the prose when
`GEMINI_API_KEY` is set. It can only ever *add* an explanation and a fix to a finding that
deterministic analysis already produced — it cannot create, remove, merge or re-rank one,
and a test asserts the finding set is byte-identical with and without it. Invalid model
output is retried once and then falls back to the template for that batch alone.

Three sample projects with **deliberately seeded cross-layer bugs** live in
[`backend/fixtures/`](backend/fixtures) — a mismatched API path, a missing database column,
and a hardcoded secret. Each has a manifest of the findings the engine must produce, so
Phases 2–3 are built against a fixed target. They double as the demo.

---

## Stack

**Frontend** React 19 · Vite · TypeScript · Tailwind CSS v4 · shadcn/ui · React Router ·
TanStack Query · Recharts · React Flow
**Backend** FastAPI · Python 3.11 · Pydantic v2 · SQLAlchemy 2 · Alembic
**Database** PostgreSQL 16 (Supabase-compatible)
**AI** Gemini (`google-genai`) orchestrated with LangGraph
**Analysis** Tree-sitter (JS/TS/TSX), Python `ast`, sqlglot
**Deploy** Vercel (frontend) · Render (backend)

---

## Requirements

- **Node.js** ≥ 20.19
- **Python** 3.11 or 3.12
- **Docker Desktop** — optional; only needed for the one-command stack
- **Git**

---

## Quick start

### Option A — Docker (everything at once)

```bash
cp .env.example .env     # then fill in GEMINI_API_KEY (optional)
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173> |
| API docs | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/health> |
| Postgres | `localhost:5432` (`mergex` / `mergex`) |

### Option B — Local toolchain

```bash
cp .env.example .env
```

**Windows (PowerShell)**

```powershell
.\scripts\dev.ps1 setup     # backend venv + frontend node_modules
.\scripts\dev.ps1 api       # http://localhost:8000
.\scripts\dev.ps1 web       # http://localhost:5173  (second terminal)
```

**Linux / macOS**

```bash
make setup
make api        # http://localhost:8000
make web        # http://localhost:5173  (second terminal)
```

Postgres is still needed for Phase 1 onward; the quickest route is
`docker compose up -d db`, or point `DATABASE_URL` at a Supabase project.

---

## Configuration

Every setting is documented in [`.env.example`](.env.example) and typed in
`backend/app/core/config.py`. Nothing in the codebase reads `os.environ` directly.

The ones that matter most:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://mergex:mergex@localhost:5432/mergex` | Connection string |
| `DB_DISABLE_PREPARED_STATEMENTS` | `false` | Set `true` for a pooled Supabase URL (see below) |
| `GEMINI_API_KEY` | *(empty)* | Enables AI explanations. **Analysis works without it** |
| `GITHUB_TOKEN` | *(empty)* | Raises the GitHub rate limit; required for private repos |
| `MAX_REPO_SIZE_MB` | `100` | Imports above this are rejected |
| `ANALYSIS_TIMEOUT_SECONDS` | `600` | Wall-clock budget per analysis |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allowed origins |

### Using Supabase

Paste the connection string exactly as the dashboard gives it to you. `postgres://` and
`postgresql://` are rewritten to `postgresql+asyncpg://`, and a trailing `?sslmode=require`
is translated into asyncpg's own SSL option — asyncpg has no `sslmode` argument and fails
outright if it is passed through.

One flag matters. The **transaction pooler** (port 6543) is pgbouncer, where a prepared
statement cannot outlive its transaction:

```bash
DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres
DB_DISABLE_PREPARED_STATEMENTS=true
```

With the **direct connection** (port 5432) leave it `false`. Always run migrations against
the direct connection.

### Migrations

```bash
make migrate                      # .\scripts\dev.ps1 migrate
make migration m="add issues"     # .\scripts\dev.ps1 migration "add issues"
make db-current                   # .\scripts\dev.ps1 db-current
```

`docker compose up` applies migrations before starting the API, so a fresh volume works
immediately. The Alembic URL comes from `app.core.config`, never from `alembic.ini`, so
migrations and the service can never disagree about which database they mean.

---

## Development

```bash
make check        # lint + typecheck + test          (.\scripts\dev.ps1 check)
make format       # ruff --fix, black, prettier      (.\scripts\dev.ps1 format)
make test         # pytest with coverage             (.\scripts\dev.ps1 test)
pre-commit install
```

Quality bar enforced in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):
`ruff` + `black` + `mypy --strict` + pytest on the backend, ESLint + Prettier + `tsc` +
Vitest + production build on the frontend, both Docker images built, and **≥ 70% test
coverage** on the analysis engine.

Frontend tests run with Vitest and Testing Library (`npm run test` in `frontend/`), and
cover the issue-table filters, the SSE hook including reconnection, and the score gauge.

---

## How the analysis works

```
            ┌──────────────────────┐
            │  StackDetectorAgent  │   frameworks from manifests + file layout
            └──────────┬───────────┘
                       │
        ┌──────────────┼──────────────┐          run in parallel
        ▼              ▼              ▼
┌───────────────┐ ┌──────────┐ ┌──────────────┐
│ APIContract   │ │ Schema   │ │ Security     │
│ Agent         │ │ Agent    │ │ Agent        │
└───────┬───────┘ └────┬─────┘ └──────┬───────┘
        └──────────────┼──────────────┘
                       ▼
            ┌──────────────────────┐
            │  SynthesizerAgent    │   dedupe → severity → Gemini explanation → score
            └──────────┬───────────┘
                       ▼
             health score + ranked issues
```

The three rule groups are independent nodes with no edges between them, which is what makes
LangGraph run them concurrently. **Each catches its own exceptions.** If one crashes the
other two still finish, the synthesiser still runs, and the report names the category that
failed — because "no security issues found" and "the security analysis crashed" must never
look the same.

Progress is streamed to the browser over Server-Sent Events, so the live analysis page shows
each agent finishing in turn, with a finding count per stage.

**Health score** starts at 100 and deducts 15 per critical issue, 8 per high, 3 per medium
and 1 per low, with a floor of 0. Per-category sub-scores use the same formula. A category
reports `analysed: false` when there was nothing of that kind to check, so the UI can say
"not applicable" rather than "perfect".

### What Gemini is and is not allowed to do

| | |
| --- | --- |
| **Finds issues** | Tree-sitter, Python `ast`, sqlglot, rule engines. Deterministic. |
| **Explains issues** | Gemini, with structured JSON output validated by Pydantic. |
| **Can the model add a finding?** | No. Explanations are matched back to findings by fingerprint, so an invented ID matches nothing. |
| **Can it remove or re-rank one?** | No. The code iterates over findings, never over the model's response. |
| **If it returns nonsense?** | Retried once, then the per-rule template. The analysis never fails. |
| **If there is no API key?** | Templates for everything. The product runs fully offline. |
| **Are snippets redacted?** | Yes — at finding construction, and again when the prompt is built. |

Token usage is logged per analysis, and the report says how many explanations came from the
model versus the templates.

---

## Platform security

MergeX treats every imported repository as hostile input.

- **User code is never executed** — no install, no build, no test run. Static analysis only.
- Clones and archive extraction are confined to the sandbox directory, with explicit
  zip-slip, path-traversal, UNC, drive-qualifier and Windows-device-name guards
  (`backend/app/core/security.py`, covered by tests).
- Size, file-count and timeout limits are enforced before and during analysis.
- Sandbox directories are deleted when an analysis ends, including on failure.
- Credentials live in environment variables, are typed `SecretStr`, and are masked in logs.
- API error responses are opaque; details go to the structured log with a request ID.

---

## Screenshots

Captured from the running stack — real imports, real analyses, no mock data. Regenerate
with `npm run screenshots` from `frontend/`; see
[docs/screenshots/README.md](docs/screenshots/README.md).

| Live analysis | Report |
| --- | --- |
| [![Live analysis](docs/screenshots/03-analysis-live.png)](docs/screenshots/03-analysis-live.png) | [![Dashboard](docs/screenshots/05-dashboard-dark.png)](docs/screenshots/05-dashboard-dark.png) |
| Each stage reports as it finishes, with a count. Reconnects with `Last-Event-ID`. | Health score, per-category sub-scores, severity breakdown, filterable issues. |

| Issue detail | Import |
| --- | --- |
| [![Issue drawer](docs/screenshots/07-issue-drawer.png)](docs/screenshots/07-issue-drawer.png) | [![Landing](docs/screenshots/01-landing-dark.png)](docs/screenshots/01-landing-dark.png) |
| Evidence with the offending line highlighted, why it matters, and the exact edit. | GitHub URL, ZIP upload, or the bundled demo. |

Light theme, the finished stepper, the coverage tab and the 390 px layout are all in
[docs/screenshots/](docs/screenshots/).

---

## Project layout

```
backend/     FastAPI service + the analysis engine (see CLAUDE.md for the module map)
frontend/    React + Vite single-page app
scripts/     dev.ps1 — Windows task runner mirroring the Makefile
docker-compose.yml
```

---

## Roadmap

Built now: repo import, API-contract validation, schema-drift detection, security scan,
dependency advisories, health score, AI explanations with concrete fixes, live progress
streaming, and the report API. Still to come: the dashboard and the architecture graph.

Deliberately deferred: documentation generation, deployment readiness checks, a PR comment
bot, and a VS Code extension.
