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

Phase 0 of 6 — **scaffold complete**. The monorepo, tooling, container stack and health
endpoints are in place. The analysis engine lands in Phases 1–4 and the dashboard in Phase 5.
See [CLAUDE.md](CLAUDE.md) for the phase plan and engineering conventions.

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
| `DATABASE_URL` | `postgresql+asyncpg://mergex:mergex@localhost:5432/mergex` | Async SQLAlchemy URL |
| `GEMINI_API_KEY` | *(empty)* | Enables AI explanations. **Analysis works without it** |
| `GITHUB_TOKEN` | *(empty)* | Raises the GitHub rate limit; required for private repos |
| `MAX_REPO_SIZE_MB` | `100` | Imports above this are rejected |
| `ANALYSIS_TIMEOUT_SECONDS` | `600` | Wall-clock budget per analysis |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allowed origins |

---

## Development

```bash
make check        # lint + typecheck + test          (.\scripts\dev.ps1 check)
make format       # ruff --fix, black, prettier      (.\scripts\dev.ps1 format)
make test         # pytest with coverage             (.\scripts\dev.ps1 test)
pre-commit install
```

Quality bar enforced in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):
`ruff` + `black` + `mypy --strict` on the backend, ESLint + Prettier + `tsc` + production
build on the frontend, both Docker images built, and **≥ 70% test coverage** on the analysis
engine.

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

Progress is streamed to the browser over Server-Sent Events, so the live analysis page shows
each agent finishing in turn.

**Health score** starts at 100 and deducts 15 per critical issue, 8 per high, 3 per medium
and 1 per low, with a floor of 0. Per-category sub-scores use the same formula.

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

*Added in Phase 6, once the dashboard exists.*

<!--
  | Landing | Live analysis | Dashboard | Architecture graph |
  | --- | --- | --- | --- |
-->

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
health score, dashboard with architecture graph.

Deliberately deferred: documentation generation, deployment readiness checks, a PR comment
bot, and a VS Code extension.
