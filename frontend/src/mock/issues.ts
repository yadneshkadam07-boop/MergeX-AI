import type { Project, PriorityIssue } from "@/types/project";
import type { Issue, ChecklistItem } from "@/types/issue";

/** Simple deterministic string hash to seed pseudo-random generation per project */
function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/** Linear congruential generator for deterministic pseudo-random floats [0, 1) */
function createPrng(seed: number) {
  let state = seed % 2147483647;
  if (state <= 0) state += 2147483646;
  return function next() {
    state = (state * 16807) % 2147483647;
    return (state - 1) / 2147483646;
  };
}

interface IssueTemplate {
  category: Issue["category"];
  severity: Issue["severity"];
  title: string;
  shortDescription: string;
  filePath: string;
  lineStart: number;
  lineEnd: number;
  explanation: string;
  impact: string;
  suggestedFix: {
    summary: string;
    steps: string[];
    codeBefore?: string;
    codeAfter?: string;
    language?: string;
  };
  meta?: Issue["meta"];
}

const TEMPLATES: IssueTemplate[] = [
  // Integration Issues
  {
    category: "integration",
    severity: "critical",
    title: "Frontend calls /api/users but backend exposes /api/user",
    shortDescription: "Plural vs singular endpoint mismatch causes 404 client runtime errors.",
    filePath: "frontend/src/api/users.ts",
    lineStart: 18,
    lineEnd: 24,
    explanation:
      "The client-side API client specifies a pluralized `/api/users` REST resource route, but the backend FastAPI route decorators bind `/api/user`. In production builds, this causes user lookup requests to fail immediately with HTTP 404 status codes.",
    impact:
      "Breaks user profile loading and hydration, triggering unhandled promise rejections on page render.",
    suggestedFix: {
      summary:
        "Harmonize the endpoint URI contract to match the backend singular path or configure aliasing.",
      steps: [
        "Inspect the route definition in backend/app/api/endpoints/users.py.",
        "Change frontend/src/api/users.ts fetch URL to `/api/user` or update backend router prefix.",
        "Run cross-contract client tests to verify response payload types.",
      ],
      codeBefore: `// frontend/src/api/users.ts\nexport async function fetchUsers() {\n  const res = await fetch("/api/users");\n  return res.json();\n}`,
      codeAfter: `// frontend/src/api/users.ts\nexport async function fetchUsers() {\n  const res = await fetch("/api/user");\n  return res.json();\n}`,
      language: "typescript",
    },
    meta: {
      integration: {
        frontendRef: "fetch('/api/users')",
        backendRef: "@router.get('/api/user')",
      },
    },
  },
  {
    category: "integration",
    severity: "high",
    title: "Request body field name mismatch (userName vs username)",
    shortDescription: "CamelCase vs lowercase casing discrepancy drops user credentials.",
    filePath: "frontend/src/services/auth.ts",
    lineStart: 42,
    lineEnd: 48,
    explanation:
      "The authentication submission payload sends JSON with key `userName`, but the Pydantic schema expects `username`. Because additional fields are ignored by default validation, the backend receives null for the username attribute.",
    impact:
      "Login and registration forms fail validation with 422 Unprocessable Entity error payloads.",
    suggestedFix: {
      summary: "Align JSON serialization field casing with the Pydantic AuthRequest schema.",
      steps: [
        "Update the login state object payload in frontend/src/services/auth.ts to serialize `username`.",
        "Add schema validation test asserting payload parity with OpenAPI specifications.",
      ],
      codeBefore: `const payload = {\n  userName: credentials.userName,\n  password: credentials.password,\n};`,
      codeAfter: `const payload = {\n  username: credentials.userName,\n  password: credentials.password,\n};`,
      language: "typescript",
    },
    meta: {
      integration: {
        frontendRef: "{ userName: string }",
        backendRef: "class AuthRequest(BaseModel): username: str",
      },
    },
  },
  {
    category: "integration",
    severity: "high",
    title: "Missing foreign key constraint on orders.user_id",
    shortDescription: "Relational integrity constraint missing in database migration.",
    filePath: "backend/alembic/versions/20240912_create_orders.py",
    lineStart: 21,
    lineEnd: 30,
    explanation:
      "The order model defines `user_id` as an unindexed integer column without a foreign key reference to `users.id`. Deleting or soft-deleting user records creates orphan transaction entries in the database.",
    impact:
      "Creates orphan records and causes JOIN queries in dashboard financial aggregates to silently drop orders.",
    suggestedFix: {
      summary: "Add ForeignKeyConstraint in SQLAlchemy model and generate migration.",
      steps: [
        "Add ForeignKey('users.id', ondelete='CASCADE') in backend/app/models/order.py.",
        "Generate and apply the Alembic revision: `alembic revision --autogenerate`.",
      ],
      codeBefore: `sa.Column('user_id', sa.Integer(), nullable=False)`,
      codeAfter: `sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)`,
      language: "python",
    },
    meta: {
      integration: {
        frontendRef: "types/order.ts (user: User)",
        backendRef: "models/order.py: Column(Integer)",
      },
    },
  },
  {
    category: "integration",
    severity: "medium",
    title: "Unbounded query parameter in search route",
    shortDescription: "Missing pagination limits allow unbounded memory consumption.",
    filePath: "backend/api/search.py",
    lineStart: 55,
    lineEnd: 62,
    explanation:
      "The search handler executes `SELECT * FROM items` without applying `LIMIT` or `OFFSET` clauses. When query results grow beyond a few thousand rows, database memory and response latency spike exponentially.",
    impact:
      "Vulnerable to resource exhaustion when searching common terms, risking 504 gateway timeouts.",
    suggestedFix: {
      summary: "Enforce default and maximum pagination parameters in request queries.",
      steps: [
        "Declare `limit: int = Query(20, le=100)` in route signature.",
        "Apply `.limit(limit).offset(offset)` in the ORM query chain.",
      ],
      codeBefore: `def search_items(q: str, db: Session = Depends(get_db)):\n  return db.query(Item).filter(Item.name.ilike(f"%{q}%")).all()`,
      codeAfter: `def search_items(q: str, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):\n  return db.query(Item).filter(Item.name.ilike(f"%{q}%")).limit(min(limit, 100)).offset(offset).all()`,
      language: "python",
    },
    meta: {
      integration: {
        frontendRef: "useInfiniteQuery('/api/search')",
        backendRef: "api/search.py: search_items()",
      },
    },
  },

  // Security Issues
  {
    category: "security",
    severity: "critical",
    title: "Hardcoded API key committed in config.js",
    shortDescription: "Sensitive third-party credential committed in plain text.",
    filePath: "backend/src/config/runtime.js",
    lineStart: 14,
    lineEnd: 17,
    explanation:
      "A production Stripe or OpenAI client secret is assigned directly as a string literal in source control. Once committed to git history, keys are visible to all repository collaborators and build artifacts.",
    impact:
      "Permits unauthorized third-party billing, secret scraping by bot networks, and quota exhaustion.",
    suggestedFix: {
      summary: "Move secret to environment variables and revoke the exposed key immediately.",
      steps: [
        "Revoke the existing API key in the provider console immediately.",
        "Reference the key via `process.env.STRIPE_SECRET_KEY`.",
        "Add `.env` and `.env.local` to `.gitignore`.",
      ],
      codeBefore: `export const STRIPE_KEY = "sk_live_51N8xL9K20948abcdef123456789";`,
      codeAfter: `export const STRIPE_KEY = process.env.STRIPE_SECRET_KEY || "";`,
      language: "javascript",
    },
    meta: {
      security: {
        cwe: "CWE-798: Use of Hard-coded Credentials",
        owaspCategory: "A07:2021-Identification and Authentication Failures",
      },
    },
  },
  {
    category: "security",
    severity: "high",
    title: "CORS allows all origins in staging and production",
    shortDescription: "Wildcard origin header permits arbitrary cross-origin requests.",
    filePath: "backend/src/main.py",
    lineStart: 31,
    lineEnd: 38,
    explanation:
      "The `CORSMiddleware` configuration defines `allow_origins=['*']` with credentials enabled. Any malicious third-party website visited by an authenticated user can perform authenticated requests against your API.",
    impact:
      "Enables Cross-Origin Resource Sharing bypasses, exposing sensitive tenant data to rogue sites.",
    suggestedFix: {
      summary:
        "Restrict allowed origins to trusted production domains specified in environment variables.",
      steps: [
        "Read allowed origins from `os.getenv('ALLOWED_HOSTS').split(',')`.",
        "Disallow wildcard origins when `allow_credentials=True`.",
      ],
      codeBefore: `app.add_middleware(\n  CORSMiddleware,\n  allow_origins=["*"],\n  allow_credentials=True,\n)`,
      codeAfter: `app.add_middleware(\n  CORSMiddleware,\n  allow_origins=settings.CORS_ORIGINS,\n  allow_credentials=True,\n)`,
      language: "python",
    },
    meta: {
      security: {
        cwe: "CWE-942: Overly Permissive CORS Policy",
        owaspCategory: "A01:2021-Broken Access Control",
      },
    },
  },
  {
    category: "security",
    severity: "high",
    title: "JWT secret read from hardcoded default fallback string",
    shortDescription: "Session token signature verification relies on static insecure secret.",
    filePath: "backend/app/core/security.py",
    lineStart: 12,
    lineEnd: 16,
    explanation:
      "The token generation utility utilizes `os.getenv('JWT_SECRET', 'secret123')`. In environments where the variable is unset, tokens are signed with a well-known trivial secret that can be forged offline.",
    impact:
      "Attackers can forge arbitrary administrative JWT tokens and bypass all authorization checks.",
    suggestedFix: {
      summary:
        "Throw an explicit runtime configuration error if JWT_SECRET is unset in production.",
      steps: [
        "Remove the fallback default 'secret123'.",
        "Add a startup validation check that prevents application boot without a cryptographically strong secret.",
      ],
      codeBefore: `JWT_SECRET = os.getenv("JWT_SECRET", "secret123")`,
      codeAfter: `JWT_SECRET = os.environ["JWT_SECRET"]  # Fails fast on startup if missing`,
      language: "python",
    },
    meta: {
      security: {
        cwe: "CWE-321: Use of Hard-coded Cryptographic Key",
        owaspCategory: "A02:2021-Cryptographic Failures",
      },
    },
  },
  {
    category: "security",
    severity: "medium",
    title: "Missing Content Security Policy (CSP) header",
    shortDescription: "No CSP response headers configured to mitigate XSS vectors.",
    filePath: "frontend/vercel.json",
    lineStart: 8,
    lineEnd: 15,
    explanation:
      "The web server headers configuration lacks a `Content-Security-Policy`. Inline scripts and untrusted script origins can execute without browser enforcement restrictions.",
    impact:
      "Increases vulnerability window to stored Cross-Site Scripting (XSS) and iframe clickjacking.",
    suggestedFix: {
      summary: "Inject standard security headers in the edge routing configuration.",
      steps: [
        "Define `Content-Security-Policy: default-src 'self'` in vercel.json or nginx headers.",
        "Add `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`.",
      ],
    },
    meta: {
      security: {
        cwe: "CWE-1021: Improper Restriction of Rendered UI Layers",
        owaspCategory: "A05:2021-Security Misconfiguration",
      },
    },
  },

  // Dependencies Issues
  {
    category: "dependencies",
    severity: "critical",
    title: "Vulnerable package axios with known Denial of Service CVE",
    shortDescription: "Unpinned HTTP client vulnerable to data-handling memory exhaustion.",
    filePath: "frontend/package.json",
    lineStart: 24,
    lineEnd: 24,
    explanation:
      "The project depends on `axios@0.21.1` which is vulnerable to Server-Side Request Forgery and prototype pollution when parsing malformed JSON response bodies. A public exploit vector exists.",
    impact:
      "Risk of client thread freezing and memory exhaustion on receiving adversarial HTTP responses.",
    suggestedFix: {
      summary: "Upgrade axios to >= 1.7.4 or replace with native Fetch API.",
      steps: [
        "Run `npm install axios@latest` in the frontend directory.",
        "Re-run test suite to verify interceptor compatibility.",
      ],
      codeBefore: `"axios": "^0.21.1"`,
      codeAfter: `"axios": "^1.7.9"`,
      language: "json",
    },
    meta: {
      dependencies: {
        packageName: "axios",
        currentVersion: "0.21.1",
        latestVersion: "1.7.9",
        cve: "CVE-2023-45857",
      },
    },
  },
  {
    category: "dependencies",
    severity: "high",
    title: "High severity prototype pollution in lodash",
    shortDescription: "Vulnerable lodash method allows arbitrary object property injection.",
    filePath: "package.json",
    lineStart: 32,
    lineEnd: 32,
    explanation:
      "The utility library `lodash@4.17.15` contains a prototype pollution vulnerability in `template` and `merge` helpers. Attackers can modify prototype properties via crafted JSON inputs.",
    impact:
      "Potential remote code execution or application state corruption via modified global object prototypes.",
    suggestedFix: {
      summary: "Upgrade lodash to 4.17.21 or migrate to native JavaScript utilities.",
      steps: [
        "Update dependency specification to `^4.17.21`.",
        "Execute `npm audit fix` to verify clean transitive graph.",
      ],
      codeBefore: `"lodash": "4.17.15"`,
      codeAfter: `"lodash": "^4.17.21"`,
      language: "json",
    },
    meta: {
      dependencies: {
        packageName: "lodash",
        currentVersion: "4.17.15",
        latestVersion: "4.17.21",
        cve: "CVE-2021-23337",
      },
    },
  },
  {
    category: "dependencies",
    severity: "medium",
    title: "Unused heavy dependency moment.js bundles full locales",
    shortDescription: "Legacy date library adds 450kB of uncompressed bundle weight.",
    filePath: "frontend/package.json",
    lineStart: 38,
    lineEnd: 38,
    explanation:
      "The bundle analysis indicates `moment.js` is imported in only two components, yet pulls in all worldwide localization tables into the production JavaScript chunk.",
    impact:
      "Significantly degrades First Contentful Paint (FCP) and mobile page loading performance.",
    suggestedFix: {
      summary: "Replace moment with lightweight date-fns or native Intl.DateTimeFormat.",
      steps: [
        "Replace moment calls with native `Intl.DateTimeFormat` or custom helpers.",
        "Uninstall moment via `npm remove moment`.",
      ],
    },
    meta: {
      dependencies: {
        packageName: "moment",
        currentVersion: "2.29.1",
        latestVersion: "2.30.1",
      },
    },
  },

  // Deployment Readiness Issues
  {
    category: "deployment",
    severity: "critical",
    title: "Missing DATABASE_URL environment variable in deploy config",
    shortDescription:
      "Container orchestrator startup will crash due to undefined connection string.",
    filePath: "docker-compose.prod.yml",
    lineStart: 18,
    lineEnd: 22,
    explanation:
      "The production deployment specification defines backend container dependencies but fails to map the `DATABASE_URL` environment variable. The backend application will crash upon its initial health check.",
    impact:
      "Prevents zero-downtime rolling updates and causes deployment orchestrator to reject the release.",
    suggestedFix: {
      summary: "Add DATABASE_URL to environment mapping in docker-compose.prod.yml.",
      steps: [
        "Map `DATABASE_URL: ${DATABASE_URL}` in the services.backend.environment block.",
        "Verify secret is populated in cloud secret manager.",
      ],
      codeBefore: `services:\n  backend:\n    image: mergex-backend:latest\n    ports:\n      - "8000:8000"`,
      codeAfter: `services:\n  backend:\n    image: mergex-backend:latest\n    environment:\n      - DATABASE_URL=\${DATABASE_URL}\n    ports:\n      - "8000:8000"`,
      language: "yaml",
    },
  },
  {
    category: "deployment",
    severity: "high",
    title: "Build command not configured for production environment",
    shortDescription: "Static site generator build step missing in hosting configuration.",
    filePath: "render.yaml",
    lineStart: 12,
    lineEnd: 15,
    explanation:
      "The hosting manifest specifies `publish: dist` but omits the `buildCommand: npm run build`. Without the build phase, the hosting provider serves an empty directory or outdated stale bundle.",
    impact: "Build pipeline deploys 404 placeholder pages instead of compiled application assets.",
    suggestedFix: {
      summary: "Specify the build command in the hosting service definition.",
      steps: [
        "Add `buildCommand: npm run build` to render.yaml or vercel.json.",
        "Ensure Node.js engine version is pinned to >= 20.x in package.json.",
      ],
    },
  },
  {
    category: "deployment",
    severity: "medium",
    title: "No dedicated HTTP health-check endpoint configured",
    shortDescription: "Orchestrator readiness check falls back to plain TCP ping.",
    filePath: "backend/app/main.py",
    lineStart: 45,
    lineEnd: 48,
    explanation:
      "The application lacks a `/health` or `/livez` route that verifies database connection pooling. The load balancer considers the container alive even when database sockets have deadlocked.",
    impact: "Traffic routes to degraded container instances during database maintenance outages.",
    suggestedFix: {
      summary: "Expose a /health route that actively validates DB session connectivity.",
      steps: [
        "Implement `@app.get('/health')` executing `SELECT 1` against the database.",
        "Update Docker HEALTHCHECK instruction to probe `http://localhost:8000/health`.",
      ],
      codeBefore: `# No health check endpoint defined`,
      codeAfter: `@app.get("/health")\ndef health_check(db: Session = Depends(get_db)):\n  db.execute(text("SELECT 1"))\n  return {"status": "healthy"}`,
      language: "python",
    },
  },
  {
    category: "deployment",
    severity: "low",
    title: "HTTPS redirect not enforced at web application layer",
    shortDescription: "HTTP plain text traffic accepted without automatic 301 upgrade.",
    filePath: "nginx.conf",
    lineStart: 5,
    lineEnd: 10,
    explanation:
      "The web server configuration binds to port 80 without a 301 Permanent Redirect to port 443. Users who type domain names without HTTPS prefix may transmit authentication tokens in plaintext.",
    impact: "Risk of unencrypted session traffic over public WiFi networks.",
    suggestedFix: {
      summary: "Add return 301 https://$host$request_uri; block for all port 80 servers.",
      steps: ["Configure redirect in nginx.conf or hosting provider SSL enforce toggle."],
    },
  },
];

/**
 * Deterministically generates 8 to 14 realistic issues for a project
 * seeded by project id, matching project.issueCounts and severity profiles.
 */
export function generateIssues(project: Project): Issue[] {
  const seed = hashCode(project.id);
  const rand = createPrng(seed);

  // Determine count between 8 and 14
  const targetCount = 8 + Math.floor(rand() * 7);

  // Shuffle templates deterministically
  const pool = [...TEMPLATES].sort(() => rand() - 0.5);
  const selected = pool.slice(0, Math.min(targetCount, pool.length));

  // If score is high (>80), convert critical issues to high/medium
  const isHighHealth = project.healthScore >= 80;

  return selected.map((template, idx) => {
    let severity = template.severity;
    if (isHighHealth && severity === "critical") {
      severity = "high";
    }

    const item: Issue = {
      id: `${project.id}_iss_${idx + 1}`,
      projectId: project.id,
      category: template.category,
      severity,
      status: "open",
      title: template.title,
      shortDescription: template.shortDescription,
      filePath: template.filePath,
      lineStart: template.lineStart,
      lineEnd: template.lineEnd,
      explanation: template.explanation,
      impact: template.impact,
      suggestedFix: template.suggestedFix,
      ...(template.meta ? { meta: template.meta } : {}),
    };
    return item;
  });
}

/**
 * Deterministically generates deployment readiness checklist items
 */
export function generateChecklist(project: Project): ChecklistItem[] {
  const seed = hashCode(project.id) + 42;
  const rand = createPrng(seed);

  const isHealthy = project.healthScore >= 75;

  return [
    {
      id: "chk-1",
      label: "Environment variables configured",
      status: isHealthy ? "pass" : rand() > 0.4 ? "warn" : "fail",
      detail: isHealthy
        ? "All required production secrets and database URIs are declared."
        : "DATABASE_URL or JWT_SECRET is missing from production env manifest.",
    },
    {
      id: "chk-2",
      label: "Production build succeeds",
      status: "pass",
      detail: "Clean zero-error compile via TypeScript and Vite bundler.",
    },
    {
      id: "chk-3",
      label: "Database schema migrations current",
      status: isHealthy ? "pass" : "warn",
      detail: isHealthy
        ? "Alembic and Prisma schemas align with target database state."
        : "Pending migrations detected that have not yet been applied to staging.",
    },
    {
      id: "chk-4",
      label: "CORS policies restricted",
      status: isHealthy ? "pass" : "fail",
      detail: isHealthy
        ? "Explicit origin allowlist enforced; wildcards disabled."
        : "Wildcard origin '*' allows unauthorized cross-site requests.",
    },
    {
      id: "chk-5",
      label: "Zero exposed secrets in source",
      status: isHealthy ? "pass" : "warn",
      detail: isHealthy
        ? "AST secret scanner detected no embedded API keys or credentials."
        : "Potential secret pattern found in runtime configuration file.",
    },
    {
      id: "chk-6",
      label: "Health check probe endpoint live",
      status: isHealthy ? "pass" : "fail",
      detail: isHealthy
        ? "Route `/health` responds with HTTP 200 and validates DB socket."
        : "Missing dedicated HTTP readiness probe endpoint.",
    },
    {
      id: "chk-7",
      label: "Dockerfile containerization verified",
      status: "pass",
      detail: "Multi-stage Dockerfile builds and runs unprivileged non-root user.",
    },
    {
      id: "chk-8",
      label: "HTTPS redirects enforced",
      status: "pass",
      detail: "Port 80 traffic automatically issues 301 redirect to port 443.",
    },
    {
      id: "chk-9",
      label: "Structured JSON logging configured",
      status: rand() > 0.3 ? "pass" : "warn",
      detail: "Log aggregators ingest formatted JSON entries with request trace IDs.",
    },
  ];
}

/**
 * Extracts top priority issues directly from generateIssues to ensure
 * Overview top issues and tabs are 100% synchronized.
 */
export function syncProjectTopIssues(project: Project): PriorityIssue[] {
  const issues = generateIssues(project);
  const severityOrder: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3,
  };

  return issues
    .sort((a, b) => (severityOrder[a.severity] ?? 99) - (severityOrder[b.severity] ?? 99))
    .slice(0, 4)
    .map((iss) => ({
      id: iss.id,
      title: iss.title,
      category: iss.category,
      severity: iss.severity,
      filePath: iss.filePath,
      shortDescription: iss.shortDescription,
    }));
}
