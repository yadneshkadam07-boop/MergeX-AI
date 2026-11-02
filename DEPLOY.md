# MergeX AI — Deployment Guide (Phase 5.5)

This guide covers a production deployment of:
- **Backend** → Render (Docker Web Service, single instance)
- **Frontend** → Vercel (Vite SPA)
- **Database** → Supabase (PostgreSQL)

> [!IMPORTANT]
> Complete the steps in order. You need the Supabase DATABASE_URL and the
> Render service URL before you can finish the Vercel configuration, and you
> need the Vercel URL before you can set CORS_ORIGINS on Render.

---

## 0. Prerequisites

- GitHub account with this repository pushed.
- Accounts at [supabase.com](https://supabase.com), [render.com](https://render.com),
  and [vercel.com](https://vercel.com).
- `git` installed locally (for the Alembic pre-flight check).

---

## 1. Supabase — create the database

1. Log in to [supabase.com](https://supabase.com) → **New project**.
2. Name it `mergex`, pick a strong DB password, choose a region *close to your Render region* (e.g. US West for Render Oregon).
3. Wait for provisioning (~2 min).
4. **Get the connection strings**:
   - Dashboard → **Connect** (top bar) → choose the connection method:
     - **Direct connection** (port **5432**): **Recommended** for MergeX AI on Render.
       - Format: `postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres`
       - Keep `DB_DISABLE_PREPARED_STATEMENTS=false`.
       - Connection pooling is managed in-process with `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`.
     - **Transaction pooler** (port **6543**): Use only if direct IPv4/IPv6 connections to port 5432 are blocked.
       - Format: `postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
       - If using port 6543, you **MUST** set `DB_DISABLE_PREPARED_STATEMENTS=true`. This disables asyncpg prepared statement caching and activates SQLAlchemy `NullPool`.

> [!NOTE]
> **DATABASE_URL URL Normalisation**:
> MergeX AI automatically normalises `DATABASE_URL` at runtime:
> - Standard prefixes `postgresql://` and `postgres://` are automatically translated to `postgresql+asyncpg://`.
> - libpq-only parameters (`sslmode`, `sslrootcert`, `target_session_attrs`, etc.) are stripped so asyncpg does not error out.
> - `sslmode=require` is automatically mapped to asyncpg's `connect_args["ssl"] = "require"`.
> - Alembic migrations (`alembic upgrade head`) read `DATABASE_URL` and run asynchronously against PostgreSQL using `NullPool`.

---

## 2. Render — deploy the backend

### 2a. Create the service via Blueprint

1. Push `render.yaml` (repo root) and `backend/Dockerfile` to your default branch.
2. Render Dashboard → **New** → **Blueprint**.
3. Connect your GitHub repo → select the branch → **Apply**.
4. Render detects `render.yaml` and displays the `mergex-backend` service. Click **Apply** — Render pauses and requests the secret environment variables.

### 2b. Fill in secret env vars

When Render pauses for secrets, supply the following values:

| Key | Where to get it | Example / Value |
|-----|----------------|-----------------|
| `DATABASE_URL` | Supabase → Connect → **Direct connection** (port 5432) | `postgresql://postgres.xyz:[email protected]:5432/postgres` |
| `CORS_ORIGINS` | Set to your Vercel URL (e.g. `https://mergex-ai.vercel.app`). Enter a placeholder (e.g. `https://placeholder.vercel.app`) if not yet deployed, then update after step 3. | `https://mergex-ai.vercel.app` |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Optional; if omitted, backend logs a warning and uses template explanations. | `AIzaSy...` |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings → Personal access tokens → Classic (scope: `public_repo`). Optional; raises rate limit from 60 to 5,000 req/h. | `ghp_...` |

Click **Confirm** — Render starts the build.

### 2c. Verify the backend deployment

1. Wait for the Docker build to complete (~4-5 min on first build).
2. Render runs the pre-deploy command:
   ```bash
   cd /app && alembic upgrade head
   ```
   Check the **Deploy logs** tab — verify migrations execute cleanly:
   ```text
   INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
   INFO  [alembic.runtime.migration] Will assume transactional DDL.
   INFO  [alembic.runtime.migration] Running upgrade  -> 20261017_1200-0001
   INFO  [alembic.runtime.migration] Running upgrade ...
   ```
3. Check the service URL: `https://your-service.onrender.com/health` returns:
   ```json
   {"status":"ok","version":"0.1.0","environment":"production"}
   ```
4. Check readiness: `https://your-service.onrender.com/health/ready` returns:
   ```json
   {"status":"ok","components":{"database":"ok","workspace":"ok","gemini":"ok"}}
   ```
5. Copy your Render service URL (e.g. `https://mergex-backend.onrender.com`).

---

## 3. Vercel — deploy the frontend

### 3a. Import the project

1. Log in to [vercel.com](https://vercel.com) → **Add New** → **Project**.
2. Select your GitHub repository.
3. In **Project Settings**:
   - **Root Directory**: Click Edit, select `frontend`.
   - **Framework Preset**: `Vite` (auto-detected).
   - **Build Command**: `npm run build` (or leave default).
   - **Output Directory**: `dist` (or leave default).

### 3b. Configure environment variables

In the **Environment Variables** section:

| Key | Value |
|-----|-------|
| `VITE_API_BASE_URL` | `https://your-service.onrender.com` (your Render service URL with NO trailing slash) |

Click **Deploy**. Build takes ~1-2 minutes.

### 3c. Note your live frontend URL

Copy your Vercel deployment URL (e.g. `https://mergex-ai.vercel.app`).

---

## 4. Final step: Update CORS_ORIGINS on Render

1. Open Render Dashboard → **mergex-backend** → **Environment**.
2. Find `CORS_ORIGINS` and set it to your exact Vercel URL:
   ```text
   https://mergex-ai.vercel.app
   ```
   *(If you have preview deployments, separate them with a comma: `https://mergex-ai.vercel.app,https://mergex-ai-preview.vercel.app`)*
3. Click **Save Changes**. Render will redeploy automatically without downtime.

---

## 5. Live URL Smoke Test Checklist

> [!WARNING]
> **Render Free Tier Spin-Down / Sleep Note**:
> Render's free tier spins down web services after 15 minutes of inactivity. The first incoming request can take **45–60 seconds** to wake up the container ("cold start").
> **Always wake your backend before giving a live demo** by pinging `https://your-backend.onrender.com/health`.

Perform the following smoke tests against your live deployment:

- [ ] **1. Liveness & Readiness Probes**
  ```bash
  # Check basic liveness
  curl -i https://your-backend.onrender.com/health
  # HTTP/1.1 200 OK -> {"status": "ok", ...}

  # Check subsystem readiness
  curl -i https://your-backend.onrender.com/health/ready
  # HTTP/1.1 200 OK -> database, workspace, gemini all reporting ok
  ```

- [ ] **2. Demo Project Flow ("Load demo")**
  - Navigate to `https://mergex-ai.vercel.app` in your browser.
  - Click **"Load demo"** on the home screen.
  - Verify:
    1. Project is created with `is_demo=True`.
    2. Analysis runs through all pipeline stages (`Detecting stack` → `API contract` → `Database schema` → `Security & dependencies` → `Scoring & explanations`).
    3. Health score and findings table load with seeded cross-layer issues.
  - Rate limit verification: Clicking "Load demo" more than 5 times in a minute returns HTTP 429 with `Retry-After` header.

- [ ] **3. Public GitHub Repository Import**
  - On the home page, select **"GitHub Repository"**.
  - Enter a public GitHub repository URL (e.g. `https://github.com/octocat/Hello-World`).
  - Click **"Import & Analyze"**.
  - Verify shallow clone completes into `/workspace` sandbox, analysis completes, and results are displayed.

- [ ] **4. ZIP Archive Upload**
  - On the home page, select **"Upload ZIP"**.
  - Drop a valid small repository ZIP archive (e.g. containing a `package.json` or `pyproject.toml`).
  - Click **"Import & Analyze"**.
  - Verify the upload streams to `/workspace/uploads/<id>.zip`, extracts into an isolated sandbox, and analysis report renders.

- [ ] **5. CORS & Request Tracking Headers**
  - Open browser DevTools Network tab.
  - Trigger any API call and verify the response headers:
    - `access-control-allow-origin: https://mergex-ai.vercel.app`
    - `x-request-id: <uuid>`

---

## 6. Environment Variable Reference

Every environment variable used by MergeX AI across backend (Render) and frontend (Vercel):

| Name | Service | Where to get value | Example format / Value |
|------|---------|-------------------|------------------------|
| `APP_ENV` | Backend (Render) | Hardcoded in `render.yaml` | `production` |
| `LOG_LEVEL` | Backend (Render) | Hardcoded in `render.yaml` | `INFO` |
| `API_V1_PREFIX` | Backend (Render) | Hardcoded in `render.yaml` | `/api/v1` |
| `DATABASE_URL` | Backend (Render) | Supabase Dashboard → Project Settings → Database → Connection string (Direct connection, port 5432) | `postgresql://postgres.[ref]:[email protected]:5432/postgres` |
| `DB_DISABLE_PREPARED_STATEMENTS` | Backend (Render) | Hardcoded in `render.yaml` (`false` for port 5432, set `true` only if port 6543 pooler used) | `false` |
| `DB_POOL_SIZE` | Backend (Render) | Hardcoded in `render.yaml` | `5` |
| `DB_MAX_OVERFLOW` | Backend (Render) | Hardcoded in `render.yaml` | `10` |
| `DB_ECHO` | Backend (Render) | Hardcoded in `render.yaml` | `false` |
| `CORS_ORIGINS` | Backend (Render) | Vercel Project Dashboard → Production Domain URL | `https://mergex-ai.vercel.app` |
| `GEMINI_API_KEY` | Backend (Render) | [Google AI Studio](https://aistudio.google.com/apikey) | `AIzaSyD...` *(Leave blank for template text only)* |
| `GEMINI_MODEL` | Backend (Render) | Hardcoded in `render.yaml` | `gemini-2.5-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Backend (Render) | Hardcoded in `render.yaml` | `60` |
| `GEMINI_MAX_RETRIES` | Backend (Render) | Hardcoded in `render.yaml` | `3` |
| `GITHUB_TOKEN` | Backend (Render) | GitHub Settings → Developer Settings → Personal Access Tokens (classic) | `ghp_...` *(Optional, raises clone rate limit)* |
| `WORKSPACE_DIR` | Backend (Render) | Hardcoded in `render.yaml` (ephemeral container scratch directory) | `/workspace` |
| `MAX_REPO_SIZE_MB` | Backend (Render) | Hardcoded in `render.yaml` | `100` |
| `MAX_UPLOAD_SIZE_MB` | Backend (Render) | Hardcoded in `render.yaml` | `100` |
| `MAX_FILE_COUNT` | Backend (Render) | Hardcoded in `render.yaml` | `20000` |
| `ANALYSIS_TIMEOUT_SECONDS` | Backend (Render) | Hardcoded in `render.yaml` | `600` |
| `CLONE_TIMEOUT_SECONDS` | Backend (Render) | Hardcoded in `render.yaml` | `120` |
| `TRUST_PROXY_HEADERS` | Backend (Render) | Hardcoded in `render.yaml` (Render reverse proxy rewrites `X-Forwarded-For`) | `true` |
| `RATE_LIMIT_PER_MINUTE` | Backend (Render) | Hardcoded in `render.yaml` | `60` |
| `DEMO_RATE_LIMIT_PER_HOUR` | Backend (Render) | Hardcoded in `render.yaml` | `5` |
| `DEMO_RATE_LIMIT_PER_MINUTE` | Backend (Render) | Hardcoded in `render.yaml` | `5` |
| `DEMO_BURST_LIMIT` | Backend (Render) | Hardcoded in `render.yaml` | `2` |
| `DEMO_BURST_WINDOW_MINUTES` | Backend (Render) | Hardcoded in `render.yaml` | `10` |
| `DEMO_RETENTION_HOURS` | Backend (Render) | Hardcoded in `render.yaml` | `24` |
| `DEMO_CLEANUP_INTERVAL_MINUTES` | Backend (Render) | Hardcoded in `render.yaml` | `60` |
| `VITE_API_BASE_URL` | Frontend (Vercel) | Render Dashboard → mergex-backend Service URL | `https://mergex-backend.onrender.com` |

---

## 7. What cannot be verified without real cloud accounts

The following components were structurally and architecturally verified via unit tests, schema parsers, and build scripts, but require real active cloud accounts to test in a live environment:

| Item | Structural Verification Status | Why it cannot be verified locally |
|------|--------------------------------|-----------------------------------|
| **Render `preDeployCommand` lifecycle** | ✅ `alembic upgrade head` runs inside `/app` in container where `alembic.ini` and `/opt/venv` exist. Tested locally against SQLite/Postgres. | Render's proprietary Blueprint executor and deployment hooks run only on Render's orchestration platform. |
| **Supabase live connection & SSL handshake** | ✅ `normalise_database_url` tested for scheme conversion, `ssl=require`, parameter stripping, and pooler compatibility. | Requires active Supabase credentials and reachable network endpoints on `pooler.supabase.com`. |
| **Render `numInstances: 1` enforcement** | ✅ Declared in `render.yaml`. Backend designed for single-instance with in-memory event bus and cleanup task. | Render dashboard / infrastructure orchestration feature. |
| **Vercel edge CDN SPA routing** | ✅ `vercel.json` SPA rewrite rules and cache headers validated. Local preview and build validated. | Vercel's proprietary Edge Network routing and TLS termination layer. |
| **SSE Event stream through Render reverse proxy** | ✅ Backend sets `Content-Type: text/event-stream` and disables output buffering. | Reverse-proxy response streaming / buffering policies on Render edge routers. |
