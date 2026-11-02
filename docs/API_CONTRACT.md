# MergeX AI — REST API Contract & Backend Specification

This document defines the REST API contract for the **MergeX AI** backend (FastAPI / Python 3.11+). The frontend client communicates with this API via the typed HTTP client (`src/lib/http.ts`) and the modular client implementation (`src/lib/api/real.ts`).

---

## 1. Architectural Overview & Conventions

### Base URL & Proxy
- In development, the Vite dev server forwards all `/api/*` traffic to `http://localhost:8000` via reverse proxy:
  ```ts
  // vite.config.ts
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ''),
    }
  }
  ```
- In production, set `VITE_API_BASE_URL` to the absolute or relative backend root URL (e.g., `https://api.mergex.ai`).
- All paths documented below are relative to the `/api` prefix (or backend root if rewritten).

### Headers & Encoding
- **Request Format:** `Content-Type: application/json`
- **Response Format:** `Content-Type: application/json; charset=utf-8`
- **Character Encoding:** UTF-8
- **Date Format:** ISO 8601 UTC string (e.g. `2026-10-31T14:30:00.000Z`)
- **Authentication:** `Authorization: Bearer <jwt_access_token>`

### HTTP Status Codes
| Code | Meaning | Use Case |
|---|---|---|
| `200 OK` | Success | Standard response for GET, PATCH, and stateful POST requests |
| `201 Created` | Created | Resource successfully created (e.g., new analysis initiated) |
| `204 No Content` | No Content | Successful update with empty body (e.g., `PUT /settings`) |
| `400 Bad Request` | Bad Request | Malformed request syntax or unprocessable parameters |
| `401 Unauthorized` | Unauthorized | Missing, expired, or invalid Bearer token (triggers frontend auto-logout) |
| `403 Forbidden` | Forbidden | Authenticated user lacks permission to access target resource |
| `404 Not Found` | Not Found | Requested project, analysis, or issue does not exist |
| `422 Unprocessable`| Validation Error | Pydantic model validation failure |
| `500 Server Error` | Internal Error | Unexpected failure in backend analyzer or database |

---

## 2. Standard Error Envelope

When returning non-2xx status codes, the backend should return a JSON error envelope. The frontend's `ApiError` class parses both the standard envelope and FastAPI's native validation structure:

```json
{
  "code": "RESOURCE_NOT_FOUND",
  "message": "Project with ID 'proj_404' could not be found.",
  "details": {
    "resourceId": "proj_404",
    "resourceType": "Project"
  }
}
```

If FastAPI returns validation errors, it conforms to the default schema:
```json
{
  "detail": [
    {
      "loc": ["body", "repoUrl"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## 3. Authentication & Session

The frontend maintains the session token in `localStorage` under `mergex_auth_token`. When a `401 Unauthorized` response is intercepted by `src/lib/http.ts`, a `mergex:unauthorized` window event is emitted, clearing the session and redirecting the user to `/login`.

### 3.1. User Profile Model
```json
{
  "id": "usr_9981",
  "email": "devin@mergex.ai",
  "name": "Devin Vance",
  "avatarUrl": "https://avatars.githubusercontent.com/u/1024",
  "githubUsername": "devin-mergex"
}
```

### 3.2. Endpoints (Implemented)

#### `POST /auth/register`
Register a new user account with email, password (min 6 characters), and optional display name.
- **Request Body:**
  ```json
  {
    "email": "developer@mergex.ai",
    "password": "SecretPassword123!",
    "name": "Alex Vance"
  }
  ```
- **Response `201 Created`:**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "user": {
      "id": "55eed860-bc1a-4639-8229-865e0110980d",
      "email": "developer@mergex.ai",
      "name": "Alex Vance",
      "displayName": "Alex Vance",
      "avatarUrl": null,
      "githubUsername": null,
      "createdAt": "2026-10-31T20:00:00Z"
    }
  }
  ```
- **Errors:**
  - `409 Conflict`: Email is already registered.
  - `422 Unprocessable`: Password shorter than 6 characters or invalid email format.
  - `429 Too Many Requests`: Exceeded auth rate limit (15 requests/minute per IP).

#### `POST /auth/token`
Authenticate with username (email) and password. Returns access token and user metadata.
- **Request Body:**
  ```json
  {
    "username": "developer@mergex.ai",
    "password": "SecretPassword123!"
  }
  ```
  *(Or `{"email": "developer@mergex.ai", "password": "SecretPassword123!"}`)*
- **Response `200 OK`:**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "user": {
      "id": "55eed860-bc1a-4639-8229-865e0110980d",
      "email": "developer@mergex.ai",
      "name": "Alex Vance",
      "displayName": "Alex Vance",
      "avatarUrl": null,
      "githubUsername": null,
      "createdAt": "2026-10-31T20:00:00Z"
    }
  }
  ```
- **Errors:**
  - `401 Unauthorized`: Invalid email or password.
  - `429 Too Many Requests`: Exceeded auth rate limit.

#### `GET /auth/me`
Retrieve the currently authenticated user's profile.
- **Headers:** `Authorization: Bearer <token>`
- **Response `200 OK`:** User JSON object.
- **Errors:**
  - `401 Unauthorized`: Missing, invalid, or expired JWT token.

---

## 4. Projects Endpoint Reference

### 4.1. `GET /projects`
Returns a list of all projects owned by or shared with the authenticated user.
- **Headers:** `Authorization: Bearer <token>`
- **Response `200 OK`:**
  ```json
  [
    {
      "id": "proj_1",
      "name": "hyperion-gateway",
      "owner": "mergex-ai",
      "repoUrl": "https://github.com/mergex-ai/hyperion-gateway",
      "stack": ["FastAPI", "React", "PostgreSQL", "Docker"],
      "healthScore": 78,
      "status": "completed",
      "issueCounts": {
        "integration": 3,
        "security": 1,
        "dependencies": 4,
        "deployment": 0
      },
      "lastScannedAt": "2026-10-31T08:30:00Z",
      "categoryScores": {
        "integration": 72,
        "security": 90,
        "dependencies": 65,
        "deployment": 85
      },
      "severityCounts": {
        "critical": 1,
        "high": 2,
        "medium": 4,
        "low": 1
      },
      "topIssues": [
        {
          "id": "iss_sec_101",
          "title": "Unauthenticated CORS origin wildcard detected",
          "category": "security",
          "severity": "critical",
          "filePath": "backend/app/main.py",
          "shortDescription": "CORS configuration permits untrusted origins on sensitive mutation endpoints."
        }
      ],
      "scanMeta": {
        "branch": "main",
        "commitSha": "7a9fc21",
        "durationSeconds": 42,
        "filesScanned": 312,
        "agentsRun": 8
      }
    }
  ]
  ```

### 4.2. `GET /projects/{id}`
Returns full project workspace metadata by ID.
- **Path Parameter:** `id` (string, e.g. `proj_1`)
- **Response `200 OK`:** Single Project JSON object (as shown above).
- **Response `404 Not Found`:** If project does not exist.

### 4.3. `PATCH /projects/{id}`
Partially updates mutable project metadata (e.g. project name, target repository URL).
- **Request Body:** `Partial<Project>` (e.g. `{"name": "hyperion-gateway-v2"}`)
- **Response `200 OK`:** Updated Project object.

### 4.4. `POST /projects/{id}/rescan`
Initiates an immediate re-scan of the project on its current branch.
- **Status:** Implemented in `app.api.routes.projects` (`rescan_project`).
- **Response `200 OK`:** Updated Project object with status set to `"analyzing"` and `analysisId` for SSE streaming.
- **Response `409 Conflict`:** If an analysis is already active for this project.

---

## 5. Analyses & Progress Polling

### 5.1. `POST /analyses`
Initiates an asynchronous multi-agent scan on a repository (one-step analysis: imports repository if not present or reuses existing, and queues analysis run).
- **Status:** Implemented in `app.api.routes.analyses` (`create_one_step_analysis`).
- **Request Body:**
  ```json
  {
    "repoUrl": "https://github.com/my-org/service-repo",
    "branch": "main"
  }
  ```
- **Response `201 Created` / `200 OK`:**
  ```json
  {
    "analysisId": "anl_88294",
    "projectId": "proj_new_88294",
    "id": "proj_new_88294",
    "name": "service-repo",
    "owner": "my-org",
    "repoUrl": "https://github.com/my-org/service-repo",
    "stack": ["TypeScript", "Next.js"],
    "healthScore": 0,
    "status": "analyzing",
    "issueCounts": { "integration": 0, "security": 0, "dependencies": 0, "deployment": 0 },
    "lastScannedAt": "2026-10-31T15:00:00Z",
    "categoryScores": { "integration": 0, "security": 0, "dependencies": 0, "deployment": 0 },
    "severityCounts": { "critical": 0, "high": 0, "medium": 0, "low": 0 },
    "topIssues": [],
    "scanMeta": {
      "branch": "main",
      "commitSha": "e4f8a10",
      "durationSeconds": 0,
      "filesScanned": 0,
      "agentsRun": 0
    },
    "steps": [
      { "id": 1, "label": "Cloning repository & inspecting tree", "status": "running" },
      { "id": 2, "label": "Detecting frameworks & tech stack", "status": "pending" },
      { "id": 3, "label": "Analyzing contract compatibility", "status": "pending" },
      { "id": 4, "label": "Running static security audit", "status": "pending" },
      { "id": 5, "label": "Resolving dependency vulnerabilities", "status": "pending" },
      { "id": 6, "label": "Validating deployment readiness", "status": "pending" },
      { "id": 7, "label": "Synthesizing architecture topology", "status": "pending" },
      { "id": 8, "label": "Generating executive health score", "status": "pending" }
    ]
  }
  ```

### 5.2. `GET /analyses/{analysisId}/status`
Polled by `NewAnalysis.tsx` every 1.5 seconds until status is `"completed"` or `"failed"`.
- **Status:** Implemented in `app.api.routes.analyses` (`get_analysis_status`).
- **Response `200 OK`:**
  ```json
  {
    "id": "anl_88294",
    "projectId": "proj_new_88294",
    "status": "running",
    "progressPercent": 62,
    "currentStepIndex": 5,
    "activeStep": "Validating deployment readiness",
    "error": null,
    "project": null
  }
  ```
- **When Complete:**
  ```json
  {
    "id": "anl_88294",
    "projectId": "proj_new_88294",
    "status": "completed",
    "progressPercent": 100,
    "currentStepIndex": 8,
    "activeStep": "Completed",
    "project": { /* full Project object ready to display */ }
  }
  ```

---

## 6. Issues & Quality Checks

### 6.1. `GET /projects/{id}/issues`
Fetches issues for a given project from its latest completed analysis run, optionally filtered by category, severity, status, or search query.
- **Status:** Implemented in `app.api.routes.projects` (`list_project_issues`).
- **Query Parameters:**
  - `category` (optional): `"integration"` | `"security"` | `"dependencies"` | `"deployment"`
  - `severity` (optional): `"critical"` | `"high"` | `"medium"` | `"low"`
  - `status` (optional): `"open"` | `"resolved"` | `"ignored"`
  - `q` (optional): Text search query string
- **Response `200 OK`:** Array of Issue objects:
  ```json
  [
    {
      "id": "iss_int_01",
      "projectId": "proj_1",
      "category": "integration",
      "severity": "high",
      "status": "open",
      "title": "API route mismatch between frontend client and backend router",
      "shortDescription": "Frontend calls POST /api/v1/auth/login but router specifies /api/v1/token.",
      "filePath": "src/lib/api.ts",
      "lineStart": 42,
      "lineEnd": 48,
      "explanation": "The frontend client constructs authentication requests to /api/v1/auth/login, whereas the FastAPI APIRouter exposes this endpoint at /api/v1/token. This will cause 404 Not Found at runtime.",
      "impact": "Authentication requests fail consistently in production.",
      "suggestedFix": {
        "summary": "Update frontend HTTP client path or add path alias in backend APIRouter.",
        "steps": [
          "Change target path in src/lib/api.ts to /api/v1/token",
          "Ensure OAuth2PasswordRequestForm compatibility"
        ],
        "codeBefore": "export const login = () => http.post('/auth/login', payload);",
        "codeAfter": "export const login = () => http.post('/token', payload);",
        "language": "typescript"
      },
      "meta": {
        "integration": {
          "frontendRef": "src/lib/api.ts#L42",
          "backendRef": "backend/app/routers/auth.py#L18"
        }
      }
    }
  ]
  ```

### 6.2. `GET /projects/{id}/issues/{issueId}`
Retrieves a single issue by ID.
- **Status:** Implemented in `app.api.routes.projects` (`get_project_issue`).
- **Response `200 OK`:** Single Issue object.
- **Response `404 Not Found`:** If issue does not exist or does not belong to the project.

### 6.3. `PATCH /projects/{id}/issues/{issueId}`
Updates an issue's status. Used for resolving, reopening, or ignoring issues with undo support.
- **Status:** Implemented in `app.api.routes.projects` (`update_project_issue_status`). Status is persisted to the database.
- **Request Body:**
  ```json
  {
    "status": "resolved"
  }
  ```
  *(Permitted values: `"open"`, `"resolved"`, `"ignored"`)*
- **Response `200 OK`:** Updated Issue object.

---

## 7. Deployment Checklist

 ### `GET /projects/{id}/deploy-checklist`
 Returns deployment readiness checklist items for the Deploy tab.
+- **Status:** Implemented in `app.api.routes.projects` (`get_project_deploy_checklist`).
 - **Response `200 OK`:**
   ```json
   [
     {
       "id": "chk_env_secrets",
       "label": "Environment Variables & Secrets Segregation",
       "status": "pass",
       "detail": "No hardcoded production API keys found in repository history or configuration files."
     },
     {
       "id": "chk_docker_user",
       "label": "Non-root Docker Container Execution",
       "status": "warn",
       "detail": "Dockerfile does not declare a non-root USER directive before ENTRYPOINT."
     },
     {
       "id": "chk_healthcheck_probe",
       "label": "Container Healthcheck Probe Endpoint",
       "status": "fail",
       "detail": "No /healthz or /livez endpoint exposed for Kubernetes/ECS container liveness probes."
     }
   ]
   ```

---

## 8. Architecture Graph Topology

### `GET /projects/{id}/architecture`
Provides node and edge data for rendering the system architecture visualization.
- **Status:** Implemented in `app.api.routes.projects` (`get_project_architecture`).
- **Response `200 OK`:**
   ```json
   {
     "nodes": [
       {
         "id": "node_web",
         "label": "Web Client",
         "kind": "frontend",
         "tech": "React 19 / Vite",
         "description": "Single-page responsive dashboard and audit workspace.",
         "issueIds": ["iss_int_01"],
         "position": { "x": 100, "y": 150 }
       },
       {
         "id": "node_api",
         "label": "Core Gateway",
         "kind": "api",
         "tech": "FastAPI (Python 3.11)",
         "description": "Async REST services and multi-agent orchestration.",
         "issueIds": ["iss_sec_101"],
         "position": { "x": 400, "y": 150 }
       },
       {
         "id": "node_db",
         "label": "Primary Store",
         "kind": "database",
         "tech": "PostgreSQL 16",
         "description": "Relational store for analysis runs, projects, and security audit logs.",
         "issueIds": [],
         "position": { "x": 700, "y": 150 }
       }
     ],
     "edges": [
       {
         "id": "edge_client_api",
         "source": "node_web",
         "target": "node_api",
         "label": "REST / JSON",
         "status": "warning",
         "issueIds": ["iss_int_01"]
       },
       {
         "id": "edge_api_db",
         "source": "node_api",
         "target": "node_db",
         "label": "asyncpg / SQLAlchemy",
         "status": "ok",
         "issueIds": []
       }
     ]
   }
   ```

---

## 9. Documentation & Executive Report

### `GET /projects/{id}/report`
Generates a structured multi-section Markdown report for the Docs tab and export options (Markdown, PDF, HTML).
- **Status:** Implemented in `app.api.routes.projects` (`get_project_report`).
- **Response `200 OK`:**
   ```json
   {
     "generatedAt": "2026-10-31T15:30:00Z",
     "sections": [
       {
         "id": "sec_exec_summary",
         "title": "Executive Summary",
         "markdown": "## Executive Summary\n\nMergeX AI conducted an automated multi-agent inspection across 312 source files..."
       },
       {
         "id": "sec_critical_findings",
         "title": "Critical Security & Integration Findings",
         "markdown": "### Security Hotspots\n\n- **CORS Misconfiguration**: Backend permits open origins on mutating routes."
       }
     ]
   }
   ```

---

## 10. User Settings

### 10.1. `GET /settings`
Returns current user preferences and scan configuration.
- **Status:** Implemented in `app.api.routes.settings` (`get_settings`). Persisted in database table `user_settings`.
- **Response `200 OK`:**
   ```json
   {
     "displayName": "Alex Vance",
     "email": "developer@mergex.ai",
     "theme": "system",
     "githubConnected": true,
     "githubUsername": "alex-vance",
     "checks": {
       "integration": true,
       "security": true,
       "dependencies": true,
       "deployment": true
     },
     "alertSeverity": "high"
   }
   ```

### 10.2. `PUT /settings`
Replaces user preferences.
- **Status:** Implemented in `app.api.routes.settings` (`update_settings`). Persisted in database table `user_settings`.
- **Request Body:** `UserSettings` JSON object.
- **Response `200 OK` or `204 No Content`**

---

## 11. Pydantic v2 Models Reference (Python 3.11+)

The backend team can copy these exact Pydantic v2 schemas into `app/schemas/` to ensure 100% contract compliance:

```python
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl

class ProjectStatus(str, Enum):
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"

class IssueCategory(str, Enum):
    INTEGRATION = "integration"
    SECURITY = "security"
    DEPENDENCIES = "dependencies"
    DEPLOYMENT = "deployment"

class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"

class IssueCounts(BaseModel):
    integration: int = 0
    security: int = 0
    dependencies: int = 0
    deployment: int = 0

class CategoryScores(BaseModel):
    integration: int = Field(..., ge=0, le=100)
    security: int = Field(..., ge=0, le=100)
    dependencies: int = Field(..., ge=0, le=100)
    deployment: int = Field(..., ge=0, le=100)

class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

class PriorityIssue(BaseModel):
    id: str
    title: str
    category: IssueCategory
    severity: IssueSeverity
    filePath: str
    shortDescription: str

class ScanMeta(BaseModel):
    branch: str
    commitSha: str
    durationSeconds: int
    filesScanned: int
    agentsRun: int

class Project(BaseModel):
    id: str
    name: str
    owner: str
    repoUrl: str
    stack: List[str]
    healthScore: int = Field(..., ge=0, le=100)
    status: ProjectStatus
    issueCounts: IssueCounts
    lastScannedAt: datetime
    categoryScores: CategoryScores
    severityCounts: SeverityCounts
    topIssues: List[PriorityIssue]
    scanMeta: ScanMeta

class AnalysisStep(BaseModel):
    id: int
    label: str
    status: StepStatus

class CreateAnalysisPayload(BaseModel):
    repoUrl: str
    branch: Optional[str] = "main"

class CreateAnalysisResponse(Project):
    analysisId: str
    projectId: str
    steps: List[AnalysisStep]

class AnalysisStatusResponse(BaseModel):
    id: str
    projectId: str
    status: str  # "pending" | "running" | "completed" | "failed"
    progressPercent: int = Field(..., ge=0, le=100)
    currentStepIndex: int
    activeStep: Optional[str] = None
    error: Optional[str] = None
    project: Optional[Project] = None

class SuggestedFix(BaseModel):
    summary: str
    steps: List[str]
    codeBefore: Optional[str] = None
    codeAfter: Optional[str] = None
    language: Optional[str] = None

class Issue(BaseModel):
    id: str
    projectId: str
    category: IssueCategory
    severity: IssueSeverity
    status: IssueStatus
    title: str
    shortDescription: str
    filePath: str
    lineStart: Optional[int] = None
    lineEnd: Optional[int] = None
    explanation: str
    impact: str
    suggestedFix: SuggestedFix
    meta: Optional[Dict[str, Any]] = None

class ChecklistItem(BaseModel):
    id: str
    label: str
    status: str  # "pass" | "warn" | "fail"
    detail: str

class ArchNode(BaseModel):
    id: str
    label: str
    kind: str  # "frontend" | "api" | "database" | "auth" | "external" | "worker"
    tech: str
    description: str
    issueIds: List[str] = []
    position: Optional[Dict[str, float]] = None

class ArchEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    status: str  # "ok" | "warning" | "broken"
    issueIds: Optional[List[str]] = []

class ArchitectureResponse(BaseModel):
    nodes: List[ArchNode]
    edges: List[ArchEdge]

class ReportSection(BaseModel):
    id: str
    title: str
    markdown: str

class ProjectReport(BaseModel):
    generatedAt: datetime
    sections: List[ReportSection]

class UserSettings(BaseModel):
    displayName: str
    email: str
    theme: str  # "light" | "dark" | "system"
    githubConnected: bool
    githubUsername: Optional[str] = None
    checks: Dict[str, bool]
    alertSeverity: IssueSeverity
```

---

## 12. Toggling Between Mock and Real Backend

To run the frontend against the live FastAPI backend:

1. Copy `.env.example` to `.env`:
   ```bash
   cp frontend/.env.example frontend/.env
   ```
2. Disable mock mode in `frontend/.env`:
   ```ini
   VITE_API_BASE_URL=/api
   VITE_USE_MOCK=false
   VITE_GITHUB_CLIENT_ID=your_github_client_id
   ```
3. Start the FastAPI backend on port `8000`:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. Start the frontend development server:
   ```bash
   npm run dev
   ```
5. *(Optional)* Fine-tune individual subsystems for gradual migration:
   ```ini
   # Test real auth while keeping projects mocked
   VITE_USE_MOCK=true
   VITE_MOCK_AUTH=false
   ```
