<div align="center">

# MergeX AI

### Multi-Agent Software Integration & Validation Platform

**Find the issues hiding between your frontend, backend, database, and deployment setup.**

MergeX AI analyzes the connections between software layers to uncover integration defects, configuration risks, and security issues before they become production problems.

<br/>

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Frontend-React-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/Language-TypeScript-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/DevOps-Docker-2496ED?logo=docker&logoColor=white)

<br/>

**Team MergX**

Yadnesh Kadam · Shaikh Taufiq · Satakshi Kharade · Harsh Bhosale

</div>

---

## Table of Contents

- [Overview](#overview)
- [Why MergeX AI?](#why-mergex-ai)
- [Key Capabilities](#key-capabilities)
- [How It Works](#how-it-works)
- [Analysis Approach](#analysis-approach)
- [Technology Stack](#technology-stack)
- [Project Status](#project-status)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Development](#development)
- [Security](#security)
- [Screenshots](#screenshots)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)
- [Team](#team)

---

## Overview

MergeX AI is a multi-agent software integration and validation platform. It examines whether the major layers of a software application work correctly together.

Import a project from a GitHub repository or upload it as a ZIP archive. MergeX analyzes its structure and produces a report containing integration findings, security risks, severity levels, evidence, and actionable remediation guidance.

> **The problem:** Individual components can appear correct in isolation while failing at their integration boundaries. MergeX focuses on those boundaries.

## Why MergeX AI?

Traditional code analysis often examines files, components, or dependencies individually. MergeX takes a cross-layer approach and checks whether the contracts between application layers are consistent.

| Integration boundary | What MergeX checks |
|---|---|
| **Frontend ↔ Backend** | Frontend API calls against backend routes, including missing endpoints, HTTP method mismatches, path differences, field mismatches, and missing authentication headers. |
| **Backend ↔ Database** | ORM models against database migrations and schema, including missing columns, type mismatches, invalid queries, foreign keys, and indexes. |
| **Configuration ↔ Deployment** | Hardcoded secrets, unsafe configuration, unprotected routes, permissive CORS settings, committed environment files, and dependency advisories. |

MergeX is especially useful for projects assembled with AI coding tools or multiple contributors, where individual layers may look valid but fail when connected.

## Key Capabilities

- **API contract validation** — compares frontend API call sites with backend route definitions.
- **Database schema validation** — identifies differences between application models and migrated database schemas.
- **Security analysis** — detects exposed credentials, unsafe configuration, and other security concerns.
- **Dependency advisory checks** — checks dependency versions against known vulnerability information.
- **Multi-agent analysis** — runs independent analysis stages and combines their findings.
- **Live analysis updates** — streams stage-by-stage progress to the dashboard using Server-Sent Events (SSE).
- **Health scoring** — provides an overall score and category-level scores.
- **Actionable reports** — includes severity, confidence, file locations, evidence, explanations, and suggested fixes.
- **Offline-capable explanations** — uses built-in rule templates when an AI API key is not configured.
- **Safe static analysis** — analyzes imported source code without executing project code.

## How It Works

At a high level, an analysis moves through the following stages:

```text
                  ┌──────────────────────┐
                  │   Project Import     │
                  │ GitHub URL / ZIP     │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │    Stack Detection   │
                  │ Frameworks & files   │
                  └──────────┬───────────┘
                             │
               ┌─────────────┼─────────────┐
               ▼             ▼             ▼
        ┌────────────┐ ┌────────────┐ ┌────────────┐
        │ API        │ │ Database   │ │ Security   │
        │ Analysis   │ │ Analysis   │ │ Analysis   │
        └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
              └─────────────┼─────────────┘
                            ▼
                  ┌──────────────────────┐
                  │     Synthesis        │
                  │ Deduplication,       │
                  │ severity & scoring   │
                  └──────────┬───────────┘
                             ▼
                  ┌──────────────────────┐
                  │   Analysis Report    │
                  │ Findings & Fixes     │
                  └──────────────────────┘
```

The API, schema, and security analysis groups are independent. They can run concurrently, and an error in one stage does not automatically prevent the other stages from completing. The report distinguishes a failed analysis category from a category in which no issues were found.

Progress is streamed to the frontend as each stage completes.

## Analysis Approach

### Deterministic findings, AI-assisted explanations

MergeX separates issue detection from issue explanation:

| Responsibility | Technology / approach |
|---|---|
| Finding issues | Tree-sitter, Python AST, sqlglot, and deterministic rule engines |
| Explaining findings | Gemini, when `GEMINI_API_KEY` is configured |
| Offline explanations | Built-in explanation and fix templates |
| Validation | Structured model output validated with Pydantic |

The language model is not the source of findings. It can explain and suggest fixes for findings already produced by deterministic analysis; it cannot create, remove, or re-rank findings. This design keeps detection reproducible and allows analysis to run without an AI API key.

### Finding details

A finding can include:

- A stable rule identifier and severity.
- A confidence score.
- The affected file and line range.
- A source snippet used as evidence.
- An explanation of the issue.
- An expected-versus-actual comparison.
- A suggested remediation with before-and-after examples.

Sensitive values are masked in stored evidence and again before snippets are sent to a language model.

### Health score

The overall health score starts at **100** and applies the following deductions:

| Severity | Deduction |
|---|---:|
| Critical | 15 points |
| High | 8 points |
| Medium | 3 points |
| Low | 1 point |

The score has a minimum of 0. Category scores use the same calculation. A category that has nothing applicable to analyze is reported as not applicable rather than being presented as issue-free.

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React 19, Vite, TypeScript, Tailwind CSS v4, shadcn/ui |
| Frontend data & visualization | React Router, TanStack Query, Recharts, React Flow |
| Backend | FastAPI, Python 3.11, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 (Supabase-compatible) |
| AI orchestration | Gemini (`google-genai`), LangGraph |
| Static analysis | Tree-sitter, Python AST, sqlglot |
| Deployment | Vercel (frontend), Render (backend) |
| Development environment | Docker, Docker Compose |

## Project Status

The project documentation reports all six implementation phases as complete.

| Phase | Scope | Status |
|---:|---|---|
| 0 | Monorepo, container stack, tooling, CI, health endpoints | Complete |
| 1 | Schema and migrations, project/analysis API, repository importer, stack detector, seeded fixtures | Complete |
| 2 | Tree-sitter parsers and extractors | Complete |
| 3 | Contract diff, schema validation, security scanner, scoring | Complete |
| 4 | LangGraph pipeline, Gemini explanations, SSE progress, report endpoint | Complete |
| 5 | Dashboard UI, live progress, issue drawer, Vitest | Complete |
| 6 | Architecture graph, deployment configurations, authentication, project hub | Complete |

The implementation includes 16 deterministic rules across four categories, according to the project documentation. Bundled sample projects in `backend/fixtures/` provide reproducible examples of seeded integration and security defects.

## Getting Started

### Prerequisites

Install the following before starting:

- **Node.js:** 20.19 or later
- **Python:** 3.11 or 3.12
- **Git**
- **Docker Desktop:** optional; required only for the Docker-based setup

A PostgreSQL database is required from Phase 1 onward. You can run it through Docker Compose or use a Supabase database.

### Option A — Run the complete stack with Docker

1. Clone the repository and open its root directory.
2. Create your local environment file:

   ```bash
   cp .env.example .env
   ```

3. Add configuration values to `.env`. `GEMINI_API_KEY` is optional.
4. Build and start the services:

   ```bash
   docker compose up --build
   ```

When the services are running, open:

| Service | Local address |
|---|---|
| Frontend | http://localhost:5173 |
| API documentation | http://localhost:8000/docs |
| Health endpoint | http://localhost:8000/health |
| PostgreSQL | localhost:5432 |

### Option B — Run locally

Create the environment file first:

```bash
cp .env.example .env
```

#### Windows (PowerShell)

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 api
```

Open a **second terminal** and run:

```powershell
.\scripts\dev.ps1 web
```

#### Linux / macOS

```bash
make setup
make api
```

Open a **second terminal** and run:

```bash
make web
```

The frontend is available at `http://localhost:5173`, and the backend is available at `http://localhost:8000`.

> **Database note:** Start a local database with `docker compose up -d db`, or configure `DATABASE_URL` to point to a Supabase project.

### Try the API workflow

Once the backend is running, the following example demonstrates the upload, analysis, progress-stream, and report endpoints:

```bash
# Upload a project archive
curl -F file=@project.zip http://localhost:8000/api/v1/projects/upload

# Start an analysis (replace PROJECT_ID with the returned project ID)
curl -X POST \
  http://localhost:8000/api/v1/projects/PROJECT_ID/analyses \
  -H "Content-Type: application/json" \
  -d '{}'

# Stream analysis progress (replace ANALYSIS_ID)
curl -N http://localhost:8000/api/v1/analyses/ANALYSIS_ID/events

# Retrieve the report
curl http://localhost:8000/api/v1/analyses/ANALYSIS_ID/report
```

The SSE endpoint supports reconnection using `Last-Event-ID`. A client connecting after an analysis has finished can still receive the event history and terminal event.

## Configuration

Application settings are documented in `.env.example` and typed in `backend/app/core/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://mergex:mergex@localhost:5432/mergex` | Database connection string |
| `DB_DISABLE_PREPARED_STATEMENTS` | `false` | Disable prepared statements for a pooled Supabase connection |
| `GEMINI_API_KEY` | Empty | Enables AI-assisted explanations; analysis can run without it |
| `GITHUB_TOKEN` | Empty | Raises GitHub API rate limits and is required for private repositories |
| `MAX_REPO_SIZE_MB` | `100` | Maximum accepted repository size |
| `ANALYSIS_TIMEOUT_SECONDS` | `600` | Maximum analysis duration |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated list of allowed origins |

### Supabase connection notes

Use the connection string provided by your Supabase dashboard. The application rewrites `postgres://` and `postgresql://` schemes to `postgresql+asyncpg://` and translates `?sslmode=require` into the corresponding asyncpg SSL option.

For the Supabase transaction pooler (port `6543`), set:

```env
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
DB_DISABLE_PREPARED_STATEMENTS=true
```

For a direct connection (port `5432`), leave `DB_DISABLE_PREPARED_STATEMENTS=false`. Run database migrations against the direct connection.

### Database migrations

```bash
make migrate
make migration m="add issues"
make db-current
```

PowerShell equivalents:

```powershell
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 migration "add issues"
.\scripts\dev.ps1 db-current
```

## Development

The repository includes commands for formatting, checks, and tests.

```bash
# Run linting, type checks, and tests
make check

# Format backend and frontend code
make format

# Run backend tests
make test

# Install Git pre-commit hooks
pre-commit install
```

PowerShell equivalents are available through `.\scripts\dev.ps1`.

The documented CI workflow (`.github/workflows/ci.yml`) runs backend linting, formatting, type checking and tests, along with frontend linting, formatting, type checking, tests and a production build. It also builds both Docker images and enforces the documented analysis-engine test-coverage threshold.

Frontend tests use Vitest and Testing Library.

## Security

MergeX treats imported repositories as untrusted input.

- **No project execution:** imported source code is analyzed statically. MergeX does not install dependencies or run the imported project's build or tests.
- **Archive protections:** extraction is guarded against zip-slip, path traversal, UNC paths, drive qualifiers, and Windows device names.
- **Resource limits:** repository size, file count, and analysis time are limited.
- **Sandbox cleanup:** temporary analysis directories are removed when an analysis ends, including after failures.
- **Credential handling:** credentials are configured through environment variables, typed as `SecretStr`, and masked in logs.
- **Protected evidence:** sensitive values are redacted before evidence is stored or passed to the language model.
- **Controlled error reporting:** API error responses avoid exposing internal details; diagnostic information is written to structured logs with a request ID.

## Screenshots

The repository includes screenshots captured from the running application. The project documentation describes these as real imports and analyses rather than mock data.

| Live analysis | Dashboard |
|---|---|
| ![Live analysis](docs/screenshots/03-analysis-live.png) | ![Dashboard](docs/screenshots/05-dashboard-dark.png) |
| Issue details | Project import |
| ![Issue drawer](docs/screenshots/07-issue-drawer.png) | ![Landing page](docs/screenshots/01-landing-dark.png) |

Additional screenshots are available in `docs/screenshots/`. The project documentation describes regenerating them with:

```bash
cd frontend
npm run screenshots
```

## Project Structure

```text
.
├── backend/              # FastAPI service and analysis engine
│   └── fixtures/         # Sample projects with seeded defects
├── frontend/             # React + Vite application
├── scripts/              # Development scripts (including dev.ps1)
├── docs/
│   └── screenshots/      # Application screenshots
├── .github/
│   └── workflows/        # CI workflow
├── docker-compose.yml
├── .env.example
└── README.md
```

## Roadmap

The core platform capabilities described in this README are implemented. Potential future extensions identified in the project notes include:

- Automated documentation generation.
- Pull request review and comment integration.
- A Visual Studio Code extension.

These are future extensions, not features claimed as currently available.

## Team

<div align="center">

### Team MergX

| No. | Team member |
|:---:|---|
| 01 | **Yadnesh Kadam** |
| 02 | **Shaikh Taufiq** |
| 03 | **Satakshi Kharade** |
| 04 | **Harsh Bhosale** |

*Built with curiosity, collaboration, and a focus on reliable software.*

</div>

---

<div align="center">

**MergeX AI — Validate the connections. Ship with confidence.**

</div>
